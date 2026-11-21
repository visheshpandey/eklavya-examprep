"""Spaced repetition: SM-2 per concept. 'Time travel' mode treats 1 day as 1 minute so judges can watch reviews fall due."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from app import db
from app.ps02 import content

_time_travel = os.environ.get("PS02_TIME_TRAVEL", "").lower() in ("1", "true", "yes")


def set_time_travel(on: bool) -> None:
    global _time_travel
    _time_travel = bool(on)


def time_travel() -> bool:
    return _time_travel


def quality(correct: bool, careless: bool = False, has_misconception: bool = False, fast: bool = False) -> int:
    """0-5 SM-2 grade: correct fast 5, correct 4, careless slip 3, wrong with a misconception 1, wrong unknown 2."""
    if correct:
        return 5 if fast else 4
    if careless:
        return 3
    return 1 if has_misconception else 2


def sm2(easiness: float, interval_days: float, repetitions: int, q: int) -> tuple[float, float, int]:
    """Standard SM-2 step -> (easiness, interval_days, repetitions)."""
    easiness = max(1.3, easiness + 0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    if q < 3:
        return easiness, 1, 0
    if repetitions == 0:
        interval = 1
    elif repetitions == 1:
        interval = 6
    else:
        interval = round(interval_days * easiness)
    return easiness, interval, repetitions + 1


def due_at(interval_days: float, now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now + (timedelta(minutes=interval_days) if _time_travel else timedelta(days=interval_days))


def record(student_id: int, concept_id: str, q: int, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    row = db.one("SELECT easiness, interval_days, repetitions FROM reviews WHERE student_id=? AND concept_id=?", (student_id, concept_id))
    e, i, r = sm2(row["easiness"] if row else 2.5, row["interval_days"] if row else 0, row["repetitions"] if row else 0, q)
    due = due_at(i, now).isoformat(timespec="seconds")
    with db.get_conn() as c:
        c.execute("DELETE FROM reviews WHERE student_id=? AND concept_id=?", (student_id, concept_id))
        c.execute("INSERT INTO reviews (student_id, concept_id, easiness, interval_days, repetitions, due_at) VALUES (?,?,?,?,?,?)",
                  (student_id, concept_id, round(e, 3), i, r, due))
    return {"concept_id": concept_id, "easiness": round(e, 3), "interval_days": i, "repetitions": r, "due_at": due}


def due_reviews(student_id: int, now: datetime | None = None) -> list[dict]:
    now_s = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    graph = content.concepts()
    rows = db.query("SELECT * FROM reviews WHERE student_id=? ORDER BY due_at", (student_id,))
    return [{**r, "name": graph[r["concept_id"]]["name"], "due": r["due_at"] <= now_s} for r in rows]


def schedule_early(student_id: int, concept_id: str, now: datetime | None = None) -> dict:
    """An unresolved misconception brings its concept back soon: due in 30 minutes (30 seconds in time-travel mode), SM-2 state reset to a failed recall."""
    now = now or datetime.now(timezone.utc)
    row = db.one("SELECT easiness FROM reviews WHERE student_id=? AND concept_id=?", (student_id, concept_id))
    easiness = max(1.3, (row["easiness"] if row else 2.5) - 0.2)
    due = (now + (timedelta(seconds=30) if _time_travel else timedelta(minutes=30))).isoformat(timespec="seconds")
    with db.get_conn() as c:
        c.execute("DELETE FROM reviews WHERE student_id=? AND concept_id=?", (student_id, concept_id))
        c.execute("INSERT INTO reviews (student_id, concept_id, easiness, interval_days, repetitions, due_at) VALUES (?,?,?,?,?,?)", (student_id, concept_id, round(easiness, 3), 1, 0, due))
    return {"concept_id": concept_id, "due_at": due, "easiness": round(easiness, 3), "interval_days": 1, "repetitions": 0}
