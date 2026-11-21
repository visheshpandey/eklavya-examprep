"""🎯 Board-exam marks: weightage data, predicted score range, marks-ranked fixes, and the teacher's class view."""
from fastapi.testclient import TestClient

from app import db
from app.main import create_app
from app.ps02 import board, content, reseed, service

client = TestClient(create_app())


def test_weightage_covers_every_concept_and_is_labelled_approximate():
    d = board._data()
    assert set(d["marks"]) == set(content.concepts())
    assert abs(sum(d["marks"].values()) - d["total_marks"]) < 1e-9
    assert "Approximate" in d["label"]


def test_a_new_student_gets_a_wide_range_around_a_middling_score():
    sid = service.create_student("BoardNew", "9-Q")["id"]
    try:
        r = client.get("/api/ps02/board", params={"student_id": sid}).json()
        assert r["approximate"] is True and r["total"] == 25.0
        assert 0 <= r["low"] <= r["predicted"] <= r["high"] <= 25
        assert r["high"] - r["low"] > 5                     # no evidence yet: the range is honest about it
        assert [c["chapter"] for c in r["chapters"]] == ["Light", "Human Eye", "Electricity", "Magnetism"]
        assert abs(sum(c["predicted"] for c in r["chapters"]) - r["predicted"]) < 0.6 and r["fixes"] == [] and r["top_fix"] is None
    finally:
        reseed.delete_by_name(["BoardNew"])


def test_more_evidence_narrows_the_range_and_mastery_moves_the_score(monkeypatch):
    sid = service.create_student("BoardMore", "9-Q")["id"]
    try:
        before = client.get("/api/ps02/board", params={"student_id": sid}).json()
        for cid in content.concept_order():
            db.execute("INSERT OR REPLACE INTO mastery (student_id, concept_id, p_known, attempts, correct, last_seen) VALUES (?,?,?,?,?,?)", (sid, cid, 0.9, 12, 11, "2026-01-01T00:00:00+00:00"))
        after = client.get("/api/ps02/board", params={"student_id": sid}).json()
        assert after["predicted"] > before["predicted"] + 5 and after["high"] - after["low"] < before["high"] - before["low"]
    finally:
        reseed.delete_by_name(["BoardMore"])


def test_fixes_are_ranked_by_marks_and_vanish_once_fixed():
    sid = service.create_student("BoardFix", "9-Q")["id"]
    try:
        service._note_misconception(sid, "MC01", "x")        # concept C1: the root of the electricity chain
        service._note_misconception(sid, "MC12", "y")        # a lens-power slip, lower in the chain
        r = client.get("/api/ps02/board", params={"student_id": sid}).json()
        marks = [f["marks"] for f in r["fixes"]]
        assert marks == sorted(marks, reverse=True) and [f["rank"] for f in r["fixes"]] == [1, 2] and r["top_fix"] == r["fixes"][0] and all(m > 0 for m in marks)
        db.execute("UPDATE student_misconceptions SET resolved=1 WHERE student_id=? AND misconception_id='MC01'", (sid,))
        assert [f["misconception_id"] for f in client.get("/api/ps02/board", params={"student_id": sid}).json()["fixes"]] == ["MC12"]
    finally:
        reseed.delete_by_name(["BoardFix"])


def test_marks_gain_counts_the_concepts_that_build_on_the_fixed_one():
    p = {c: 0.2 for c in content.concepts()}
    m = board.marks()
    direct_only = sum(m[c] * 0.8 * board.RECOVER for c in content.misconceptions()["MC01"]["concept_ids"])
    assert board.marks_gain("MC01", p) > round(direct_only, 1)
    perfect = {c: 1.0 for c in content.concepts()}
    assert board.marks_gain("MC01", perfect) == 0.0


def test_the_teacher_overview_has_a_class_average_and_the_top_three_by_marks():
    client.post("/api/demo/seed-class")
    b = client.get("/api/teacher/overview").json()["board"]
    assert b["approximate"] is True and 0 < b["predicted_avg"] < b["total"] and 1 <= len(b["top"]) <= 3
    assert [t["marks"] for t in b["top"]] == sorted((t["marks"] for t in b["top"]), reverse=True)
    assert all(t["students"] >= 1 and t["marks_each"] > 0 for t in b["top"])
    assert board.class_board([])["top"] == []


def test_an_unknown_student_is_a_404():
    assert client.get("/api/ps02/board", params={"student_id": 999999}).status_code == 404
