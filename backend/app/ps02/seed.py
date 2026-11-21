"""Demo class "10-B": six students with distinct profiles, produced by running scripted answers through the REAL BKT / misconception / SM-2 code.

Nothing is hard-coded mastery: each profile only says how likely a student is to answer a concept correctly and which misconceptions they hold.
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone

from app import db
from app.ps02 import content, learner_model as lm, service

CLASS = "10-B"
LIGHT = {"L1", "L2", "L3", "L4", "L5", "L6"}
EYE = {"E1", "E2", "E3", "E4"}
ELEC = {"C1", "C2", "C3", "C4", "C5", "C6", "C7"}
MAG = {"M1", "M2", "M3", "M4"}

# name, {concept: P(correct) overrides}, default P(correct), {concept: [misconceptions held]}, careless share of wrong answers
PROFILES = [
    ("Aarav Sharma", {**{c: 0.9 for c in LIGHT | EYE | MAG}, **{c: 0.25 for c in ELEC}}, 0.8, {"C1": ["MC01"], "C5": ["MC01"], "C6": ["MC03"], "C3": ["MC02"]}, 0.05),
    ("Diya Patel", {"L3": 0.2, "L6": 0.2, "L2": 0.5}, 0.78, {"L3": ["MC09"], "L6": ["MC12", "MC09"]}, 0.05),
    ("Kabir Singh", {"M3": 0.15, "M2": 0.5}, 0.9, {"M3": ["MC18"]}, 0.1),
    ("Rohan Verma", {}, 0.3, {"C1": ["MC01"], "C5": ["MC06"], "C6": ["MC03"], "C4": ["MC05"], "C3": ["MC07"], "L3": ["MC09"], "L4": ["MC10"], "E2": ["MC13"], "M1": ["MC16"]}, 0.05),
    ("Meera Nair", {}, 0.58, {c: [] for c in ELEC}, 0.65),
    ("Ishita Gupta", {"E2": 0.2, "E4": 0.2, "E3": 0.5}, 0.68, {"E2": ["MC13"], "E4": ["MC15"]}, 0.05),
]

SLIP_QUOTES = ["mujhe pata tha answer, galti se doosra option tap ho gaya", "my working was right, I misread the option", "calculation sahi tha par sign likhna bhool gaya"]


def _p_correct(overrides: dict, default: float, cid: str, difficulty: int) -> float:
    return max(0.05, min(0.97, overrides.get(cid, default) - 0.07 * (difficulty - 1)))


def _wrong_pick(q: dict, wanted_mc: str | None, rng: random.Random) -> int:
    wrong = [int(i) for i in q["distractor_misconceptions"]]
    if wanted_mc:
        hits = [i for i in wrong if q["distractor_misconceptions"][str(i)] == wanted_mc]
        if hits:
            return rng.choice(hits)
    return rng.choice(wrong)


def _stub_question(cid: str, difficulty: int, rng: random.Random) -> dict:
    """Seed attempts reuse hand-written questions where they exist; otherwise a generic stand-in built from the concept's misconceptions."""
    bank = [q for q in content.diagnostic() if q["concept_id"] == cid]
    if bank:
        return {**rng.choice(bank), "difficulty": difficulty, "source": "seed"}
    mcs = [m["id"] for m in content.misconceptions().values() if cid in m["concept_ids"]] or ["MC_UNKNOWN"]
    return {"stem": f"Practice question on {content.concepts()[cid]['name']}", "options": ["A", "B", "C", "D"], "correct_index": 0, "difficulty": difficulty, "concept_id": cid,
            "distractor_misconceptions": {"1": mcs[0], "2": mcs[-1], "3": "MC_UNKNOWN"}, "explanation": "", "source": "seed"}


def _quote(mc_id: str | None, rng: random.Random) -> str:
    m = content.misconceptions().get(mc_id or "")
    return rng.choice(m["telltale_phrases"]) if m and m["telltale_phrases"] else "pata nahi, andaza lagaya"


