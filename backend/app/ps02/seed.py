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


def seed_student(profile, index: int, rng: random.Random, attempts: int = 30) -> int:
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
    for sid in [r["id"] for r in db.query("SELECT id FROM students WHERE is_demo=1")]:
        for table in ("mastery", "attempts", "reviews", "student_misconceptions"):
            db.execute(f"DELETE FROM {table} WHERE student_id=?", (sid,))
        db.execute("DELETE FROM students WHERE id=?", (sid,))
    db.execute("DELETE FROM ps02_cache WHERE cache_key LIKE 'reteach:%'")


def simulate() -> list[int]:
    """Run the scripted students through the real BKT / misconception / SM-2 code (slow: thousands of small DB writes)."""
    rng = random.Random(2611)
    return [seed_student(p, i, rng) for i, p in enumerate(PROFILES)]


def export_fixture() -> None:
    """Regenerate backend/data/demo_class.json from a fresh simulation:  python -m app.ps02.seed"""
    _wipe_demo()
    ids = simulate()
    marks = ",".join("?" * len(ids))
    dump = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "students": db.query(f"SELECT * FROM students WHERE id IN ({marks})", ids)}
    for table in ("mastery", "attempts", "reviews", "student_misconceptions"):
        dump[table] = db.query(f"SELECT * FROM {table} WHERE student_id IN ({marks})", ids)
    FIXTURE.write_text(json.dumps(dump, indent=0), encoding="utf-8")


def _shift(value, delta: timedelta):
    if not value:
        return value
    return (datetime.fromisoformat(value) + delta).isoformat(timespec="seconds") if "T" in value else (datetime.fromisoformat(value + "+00:00") + delta).isoformat(timespec="seconds")


def load_fixture() -> dict:
    """Insert the pre-simulated class in one transaction, moving every timestamp so the history ends 'just now' (reviews fall due as they would have)."""
    dump = json.loads(FIXTURE.read_text(encoding="utf-8"))
    delta = datetime.now(timezone.utc) - datetime.fromisoformat(dump["generated_at"])
    ids: dict[int, int] = {}
    with db.get_conn() as c:
        for s in dump["students"]:
            cur = c.execute("INSERT INTO students (name, class_section, is_demo) VALUES (?,?,1)", (s["name"], s["class_section"]))
            ids[s["id"]] = cur.lastrowid
        for table in ("mastery", "attempts", "reviews", "student_misconceptions"):
            for row in dump[table]:
                row = dict(row)
                row["student_id"] = ids[row["student_id"]]
                row.pop("id", None)
                for f in _TIME_FIELDS[table]:
                    row[f] = _shift(row.get(f), delta)
                cols = ",".join(row)
                c.execute(f"INSERT INTO {table} ({cols}) VALUES ({','.join('?' * len(row))})", tuple(row.values()))
    return {"class_section": CLASS, "students": [{"id": ids[s["id"]], "name": s["name"]} for s in dump["students"]]}


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


if __name__ == "__main__":
    db.init_db()
    export_fixture()
    print(f"wrote {FIXTURE}")
