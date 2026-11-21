"""A time-boxed, hedged Gemini VISION call (image + prompt -> JSON), same idea as llm.hedged_json: the primary model first, the backup model
raced after ``hedge_after_s`` (or at once if the primary fails). Past ``deadline_s`` the caller gets an LLMError and shows its own fallback."""
from __future__ import annotations

import logging
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from google.genai import types

from app.ai import gemini
from app.config import settings

log = logging.getLogger(__name__)
_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ps02-vision")


def _call(model: str, system: str, prompt: str, image: bytes, mime: str, temperature: float, timeout_ms: int, required_keys) -> dict:
    response = gemini._get_client().models.generate_content(
        model=model, contents=[types.Part.from_bytes(data=image, mime_type=mime), prompt],
        config=types.GenerateContentConfig(system_instruction=gemini.guarded(system), response_mime_type="application/json", temperature=temperature,
                                           http_options=types.HttpOptions(timeout=timeout_ms)))
    data = gemini._parse_json(response.text or "")
    if not isinstance(data, dict):
        raise ValueError("not an object")
    missing = [k for k in required_keys if k not in data]
    if missing:
        raise ValueError(f"missing fields: {', '.join(missing)}")
    return data


def hedged_vision_json(system: str, prompt: str, image: bytes, mime: str = "image/jpeg", required_keys=(), temperature: float = 0.1,
                       deadline_s: float = 18.0, hedge_after_s: float = 6.0) -> dict:
    start = time.monotonic()
    timeout_ms = max(10000, int(deadline_s * 1000) + 2000)
    live = {_pool.submit(_call, settings.gemini_model, system, prompt, image, mime, temperature, timeout_ms, required_keys): "primary"}
    backup_started = not settings.gemini_fallback_model or settings.gemini_fallback_model == settings.gemini_model
    last_error: Exception = gemini.LLMError("no answer")
    while live and time.monotonic() - start < deadline_s:
        done, _ = wait(live, timeout=0.1, return_when=FIRST_COMPLETED)
        for fut in done:
            live.pop(fut)
            exc = fut.exception()
            if exc is None:
                return fut.result()
            last_error = exc
            log.warning("Vision call failed: %s", str(exc)[:160])
        if not backup_started and (time.monotonic() - start >= hedge_after_s or not live):
            backup_started = True
            live[_pool.submit(_call, settings.gemini_fallback_model, system, prompt, image, mime, temperature, timeout_ms, required_keys)] = "backup"
    raise gemini.LLMError(f"the handwriting reader did not answer within {deadline_s:.0f}s ({str(last_error)[:100]})")
