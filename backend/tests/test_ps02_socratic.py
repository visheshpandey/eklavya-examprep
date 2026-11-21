"""Socratic dialogue: resolves only when the student explains the idea, caps at 4 turns, falls back safely, and moves BKT / SM-2."""
import pytest
from fastapi.testclient import TestClient

from app import db
from app.ai import gemini
from app.errors import LLMError
from app.main import create_app
from app.ps02 import content, learner_model as lm, service, socratic

client = TestClient(create_app())
QUESTION = content.diagnostic()[7]   # D08, charge & current: option 0 is built from MC01


def wrong_attempt():
    sid = service.create_student("Dia", "9-Z")["id"]
    lm.save_mastery(sid, {c: 0.3 for c in content.concepts()})
    res = service.record_answer(sid, QUESTION, 0, reasoning="current kam ho jata hai", mode="text", misconception_id="MC01", confidence=0.9)
    return sid, res["attempt_id"]


def verdict(understanding, say="Achha, aur batao?", still=True, move="question"):
    return lambda *a, **k: {"understanding": understanding, "still_holds_misconception": still, "next_move": move, "say": say}


def test_start_opens_with_a_guiding_question_and_is_idempotent():
    sid, att = wrong_attempt()
    d = client.post("/api/dialogue/start", json={"student_id": sid, "attempt_id": att, "language": "hinglish"}).json()
    assert d["status"] == "open" and d["progress"] == "holds" and d["transcript"][0]["role"] == "tutor"
    assert "ammeter" in d["say"] and d["misconception"]["id"] == "MC01"
    assert client.post("/api/dialogue/start", json={"student_id": sid, "attempt_id": att}).json()["dialogue_id"] == d["dialogue_id"]
    sid2, att2 = wrong_attempt()
    eng = client.post("/api/dialogue/start", json={"student_id": sid2, "attempt_id": att2, "language": "english"}).json()
    assert "ammeter" in eng["say"] and "kha" not in eng["say"]      # English opener, not the Hinglish one


def test_no_dialogue_without_a_misconception():
    sid = service.create_student("Dia2", "9-Z")["id"]
    res = service.record_answer(sid, QUESTION, 1, careless=True)   # careless slip: nothing to talk out of
    r = client.post("/api/dialogue/start", json={"student_id": sid, "attempt_id": res["attempt_id"]})
    assert r.status_code == 422


def test_resolves_only_when_the_judge_says_resolved_and_gain_beats_plain_correct(monkeypatch):
    sid, att = wrong_attempt()
    d = client.post("/api/dialogue/start", json={"student_id": sid, "attempt_id": att}).json()
    before = lm.get_mastery(sid)["C1"]
    monkeypatch.setattr(gemini, "llm_json", verdict("partial", "Sahi disha mein ho, aur socho."))
    r1 = client.post("/api/dialogue/reply", json={"student_id": sid, "dialogue_id": d["dialogue_id"], "text": "shayad kam hota hai"}).json()
    assert r1["status"] == "open" and r1["progress"] == "wavering" and "mastery_changes" not in r1
    assert lm.get_mastery(sid)["C1"] == before                       # a partial answer does not change mastery
    monkeypatch.setattr(gemini, "llm_json", verdict("resolved", "Bilkul sahi!", still=False, move="confirm"))
    r2 = client.post("/api/dialogue/reply", json={"student_id": sid, "dialogue_id": d["dialogue_id"], "text": "current same rehta hai, sirf energy use hoti hai", "mode": "voice"}).json()
    assert r2["status"] == "resolved" and r2["progress"] == "resolved" and r2["reveal"]["correction"]
    gain = lm.get_mastery(sid)["C1"] - before
    assert 0 < gain <= socratic.MAX_RESOLVE_GAIN + 1e-9              # a resolved dialogue lifts mastery, but never by more than 25 points
    resolved = db.one("SELECT resolved FROM student_misconceptions WHERE student_id=? AND misconception_id='MC01'", (sid,))
    assert resolved["resolved"] == 1
    again = client.post("/api/dialogue/reply", json={"student_id": sid, "dialogue_id": d["dialogue_id"], "text": "thanks"}).json()
    assert again["status"] == "resolved" and len(again["transcript"]) == len(r2["transcript"])   # closed: no further turns


def test_four_unresolved_turns_explain_and_schedule_an_early_review(monkeypatch):
    sid, att = wrong_attempt()
    d = client.post("/api/dialogue/start", json={"student_id": sid, "attempt_id": att}).json()
    monkeypatch.setattr(gemini, "llm_json", verdict("none", "Ek aur baar socho."))
    last = None
    for i in range(socratic.MAX_TURNS):
        last = client.post("/api/dialogue/reply", json={"student_id": sid, "dialogue_id": d["dialogue_id"], "text": f"pata nahi {i}"}).json()
    assert last["status"] == "unresolved" and last["turns_used"] == 4
    assert last["reveal"]["correction"] and last["reveal"]["analogy"] and last["review"]["interval_days"] == 1
    due = db.one("SELECT due_at FROM reviews WHERE student_id=? AND concept_id='C1'", (sid,))["due_at"]
    from datetime import datetime, timezone
    assert 0 < (datetime.fromisoformat(due) - datetime.now(timezone.utc)).total_seconds() <= 31 * 60   # back within the hour
    resolved = db.one("SELECT resolved FROM student_misconceptions WHERE student_id=? AND misconception_id='MC01'", (sid,))
    assert resolved["resolved"] == 0


