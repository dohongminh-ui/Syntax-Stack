"""Real-time 1v1 matches (Code Rescue "Đối kháng"). Contract: docs/pvp.md.

Everything lives in this process's memory (single process, no persistence): the tickets, the queue, the private
duel codes and the live matches. Only the Elo ratings are stored (``ranked.sqlite``). A deploy or restart ends all
live matches (``server_restart``, no rating change).

Trust model: the server is authoritative. It runs both players' games with the rules engine
(``rescue_engine.RescueGame(mode="pvp")``, the same rules as ``frontend/js/game.js``), deals the same seed to both,
picks every puzzle (deterministically from the match seed), checks every answer and applies its outcome. The browser
only sends intentions (place / bomb / shuffle / undo / resign) and renders what the server pushes.

Threads: the WebSocket handlers and the clock run on the event loop; the puzzle endpoints (``serve_puzzle``,
``record_hint``, ``record_answer``) run in FastAPI's thread pool. One module-wide re-entrant lock protects all state;
messages to browsers go through a per-connection asyncio queue (``Conn.send`` is safe from any thread).
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import random
import secrets
import threading
import time
from collections import deque
from typing import Any, Optional

from . import bank, nicknames, pvp_bot, pvp_coach, ranked, rooms
from . import rescue_engine as E

log = logging.getLogger("syntax_stack.pvp")
# Uvicorn configures this logger's parent at INFO, so diagnostics reach the server console by default.
diagnostics = logging.getLogger("uvicorn.error.pvp")

# --- limits (docs/pvp.md section 7) and timings (seconds of match clock)
MAX_LIVE_MATCHES = 200
MAX_TICKETS = 2000
MAX_MESSAGE_BYTES = 4096
MAX_ACTIONS_PER_S = 10           # real time; more are dropped
OUTBOX_LIMIT = 512               # queued messages per connection before it is cut off
COUNTDOWN_S = 3
GRACE_S = 20
OVERTIME_AT_S = 240
OVERTIME_EVERY_S = 20
OPPONENT_PUSH_S = 0.25           # opponent board pushes: at most 4 per second
PRIVATE_TTL_S = 600              # a private duel code lives 10 minutes without a second player
LOBBY_TIMEOUT_S = 60             # two players paired but not both ready within this: the match is cancelled
QUEUE_TIMEOUT_S = 300            # waiting in the quick-match queue
QUEUE_FRESH_S = 15               # a queued ticket must have its socket open within this, and be away at most this long
REMATCH_S = 60                   # a private duel can be played again when both press "rematch" within this
KEEP_OVER_S = 300                # a finished match stays this long so that a reconnecting client still gets `end`
STALE_UNSEEN_S = 120             # tickets / matches nobody ever connected to are dropped after this
TICK_S = 0.1
SPEED = 1.0                      # tests: > 1 runs the match clock faster
MAX_SERVED_PER_PLAYER = 1000
HISTORY_IDS = 500
HISTORY_TEMPLATES = 3
SUGGEST_EVERY_S = 3.0            # training: a `suggest` more often than this (real time) is dropped
COACH_LOOK_S = 0.5               # training: how often the coach looks at the player's board (besides after every change)

LEVELS = E.LEVELS
_ERR = {
    "bad_message": "Tin nhắn không hợp lệ.",
    "not_playing": "Ván đấu chưa bắt đầu hoặc đã kết thúc.",
    "illegal": "Nước đi không hợp lệ.",
    "stale_state": "Có dòng lỗi mới vừa tới. Hãy xem lại bàn rồi đặt khối.",
    "not_training": "Gợi ý chỉ có trong chế độ luyện tập cùng Misaki.",
}


def now() -> float:
    """The match clock (monotonic seconds, scaled by ``SPEED`` in tests)."""
    return time.monotonic() * SPEED


def _real() -> float:
    return time.monotonic()


class PvpError(ranked.RankedError):
    """An error with an explicit HTTP status; the message is Vietnamese."""


# --------------------------------------------------------------------------- registry

_lock = threading.RLock()
_tickets: dict[str, "Player"] = {}
_matches: dict[str, "Match"] = {}
_queues: dict[str, list["Player"]] = {lv: [] for lv in LEVELS}
_private: dict[str, "Match"] = {}
_expired_codes: dict[str, float] = {}     # private codes that ran out: they answer 410 (not 404) for an hour
_runner: Optional[asyncio.Task] = None
_runner_loop: Optional[asyncio.AbstractEventLoop] = None


def reset() -> None:
    """Forget everything (tests)."""
    global _runner, _runner_loop
    with _lock:
        _tickets.clear()
        _matches.clear()
        _private.clear()
        _expired_codes.clear()
        for q in _queues.values():
            q.clear()
        task, _runner, _runner_loop = _runner, None, None
    if task is not None and not task.done():
        try:
            task.get_loop().call_soon_threadsafe(task.cancel)
        except RuntimeError:
            pass


def live_matches() -> int:
    return sum(1 for m in _matches.values() if m.phase != "over")


# --------------------------------------------------------------------------- connections


class Conn:
    """One WebSocket and its outbox. ``send`` may be called from any thread."""

    def __init__(self, ws: Any, loop: asyncio.AbstractEventLoop):
        self.ws, self.loop = ws, loop
        self.q: asyncio.Queue = asyncio.Queue(maxsize=OUTBOX_LIMIT)
        self.dead = False

    def send(self, msg: dict) -> None:
        self._submit(json.dumps(msg, separators=(",", ":"), ensure_ascii=False))

    def close(self, code: int = 1000) -> None:
        self._submit(("close", code))

    def _submit(self, item: Any) -> None:
        try:
            self.loop.call_soon_threadsafe(self._put, item)
        except RuntimeError:  # the loop is gone (shutdown)
            self.dead = True

    def _put(self, item: Any) -> None:
        if self.dead:
            return
        try:
            self.q.put_nowait(item)
        except asyncio.QueueFull:  # a client that does not read: cut it off, it will reconnect
            self.dead = True
            asyncio.ensure_future(self._kill())

    async def _kill(self) -> None:
        try:
            await self.ws.close(1013)
        except Exception:  # noqa: BLE001
            pass

    async def pump(self) -> None:
        try:
            while True:
                item = await self.q.get()
                if isinstance(item, tuple):
                    await self.ws.close(item[1])
                    return
                await self.ws.send_text(item)
        except Exception:  # noqa: BLE001 - the peer is gone; the receive loop notices too
            self.dead = True


# --------------------------------------------------------------------------- players, puzzles


class Served:
    """A puzzle served to a player for one lock part or one bug line."""

    __slots__ = ("id", "kind", "topic", "template_id", "tier", "bug_id", "hint", "answered", "correct")

    def __init__(self, row: dict, kind: str, tier: int, bug_id: Optional[int]):
        self.id, self.kind, self.tier, self.bug_id = row["id"], kind, tier, bug_id
        self.topic, self.template_id = row["topic"], row["template_id"]
        self.hint = 0
        self.answered = False
        self.correct: Optional[bool] = None


class Player:
    """One side of a match; also the ticket holder (``ticket`` is the secret that opens the socket)."""

    def __init__(self, level: str, nickname: str, device_hash: Optional[str], kind: str, bot: bool = False):
        self.ticket = secrets.token_hex(16)
        self.token = secrets.token_hex(16)        # the match_token of the HTTP puzzle endpoints
        self.level, self.nickname, self.device_hash, self.kind, self.bot = level, nickname, device_hash, kind, bot
        self.created = self.last_seen = now()
        self.conn: Optional[Conn] = None
        self.connected = bot
        self.ready = bot
        self.rating: Optional[int] = None
        self.match: Optional["Match"] = None
        self.index = -1
        self.game: Optional[E.RescueGame] = None
        self.rev = 0
        self.dropped_at: Optional[float] = None
        self.final: Optional[dict] = None
        self.stamps: deque = deque()              # real times of recent messages (rate limit)
        self.opp_dirty = True
        self.opp_pushed = -1e9
        # puzzles
        self.served: dict[str, Served] = {}
        self.history: list[tuple[str, str]] = []
        self.counts: dict[tuple, int] = {}
        self.lock_parts: list[Served] = []
        self.lock_opened = False
        self.lock_debugger = False
        self.open_debug: Optional[Served] = None
        self.brain: Optional[pvp_bot.BotBrain] = None
        # Misaki (docs/pvp.md section 5): the chosen ladder level (None: the generic "Máy" bot), training mode, coach
        self.misaki: Optional[int] = None
        self.training = False
        self.coach: Optional[pvp_coach.Coach] = None
        self.last_suggest = -1e9
        self.last_look = -1e9

    def send(self, msg: dict) -> None:
        if self.conn is not None:
            self.conn.send(msg)

    @property
    def opponent(self) -> Optional["Player"]:
        return self.match.sides[1 - self.index] if self.match else None

    def reset_lock(self) -> None:
        self.lock_parts = []
        self.lock_opened = False
        self.lock_debugger = False


# --------------------------------------------------------------------------- views (JSON for the browser)


def _cells_view(grid: list) -> list:
    return [[None if not x else {"topic": x["topic"], "bug": x["bug"], "bugId": x["bug_id"]} for x in row]
            for row in grid]


def _piece_view(p: Optional[E.Piece]) -> Optional[dict]:
    if p is None:
        return None
    h = max(r for r, _ in p.cells) + 1
    w = max(c for _, c in p.cells) + 1
    return {"id": p.id, "shape": p.shape, "cells": [list(x) for x in p.cells], "w": w, "h": h, "topic": p.topic}


def _template_of(topic: str, template_id: Optional[str]) -> str:
    return template_id or f"{topic}_bug"


def state_view(p: Player) -> dict:
    g = p.game
    lock = None
    if g.lock:
        lock = {**{k: g.lock[k] for k in ("rows", "cols", "count", "tier", "boss", "topic")},
                "cells": [list(x) for x in g.lock["cells"]], "debugger": p.lock_debugger}
    return {
        "grid": _cells_view(g.grid), "tray": [_piece_view(x) for x in g.tray], "score": g.score, "streak": g.streak,
        "items": dict(g.items), "pending": [{"topic": x["topic"], "templateId": _template_of(x["topic"], x["template_id"])}
                                            for x in g.pending],
        "bugLines": [{"id": b["id"], "cells": [list(x) for x in b["cells"]], "topic": b["topic"],
                      "templateId": _template_of(b["topic"], b["template_id"])} for b in g.bug_lines],
        "lock": lock, "phase": g.phase, "status": g.status, "bestStreak": g.best_streak,
        "sent": g.sent, "received": g.received, "endReason": g.end_reason,
    }


def opponent_view(o: Player) -> dict:
    g = o.game
    return {"grid": _cells_view(g.grid), "score": g.score, "pending": len(g.pending), "lock": g.phase == "locked",
            "phase": g.phase, "connected": o.connected}


def _stats(p: Player) -> dict:
    g = p.game
    if g is None:
        return {"score": 0, "sent": 0, "received": 0, "locks": 0}
    return {"score": g.score, "sent": g.sent, "received": g.received, "locks": g.locks_cleared}


def _board_rows(g: E.RescueGame) -> list[str]:
    return ["".join("." if cell is None else "B" if cell["bug"] else "#" for cell in row) for row in g.grid]


# --------------------------------------------------------------------------- the match


class Match:
    def __init__(self, level: str, kind: str):
        self.id = secrets.token_hex(8)
        self.seed = secrets.randbits(32)
        self.level, self.kind = level, kind                # kind: queue | private | bot
        self.sides: list[Optional[Player]] = [None, None]
        self.phase = "lobby"                               # lobby | playing | over
        self.created = now()
        self.paired_at: Optional[float] = None
        self.countdown_at: Optional[float] = None
        self._last_sec: Optional[int] = None
        self.started_at = 0.0
        self.start_wall = 0.0
        self.next_overtime = 0
        self.ended_at = 0.0
        self.winner: Optional[int] = None
        self.reason: Optional[str] = None
        self.code: Optional[str] = None                    # private duels
        self.rematch = [False, False]                      # private duels: who asked for another round
        self.rematch_until: Optional[float] = None
        self.training = False                              # bot matches: Misaki also coaches (section 5.4)

    # ---- helpers ----
    def players(self) -> list[Player]:
        return [s for s in self.sides if s is not None]

    def humans(self) -> list[Player]:
        return [s for s in self.players() if not s.bot]

    def elapsed(self) -> float:
        return max(0.0, now() - self.started_at) if self.phase != "lobby" else 0.0

    def trace(self, event: str, **fields: Any) -> None:
        diagnostics.info("pvp %s", json.dumps({"event": event, "match": self.id, "seed": self.seed,
                                              "elapsed_s": round(self.elapsed(), 3), **fields}, separators=(",", ":")))

    def seat(self, p: Player, index: int) -> None:
        self.sides[index] = p
        p.match, p.index = self, index

    # ---- lobby ----
    def lobby_msg(self, p: Player) -> dict:
        o = p.opponent
        starts = None if self.countdown_at is None else max(0, math.ceil(self.countdown_at - now()))
        return {"t": "lobby", "you": {"nickname": p.nickname, "rating": p.rating}, "level": self.level,
                "opponent": None if o is None else self.opponent_lobby(o), "starts_in": starts}

    @staticmethod
    def opponent_lobby(o: Player) -> dict:
        out = {"nickname": o.nickname, "bot": o.bot, "connected": o.connected, "rating": o.rating}
        if o.bot and o.misaki:
            # `misaki` / `title` are the level the player CHOSE; `plays_as` is the level she really plays at (one lower
            # in training mode)
            out.update({"misaki": o.misaki, "title": pvp_bot.title(o.misaki), "training": o.training,
                        "plays_as": pvp_bot.effective_level(o.misaki, o.training)})
        return out

    def push_lobby(self) -> None:
        if self.phase != "lobby":
            return
        for p in self.players():
            p.send(self.lobby_msg(p))

    def cancel(self, code: str, message: str) -> None:
        for p in self.players():
            p.send({"t": "error", "code": code, "message": message})
            if p.conn is not None:
                p.conn.close(4000)
        self.phase = "over"
        self.reason = code
        self.ended_at = now() - KEEP_OVER_S               # nothing to reconnect to: sweep at the next tick
        if code == "expired" and self.code and len(_expired_codes) < 5000:
            _expired_codes[self.code] = now()
        self.drop()

    def drop(self) -> None:
        _matches.pop(self.id, None)
        if self.code:
            _private.pop(self.code, None)
        for p in self.players():
            _tickets.pop(p.ticket, None)

    # ---- sockets ----
    def attach(self, p: Player, conn: Conn) -> None:
        old = p.conn
        p.conn, p.connected, p.last_seen = conn, True, now()
        if old is not None and old is not conn:
            old.send({"t": "error", "code": "replaced", "message": "Bạn đã mở ván đấu ở nơi khác."})
            old.close(4001)
        if self.phase == "lobby":
            self.push_lobby()
        elif self.phase == "playing":
            back = p.dropped_at is not None
            p.dropped_at = None
            self.send_start(p)
            self.push_state(p, bump=True)
            o = p.opponent
            if o is not None:
                p.opp_dirty = True
                if back:
                    o.send({"t": "opponent_status", "connected": True, "grace_s": 0})
                o.opp_dirty = True
        else:
            if p.final:
                p.send(p.final)
            if self.rematch_until is not None:                 # a private duel: the sockets stay open for a rematch
                p.send(self.rematch_msg(p))
            else:
                conn.close(1000)

    def rematch_msg(self, p: Player) -> dict:
        return {"t": "rematch_status", "you": self.rematch[p.index], "opponent": self.rematch[1 - p.index]}

    def ask_rematch(self, p: Player) -> None:
        if self.phase != "over" or self.rematch_until is None or now() > self.rematch_until:
            return _error(p, "no_rematch", "Không thể đấu lại ván này.")
        self.rematch[p.index] = True
        a, b = self.sides
        if a is not None and b is not None and all(s.connected and self.rematch[s.index] for s in (a, b)):
            return self.new_round()
        for s in self.humans():
            s.send(self.rematch_msg(s))

    def new_round(self) -> None:
        """Both players of a private duel asked for a rematch: a fresh seed, new tokens, the same sockets."""
        _matches.pop(self.id, None)
        self.id = secrets.token_hex(8)
        _matches[self.id] = self
        self.seed = secrets.randbits(32)
        self.winner = self.reason = None
        self.rematch, self.rematch_until = [False, False], None
        self.next_overtime = 0
        for p in self.players():
            p.token = secrets.token_hex(16)
            p.final, p.dropped_at, p.rev = None, None, 0
            p.served, p.history, p.counts, p.open_debug = {}, [], {}, None
            p.reset_lock()
            p.opp_pushed = -1e9
        self.start()

    def detach(self, p: Player, conn: Conn) -> None:
        if p.conn is not conn:
            return                                          # replaced by a newer socket
        p.conn, p.connected, p.last_seen = None, False, now()
        if self.phase == "lobby":
            self.countdown_at = None
            self.push_lobby()
        elif self.phase == "playing":
            p.dropped_at = now()
            o = p.opponent
            if o is not None:
                o.send({"t": "opponent_status", "connected": False, "grace_s": GRACE_S})
                o.opp_dirty = True
        elif self.rematch_until is not None and self.rematch[p.index]:
            self.rematch[p.index] = False                       # gone: the other player's wish can no longer be met
            for s in self.humans():
                s.send(self.rematch_msg(s))

    # ---- start ----
    def send_start(self, p: Player) -> None:
        p.send({"t": "start", "seed": self.seed, "level": self.level, "match_id": self.id, "match_token": p.token,
                "at": self.start_wall, "elapsed": round(self.elapsed(), 2)})

    def start(self) -> None:
        self.phase = "playing"
        self.started_at = now()
        self.start_wall = time.time()
        self.countdown_at = None
        self.trace("start", kind=self.kind, level=self.level,
                   players=[{"side": p.index, "bot": p.bot, "misaki": p.misaki, "training": p.training}
                            for p in self.players()])
        for p in self.players():
            p.game = E.RescueGame(self.seed, self.level, "pvp")
            if p.bot:
                chosen = p.misaki or pvp_bot.LEGACY_LEVEL[self.level]
                p.brain = pvp_bot.BotBrain(self.seed, pvp_bot.effective_level(chosen, p.training), p.training,
                                           stream=f"bot:{p.index}")
                p.brain.next_at = self.started_at + p.brain.place_delay()
            elif self.training:
                p.coach = pvp_coach.Coach(self.seed)
                p.last_look = -1e9
            self.send_start(p)
            self.push_state(p, bump=True)
            p.opp_dirty = True

    # ---- pushes ----
    def push_state(self, p: Player, bump: bool = True) -> None:
        if bump:
            p.rev += 1
        if p.conn is not None:
            p.send({"t": "state", "you": state_view(p), "rev": p.rev})

    def changed(self, p: Player) -> None:
        """``p``'s game changed: tell ``p`` (full state), mark both opponent views dirty and see whether the match is over."""
        self.push_state(p)
        p.opp_dirty = True
        o = p.opponent
        if o is not None:
            o.opp_dirty = True
        if p.game.phase == "over" and self.phase == "playing":
            self.finish(1 - p.index, p.game.end_reason or "nofit")
        elif p.coach is not None:
            self.coach_look(p)

    # ---- training mode: Misaki coaches (docs/pvp.md section 5.4) ----
    def coach_say(self, p: Player, msg: Optional[dict]) -> None:
        if msg is not None:
            p.send(msg)

    def coach_event(self, p: Player, kind: str, **kw: Any) -> None:
        if p.coach is not None and self.phase == "playing":
            self.coach_say(p, p.coach.event(kind, now(), **kw))

    def coach_look(self, p: Player) -> None:
        """The coach looks at the player's board (after every change and about twice a second)."""
        c = p.coach
        if c is None or self.phase != "playing" or p.game is None:
            return
        t = now()
        p.last_look = t
        self.coach_say(p, c.due(t))
        self.coach_say(p, c.observe(p.game, t))

    def push_opponents(self) -> None:
        t = now()
        for p in self.humans():
            o = p.opponent
            if p.conn is None or o is None or o.game is None or not p.opp_dirty or t - p.opp_pushed < OPPONENT_PUSH_S:
                continue
            p.opp_pushed, p.opp_dirty = t, False
            p.send({"t": "opponent", **opponent_view(o)})

    # ---- actions (the same code for a human's message and for the bot) ----
    def do_place(self, p: Player, i: int, r: int, c: int) -> bool:
        g = p.game
        pending = len(g.pending)
        before = _board_rows(g) if pending else None
        piece = g.tray[i] if 0 <= i < len(g.tray) else None
        res = g.place(i, r, c) if g.phase == "play" else None
        if res is None:
            return False
        if res["landed"]:
            self.trace("landing", side=p.index, move={"i": i, "r": r, "c": c},
                       cells=[[r + dr, c + dc] for dr, dc in piece.cells],
                       pending_before=pending, rows=res["landed"], received=g.received,
                       board_before=before, board_after=_board_rows(g), end_reason=g.end_reason)
        if res["lock"]:
            g.phase = "locked"
            p.reset_lock()
        if res["landed"] and g.phase != "over":
            p.send({"t": "landed", "rows": res["landed"]})
        self.changed(p)
        return True

    def do_bomb(self, p: Player, r: int, c: int) -> bool:
        g = p.game
        if g.phase != "play" or g.bomb(r, c) is None:
            return False
        self.changed(p)
        return True

    def do_shuffle(self, p: Player) -> bool:
        g = p.game
        if g.phase != "play" or not g.shuffle():
            return False
        self.changed(p)
        return True

    def do_undo(self, p: Player) -> bool:
        g = p.game
        if g.phase != "locked" or p.lock_opened or not g.undo():
            return False
        p.reset_lock()
        self.changed(p)
        return True

    # ---- puzzles ----
    def pick_puzzle(self, p: Player, kind: str, topic: str, tier: int, template: Optional[str],
                    bug_id: Optional[int]) -> dict:
        """The deterministic puzzle for this player's situation, recorded as served to them."""
        key = (kind, topic, tier, template)
        n = p.counts.get(key, 0)
        rng = random.Random(f"{self.seed}:{kind}:{topic}:{tier}:{template}:{n}")
        hist = p.history[-HISTORY_IDS:]
        row = bank.select_puzzle(
            kind=kind, topic=topic, tier=tier, level=self.level, template_id=template,
            exclude_ids=[h[0] for h in hist], exclude_templates=[h[1] for h in reversed(hist[-HISTORY_TEMPLATES:])],
            rng=rng)
        p.counts[key] = n + 1
        p.history.append((row["id"], row["template_id"]))
        sv = Served(row, kind, tier, bug_id)
        p.served[row["id"]] = sv
        return row

    def serve(self, p: Player, kind: str, bug: Optional[int]) -> dict:
        """What ``POST /api/puzzle/next`` does for a valid match pair. Raises ``PvpError`` (409/422) when the
        player has nothing to solve."""
        g = p.game
        if self.phase != "playing" or g is None or g.phase == "over":
            raise PvpError("Ván đấu đã kết thúc.", 409)
        if len(p.served) >= MAX_SERVED_PER_PLAYER:
            raise PvpError("Đã dùng quá nhiều câu đố trong ván này.", 409)
        if kind == "rescue":
            lk = g.lock
            if g.phase != "locked" or lk is None:
                raise PvpError("Bạn chưa có khóa nào cần giải.", 409)
            need = 2 if lk["boss"] else 1
            if p.lock_parts and not p.lock_parts[-1].answered:  # asked again: the same puzzle (no re-roll)
                return bank.get_puzzle(p.lock_parts[-1].id)
            if len(p.lock_parts) >= need:
                raise PvpError("Khóa này đã có đủ câu đố.", 409)
            tier = 3 if lk["boss"] else lk["tier"]
            row = self.pick_puzzle(p, "rescue", lk["topic"], tier, None, None)
            p.lock_parts.append(p.served[row["id"]])
            if not p.lock_opened:
                p.lock_opened = True
                p.lock_debugger = g.pvp_open_lock()           # a Debugger is spent automatically, as in Rescue
                self.changed(p)
            return row
        if kind == "debug":
            if g.phase != "play":
                raise PvpError("Hãy giải khóa đang mở trước khi sửa dòng lỗi.", 409)
            if bug is None:
                raise PvpError("kind 'debug' cần có bug (id dòng lỗi).", 422)
            bl = next((b for b in g.bug_lines if b["id"] == bug), None)
            if bl is None:
                raise PvpError("Không có dòng lỗi này.", 409)
            if p.open_debug is not None and not p.open_debug.answered and p.open_debug.bug_id == bug:
                return bank.get_puzzle(p.open_debug.id)
            row = self.pick_puzzle(p, "debug", bl["topic"], 1, _template_of(bl["topic"], bl["template_id"]), bug)
            p.open_debug = p.served[row["id"]]
            return row
        raise PvpError("Đối kháng không có Last Commit.", 422)

    def answered(self, p: Player, sv: Served, correct: bool) -> None:
        """The server checked the answer to ``sv``: apply it to the game when it is the player's current puzzle."""
        g = p.game
        if sv.answered:
            return                                              # the first answer counts
        sv.answered, sv.correct = True, correct
        if self.phase != "playing" or g is None or g.phase == "over":
            return
        if sv.kind == "rescue":
            if g.phase != "locked" or g.lock is None or not p.lock_parts or p.lock_parts[-1] is not sv:
                return
            if correct and len(p.lock_parts) < (2 if g.lock["boss"] else 1):
                return                                          # a boss lock: the second puzzle is next
            parts = [{"correct": s.correct, "hint": s.hint, "topic": s.topic, "template_id": s.template_id}
                     for s in p.lock_parts]
            lines = g.lock["count"]
            res = g.pvp_resolve_lock(p.lock_debugger, parts)
            p.reset_lock()
            if p.coach is not None:
                if res["result"] == "bug":
                    self.coach_event(p, "wrong", topic=pvp_coach.TOPIC_VI.get(res["topic"], ""))
                else:
                    if lines >= 2:
                        self.coach_event(p, "good", n=lines)
                    if g.streak == 3:
                        self.coach_event(p, "streak", n=3)
            self.deliver(p, res)
            self.changed(p)
        elif sv.kind == "debug":
            if g.phase != "play" or p.open_debug is not sv:
                return
            p.open_debug = None
            bl = next((b for b in g.bug_lines if b["id"] == sv.bug_id), None)
            if bl is None:
                return
            if correct:
                g.fix_bug(sv.bug_id)
            else:
                g.apply_debug_wrong(sv.topic, sv.template_id)
            self.changed(p)

    def deliver(self, p: Player, res: dict) -> None:
        """Tell the sender what it sent / cancelled and queue the lines on the opponent."""
        send, cancelled = res["send"], res["cancelled"]
        if send or cancelled:
            p.send({"t": "sent", "lines": send, "cancelled": cancelled})
        if cancelled:
            self.coach_event(p, "cancel", n=cancelled)
        o = p.opponent
        if send and o is not None and o.game is not None and o.game.phase != "over":
            topic = res["topic"]
            entries = [{"topic": topic, "template_id": _template_of(topic, res["template_id"])}] * send
            o.game.queue_incoming(entries)
            self.trace("incoming", side=o.index, source="opponent", sender=p.index, rows=send,
                       pending=len(o.game.pending), received=o.game.received)
            o.send({"t": "incoming", "lines": send, "from_topic": topic})
            self.push_state(o)
            o.opp_dirty = p.opp_dirty = True
            self.coach_event(o, "incoming")
            if o.coach is not None:
                self.coach_look(o)

    def suggest(self, p: Player) -> None:
        """Training mode: Misaki's level-4 search on the player's own state (``{"t": "suggest"}``)."""
        if not self.training:
            return _error(p, "not_training")
        g = p.game
        if self.phase != "playing" or g is None or g.phase == "over":
            return _error(p, "not_playing")
        t = _real()
        if t - p.last_suggest < SUGGEST_EVERY_S:
            return                                              # at most one every 3 s: dropped silently
        p.last_suggest = t
        sg = pvp_bot.suggest(g)
        if sg is None:
            p.send({"t": "suggestion", "none": True, "why": pvp_coach.suggestion_text("none")})
        else:
            p.send({"t": "suggestion", "i": sg.i, "r": sg.r, "c": sg.c, "cells": sg.cells,
                    "why": pvp_coach.suggestion_text(sg.reason, sg.n)})

    # ---- the end ----
    def finish(self, winner: Optional[int], reason: str) -> None:
        if self.phase == "over":
            return
        self.phase = "over"
        self.winner, self.reason, self.ended_at = winner, reason, now()
        self.trace("end", winner=winner, reason=reason,
                   players=[{"side": p.index, "bot": p.bot, **_stats(p),
                             "pending": len(p.game.pending) if p.game else 0,
                             "board": _board_rows(p.game) if p.game else None} for p in self.players()])
        humans = self.humans()
        rated: Optional[tuple] = None
        if (self.kind != "bot" and len(humans) == 2 and reason not in ("both_disconnected", "server_restart")
                and humans[0].device_hash != humans[1].device_hash):
            a, b = self.sides
            score_a = 0.5 if winner is None else (1.0 if winner == 0 else 0.0)
            rated = ranked.pvp_apply_result(a.device_hash, b.device_hash, score_a)
        for p in self.players():
            g = p.game
            if g is not None and g.phase != "over":
                if winner == p.index:
                    g.phase = "over"              # the winner's board just stops (no end reason of its own)
                else:
                    g.end_game(reason)
        ladder: Optional[dict] = None                 # a match against Misaki: the ladder result (section 5.2)
        bot = next((x for x in self.players() if x.bot and x.misaki), None)
        if self.kind == "bot" and bot is not None and len(humans) == 1:
            ladder = {"level": bot.misaki, "unlocked_now": None}
            if not bot.training and winner is not None and reason not in ("both_disconnected", "server_restart"):
                ladder["unlocked_now"] = ranked.misaki_record(humans[0].device_hash, bot.misaki,
                                                              winner == humans[0].index)
        for p in humans:
            o = p.opponent
            who = "draw" if winner is None else ("you" if winner == p.index else "opponent")
            msg = {"t": "end", "winner": who, "reason": reason, "you": _stats(p),
                   "opponent": {**_stats(o), "nickname": o.nickname, "bot": o.bot}}
            if rated is not None:
                before, after = rated[p.index]
                msg["rating"] = {"before": before, "after": after}
            if ladder is not None:
                msg["misaki"] = dict(ladder)
            p.final = msg
            if p.game is not None:
                self.push_state(p)
                if o is not None and o.game is not None:
                    p.send({"t": "opponent", **opponent_view(o)})
            p.send(msg)
            if self.kind == "private" and reason != "server_restart":
                p.send(self.rematch_msg(p))
            elif p.conn is not None:
                p.conn.close(1000)
        if self.kind == "private" and reason != "server_restart":
            self.rematch_until = now() + REMATCH_S

    # ---- clock ----
    def tick(self) -> None:
        t = now()
        if self.phase == "lobby":
            self.tick_lobby(t)
        elif self.phase == "playing":
            self.tick_playing(t)
        elif self.rematch_until is not None and t > self.rematch_until:
            self.rematch_until = None                           # the window closed: tell them and let go
            for p in self.humans():
                p.send({"t": "rematch_status", "you": False, "opponent": False, "expired": True})
                if p.conn is not None:
                    p.conn.close(1000)
        elif t - self.ended_at > KEEP_OVER_S:
            self.drop()

    def tick_lobby(self, t: float) -> None:
        a, b = self.sides
        ready = a is not None and b is not None and all(s.connected and s.ready for s in (a, b))
        if ready:
            if self.countdown_at is None:
                self.countdown_at = t + COUNTDOWN_S
                self._last_sec = None
            sec = max(0, math.ceil(self.countdown_at - t))
            if sec != self._last_sec:
                self._last_sec = sec
                self.push_lobby()
            if t >= self.countdown_at:
                self.start()
            return
        if self.countdown_at is not None:
            self.countdown_at = None
            self.push_lobby()
        if b is not None and self.paired_at is not None and t - self.paired_at > LOBBY_TIMEOUT_S:
            self.cancel("lobby_timeout", "Hai người chơi chưa sẵn sàng, trận đấu bị hủy.")
        elif b is None and t - self.created > PRIVATE_TTL_S:
            self.cancel("expired", "Mã phòng đã hết hạn (10 phút).")
        elif not any(s.connected for s in self.humans()) and all(
                t - s.last_seen > STALE_UNSEEN_S for s in self.humans()):
            self.drop()                                         # everybody left the lobby long ago

    def tick_playing(self, t: float) -> None:
        # overtime: from 4:00 one bug line every 20 s to both players
        while t - self.started_at >= OVERTIME_AT_S + self.next_overtime * OVERTIME_EVERY_S:
            topic = random.Random(f"{self.seed}:overtime:{self.next_overtime}").choice(E.TOPICS)
            self.next_overtime += 1
            for p in self.players():
                if p.game.phase == "over":
                    continue
                p.game.queue_incoming([{"topic": topic, "template_id": f"{topic}_bug"}])
                self.trace("incoming", side=p.index, source="overtime", rows=1,
                           pending=len(p.game.pending), received=p.game.received)
                p.send({"t": "incoming", "lines": 1, "from_topic": topic, "overtime": True})
                self.push_state(p)
                p.opp_dirty = True
        # bots
        for p in self.players():
            if p.bot and self.phase == "playing":
                self.bot_act(p, t)
        # training: the coach looks at the human's board twice a second (deferred messages, the bug line timer)
        for p in self.humans():
            if p.coach is not None and self.phase == "playing" and t - p.last_look >= COACH_LOOK_S:
                self.coach_look(p)
        # disconnect grace
        if self.phase == "playing":
            expired = [p for p in self.humans() if p.dropped_at is not None and t - p.dropped_at >= GRACE_S]
            if expired:
                if all(not p.connected for p in self.humans()):
                    self.finish(None, "both_disconnected")
                else:
                    self.finish(1 - expired[0].index, "disconnect")
        if self.phase == "playing":
            self.push_opponents()

    # ---- the bot (Misaki, docs/pvp.md section 5) ----
    def bot_act(self, p: Player, t: float) -> None:
        """Run what the bot's brain wants now through the same code a human's messages and answers take."""
        g, brain = p.game, p.brain
        act = brain.step(g, t)
        if act is None:
            return
        kind = act[0]
        try:
            if kind == "solve":
                for ok in act[1]:
                    row = self.serve(p, "rescue", None)
                    self.answered(p, p.served[row["id"]], ok)
                    if g.phase != "locked":
                        break
            elif kind == "fix":
                row = self.serve(p, "debug", act[1])
                self.answered(p, p.served[row["id"]], act[2])
            elif kind == "place":
                self.do_place(p, act[1], act[2], act[3])
            elif kind == "bomb":
                self.do_bomb(p, act[1], act[2])
            elif kind == "shuffle":
                self.do_shuffle(p)
        except PvpError:                                        # e.g. the puzzle server refused: she tries again later
            log.exception("bot action failed")


