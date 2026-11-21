"""Unit tests: BKT update, prerequisite propagation, diagnostic seeding, calibration, SM-2."""
import math
from datetime import datetime, timedelta, timezone

from app import db
from app.ps02 import calibration, content, learner_model as lm, srs


def test_posterior_known_values():
    # p=0.5, correct: 0.5*0.9 / (0.5*0.9 + 0.5*0.25) = 0.45/0.575
    assert math.isclose(lm.posterior(0.5, True), 0.45 / 0.575)
    # p=0.5, wrong: 0.05 / (0.05 + 0.375)
    assert math.isclose(lm.posterior(0.5, False), 0.05 / 0.425)


def test_correct_raises_wrong_lowers():
    post = 0.45 / 0.575
    assert math.isclose(lm.bkt_update(0.5, True), post + (1 - post) * 0.15)      # posterior, then the learning transition
    assert math.isclose(lm.bkt_update(0.5, False), 0.05 / 0.425)                 # a miss: posterior only, no learning
    for p in (0.15, 0.4, 0.8):
        assert lm.bkt_update(p, False) < p                                      # a wrong answer never raises mastery
    assert lm.bkt_update(0.05, False) == 0.05                                    # ...and mastery has a 5% floor
        assert lm.bkt_update(p, False, weight=lm.WRONG_WEIGHT) < p


def test_bounds_and_weight():
    for p in (0.0, 0.01, 0.5, 0.99, 1.0):
        for ok in (True, False):
            assert 0.05 <= lm.bkt_update(p, ok) <= 0.99
    full = lm.bkt_update(0.5, False)
    soft = lm.bkt_update(0.5, False, weight=0.3)
    assert full < soft < 0.5   # careless slip hurts less


def test_seed_from_diagnostic():
    seeded = lm.seed_from_diagnostic({"C1": (True, 1), "C3": (False, 1), "C6": (True, 3), "L1": (False, 3)})
    assert seeded["C1"] == 0.60 and seeded["C6"] == 0.70
    assert seeded["C3"] == 0.15 and seeded["L1"] == 0.25
    assert seeded["C2"] == 0.60                       # untested: mean of its only prerequisite C1
    assert math.isclose(seeded["C5"], 0.15)           # prerequisite C3
    assert seeded["M1"] == 0.3                        # no prerequisites, untested -> default
    assert set(seeded) == set(content.concepts())


def test_wrong_with_prerequisite_misconception_hits_prerequisite_at_half_weight():
    m = {c: 0.5 for c in content.concepts()}
    # MC01 belongs to C1 (current) and C5; the question is on C5 (series) whose prerequisite chain includes C1
    deltas = lm.apply_answer(m, "C5", False, 2, misconception_id="MC01")
    by = {d["concept_id"]: d for d in deltas}
    assert set(by) == {"C5", "C1"}
    main_drop = 0.5 - by["C5"]["after"]
    pre_drop = 0.5 - by["C1"]["after"]
    assert 0 < pre_drop < main_drop
    assert math.isclose(pre_drop, 0.5 * main_drop, rel_tol=1e-6)
    assert by["C1"]["reason"].startswith("prerequisite effect")


def test_misconception_on_unrelated_concept_does_not_propagate():
    m = {c: 0.5 for c in content.concepts()}
    deltas = lm.apply_answer(m, "C6", False, 2, misconception_id="MC13")   # MC13 is about E2: not a prerequisite of C6
    assert [d["concept_id"] for d in deltas] == ["C6"]


def test_careless_error_has_smaller_penalty_and_no_propagation():
    a = {c: 0.5 for c in content.concepts()}
    b = dict(a)
    lm.apply_answer(a, "C5", False, 2, misconception_id="MC01")
    lm.apply_answer(b, "C5", False, 2, misconception_id="MC01", careless=True)
    assert b["C5"] > a["C5"]
    assert b["C1"] == 0.5


def test_hard_correct_nudges_prerequisites_up():
    m = {c: 0.4 for c in content.concepts()}
    deltas = lm.apply_answer(m, "C6", True, 3)
    by = {d["concept_id"]: d for d in deltas}
    assert set(by) == {"C6", "C3", "C5"}
    assert by["C3"]["after"] > 0.4
    assert (by["C3"]["after"] - 0.4) < (by["C6"]["after"] - 0.4)   # smaller than the main update
    easy = {c: 0.4 for c in content.concepts()}
    assert [d["concept_id"] for d in lm.apply_answer(easy, "C6", True, 2)] == ["C6"]