def seed_student(profile, index: int, rng: random.Random, attempts: int = 34) -> int:
    name, overrides, default, holds, careless_share = profile
    sid = service.create_student(name, CLASS, is_demo=True)["id"]
    start = datetime.now(timezone.utc) - timedelta(days=14)

    # 1) the diagnostic, answered according to the profile
    answers = []
    for q in content.diagnostic():
        pc = overrides.get(q["concept_id"], default)
        ok = False if pc <= 0.3 else True if pc >= 0.8 else rng.random() < _p_correct(overrides, default, q["concept_id"], q["difficulty"])   # clear strengths/gaps show up in the diagnostic
        mc = (holds.get(q["concept_id"]) or [None])[0]
        answers.append({"question_id": q["id"], "chosen_index": q["correct_index"] if ok else _wrong_pick(q, mc, rng)})
    service.submit_diagnostic(sid, answers, when=start)
    base = lm.get_mastery(sid)   # prior knowledge differs between students: spread the starting values so the heatmap is not made of repeats
    lm.save_mastery(sid, {c: round(min(0.95, max(0.12, p + rng.gauss(0, 0.07))), 3) for c, p in base.items()}, when=start.isoformat(timespec="seconds"))

    # 2) adaptive practice: the REAL planner picks the concept, the profile decides how the student answers
    for n in range(attempts):
        when = start + timedelta(days=0.5 + n * (13.0 / attempts), hours=rng.random() * 3)
        focus = [c for c in content.concept_order() if overrides.get(c, default) < 0.4 or holds.get(c)]
        plan = service.plan_next(sid, concept_id=rng.choice(focus) if focus and rng.random() < 0.5 else None)   # half the time the student works on their own trouble spots
        cid, diff = plan["concept_id"], plan["difficulty"]
        q = _stub_question(cid, diff, rng)
        ok = rng.random() < _p_correct(overrides, default, cid, diff)
        if ok:
            service.record_answer(sid, q, q["correct_index"], when=when, fast=rng.random() < 0.4)
            continue
        held = holds.get(cid, [])
        mc = rng.choice(held) if held and rng.random() < 0.85 else None
        careless = rng.random() < careless_share
        chosen = _wrong_pick(q, mc, rng)
        quote = rng.choice(SLIP_QUOTES) if careless else _quote(mc, rng)
        service.record_answer(sid, q, chosen, reasoning=quote, mode="voice" if rng.random() < 0.5 else "text",
                              misconception_id=None if careless else (mc or "MC_UNKNOWN"), confidence=0.55 if careless else (0.85 if mc else 0.4),
                              careless=careless, when=when)
    return sid


FIXTURE = content.DATA / "demo_class.json"
_TIME_FIELDS = {"mastery": ("last_seen", "updated_at"), "attempts": ("created_at",), "reviews": ("due_at",), "student_misconceptions": ("last_seen",), "students": ("created_at",)}


def _wipe_demo() -> None:
    from app.ps02 import reseed
    reseed.delete_students([r["id"] for r in db.query("SELECT id FROM students WHERE is_demo=1")])


def simulate() -> list[int]:
    """Run the scripted students through the real BKT / misconception / SM-2 code (slow: thousands of small DB writes)."""
    rng = random.Random(2611)
    return [seed_student(p, i, rng) for i, p in enumerate(PROFILES)]


def _spread_reviews(ids: list[int], rng: random.Random) -> None:
    """Only 2-3 reviews are due right now (so the badge is believable); the rest are scheduled over the coming days."""
    now = datetime.now(timezone.utc)
    for sid in ids:
        rows = db.query("SELECT concept_id FROM reviews WHERE student_id=?", (sid,))
        rng.shuffle(rows)
        limit = rng.choice([2, 3])
        for k, r in enumerate(rows):
            due = now - timedelta(hours=rng.uniform(1, 20)) if k < limit else now + timedelta(hours=rng.uniform(6, 24 * 9))
            db.execute("UPDATE reviews SET due_at=? WHERE student_id=? AND concept_id=?", (due.isoformat(timespec="seconds"), sid, r["concept_id"]))


PREREQ_GAP = 0.25   # a concept may sit at most this far above its weakest prerequisite

# The demo student's headline story is written down, not left to simulation luck, because the Judge tour depends on it:
# "Series circuits keeps going wrong. You don't have a series problem: you believe current gets used up, in Charge & current."
STORY_STUDENT = "Aarav Sharma"
STORY_MASTERY = {"C1": 0.36, "C2": 0.50, "C3": 0.44, "C4": 0.46, "C5": 0.28, "C6": 0.22, "C7": 0.34}
STORY_C5_PATH = [0.52, 0.44, 0.37, 0.31, 0.28]     # Series circuits slipping over five practice answers (feeds the sparkline)
STORY_QUOTES = ["bulb mein current kha jaata hai isliye aage kam bachta hai", "resistor ke baad current kam ho jata hai", "current use ho jata hai bulb mein"]


