"""📸 Snap your notebook: read a photo of the student's handwritten working, find the FIRST wrong line, name the misconception, and feed it into the
learner model exactly like spoken reasoning (BKT, SM-2, student_misconceptions, teacher dashboard).

The model reads and judges; plain code validates its JSON, decides what changes in the learner model, and falls back to a prepared reading for
the two built-in samples so the demo and the Judge tour never depend on the camera or on Gemini being up.
"""
from __future__ import annotations

import io
import json
import logging

from pydantic import BaseModel, ValidationError, field_validator

from app import db
from app.ai import gemini
from app.ps02 import content, doubts, learner_model as lm, llm_vision, misconception, service

log = logging.getLogger(__name__)
READ_DEADLINE_S = 18.0
SAMPLE_DEADLINE_S = 14.0
MAX_SIDE = 1600
CONFIDENCE = {"high": 0.9, "medium": 0.65, "low": 0.4}
NOTEBOOK_NUDGE_WEIGHT = 0.2          # a notebook error found OUTSIDE a practice question: a push toward "does not know" (a doubt uses 0.15)

SYSTEM = """You read a photo of a CBSE Class 10 student's HANDWRITTEN physics working. Be careful and honest.
1. If you cannot read it clearly (blurry, too dark, cut off, not a notebook page, no working shown), return {"readable": false} and nothing else.
2. Transcribe every written line of the WORKING (the student's own steps, including the final answer line) as one short step, in order, as plain text. Use symbols like ×, ÷, Ω, ², ₁. No LaTeX. Do not transcribe the printed question.
3. Compare with the correct physics. first_wrong_step = the 0-based index of the FIRST line that is wrong (a wrong formula, a unit not converted, a wrong number); first_wrong_line = the EXACT text of that same step as you transcribed it. Use null for both if every line is correct.
4. error = ONE short sentence naming what is wrong on that line, e.g. "mA was not converted to A: you used 200 instead of 0.2 A".
5. misconception_id: pick ONE id from the candidate list, MC_UNKNOWN if the error matches none (then give new_label, 3-6 words), or NONE if the working is correct. is_careless_error = true only for a pure arithmetic or copying slip.
6. feedback_hinglish (friendly Hinglish in Roman script) and feedback_english: two short sentences each that quote the wrong line (for example “Q = I / t”) and say why. Do NOT write line numbers (the app adds them). Plain text, no LaTeX.
Return ONLY JSON: {"readable": bool, "transcribed_steps": [str], "first_wrong_step": int|null, "first_wrong_line": str|null, "error": str, "misconception_id": str, "confidence": "high|medium|low",
"is_careless_error": bool, "new_label": str, "feedback_hinglish": str, "feedback_english": str}"""


class Reading(BaseModel):
    readable: bool = True
    transcribed_steps: list[str] = []
    first_wrong_step: int | None = None
    first_wrong_line: str | None = None
    error: str = ""
    misconception_id: str = "MC_UNKNOWN"
    confidence: str = "medium"
    is_careless_error: bool = False
    new_label: str = ""
    feedback_hinglish: str = ""
    feedback_english: str = ""

    @field_validator("transcribed_steps")
    @classmethod
    def clean_steps(cls, v):
        return [str(s).strip()[:160] for s in v if str(s).strip()][:12]

    @field_validator("confidence")
    @classmethod
    def valid_confidence(cls, v):
        v = str(v).lower().strip()
        return v if v in CONFIDENCE else "medium"


# ------------------------------------------------------------------ samples
def samples() -> list[dict]:
    return content._load("notebook_samples.json")["samples"]


def sample(sample_id: str) -> dict | None:
    return next((s for s in samples() if s["id"] == sample_id), None)


def public_samples() -> list[dict]:
    return [{"id": s["id"], "title": s["title"], "subtitle": s["subtitle"], "image": s["image"], "question": {"stem": s["question"]["stem"], "options": s["question"]["options"]}} for s in samples()]


