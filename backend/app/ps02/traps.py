"""🔒 Verified fixed. A misconception is "Detected" -> "Resolved" (the student explained the right idea in a dialogue) -> "Verified" (they later
avoided a TRAP question designed so that someone still holding the idea picks a specific wrong option).

When a dialogue resolves a misconception, a misconception-level check is scheduled (separate from the concept's own SM-2 review): due after 2 days, or
2 minutes in time-travel mode. When due, a trap question is served. Correct -> verified. The trap option -> the misconception is reactivated and the
student talks it through again. Any other wrong answer -> inconclusive: a fresh check is scheduled sooner, nothing is reactivated.
"""
from __future__ import annotations

import json
import logging
import random
from datetime import datetime, timedelta, timezone

from app import db
from app.ps02 import content, learner_model as lm, question_gen, service, srs

log = logging.getLogger(__name__)
FIRST_INTERVAL_DAYS = 2        # 2 days normally; with time travel (1 day = 1 minute) that is 2 minutes
RETRY_INTERVAL_DAYS = 1
STAGES = ("detected", "resolved", "verified")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def stage_of(row: dict) -> str:
    """Detected -> Resolved -> Verified, from a student_misconceptions row."""
    if not row["resolved"]:
        return "detected"
    return "verified" if row.get("verified") else "resolved"


def due_at(row: dict) -> datetime:
    """When the check falls due. Computed on read, so switching time travel on makes pending checks due within minutes."""
    start = datetime.fromisoformat(row["scheduled_at"])
    return start + (timedelta(minutes=row["interval_days"]) if srs.time_travel() else timedelta(days=row["interval_days"]))


# ------------------------------------------------------------------ scheduling
def schedule(student_id: int, misconception_id: str, concept_id: str, now: datetime | None = None) -> dict:
    """Called when a dialogue resolves a misconception. Replaces any earlier check for it."""
    now = now or _now()
    with db.get_conn() as c:
        c.execute("DELETE FROM misconception_checks WHERE student_id=? AND misconception_id=?", (student_id, misconception_id))
        c.execute("INSERT INTO misconception_checks (student_id, misconception_id, concept_id, scheduled_at, interval_days, status, attempts) VALUES (?,?,?,?,?, 'pending', 0)",
                  (student_id, misconception_id, concept_id, _iso(now), FIRST_INTERVAL_DAYS))
        c.execute("UPDATE student_misconceptions SET verified=0, verified_at=NULL WHERE student_id=? AND misconception_id=?", (student_id, misconception_id))
    return {"misconception_id": misconception_id, "concept_id": concept_id, "interval_days": FIRST_INTERVAL_DAYS}


def _card(row: dict, now: datetime) -> dict:
    mc = content.misconceptions()[row["misconception_id"]]
    due = due_at(row)
    return {"misconception_id": row["misconception_id"], "label": mc["label"], "concept_id": row["concept_id"], "concept_name": content.concepts()[row["concept_id"]]["name"],
            "due_at": _iso(due), "due": due <= now, "seconds_left": max(0, int((due - now).total_seconds())), "attempts": row["attempts"]}


def checks(student_id: int, now: datetime | None = None) -> dict:
    """Everything the Reviews screen needs: checks that are due, checks coming up, and misconceptions already verified."""
    now = now or _now()
    pending = [_card(r, now) for r in db.query("SELECT * FROM misconception_checks WHERE student_id=? AND status='pending' ORDER BY id", (student_id,))]
    verified = [{"misconception_id": r["misconception_id"], "label": content.misconceptions()[r["misconception_id"]]["label"], "verified_at": r["verified_at"]}
                for r in db.query("SELECT misconception_id, verified_at FROM student_misconceptions WHERE student_id=? AND resolved=1 AND verified=1 ORDER BY verified_at DESC", (student_id,))
                if r["misconception_id"] in content.misconceptions()]
    return {"time_travel": srs.time_travel(), "due": [p for p in pending if p["due"]], "upcoming": [p for p in pending if not p["due"]], "verified": verified}


def force_due(student_id: int) -> int:
    """Demo helper (Judge tour): make every pending check due right now."""
    old = (_now() - timedelta(days=FIRST_INTERVAL_DAYS + 1)).isoformat(timespec="seconds")
    return db.execute("UPDATE misconception_checks SET scheduled_at=? WHERE student_id=? AND status='pending'", (old, student_id)) or 0


# ------------------------------------------------------------------ the trap question
def _bank(mc_id: str, attempts: int) -> dict | None:
    pool = [t for t in content._load("trap_bank.json")["traps"] if t["misconception_id"] == mc_id]
    if not pool:
        return None
    t = pool[attempts % len(pool)]                        # a repeat check uses the next hand-written trap
    return {"stem": t["stem"], "options": list(t["options"]), "correct_index": t["correct_index"], "distractor_misconceptions": dict(t["distractor_misconceptions"]),
            "difficulty": t["difficulty"], "concept_id": t["concept_id"], "explanation": t["explanation"], "source": "bank"}


