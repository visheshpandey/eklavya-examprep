"""Targeted question generation (LLM, structured JSON) with validation, one retry, a per-concept cache and background pre-generation.

The LLM only writes the question; WHICH concept and difficulty to ask is decided by the deterministic learner model.
"""
from __future__ import annotations

import logging
import random
import threading
from concurrent.futures import Future, ThreadPoolExecutor

from pydantic import BaseModel, ValidationError, field_validator, model_validator

from app.ai import gemini
from app.ps02 import content, llm

log = logging.getLogger(__name__)
GEN_DEADLINE_S = 12.0
_pool_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="ps02-gen")
_cache: dict[str, list[dict]] = {}            # concept_id -> recently generated, validated questions (fallback pool)
_prefetch: dict[int, tuple[tuple[str, int], Future]] = {}   # student_id -> ((concept, difficulty), future)
_lock = threading.Lock()


class GeneratedQuestion(BaseModel):
    stem: str
    options: list[str]
    correct_index: int
    distractor_misconceptions: dict[str, str] = {}
    difficulty: int = 2
    concept_id: str = ""
    explanation: str = ""
    used_notes: bool = False

    @field_validator("options")
    @classmethod
    def four_distinct(cls, v):
        v = [str(o).strip() for o in v]
        if len(v) != 4 or len(set(v)) != 4 or any(not o for o in v):
            raise ValueError("need exactly 4 distinct non-empty options")
        return v

    @field_validator("correct_index")
    @classmethod
    def in_range(cls, v):
        if not 0 <= int(v) <= 3:
            raise ValueError("correct_index out of range")
        return int(v)

    @model_validator(mode="after")
    def clean_map(self):
        valid = content.misconceptions()
        wrong = {str(i) for i in range(4)} - {str(self.correct_index)}
        self.distractor_misconceptions = {str(k): (v if v in valid else "MC_UNKNOWN") for k, v in self.distractor_misconceptions.items() if str(k) in wrong}
        for k in wrong:
            self.distractor_misconceptions.setdefault(k, "MC_UNKNOWN")
        return self


SYSTEM = """You write one multiple-choice physics question for CBSE Class 10 students (rationalised syllabus).
Rules: CBSE Class 10 level; sensible numeric values and correct units; exactly one correct option; four distinct options;
every wrong option must be deliberately built from one of the listed misconceptions (a student holding that misconception would pick it),
otherwise map it to MC_UNKNOWN. Do not repeat the stems already used. Plain language, no markdown. Write plain text only: no LaTeX and no $ signs; write maths with Unicode symbols (Ω, ², ×, ₁, ÷).
Return ONLY JSON: {"stem": str, "options": [4 strings], "correct_index": 0-3, "distractor_misconceptions": {"<wrong option index>": "<misconception id>"},
"difficulty": 1-3, "concept_id": str, "explanation": str (1-2 sentences, why the right answer is right)}.
Difficulty 1 = direct recall or one step; 2 = a short calculation or a comparison; 3 = multi-step or a tricky case."""


def _prompt(concept_id: str, difficulty: int, active_mcs: list[str], recent_stems: list[str], notes: dict | None = None, target_mc: str | None = None, trap: bool = False) -> str:
    c = content.concepts()[concept_id]
    mcs = content.misconceptions()
    pool = [m for m in mcs.values() if concept_id in m["concept_ids"]]
    pool += [mcs[i] for i in active_mcs if i in mcs and mcs[i] not in pool]
    listing = "\n".join(f'- {m["id"]}: {m["description"]}' for m in pool) or "- (none known; use MC_UNKNOWN)"
    formulas = ", ".join(c["key_formulas"]) or "none"
    avoid = "\n".join(f"- {s}" for s in recent_stems[:8]) or "- (none)"
    aim = (f"\nTARGET: this question must test the misconception {target_mc}: {mcs[target_mc]['description']} At least TWO of the three wrong options must be "
           f"built from it and mapped to {target_mc} in distractor_misconceptions; set the scenario so a student holding this belief would be tempted by them.\n") if target_mc in mcs else ""
    if trap and aim:
        aim += ("This is a VERIFICATION TRAP for a student who was taught the right idea recently: use a NEW scenario (not the usual textbook example); the trap option must be "
                "exactly what someone who STILL holds the belief would choose or compute, and the correct option must look unattractive to them. Do not hint at the misconception.\n")
    own = (f"\nThe student's OWN NOTES on this topic (set used_notes true and let the question's scenario and the explanation follow these notes when they fit, in the notes' terms; "
           f"otherwise set used_notes false):\n{notes['text']}\n") if notes else ""
    return (f"Concept {concept_id}: {c['name']} ({c['chapter']}). {c['description']}\nKey formulas: {formulas}\n{own}"
            f"Target difficulty: {difficulty}\nMisconceptions to build wrong options from:\n{listing}\n{aim}"
            f"The student currently holds: {', '.join(active_mcs) or 'nothing recorded'}\nStems already used (do not repeat):\n{avoid}")


NOTE_OVERLAP = 0.2   # share of the question's content words that also appear in the retrieved passage


def _overlaps_notes(question: dict, passage: str) -> bool:
    """The model does not always set used_notes; a question whose stem and explanation share real vocabulary with the passage is grounded in it."""
    from app.domain import retrieval
    words = {w for w in retrieval.tokenize(f"{question['stem']} {question.get('explanation', '')}") if len(w) > 3}
    return bool(words) and len(words & set(retrieval.tokenize(passage))) / len(words) >= NOTE_OVERLAP


