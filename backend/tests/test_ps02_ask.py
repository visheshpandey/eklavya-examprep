"""Ask a doubt + notes, built on the original Eklavya pipeline (Gemini stubbed)."""
import pytest
from fastapi.testclient import TestClient

from app import db
from app.agents import voice_tutor
from app.ai import gemini
from app.main import create_app
from app.ps02 import content, doubts, learner_model as lm, notes, service

client = TestClient(create_app())
NOTES_TEXT = ("Electric current is the rate of flow of charge through a conductor. Current is measured in amperes. "
              "Charge is conserved, so the same current leaves a bulb as enters it; the bulb only converts electrical energy into light and heat. "
              "Ohm's law says the potential difference across a conductor is proportional to the current through it at constant temperature.\n\n"
              "Resistors in parallel: the voltage across each branch is the same and the total resistance is less than the smallest branch.")


@pytest.fixture(autouse=True)
def stub_llm(monkeypatch):
    def fake(system, prompt, required_keys=(), temperature=0.7, timeout_ms=None, model=None):
        if "tag a CBSE" in system or "You tag" in system:
            wrong = "use up" in prompt.lower() or "kha jaata" in prompt.lower()
            return {"concept_id": "C1", "misconception_id": "MC01" if wrong else None, "confidence": 0.9 if wrong else 0.1, "evidence": "bulb uses up current" if wrong else ""}
        if "Target difficulty" in prompt:     # practice question generation
            used = "OWN NOTES" in prompt
            return {"stem": "Notes-based charge question number " + str(abs(hash(prompt)) % 100000) + "?", "options": ["0.2 C", "5 C", "12 C", "20 C"], "correct_index": 3,
                    "distractor_misconceptions": {"0": "MC21", "1": "MC_UNKNOWN", "2": "MC_UNKNOWN"}, "difficulty": 1, "explanation": "Charge = current x time.", "used_notes": used}
        if "topics" in prompt.lower() and "JSON" in prompt:
            return {"topics": ["Electric current", "Ohm's law", "Parallel resistors"]}
        return {"answer": "Current is the flow of charge. It is not used up.", "follow_up_question": "What does a bulb use?", "source_topic": "Electric current", "used_notes": True}
    from app.agents import document_intelligence
    from app.ai import embeddings
    monkeypatch.setattr(gemini, "llm_json", fake)
    monkeypatch.setattr(voice_tutor, "llm_json", fake)
    monkeypatch.setattr(document_intelligence, "llm_json", fake)       # the original ingest reads topics and a title through its own reference
    monkeypatch.setattr(embeddings, "vectors_for", lambda ids: {})       # keyword retrieval only: no embedding calls in tests


def new_student(name="AskTest", section="9-Z"):
    """Test students live in their own class so they never disturb the 10-B demo-class assertions elsewhere."""
    return client.post("/api/students", json={"name": name, "class_section": section}).json()["id"]


def test_doubt_without_notes_is_answered_from_general_knowledge_and_tagged():
    sid = new_student()
    r = client.post("/api/ps02/doubt", json={"student_id": sid, "question": "What is electric current?", "language": "english"}).json()
    assert r["answer"] and r["general"] is True and r["grounded"] is False and r["notes_available"] is False
    assert r["concept"]["id"] == "C1" and r["misconception"] is None and r["mastery_changes"] == []
    row = db.one("SELECT student_id, concept_id FROM doubts WHERE id=?", (r["doubt_id"],))
    assert row["student_id"] == sid and row["concept_id"] == "C1"


def test_doubt_that_reveals_a_misconception_is_logged_and_nudges_mastery():
    sid = new_student("MisDoubt")
    lm.save_mastery(sid, {"C1": 0.6})
    r = client.post("/api/ps02/doubt", json={"student_id": sid, "question": "Why does the bulb use up the current?", "language": "english"}).json()
    assert r["misconception"]["id"] == "MC01" and r["concept"]["id"] == "C1"
    m = r["mastery_changes"][0]
    assert m["after"] < m["before"] and m["before"] - m["after"] < 0.1            # a small nudge, not a penalty for asking
    active = service.active_misconceptions(sid)
    assert any(x["id"] == "MC01" and "use up" in x["quote"] for x in active)
    assert doubts.list_doubts(sid, "C1")["total"] == 1


def test_notes_upload_then_doubt_is_answered_from_the_notes_with_a_citation():
    sid = new_student("Noter")
    r = client.post("/api/ps02/notes", data={"student_id": str(sid), "text": NOTES_TEXT}).json()
    assert r["scope"] == "mine" and r["chunks"] >= 1 and r["file_name"]
    assert [n["file_name"] for n in client.get("/api/ps02/notes", params={"student_id": sid}).json()["notes"]] == [r["file_name"]]
    a = client.post("/api/ps02/doubt", json={"student_id": sid, "question": "Is current used up by a bulb? same current leaves the bulb", "language": "english"}).json()
    assert a["notes_available"] is True and a["grounded"] is True and a["source_document_name"] == r["file_name"]