def test_judge_failure_falls_back_and_never_resolves(monkeypatch):
    sid, att = wrong_attempt()
    d = client.post("/api/dialogue/start", json={"student_id": sid, "attempt_id": att, "language": "english"}).json()

    def boom(*a, **k):
        raise LLMError("down")
    monkeypatch.setattr(gemini, "llm_json", boom)
    text = "current is the flow of charge and charge is not used up, the same current leaves the bulb"
    r = client.post("/api/dialogue/reply", json={"student_id": sid, "dialogue_id": d["dialogue_id"], "text": text, "language": "english"}).json()
    assert r["status"] == "open" and r["verdict"]["source"] == "heuristic" and r["say"]
    assert r["progress"] == "wavering"      # shows credit for the right words, but only the model may declare it resolved


def test_invalid_judge_output_is_sanitised(monkeypatch):
    sid, att = wrong_attempt()
    d = client.post("/api/dialogue/start", json={"student_id": sid, "attempt_id": att}).json()
    monkeypatch.setattr(gemini, "llm_json", lambda *a, **k: {"understanding": "AMAZING", "next_move": "shout", "say": "ok"})
    r = client.post("/api/dialogue/reply", json={"student_id": sid, "dialogue_id": d["dialogue_id"], "text": "hmm"}).json()
    assert r["status"] == "open" and r["verdict"]["understanding"] == "none" and r["verdict"]["next_move"] == "hint"


def test_dialogue_belongs_to_its_student():
    sid, att = wrong_attempt()
    d = client.post("/api/dialogue/start", json={"student_id": sid, "attempt_id": att}).json()
    other = service.create_student("Other", "9-Z")["id"]
    assert client.post("/api/dialogue/reply", json={"student_id": other, "dialogue_id": d["dialogue_id"], "text": "hi"}).status_code == 404


def test_hedged_call_uses_the_backup_model_when_the_primary_is_slow(monkeypatch):
    import time
    from app.ps02 import llm

    def fake(system, prompt, required_keys=(), temperature=0.5, timeout_ms=None, model=None):
        if model is None:
            time.sleep(1.5)
            raise LLMError("primary overloaded")
        return {"ok": model}
    monkeypatch.setattr(gemini, "llm_json", fake)
    t = time.monotonic()
    out = llm.hedged_json("s", "p", ("ok",), 0.1, deadline_s=5, hedge_after_s=0.2)
    assert out["ok"] and time.monotonic() - t < 1.2          # did not wait for the slow primary


def test_hedged_call_raises_after_the_deadline_when_nobody_answers(monkeypatch):
    import time
    from app.ps02 import llm
    monkeypatch.setattr(gemini, "llm_json", lambda *a, **k: time.sleep(2) or {"x": 1})
    t = time.monotonic()
    with pytest.raises(LLMError):
        llm.hedged_json("s", "p", (), 0.1, deadline_s=0.5, hedge_after_s=0.1)
    assert time.monotonic() - t < 1.5


def test_fallback_hints_never_reveal_the_answer(monkeypatch):
    sid, att = wrong_attempt()
    d = client.post("/api/dialogue/start", json={"student_id": sid, "attempt_id": att, "language": "hinglish"}).json()

    def boom(*a, **k):
        raise LLMError("down")
    monkeypatch.setattr(gemini, "llm_json", boom)
    mc = content.misconceptions()["MC01"]
    for i in range(3):
        r = client.post("/api/dialogue/reply", json={"student_id": sid, "dialogue_id": d["dialogue_id"], "text": "pata nahi"}).json()
        assert r["verdict"]["source"] == "heuristic"
        assert mc["analogy"] not in r["say"] and mc["correction"] not in r["say"]
        if r["status"] != "open":
            break


def test_a_clearly_correct_first_reply_resolves_immediately(monkeypatch):
    sid, att = wrong_attempt()
    d = client.post("/api/dialogue/start", json={"student_id": sid, "attempt_id": att}).json()
    monkeypatch.setattr(gemini, "llm_json", verdict("resolved", "Bilkul sahi!", still=False, move="confirm"))
    r = client.post("/api/dialogue/reply", json={"student_id": sid, "dialogue_id": d["dialogue_id"], "text": "current same rehta hai, bulb sirf energy leta hai"}).json()
    assert r["status"] == "resolved" and r["turns_used"] == 1 and r["mastery_changes"]


def test_resolved_gain_is_capped_at_25_points_even_from_a_very_low_start(monkeypatch):
    sid, att = wrong_attempt()
    lm.save_mastery(sid, {"C1": 0.10})
    d = client.post("/api/dialogue/start", json={"student_id": sid, "attempt_id": att}).json()
    monkeypatch.setattr(gemini, "llm_json", verdict("resolved", "Sahi!", still=False, move="confirm"))
    r = client.post("/api/dialogue/reply", json={"student_id": sid, "dialogue_id": d["dialogue_id"], "text": "charge use nahi hota"}).json()
    for m in r["mastery_changes"]:
        assert m["after"] - m["before"] <= 0.25 + 1e-9
    assert lm.get_mastery(sid)["C1"] <= 0.35 + 1e-9


def test_reseed_command_removes_test_students_and_rebuilds_the_class():
    from app.ps02 import reseed
    sid = service.create_student("QA Check", "10-B")["id"]
    service.create_student("Real One", "10-B")
    assert reseed.delete_by_name(["qa check", "nobody"]) == ["QA Check"]
    assert db.one("SELECT id FROM students WHERE id=?", (sid,)) is None
    out = reseed.reset_all()
    assert len(out["students"]) == 6 and db.one("SELECT COUNT(*) AS n FROM students")["n"] == 6      # every other student is gone too
    assert db.one("SELECT COUNT(*) AS n FROM dialogues WHERE student_id NOT IN (SELECT id FROM students)")["n"] == 0
