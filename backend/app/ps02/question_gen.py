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
from app.ps02 import content

log = logging.getLogger(__name__)
GEN_TIMEOUT_MS = 15000
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
otherwise map it to MC_UNKNOWN. Do not repeat the stems already used. Plain language, no markdown.
Return ONLY JSON: {"stem": str, "options": [4 strings], "correct_index": 0-3, "distractor_misconceptions": {"<wrong option index>": "<misconception id>"},
"difficulty": 1-3, "concept_id": str, "explanation": str (1-2 sentences, why the right answer is right)}.
Difficulty 1 = direct recall or one step; 2 = a short calculation or a comparison; 3 = multi-step or a tricky case."""


def _prompt(concept_id: str, difficulty: int, active_mcs: list[str], recent_stems: list[str]) -> str:
    c = content.concepts()[concept_id]
    mcs = content.misconceptions()
    pool = [m for m in mcs.values() if concept_id in m["concept_ids"]]
    pool += [mcs[i] for i in active_mcs if i in mcs and mcs[i] not in pool]
    listing = "\n".join(f'- {m["id"]}: {m["description"]}' for m in pool) or "- (none known; use MC_UNKNOWN)"
    formulas = ", ".join(c["key_formulas"]) or "none"
    avoid = "\n".join(f"- {s}" for s in recent_stems[-5:]) or "- (none)"
    return (f"Concept {concept_id}: {c['name']} ({c['chapter']}). {c['description']}\nKey formulas: {formulas}\n"
            f"Target difficulty: {difficulty}\nMisconceptions to build wrong options from:\n{listing}\n"
            f"The student currently holds: {', '.join(active_mcs) or 'nothing recorded'}\nStems already used (do not repeat):\n{avoid}")


def _shuffle(q: GeneratedQuestion) -> dict:
    """The model likes putting the answer in one slot: shuffle the options and remap the answer and the misconception map."""
    order = list(range(4))
    random.shuffle(order)
    options = [q.options[i] for i in order]
    new_correct = order.index(q.correct_index)
    mapping = {str(order.index(int(k))): v for k, v in q.distractor_misconceptions.items()}
    return {"stem": q.stem.strip(), "options": options, "correct_index": new_correct, "distractor_misconceptions": mapping,
            "difficulty": q.difficulty, "concept_id": q.concept_id, "explanation": q.explanation.strip()}


def generate(concept_id: str, difficulty: int, active_mcs: list[str] | None = None, recent_stems: list[str] | None = None) -> dict:
    """Return a validated question dict. Tries the LLM twice; on failure falls back to a cached or hand-written question (``source`` says which)."""
    active_mcs, recent_stems = active_mcs or [], recent_stems or []
    prompt = _prompt(concept_id, difficulty, active_mcs, recent_stems)
    for attempt in (1, 2):
        try:
            raw = gemini.llm_json(SYSTEM, prompt, required_keys=("stem", "options", "correct_index"), temperature=0.8 if attempt == 1 else 0.4,
                                  timeout_ms=GEN_TIMEOUT_MS)
            q = GeneratedQuestion(**raw)
            q.concept_id, q.difficulty = concept_id, max(1, min(3, int(q.difficulty or difficulty)))
            if q.stem.strip() in recent_stems:
                continue
            out = _shuffle(q)
            out["source"] = "ai"
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
def prefetch(student_id: int, concept_id: str, difficulty: int, active_mcs: list[str], recent_stems: list[str]) -> None:
    key = (concept_id, difficulty)
    with _lock:
        existing = _prefetch.get(student_id)
        if existing and existing[0] == key:
            return
        _prefetch[student_id] = (key, _pool_executor.submit(generate, concept_id, difficulty, active_mcs, recent_stems))


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
