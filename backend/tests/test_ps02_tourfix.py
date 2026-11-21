"""Judge-tour fixes: a fixed wrong-on-purpose question read with no model call, the ±15 mastery cap, and the notebook quote."""
from fastapi.testclient import TestClient

from app import db
from app.ai import gemini
from app.main import create_app
from app.ps02 import learner_model as lm, llm_stream, notebook, reseed, service

client = TestClient(create_app())


def student(name="TourFix"):
    return service.create_student(name, "9-T")["id"]


def test_the_tour_question_is_fixed_and_names_a_wrong_option_without_any_model_call(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the tour must not call the model")
    monkeypatch.setattr(gemini, "llm_json", boom)
    monkeypatch.setattr(llm_stream, "_worker", boom)
    sid = student()
    try:
        for kind, concept in (("misconception", "C5"), ("notebook", "C1")):
            q = client.get("/api/practice/next", params={"student_id": sid, "tour": kind}).json()
            stored = service._load_question(q["question_id"])["question"]
            assert q["concept_id"] == concept and stored["tour"] is True
            assert q["tour_wrong_index"] != stored["correct_index"] and "correct_index" not in q
        assert client.get("/api/practice/next", params={"student_id": sid, "tour": "nope"}).status_code == 404
        q = client.get("/api/practice/next", params={"student_id": sid, "tour": "misconception"}).json()
        a = client.post("/api/practice/answer", json={"student_id": sid, "question_id": q["question_id"], "chosen_index": q["tour_wrong_index"]}).json()
        assert a["correct"] is False
        events = [__import__("json").loads(l) for l in client.post("/api/practice/reasoning/stream", json={
            "student_id": sid, "attempt_id": a["attempt_id"], "reasoning_text": "bulb mein current kha jaata hai, isliye resistor ke baad current kam bachta hai", "language": "hinglish"}).text.splitlines() if l.strip()]
        final = events[-1]["result"]
        assert final["misconception"]["id"] == "MC01"                      # named from the words, instantly
    finally:
        reseed.delete_by_name(["TourFix"])


def test_one_answer_never_moves_a_concept_by_more_than_fifteen_points():
    for p in (0.05, 0.3, 0.5, 0.8, 0.97):
        for correct in (True, False):
            m = {c: p for c in ("C1", "C2", "C3", "C4", "C5")}
            for d in lm.apply_answer(m, "C5", correct, 2, misconception_id=None if correct else "MC01"):
                assert abs(d["after"] - d["before"]) <= lm.MAX_ANSWER_CHANGE + 1e-9


def test_the_cap_clamps_a_big_swing():
    m = {c: 0.2 for c in ("C1", "C2", "C3", "C4", "C5")}
    d = lm.apply_answer(m, "C5", True, 1)[0]
    assert round(d["after"] - d["before"], 4) <= 0.15


def test_the_notebook_quote_is_the_students_own_line_not_the_analysis():
    sid = student("NbQuote")
    try:
        r = notebook.analyse(sid, b"x", sample_id="unit")
        ev = r["diagnosis"]["evidence"]
        assert "200" in ev and "mA was not converted" not in ev and "(" not in ev.split(":", 1)[1]
        assert r["notebook"]["source"] == "sample-prepared"                # a built-in page never waits on the vision model
    finally:
        reseed.delete_by_name(["NbQuote"])


def test_the_tour_notebook_sample_is_read_ahead_and_returned_at_once_without_a_second_attempt():
    sid = student("NbAhead")
    try:
        client.get("/api/practice/next", params={"student_id": sid, "tour": "notebook"})     # starts reading the sample page in the background
        entry = notebook._PREPARED[(sid, "unit")]
        assert entry["event"].wait(20)
        before = db.one("SELECT COUNT(*) AS n FROM attempts WHERE student_id=?", (sid,))["n"]
        r = notebook.analyse(sid, b"x", sample_id="unit")
        assert r["readable"] and r["misconception"]["id"] == "MC22" and (sid, "unit") not in notebook._PREPARED
        assert db.one("SELECT COUNT(*) AS n FROM attempts WHERE student_id=?", (sid,))["n"] == before      # the tap added nothing: the work was already done
    finally:
        reseed.delete_by_name(["NbAhead"])
