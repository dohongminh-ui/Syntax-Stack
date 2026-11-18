"""Server-side replay of a Code Rescue game (``mode: 'rescue'``).

A pure Python port of ``frontend/js/game.js`` + ``frontend/js/pieces.js``. Ranked runs and races never
trust a score from the browser: the server deals the pieces from a seed (``mulberry32``, bit-exact with
``mulberry()`` in ``frontend/js/main.js``), records which puzzles it served and what the answers were,
and then replays the player's list of moves with exactly these rules.

Everything that consumes the RNG is mirrored in the same order as the JavaScript:

* ``refill_tray`` (3 pieces: shape, number of rotations, topic),
* ``major_topic`` (one draw per lock, even without a tie),
* ``last_commit_topic`` (one draw), and
* ``shuffle`` (a tray refill).

``backend/tests/test_rescue_engine.py`` runs ``tests/js_harness/play.mjs`` (the real game.js) and
checks that this module reaches the same final state for hundreds of games. If a rule changes in the
JavaScript, change it here too; that test fails otherwise.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Iterable, Optional

SIZE = 8
TOPICS = ("variables", "conditions", "loops", "functions")
LEVELS = ("beginner", "intermediate", "advanced")
BASE_POINTS = (0, 100, 250, 450, 700)  # index = number of lines (4 = 4+)
HINT_FACTOR = (1, 0.9, 0.75, 0.5)
BUG_FIX_POINTS = 150
ITEM_CAP = 3
MAX_MOVES = 3000
_M32 = 0xFFFFFFFF

# Base shapes as (row, col); rotations are generated on pick. Dict order = JS key order (it matters).
_BASE: dict[str, tuple[tuple[tuple[int, int], ...], float]] = {
    "dot": (((0, 0),), 1),
    "i2": (((0, 0), (0, 1)), 3),
    "i3": (((0, 0), (0, 1), (0, 2)), 3),
    "i4": (((0, 0), (0, 1), (0, 2), (0, 3)), 2),
    "i5": (((0, 0), (0, 1), (0, 2), (0, 3), (0, 4)), 1),
    "sq2": (((0, 0), (0, 1), (1, 0), (1, 1)), 2),
    "sq3": (((0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2), (2, 0), (2, 1), (2, 2)), 0.6),
    "l3": (((0, 0), (1, 0), (1, 1)), 3),
    "l4": (((0, 0), (1, 0), (2, 0), (2, 1)), 2),
    "j4": (((0, 1), (1, 1), (2, 1), (2, 0)), 2),
    "t": (((0, 0), (0, 1), (0, 2), (1, 1)), 2),
    "s": (((0, 1), (0, 2), (1, 0), (1, 1)), 1.5),
    "z": (((0, 0), (0, 1), (1, 1), (1, 2)), 1.5),
}


class Rejected(Exception):
    """The replayed run is not a legal Code Rescue game. ``reason`` is a short machine-readable code."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


# --------------------------------------------------------------------------- RNG


def mulberry32(seed: int) -> Callable[[], float]:
    """Same float sequence as ``mulberry(a)`` in frontend/js/main.js (everything is mod 2^32)."""
    a = seed & _M32

    def rng() -> float:
        nonlocal a
        a = (a + 0x6D2B79F5) & _M32
        t = ((a ^ (a >> 15)) * (a | 1)) & _M32
        t = ((t + (((t ^ (t >> 7)) * (t | 61)) & _M32)) & _M32) ^ t
        return ((t ^ (t >> 14)) & _M32) / 4294967296

    return rng


def js_round(x: float) -> int:
    """JavaScript ``Math.round``: nearest integer, ties toward +infinity."""
    f = math.floor(x)
    return f + 1 if x - f >= 0.5 else f


# --------------------------------------------------------------------------- pieces