# --------------------------------------------------------------------------- messages from a browser


def _is_int(x: Any) -> bool:
    return type(x) is int


def _error(p: Player, code: str, message: Optional[str] = None) -> None:
    p.send({"t": "error", "code": code, "message": message or _ERR.get(code, code)})


def handle_message(p: Player, conn: Conn, raw: str) -> None:
    """One text frame from a socket. Never raises."""
    try:
        with _lock:
            if p.conn is not conn:
                return
            t = _real()
            while p.stamps and t - p.stamps[0] >= 1.0:
                p.stamps.popleft()
            if len(p.stamps) >= MAX_ACTIONS_PER_S:
                return                                          # dropped
            p.stamps.append(t)
            try:
                msg = json.loads(raw)
            except ValueError:
                return _error(p, "bad_message")
            if not isinstance(msg, dict) or not isinstance(msg.get("t"), str):
                return _error(p, "bad_message")
            _dispatch(p, msg)
    except Exception:  # noqa: BLE001 - a bad message must never take the socket handler down
        log.exception("pvp message failed")


def _dispatch(p: Player, msg: dict) -> None:
    kind = msg["t"]
    m = p.match
    if kind == "ping":
        n = msg.get("n")
        p.send({"t": "pong", "n": n if isinstance(n, (int, float, str)) and not isinstance(n, bool)
                and len(str(n)) <= 32 else None})
        return
    if kind == "ready":                                          # also before an opponent was found
        if m is None or m.phase == "lobby":
            p.ready = True
        return
    if m is None:
        return _error(p, "not_playing")
    if kind == "suggest":
        return m.suggest(p)
    if kind == "rematch":
        return m.ask_rematch(p)
    if kind not in ("place", "bomb", "shuffle", "undo", "resign"):
        return _error(p, "bad_message")
    if m.phase != "playing" or p.game is None or p.game.phase == "over":
        return _error(p, "not_playing")
    if kind == "resign":
        return m.finish(1 - p.index, "resign")
    ok = False
    if kind == "place":
        if all(_is_int(msg.get(k)) for k in ("i", "r", "c")):
            # An attack arriving in transit must be shown before this placement can land it.
            if "received" in msg:
                received = msg["received"]
                if not _is_int(received) or received < 0:
                    return _error(p, "bad_message")
                if received != p.game.received:
                    m.trace("stale_place", side=p.index, seen_received=received, received=p.game.received,
                            move={"i": msg["i"], "r": msg["r"], "c": msg["c"]})
                    _error(p, "stale_state")
                    m.push_state(p)
                    return
            ok = m.do_place(p, msg["i"], msg["r"], msg["c"])
        else:
            return _error(p, "bad_message")
    elif kind == "bomb":
        if all(_is_int(msg.get(k)) for k in ("r", "c")):
            ok = m.do_bomb(p, msg["r"], msg["c"])
        else:
            return _error(p, "bad_message")
    elif kind == "shuffle":
        ok = m.do_shuffle(p)
    elif kind == "undo":
        ok = m.do_undo(p)
    if not ok:                                                  # illegal: say so and resync the browser
        _error(p, "illegal")
        m.push_state(p)


