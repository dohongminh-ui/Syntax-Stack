"""Language choice for everything the server says: Vietnamese (the default) or English.

The language only changes *display text*. It never reaches a random generator, a seed, a puzzle pick, a replay or an
answer check, so the same request in both languages plays the same game.

How a request picks its language
--------------------------------
* HTTP: the header ``X-Lang: en`` (or ``vi``). Missing or unknown means ``vi``. ``LangMiddleware`` reads it and sets a
  context variable, so code deep inside a request (an error raised in ``rooms.py``, a message built in ``bank.py``) can
  call ``tr(vi, en)`` / ``cur()`` without the language being threaded through every signature. Sync endpoints run in the
  thread pool, which copies the context, so this works there too.
* WebSocket: the query parameter ``lang=en|vi`` on the socket URL. A match has two players who may differ, so PvP does
  not use the context variable: it stores ``Player.lang`` per connection and passes it explicitly.

How content carries both languages
----------------------------------
Authored content (YAML, the puzzle bank) keeps the Vietnamese text in its field and the English text in a sibling field
with an ``_en`` suffix: ``prompt`` / ``prompt_en``, ``hints`` / ``hints_en``, ``title`` / ``title_en`` ...
``pick(obj, "prompt", lang)`` returns the English one for ``en`` when it exists and the Vietnamese one otherwise, so a
row that predates the English text (for example an old custom puzzle set) still renders.
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Mapping, Optional

DEFAULT = "vi"
LANGS = ("vi", "en")
SUFFIX = "_en"
HEADER = "x-lang"

_current: ContextVar[str] = ContextVar("syntax_stack_lang", default=DEFAULT)


def norm(value: Any) -> str:
    """``"en"`` for English (``en``, ``EN``, ``en-US``), ``"vi"`` for anything else."""
    if isinstance(value, str):
        head = value.strip().lower().replace("_", "-").split("-", 1)[0].split(",", 1)[0].strip()
        if head == "en":
            return "en"
    return DEFAULT


def cur() -> str:
    """The language of the request being served (``vi`` outside a request)."""
    return _current.get()


def set_lang(lang: Any):
    """Set the current language; returns the token for ``reset``."""
    return _current.set(norm(lang))


def reset(token) -> None:
    _current.reset(token)


def lang_of(request: Any) -> str:
    """The language of a Starlette ``Request`` / ``WebSocket`` (header ``X-Lang``, or ``lang`` on a socket URL)."""
    scope_type = getattr(request, "scope", {}).get("type")
    if scope_type == "websocket":
        return norm(request.query_params.get("lang"))
    return norm(request.headers.get(HEADER))


def resolve(lang: Optional[str]) -> str:
    """An explicit language, or the request's when ``lang`` is None."""
    return cur() if lang is None else norm(lang)


def tr(vi: str, en: str, lang: Optional[str] = None) -> str:
    """The Vietnamese or the English variant of a message, by ``lang`` (default: the request's)."""
    return en if resolve(lang) == "en" else vi


def pick(obj: Mapping, field: str, lang: Optional[str] = None) -> Any:
    """``obj[field]`` or, for English, ``obj[field + "_en"]`` when that is present and not empty."""
    if resolve(lang) == "en":
        en = obj.get(field + SUFFIX)
        if en:
            return en
    return obj[field]


def pick_get(obj: Mapping, field: str, lang: Optional[str] = None, default: Any = None) -> Any:
    """Like ``pick`` but ``default`` when the Vietnamese field is missing too."""
    if resolve(lang) == "en":
        en = obj.get(field + SUFFIX)
        if en:
            return en
    return obj.get(field, default)


def split_en(table: Mapping) -> tuple[dict, dict]:
    """Split a flat mapping into ``(vi, en)``: keys ending in ``_en`` go to ``en`` (with the suffix removed)."""
    vi, en = {}, {}
    for key, value in table.items():
        if isinstance(key, str) and key.endswith(SUFFIX):
            en[key[:-len(SUFFIX)]] = value
        else:
            vi[key] = value
    return vi, en


class LangMiddleware:
    """Pure ASGI middleware: puts the request's language into the context variable for the whole request."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        if scope["type"] == "http":
            raw = dict(scope.get("headers") or []).get(b"x-lang", b"").decode("latin-1")
        else:
            raw = ""
            for part in (scope.get("query_string") or b"").decode("latin-1").split("&"):
                key, _, value = part.partition("=")
                if key == "lang":
                    raw = value
        token = _current.set(norm(raw))
        try:
            return await self.app(scope, receive, send)
        finally:
            _current.reset(token)
