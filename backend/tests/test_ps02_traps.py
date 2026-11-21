"""🔒 Verified fixed: Detected -> Resolved -> Verified, trap questions, relapse, inconclusive answers, and the chain shown to students and teachers."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import db
from app.ai import gemini
from app.main import create_app
from app.ps02 import content, copilot, learner_model as lm, question_gen, reseed, seed, service, srs, traps

client = TestClient(create_app())


@pytest.fixture(autouse=True)
def reset():
    yield
    srs.set_time_travel(False)


def make_student(name="Trapper", section="9-Z"):
    return service.create_student(name, section)["id"]


def resolve(sid, mc="MC01", concept="C1", monkeypatch=None):
    """The student holds the misconception, then explains it in a dialogue (Resolved)."""
    service._note_misconception(sid, mc, "bulb mein current kha jaata hai")
    monkeypatch.setattr(gemini, "llm_json", lambda *a, **k: {"understanding": "resolved", "still_holds_misconception": False, "next_move": "confirm", "say": "Exactly!"})
    d = client.post("/api/dialogue/start", json={"student_id": sid, "misconception_id": mc, "concept_id": concept, "language": "english"}).json()
    r = client.post("/api/dialogue/reply", json={"student_id": sid, "dialogue_id": d["dialogue_id"], "text": "charge is conserved"}).json()
    assert r["status"] == "resolved"


def stage(sid, mc="MC01"):
    return traps.stage_of(db.one("SELECT * FROM student_misconceptions WHERE student_id=? AND misconception_id=?", (sid, mc)))


def make_due(sid):
    old = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat(timespec="seconds")
    db.execute("UPDATE misconception_checks SET scheduled_at=? WHERE student_id=?", (old, sid))


def trap_for(sid, mc="MC01"):
    return client.get("/api/ps02/checks/next", params={"student_id": sid, "misconception_id": mc}).json()


def pick(sid, q, wanted):
    """Option index for 'correct' | 'trap' | 'other', using the stored question (the client never sees the key)."""
    stored = service._load_question(q["question_id"])["question"]
    if wanted == "correct":
        return stored["correct_index"]
    mapping = stored["distractor_misconceptions"]
    if wanted == "trap":
        return int(next(k for k, v in mapping.items() if v == stored["trap_mc"]))
    return int(next(k for k, v in mapping.items() if v != stored["trap_mc"]))


def test_resolving_in_dialogue_schedules_a_check_that_is_not_yet_due(monkeypatch):
    sid = make_student()
    service._note_misconception(sid, "MC01", "x")
    assert stage(sid) == "detected"
    resolve(sid, monkeypatch=monkeypatch)
    assert stage(sid) == "resolved"
    c = client.get("/api/ps02/checks", params={"student_id": sid}).json()
    assert c["due"] == [] and len(c["upcoming"]) == 1 and c["upcoming"][0]["misconception_id"] == "MC01" and c["upcoming"][0]["seconds_left"] > 86400   # 2 days
    row = db.one("SELECT * FROM misconception_checks WHERE student_id=?", (sid,))
    assert row["interval_days"] == traps.FIRST_INTERVAL_DAYS == 2 and row["status"] == "pending"
    assert client.get("/api/ps02/checks/next", params={"student_id": sid, "misconception_id": "MC01"}).status_code == 409         # not due yet


def test_time_travel_makes_the_check_due_within_about_two_minutes(monkeypatch):
    sid = make_student("TimeTravel")
    resolve(sid, monkeypatch=monkeypatch)
    assert not client.get("/api/ps02/checks", params={"student_id": sid}).json()["due"]
    client.post("/api/demo/time-travel", json={"on": True})
    c = client.get("/api/ps02/checks", params={"student_id": sid}).json()
    assert c["time_travel"] is True and not c["due"] and c["upcoming"][0]["seconds_left"] <= 120     # 2 minutes, computed on read
    db.execute("UPDATE misconception_checks SET scheduled_at=? WHERE student_id=?", ((datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat(timespec="seconds"), sid))
    assert len(client.get("/api/ps02/checks", params={"student_id": sid}).json()["due"]) == 1


def test_the_demo_helper_makes_pending_checks_due_now(monkeypatch):
    sid = make_student("ForceDue")
    resolve(sid, monkeypatch=monkeypatch)
    assert client.post("/api/demo/checks-due", params={"student_id": sid}).json() == {"ok": True}
    assert len(client.get("/api/ps02/checks", params={"student_id": sid}).json()["due"]) == 1
    assert client.post("/api/demo/checks-due", params={"student_id": 999999}).status_code == 404


def test_the_trap_question_is_hand_written_for_common_misconceptions_and_hides_its_key(monkeypatch):
    sid = make_student("Bank")
    resolve(sid, monkeypatch=monkeypatch)
    make_due(sid)
    q = trap_for(sid)
    assert set(q) >= {"question_id", "stem", "options", "misconception", "concept_name"} and "correct_index" not in q and len(q["options"]) == 4
    stored = service._load_question(q["question_id"])["question"]
    assert stored["source"] == "bank" and stored["trap_mc"] == "MC01"
    trap_text = stored["options"][pick(sid, q, "trap")]
    assert "uses up" in trap_text or "uses up" in trap_text.lower() or "less than" in trap_text.lower() or "some charge" in trap_text   # the trap option is the misconception's
    assert stored["options"][stored["correct_index"]] != trap_text


def test_an_ai_trap_is_built_for_misconceptions_without_a_hand_written_one(monkeypatch):
    prompts = []

    def fake(system, prompt, required_keys=(), temperature=0.7, timeout_ms=None, model=None):
        prompts.append(prompt)
        return {"stem": "A new scenario about light speed in glass number 7?", "options": ["faster", "slower", "same", "zero"], "correct_index": 1,
                "distractor_misconceptions": {"0": "MC10", "2": "MC_UNKNOWN", "3": "MC_UNKNOWN"}, "difficulty": 2, "explanation": "n = c/v"}
    sid = make_student("AiTrap")
    service._note_misconception(sid, "MC10", "light speeds up in glass")
    monkeypatch.setattr(gemini, "llm_json", lambda *a, **k: {"understanding": "resolved", "still_holds_misconception": False, "next_move": "confirm", "say": "ok"})
    d = client.post("/api/dialogue/start", json={"student_id": sid, "misconception_id": "MC10", "concept_id": "L4"}).json()
    client.post("/api/dialogue/reply", json={"student_id": sid, "dialogue_id": d["dialogue_id"], "text": "light slows down"})
    make_due(sid)
    monkeypatch.setattr(gemini, "llm_json", fake)
    q = trap_for(sid, "MC10")
    assert q["stem"].startswith("A new scenario") and "VERIFICATION TRAP" in prompts[0] and "MC10" in prompts[0]
    assert service._load_question(q["question_id"])["question"]["options"][pick(sid, q, "trap")] == "faster"


def test_passing_the_trap_verifies_the_fix(monkeypatch):
    sid = make_student("Passer")
    resolve(sid, monkeypatch=monkeypatch)
    make_due(sid)
    q = trap_for(sid)
    r = client.post("/api/ps02/checks/answer", json={"student_id": sid, "question_id": q["question_id"], "chosen_index": pick(sid, q, "correct")}).json()
    assert r["outcome"] == "verified" and r["stage"] == "verified" and r["correct"] is True and "Verified fixed" in r["message"]
    assert stage(sid) == "verified"
    assert db.one("SELECT status FROM misconception_checks WHERE student_id=?", (sid,))["status"] == "passed"
    c = client.get("/api/ps02/checks", params={"student_id": sid}).json()
    assert c["due"] == [] and c["upcoming"] == [] and [v["misconception_id"] for v in c["verified"]] == ["MC01"]
    assert db.one("SELECT phase FROM attempts WHERE student_id=? ORDER BY id DESC LIMIT 1", (sid,))["phase"] == "verify"
    again = client.post("/api/ps02/checks/answer", json={"student_id": sid, "question_id": q["question_id"], "chosen_index": 0})
    assert again.status_code in (200, 404)


def test_falling_for_the_trap_reactivates_the_misconception_and_reopens_the_dialogue(monkeypatch):
    sid = make_student("Relapser")
    resolve(sid, monkeypatch=monkeypatch)
    make_due(sid)
    before = db.one("SELECT count FROM student_misconceptions WHERE student_id=? AND misconception_id='MC01'", (sid,))["count"]
    q = trap_for(sid)
    r = client.post("/api/ps02/checks/answer", json={"student_id": sid, "question_id": q["question_id"], "chosen_index": pick(sid, q, "trap")}).json()
    assert r["outcome"] == "relapsed" and r["stage"] == "detected" and r["misconception"]["id"] == "MC01" and r["concept_id"]
    row = db.one("SELECT * FROM student_misconceptions WHERE student_id=? AND misconception_id='MC01'", (sid,))
    assert row["resolved"] == 0 and row["verified"] == 0 and row["count"] == before + 1 and row["last_source"] == "trap" and "trap" in row["last_quote"]
    assert any(m["id"] == "MC01" for m in service.active_misconceptions(sid))                    # an active misconception again
    d = client.post("/api/dialogue/start", json={"student_id": sid, "misconception_id": "MC01", "concept_id": r["concept_id"]}).json()
    assert d["status"] == "open" and d["transcript"][0]["role"] == "tutor"                         # talk it through again
    resolve_again = client.post("/api/dialogue/reply", json={"student_id": sid, "dialogue_id": d["dialogue_id"], "text": "charge cannot vanish"}).json()
    assert resolve_again["status"] == "resolved" and stage(sid) == "resolved"
    assert db.one("SELECT status FROM misconception_checks WHERE student_id=?", (sid,))["status"] == "pending"    # a fresh check is scheduled


def test_a_different_wrong_answer_is_inconclusive_and_reschedules_sooner(monkeypatch):
    sid = make_student("Unsure")
    resolve(sid, monkeypatch=monkeypatch)
    make_due(sid)
    q = trap_for(sid)
    first_stem = q["stem"]
    r = client.post("/api/ps02/checks/answer", json={"student_id": sid, "question_id": q["question_id"], "chosen_index": pick(sid, q, "other")}).json()
    assert r["outcome"] == "inconclusive" and r["stage"] == "resolved"
    assert stage(sid) == "resolved"                                                              # NOT reactivated: it was not the old slip
    row = db.one("SELECT * FROM misconception_checks WHERE student_id=?", (sid,))
    assert row["status"] == "pending" and row["interval_days"] == traps.RETRY_INTERVAL_DAYS == 1 and row["attempts"] == 1
    make_due(sid)
    assert trap_for(sid)["stem"] != first_stem                                                   # the retry uses the next hand-written trap


def test_check_answers_are_validated():
    a, b = make_student("A1"), make_student("B1")
    assert client.post("/api/ps02/checks/answer", json={"student_id": a, "question_id": "nope", "chosen_index": 0}).status_code == 404
    plain = service._store_question(a, {**content.diagnostic()[7], "source": "bank"})              # an ordinary question is not a check
    assert client.post("/api/ps02/checks/answer", json={"student_id": a, "question_id": plain, "chosen_index": 0}).status_code == 404
    assert client.get("/api/ps02/checks/next", params={"student_id": a, "misconception_id": "MC01"}).status_code == 404       # nothing pending
    assert client.get("/api/ps02/checks", params={"student_id": 999999}).status_code == 404
    assert client.post("/api/ps02/checks/answer", json={"student_id": b, "question_id": plain, "chosen_index": 0}).status_code == 404   # not their question


def test_shuffling_keeps_the_trap_option_mapped_to_the_misconception():
    q = traps._bank("MC22", 0)
    for _ in range(20):
        s = traps.random_order(q)
        trapped = [s["options"][int(i)] for i, m in s["distractor_misconceptions"].items() if m == "MC22"]
        assert trapped == ["10000 C"] and s["options"][s["correct_index"]] == "10 C"


def test_the_chain_is_visible_on_the_concept_panel_and_in_teacher_groups(monkeypatch):
    sid = make_student("Chain", "10-B")
    try:
        service._note_misconception(sid, "MC01", "bulb mein current kha jaata hai")
        node = lambda: next(n for n in client.get("/api/mastery", params={"student_id": sid}).json()["nodes"] if n["id"] == "C1")
        assert node()["misconception_chain"][0]["stage"] == "detected"
        client.post("/api/demo/seed-class")
        sid2 = make_student("Chain2", "10-B")
        service._note_misconception(sid2, "MC01", "x")
        client.post("/api/teacher/assign", json={"misconception_id": "MC01"})
        resolve(sid, monkeypatch=monkeypatch)
        assert node()["misconception_chain"][0]["stage"] == "resolved"
        make_due(sid)
        q = trap_for(sid)
        client.post("/api/ps02/checks/answer", json={"student_id": sid, "question_id": q["question_id"], "chosen_index": pick(sid, q, "correct")})
        assert node()["misconception_chain"][0]["stage"] == "verified" and node()["misconception_chain"][0]["verified_at"]
        group = next(g for g in copilot.groups("10-B")["groups"] if g["id"] == "MC01")
        me = next(s for s in group["assignment"]["students"] if s["student_id"] == sid)
        assert me["stage"] == "verified" and group["assignment"]["verified"] == 1
        other = next(s for s in group["assignment"]["students"] if s["student_id"] == sid2)
        assert other["stage"] == "detected"
    finally:
        reseed.delete_by_name(["Chain", "Chain2"])


def test_the_tour_reset_clears_checks_for_the_tour_students(monkeypatch):
    reseed.reset_all()
    aarav = db.one("SELECT id FROM students WHERE name='Aarav Sharma' AND is_demo=1")["id"]
    resolve(aarav, monkeypatch=monkeypatch)
    assert db.one("SELECT COUNT(*) AS n FROM misconception_checks WHERE student_id=?", (aarav,))["n"] == 1
    seed.reset_tour_students()
    assert db.one("SELECT COUNT(*) AS n FROM misconception_checks WHERE student_id=?", (aarav,))["n"] == 0