# --------------------------------------------------------------------------- the clock (one task for all matches)


async def _run() -> None:
    last_sweep = 0.0
    while True:
        await asyncio.sleep(TICK_S)
        with _lock:
            for m in list(_matches.values()):
                try:
                    m.tick()
                except Exception:  # noqa: BLE001
                    log.exception("pvp tick failed")
            t = now()
            if t - last_sweep >= 1.0:
                last_sweep = t
                _sweep(t)


def ensure_runner(loop: asyncio.AbstractEventLoop) -> None:
    global _runner, _runner_loop
    with _lock:
        if _runner is None or _runner.done() or _runner_loop is not loop:
            _runner_loop = loop
            _runner = loop.create_task(_run())


def _wake(p: Player) -> None:
    """Called from a worker thread: make sure the clock runs on the loop of a connected player."""
    c = p.conn
    if c is not None:
        c.loop.call_soon_threadsafe(ensure_runner, c.loop)


def _sweep(t: float) -> None:
    """Drop stale queue entries and tickets nobody ever used (called with the lock held)."""
    for level, q in _queues.items():
        for p in list(q):
            if not _alive(p, t):
                q.remove(p)
                if p.conn is not None:
                    p.send({"t": "error", "code": "queue_timeout", "message": "Chưa tìm thấy đối thủ."})
                    p.conn.close(4000)
                _tickets.pop(p.ticket, None)
    for code, at in list(_expired_codes.items()):
        if t - at > 3600:
            del _expired_codes[code]
    for tid, p in list(_tickets.items()):
        if p.match is None and p not in _queues.get(p.level, ()) and t - p.last_seen > STALE_UNSEEN_S:
            _tickets.pop(tid, None)
    for m in list(_matches.values()):
        if m.phase == "over" and t - m.ended_at > KEEP_OVER_S:
            m.drop()
        elif m.phase == "lobby" and t - m.created > PRIVATE_TTL_S + LOBBY_TIMEOUT_S:
            m.drop()


