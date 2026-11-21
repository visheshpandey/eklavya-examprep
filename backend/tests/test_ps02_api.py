"""End-to-end PS02 loop over HTTP with Gemini stubbed (tests never call the real model)."""
import pytest
from fastapi.testclient import TestClient

from app.ai import gemini
from app.errors import LLMError
from app.main import create_app
from app.ps02 import content, question_gen, seed

client = TestClient(create_app())


def fake_question(system, prompt, required_keys=(), temperature=0.7, timeout_ms=None, model=None):
    if "diagnosing WHY" in system:   # misconception classifier
        return {"misconception_id": "MC01", "confidence": 0.9, "evidence": "bulb current kha jaata hai", "is_careless_error": False, "reasoning_sound": False,
                "feedback_hinglish": "Current khatam nahi hota.", "feedback_english": "Current is not used up."}
    return {"stem": "Two 4 ohm resistors are connected in parallel. What is the equivalent resistance?", "options": ["8 ohm", "2 ohm", "4 ohm", "16 ohm"],
            "correct_index": 1, "distractor_misconceptions": {"0": "MC03", "2": "MC_UNKNOWN", "3": "NOT_A_REAL_ID"}, "difficulty": 2, "concept_id": "C6", "explanation": "1/R = 1/4 + 1/4."}


@pytest.fixture(autouse=True)
def stub_llm(monkeypatch):
    monkeypatch.setattr(gemini, "llm_json", fake_question)


def new_student():
    return client.post("/api/students", json={"name": "Test", "class_section": "9-Z"}).json()["id"]


def test_diagnostic_hides_answers_and_seeds_mastery():
    qs = client.get("/api/diagnostic").json()["questions"]
    assert len(qs) == 14 and all("correct_index" not in q and "distractor_misconceptions" not in q for q in qs)
    sid = new_student()
    bank = {q["id"]: q for q in content.diagnostic()}
    answers = [{"question_id": q["id"], "chosen_index": bank[q["id"]]["correct_index"] if i % 2 else (bank[q["id"]]["correct_index"] + 1) % 4} for i, q in enumerate(qs)]
    r = client.post("/api/diagnostic/submit", json={"student_id": sid, "answers": answers}).json()
    assert r["total"] == 14 and set(r["mastery"]) == set(content.concepts())
    assert all(0 < v < 1 for v in r["mastery"].values())
    m = client.get("/api/mastery", params={"student_id": sid}).json()
    assert len(m["nodes"]) == 21 and m["edges"] and m["weakest"]


def test_full_practice_loop_wrong_answer_reasoning_and_review():
    sid = new_student()
    client.post("/api/diagnostic/submit", json={"student_id": sid, "answers": []})
    q = client.get("/api/practice/next", params={"student_id": sid}).json()
    assert q["why"] and "correct_index" not in q and len(q["options"]) == 4
    wrong = next(i for i in range(4) if i != 1) if False else None   # the stub's shuffled position is unknown: ask the server via a wrong pick below
    stored = None
    for pick in range(4):
        a = client.post("/api/practice/answer", json={"student_id": sid, "question_id": q["question_id"], "chosen_index": pick}).json()
        if not a["correct"]:
            stored = a
            break
        q = client.get("/api/practice/next", params={"student_id": sid}).json()
    assert stored and stored["needs_reasoning"] and stored["mastery_changes"] and stored["review"]["interval_days"] == 1
    before_changes = {c["concept_id"]: c["after"] for c in stored["mastery_changes"]}
    r = client.post("/api/practice/reasoning", json={"student_id": sid, "attempt_id": stored["attempt_id"], "reasoning_text": "bulb mein current kha jaata hai",
                                                    "reasoning_mode": "voice"}).json()
    assert r["diagnosis"]["misconception_id"] == "MC01" and r["misconception"]["label"] and r["diagnosis"]["feedback_hinglish"]
    ms = client.get("/api/misconceptions", params={"student_id": sid}).json()["misconceptions"]
    assert any(m["id"] == "MC01" and "kha jaata" in m["quote"] for m in ms)
    # the informed update replaced the provisional one: mastery is stored once, not double-applied
    now = client.get("/api/mastery", params={"student_id": sid}).json()["nodes"]
    assert all(0.01 <= n["p_known"] <= 0.99 for n in now)
    assert client.get("/api/reviews/due", params={"student_id": sid}).json()["upcoming"]
    hist = client.get("/api/mastery/history", params={"student_id": sid, "concept_id": q["concept_id"]}).json()["points"]
    assert hist


