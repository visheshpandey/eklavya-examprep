"""Streaming primitives: partial JSON string extraction and the hedged stream."""
import time

import pytest

from app.errors import LLMError
from app.ps02 import llm_stream as llm


def test_partial_string_grows_and_handles_escapes():
    key = "say"
    assert llm.partial_string('{"understanding": "none", "sa', key) is None
    assert llm.partial_string('{"say": "Hel', key) == ("Hel", False)
    assert llm.partial_string('{"say": "Hello \\"you\\"\\nok", "x": 1}', key) == ('Hello "you"\nok', True)
    assert llm.partial_string('{"say": "tab\\', key) == ("tab", False)                       # a dangling escape waits for more text
    assert llm.partial_string('{"say": "\\u0928\\u092e', key) == ("नम", False)       # unicode escapes decode (Devanagari)
    assert llm.partial_string('{"say": "half \\u09', key) == ("half ", False)


def fake_worker(script):
    """script: {tag: [(delay_s, kind, value), ...]}"""
    def worker(q, tag, model, system, prompt, temperature, timeout_ms):
        for delay, kind, value in script.get(tag, []):
            time.sleep(delay)
            q.put((tag, kind, value))
    return worker


def test_stream_emits_deltas_then_final(monkeypatch):
    chunks = ['{"understanding": "partial", "sa', 'y": "Sahi ', 'disha mein", "next_move": "hint"}']
    monkeypatch.setattr(llm, "_worker", fake_worker({"primary": [(0, "chunk", c) for c in chunks] + [(0, "done", None)]}))
    events = list(llm.stream_json("s", "p", "say", ("understanding", "say")))
    deltas = "".join(v for k, v in events if k == "delta")
    assert deltas == "Sahi disha mein" and events[-1][0] == "final" and events[-1][1]["understanding"] == "partial"


def test_stream_hedges_to_the_backup_when_the_primary_is_silent(monkeypatch):
    backup = [(0.05, "chunk", '{"say": "from backup"}'), (0, "done", None)]
    monkeypatch.setattr(llm, "_worker", fake_worker({"primary": [(3.0, "chunk", '{"say": "late"}')], "backup": backup}))
    t = time.monotonic()
    events = list(llm.stream_json("s", "p", "say", hedge_after_s=0.2, deadline_s=5))
    assert events[-1][1]["say"] == "from backup" and time.monotonic() - t < 1.5


def test_stream_falls_over_when_the_primary_errors(monkeypatch):
    monkeypatch.setattr(llm, "_worker", fake_worker({"primary": [(0, "error", RuntimeError("503"))], "backup": [(0, "chunk", '{"say": "ok"}'), (0, "done", None)]}))
    assert list(llm.stream_json("s", "p", "say", deadline_s=5))[-1][1]["say"] == "ok"


def test_stream_raises_when_everything_fails_or_is_too_slow(monkeypatch):
    monkeypatch.setattr(llm, "_worker", fake_worker({"primary": [(0, "error", RuntimeError("a"))], "backup": [(0, "error", RuntimeError("b"))]}))
    with pytest.raises(LLMError):
        list(llm.stream_json("s", "p", "say", deadline_s=3))
    monkeypatch.setattr(llm, "_worker", fake_worker({"primary": [(2, "chunk", "{}")], "backup": [(2, "chunk", "{}")]}))
    with pytest.raises(LLMError):
        list(llm.stream_json("s", "p", "say", hedge_after_s=0.1, deadline_s=0.6))


def test_stream_raises_if_the_winner_dies_midway(monkeypatch):
    monkeypatch.setattr(llm, "_worker", fake_worker({"primary": [(0, "chunk", '{"say": "par'), (0, "error", RuntimeError("cut"))]}))
    seen = []
    with pytest.raises(LLMError):
        for _kind, text in llm.stream_json("s", "p", "say", deadline_s=3):
            seen.append(text)
    assert seen == ["par"]          # the partial text was already delivered: the caller must replace it


# ---------------------------------------------------------------- the streaming endpoints
import json as _json  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app.main import create_app  # noqa: E402
from app.ps02 import content, learner_model as lm, service  # noqa: E402

api = TestClient(create_app())


def _wrong_attempt():
    sid = service.create_student("Streamer", "9-Z")["id"]
    lm.save_mastery(sid, {c: 0.3 for c in content.concepts()})
    q = content.diagnostic()[7]          # D08: option 0 is built from MC01
    res = service.record_answer(sid, q, 0, reasoning="x", misconception_id="MC01", confidence=0.9)
    return sid, res["attempt_id"]


def _events(response):
    return [_json.loads(line) for line in response.text.splitlines() if line.strip()]