def _alive(p: Player, t: float) -> bool:
    if t - p.created > QUEUE_TIMEOUT_S:
        return False
    return p.conn is not None or t - p.last_seen < QUEUE_FRESH_S


# --------------------------------------------------------------------------- HTTP: matchmaking


def _new_player(level: str, nickname: str, device_id: str, client: Optional[str], kind: str) -> Player:
    nickname, device_hash = ranked._clean_identity(nickname, device_id)
    ranked.take_pvp_slot(client)
    p = Player(level, nickname, device_hash, kind)
    p.rating = ranked.pvp_rating(device_hash)
    return p


def _check_room() -> None:
    if len(_tickets) >= MAX_TICKETS or live_matches() >= MAX_LIVE_MATCHES:
        raise PvpError("Máy chủ đang có quá nhiều trận đối kháng. Hãy thử lại sau ít phút.", 503)


def _pair(level: str, kind: str, first: Player, second: Optional[Player]) -> Match:
    m = Match(level, kind)
    _matches[m.id] = m
    m.seat(first, 0)
    if second is not None:
        m.seat(second, 1)
        m.paired_at = now()
    return m


def queue_join(level: str, nickname: str, device_id: str, client: Optional[str]) -> dict:
    p = _new_player(level, nickname, device_id, client, "queue")
    with _lock:
        _sweep(now())
        _check_room()
        _tickets[p.ticket] = p
        t = now()
        q = _queues[level]
        for other in list(q):
            if not _alive(other, t):
                q.remove(other)
                _tickets.pop(other.ticket, None)
                continue
            if other.device_hash == p.device_hash:
                continue                                        # never against yourself
            q.remove(other)
            m = _pair(level, "queue", other, p)
            m.push_lobby()
            _wake(other)
            break
        else:
            q.append(p)
    return {"ticket": p.ticket}


