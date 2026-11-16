"""Optional n8n tutor for validated game context.

Every tutor attempt ends in exactly one outcome: ``ai`` (fresh reply), ``cached`` (reply served from
the in-process cache, no outbound call) or ``canned:<reason>`` with reason ``not_configured``,
``busy``, ``limit`` or ``error``. One INFO line is logged per attempt (task, outcome, latency in
ms); the context and the reply text are never logged.
"""
from __future__ import annotations

import json
import logging
import os
import time
from collections import OrderedDict
from datetime import date
from threading import BoundedSemaphore, Lock
from typing import Optional

import httpx

logger = logging.getLogger(__name__)
_slots = BoundedSemaphore(2)

CACHE_SIZE = 128
DEFAULT_DAILY_LIMIT = 500

_lock = Lock()
_cache: "OrderedDict[tuple[str, str], str]" = OrderedDict()
_day: date = date.today()
_calls = _ai = _fallback = 0


def request_tutor(url: str, payload: str, *, timeout: float) -> dict:
    response = httpx.post(
        url, content=payload,
        headers={"Content-Type": "application/json",
                 "X-Syntax-Stack-Token": os.environ["SYNTAX_STACK_TUTOR_TOKEN"]},
        timeout=timeout, trust_env=False,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("Invalid tutor response")
    return data


def _ask(url: str, payload: str) -> str:
    text = request_tutor(url, payload, timeout=38).get("text")
    if not isinstance(text, str) or not 0 < len(text.strip()) <= 750:
        raise ValueError("Missing or invalid tutor text")
    return text.strip()


def daily_limit() -> int:
    raw = os.getenv("SYNTAX_STACK_TUTOR_DAILY_LIMIT")
    if raw is None or not raw.strip():
        return DEFAULT_DAILY_LIMIT
    try:
        return max(0, int(raw))
    except ValueError:
        return DEFAULT_DAILY_LIMIT


def configured() -> bool:
    return bool(os.getenv("SYNTAX_STACK_TUTOR_URL") and os.getenv("SYNTAX_STACK_TUTOR_TOKEN"))


def _roll_day() -> None:
    """Reset the counters at local midnight. Caller holds ``_lock``."""
    global _day, _calls, _ai, _fallback
    today = date.today()
    if today != _day:
        _day, _calls, _ai, _fallback = today, 0, 0, 0


def stats() -> dict:
    with _lock:
        _roll_day()
        return {"configured": configured(), "calls_today": _calls, "ai_today": _ai,
                "fallback_today": _fallback, "limit": daily_limit()}


def reset() -> None:
    """Clear cache and counters (used by tests)."""
    global _day, _calls, _ai, _fallback
    with _lock:
        _cache.clear()
        _day, _calls, _ai, _fallback = date.today(), 0, 0, 0


def _finish(task: str, started: float, outcome: str, text: str, fallback: str) -> dict:
    global _fallback
    ms = round((time.monotonic() - started) * 1000)
    if outcome.startswith("canned"):
        with _lock:
            _roll_day()
            _fallback += 1
        text, source = fallback, "canned"
    else:
        source = "ai"
    logger.info("tutor task=%s outcome=%s latency_ms=%d", task, outcome, ms)
    return {"text": text, "source": source}


def feedback(task: str, context: dict, fallback: str) -> dict:
    global _calls, _ai
    started = time.monotonic()
    url = os.getenv("SYNTAX_STACK_TUTOR_URL")
    if not (url and os.getenv("SYNTAX_STACK_TUTOR_TOKEN")):
        return _finish(task, started, "canned:not_configured", "", fallback)
    limit = daily_limit()
    if limit == 0:
        return _finish(task, started, "canned:limit", "", fallback)
    try:
        payload = json.dumps({"task": task, "context": context}, ensure_ascii=False)
    except (TypeError, ValueError):
        return _finish(task, started, "canned:error", "", fallback)
    key = (url, payload)
    with _lock:
        hit: Optional[str] = _cache.get(key)
        if hit is not None:
            _cache.move_to_end(key)
    if hit is not None:
        return _finish(task, started, "cached", hit, fallback)
    if not _slots.acquire(blocking=False):
        return _finish(task, started, "canned:busy", "", fallback)
    try:
        with _lock:
            _roll_day()
            if _calls >= limit:
                over = True
            else:
                over, _calls = False, _calls + 1
        if over:
            return _finish(task, started, "canned:limit", "", fallback)
        try:
            text = _ask(url, payload)
        except (httpx.HTTPError, httpx.InvalidURL, ValueError, KeyError, TypeError) as exc:
            logger.warning("Tutor unavailable (%s)", type(exc).__name__)
            return _finish(task, started, "canned:error", "", fallback)
        with _lock:
            _ai += 1
            _cache[key] = text
            _cache.move_to_end(key)
            while len(_cache) > CACHE_SIZE:
                _cache.popitem(last=False)
        return _finish(task, started, "ai", text, fallback)
    finally:
        _slots.release()
