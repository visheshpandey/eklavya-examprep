"""Misconception detection from the student's REASONING (voice transcript or text), not just the wrong option.

The distractor's mapped misconception is only a prior; the LLM reads what the student actually said and decides. If the LLM is
unavailable, a keyword matcher over each misconception's telltale phrases keeps the flow alive.
"""
from __future__ import annotations

import logging
import re

from pydantic import BaseModel, ValidationError, field_validator

from app.ai import gemini
from app.ps02 import content, llm

log = logging.getLogger(__name__)
CLASSIFY_DEADLINE_S = 8.0

SYSTEM = """You are a physics teacher diagnosing WHY a CBSE Class 10 student gave an answer. The student explained their thinking in English, Hindi or
Hinglish (possibly a speech transcript with errors). Decide which ONE known misconception, if any, their reasoning shows.
Rules: pick only from the candidate ids given (or MC_UNKNOWN if the reasoning is wrong but matches none).
When you answer MC_UNKNOWN you must NOT be generic: put a specific 3-6 word label for THIS error in new_label (e.g. "Divided instead of multiplied"), quote the faulty step in evidence, and explain exactly that step in the feedback. Formula slips (a formula turned upside down, wrong rearrangement) and unit or prefix errors (mA vs A, cm vs m) are covered by candidates when listed: prefer them.
fix = one sentence stating the correct idea for exactly this error.
The 'prior' misconception comes from the option they picked and is only a hint: trust the reasoning text over it.
If the reasoning is actually correct and the wrong pick was a slip (misread option, arithmetic or tapped wrong), set is_careless_error true and misconception_id "NONE".
If the answer was correct, set reasoning_sound false only when the reasoning is wrong or shows a lucky guess.
evidence = a short quote or paraphrase of what the student said. confidence is 0 to 1.
feedback_hinglish: friendly Hinglish (Roman script), 2-3 short sentences: name the idea they mixed up, why it is wrong, and ONE intuitive analogy. Use the analogy given for the chosen misconception (put it in your own simple words); never invent a new analogy, and never say anything physically wrong.
feedback_english: the same in simple English. Never be harsh.
Return ONLY JSON: {"misconception_id": str, "confidence": number, "evidence": str, "is_careless_error": bool, "reasoning_sound": bool,
"new_label": str, "fix": str, "feedback_hinglish": str, "feedback_english": str}"""


class Diagnosis(BaseModel):
    misconception_id: str = "MC_UNKNOWN"
    confidence: float = 0.5
    evidence: str = ""
    is_careless_error: bool = False
    reasoning_sound: bool = True
    new_label: str = ""
    fix: str = ""
    feedback_hinglish: str = ""
    feedback_english: str = ""

    @field_validator("confidence")
    @classmethod
    def clamp(cls, v):
        return max(0.0, min(1.0, float(v)))


def candidates(concept_id: str) -> list[dict]:
    """Misconceptions attached to the concept or any prerequisite (a wrong answer often traces back to a prerequisite)."""
    mcs = content.misconceptions()
    scope = {concept_id} | content.ancestors(concept_id)
    return [m for m in mcs.values() if m["id"] != "MC_UNKNOWN" and set(m["concept_ids"]) & scope]