def queue_leave(ticket: str) -> None:
    with _lock:
        p = _tickets.get(ticket)
        if p is None or p.kind != "queue":
            raise PvpError("Không tìm thấy vé này.", 404)
        if p.match is None:
            _queues[p.level] = [x for x in _queues[p.level] if x is not p]
            _tickets.pop(ticket, None)
            return
        m = p.match
        if m.phase != "lobby":
            raise PvpError("Trận đấu đã bắt đầu.", 409)
        o = p.opponent
        if o is not None:                                       # the other player is told and may queue again
            o.send({"t": "error", "code": "opponent_left", "message": "Đối thủ đã rời hàng chờ."})
            if o.conn is not None:
                o.conn.close(4000)
        m.phase = "over"
        m.ended_at = now() - KEEP_OVER_S
        m.drop()


def private_create(level: str, nickname: str, device_id: str, client: Optional[str]) -> dict:
    p = _new_player(level, nickname, device_id, client, "private")
    with _lock:
        _sweep(now())
        _check_room()
        for _ in range(50):
            code = "".join(secrets.choice(rooms.CODE_ALPHABET) for _ in range(rooms.CODE_LEN))
            if code not in _private:
                break
        else:  # pragma: no cover
            raise PvpError("Không tạo được mã phòng, hãy thử lại.", 503)
        _tickets[p.ticket] = p
        m = _pair(level, "private", p, None)
        m.code = code
        _private[code] = m
    return {"code": code, "ticket": p.ticket}


