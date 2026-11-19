"""Misaki's coaching in training mode ("Luyện tập cùng Misaki", docs/pvp.md section 5.4).

``Coach`` decides *when* to say something and *which* line; the lines themselves are the director-written copy in
``content/misaki_coach.yaml`` (used verbatim). It is pure: every call gets the match clock ``t`` and returns the message
to push (or None); ``app/pvp.py`` sends it. Nothing here talks to a network or reads the clock.

Rules (all on the match clock):

* at most one coach message every ``GAP_S`` (4 s); the ``suggestion`` answers to the player's own request are not coach
  messages and are never throttled;
* event kinds (``incoming``, ``cancel``, ``streak``, ``wrong``, ``good``) that arrive during the pause wait for it, the
  highest priority one first, for at most ``DEFER_S``; state kinds (``danger``, ``nofit_risk``, ``bugline``) are simply
  checked again on the next look, never queued;
* ``incoming`` is said once per match (the first lines the opponent sends), ``bugline`` once per bug line (after it has
  stood for 30 s), ``danger`` and ``nofit_risk`` repeat at most every 15 s / 20 s while the situation lasts;
* the variant of a line is picked from the match seed: ``Random(f"{seed}:coach:{kind}:{k}")`` for the k-th message of that
  kind, so the same match tells the same story.

Language: the English lines are the ``<kind>_en`` siblings in the same YAML file, with the same number of variants. The
language is only a *display* choice made per player (``lang`` argument of every call, ``Player.lang`` in ``pvp.py``): the
variant index, the timing and everything else are the same for a Vietnamese and an English player in one match.
"""
from __future__ import annotations

import random
from pathlib import Path
from typing import Any, Optional

import yaml

from . import i18n
from . import rescue_engine as E

COACH_FILE = Path(__file__).resolve().parents[1] / "content" / "misaki_coach.yaml"
GAP_S = 4.0
DEFER_S = 6.0
BUGLINE_AFTER_S = 30.0
COOLDOWN_S = {"danger": 15.0, "nofit_risk": 20.0}
PRIORITY = {"wrong": 6, "danger": 5, "incoming": 4, "good": 4, "cancel": 3, "streak": 2, "nofit_risk": 2, "bugline": 1}
EVENT_KINDS = ("incoming", "cancel", "streak", "wrong", "good")      # deferred while throttled
TOPIC_VI = {"variables": "Biến", "conditions": "Điều kiện", "loops": "Vòng lặp", "functions": "Hàm"}
TOPIC_EN = {"variables": "Variables", "conditions": "Conditions", "loops": "Loops", "functions": "Functions"}
MAX_TEXT = 120


def _load() -> dict[str, Any]:
    return yaml.safe_load(COACH_FILE.read_text(encoding="utf-8")) or {}


TEXTS: dict[str, Any]                 # Vietnamese lines, by kind
TEXTS_EN: dict[str, Any]              # English lines, by kind (the ``<kind>_en`` keys of the file)
TEXTS, TEXTS_EN = i18n.split_en(_load())
KINDS = tuple(PRIORITY)
SUGGESTION_KEYS = ("line", "safe", "danger", "fit", "none")


class _Fmt(dict):
    def __missing__(self, key: str) -> str:
        return ""


def topic_name(topic: Optional[str], lang: Optional[str] = None) -> str:
    """The display name of a topic id (``loops`` -> ``Vòng lặp`` / ``Loops``). Anything else is returned as it is."""
    names = TOPIC_EN if i18n.resolve(lang) == "en" else TOPIC_VI
    return names.get(topic or "", topic or "")


def _format(text: str, n: Optional[int], topic: Optional[str], lang: Optional[str] = None) -> str:
    return text.format_map(_Fmt(n="" if n is None else n, topic=topic_name(topic, lang)))


def _lines(kind: str, lang: Optional[str]):
    """The variants of ``kind`` in the language (the Vietnamese ones when no English text exists)."""
    if i18n.resolve(lang) == "en" and TEXTS_EN.get(kind):
        return TEXTS_EN[kind]
    return TEXTS[kind]


def suggestion_text(reason: str, n: int = 0, lang: Optional[str] = None) -> str:
    """The ``why`` of a suggestion (``reason``: line | safe | danger | fit | none)."""
    return _format(_lines("suggestion", lang)[reason], n, None, lang)


