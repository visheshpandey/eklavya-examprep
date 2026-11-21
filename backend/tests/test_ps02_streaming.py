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