def private_join(code: str, nickname: str, device_id: str, client: Optional[str]) -> dict:
    code = rooms._normalize_code(code)
    if not rooms._CODE_RE.match(code):
        raise PvpError("Không tìm thấy phòng này.", 404)
    nickname, device_hash = ranked._clean_identity(nickname, device_id)
    ranked.take_pvp_slot(client)
    with _lock:
        m = _private.get(code)
        if m is None:
            if code in _expired_codes:
                raise PvpError("Phòng này đã hết hạn (10 phút).", 410)
            raise PvpError("Không tìm thấy phòng này.", 404)
        if m.sides[1] is not None:
            raise PvpError("Phòng này đã đủ hai người.", 409)
        if now() - m.created > PRIVATE_TTL_S:
            m.cancel("expired", "Mã phòng đã hết hạn (10 phút).")
            raise PvpError("Phòng này đã hết hạn (10 phút).", 410)
        if len(_tickets) >= MAX_TICKETS:
            raise PvpError("Máy chủ đang có quá nhiều trận đối kháng. Hãy thử lại sau ít phút.", 503)
        p = Player(m.level, nickname, device_hash, "private")
        p.rating = ranked.pvp_rating(device_hash)
        _tickets[p.ticket] = p
        m.seat(p, 1)
        m.paired_at = now()
        m.push_lobby()
        host = m.sides[0]
        if host is not None:
            _wake(host)
    return {"ticket": p.ticket}


