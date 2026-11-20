"""Optional tutor (n8n webhook, or Gemini directly) for validated game context.

Two providers, picked on every call: ``n8n`` when ``SYNTAX_STACK_TUTOR_URL`` and ``SYNTAX_STACK_TUTOR_TOKEN`` are set
(preferred), else ``gemini`` when ``SYNTAX_STACK_GEMINI_API_KEY`` is set (REST call straight to Gemini, the request is
built in ``tutor_prompts.py`` exactly as the n8n flow builds it), else nothing (always canned). Both go through the same
``_run`` core below, so quotas, slots, cache, logging and the canned fallback behave identically.

Every tutor attempt ends in exactly one outcome: ``ai`` (fresh reply), ``cached`` (reply served from
the in-process cache, no outbound call) or ``canned:<reason>`` with reason ``not_configured``,
``busy``, ``limit``, ``client_limit`` or ``error``. One INFO line is logged per attempt (task,
outcome, latency in ms); the context, the reply text and the client are never logged.

Two daily quotas count real outbound calls (cache hits are free): a global one
(``SYNTAX_STACK_TUTOR_DAILY_LIMIT``, protects cost) and a per-client one
(``SYNTAX_STACK_TUTOR_CLIENT_LIMIT``, stops one visitor from using up the global quota for everyone).
Clients are identified by a hash of their IP that is kept in memory only and forgotten at midnight.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import time
from collections import OrderedDict
from datetime import date
from threading import BoundedSemaphore, Lock
from typing import Any, Callable, Optional

import httpx

from . import i18n, tutor_prompts

logger = logging.getLogger(__name__)
_slots = BoundedSemaphore(2)

CACHE_SIZE = 128
DEFAULT_DAILY_LIMIT = 500
DEFAULT_CLIENT_LIMIT = 40
MAX_TRACKED_CLIENTS = 20_000  # memory bound; beyond it new clients are treated as over quota

_lock = Lock()
_cache: "OrderedDict[tuple[str, str, str], Any]" = OrderedDict()
_day: date = date.today()
_calls = _ai = _fallback = 0
_per_client: dict[str, int] = {}


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


GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_PREFIX = "gemini:"   # pseudo-URL (part of the cache key) that routes a call to the direct Gemini provider


def gemini_model(task: str) -> str:
    if task == tutor_prompts.VOICE_TASK:
        return tutor_prompts.VOICE_MODEL
    return (os.getenv("SYNTAX_STACK_GEMINI_MODEL") or "").strip() or tutor_prompts.default_model(task)


def request_gemini(model: str, payload: str, *, timeout: float) -> dict:
    """Call Gemini directly and normalize its response to the same envelope as the n8n flow.

    The key travels only in the ``x-goog-api-key`` header (never in the URL, never logged)."""
    body = json.loads(payload)
    voice = body.get("task") == tutor_prompts.VOICE_TASK
    response = httpx.post(
        tutor_prompts.VOICE_ENDPOINT if voice else GEMINI_ENDPOINT.format(model=model),
        json=tutor_prompts.build_voice_request(body) if voice else tutor_prompts.build_request(body, model),
        headers={"x-goog-api-key": os.environ["SYNTAX_STACK_GEMINI_API_KEY"]},
        timeout=timeout, trust_env=False,
    )
    if voice and response.status_code == 429:
        return {"status": 429}
    response.raise_for_status()
    if voice:
        return tutor_prompts.parse_voice_response(response.json())
    return tutor_prompts.parse_response(response.json(), body.get("task"))


def _call(url: str, payload: str) -> dict:
    if url.startswith(GEMINI_PREFIX):
        return request_gemini(url[len(GEMINI_PREFIX):], payload, timeout=38)
    return request_tutor(url, payload, timeout=38)


def _ask(url: str, payload: str) -> str:
    text = _call(url, payload).get("text")
    if not isinstance(text, str) or not 0 < len(text.strip()) <= 750:
        raise ValueError("Missing or invalid tutor text")
    return text.strip()


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


def daily_limit() -> int:
    return _env_int("SYNTAX_STACK_TUTOR_DAILY_LIMIT", DEFAULT_DAILY_LIMIT)


def client_limit() -> int:
    return _env_int("SYNTAX_STACK_TUTOR_CLIENT_LIMIT", DEFAULT_CLIENT_LIMIT)


def client_key(ip: Optional[str]) -> Optional[str]:
    """Opaque per-day key for a client IP (never stored or logged in clear)."""
    if not ip:
        return None
    return hashlib.sha256(f"{date.today().isoformat()}|{ip}".encode()).hexdigest()[:20]


def provider() -> Optional[str]:
    """``"n8n"`` (preferred), ``"gemini"`` (direct, key only) or ``None``."""
    if os.getenv("SYNTAX_STACK_TUTOR_URL") and os.getenv("SYNTAX_STACK_TUTOR_TOKEN"):
        return "n8n"
    if os.getenv("SYNTAX_STACK_GEMINI_API_KEY"):
        return "gemini"
    return None


def configured() -> bool:
    return provider() is not None


def _roll_day() -> None:
    """Reset the counters at local midnight. Caller holds ``_lock``."""
    global _day, _calls, _ai, _fallback
    today = date.today()
    if today != _day:
        _day, _calls, _ai, _fallback = today, 0, 0, 0
        _per_client.clear()


def stats() -> dict:
    with _lock:
        _roll_day()
        return {"configured": configured(), "provider": provider(), "calls_today": _calls, "ai_today": _ai,
                "fallback_today": _fallback, "limit": daily_limit(),
                "client_limit": client_limit()}


def reset() -> None:
    """Clear cache and counters (used by tests)."""
    global _day, _calls, _ai, _fallback
    with _lock:
        _cache.clear()
        _per_client.clear()
        _day, _calls, _ai, _fallback = date.today(), 0, 0, 0


def _finish(task: str, started: float, outcome: str, value: Any, fallback: Any) -> tuple[Any, str]:
    global _fallback
    ms = round((time.monotonic() - started) * 1000)
    if outcome.startswith("canned"):
        with _lock:
            _roll_day()
            _fallback += 1
        value, source = fallback, "canned"
    else:
        source = "ai"
    logger.info("tutor task=%s outcome=%s latency_ms=%d", task, outcome, ms)
    return value, source


def _run(task: str, context: dict, fallback: Any, client: Optional[str], lang: Optional[str],
         ask: Callable[[str, str], Any], *, cache: bool = True) -> tuple[Any, str]:
    """Shared core of ``feedback`` and ``ask_json``: configuration check, quotas, cache, slots, logging.

    ``ask(url, payload)`` makes the call and returns the validated reply (a string or a dict); it raises
    ``ValueError`` & co. for a bad reply. Returns ``(reply, "ai")`` or ``(fallback, "canned")``."""
    global _calls, _ai
    lang = i18n.resolve(lang)
    who = client_key(client)
    started = time.monotonic()
    kind = provider()
    if kind is None:
        return _finish(task, started, "canned:not_configured", None, fallback)
    url = os.environ["SYNTAX_STACK_TUTOR_URL"] if kind == "n8n" else GEMINI_PREFIX + gemini_model(task)
    limit = daily_limit()
    if limit == 0:
        return _finish(task, started, "canned:limit", None, fallback)
    try:
        payload = json.dumps({"task": task, "lang": lang, "context": context}, ensure_ascii=False)
    except (TypeError, ValueError):
        return _finish(task, started, "canned:error", None, fallback)
    key = (url, lang, payload)
    with _lock:
        hit = _cache.get(key) if cache else None
        if hit is not None:
            _cache.move_to_end(key)
    if hit is not None:
        return _finish(task, started, "cached", copy.deepcopy(hit), fallback)
    if not _slots.acquire(blocking=False):
        return _finish(task, started, "canned:busy", None, fallback)
    try:
        per_client = client_limit()
        with _lock:
            _roll_day()
            used = _per_client.get(who, 0) if who else 0
            if _calls >= limit:
                over = "canned:limit"
            elif who and (used >= per_client
                          or (who not in _per_client and len(_per_client) >= MAX_TRACKED_CLIENTS)):
                over = "canned:client_limit"
            else:
                over, _calls = "", _calls + 1
                if who:
                    _per_client[who] = used + 1
        if over:
            return _finish(task, started, over, None, fallback)
        try:
            reply = ask(url, payload)
        except (httpx.HTTPError, httpx.InvalidURL, ValueError, KeyError, TypeError) as exc:
            logger.warning("Tutor unavailable (%s)", type(exc).__name__)
            return _finish(task, started, "canned:error", None, fallback)
        with _lock:
            _ai += 1
            if cache:
                _cache[key] = copy.deepcopy(reply)
                _cache.move_to_end(key)
                while len(_cache) > CACHE_SIZE:
                    _cache.popitem(last=False)
        return _finish(task, started, "ai", reply, fallback)
    finally:
        _slots.release()


def feedback(task: str, context: dict, fallback: str, client: Optional[str] = None,
             lang: Optional[str] = None) -> dict:
    """Ask the tutor; ``client`` is the requester's IP (used only for the per-client quota).

    ``lang`` (``"vi"`` / ``"en"``, default: the request's) is sent to the provider in the body of every task so the reply is
    written in that language, and is part of the cache key so a reply is never served to the other language."""
    text, source = _run(task, context, fallback, client, lang, lambda url, payload: _ask(url, payload))
    return {"text": text, "source": source}


def ask_json(task: str, context: dict, fallback: dict, validate: Callable[[dict], dict],
             client: Optional[str] = None, lang: Optional[str] = None, *, cache: bool = True) -> dict:
    """Like ``feedback`` for tasks that need a structured reply (``misaki_chat``, ``misaki_puzzle``).

    Same quotas, slots, cache, day roll and log line. ``validate(raw_reply_object)`` returns the cleaned dict or raises
    ``ValueError`` / ``KeyError`` / ``TypeError``; any such error means the AI failed. Returns
    ``{**validated, "source": "ai"}`` or ``{**fallback, "source": "canned"}``."""
    def ask(url: str, payload: str) -> dict:
        raw = _call(url, payload)
        if task == tutor_prompts.VOICE_TASK and raw.get("status") == 429:
            body = json.loads(payload)
            body["context"]["fallback"] = True
            raw = _call(url, json.dumps(body, ensure_ascii=False))
        return validate(raw)

    value, source = _run(task, context, fallback, client, lang, ask, cache=cache)
    return {**value, "source": source}