def test_class_notes_from_the_teacher_reach_every_student_in_the_class():
    section = "7-Q"
    teacher_upload = client.post("/api/ps02/notes", data={"class_section": section, "text": NOTES_TEXT}).json()
    assert teacher_upload["scope"] == "class"
    sid = client.post("/api/students", json={"name": "ClassKid", "class_section": section}).json()["id"]
    listed = client.get("/api/ps02/notes", params={"student_id": sid}).json()["notes"]
    assert [n["scope"] for n in listed] == ["class"]
    other = client.post("/api/students", json={"name": "OtherClass", "class_section": "8-Z"}).json()["id"]
    assert client.get("/api/ps02/notes", params={"student_id": other}).json()["notes"] == []     # another class does not see them
    ctx = notes.context_for(sid, "electric current charge flow conductor")
    assert ctx and ctx["citation"]["file_name"] == teacher_upload["file_name"]
    assert notes.context_for(other, "electric current charge flow conductor") is None


def test_student_cannot_delete_class_notes_but_can_delete_their_own():
    sid = client.post("/api/students", json={"name": "Deleter", "class_section": "6-D"}).json()["id"]
    own = client.post("/api/ps02/notes", data={"student_id": str(sid), "text": NOTES_TEXT}).json()
    cls = client.post("/api/ps02/notes", data={"class_section": "6-D", "text": NOTES_TEXT + " extra words for a distinct document"}).json()
    assert client.delete(f"/api/ps02/notes/{cls['id']}", params={"student_id": sid}).status_code == 404
    assert client.delete(f"/api/ps02/notes/{own['id']}", params={"student_id": sid}).status_code == 200
    assert [n["scope"] for n in client.get("/api/ps02/notes", params={"student_id": sid}).json()["notes"]] == ["class"]


def test_tagging_falls_back_to_a_heuristic_when_the_model_fails(monkeypatch):
    from app.errors import LLMError

    def boom(*a, **k):
        raise LLMError("down")
    monkeypatch.setattr(gemini, "llm_json", boom)
    t = doubts.tag("why does the bulb use up the current? bulb mein current kha jaata hai", None)
    assert t["concept_id"] in content.concepts() or t["concept_id"] is None
    assert doubts.heuristic_tag("bulb mein current kha jaata hai", None)["misconception_id"] == "MC01"


def test_unknown_student_is_404_for_doubts_and_notes():
    assert client.post("/api/ps02/doubt", json={"student_id": 999999, "question": "hello there"}).status_code == 404
    assert client.get("/api/ps02/notes", params={"student_id": 999999}).status_code == 404


def test_practice_questions_use_the_notes_and_cite_them_only_when_relevant():
    sid = new_student("NotesQ")
    plain = client.get("/api/practice/next", params={"student_id": sid, "concept_id": "C1"}).json()
    assert plain["note"] is None                                   # no notes uploaded: nothing to cite
    up = client.post("/api/ps02/notes", data={"student_id": str(sid), "text": NOTES_TEXT}).json()
    q = client.get("/api/practice/next", params={"student_id": sid, "concept_id": "C1"}).json()
    assert q["note"] and q["note"]["file_name"] == up["file_name"]     # shown as "From your notes: <file> · <topic>"
    far = client.get("/api/practice/next", params={"student_id": sid, "concept_id": "M4"}).json()
    assert far["note"] is None                                     # the notes say nothing about domestic circuits: no citation


def test_doubts_show_on_the_concept_panel_and_the_teacher_dashboard():
    from app.ps02 import reseed
    client.post("/api/demo/seed-class")
    sid = new_student("DoubtDash", "10-B")
    try:
        _doubts_on_panel_and_dashboard(sid)
    finally:
        reseed.delete_by_name(["DoubtDash"])


def _doubts_on_panel_and_dashboard(sid):
    client.post("/api/ps02/doubt", json={"student_id": sid, "question": "Why does the bulb use up the current?", "language": "english"})
    client.post("/api/ps02/doubt", json={"student_id": sid, "question": "What is electric current?", "language": "english"})
    node = next(n for n in client.get("/api/mastery", params={"student_id": sid}).json()["nodes"] if n["id"] == "C1")
    assert node["doubts_count"] == 2 and len(node["recent_doubts"]) == 2 and node["recent_doubts"][0]["question"].startswith("What is")
    ov = client.get("/api/teacher/overview", params={"class_section": "10-B"}).json()
    assert ov["doubts"]["total"] >= 2
    assert ov["doubts"]["by_concept"][0]["name"] == "Electric charge & current" and ov["doubts"]["by_concept"][0]["count"] >= 2
    assert any(d["student"] == "DoubtDash" and d["misconception"] == "Current gets used up" for d in ov["doubts"]["recent"])


def test_original_eklavya_ask_still_works_for_its_own_users(monkeypatch):
    """The PS02 bridge must not change how the original tutor behaves for a normal Eklavya user."""
    g = client.post("/api/guest").json()
    headers = {"Authorization": f"Bearer {g['token']}"}
    r = client.post("/api/tutor/ask", headers=headers, json={"question": "what is current", "language": "english"})
    assert r.status_code == 400 and "No notes" in r.json()["error"]     # the original rule: its own Ask needs notes (the PS02 doubt route handles the no-notes case)