def _prompt(question: dict, chosen_index: int, reasoning: str, concept_id: str, prior: str | None) -> str:
    opts = "\n".join(f"  {i}. {o}" for i, o in enumerate(question["options"]))
    cand = "\n".join(f'- {m["id"]} ({m["label"]}): {m["description"]}; e.g. {"; ".join(m["telltale_phrases"][:3])}. Correct idea: {m["correction"]} Analogy: {m["analogy"]}' for m in candidates(concept_id))
    correct = question["correct_index"]
    return (f"Question: {question['stem']}\nOptions:\n{opts}\nCorrect: {correct}. {question['options'][correct]}\n"
            f"Student chose: {chosen_index}. {question['options'][chosen_index]} ({'correct' if chosen_index == correct else 'wrong'})\n"
            f"Prior (from the chosen option): {prior or 'none'}\nStudent's reasoning: \"{reasoning}\"\nCandidate misconceptions:\n{cand}")


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def heuristic(question: dict, chosen_index: int, reasoning: str, concept_id: str, prior: str | None) -> Diagnosis:
    """No-LLM fallback: score each candidate by telltale-phrase overlap with the reasoning; otherwise lean on the distractor prior."""
    said = _words(reasoning)
    best, best_score = None, 0.0
    for m in candidates(concept_id):
        for phrase in m["telltale_phrases"]:
            pw = _words(phrase)
            if pw:
                score = len(pw & said) / len(pw)
                if score > best_score:
                    best, best_score = m, score
    if best and best_score >= 0.6:
        conf, mc = min(0.85, 0.5 + best_score / 2), best
    elif prior and prior != "MC_UNKNOWN" and prior in content.misconceptions():
        conf, mc = 0.45, content.misconceptions()[prior]
    else:
        # still specific: name the actual question's right answer and its worked explanation, not a generic "revise the definition"
        chosen, right = question["options"][chosen_index], question["options"][question["correct_index"]]
        why = question.get("explanation", "")
        return Diagnosis(misconception_id="MC_UNKNOWN", confidence=0.3, evidence=reasoning[:120], new_label="Working differs from the answer", fix=why,
                         feedback_english=f"You picked “{chosen}”, but the answer is “{right}”. {why}".strip(),
                         feedback_hinglish=f"Aapne “{chosen}” chuna, par sahi jawab “{right}” hai. Dekhiye: {why}".strip())
    return Diagnosis(misconception_id=mc["id"], confidence=conf, evidence=reasoning[:120],
                     feedback_english=f"{mc['correction']} Think of it like this: {mc['analogy']}".strip(),
                     feedback_hinglish=f"{mc['label']}: {mc['correction']} {mc['analogy']}".strip())


def classify(question: dict, chosen_index: int, reasoning: str, concept_id: str, prior: str | None = None) -> dict:
    """Return the diagnosis plus the misconception's catalogue entry. ``source`` is 'ai' or 'heuristic'."""
    mcs = content.misconceptions()
    allowed = {m["id"] for m in candidates(concept_id)} | {"MC_UNKNOWN", "NONE"}
    source, diag = "ai", None
    try:
        raw = llm.hedged_json(SYSTEM, _prompt(question, chosen_index, reasoning, concept_id, prior), ("misconception_id",), 0.2, deadline_s=CLASSIFY_DEADLINE_S)   # past 8 s: keyword-matcher answer
        diag = Diagnosis(**raw)
        if diag.misconception_id not in allowed:
            diag.misconception_id = "MC_UNKNOWN"
        if diag.is_careless_error:
            diag.misconception_id = "NONE"
    except (ValidationError, ValueError, TypeError, gemini.LLMError) as exc:
        log.warning("Misconception classifier fell back to heuristic: %s", str(exc)[:200])
    if diag is None:
        source, diag = "heuristic", heuristic(question, chosen_index, reasoning, concept_id, prior)
    entry = mcs.get(diag.misconception_id)
    if entry and not diag.feedback_english:
        diag.feedback_english = f"{entry['correction']} {entry['analogy']}".strip()
    if entry and not diag.feedback_hinglish:
        diag.feedback_hinglish = diag.feedback_english
    out = diag.model_dump()
    specific = diag.new_label if diag.misconception_id == "MC_UNKNOWN" and diag.new_label else None   # an unknown error keeps its own specific label, not the catalogue's generic one
    out.update({"source": source, "label": specific or (entry["label"] if entry else "Needs a closer look"),
                "correction": entry["correction"] if entry else "", "analogy": entry["analogy"] if entry else ""})
    return out