def test_generation_falls_back_when_llm_fails(monkeypatch):
    def boom(*a, **k):
        raise LLMError("down")
    monkeypatch.setattr(gemini, "llm_json", boom)
    q = question_gen.generate("C3", 2, [], [])
    assert q["source"] in ("bank", "cache") and len(q["options"]) == 4
    sid = new_student()
    assert client.get("/api/practice/next", params={"student_id": sid}).status_code == 200


def test_invalid_generated_question_is_rejected_then_falls_back(monkeypatch):
    monkeypatch.setattr(gemini, "llm_json", lambda *a, **k: {"stem": "x", "options": ["a", "a", "b", "c"], "correct_index": 9})
    assert question_gen.generate("L1", 1, [], [])["source"] in ("bank", "cache")


def test_generated_question_is_shuffled_and_map_remapped():
    q = question_gen.generate("C6", 2, ["MC03"], [])
    assert q["source"] == "ai" and q["options"][q["correct_index"]] == "2 ohm"
    assert q["distractor_misconceptions"][str(q["options"].index("8 ohm"))] == "MC03"
    assert q["distractor_misconceptions"][str(q["options"].index("16 ohm"))] == "MC_UNKNOWN"   # unknown id sanitised


def test_careless_error_penalised_less(monkeypatch):
    monkeypatch.setattr(gemini, "llm_json", lambda s, p, *a, **k: {"misconception_id": "NONE", "confidence": 0.8, "evidence": "slip", "is_careless_error": True,
                                                                    "reasoning_sound": True, "feedback_hinglish": "ok", "feedback_english": "ok"})
    sid = new_student()
    client.post("/api/diagnostic/submit", json={"student_id": sid, "answers": []})
    q = client.get("/api/practice/next", params={"student_id": sid}).json()
    wrong = (0 if q["options"][0] != "2 ohm" else 1)
    a = client.post("/api/practice/answer", json={"student_id": sid, "question_id": q["question_id"], "chosen_index": wrong}).json()
    if a["correct"]:
        pytest.skip("stub picked the right answer")
    prov = a["mastery_changes"][0]["after"]
    r = client.post("/api/practice/reasoning", json={"student_id": sid, "attempt_id": a["attempt_id"], "reasoning_text": "I knew it, tapped wrong"}).json()
    assert r["diagnosis"]["is_careless_error"] and r["misconception"] is None
    assert r["mastery_changes"][0]["after"] > prov                      # softer penalty than the provisional wrong
    assert r["review"]["interval_days"] == 1
    assert client.get("/api/misconceptions", params={"student_id": sid}).json()["misconceptions"] == []


def test_seed_and_teacher_dashboard():
    r = client.post("/api/demo/seed-class").json()
    assert len(r["students"]) == 6
    ov = client.get("/api/teacher/overview", params={"class_section": "10-B"}).json()
    assert ov["student_count"] == 6 and len(ov["heatmap"]) == 6 and len(ov["concepts"]) == 21
    gaps = [g["average"] for g in ov["gaps"]]
    assert gaps == sorted(gaps)
    assert ov["top_misconceptions"] and ov["top_misconceptions"][0]["examples"]
    assert ov["at_risk"][0]["name"] == "Rohan Verma"                  # the struggling profile
    by = {h["name"]: h["mastery"] for h in ov["heatmap"]}
    light = lambda n: sum(by[n][c] for c in ("L1", "L2", "L3", "L4", "L5", "L6")) / 6
    elec = lambda n: sum(by[n][c] for c in ("C1", "C3", "C5", "C6")) / 4
    assert light("Aarav Sharma") > elec("Aarav Sharma") + 0.15       # strong in Light, weak in Electricity
    held = {m["id"] for m in ov["top_misconceptions"]}
    assert {"MC01", "MC03"} & held
    rt = client.get("/api/teacher/reteach", params={"class_section": "10-B"}).json()
    assert rt["items"]