def make_trap(student_id: int, mc_id: str, concept_id: str, attempts: int) -> dict:
    """A hand-written trap when one exists (instant and reliable), else an AI-written one built to tempt exactly this misconception."""
    q = _bank(mc_id, attempts)
    if q is None:
        stems = service._recent_stems(student_id)
        q = question_gen.generate(concept_id, 2, [mc_id], stems, None, target_mc=mc_id, trap=True)
        if q.get("target_mc") != mc_id:                    # the model could not build a trap: fall back to a prepared question that carries this misconception
            q = next((fallback for fallback in (_from_diagnostic(mc_id),) if fallback), q)
    q = random_order(q)
    return {**q, "trap_mc": mc_id}


def _from_diagnostic(mc_id: str) -> dict | None:
    for d in content.diagnostic():
        if mc_id in d["distractor_misconceptions"].values():
            return {**{k: d[k] for k in ("stem", "options", "correct_index", "distractor_misconceptions", "difficulty", "concept_id", "explanation")}, "source": "bank"}
    return None


def random_order(q: dict) -> dict:
    """Shuffle the options (so the trap is not always in the same slot) and remap the answer and the misconception map."""
    order = list(range(len(q["options"])))
    random.shuffle(order)
    return {**q, "options": [q["options"][i] for i in order], "correct_index": order.index(q["correct_index"]),
            "distractor_misconceptions": {str(order.index(int(k))): v for k, v in q["distractor_misconceptions"].items()}}


def next_trap(student_id: int, mc_id: str) -> dict:
    row = db.one("SELECT * FROM misconception_checks WHERE student_id=? AND misconception_id=? AND status='pending'", (student_id, mc_id))
    if not row:
        raise KeyError("no check is pending for this misconception")
    if due_at(row) > _now():
        raise ValueError("this check is not due yet")
    q = make_trap(student_id, mc_id, row["concept_id"], row["attempts"])
    qid = service._store_question(student_id, q)
    mc = content.misconceptions()[mc_id]
    return {"question_id": qid, "misconception": {"id": mc_id, "label": mc["label"]}, "concept_id": q["concept_id"], "concept_name": content.concepts()[q["concept_id"]]["name"],
            "stem": q["stem"], "options": q["options"], "difficulty": q.get("difficulty", 2), "attempt": row["attempts"] + 1}


# ------------------------------------------------------------------ the answer
def answer(student_id: int, question_id: str, chosen_index: int) -> dict:
    stored = service._load_question(question_id)
    if not stored or stored["student_id"] != student_id or not stored["question"].get("trap_mc"):
        raise KeyError("check not found")
    q, mc_id = stored["question"], stored["question"]["trap_mc"]
    correct = chosen_index == q["correct_index"]
    trapped = not correct and q["distractor_misconceptions"].get(str(chosen_index)) == mc_id
    res = service.record_answer(student_id, q, chosen_index, phase="verify")
    now = _iso(_now())
    row = db.one("SELECT attempts FROM misconception_checks WHERE student_id=? AND misconception_id=?", (student_id, mc_id)) or {"attempts": 0}
    out: dict = {"correct": correct, "correct_index": q["correct_index"], "explanation": q.get("explanation", ""), "mastery_changes": res["deltas"], "misconception_id": mc_id,
                 "label": content.misconceptions()[mc_id]["label"]}

    if correct:
        with db.get_conn() as c:
            c.execute("UPDATE student_misconceptions SET resolved=1, verified=1, verified_at=? WHERE student_id=? AND misconception_id=?", (now, student_id, mc_id))
            c.execute("UPDATE misconception_checks SET status='passed', attempts=? WHERE student_id=? AND misconception_id=?", (row["attempts"] + 1, student_id, mc_id))
        out.update({"outcome": "verified", "stage": "verified", "message": "Verified fixed: you avoided the trap, so the idea has really changed."})
    elif trapped:
        service._note_misconception(student_id, mc_id, "Fell for the verification trap: " + q["options"][chosen_index], source="trap")
        with db.get_conn() as c:
            c.execute("UPDATE student_misconceptions SET verified=0, verified_at=NULL WHERE student_id=? AND misconception_id=?", (student_id, mc_id))
            c.execute("UPDATE misconception_checks SET status='failed', attempts=? WHERE student_id=? AND misconception_id=?", (row["attempts"] + 1, student_id, mc_id))
        out.update({"outcome": "relapsed", "stage": "detected", "message": "That old idea came back. Let's talk it through again.", "concept_id": q["concept_id"],
                    "misconception": service.misconception_card(mc_id)})
    else:
        with db.get_conn() as c:
            c.execute("UPDATE misconception_checks SET scheduled_at=?, interval_days=?, attempts=? WHERE student_id=? AND misconception_id=? AND status='pending'",
                      (now, RETRY_INTERVAL_DAYS, row["attempts"] + 1, student_id, mc_id))
        out.update({"outcome": "inconclusive", "stage": "resolved", "message": "Not quite, but it was not the old slip. We'll check again soon."})
    out["trace"] = [{"tool": "schedule_review", "ms": None, "summary": {"verified": "Misconception verified: the check passed", "relapsed": "Misconception reactivated: the student chose the trap option",
                                                                      "inconclusive": "Inconclusive: a fresh check is scheduled"}[out["outcome"]]}]
    return out
