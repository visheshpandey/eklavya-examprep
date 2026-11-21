"""Socratic dialogue agent: after a misconception is detected Eklavya talks the student out of it instead of just correcting them.

It never states the answer. It asks guiding questions built for that misconception; after each reply an LLM judge returns
{understanding, still_holds_misconception, next_move, say}. The misconception counts as resolved ONLY when the student explains the correct
idea in their own words. Hard cap: 4 student turns; then Eklavya explains clearly and schedules an early review.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

from pydantic import BaseModel, ValidationError, field_validator

from app import db
from app.ai import gemini
from app.ps02 import content, learner_model as lm, llm, srs

log = logging.getLogger(__name__)
MAX_TURNS = 4
JUDGE_DEADLINE_S = 8.0
RESOLVE_LEARN = 0.35              # a resolved dialogue teaches more than a lucky click (plain correct uses 0.15)

LANG_NAMES = {"hinglish": "Hinglish (Hindi in Roman script mixed with English, the way students talk)", "english": "simple English",
              "hindi": "Hindi in Devanagari script"}

SYSTEM = """You are Eklavya, a warm Socratic physics tutor for a CBSE Class 10 student. The student holds a specific misconception. Your job is to help them
discover the correct idea themselves by talking, NOT to tell them the answer.
Rules:
- Reply in the requested language. At most 2 short sentences, spoken style (it will be read aloud). One question at a time.
- NEVER state the correct idea or the final answer yourself, until understanding is "resolved" (then confirm it warmly in one sentence).
- next_move: "hint" (a small nudge), "question" (a new guiding question), "counterexample" (a situation that contradicts their idea), or "confirm" (they got it).
- Judge the student's LAST reply against the correct idea: understanding "none" (still wrong or off-topic), "partial" (moving the right way but incomplete), or
  "resolved" (they explained the correct idea clearly in their own words; repeating your hint back, or a bare "yes/ok", is NOT resolved).