def _shuffle(q: GeneratedQuestion) -> dict:
    """The model likes putting the answer in one slot: shuffle the options and remap the answer and the misconception map."""
    order = list(range(4))
    random.shuffle(order)
    options = [q.options[i] for i in order]
    new_correct = order.index(q.correct_index)
    mapping = {str(order.index(int(k))): v for k, v in q.distractor_misconceptions.items()}
    return {"stem": q.stem.strip(), "options": options, "correct_index": new_correct, "distractor_misconceptions": mapping,
            "difficulty": q.difficulty, "concept_id": q.concept_id, "explanation": q.explanation.strip()}


def generate(concept_id: str, difficulty: int, active_mcs: list[str] | None = None, recent_stems: list[str] | None = None, notes: dict | None = None, target_mc: str | None = None, trap: bool = False) -> dict:
    """Return a validated question dict. Tries the LLM twice; on failure falls back to a cached or hand-written question (``source`` says which)."""
    active_mcs, recent_stems = active_mcs or [], recent_stems or []
    seen = {s.strip() for s in recent_stems} | {q["stem"].strip() for q in content.diagnostic()}   # never repeat a stem the student saw, nor a diagnostic one
    target_mc = target_mc if target_mc in content.misconceptions() and target_mc != "MC_UNKNOWN" else None
    prompt = _prompt(concept_id, difficulty, active_mcs, recent_stems, notes, target_mc, trap)
    for attempt in (1, 2):
        try:
            raw = llm.hedged_json(SYSTEM, prompt, ("stem", "options", "correct_index"), 0.8 if attempt == 1 else 0.4, deadline_s=GEN_DEADLINE_S, hedge_after_s=5.0)
            q = GeneratedQuestion(**raw)
            q.concept_id, q.difficulty = concept_id, difficulty   # never trust the model's own difficulty label: the planner decided it
            if q.stem.strip() in seen:
                continue
            if target_mc and target_mc not in q.distractor_misconceptions.values():
                continue   # asked to aim at the misconception but no option is built from it: try once more
            out = _shuffle(q)
            out["source"] = "ai"
            out["target_mc"] = target_mc
            out["note"] = notes["citation"] if (notes and (q.used_notes or _overlaps_notes(out, notes["text"]))) else None   # cite only when the model used the passage or the wording clearly follows it
            with _lock:
                _cache.setdefault(concept_id, []).append(out)
                _cache[concept_id] = _cache[concept_id][-6:]
            return out
        except (ValidationError, ValueError, TypeError, KeyError, gemini.LLMError) as exc:
            log.warning("Question generation attempt %d failed for %s: %s", attempt, concept_id, str(exc)[:200])
    return fallback(concept_id, difficulty, recent_stems)


def fallback(concept_id: str, difficulty: int, recent_stems: list[str]) -> dict:
    """A previously generated question for the concept, else a hand-written diagnostic one (concept, then prerequisites, then anything)."""
    with _lock:
        cached = [q for q in _cache.get(concept_id, []) if q["stem"] not in recent_stems]
    if cached:
        return {**random.choice(cached), "source": "cache"}
    bank = content.diagnostic()
    near = [concept_id, *sorted(content.ancestors(concept_id))]
    for cid in near:
        options = [q for q in bank if q["concept_id"] == cid and q["stem"] not in recent_stems]
        if options:
            q = min(options, key=lambda x: abs(x["difficulty"] - difficulty))
            return {**{k: q[k] for k in ("stem", "options", "correct_index", "distractor_misconceptions", "difficulty", "explanation")},
                    "concept_id": q["concept_id"], "source": "bank"}
    q = random.choice(bank)
    return {**{k: q[k] for k in ("stem", "options", "correct_index", "distractor_misconceptions", "difficulty", "explanation")},
            "concept_id": q["concept_id"], "source": "bank"}


# ---- background pre-generation: start the next question while the student is answering this one
def prefetch(student_id: int, concept_id: str, difficulty: int, active_mcs: list[str], recent_stems: list[str], notes: dict | None = None) -> None:
    key = (concept_id, difficulty)
    with _lock:
        existing = _prefetch.get(student_id)
        if existing and existing[0] == key:
            return
        _prefetch[student_id] = (key, _pool_executor.submit(generate, concept_id, difficulty, active_mcs, recent_stems, notes))


def clear_prefetch(student_id: int | None = None) -> None:
    """Forget pre-generated questions (all of them, or one student's). Called when notes change, so no stale question without a citation is served."""
    with _lock:
        if student_id is None:
            _prefetch.clear()
        else:
            _prefetch.pop(student_id, None)


def take_prefetched(student_id: int, concept_id: str, difficulty: int, wait_seconds: float = 12.0) -> dict | None:
    """The pre-generated question if it matches what is wanted now (waits briefly if still running), else None."""
    with _lock:
        item = _prefetch.get(student_id)
    if not item or item[0] != (concept_id, difficulty):
        return None
    try:
        result = item[1].result(timeout=wait_seconds)
    except Exception:  # noqa: BLE001 - slow or failed: the caller generates directly / falls back
        return None
    with _lock:
        if _prefetch.get(student_id) is item:
            del _prefetch[student_id]
    return result