# ------------------------------------------------------------------ the photo
def prepare_image(data: bytes) -> tuple[bytes, str]:
    """Shrink big phone photos (faster, cheaper reads) and normalise to JPEG. Raises ValueError if it is not an image."""
    from PIL import Image, ImageOps
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
    except Exception as exc:  # noqa: BLE001 - anything unreadable is "not an image"
        raise ValueError("not an image") from exc
    img = img.convert("RGB")
    if max(img.size) > MAX_SIDE:
        img.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=85)
    return out.getvalue(), "image/jpeg"


# ------------------------------------------------------------------ reading
def _prompt(question: dict | None, concept_id: str | None, language: str) -> str:
    if question:
        correct = question["options"][question["correct_index"]]
        task = (f"Question: {question['stem']}\nOptions: " + " | ".join(f"{'ABCD'[i]}. {o}" for i, o in enumerate(question["options"]))
                + f"\nThe correct answer: {correct}\nWhat the correct working should show: {question.get('explanation', '')}")
    else:
        task = "No question was given: judge the working on its own physics."
    cands = misconception.candidates(concept_id) if concept_id else [m for m in content.misconceptions().values() if m["id"] != "MC_UNKNOWN"]
    listing = "\n".join(f"- {m['id']}: {m['description']}" for m in cands)
    return f"{task}\nLanguage of the student: {language}\nCandidate misconceptions:\n{listing}"


def _norm(text: str) -> str:
    return "".join(ch for ch in str(text).lower().replace("x", "×").replace("*", "×") if not ch.isspace())


def _match_line(line: str | None, steps: list[str]) -> int | None:
    """Index of the transcribed step that best matches the quoted wrong line (None when it matches none well)."""
    if not line or not steps:
        return None
    from difflib import SequenceMatcher
    scores = [SequenceMatcher(None, _norm(line), _norm(s)).ratio() for s in steps]
    best = max(range(len(steps)), key=scores.__getitem__)
    return best if scores[best] >= 0.85 else None


def read(image: bytes, mime: str, question: dict | None, concept_id: str | None, language: str, deadline_s: float = READ_DEADLINE_S) -> Reading:
    """Vision -> validated Reading. Raises LLMError when the model cannot be reached in time."""
    raw = llm_vision.hedged_vision_json(SYSTEM, _prompt(question, concept_id, language), image, mime, ("readable",), deadline_s=deadline_s)
    reading = Reading(**raw)
    if reading.readable and not reading.transcribed_steps:
        reading.readable = False                                  # "readable" with nothing transcribed is not a reading
    by_text = _match_line(reading.first_wrong_line, reading.transcribed_steps)
    if by_text is not None:
        reading.first_wrong_step = by_text          # the quoted text beats a bare index: models sometimes miscount
    if reading.first_wrong_step is not None and not 0 <= reading.first_wrong_step < len(reading.transcribed_steps):
        reading.first_wrong_step = None
    allowed = {m["id"] for m in (misconception.candidates(concept_id) if concept_id else content.misconceptions().values())} | {"MC_UNKNOWN", "NONE"}
    if reading.misconception_id not in allowed:
        reading.misconception_id = "MC_UNKNOWN"
    return reading


def _diagnosis(r: Reading, attempt_correct: bool | None, language: str) -> dict:
    """The Reading as the same diagnosis dict that spoken reasoning produces, so everything downstream is shared."""
    wrong = r.first_wrong_step is not None
    careless = r.is_careless_error or (attempt_correct is False and not wrong)     # right working but a wrong pick: a slip
    mc = "NONE" if (careless or not wrong) else r.misconception_id
    line = f"line {r.first_wrong_step + 1}: {r.transcribed_steps[r.first_wrong_step]}" if wrong else ""
    diag = misconception.Diagnosis(
        misconception_id=mc, confidence=CONFIDENCE[r.confidence], evidence=(line if wrong else "the written working is correct")[:240],
        is_careless_error=careless, reasoning_sound=not wrong, new_label=r.new_label, fix=r.error,
        feedback_hinglish=r.feedback_hinglish, feedback_english=r.feedback_english)
    return misconception._finish(diag, "notebook", language)


def _notebook_block(r: Reading, source: str) -> dict:
    return {"steps": r.transcribed_steps, "first_wrong_step": r.first_wrong_step, "error": r.error, "confidence": r.confidence, "source": source}


