"""The Judge tour's reset: the demo student goes back to the known story in place, and nobody else is disturbed."""
import pytest
from fastapi.testclient import TestClient

from app import db
from app.ai import gemini
from app.main import create_app
from app.ps02 import content, copilot, learner_model as lm, reseed, rootcause, seed, service, srs

client = TestClient(create_app())


@pytest.fixture(autouse=True)
def fresh():
    reseed.reset_all()
    yield
    srs.set_time_travel(False)


def sid_of(name):
    return db.one("SELECT id FROM students WHERE name=? AND is_demo=1", (name,))["id"]


def snapshot(sid):
    return {"mastery": lm.get_mastery(sid), "attempts": db.one("SELECT COUNT(*) AS n FROM attempts WHERE student_id=?", (sid,))["n"],
            "mc": sorted((m["id"], m["count"]) for m in service.active_misconceptions(sid))}


def test_reset_restores_the_story_in_place_and_leaves_everyone_else_alone(monkeypatch):
    aarav, rohan, diya = sid_of("Aarav Sharma"), sid_of("Rohan Verma"), sid_of("Diya Patel")
    known, diya_before = snapshot(aarav), snapshot(diya)
    # a visitor changes Aarav: wrong answers, a resolved misconception, an assignment, time travel on
    lm.save_mastery(aarav, {c: 0.9 for c in content.concepts()})
    db.execute("UPDATE student_misconceptions SET resolved=1 WHERE student_id=?", (aarav,))
    q = content.diagnostic()[7]
    for _ in range(3):
        service.record_answer(aarav, {**q, "concept_id": "C5"}, 0)
    client.post("/api/teacher/assign", json={"misconception_id": "MC01"})
    srs.set_time_travel(True)
    assert snapshot(aarav) != known

    r = client.post("/api/demo/tour-reset").json()["student"]
    assert r == {"id": aarav, "name": "Aarav Sharma", "reseeded": False}              # the SAME id: nobody holding it gets a 404
    assert snapshot(aarav) == known
    assert snapshot(diya) == diya_before                                               # an unrelated student is untouched
    assert sid_of("Rohan Verma") == rohan and ("MC01", 2) in snapshot(rohan)["mc"]
    assert srs.time_travel() is False
    assert db.one("SELECT COUNT(*) AS n FROM assignments")["n"] == 0
    assert copilot.groups("10-B")["groups"][0]["assignment"] is None
    t = rootcause.trace("C5", lm.get_mastery(aarav), service.active_misconceptions(aarav))
    assert rootcause.struggling(aarav) == ["C5"] and t["root"]["concept_id"] == "C1" and t["path"] == ["C5", "C3", "C1"]
    assert [p["p_known"] for p in service.mastery_history(aarav, "C5")] == seed.STORY_C5_PATH


def test_reset_is_idempotent_and_does_not_duplicate_rows():
    aarav = sid_of("Aarav Sharma")
    first = snapshot(aarav)
    for _ in range(3):
        client.post("/api/demo/tour-reset")
    assert snapshot(aarav) == first
    assert db.one("SELECT COUNT(*) AS n FROM students WHERE is_demo=1")["n"] == 6
    assert db.one("SELECT COUNT(*) AS n FROM mastery WHERE student_id=?", (aarav,))["n"] == 21


def test_reset_builds_the_demo_class_when_it_does_not_exist():
    reseed.delete_students([r["id"] for r in db.query("SELECT id FROM students")])
    assert db.one("SELECT COUNT(*) AS n FROM students")["n"] == 0
    r = client.post("/api/demo/tour-reset").json()["student"]
    assert r["reseeded"] is True and r["name"] == "Aarav Sharma"
    assert snapshot(r["id"])["mc"] == [("MC01", 3)]


def test_reset_leaves_real_students_alone():
    real = service.create_student("Real Visitor", "10-B")["id"]
    lm.save_mastery(real, {"C1": 0.77})
    client.post("/api/demo/tour-reset")
    assert lm.get_mastery(real)["C1"] == 0.77 and service.get_student(real)["name"] == "Real Visitor"