- still_holds_misconception is true while they still believe the wrong idea. Be kind; never say "wrong" harshly.
Return ONLY JSON: {"understanding": "none|partial|resolved", "still_holds_misconception": bool, "next_move": "hint|question|counterexample|confirm", "say": str}"""


class Verdict(BaseModel):
    understanding: str = "none"
    still_holds_misconception: bool = True
    next_move: str = "hint"
    say: str = ""

    @field_validator("understanding")
    @classmethod
    def valid_understanding(cls, v):
        v = str(v).lower().strip()
        return v if v in ("none", "partial", "resolved") else "none"

    @field_validator("next_move")
    @classmethod
    def valid_move(cls, v):
        v = str(v).lower().strip()
        return v if v in ("hint", "question", "counterexample", "confirm") else "hint"


def _probe(mc: dict, language: str) -> str:
    return mc["probe_english"] if language == "english" else mc["probe_hinglish"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------------ progress
PROGRESS = {"none": "holds", "partial": "wavering", "resolved": "resolved"}


def _public(row: dict, say: str | None = None, extra: dict | None = None) -> dict:
    mc = content.misconceptions().get(row["misconception_id"], {})
    transcript = json.loads(row["transcript"] or "[]")
    last = next((t["understanding"] for t in reversed(transcript) if t["role"] == "student"), None)
    progress = "resolved" if row["status"] == "resolved" else PROGRESS.get(last, "holds")
    return {"dialogue_id": row["id"], "status": row["status"], "progress": progress, "turns_used": row["student_turns"], "turns_max": MAX_TURNS,
            "misconception": {"id": row["misconception_id"], "label": mc.get("label", "")}, "transcript": transcript, "say": say, **(extra or {})}


def _load(dialogue_id: int, student_id: int) -> dict:
    row = db.one("SELECT * FROM dialogues WHERE id=? AND student_id=?", (dialogue_id, student_id))
    if not row:
        raise KeyError("dialogue not found")
    return row


def _save(row_id: int, transcript: list, status: str, turns: int) -> None:
    db.execute("UPDATE dialogues SET transcript=?, status=?, student_turns=?, updated_at=? WHERE id=?", (json.dumps(transcript, ensure_ascii=False), status, turns, _now(), row_id))


# ------------------------------------------------------------------ start
def start(student_id: int, attempt_id: int, language: str = "hinglish") -> dict:
    att = db.one("SELECT * FROM attempts WHERE id=? AND student_id=?", (attempt_id, student_id))
    if not att:
        raise KeyError("attempt not found")
    mc_id = att["misconception_id"]
    if not mc_id or mc_id == "NONE" or mc_id not in content.misconceptions():
        raise ValueError("no misconception to work on for this attempt")
    existing = db.one("SELECT * FROM dialogues WHERE attempt_id=? AND student_id=? ORDER BY id DESC LIMIT 1", (attempt_id, student_id))
    if existing:
        return _public(existing)
    mc = content.misconceptions()[mc_id]
    opener = {"role": "tutor", "text": _probe(mc, language), "move": "question"}
    row_id = db.execute("INSERT INTO dialogues (student_id, attempt_id, concept_id, misconception_id, language, status, student_turns, transcript, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (student_id, attempt_id, att["concept_id"], mc_id, language, "open", 0, json.dumps([opener], ensure_ascii=False), _now(), _now()))
    return _public(_load(row_id, student_id), say=opener["text"])


# ------------------------------------------------------------------ the judge
def _judge_prompt(mc: dict, transcript: list, language: str, turn: int) -> str:
    convo = "\n".join(f"{'Eklavya' if t['role'] == 'tutor' else 'Student'}: {t['text']}" for t in transcript)
    return (f"Language to reply in: {LANG_NAMES.get(language, LANG_NAMES['hinglish'])}\nStudent's misconception: {mc['label']}: {mc['description']}\n"
            f"The CORRECT idea (for judging only, do not reveal it): {mc['correction']}\nA good analogy you may hint at without stating the answer: {mc['analogy']}\n"
            f"This is student turn {turn} of {MAX_TURNS}.\nConversation so far:\n{convo}")


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 3}


def _heuristic(mc: dict, transcript: list, language: str, turn: int) -> Verdict:
    """No-LLM fallback. Conservative: it never declares 'resolved', so a failing model cannot hand out free credit."""
    last = next(t["text"] for t in reversed(transcript) if t["role"] == "student")
    key = _words(mc["correction"]) - {"that", "this", "with", "from", "same", "does", "have"}
    overlap = len(key & _words(last)) / max(1, len(key))
    eng = language == "english"
    if overlap >= 0.3:
        say = "You are moving the right way. Can you say the whole idea in your own words?" if eng else "Tum sahi disha mein ho. Poora idea apne shabdon mein bolo?"
        return Verdict(understanding="partial", still_holds_misconception=True, next_move="question", say=say)
    # neutral nudges only: the fallback must never reveal the answer (the catalogue analogy would), so it re-asks the guiding question
    ladder_en = ["Let's slow down. " + mc["probe_english"], "Tell me in your own words: what do you think is really happening here, and why?",
                 "Think of an everyday example that behaves the same way. What does it tell you?"]
    ladder_hi = ["Chalo thoda ruk ke socho. " + mc["probe_hinglish"], "Apne shabdon mein batao: tumhare hisaab se asal mein yahan kya ho raha hai, aur kyun?",
                 "Koi roz ka example socho jo aisa hi kaam karta ho. Woh tumhe kya batata hai?"]
    ladder = ladder_en if eng else ladder_hi
    return Verdict(understanding="none", still_holds_misconception=True, next_move="hint", say=ladder[min(turn - 1, len(ladder) - 1)])


def _judge(mc: dict, transcript: list, language: str, turn: int) -> tuple[Verdict, str]:
    try:
        raw = llm.hedged_json(SYSTEM, _judge_prompt(mc, transcript, language, turn), ("understanding", "say"), 0.4, deadline_s=JUDGE_DEADLINE_S)
        if not isinstance(raw, dict):
            raise ValueError("not an object")
        v = Verdict(**raw)
        if v.understanding == "resolved":
            v.still_holds_misconception = False
        return v, "ai"
    except (ValidationError, ValueError, TypeError, gemini.LLMError) as exc:
        log.warning("Socratic judge fell back to the heuristic: %s", str(exc)[:200])
        return _heuristic(mc, transcript, language, turn), "heuristic"


# ------------------------------------------------------------------ outcomes
def _resolve(student_id: int, row: dict) -> list[dict]:
    """Explained in their own words: a bigger BKT gain than a click, and the misconception is marked resolved."""
    mc = content.misconceptions()[row["misconception_id"]]
    graph = content.concepts()
    mastery = lm.get_mastery(student_id)
    scope = {row["concept_id"]} | content.ancestors(row["concept_id"])
    targets = [row["concept_id"]] + [c for c in mc["concept_ids"] if c in scope and c != row["concept_id"]]
    deltas = []
    for i, cid in enumerate(targets):
        before = mastery[cid]
        weight = 1.0 if i == 0 else 0.5
        mastery[cid] = round(lm.bkt_update(before, True, learn=RESOLVE_LEARN, weight=weight), 4)
        deltas.append({"concept_id": cid, "name": graph[cid]["name"], "before": round(before, 4), "after": mastery[cid],
                       "reason": "explained the idea in their own words" if i == 0 else "prerequisite effect (misconception resolved)"})
    lm.save_mastery(student_id, {d["concept_id"]: d["after"] for d in deltas})
    db.execute("UPDATE student_misconceptions SET resolved=1 WHERE student_id=? AND misconception_id=?", (student_id, row["misconception_id"]))
    return deltas


def _give_up(student_id: int, row: dict, language: str) -> dict:
    """Four turns and still unsure: explain it clearly, and bring the concept back for an early review."""
    mc = content.misconceptions()[row["misconception_id"]]
    review = srs.schedule_early(student_id, row["concept_id"])
    return {"explanation": mc["correction"], "analogy": mc["analogy"], "review": review}


# ------------------------------------------------------------------ reply
def reply(student_id: int, dialogue_id: int, text: str, mode: str = "text", language: str | None = None) -> dict:
    row = _load(dialogue_id, student_id)
    if row["status"] != "open":
        return _public(row)
    language = language or row["language"] or "hinglish"
    mc = content.misconceptions()[row["misconception_id"]]
    transcript = json.loads(row["transcript"])
    turn = row["student_turns"] + 1
    transcript.append({"role": "student", "text": text.strip()[:600], "mode": mode if mode in ("voice", "text") else "text"})
    verdict, source = _judge(mc, transcript, language, turn)
    transcript[-1]["understanding"] = verdict.understanding
    extra: dict = {"verdict": {**verdict.model_dump(), "source": source}}

    if verdict.understanding == "resolved":
        say = verdict.say or ("Exactly, you worked it out yourself." if language == "english" else "Bilkul sahi, tumne khud samjha diya.")
        transcript.append({"role": "tutor", "text": say, "move": "confirm"})
        _save(row["id"], transcript, "resolved", turn)
        extra["mastery_changes"] = _resolve(student_id, row)
        extra["reveal"] = {"correction": mc["correction"], "analogy": mc["analogy"]}
        return _public(_load(row["id"], student_id), say=say, extra=extra)

    if turn >= MAX_TURNS:
        closing = _give_up(student_id, row, language)
        say = ("Let's stop here. Here is the idea: " if language == "english" else "Chalo yahin rukte hain. Idea yeh hai: ") + closing["explanation"]
        transcript.append({"role": "tutor", "text": say, "move": "confirm"})
        _save(row["id"], transcript, "unresolved", turn)
        extra["reveal"] = {"correction": closing["explanation"], "analogy": closing["analogy"]}
        extra["review"] = closing["review"]
        return _public(_load(row["id"], student_id), say=say, extra=extra)

    say = verdict.say or _probe(mc, language)
    transcript.append({"role": "tutor", "text": say, "move": verdict.next_move})
    _save(row["id"], transcript, "open", turn)
    return _public(_load(row["id"], student_id), say=say, extra=extra)