def _apply_demo_story(ids: list[int]) -> None:
    row = db.one("SELECT id FROM students WHERE name=? AND is_demo=1 ORDER BY id DESC LIMIT 1", (STORY_STUDENT,))
    if not row or row["id"] not in ids:
        return
    sid, graph, now = row["id"], content.concepts(), datetime.now(timezone.utc)
    m = lm.get_mastery(sid)
    m.update(STORY_MASTERY)
    lm.save_mastery(sid, m)
    # the evidence: "Current gets used up" shown three times, still unresolved
    db.execute("DELETE FROM student_misconceptions WHERE student_id=? AND misconception_id='MC01'", (sid,))
    db.execute("INSERT INTO student_misconceptions (student_id, misconception_id, count, last_seen, resolved, last_quote) VALUES (?,?,?,?,0,?)",
               (sid, "MC01", 3, (now - timedelta(hours=5)).isoformat(timespec="seconds"), STORY_QUOTES[0]))
    # five practice answers on Series circuits, the last three wrong, with the quotes that show the idea
    db.execute("DELETE FROM attempts WHERE student_id=? AND concept_id='C5' AND phase='practice'", (sid,))
    question = {"stem": "Two identical bulbs are in series with a battery. How does the current after the second bulb compare with the current before the first?",
                "options": ["Smaller", "The same", "Larger", "Zero"], "correct_index": 1, "concept_id": "C5", "difficulty": 2,
                "distractor_misconceptions": {"0": "MC01", "2": "MC_UNKNOWN", "3": "MC01"}, "explanation": "The same current flows through every part of a series circuit.", "source": "seed"}
    prev = 0.58
    for k, after in enumerate(STORY_C5_PATH):
        correct = k < 2
        when = (now - timedelta(days=2, hours=-3 * k)).isoformat(timespec="seconds")
        deltas = [{"concept_id": "C5", "name": graph["C5"]["name"], "before": prev, "after": after, "reason": "answered correctly" if correct else "answered wrong"}]
        db.execute("INSERT INTO attempts (student_id, question_json, concept_id, difficulty, chosen_index, correct, reasoning_text, reasoning_mode, misconception_id, misconception_confidence, "
                   "is_careless, phase, delta_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,0,'practice',?,?)",
                   (sid, json.dumps(question), "C5", 2, 1 if correct else 0, 1 if correct else 0, None if correct else STORY_QUOTES[(k - 2) % 3], None if correct else "voice",
                    None if correct else "MC01", None if correct else 0.9, json.dumps({"deltas": deltas}), when))
        prev = after
    db.execute("UPDATE mastery SET attempts=?, correct=? WHERE student_id=? AND concept_id='C5'", (5, 2, sid))
    # keep the story clean: Series circuits is the ONE concept he is struggling on, and "Current gets used up" the one misconception he holds
    db.execute("DELETE FROM attempts WHERE student_id=? AND phase='practice' AND concept_id<>'C5'", (sid,))
    db.execute("UPDATE mastery SET attempts=1, correct=0 WHERE student_id=? AND concept_id<>'C5' AND attempts>1", (sid,))
    db.execute("DELETE FROM student_misconceptions WHERE student_id=? AND misconception_id<>'MC01'", (sid,))
    # a classmate shares the idea, so the teacher co-pilot has a real "Current gets used up" group (Aarav + Rohan)
    mate = db.one("SELECT id FROM students WHERE name='Rohan Verma' AND is_demo=1 ORDER BY id DESC LIMIT 1")
    if mate:
        db.execute("DELETE FROM student_misconceptions WHERE student_id=? AND misconception_id='MC01'", (mate["id"],))
        db.execute("INSERT INTO student_misconceptions (student_id, misconception_id, count, last_seen, resolved, last_quote) VALUES (?,?,?,?,0,?)",
                   (mate["id"], "MC01", 2, (now - timedelta(hours=9)).isoformat(timespec="seconds"), "current kam ho jaata hai bulb ke baad"))


def _enforce_prerequisite_order(ids: list[int]) -> None:
    """A student cannot be strong on Series circuits while Ohm's law is at 10%: cap every concept at (weakest prerequisite + 25 points)."""
    graph = content.concepts()
    for sid in ids:
        m = lm.get_mastery(sid)
        for cid in content.concept_order():            # prerequisites come first, so a cap cascades down the graph
            pre = graph[cid]["prerequisites"]
            if pre:
                m[cid] = round(min(m[cid], min(m[p] for p in pre) + PREREQ_GAP), 3)
        lm.save_mastery(sid, m)


def export_fixture() -> None:
    """Regenerate backend/data/demo_class.json from a fresh simulation:  python -m app.ps02.seed"""
    _wipe_demo()
    ids = simulate()
    _apply_demo_story(ids)
    _enforce_prerequisite_order(ids)
    _spread_reviews(ids, random.Random(7))
    marks = ",".join("?" * len(ids))
    dump = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "students": db.query(f"SELECT * FROM students WHERE id IN ({marks})", ids)}
    for table in ("mastery", "attempts", "reviews", "student_misconceptions"):
        dump[table] = db.query(f"SELECT * FROM {table} WHERE student_id IN ({marks})", ids)
    FIXTURE.write_text(json.dumps(dump, indent=0), encoding="utf-8")