def test_frontier_weakest_respects_prerequisites_and_falls_back():
    m = {c: 0.8 for c in content.concepts()}
    m["C1"] = 0.2            # C1 is a root, weak
    m["C3"] = 0.1            # weaker, but its prerequisite C1 is not >= 0.5, so not on the frontier
    assert lm.frontier_weakest(m, 1) == ["C1"]
    all_low = {c: 0.2 for c in content.concepts()}
    all_low["L1"] = 0.1
    assert lm.frontier_weakest(all_low, 1) == ["L1"]
    # nothing qualifies: every root is below the bar for its dependents but roots themselves have no prerequisites -> still frontier
    assert lm.frontier_weakest({c: 0.1 for c in content.concepts()}, 3)


def test_difficulty_mapping_and_streaks():
    assert [calibration.base_difficulty(p) for p in (0.2, 0.4, 0.7, 0.71)] == [1, 2, 2, 3]
    right = [{"difficulty": 2, "correct": 1}] * 3
    wrong = [{"difficulty": 2, "correct": 0}] * 2
    assert calibration.adjust_for_streak(2, right) == 3
    assert calibration.adjust_for_streak(2, wrong) == 1
    assert calibration.adjust_for_streak(3, right) == 3 and calibration.adjust_for_streak(1, [{"difficulty": 1, "correct": 0}] * 2) == 1
    assert calibration.adjust_for_streak(2, [{"difficulty": 2, "correct": 1}, {"difficulty": 2, "correct": 0}, {"difficulty": 2, "correct": 1}]) == 2


def test_why_string_mentions_percent_and_dependent():
    text = calibration.why("C3", 0.32, 1, 1)
    assert "32%" in text and "Ohm's law" in text and "prerequisite for" in text and "difficulty 1" in text


def test_sm2_standard_progression():
    e, i, r = srs.sm2(2.5, 0, 0, 4)
    assert (i, r) == (1, 1) and math.isclose(e, 2.5)
    e, i, r = srs.sm2(e, i, r, 4)
    assert (i, r) == (6, 2)
    e, i, r = srs.sm2(e, i, r, 5)
    assert r == 3 and i == round(6 * e) and e > 2.5
    e, i, r = srs.sm2(e, i, r, 1)   # failure resets
    assert (i, r) == (1, 0)
    assert srs.sm2(1.3, 6, 2, 0)[0] == 1.3   # easiness floor


def test_quality_scale():
    assert srs.quality(True, fast=True) == 5 and srs.quality(True) == 4
    assert srs.quality(False, careless=True) == 3
    assert srs.quality(False, has_misconception=True) == 1 and srs.quality(False) == 2


def test_time_travel_makes_a_day_a_minute():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    srs.set_time_travel(False)
    assert srs.due_at(6, now) == now + timedelta(days=6)
    srs.set_time_travel(True)
    try:
        assert srs.due_at(6, now) == now + timedelta(minutes=6)
    finally:
        srs.set_time_travel(False)


def test_persistence_roundtrip_and_reviews_due():
    db.init_db()
    sid = db.execute("INSERT INTO students (name, class_section) VALUES (?,?)", ("T", "10-B"))
    assert lm.get_mastery(sid)["C1"] == 0.3
    lm.save_mastery(sid, {"C1": 0.6, "C3": 0.2}, touched={"C3": False})
    got = lm.mastery_details(sid)
    assert got["C1"]["p_known"] == 0.6 and got["C3"]["attempts"] == 1 and got["C3"]["correct"] == 0
    lm.save_mastery(sid, {"C3": 0.4}, touched={"C3": True})
    assert lm.mastery_details(sid)["C3"]["attempts"] == 2 and lm.mastery_details(sid)["C3"]["correct"] == 1
    past = datetime.now(timezone.utc) - timedelta(days=3)
    srs.record(sid, "C3", 4, now=past)
    due = srs.due_reviews(sid)
    assert len(due) == 1 and due[0]["due"] is True and due[0]["name"] == "Ohm's law & resistance"