def bot_start(level: str, nickname: str, device_id: str, client: Optional[str], misaki: Optional[int] = None,
              training: bool = False) -> dict:
    """A match against the bot. ``misaki`` (1..4) picks Misaki of that ladder level (403 while it is locked for the
    device); without it the generic "Máy <animal>" bot plays (ladder level from the game level). ``training``: section
    5.4 (needs ``misaki``; nothing ranked or unlocked)."""
    if training and not misaki:
        raise PvpError("Chế độ luyện tập cần chọn một cấp của Misaki.", 422)
    if misaki is not None and not 1 <= misaki <= pvp_bot.MAX_LEVEL:
        raise PvpError("Cấp của Misaki phải từ 1 đến 4.", 422)
    _, device_hash = ranked._clean_identity(nickname, device_id)
    if misaki and misaki > ranked.misaki_unlocked(device_hash):
        raise PvpError("Bạn chưa mở khóa cấp này của Misaki. Hãy thắng cấp trước đó.", 403)
    p = _new_player(level, nickname, device_id, client, "bot")
    with _lock:
        _sweep(now())
        _check_room()
        name = pvp_bot.NAME if misaki else f"Máy {random.SystemRandom().choice(nicknames.ANIMALS)}"
        bot = Player(level, name, None, "bot", bot=True)
        bot.misaki, bot.training = misaki, bool(training)
        _tickets[p.ticket] = p
        m = _pair(level, "bot", p, bot)
        m.kind = "bot"
        m.training = bool(training)
    return {"ticket": p.ticket}