def _normalize(cells: Iterable[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    cells = list(cells)
    min_r = min(c[0] for c in cells)
    min_c = min(c[1] for c in cells)
    return tuple(sorted((r - min_r, c - min_c) for r, c in cells))


def _rotate(cells: Iterable[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    return _normalize((c, -r) for r, c in cells)


def _pick_weighted(items: list, weight_of: Callable[[Any], float], rng: Callable[[], float]):
    total = 0
    for it in items:  # explicit loop: sum() uses compensated float addition since Python 3.12
        total = total + weight_of(it)
    x = rng() * total
    for it in items:
        x -= weight_of(it)
        if x <= 0:
            return it
    return items[-1]


class Piece:
    __slots__ = ("shape", "cells", "topic")

    def __init__(self, shape: str, cells: tuple[tuple[int, int], ...], topic: str):
        self.shape, self.cells, self.topic = shape, cells, topic


def make_piece(rng: Callable[[], float]) -> Piece:
    """``makePiece(rng, null)``: draws shape, then rotations, then topic."""
    key = _pick_weighted(list(_BASE), lambda k: _BASE[k][1], rng)
    cells = _normalize(_BASE[key][0])
    for _ in range(math.floor(rng() * 4)):
        cells = _rotate(cells)
    topic = TOPICS[math.floor(rng() * len(TOPICS))]
    return Piece(key, cells, topic)


def streak_factor(n: int) -> float:
    if n >= 5:
        return 2
    if n >= 3:
        return 1.5
    if n == 2:
        return 1.2
    return 1


# --------------------------------------------------------------------------- game state


class RescueGame:
    """One Code Rescue game. Method names follow game.js; phases: play | locked | over."""

    def __init__(self, seed: int, level: str):
        self.level = level
        self.rng = mulberry32(seed)
        self.grid: list[list[Optional[dict]]] = [[None] * SIZE for _ in range(SIZE)]
        self.tray: list[Optional[Piece]] = []
        self.score = 0
        self.streak = 0
        self.best_streak = 0
        self.mistakes = 0  # 0 = stable, 1 = warning
        self.status = "ok"
        self.items = {"bomb": 0, "shuffle": 0, "undo": 0, "debugger": 0}
        self.bugs_fixed = 0
        self.locks_cleared = 0
        self.last_commit_used = False
        self.wrong_log: list[dict] = []
        self.topic_misses: dict[str, int] = {}
        self.bug_lines: list[dict] = []
        self.next_bug_id = 1
        self.phase = "play"
        self.lock: Optional[dict] = None
        self.snapshot: Optional[dict] = None
        self.end_reason: Optional[str] = None
        self.stuck = False  # no piece fits and the Last Commit choice is pending
        self.refill_tray()

    # ---- pieces and placing ----
    def refill_tray(self) -> None:
        self.tray = [make_piece(self.rng) for _ in range(3)]

    def can_place(self, piece: Piece, r: int, c: int) -> bool:
        for dr, dc in piece.cells:
            rr, cc = r + dr, c + dc
            if not (0 <= rr < SIZE and 0 <= cc < SIZE) or self.grid[rr][cc]:
                return False
        return True

    def fits_anywhere(self, piece: Piece) -> bool:
        return any(self.can_place(piece, r, c) for r in range(SIZE) for c in range(SIZE))

    def any_fit(self) -> bool:
        return any(p is not None and self.fits_anywhere(p) for p in self.tray)

    def _take_snapshot(self) -> dict:
        return {
            "grid": [[dict(c) if c else None for c in row] for row in self.grid],
            "tray": list(self.tray),
            "score": self.score,
            "bug_lines": [dict(b) for b in self.bug_lines],
        }

    def place(self, idx: int, r: int, c: int) -> Optional[dict]:
        """``Game.place``: None when the piece does not fit; else ``{"lock": ...}`` (lock may be None)."""
        piece = self.tray[idx] if 0 <= idx < len(self.tray) else None
        if piece is None or not self.can_place(piece, r, c):
            return None
        self.snapshot = self._take_snapshot()
        for dr, dc in piece.cells:
            self.grid[r + dr][c + dc] = {"topic": piece.topic, "bug": False, "bug_id": None}
        self.score += len(piece.cells)
        self.tray[idx] = None
        if all(p is None for p in self.tray):
            self.refill_tray()
        self.lock = self.find_lock()
        return {"lock": self.lock}

    def find_lock(self) -> Optional[dict]:
        rows = [r for r in range(SIZE) if all(x and not x["bug"] for x in self.grid[r])]
        cols = [c for c in range(SIZE)
                if all(self.grid[r][c] and not self.grid[r][c]["bug"] for r in range(SIZE))]
        if not rows and not cols:
            return None
        keys = set()
        for r in rows:
            keys.update(r * SIZE + c for c in range(SIZE))
        for c in cols:
            keys.update(r * SIZE + c for r in range(SIZE))
        cells = [(k // SIZE, k % SIZE) for k in sorted(keys)]
        count = len(rows) + len(cols)
        return {
            "rows": rows, "cols": cols, "cells": cells, "count": count,
            "tier": min(count, 3), "boss": count >= 4, "topic": self.major_topic(cells),
        }

    def major_topic(self, cells: list[tuple[int, int]]) -> str:
        n: dict[str, int] = {}
        for r, c in cells:
            t = self.grid[r][c]["topic"]
            n[t] = n.get(t, 0) + 1
        top = max(n.values())
        tied = [t for t in n if n[t] == top]
        return tied[math.floor(self.rng() * len(tied))]  # one draw even when nothing is tied

    # ---- points ----
    @staticmethod
    def base_for(lock: dict) -> int:
        return BASE_POINTS[min(lock["count"], 4)]

    def free_hint_level(self, debugger_active: bool) -> int:
        return max(1 if self.level == "beginner" else 0, 2 if debugger_active else 0)

    def reward(self, base: int, max_hint: int, free: int) -> dict:
        pl = 0 if max_hint <= free else max_hint
        clean = pl == 0
        new_streak = self.streak + 1 if clean else 1
        points = js_round(base * HINT_FACTOR[pl] * streak_factor(new_streak))
        return {"points": points, "clean": clean, "penalty_level": pl}

    def _add_item(self, name: str) -> None:
        if self.items[name] < ITEM_CAP:
            self.items[name] += 1

    def apply_correct(self, base: int, max_hint: int, free: int, lines: int) -> dict:
        r = self.reward(base, max_hint, free)
        self.score += r["points"]
        if r["clean"]:
            self.streak += 1
            if self.streak == 3:
                self._add_item("bomb")
            if self.streak == 5:
                self._add_item("shuffle")
        else:
            self.streak = 0
        if lines >= 4:
            self._add_item("undo")
        self.best_streak = max(self.best_streak, self.streak)
        return r

    def finish_lock(self) -> None:
        if self.lock:
            for r, c in self.lock["cells"]:
                self.grid[r][c] = None
        self.lock = None
        self.snapshot = None
        self.phase = "play"
        self.locks_cleared += 1

    def refresh_status(self) -> None:
        if self.end_reason == "crash":
            self.status = "crash"
        else:
            self.status = "warn" if self.mistakes > 0 else "ok"

    # ---- wrong answers ----
    def _log_wrong(self, topic: str, template_id: str, kind: str) -> None:
        self.streak = 0
        self.topic_misses[topic] = self.topic_misses.get(topic, 0) + 1
        self.wrong_log.append({"topic": topic, "template_id": template_id, "kind": kind})

    def apply_wrong(self, topic: str, template_id: str) -> str:
        """Wrong answer to a lock puzzle. Returns ``'bug'`` or ``'crash'``."""
        self._log_wrong(topic, template_id, "rescue")
        if self.mistakes >= 1:
            self.end_reason = "crash"
            self.phase = "over"
            self.refresh_status()
            return "crash"
        bug_id = self.next_bug_id
        self.next_bug_id += 1
        cells = [tuple(x) for x in self.lock["cells"]]
        for r, c in cells:
            self.grid[r][c]["bug"] = True
            self.grid[r][c]["bug_id"] = bug_id
        self.bug_lines.append({"id": bug_id, "cells": cells, "topic": topic, "template_id": template_id})
        self.mistakes = 1
        self.lock = None
        self.snapshot = None
        self.phase = "play"
        self.refresh_status()
        return "bug"

    def apply_debug_wrong(self, topic: str, template_id: str) -> str:
        self._log_wrong(topic, template_id, "debug")
        self.end_reason = "crash"
        self.phase = "over"
        self.refresh_status()
        return "crash"

    def fix_bug(self, bug_id: int) -> bool:
        b = next((x for x in self.bug_lines if x["id"] == bug_id), None)
        if b is None:
            return False
        for r, c in b["cells"]:
            self.grid[r][c] = None
        self.bug_lines = [x for x in self.bug_lines if x["id"] != bug_id]
        self.score += BUG_FIX_POINTS
        self.bugs_fixed += 1
        self.mistakes = 0
        self._add_item("debugger")
        self.refresh_status()
        return True

    # ---- Last Commit ----
    def last_commit_topic(self) -> str:
        entries = [(t, n) for t, n in self.topic_misses.items() if n > 0]
        if not entries:
            return TOPICS[math.floor(self.rng() * len(TOPICS))]
        top_n = max(n for _, n in entries)
        top = [t for t, n in entries if n == top_n]
        return top[math.floor(self.rng() * len(top))]

    def fail_last_commit(self, topic: str, template_id: str) -> None:
        self._log_wrong(topic, template_id, "last_commit")
        self.end_reason = "nofit"
        self.phase = "over"

    def fullest_rows(self, n: int = 3) -> list[int]:
        rows = []
        for r in range(SIZE):
            if any(x and x["bug"] for x in self.grid[r]):
                continue
            filled = sum(1 for x in self.grid[r] if x)
            if filled > 0:
                rows.append((r, filled))
        rows.sort(key=lambda x: (-x[1], x[0]))
        return [r for r, _ in rows[:n]]

    def clear_fullest_rows(self) -> None:
        for r in self.fullest_rows():
            for c in range(SIZE):
                self.grid[r][c] = None

    # ---- items ----
    def bomb(self, r: int, c: int) -> Optional[list[tuple[int, int]]]:
        if self.items["bomb"] < 1:
            return None
        cleared = []
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                rr, cc = r + dr, c + dc
                if not (0 <= rr < SIZE and 0 <= cc < SIZE):
                    continue
                cell = self.grid[rr][cc]
                if cell and not cell["bug"]:
                    cleared.append((rr, cc))
        if not cleared:
            return None
        self.items["bomb"] -= 1
        for rr, cc in cleared:
            self.grid[rr][cc] = None
        return cleared

    def shuffle(self) -> bool:
        if self.items["shuffle"] < 1:
            return False
        self.items["shuffle"] -= 1
        self.refill_tray()
        return True

    def can_undo(self) -> bool:
        return self.items["undo"] > 0 and self.snapshot is not None

    def undo(self) -> bool:
        if not self.can_undo():
            return False
        sn = self.snapshot
        self.grid = sn["grid"]
        self.tray = sn["tray"]
        self.score = sn["score"]
        self.bug_lines = sn["bug_lines"]
        self.items["undo"] -= 1
        self.lock = None
        self.snapshot = None
        self.phase = "play"
        self.refresh_status()
        return True

    def end_game(self, reason: str) -> None:
        self.phase = "over"
        self.end_reason = reason
        self.refresh_status()

    # ---- main.js: afterResolution (rescue branch) ----
    def settle(self) -> None:
        """After a resolved lock, bomb, shuffle, bug fix or a placement that made no lock: when nothing
        fits, the game ends at once if Last Commit is spent, otherwise it waits for ``last_commit`` or
        ``end nofit``."""
        self.stuck = False
        if self.phase != "over" and not self.any_fit():
            if self.last_commit_used:
                self.end_game("nofit")
            else:
                self.stuck = True

    # ---- results ----
    def grid_rows(self) -> list[str]:
        """8 strings; v/c/l/f = topic, uppercase = bug cell, '.' = empty (same as the JS harness)."""
        out = []
        for row in self.grid:
            out.append("".join(
                "." if not x else (x["topic"][0].upper() if x["bug"] else x["topic"][0]) for x in row))
        return out

    def summary(self) -> dict:
        return {
            "score": self.score,
            "locks": self.locks_cleared,
            "mistakes": len(self.wrong_log),
            "bugs_fixed": self.bugs_fixed,
            "best_streak": self.best_streak,
            "streak": self.streak,
            "status": self.status,
            "end_reason": self.end_reason,
            "last_commit_used": self.last_commit_used,
            "grid": self.grid_rows(),
            "items": dict(self.items),
            "tray": [None if p is None else {"topic": p.topic, "cells": [list(x) for x in p.cells]}
                     for p in self.tray],
        }


# --------------------------------------------------------------------------- replay


class _Served:
    """The server's record of the puzzles served in a run (in serving order) and how they were answered."""

    def __init__(self, records: Iterable[dict]):
        self.by_id: dict[str, dict] = {}
        for rec in sorted(records, key=lambda x: x["seq"]):
            self.by_id.setdefault(rec["id"], rec)  # a puzzle served twice counts once (the first serve)
        self.used: set[str] = set()
        self.last_seq = -1

    def take(self, pid: Any, kind: str, topic: Optional[str], tier: int, template: Optional[str] = None) -> dict:
        """The record for ``pid``: it must have been served for exactly this request, answered, used once,
        and in serving order."""
        rec = self.by_id.get(pid) if isinstance(pid, str) else None
        if rec is None:
            raise Rejected("puzzle_not_served")
        if pid in self.used:
            raise Rejected("puzzle_reused")
        if (rec["kind"] != kind or rec["req_topic"] != topic or rec["req_tier"] != tier
                or rec["req_template"] != template):
            raise Rejected("puzzle_mismatch")
        if rec["seq"] < self.last_seq:
            raise Rejected("puzzle_order")
        if rec["correct"] is None:
            raise Rejected("puzzle_not_answered")
        self.used.add(pid)
        self.last_seq = rec["seq"]
        return rec


def _int(m: dict, key: str, lo: int, hi: int) -> int:
    v = m.get(key)
    if type(v) is not int or not lo <= v <= hi:
        raise Rejected("bad_move")
    return v


def replay(seed: int, level: str, moves: Any, records: Iterable[dict]) -> dict:
    """Replay ``moves`` from ``seed`` and return the verified summary, or raise ``Rejected``.

    ``records``: one dict per puzzle the server served in this run: ``id, seq, kind`` (rescue | debug |
    last_commit), ``req_topic, req_tier, req_template`` (what the client asked for), ``topic,
    template_id`` (of the served puzzle), ``hint`` (highest hint level opened, 0 if none) and
    ``correct`` (True/False, or None when never answered; the first answer counts).
    """
    if level not in LEVELS:
        raise Rejected("bad_level")
    if not isinstance(moves, list) or len(moves) > MAX_MOVES:
        raise Rejected("too_many_moves")
    served = _Served(records)
    g = RescueGame(seed, level)
    ended = False

    for m in moves:
        if not isinstance(m, dict):
            raise Rejected("bad_move")
        t = m.get("t")
        if ended or (g.phase == "over" and t != "end"):
            raise Rejected("moves_after_end")

        if t == "end":
            reason = m.get("reason")
            if g.phase == "over":
                if reason != g.end_reason:
                    raise Rejected("bad_end")
            elif g.stuck:
                if reason != "nofit":
                    raise Rejected("bad_end")
                g.end_game("nofit")
            elif reason == "quit":
                g.end_game("quit")
            else:
                raise Rejected("bad_end")
            g.stuck = False
            ended = True
            continue

        if g.stuck and t != "last_commit":
            raise Rejected("stuck")  # no piece fits: only Last Commit or ending the run is allowed

        if t == "place":
            idx, r, c = _int(m, "i", 0, 2), _int(m, "r", 0, SIZE - 1), _int(m, "c", 0, SIZE - 1)
            if g.phase != "play":
                raise Rejected("illegal_phase")
            res = g.place(idx, r, c)
            if res is None:
                raise Rejected("illegal_place")
            if res["lock"]:
                g.phase = "locked"
            else:
                g.settle()

        elif t == "lock":
            if g.phase != "locked" or not g.lock:
                raise Rejected("no_lock")
            ids = m.get("puzzles")
            if not isinstance(ids, list) or not 1 <= len(ids) <= 2:
                raise Rejected("bad_move")
            flag = m.get("debugger", False)
            if type(flag) is not bool:
                raise Rejected("bad_move")
            lk = g.lock
            use_dbg = g.items["debugger"] > 0  # the browser spends a Debugger automatically
            if flag != use_dbg:
                raise Rejected("debugger_mismatch")
            if use_dbg:
                g.items["debugger"] -= 1
            free = g.free_hint_level(use_dbg)
            parts = 2 if lk["boss"] else 1
            base = g.base_for(lk)
            tier = 3 if lk["boss"] else lk["tier"]
            max_hint = 0
            failed: Optional[dict] = None
            used = 0
            for i in range(parts):
                if i >= len(ids):
                    raise Rejected("bad_lock")
                rec = served.take(ids[i], "rescue", lk["topic"], tier)
                used += 1
                max_hint = max(max_hint, min(3, max(0, int(rec["hint"] or 0))))
                if not rec["correct"]:
                    failed = rec
                    break
            if used != len(ids):
                raise Rejected("bad_lock")
            if failed is None:
                g.apply_correct(base, max_hint, free, lk["count"])
                g.finish_lock()
                g.settle()
            elif g.apply_wrong(failed["topic"], failed["template_id"]) == "bug":
                g.settle()

        elif t == "undo":
            if g.phase != "locked":
                raise Rejected("illegal_phase")
            if not g.undo():
                raise Rejected("item_not_owned")

        elif t == "bomb":
            r, c = _int(m, "r", 0, SIZE - 1), _int(m, "c", 0, SIZE - 1)
            if g.phase != "play":
                raise Rejected("illegal_phase")
            if g.items["bomb"] < 1:
                raise Rejected("item_not_owned")
            if g.bomb(r, c) is None:
                raise Rejected("bomb_empty")
            g.settle()

        elif t == "shuffle":
            if g.phase != "play":
                raise Rejected("illegal_phase")
            if not g.shuffle():
                raise Rejected("item_not_owned")
            g.settle()

        elif t == "bugfix":
            bug = _int(m, "bug", 1, 1_000_000)
            if g.phase != "play":
                raise Rejected("illegal_phase")
            bl = next((b for b in g.bug_lines if b["id"] == bug), None)
            if bl is None:
                raise Rejected("bad_bug")
            rec = served.take(m.get("puzzle"), "debug", bl["topic"], 1, bl["template_id"])
            if rec["correct"]:
                g.fix_bug(bug)
                g.settle()
            else:
                g.apply_debug_wrong(rec["topic"], rec["template_id"])

        elif t == "last_commit":
            if not g.stuck or g.last_commit_used:
                raise Rejected("not_stuck")
            g.last_commit_used = True
            topic = g.last_commit_topic()
            rec = served.take(m.get("puzzle"), "last_commit", topic, 3)
            g.stuck = False
            if not rec["correct"]:
                g.fail_last_commit(rec["topic"], rec["template_id"])
            else:
                g.clear_fullest_rows()
                g.settle()

        else:
            raise Rejected("bad_move")

    if not ended and g.phase != "over":
        raise Rejected("incomplete")
    return g.summary()
