"""Learner model: Bayesian Knowledge Tracing per concept, with prerequisite propagation and diagnostic seeding.

The first half is pure (no database) so it is easy to test; the second half persists to the ``mastery`` table.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app import db
from app.ps02 import content

P_LEARN = 0.15
P_SLIP = 0.10
P_GUESS = 0.25          # 4-option MCQ
WRONG_WEIGHT = 0.6       # one wrong MCQ may be a slip, so mastery moves 60% of the way to the Bayesian posterior (and never rises on a miss)
PREREQ_NEGATIVE_WEIGHT = 0.5   # x the main drop
PREREQ_POSITIVE_WEIGHT = 0.3
CARELESS_WEIGHT = 0.2    # right reasoning, wrong pick: a slip, so only a small penalty
LUCKY_WEIGHT = 0.5       # right answer but shaky reasoning: smaller gain
DEFAULT_P = 0.3
FRONTIER_THRESHOLD = 0.5


# ------------------------------------------------------------------ pure BKT
def posterior(p: float, correct: bool, slip: float = P_SLIP, guess: float = P_GUESS) -> float:
    """P(known | answer) by Bayes' rule."""
    if correct:
        num = p * (1 - slip)
        den = num + (1 - p) * guess
    else:
        num = p * slip
        den = num + (1 - p) * (1 - guess)
    return num / den if den else p


def clamp(p: float) -> float:
    return min(0.99, max(0.05, p))   # floor: a few misses should not read as "0%"


def bkt_update(p: float, correct: bool, learn: float = P_LEARN, weight: float = 1.0) -> float:
    """Bayesian posterior; after a CORRECT answer also the learning transition (a miss shows no learning, so a wrong answer can never raise p).
    ``weight`` (0..1) scales how far p moves toward that target."""
    post = posterior(p, correct)
    target = post + (1 - post) * learn if correct else post
    return clamp(p + weight * (target - p))


def seed_from_diagnostic(results: dict[str, tuple[bool, int]]) -> dict[str, float]:
    """Initial p_known per concept. ``results`` maps tested concept -> (correct, difficulty).

    Correct: 0.60-0.70 by difficulty. Wrong: 0.15-0.25 (a miss on an easy question says more). Untested: mean of the
    prerequisites' values, 0.3 when it has none."""
    out: dict[str, float] = {}
    graph = content.concepts()
    for cid in content.concept_order():
        if cid in results:
            ok, d = results[cid]
            out[cid] = 0.60 + 0.05 * (d - 1) if ok else 0.15 + 0.05 * (d - 1)
        else:
            pre = [out[p] for p in graph[cid]["prerequisites"] if p in out]
            out[cid] = sum(pre) / len(pre) if pre else DEFAULT_P
    return {k: round(v, 4) for k, v in out.items()}


def apply_answer(mastery: dict[str, float], concept_id: str, correct: bool, difficulty: int = 2,
                 misconception_id: str | None = None, careless: bool = False, lucky: bool = False) -> list[dict]:
    """Update ``mastery`` in place for one answer and return the list of changes (concept, before, after, reason).

    - Normal BKT update on the question's concept (softened for a careless slip or a lucky guess).
    - Wrong + a misconception that belongs to a prerequisite: half-weight negative update on that prerequisite.
    - Correct on a difficulty-3 question: a small positive nudge (x0.3) to each direct prerequisite."""
    deltas: list[dict] = []
    graph = content.concepts()

    def change(cid: str, new: float, reason: str) -> None:
        before = mastery.get(cid, DEFAULT_P)
        mastery[cid] = round(new, 4)
        deltas.append({"concept_id": cid, "name": graph[cid]["name"], "before": round(before, 4), "after": round(new, 4), "reason": reason})

    p = mastery.get(concept_id, DEFAULT_P)
    if correct:
        change(concept_id, bkt_update(p, True, weight=LUCKY_WEIGHT if lucky else 1.0), "answered correctly")
        if difficulty >= 3:
            for pre in graph[concept_id]["prerequisites"]:
                change(pre, bkt_update(mastery.get(pre, DEFAULT_P), True, weight=PREREQ_POSITIVE_WEIGHT), "prerequisite effect (hard question solved)")
    else:
        change(concept_id, bkt_update(p, False, weight=CARELESS_WEIGHT if careless else WRONG_WEIGHT), "careless slip" if careless else "answered wrong")
        if misconception_id and not careless:
            mc = content.misconceptions().get(misconception_id)
            prereqs = content.ancestors(concept_id)
            for cid in (mc["concept_ids"] if mc else []):
                if cid != concept_id and cid in prereqs:
                    change(cid, bkt_update(mastery.get(cid, DEFAULT_P), False, weight=PREREQ_NEGATIVE_WEIGHT * WRONG_WEIGHT), "prerequisite effect (misconception)")
    return deltas


def frontier_weakest(mastery: dict[str, float], k: int = 3) -> list[str]:
    """Lowest p_known among concepts whose prerequisites are all >= 0.5; falls back to the lowest overall."""
    graph = content.concepts()
    ready = [c for c in graph if all(mastery.get(p, DEFAULT_P) >= FRONTIER_THRESHOLD for p in graph[c]["prerequisites"])]
    pool = ready or list(graph)
    return sorted(pool, key=lambda c: (mastery.get(c, DEFAULT_P), c))[:k]


# ------------------------------------------------------------------ persistence
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def get_mastery(student_id: int) -> dict[str, float]:
    rows = db.query("SELECT concept_id, p_known FROM mastery WHERE student_id=?", (student_id,))
    have = {r["concept_id"]: r["p_known"] for r in rows}
    return {cid: have.get(cid, DEFAULT_P) for cid in content.concept_order()}


def mastery_details(student_id: int) -> dict[str, dict]:
    rows = {r["concept_id"]: r for r in db.query("SELECT * FROM mastery WHERE student_id=?", (student_id,))}
    out = {}
    for cid in content.concept_order():
        r = rows.get(cid)
        out[cid] = {"p_known": r["p_known"] if r else DEFAULT_P, "attempts": r["attempts"] if r else 0,
                    "correct": r["correct"] if r else 0, "last_seen": r["last_seen"] if r else None}
    return out


def save_mastery(student_id: int, new: dict[str, float], touched: dict[str, bool] | None = None, when: str | None = None) -> None:
    """Write p_known for every concept in ``new``. ``touched`` maps concept -> answered correctly, for the attempts/correct counters."""
    when = when or now_iso()
    touched = touched or {}
    with db.get_conn() as c:
        for cid, p in new.items():
            row = c.execute("SELECT attempts, correct, last_seen FROM mastery WHERE student_id=? AND concept_id=?", (student_id, cid)).fetchone()
            attempts, correct, last_seen = (row[0], row[1], row[2]) if row else (0, 0, None)
            if cid in touched:
                attempts += 1
                correct += 1 if touched[cid] else 0
                last_seen = when
            c.execute("DELETE FROM mastery WHERE student_id=? AND concept_id=?", (student_id, cid))
            c.execute("INSERT INTO mastery (student_id, concept_id, p_known, attempts, correct, last_seen, updated_at) VALUES (?,?,?,?,?,?,?)",
                      (student_id, cid, p, attempts, correct, last_seen, when))


def weakest_concepts(student_id: int, k: int = 3) -> list[str]:
    return frontier_weakest(get_mastery(student_id), k)