def misaki_status(device_id: Any) -> dict:
    """``GET /api/pvp/misaki``: the ladder progress of a device."""
    if not isinstance(device_id, str) or not ranked._DEVICE_RE.match(device_id):
        raise PvpError("Mã thiết bị không hợp lệ.", 422)
    return ranked.misaki_progress(ranked._device_hash(device_id))


# --------------------------------------------------------------------------- HTTP: puzzles of a live match


def _find(match_id: Any, token: Any) -> Optional[tuple[Match, Player]]:
    if not isinstance(match_id, str) or not isinstance(token, str) or not token or len(token) > 64:
        return None
    m = _matches.get(match_id)
    if m is None:
        return None
    for p in m.humans():
        if secrets.compare_digest(p.token, token):
            return m, p
    return None


def serve_puzzle(match_id: Any, token: Any, *, kind: str, bug: Optional[int], topic: Optional[str] = None,
                 template_id: Optional[str] = None) -> Optional[tuple[dict, str]]:
    """The puzzle for a valid ``(match_id, match_token)`` pair, picked by the server for the player's current lock
    (``kind`` rescue) or the bug line ``bug`` they tapped (``kind`` debug), and recorded. ``None`` when the pair is
    missing or invalid (the caller then serves a normal random puzzle); ``PvpError`` (409/422) when the pair is valid
    but there is nothing to solve."""
    if not match_id or not token:
        return None
    with _lock:
        found = _find(match_id, token)
        if found is None:
            return None
        m, p = found
        if kind == "debug" and bug is None and p.game is not None:
            # a client that only sends the bug line's template (and topic): the first bug line that matches
            bug = next((b["id"] for b in p.game.bug_lines
                        if _template_of(b["topic"], b["template_id"]) == template_id
                        and (topic is None or b["topic"] == topic)), None)
        return m.serve(p, kind, bug), m.level


def record_hint(match_id: Any, token: Any, puzzle_id: str, level: int) -> None:
    """Remember the highest hint level opened for a puzzle served to this player. Never raises."""
    if not match_id or not token:
        return
    try:
        with _lock:
            found = _find(match_id, token)
            sv = found[1].served.get(puzzle_id) if found else None
            if sv is not None and not sv.answered:
                sv.hint = max(sv.hint, level)
    except Exception:  # noqa: BLE001
        log.exception("pvp hint failed")


def record_answer(match_id: Any, token: Any, puzzle_id: str, correct: bool) -> None:
    """Apply the server-checked answer to the player's game (only for the puzzle served for their current lock or
    bug line; the first answer counts). Never raises."""
    if not match_id or not token:
        return
    try:
        with _lock:
            found = _find(match_id, token)
            if found is None:
                return
            m, p = found
            sv = p.served.get(puzzle_id)
            if sv is not None:
                m.answered(p, sv, bool(correct))
    except Exception:  # noqa: BLE001
        log.exception("pvp answer failed")


# --------------------------------------------------------------------------- WebSocket


async def serve_socket(ws: Any, ticket: str) -> None:
    """``GET /api/pvp/ws?ticket=...``: one player's live connection (a Starlette ``WebSocket``)."""
    await ws.accept()
    loop = asyncio.get_running_loop()
    conn = Conn(ws, loop)
    with _lock:
        p = _tickets.get(ticket) if isinstance(ticket, str) else None
    if p is None:
        await ws.send_text(json.dumps({"t": "error", "code": "bad_ticket",
                                       "message": "Vé không hợp lệ hoặc trận đấu đã kết thúc."}))
        await ws.close(4404)
        return
    ensure_runner(loop)
    pump = asyncio.create_task(conn.pump())
    cut = False
    try:
        with _lock:
            m = p.match
            if m is None:                                       # waiting in the quick-match queue
                old = p.conn
                p.conn, p.connected, p.last_seen = conn, True, now()
                if old is not None and old is not conn:
                    old.send({"t": "error", "code": "replaced", "message": "Bạn đã mở ván đấu ở nơi khác."})
                    old.close(4001)
                conn.send({"t": "lobby", "you": {"nickname": p.nickname, "rating": p.rating}, "level": p.level,
                           "opponent": None, "starts_in": None})
            else:
                m.attach(p, conn)
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            raw = msg.get("text")
            if raw is None:
                raw = msg.get("bytes")
                if raw is not None and len(raw) <= MAX_MESSAGE_BYTES:
                    with _lock:
                        _error(p, "bad_message")
                    continue
            if raw is None or len(raw if isinstance(raw, bytes) else raw.encode("utf-8")) > MAX_MESSAGE_BYTES:
                conn.close(1009)
                cut = True
                break
            handle_message(p, conn, raw)
    except Exception as e:  # noqa: BLE001 - WebSocketDisconnect and friends: the client is gone
        if type(e).__name__ not in ("WebSocketDisconnect", "RuntimeError", "ConnectionClosedError"):
            log.exception("pvp socket failed")
    finally:
        with _lock:
            if p.match is not None:
                p.match.detach(p, conn)
            elif p.conn is conn:
                p.conn, p.connected, p.last_seen = None, False, now()
        if cut:                                                 # let the pump deliver the close frame
            await asyncio.wait({pump}, timeout=1.0)
        pump.cancel()


def shutdown() -> None:
    """The server is stopping: end every live match without a rating change."""
    with _lock:
        for m in list(_matches.values()):
            if m.phase == "playing":
                m.finish(None, "server_restart")
            elif m.phase == "lobby":
                m.cancel("server_restart", "Máy chủ đang khởi động lại.")
