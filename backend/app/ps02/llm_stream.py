"""Streaming JSON from Gemini for PS02: text of one chosen field is delivered as the model writes it (first words in about a second).

Same hedging as ``llm.hedged_json``: if the primary model has produced nothing after ``hedge_after_s`` (or errors), a second model is raced and
whichever starts producing text first wins.
"""
from __future__ import annotations

import queue
import re
import threading
import time

from app.ai import gemini
from app.config import settings

API_MIN_TIMEOUT_MS = 10000   # Gemini rejects any shorter per-request deadline


def partial_string(buf: str, key: str):
    """The (possibly unfinished) JSON string value of ``key`` in a growing buffer -> (text, closed), or None if it has not started yet."""
    m = re.search(r'"%s"\s*:\s*"' % re.escape(key), buf)
    if not m:
        return None
    i, out = m.end(), []
    simple = {"n": "\n", "t": "\t", '"': '"', "\\": "\\", "/": "/", "r": "", "b": "", "f": ""}
    while i < len(buf):
        c = buf[i]
        if c == "\\":
            if i + 1 >= len(buf):
                break
            n = buf[i + 1]
            if n == "u":
                if i + 6 > len(buf):
                    break
                try:
                    out.append(chr(int(buf[i + 2:i + 6], 16)))
                except ValueError:
                    pass
                i += 6
                continue
            out.append(simple.get(n, n))
            i += 2
            continue
        if c == '"':
            return "".join(out), True
        out.append(c)
        i += 1
    return "".join(out), False


def _worker(q: "queue.Queue", tag: str, model: str, system: str, prompt: str, temperature: float, timeout_ms: int) -> None:
    """One streaming Gemini call; pushes (tag, 'chunk'|'done'|'error', value) onto the queue."""
    try:
        config = gemini.types.GenerateContentConfig(system_instruction=gemini.guarded(system), response_mime_type="application/json", temperature=temperature,
                                                    http_options=gemini.types.HttpOptions(timeout=timeout_ms))
        for chunk in gemini._get_client().models.generate_content_stream(model=model, contents=prompt, config=config):
            if chunk.text:
                q.put((tag, "chunk", chunk.text))
        q.put((tag, "done", None))
    except Exception as exc:  # noqa: BLE001 - reported to the consumer, which decides what to do
        q.put((tag, "error", exc))


def stream_json(system: str, prompt: str, stream_key: str, required_keys=(), temperature: float = 0.5, deadline_s: float = 10.0, hedge_after_s: float = 2.5):
    """Generator of ("delta", new_text) events for the string field ``stream_key`` as it is written, then one ("final", dict).

    Raises LLMError past ``deadline_s`` or if the winning model fails; text already streamed is then stale and the caller replaces it with its own fallback.
    """
    q: queue.Queue = queue.Queue()
    start = time.monotonic()
    timeout_ms = max(API_MIN_TIMEOUT_MS, int(deadline_s * 1000) + 2000)

    def launch(tag: str, model: str) -> None:
        threading.Thread(target=_worker, args=(q, tag, model, system, prompt, temperature, timeout_ms), daemon=True, name=f"ps02-stream-{tag}").start()

    launch("primary", settings.gemini_model)
    can_hedge = bool(settings.gemini_fallback_model) and settings.gemini_fallback_model != settings.gemini_model
    backup_started, winner, failed, buf, emitted = False, None, {}, "", 0
    while True:
        remaining = deadline_s - (time.monotonic() - start)
        if remaining <= 0:
            raise gemini.LLMError(f"no model finished within {deadline_s:.0f}s")
        try:
            tag, kind, value = q.get(timeout=min(0.1, remaining))
        except queue.Empty:
            if can_hedge and not backup_started and winner is None and time.monotonic() - start >= hedge_after_s:
                backup_started = True
                launch("backup", settings.gemini_fallback_model)
            continue
        if winner and tag != winner:
            continue
        if kind == "chunk":
            winner = winner or tag
            buf += value
            part = partial_string(buf, stream_key)
            if part and len(part[0]) > emitted:
                yield ("delta", part[0][emitted:])
                emitted = len(part[0])
        elif kind == "done":
            if tag != winner:
                failed[tag] = gemini.LLMError("model returned nothing")
            else:
                data = gemini._parse_json(buf)
                missing = [k for k in required_keys if k not in data]
                if missing:
                    raise gemini.LLMError(f"missing fields: {', '.join(missing)}")
                yield ("final", data)
                return
        elif kind == "error":
            if tag == winner:
                raise value if isinstance(value, gemini.LLMError) else gemini.LLMError(str(value)[:200])
            failed[tag] = value
        if tag in failed and winner is None:
            if can_hedge and not backup_started:
                backup_started = True
                launch("backup", settings.gemini_fallback_model)
            elif len(failed) >= (2 if can_hedge else 1):
                raise gemini.LLMError(f"all models failed ({next(iter(failed.values()))})")