def danger_cells(g: E.RescueGame) -> list[list[int]]:
    """The blocks in the top ``len(pending)`` rows: the ones the incoming lines would push off the board."""
    k = len(g.pending)
    if not k:
        return []
    return [[r, c] for r in range(min(k, E.SIZE)) for c in range(E.SIZE) if g.grid[r][c]]


class Coach:
    def __init__(self, seed: int):
        self.seed = seed
        self.last_t: Optional[float] = None                 # when the last coach message went out
        self.counts: dict[str, int] = {}                    # messages sent, by kind
        self.last_kind_t: dict[str, float] = {}
        self.deferred: Optional[tuple[int, str, Optional[int], Optional[str], Optional[list], float]] = None
        self.incoming_told = False
        self.bug_first_seen: dict[int, float] = {}
        self.bug_told: set[int] = set()

    # ---- the line ----
    def text(self, kind: str, n: Optional[int] = None, topic: Optional[str] = None,
             lang: Optional[str] = None) -> str:
        """``topic`` is a topic id (``loops``) or an already-written name; the variant index never depends on ``lang``."""
        k = self.counts.get(kind, 0)
        pick = random.Random(f"{self.seed}:coach:{kind}:{k}").randrange(len(TEXTS[kind]))
        variants = _lines(kind, lang)
        return _format(variants[pick % len(variants)], n, topic, lang)

    def _out(self, kind: str, t: float, n: Optional[int], topic: Optional[str], cells: Optional[list],
             lang: Optional[str] = None) -> dict:
        msg: dict[str, Any] = {"t": "coach", "kind": kind, "text": self.text(kind, n, topic, lang)}
        if cells:
            msg["cells"] = cells
        self.counts[kind] = self.counts.get(kind, 0) + 1
        self.last_kind_t[kind] = self.last_t = t
        return msg

    def _throttled(self, t: float) -> bool:
        return self.last_t is not None and t - self.last_t < GAP_S

    # ---- events (something just happened) ----
    def event(self, kind: str, t: float, *, n: Optional[int] = None, topic: Optional[str] = None,
              cells: Optional[list] = None, lang: Optional[str] = None) -> Optional[dict]:
        if kind == "incoming":
            if self.incoming_told:
                return None
            self.incoming_told = True
        last = self.last_kind_t.get(kind)
        if last is not None and t - last < COOLDOWN_S.get(kind, 0.0):
            return None
        if self._throttled(t):
            if kind in EVENT_KINDS:
                cur = self.deferred
                if cur is None or PRIORITY[kind] > cur[0] or t > cur[5]:
                    self.deferred = (PRIORITY[kind], kind, n, topic, cells, t + DEFER_S)
            return None
        return self._out(kind, t, n, topic, cells, lang)

    def due(self, t: float, lang: Optional[str] = None) -> Optional[dict]:
        """The deferred event, once the pause is over (dropped when it waited longer than ``DEFER_S``)."""
        d = self.deferred
        if d is None:
            return None
        if t > d[5]:
            self.deferred = None
            return None
        if self._throttled(t):
            return None
        self.deferred = None
        return self._out(d[1], t, d[2], d[3], d[4], lang)

    # ---- state (looked at after every change and about twice a second) ----
    def observe(self, g: E.RescueGame, t: float, lang: Optional[str] = None) -> Optional[dict]:
        """``danger`` / ``bugline`` / ``nofit_risk`` from the player's current state, most urgent first."""
        if g.phase == "over":
            return None
        seen = {b["id"] for b in g.bug_lines}
        for bid in list(self.bug_first_seen):
            if bid not in seen:
                del self.bug_first_seen[bid]
        for bid in seen:
            self.bug_first_seen.setdefault(bid, t)
        cells = danger_cells(g)
        if cells or len(g.pending) > E.SIZE:
            return self.event("danger", t, n=len(g.pending), cells=cells, lang=lang)
        if g.phase == "play":
            old = [b for b in g.bug_lines if b["id"] not in self.bug_told
                   and t - self.bug_first_seen.get(b["id"], t) >= BUGLINE_AFTER_S]
            if old and not self._throttled(t):
                msg = self.event("bugline", t, topic=old[0]["topic"], lang=lang)
                if msg:
                    self.bug_told.add(old[0]["id"])
                    return msg
            present = [p for p in g.tray if p is not None]
            if len(present) >= 2 and sum(1 for p in present if g.fits_anywhere(p)) == 1:
                return self.event("nofit_risk", t, lang=lang)
        return None
