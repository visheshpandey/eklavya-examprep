"""Teacher co-pilot: misconception groups, cached mini-lessons, assignments to a group, and before -> after (Gemini stubbed)."""
import pytest
from fastapi.testclient import TestClient

from app import db
from app.ai import gemini
from app.errors import LLMError
from app.main import create_app
from app.ps02 import content, copilot, reseed

client = TestClient(create_app())
LESSON = {"title": "Where does the current go?", "hook_demo": "Put two ammeters on either side of a bulb.", "analogy": "Water through a water-wheel.",
          "check_questions": [{"q": "q1?", "a": "a1"}, {"q": "q2?", "a": "a2"}, {"q": "q3?", "a": "a3"}], "script_hinglish": "Aaj hum current ke baare mein baat karenge.",
          "board_notes": ["I same", "energy used"]}


@pytest.fixture(autouse=True)
def fresh_class():
    reseed.reset_all()
    yield


def groups():
    return client.get("/api/teacher/groups", params={"class_section": "10-B"}).json()


def first_group():
    g = groups()["groups"][0]
    return g


def test_students_are_grouped_by_a_shared_active_misconception():
    data = groups()
    gs = data["groups"]
    assert len(gs) >= 3 and all(g["size"] >= 2 for g in gs)
    assert [g["name"] for g in gs][:3] == ["Group A", "Group B", "Group C"]
    assert [g["size"] for g in gs] == sorted((g["size"] for g in gs), reverse=True)
    g = gs[0]
    assert g["misconception"]["label"] and g["students"][0]["quote"] and g["assignment"] is None and g["concept_names"]
    ids = [s["student_id"] for s in g["students"]]
    held = {r["student_id"] for r in db.query("SELECT student_id FROM student_misconceptions WHERE misconception_id=? AND resolved=0 AND count>0", (g["id"],))}
    assert set(ids) == held                                      # exactly the students who hold it right now
    assert isinstance(data["individual_misconceptions"], int)


def test_a_resolved_misconception_leaves_its_group():
    g = first_group()
    sid = g["students"][0]["student_id"]
    db.execute("UPDATE student_misconceptions SET resolved=1 WHERE student_id=? AND misconception_id=?", (sid, g["id"]))
    again = next((x for x in groups()["groups"] if x["id"] == g["id"]), None)
    assert again is None or sid not in [s["student_id"] for s in again["students"]]


def test_lesson_is_generated_once_then_served_from_the_cache(monkeypatch):
    calls = []

    def fake(*a, **k):
        calls.append(1)
        return LESSON
    monkeypatch.setattr(gemini, "llm_json", fake)
    mc = first_group()["id"]
    one = client.get("/api/teacher/lesson", params={"misconception_id": mc, "class_section": "10-B"}).json()
    assert one["source"] == "ai" and one["cached"] is False and len(one["check_questions"]) == 3 and one["script_hinglish"]
    two = client.get("/api/teacher/lesson", params={"misconception_id": mc, "class_section": "10-B"}).json()
    assert two["cached"] is True and two["title"] == one["title"] and len(calls) == 1
    assert groups()["groups"][0]["lesson_ready"] is True
    client.get("/api/teacher/lesson", params={"misconception_id": mc, "class_section": "10-B", "refresh": True})
    assert len(calls) == 2                                            # refresh asks the model again


def test_lesson_falls_back_to_the_catalogue_and_is_not_cached(monkeypatch):
    def boom(*a, **k):
        raise LLMError("down")
    monkeypatch.setattr(gemini, "llm_json", boom)
    mc = first_group()["id"]
    lesson = client.get("/api/teacher/lesson", params={"misconception_id": mc}).json()
    assert lesson["source"] == "catalogue" and len(lesson["check_questions"]) == 3 and lesson["script_hinglish"] and lesson["hook_demo"]
    assert db.one("SELECT 1 AS x FROM ps02_cache WHERE cache_key LIKE 'lesson:%'") is None     # a retry can still get the AI version
    monkeypatch.setattr(gemini, "llm_json", lambda *a, **k: {**LESSON, "check_questions": LESSON["check_questions"][:2]})
    assert client.get("/api/teacher/lesson", params={"misconception_id": mc, "refresh": True}).json()["source"] == "catalogue"   # malformed output is rejected
    assert client.get("/api/teacher/lesson", params={"misconception_id": "NOPE"}).status_code == 404


def test_assign_pushes_the_task_to_each_student_in_the_group_and_counts_before():
    g = first_group()
    r = client.post("/api/teacher/assign", json={"class_section": "10-B", "misconception_id": g["id"]}).json()
    assert r["topped_up"] is False and sorted(r["students"]) == sorted(s["student_id"] for s in g["students"])
    st = r["state"]
    assert st["before"] == g["size"] == st["after"] and st["done"] == 0
    for s in g["students"]:
        mine = client.get("/api/ps02/assignments", params={"student_id": s["student_id"]}).json()["assignments"]
        assert len(mine) == 1 and mine[0]["misconception"]["id"] == g["id"] and mine[0]["concept_id"] in content.concepts()
    again = client.post("/api/teacher/assign", json={"class_section": "10-B", "misconception_id": g["id"]}).json()
    assert again["topped_up"] is True and again["assignment_id"] == r["assignment_id"]            # no duplicate assignment
    assert db.one("SELECT COUNT(*) AS n FROM assignment_students WHERE assignment_id=?", (r["assignment_id"],))["n"] == g["size"]