# ------------------------------------------------------------------ entry points
def analyse(student_id: int, image: bytes | None, *, attempt_id: int | None = None, sample_id: str | None = None, concept_id: str | None = None,
            language: str = "hinglish") -> dict:
    """Read the photo. With an attempt (a practice answer) or a built-in sample, it is applied like spoken reasoning; otherwise (Ask) it is logged like a doubt."""
    smp = sample(sample_id) if sample_id else None
    if sample_id and not smp:
        raise KeyError("unknown sample")
    question, attempt = None, None
    if smp:
        question = smp["question"]
        concept_id = question["concept_id"]
        res = service.record_answer(student_id, question, smp["picked"], mode="notebook")     # the sample is a real wrong answer in the learner model
        attempt = db.one("SELECT * FROM attempts WHERE id=? AND student_id=?", (res["attempt_id"], student_id))
    elif attempt_id is not None:
        attempt = db.one("SELECT * FROM attempts WHERE id=? AND student_id=?", (attempt_id, student_id))
        if not attempt:
            raise KeyError("attempt not found")
        question, concept_id = json.loads(attempt["question_json"]), attempt["concept_id"]

    reading, source = None, "ai"
    if image is not None and not smp:      # a built-in sample page is shown from its prepared reading at once
        try:
            reading = read(image, "image/jpeg", question, concept_id, language, SAMPLE_DEADLINE_S if smp else READ_DEADLINE_S)
        except (ValidationError, ValueError, TypeError, gemini.LLMError) as exc:
            log.warning("Notebook read failed: %s", str(exc)[:200])
            if not smp:
                return {"readable": False, "reason": "busy", "message": "The handwriting reader is busy. Please try again, or type your reasoning."}
    if smp and (reading is None or not reading.readable):
        reading, source = Reading(**smp["canned"]), "sample-prepared"          # the demo never depends on the camera or on Gemini
    if reading is None or not reading.readable:
        return {"readable": False, "reason": "unclear", "message": "Couldn't read that clearly. Try again with good light, or type your reasoning."}

    nb = _notebook_block(reading, source)
    if attempt:
        diag = _diagnosis(reading, bool(attempt["correct"]), language)
        said = "📸 " + " | ".join(reading.transcribed_steps)
        result = service.apply_reasoning(student_id, attempt["id"], said, mode="notebook", diag=diag, language=language)
        return {"readable": True, "notebook": nb, **result, **({"sample": {"id": smp["id"], "stem": question["stem"], "options": question["options"], "picked": smp["picked"], "image": smp["image"],
                                                                         "correct_index": question["correct_index"]}} if smp else {})}
    return _log_as_doubt(student_id, reading, nb, concept_id, language)


def _log_as_doubt(student_id: int, reading: Reading, nb: dict, hint: str | None, language: str) -> dict:
    """A photo sent from Ask: no question to grade against, so find the concept, log the misconception, and nudge mastery gently."""
    wrong = reading.first_wrong_step is not None
    diag = _diagnosis(reading, None, language)
    tag = doubts.tag(f"{reading.error} {' '.join(reading.transcribed_steps)}", hint)
    cid = tag["concept_id"] or hint
    mc_id = diag["misconception_id"] if wrong and diag["misconception_id"] not in ("NONE", "MC_UNKNOWN") else None
    changes = []
    if mc_id and cid:
        service._note_misconception(student_id, mc_id, diag["evidence"], source="notebook")
        mastery = lm.get_mastery(student_id)
        before = mastery[cid]
        after = round(lm.bkt_update(before, False, weight=NOTEBOOK_NUDGE_WEIGHT), 4)
        if after < before:
            lm.save_mastery(student_id, {cid: after})
            changes.append({"concept_id": cid, "name": content.concepts()[cid]["name"], "before": round(before, 4), "after": after, "reason": "a mistake found in your notebook"})
    graph = content.concepts()
    return {"readable": True, "notebook": nb, "diagnosis": diag, "misconception": service.misconception_card(mc_id) if mc_id else None,
            "concept": {"id": cid, "name": graph[cid]["name"]} if cid in graph else None, "mastery_changes": changes}
