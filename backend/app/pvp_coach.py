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
"""
from __future__ import annotations

import random
from pathlib import Path
from typing import Any, Optional

import yaml

from . import rescue_engine as E

COACH_FILE = Path(__file__).resolve().parents[1] / "content" / "misaki_coach.yaml"
GAP_S = 4.0
DEFER_S = 6.0
BUGLINE_AFTER_S = 30.0
COOLDOWN_S = {"danger": 15.0, "nofit_risk": 20.0}
PRIORITY = {"wrong": 6, "danger": 5, "incoming": 4, "good": 4, "cancel": 3, "streak": 2, "nofit_risk": 2, "bugline": 1}
EVENT_KINDS = ("incoming", "cancel", "streak", "wrong", "good")      # deferred while throttled
TOPIC_VI = {"variables": "Biến", "conditions": "Điều kiện", "loops": "Vòng lặp", "functions": "Hàm"}
MAX_TEXT = 120


def _load() -> dict[str, Any]:
    return yaml.safe_load(COACH_FILE.read_text(encoding="utf-8")) or {}


TEXTS: dict[str, Any] = _load()
KINDS = tuple(PRIORITY)
SUGGESTION_KEYS = ("line", "safe", "danger", "fit", "none")


class _Fmt(dict):
    def __missing__(self, key: str) -> str:
        return ""


def _format(text: str, n: Optional[int], topic: Optional[str]) -> str:
    return text.format_map(_Fmt(n="" if n is None else n, topic=topic or ""))


def suggestion_text(reason: str, n: int = 0) -> str:
    """The ``why`` of a suggestion (``reason``: line | safe | danger | fit | none)."""
    return _format(TEXTS["suggestion"][reason], n, None)


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
    def text(self, kind: str, n: Optional[int] = None, topic: Optional[str] = None) -> str:
        variants = TEXTS[kind]
        k = self.counts.get(kind, 0)
        pick = random.Random(f"{self.seed}:coach:{kind}:{k}").randrange(len(variants))
        return _format(variants[pick], n, topic)

    def _out(self, kind: str, t: float, n: Optional[int], topic: Optional[str], cells: Optional[list]) -> dict:
        msg: dict[str, Any] = {"t": "coach", "kind": kind, "text": self.text(kind, n, topic)}
        if cells:
            msg["cells"] = cells
        self.counts[kind] = self.counts.get(kind, 0) + 1
        self.last_kind_t[kind] = self.last_t = t
        return msg

    def _throttled(self, t: float) -> bool:
        return self.last_t is not None and t - self.last_t < GAP_S

    # ---- events (something just happened) ----
    def event(self, kind: str, t: float, *, n: Optional[int] = None, topic: Optional[str] = None,
              cells: Optional[list] = None) -> Optional[dict]:
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
        return self._out(kind, t, n, topic, cells)

    def due(self, t: float) -> Optional[dict]:
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
        return self._out(d[1], t, d[2], d[3], d[4])

    # ---- state (looked at after every change and about twice a second) ----
    def observe(self, g: E.RescueGame, t: float) -> Optional[dict]:
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
            return self.event("danger", t, n=len(g.pending), cells=cells)
        if g.phase == "play":
            old = [b for b in g.bug_lines if b["id"] not in self.bug_told
                   and t - self.bug_first_seen.get(b["id"], t) >= BUGLINE_AFTER_S]
            if old and not self._throttled(t):
                msg = self.event("bugline", t, topic=TOPIC_VI.get(old[0]["topic"], ""))
                if msg:
                    self.bug_told.add(old[0]["id"])
                    return msg
            present = [p for p in g.tray if p is not None]
            if len(present) >= 2 and sum(1 for p in present if g.fits_anywhere(p)) == 1:
                return self.event("nofit_risk", t)
        return None