def test_seed_is_repeatable_and_does_not_double_students():
    seed.reseed()
    seed.reseed()
    ov = client.get("/api/teacher/overview", params={"class_section": "10-B"}).json()
    assert ov["student_count"] == 6


def test_time_travel_toggle():
    assert client.post("/api/demo/time-travel", json={"on": True}).json()["on"] is True
    assert client.get("/api/demo/time-travel").json()["on"] is True
    client.post("/api/demo/time-travel", json={"on": False})


def test_unknown_student_is_404():
    assert client.get("/api/practice/next", params={"student_id": 99999}).status_code == 404
    assert client.get("/api/health").json() == {"ok": True}      # the original health route, not shadowed


def test_new_student_joins_class_and_shows_on_heatmap():
    client.post("/api/demo/seed-class")
    sid = client.post("/api/students", json={"name": "Newcomer"}).json()
    assert sid["class_section"] == "10-B"
    ov = client.get("/api/teacher/overview", params={"class_section": "10-B"}).json()
    assert "Newcomer" in [r["name"] for r in ov["heatmap"]] and ov["student_count"] == 7


def test_generated_question_never_repeats_a_diagnostic_or_seen_stem(monkeypatch):
    diag_stem = content.diagnostic()[0]["stem"]
    monkeypatch.setattr(gemini, "llm_json", lambda *a, **k: {"stem": diag_stem, "options": ["a", "b", "c", "d"], "correct_index": 0})
    q = question_gen.generate("L1", 1, [], [])
    assert q["stem"] != diag_stem or q["source"] == "bank"   # a repeat is rejected; only the last-resort bank may reuse one
    seen = [content.diagnostic()[i]["stem"] for i in range(14)]
    monkeypatch.setattr(gemini, "llm_json", fake_question)
    assert question_gen.generate("C6", 2, [], seen)["stem"] not in seen


def test_formula_and_unit_misconceptions_are_candidates_for_charge():
    from app.ps02 import misconception
    ids = {m["id"] for m in misconception.candidates("C1")}
    assert {"MC21", "MC22"} <= ids
    q = content.diagnostic()[7]   # D08 on charge & current
    d = misconception.heuristic(q, 0, "charge = current / time so 2/10 = 0.2 C", "C1", None)
    assert d.misconception_id == "MC21"


def test_unknown_misconception_still_returns_specific_label_and_fix(monkeypatch):
    monkeypatch.setattr(gemini, "llm_json", lambda *a, **k: {"misconception_id": "MC_UNKNOWN", "confidence": 0.6, "evidence": "added 2 and 10", "is_careless_error": False,
                                                              "reasoning_sound": False, "new_label": "Added instead of multiplied", "fix": "Charge is current times time.",
                                                              "feedback_hinglish": "Aapne 2 aur 10 jod diye.", "feedback_english": "You added 2 and 10."})
    from app.ps02 import misconception
    r = misconception.classify(content.diagnostic()[7], 0, "I added 2 and 10", "C1", None)
    assert r["label"] == "Added instead of multiplied" and r["fix"]


def test_prefetch_endpoint():
    sid = new_student()
    assert client.post("/api/practice/prefetch", params={"student_id": sid}).json()["started"] is True


def test_badge_and_why_use_the_same_difficulty(monkeypatch):
    # the model labels its question difficulty 3, but the planner decided; the served question must carry the planner's value
    monkeypatch.setattr(gemini, "llm_json", lambda *a, **k: {"stem": "Unique stem for difficulty test?", "options": ["a", "b", "c", "d"], "correct_index": 0, "difficulty": 3})
    sid = new_student()
    client.post("/api/diagnostic/submit", json={"student_id": sid, "answers": []})
    q = client.get("/api/practice/next", params={"student_id": sid}).json()
    assert f"difficulty {q['difficulty']}" in q["why"]
    from app import db
    stored = db.one("SELECT payload FROM ps02_cache WHERE cache_key=?", (f"q:{q['question_id']}",))["payload"]
    assert f'"difficulty": {q["difficulty"]}' in stored


def test_confidence_is_reported_as_a_label():
    from app.ps02 import misconception
    q = content.diagnostic()[7]
    r = misconception.classify(q, 0, "bulb current kha jaata hai", "C1", None)
    assert r["confidence_label"] in ("High", "Medium", "Low")