def test_reasoning_stream_sends_a_quick_read_then_text_then_the_final_result(monkeypatch):
    sid, att = _wrong_attempt()
    chunks = ['{"misconception_id": "MC01", "confidence": 0.92, "feedback": "Current kha', 'ta nahi hai, bulb sirf energy leta hai.", "feedback_alt": "Current is not used up.", ',
              '"evidence": "current kha jaata hai", "is_careless_error": false, "reasoning_sound": false, "new_label": "", "fix": ""}']
    monkeypatch.setattr(llm, "_worker", fake_worker({"primary": [(0, "chunk", c) for c in chunks] + [(0, "done", None)]}))
    ev = _events(api.post("/api/practice/reasoning/stream", json={"student_id": sid, "attempt_id": att, "reasoning_text": "bulb mein current kha jaata hai", "language": "hinglish"}))
    kinds = [e["type"] for e in ev]
    assert kinds[0] == "quick" and kinds[-1] == "final" and "delta" in kinds           # a first impression before any model text
    assert kinds.index("quick") < kinds.index("delta") < kinds.index("final")
    assert "".join(e["text"] for e in ev if e["type"] == "delta") == "Current khata nahi hai, bulb sirf energy leta hai."
    final = ev[-1]["result"]
    assert final["diagnosis"]["misconception_id"] == "MC01" and final["diagnosis"]["source"] == "ai"
    assert final["diagnosis"]["feedback_hinglish"].startswith("Current khata") and final["diagnosis"]["feedback_english"] == "Current is not used up."
    assert final["mastery_changes"] and final["trace"][0]["tool"] == "detect_misconception"


def test_reasoning_stream_falls_back_to_the_keyword_matcher_when_the_models_fail(monkeypatch):
    sid, att = _wrong_attempt()
    monkeypatch.setattr(llm, "_worker", fake_worker({"primary": [(0, "error", RuntimeError("503"))], "backup": [(0, "error", RuntimeError("503"))]}))
    ev = _events(api.post("/api/practice/reasoning/stream", json={"student_id": sid, "attempt_id": att, "reasoning_text": "bulb mein current kha jaata hai"}))
    assert [e["type"] for e in ev] == ["quick", "final"] and ev[-1]["result"]["diagnosis"]["source"] == "heuristic"


def _open_dialogue(sid, att):
    return api.post("/api/dialogue/start", json={"student_id": sid, "attempt_id": att}).json()["dialogue_id"]


def test_dialogue_reply_streams_the_tutors_words_before_the_final_result(monkeypatch):
    sid, att = _wrong_attempt()
    did = _open_dialogue(sid, att)
    chunks = ['{"understanding": "partial", "say": "Sahi disha mein ho. ', 'Ab batao, current kahan jaata hai?", "still_holds_misconception": true, "next_move": "question"}']
    monkeypatch.setattr(llm, "_worker", fake_worker({"primary": [(0, "chunk", c) for c in chunks] + [(0, "done", None)]}))
    ev = _events(api.post("/api/dialogue/reply/stream", json={"student_id": sid, "dialogue_id": did, "text": "shayad kam nahi hota"}))
    assert [e["type"] for e in ev][-1] == "final" and any(e["type"] == "delta" for e in ev)
    assert "".join(e["text"] for e in ev if e["type"] == "delta") == "Sahi disha mein ho. Ab batao, current kahan jaata hai?"
    res = ev[-1]["result"]
    assert res["progress"] == "wavering" and res["transcript"][-1]["text"] == "Sahi disha mein ho. Ab batao, current kahan jaata hai?"


def test_dialogue_stream_can_resolve_and_returns_the_mastery_jump(monkeypatch):
    sid, att = _wrong_attempt()
    did = _open_dialogue(sid, att)
    chunks = ['{"understanding": "resolved", "say": "Bilkul sahi!", "still_holds_misconception": false, "next_move": "confirm"}']
    monkeypatch.setattr(llm, "_worker", fake_worker({"primary": [(0, "chunk", chunks[0]), (0, "done", None)]}))
    res = _events(api.post("/api/dialogue/reply/stream", json={"student_id": sid, "dialogue_id": did, "text": "charge use nahi hota"}))[-1]["result"]
    assert res["status"] == "resolved" and res["mastery_changes"][0]["after"] - res["mastery_changes"][0]["before"] <= 0.25 + 1e-9


def test_dialogue_stream_replaces_partial_text_when_the_model_dies_midway(monkeypatch):
    sid, att = _wrong_attempt()
    did = _open_dialogue(sid, att)
    monkeypatch.setattr(llm, "_worker", fake_worker({"primary": [(0, "chunk", '{"understanding": "none", "say": "Soch'), (0, "error", RuntimeError("cut"))]}))
    ev = _events(api.post("/api/dialogue/reply/stream", json={"student_id": sid, "dialogue_id": did, "text": "pata nahi", "language": "english"}))
    kinds = [e["type"] for e in ev]
    assert kinds == ["delta", "replace", "final"] and ev[-1]["result"]["verdict"]["source"] == "heuristic"
    assert ev[1]["text"] == ev[-1]["result"]["transcript"][-1]["text"]           # the stale partial text is swapped for the real reply


def test_stream_endpoints_404_for_unknown_students():
    assert api.post("/api/practice/reasoning/stream", json={"student_id": 999999, "attempt_id": 1, "reasoning_text": "x"}).status_code == 404
    assert api.post("/api/dialogue/reply/stream", json={"student_id": 999999, "dialogue_id": 1, "text": "x"}).status_code == 404