def test_assign_validates_the_group_and_students():
    g = first_group()
    outsider = next(s["id"] for s in client.get("/api/students", params={"class_section": "10-B"}).json()["students"] if s["id"] not in [x["student_id"] for x in g["students"]])
    assert client.post("/api/teacher/assign", json={"misconception_id": g["id"], "student_ids": [outsider]}).status_code == 422
    assert client.post("/api/teacher/assign", json={"misconception_id": "MC19"}).status_code == 422          # nobody holds it
    one = g["students"][0]["student_id"]
    r = client.post("/api/teacher/assign", json={"misconception_id": g["id"], "student_ids": [one]}).json()
    assert r["students"] == [one] and r["state"]["before"] == 1


def _start_and_reply(sid, mc, concept, monkeypatch, understanding):
    monkeypatch.setattr(gemini, "llm_json", lambda *a, **k: {"understanding": understanding, "still_holds_misconception": understanding != "resolved", "next_move": "hint", "say": "ok"})
    d = client.post("/api/dialogue/start", json={"student_id": sid, "misconception_id": mc, "concept_id": concept}).json()
    return d, lambda: client.post("/api/dialogue/reply", json={"student_id": sid, "dialogue_id": d["dialogue_id"], "text": "charge is conserved, so the same current leaves"}).json()


def test_resolving_the_dialogue_completes_the_assignment_and_moves_before_to_after(monkeypatch):
    g = first_group()
    assert len(g["students"]) >= 2
    r = client.post("/api/teacher/assign", json={"misconception_id": g["id"]}).json()
    first, second = g["students"][0]["student_id"], g["students"][1]["student_id"]
    concept = client.get("/api/ps02/assignments", params={"student_id": first}).json()["assignments"][0]["concept_id"]
    _d, reply = _start_and_reply(first, g["id"], concept, monkeypatch, "resolved")
    assert reply()["status"] == "resolved"
    st = next(x for x in groups()["groups"] if x["id"] == g["id"])["assignment"]       # the group stays listed after it shrinks
    assert st["before"] == g["size"] and st["after"] == g["size"] - 1 and st["done"] == 1 and st["resolved"] == 1
    me = next(s for s in st["students"] if s["student_id"] == first)
    assert me["status"] == "done" and me["outcome"] == "resolved" and me["still_holds"] is False
    assert client.get("/api/ps02/assignments", params={"student_id": first}).json()["assignments"] == []                 # banner gone for them
    assert len(client.get("/api/ps02/assignments", params={"student_id": second}).json()["assignments"]) == 1            # still waiting for the others
    assert r["assignment_id"] == st["id"]


def test_an_unresolved_dialogue_completes_the_task_but_the_student_still_holds_it(monkeypatch):
    g = first_group()
    client.post("/api/teacher/assign", json={"misconception_id": g["id"]})
    sid = g["students"][0]["student_id"]
    concept = client.get("/api/ps02/assignments", params={"student_id": sid}).json()["assignments"][0]["concept_id"]
    _d, reply = _start_and_reply(sid, g["id"], concept, monkeypatch, "none")
    last = None
    for _ in range(4):
        last = reply()
    assert last["status"] == "unresolved"
    st = next(x for x in groups()["groups"] if x["id"] == g["id"])["assignment"]
    me = next(s for s in st["students"] if s["student_id"] == sid)
    assert me["status"] == "done" and me["outcome"] == "unresolved" and me["still_holds"] is True and st["after"] == st["before"]


def test_resetting_the_class_removes_assignments():
    g = first_group()
    client.post("/api/teacher/assign", json={"misconception_id": g["id"]})
    reseed.reset_all()
    assert db.one("SELECT COUNT(*) AS n FROM assignments")["n"] == 0 and db.one("SELECT COUNT(*) AS n FROM assignment_students")["n"] == 0
    assert copilot.groups("10-B")["groups"][0]["assignment"] is None


def test_an_assigned_group_stays_listed_when_everyone_has_resolved_it(monkeypatch):
    g = first_group()
    client.post("/api/teacher/assign", json={"misconception_id": g["id"]})
    concept = client.get("/api/ps02/assignments", params={"student_id": g["students"][0]["student_id"]}).json()["assignments"][0]["concept_id"]
    for s in g["students"]:
        _d, reply = _start_and_reply(s["student_id"], g["id"], concept, monkeypatch, "resolved")
        reply()
    card = next(x for x in groups()["groups"] if x["id"] == g["id"])
    assert card["size"] == 0 and card["assignment"]["before"] == g["size"] and card["assignment"]["after"] == 0 and card["assignment"]["done"] == g["size"]
    assert card["name"] == g["name"]                                  # and it keeps its letter


def test_group_letters_do_not_jump_when_an_assigned_group_shrinks(monkeypatch):
    before = {g["id"]: g["name"] for g in groups()["groups"]}
    g = first_group()
    client.post("/api/teacher/assign", json={"misconception_id": g["id"]})
    sid = g["students"][0]["student_id"]
    concept = client.get("/api/ps02/assignments", params={"student_id": sid}).json()["assignments"][0]["concept_id"]
    _d, reply = _start_and_reply(sid, g["id"], concept, monkeypatch, "resolved")
    reply()                                                           # one of the two students is done: the group is now 1 student
    after = {x["id"]: x["name"] for x in groups()["groups"]}
    assert after[g["id"]] == before[g["id"]] == "Group A"
    assert all(after[k] == before[k] for k in before if k in after and k != g["id"] or k == g["id"])
