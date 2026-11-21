"""One place for PS02's time-boxed, hedged JSON calls to Gemini.

Gemini's fast models have demand spikes. A call goes to the primary model; if it has not answered after ``hedge_after_s`` (or has failed),
the same request is also sent to a second model, and the first valid answer wins. Past ``deadline_s`` the caller gets an LLMError and uses its
own deterministic fallback, so the student never waits longer than the deadline.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from app.ai import gemini
from app.config import settings

log = logging.getLogger(__name__)
API_MIN_TIMEOUT_MS = 10000          # Gemini rejects any shorter per-request deadline
_pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="ps02-llm")


def hedged_json(system: str, prompt: str, required_keys=(), temperature: float = 0.5, deadline_s: float = 8.0, hedge_after_s: float = 2.0):
    start = time.monotonic()
    timeout_ms = max(API_MIN_TIMEOUT_MS, int(deadline_s * 1000) + 2000)
    live = {_pool.submit(gemini.llm_json, system, prompt, required_keys, temperature, timeout_ms): "primary"}
    backup_started = not settings.gemini_fallback_model or settings.gemini_fallback_model == settings.gemini_model
    last_error: Exception = gemini.LLMError("no answer")
    while live and time.monotonic() - start < deadline_s:
        done, _ = wait(live, timeout=0.1, return_when=FIRST_COMPLETED)
        for fut in done:
            name = live.pop(fut)
            exc = fut.exception()
            if exc is None:
                if name == "backup":
                    log.info("Backup model answered in %.1fs", time.monotonic() - start)
                return fut.result()
            last_error = exc
        if not backup_started and (time.monotonic() - start >= hedge_after_s or not live):
            backup_started = True
            live[_pool.submit(gemini.llm_json, system, prompt, required_keys, temperature, timeout_ms, model=settings.gemini_fallback_model)] = "backup"
    raise gemini.LLMError(f"no model answered within {deadline_s:.0f}s ({last_error})") if not live or time.monotonic() - start >= deadline_s else last_error
