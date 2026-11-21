"""Root-cause tracer, the tutor agent's logged tool calls, and starting a dialogue straight from a misconception."""
import pytest
from fastapi.testclient import TestClient

from app import db
from app.ai import gemini
from app.errors import LLMError
from app.main import create_app
from app.ps02 import agent, content, learner_model as lm, rootcause, service

client = TestClient(create_app())
MC01 = {"id": "MC01", "label": "Current gets used up", "count": 3, "quote": "bulb mein current kha jaata hai"}


def mastery(**over):
    m = {c: 0.7 for c in content.concepts()}
    m.update(over)
    return m


def student(name="AgentKid"):
    return service.create_student(name, "9-Z")["id"]


def test_root_cause_scores_by_mastery_evidence_and_distance():
    t = rootcause.trace("C5", mastery(C1=0.2, C3=0.45, C5=0.22), [MC01])
    assert t["root"]["concept_id"] == "C1" and t["root"]["misconception"]["id"] == "MC01"
    assert t["path"] == ["C5", "C3", "C1"]                                       # series -> Ohm's law -> charge & current
    expected = (1 - 0.2) * (1 - 0.5 ** 3) * 0.8 ** (2 - 1)                      # (1 - p) x evidence x decay^(distance - 1)
    assert t["root"]["score"] == pytest.approx(expected, abs=1e-3)
    assert [c["score"] for c in t["candidates"]] == sorted((c["score"] for c in t["candidates"]), reverse=True)


def test_no_convincing_root_without_evidence():
    t = rootcause.trace("C5", mastery(C1=0.3, C5=0.2), [])
    assert t["root"] is None and t["path"] == ["C5"]


def test_nearer_ancestor_wins_when_evidence_is_equal():
    mc_c3 = {"id": "MC02", "label": "Battery gives fixed current", "count": 3, "quote": ""}      # belongs to C3 (distance 1 from C5)
    t = rootcause.trace("C5", mastery(C1=0.2, C3=0.2, C5=0.2), [MC01, mc_c3])
    assert t["root"]["concept_id"] == "C3"


def test_explanation_uses_the_model_and_falls_back_to_a_template(monkeypatch):
    t = rootcause.trace("C5", mastery(C1=0.2, C3=0.45, C5=0.22), [MC01])
    rootcause._explain_cache.clear()
    monkeypatch.setattr(gemini, "llm_json", lambda *a, **k: {"text": "You don't have a series problem. You believe current gets used up. Fix that."})
    text, source = rootcause.explain(t, "english")
    assert source == "ai" and "series" in text

    def boom(*a, **k):
        raise LLMError("down")
    rootcause._explain_cache.clear()
    monkeypatch.setattr(gemini, "llm_json", boom)
    text, source = rootcause.explain(t, "english")
    assert source == "template" and "Resistors in series problem" in text and "Current gets used up" in text


def test_struggling_concepts_come_from_repeated_misses():
    sid = student()
    q = content.diagnostic()[7]
    for _ in range(2):
        service.record_answer(sid, {**q, "concept_id": "C5"}, 0)
    assert "C5" in rootcause.struggling(sid)


def test_agent_redirects_to_the_root_cause_and_logs_every_tool_call():
    sid = student("Redirect")
    lm.save_mastery(sid, mastery(C1=0.55, C5=0.2))
    service._note_misconception(sid, "MC01", "bulb mein current kha jaata hai")
    service._note_misconception(sid, "MC01", "current kam ho jata hai")
    service._note_misconception(sid, "MC01", "current use ho jata hai")
    plan = service.plan_next(sid)
    assert plan["concept_id"] == "C1" and plan["root_applied"] is True and plan["focus_concept"] == "C5"
    tools = [s["tool"] for s in plan["trace"]]
    assert tools == ["get_mastery", "pick_concept", "trace_root_cause", "pick_concept", "calibrate_difficulty"]
    assert "root" in plan["trace"][3]["summary"].lower() and "Current gets used up" in plan["why"]
    assert all(s["summary"] for s in plan["trace"])


def test_explicit_choice_is_respected_but_the_root_is_suggested():
    sid = student("Explicit")
    lm.save_mastery(sid, mastery(C1=0.2, C3=0.45, C5=0.22))
    for _ in range(3):
        service._note_misconception(sid, "MC01", "current kha jaata hai")
    plan = service.plan_next(sid, concept_id="C5")
    assert plan["concept_id"] == "C5" and plan["root_applied"] is False
    assert plan["root_cause"]["root"]["concept_id"] == "C1"
    assert [s["tool"] for s in plan["trace"]].count("trace_root_cause") == 1