def _shift(value, delta: timedelta):
    if not value:
        return value
    return (datetime.fromisoformat(value) + delta).isoformat(timespec="seconds") if "T" in value else (datetime.fromisoformat(value + "+00:00") + delta).isoformat(timespec="seconds")


def _insert_rows(c, dump: dict, id_map: dict[int, int], delta) -> None:
    """Insert the fixture's rows for the students in ``id_map`` (fixture id -> live id), one batched statement per table and column set: on Postgres every
    separate statement is a network round trip, so a few hundred single inserts would take many seconds."""
    for table in ("mastery", "attempts", "reviews", "student_misconceptions"):
        groups: dict[tuple, list[tuple]] = {}
        for row in dump[table]:
            if row["student_id"] not in id_map:
                continue
            row = dict(row)
            row["student_id"] = id_map[row["student_id"]]
            row.pop("id", None)
            for f in _TIME_FIELDS[table]:
                row[f] = _shift(row.get(f), delta)
            groups.setdefault(tuple(row), []).append(tuple(row.values()))
        for cols, rows in groups.items():
            c.executemany(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", rows)


def load_fixture() -> dict:
    """Insert the pre-simulated class in one transaction, moving every timestamp so the history ends 'just now' (reviews fall due as they would have)."""
    dump = json.loads(FIXTURE.read_text(encoding="utf-8"))
    delta = datetime.now(timezone.utc) - datetime.fromisoformat(dump["generated_at"])
    ids: dict[int, int] = {}
    with db.get_conn() as c:
        for s in dump["students"]:
            cur = c.execute("INSERT INTO students (name, class_section, is_demo) VALUES (?,?,1)", (s["name"], s["class_section"]))
            ids[s["id"]] = cur.lastrowid
        _insert_rows(c, dump, ids, delta)
    return {"class_section": CLASS, "students": [{"id": ids[s["id"]], "name": s["name"]} for s in dump["students"]]}


TOUR_STUDENTS = ("Aarav Sharma", "Rohan Verma")     # the tour's student and the classmate who shares his misconception


def reset_tour_students() -> dict:
    """Put the Judge tour's students back to the fixture state IN PLACE (same ids, nobody else touched), so a tour always starts from the same story
    without deleting rows another visitor might be using. Falls back to a full reseed when the demo class does not exist yet."""
    from app.ps02 import srs
    live = {r["name"]: r["id"] for r in db.query("SELECT id, name FROM students WHERE is_demo=1 ORDER BY id")}
    if not FIXTURE.exists() or any(n not in live for n in TOUR_STUDENTS):
        result = reseed()
        live = {s["name"]: s["id"] for s in result["students"]}
        srs.set_time_travel(False)
        return {"id": live[STORY_STUDENT], "name": STORY_STUDENT, "reseeded": True}
    dump = json.loads(FIXTURE.read_text(encoding="utf-8"))
    delta = datetime.now(timezone.utc) - datetime.fromisoformat(dump["generated_at"])
    by_name = {s["name"]: s["id"] for s in dump["students"]}
    with db.get_conn() as c:
        sids = [live[n] for n in TOUR_STUDENTS]
        marks = ",".join("?" * len(sids))
        for table in ("mastery", "attempts", "reviews", "student_misconceptions", "dialogues", "assignment_students", "doubts", "misconception_checks"):
            c.execute(f"DELETE FROM {table} WHERE student_id IN ({marks})", tuple(sids))
        _insert_rows(c, dump, {by_name[n]: live[n] for n in TOUR_STUDENTS}, delta)
        c.execute("DELETE FROM assignments WHERE id NOT IN (SELECT assignment_id FROM assignment_students)")
        c.execute("DELETE FROM ps02_cache WHERE cache_key LIKE 'q:%'")
    srs.set_time_travel(False)
    return {"id": live[STORY_STUDENT], "name": STORY_STUDENT, "reseeded": False}


def reseed(class_section: str = CLASS) -> dict:
    """Wipe the demo class and rebuild it (from the fixture when present, else by simulating). Real students are untouched."""
    _wipe_demo()
    if FIXTURE.exists():
        return load_fixture()
    ids = simulate()
    return {"class_section": CLASS, "students": [{"id": i, "name": PROFILES[k][0]} for k, i in enumerate(ids)]}


def ensure_seeded() -> None:
    if not db.one("SELECT id FROM students WHERE is_demo=1 LIMIT 1"):
        reseed()


if __name__ == "__main__":   # kept for old habits: use  python -m app.ps02.reseed --regenerate
    db.init_db()
    export_fixture()
    print(f"wrote {FIXTURE}")