def test_question_response_carries_the_agent_trace(monkeypatch):
    def fake(system, prompt, required_keys=(), temperature=0.7, timeout_ms=None, model=None):
        return {"stem": "Trace question " + str(abs(hash(prompt)) % 99999) + "?", "options": ["a", "b", "c", "d"], "correct_index": 1,
                "distractor_misconceptions": {"0": "MC01", "2": "MC_UNKNOWN", "3": "MC_UNKNOWN"}, "explanation": "e"}
    monkeypatch.setattr(gemini, "llm_json", fake)
    sid = student("Tracer")
    client.post("/api/diagnostic/submit", json={"student_id": sid, "answers": []})
    q = client.get("/api/practice/next", params={"student_id": sid}).json()
    tools = [s["tool"] for s in q["trace"]]
    assert tools[0] == "get_mastery" and "calibrate_difficulty" in tools and tools[-1] == "generate_question"
    assert "Current gets used up" in q["trace"][-1]["summary"]                  # the distractors' misconception is named
    wrong = next(i for i in range(4) if i != q["options"].index("b"))
    a = client.post("/api/practice/answer", json={"student_id": sid, "question_id": q["question_id"], "chosen_index": wrong}).json()
    assert [s["tool"] for s in a["trace"]] == ["update_mastery", "schedule_review"]


def test_struggles_and_root_cause_endpoints(monkeypatch):
    sid = student("Endpoints")
    lm.save_mastery(sid, mastery(C1=0.2, C3=0.45, C5=0.22))
    for _ in range(3):
        service._note_misconception(sid, "MC01", "bulb mein current kha jaata hai")
    q = content.diagnostic()[7]
    for _ in range(2):
        service.record_answer(sid, {**q, "concept_id": "C5"}, 0)
    s = client.get("/api/ps02/struggles", params={"student_id": sid}).json()["struggles"]
    assert s and s[0]["concept_id"] == "C5" and s[0]["root"]["concept_id"] == "C1" and s[0]["explanation"]
    rootcause._explain_cache.clear()
    monkeypatch.setattr(gemini, "llm_json", lambda *a, **k: {"text": "You don't have a series problem. Fix current first."})
    r = client.get("/api/ps02/root-cause", params={"student_id": sid, "concept_id": "C5", "language": "english"}).json()
    assert r["explanation_source"] == "ai" and r["path"] == ["C5", "C3", "C1"]
    assert client.get("/api/ps02/root-cause", params={"student_id": sid, "concept_id": "ZZ"}).status_code == 404


def test_dialogue_can_start_from_a_misconception_without_an_attempt(monkeypatch):
    sid = student("RootDialogue")
    lm.save_mastery(sid, mastery(C1=0.3))
    d = client.post("/api/dialogue/start", json={"student_id": sid, "misconception_id": "MC01", "concept_id": "C1", "language": "english"}).json()
    assert d["status"] == "open" and d["misconception"]["id"] == "MC01" and "ammeter" in d["say"]
    again = client.post("/api/dialogue/start", json={"student_id": sid, "misconception_id": "MC01", "concept_id": "C1"}).json()
    assert again["dialogue_id"] == d["dialogue_id"]                              # reuses the open one
    monkeypatch.setattr(gemini, "llm_json", lambda *a, **k: {"understanding": "resolved", "still_holds_misconception": False, "next_move": "confirm", "say": "Exactly!"})
    r = client.post("/api/dialogue/reply", json={"student_id": sid, "dialogue_id": d["dialogue_id"], "text": "current is not used up, the bulb uses energy"}).json()
    assert r["status"] == "resolved" and r["mastery_changes"][0]["concept_id"] == "C1"
    bad = client.post("/api/dialogue/start", json={"student_id": sid, "misconception_id": "MC01"})
    assert bad.status_code == 422


def test_the_root_cause_prompt_asks_for_the_requested_language_with_a_hinglish_example(monkeypatch):
    seen = {}

    def fake(system, prompt, required_keys=(), temperature=0.7, timeout_ms=None, model=None):
        seen["system"], seen["prompt"] = system, prompt
        return {"text": "Tumhe series ki problem nahi hai. Pehle current theek karo."}
    monkeypatch.setattr(gemini, "llm_json", fake)
    rootcause._explain_cache.clear()
    t = rootcause.trace("C5", mastery(C1=0.2, C3=0.45, C5=0.22), [MC01])
    text, source = rootcause.explain(t, "hinglish")
    assert source == "ai" and "Tumhe <failing concept> ki problem nahi hai" in seen["system"] and "Language: Hinglish" in seen["prompt"]
    rootcause._explain_cache.clear()
    rootcause.explain(t, "english")
    assert "Language: English" in seen["prompt"]
