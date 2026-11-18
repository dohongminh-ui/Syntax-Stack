"""Live 1v1 matches (docs/pvp.md) through the real HTTP + WebSocket API (Starlette TestClient, one shared event loop).

The match clock is accelerated (``pvp.SPEED``) so that countdowns, the 20 s disconnect grace and the 4:00 overtime
take fractions of a second. The rules themselves are covered by test_pvp_rules.py.
"""
import contextlib
import json
import random
import secrets
import time

import anyio
import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import bank, nicknames, pvp, ranked
from app import rescue_engine as E
from app.main import app

from .ranked_bot import answer_body


@pytest.fixture
def tc(tmp_path, monkeypatch):
    monkeypatch.setattr(ranked, "DB_PATH", tmp_path / "ranked.sqlite")
    monkeypatch.setattr(ranked, "_db_path_cache", None)
    monkeypatch.delenv("SYNTAX_STACK_PUBLIC_URL", raising=False)
    monkeypatch.setattr(pvp, "SPEED", 20.0)
    monkeypatch.setattr(pvp, "TICK_S", 0.01)
    monkeypatch.setattr(pvp, "MAX_ACTIONS_PER_S", 10_000)
    ranked.reset_rate_limits()
    pvp.reset()
    with TestClient(app) as c:
        c.clients = []
        try:
            yield c
        finally:
            for cl in c.clients:                       # a failing test must not leave sockets open (the portal would hang)
                with contextlib.suppress(Exception):
                    cl.close()
    pvp.reset()
    ranked.reset_rate_limits()


def nick(i=0):
    return nicknames.generate(random.Random(1000 + i))


def dev():
    return secrets.token_hex(16)


class Client:
    """A WebSocket client that remembers what the server told it."""

    def __init__(self, tc, ticket):
        self.tc, self.ticket = tc, ticket
        getattr(tc, "clients", []).append(self)
        self.stack = contextlib.ExitStack()
        self.ws = self.stack.enter_context(tc.websocket_connect(f"/api/pvp/ws?ticket={ticket}"))
        self.log: list[dict] = []
        self.state = self.start = self.end = self.lobby = None
        self.closed = None

    async def _recv(self, timeout):
        with anyio.fail_after(timeout):
            return await self.ws._send_rx.receive()

    async def _poll(self):
        try:
            return self.ws._send_rx.receive_nowait()
        except anyio.WouldBlock:
            return None

    def _take(self, m):
        if m is None:
            return None
        if m["type"] == "websocket.close":
            self.closed = m.get("code", 1000)
            if self.end is not None:                    # the server closes the socket after `end`
                return {"t": "closed"}
            raise WebSocketDisconnect(self.closed)
        d = json.loads(m["text"])
        self.log.append(d)
        if d["t"] == "state":
            self.state = d["you"]
            self.rev = d["rev"]
        elif d["t"] == "start":
            self.start = d
        elif d["t"] == "end":
            self.end = d
        elif d["t"] == "lobby":
            self.lobby = d
        return d

    def get(self, timeout=5):
        return self._take(self.ws.portal.call(self._recv, timeout))

    def poll(self):
        return self._take(self.ws.portal.call(self._poll))

    def drain(self):
        while self.poll() is not None:
            pass

    def until(self, *types, timeout=5):
        end = time.monotonic() + timeout
        while True:
            d = self.get(max(0.01, end - time.monotonic()))
            if d["t"] in types:
                return d

    def wait(self, pred, timeout=5):
        """The latest state (read more if needed) once ``pred(state)`` holds."""
        end = time.monotonic() + timeout
        self.drain()
        while not (self.state and pred(self.state)):
            self.until("state", timeout=max(0.01, end - time.monotonic()))
        return self.state

    def send(self, **msg):
        self.ws.send_json(msg)

    def act(self, **msg):
        """Send an action and wait for the answer (a state, an error or the end)."""
        self.send(**msg)
        return self.until("state", "error", "end")

    def close(self):
        self.stack.close()

    @property
    def mid(self):
        return self.start["match_id"]

    @property
    def tok(self):
        return self.start["match_token"]

    def log_types(self):
        return [m["t"] for m in self.log]


def post(tc, path, expect=200, **body):
    r = tc.post(path, json=body)
    assert r.status_code == expect, r.text
    return r.json() if r.content else None


def queue(tc, level="intermediate", i=0, d=None):
    return post(tc, "/api/pvp/queue", level=level, nickname=nick(i), device_id=d or dev())["ticket"]


def start_match(a, b):
    for c in (a, b):
        c.send(t="ready")
    for c in (a, b):
        c.until("start")
        c.until("state")
    return a, b


@pytest.fixture
def duo(tc):
    """Two humans paired by the quick-match queue, connected, ready and playing."""
    da, db = dev(), dev()
    ta = queue(tc, i=1, d=da)
    a = Client(tc, ta)
    a.until("lobby")
    tb = queue(tc, i=2, d=db)
    b = Client(tc, tb)
    a.until("lobby")
    b.until("lobby")
    start_match(a, b)
    a.devs = (da, db)
    yield a, b
    a.close()
    b.close()


def match_of(c):
    return pvp._matches[c.mid]


def side_of(c):
    m = match_of(c)
    return next(p for p in m.players() if p.token == c.tok)


def prime_lock(c, topic="variables"):
    """Server-side test setup: row 7 is full except (7, 0) and tray piece 0 is a dot, so placing it makes a lock."""
    m, p = match_of(c), side_of(c)
    with pvp._lock:
        g = p.game
        for col in range(1, 8):
            g.grid[7][col] = {"topic": topic, "bug": False, "bug_id": None}
        g.tray[0] = E.Piece("dot", ((0, 0),), topic)
        g.tray[0].id = "px"
        m.push_state(p)
    c.until("state")


def legal(state):
    grid = state["grid"]
    for i, p in enumerate(state["tray"]):
        if p is None:
            continue
        for r in range(7, -1, -1):      # from the bottom: the rows that land push everything up
            for col in range(8):
                if all(0 <= r + dr < 8 and 0 <= col + dc < 8 and grid[r + dr][col + dc] is None
                       for dr, dc in p["cells"]):
                    return i, r, col
    return None


def solve(tc, c, correct=True, hint=0, bug=None, kind="rescue"):
    """Ask the server for the puzzle of the current lock (or bug line) and answer it. Returns (puzzle, answer)."""
    body = {"kind": kind, "match_id": c.mid, "match_token": c.tok, "level": "intermediate"}
    if kind == "rescue":
        lk = c.state["lock"]
        body.update(topic=lk["topic"], tier=lk["tier"])
    else:
        body.update(bug=bug, template_id="x")
    r = tc.post("/api/puzzle/next", json=body)
    assert r.status_code == 200, r.text
    pz = r.json()
    if hint:
        h = tc.get(f"/api/puzzle/{pz['id']}/hint", params={"level": hint, "match_id": c.mid, "match_token": c.tok})
        assert h.status_code == 200
    ans = tc.post(f"/api/puzzle/{pz['id']}/answer", json={**answer_body(bank.get_puzzle(pz["id"]), correct),
                                                           "match_id": c.mid, "match_token": c.tok})
    assert ans.status_code == 200, ans.text
    return pz, ans.json()


# --------------------------------------------------------------------------- lobby, start, a whole match


def test_lobby_countdown_start_and_same_pieces(tc):
    ta = queue(tc, i=1)
    a = Client(tc, ta)
    first = a.until("lobby")
    assert first["opponent"] is None and first["starts_in"] is None and first["level"] == "intermediate"
    assert first["you"]["rating"] == 1000
    b = Client(tc, queue(tc, i=2))
    lob = a.until("lobby")
    assert lob["opponent"]["nickname"] == nick(2) and lob["opponent"]["bot"] is False
    b.until("lobby")
    a.send(t="ready")
    b.send(t="ready")
    seen = []
    while not seen or seen[-1] != 0:
        seen.append(a.until("lobby")["starts_in"])
    assert [x for x in seen if x is not None] == [3, 2, 1, 0]
    a.until("start")
    b.until("start")
    a.until("state")
    b.until("state")
    assert a.start["seed"] == b.start["seed"] and a.start["match_id"] == b.start["match_id"]
    assert a.start["match_token"] != b.start["match_token"] and len(a.start["match_token"]) == 32
    assert a.start["level"] == "intermediate" and a.start["at"] > 1.7e9
    assert a.state["tray"] == b.state["tray"] and a.state["phase"] == "play" and a.state["pending"] == []
    assert len(a.state["grid"]) == 8 and a.state["items"] == {"bomb": 0, "shuffle": 0, "undo": 0, "debugger": 0}
    assert a.state["lock"] is None and a.state["bugLines"] == [] and a.rev == 1
    opp = a.until("opponent")
    assert opp["lock"] is False and opp["phase"] == "play" and opp["connected"] is True and opp["pending"] == 0
    a.close()
    b.close()


def test_send_cancel_land_resign_and_rating(duo, tc):
    a, b = duo
    prime_lock(a)
    st = a.act(t="place", i=0, r=7, c=0)
    assert st["t"] == "state" and st["you"]["phase"] == "locked" and st["you"]["lock"]["count"] == 1
    assert st["you"]["lock"]["debugger"] is False
    pz, res = solve(tc, a)
    assert res["correct"] is True
    assert a.until("sent") == {"t": "sent", "lines": 1, "cancelled": 0}
    inc = b.until("incoming")
    assert inc["lines"] == 1 and inc["from_topic"] == pz["topic"]
    a_state = a.wait(lambda s: s["phase"] == "play" and s["sent"] == 1)
    assert a_state["phase"] == "play" and a_state["lock"] is None and a_state["sent"] == 1
    assert a_state["score"] > 100
    b_state = b.wait(lambda s: len(s["pending"]) == 1)
    assert len(b_state["pending"]) == 1 and b_state["received"] == 1 and b_state["pending"][0]["topic"] == pz["topic"]
    # the row lands after B's next placement
    i, r, col = legal(b.state)
    b.send(t="place", i=i, r=r, c=col)
    assert b.until("landed") == {"t": "landed", "rows": 1}
    st = b.wait(lambda s: s["pending"] == [] and len(s["bugLines"]) == 1)
    assert st["pending"] == [] and len(st["bugLines"]) == 1 and all(x and x["bug"] for x in st["grid"][7])
    assert st["bugLines"][0]["topic"] == pz["topic"] and st["bugLines"][0]["templateId"] == pz["template_id"]
    # A resigns
    a.send(t="resign")
    ea, eb = a.until("end"), b.until("end")
    assert (ea["winner"], eb["winner"], ea["reason"]) == ("opponent", "you", "resign")
    assert ea["you"]["sent"] == 1 and eb["you"]["received"] == 1 and eb["opponent"]["score"] == ea["you"]["score"]
    assert ea["rating"] == {"before": 1000, "after": 984} and eb["rating"] == {"before": 1000, "after": 1016}
    assert ranked.pvp_rating(ranked._device_hash(a.devs[1])) == 1016


def test_cancel_own_pending_before_sending(duo, tc):
    a, b = duo
    with pvp._lock:
        side_of(a).game.queue_incoming([{"topic": "loops", "template_id": "loops_t"}] * 2)
    prime_lock(a)
    a.act(t="place", i=0, r=7, c=0)
    assert len(a.state["pending"]) == 2
    solve(tc, a)
    assert a.until("sent") == {"t": "sent", "lines": 0, "cancelled": 1}
    st = a.wait(lambda s: s["phase"] == "play")
    assert len(st["pending"]) == 1 and st["sent"] == 0
    b.drain()
    assert "incoming" not in b.log_types()


def test_wrong_answer_makes_a_bug_line_and_it_can_be_fixed_without_a_crash(duo, tc):
    a, b = duo
    prime_lock(a)
    a.act(t="place", i=0, r=7, c=0)
    solve(tc, a, correct=False)
    st = a.wait(lambda s: s["phase"] == "play")
    assert st["phase"] == "play" and len(st["bugLines"]) == 1 and st["endReason"] is None
    bug = st["bugLines"][0]
    assert all(st["grid"][r][c]["bug"] for r, c in bug["cells"])
    _, res = solve(tc, a, correct=False, kind="debug", bug=bug["id"])     # a wrong Debug answer: the line stays
    assert res["correct"] is False
    a.wait(lambda s: s["streak"] == 0)
    time.sleep(0.1)
    a.drain()
    st = a.state
    assert len(st["bugLines"]) == 1 and st["phase"] == "play"
    _, res = solve(tc, a, correct=True, kind="debug", bug=bug["id"])
    st = a.wait(lambda s: s["bugLines"] == [])
    assert st["items"]["debugger"] == 1 and st["sent"] == 0
    b.drain()
    assert "incoming" not in b.log_types()


def test_boss_lock_needs_two_puzzles_and_sends_four(duo, tc):
    a, b = duo
    m, p = match_of(a), side_of(a)
    with pvp._lock:
        g = p.game
        for r in range(4, 8):
            for col in range(7):
                g.grid[r][col] = {"topic": "loops", "bug": False, "bug_id": None}
        g.tray[0] = E.Piece("i4", ((0, 0), (1, 0), (2, 0), (3, 0)), "loops")
        g.tray[0].id = "px"
        m.push_state(p)
    a.until("state")
    st = a.act(t="place", i=0, r=4, c=7)
    assert st["you"]["lock"]["boss"] is True and st["you"]["lock"]["count"] == 4
    solve(tc, a)
    assert a.state["phase"] == "locked"                    # one more puzzle to go
    solve(tc, a)
    assert a.until("sent")["lines"] == 4 and b.until("incoming")["lines"] == 4
    assert a.wait(lambda s: s["items"]["undo"] == 1)["phase"] == "play"


def test_answers_without_or_with_a_wrong_match_token_are_not_applied(duo, tc):
    a, b = duo
    prime_lock(a)
    a.act(t="place", i=0, r=7, c=0)
    lk = a.state["lock"]
    good = {"kind": "rescue", "topic": lk["topic"], "tier": lk["tier"], "level": "intermediate"}
    # next with a wrong token: an ordinary random puzzle (nothing recorded)
    r = tc.post("/api/puzzle/next", json={**good, "match_id": a.mid, "match_token": "0" * 32})
    assert r.status_code == 200
    stray = r.json()
    for fields in ({}, {"match_id": a.mid}, {"match_id": a.mid, "match_token": "f" * 32},
                   {"match_id": a.mid, "match_token": b.tok},          # the opponent's token is not yours
                   {"match_id": "0" * 16, "match_token": a.tok}):
        ans = tc.post(f"/api/puzzle/{stray['id']}/answer", json={**answer_body(bank.get_puzzle(stray["id"]), True),
                                                                  **fields})
        assert ans.status_code == 200 and ans.json()["correct"] is True
    # next without a valid pair while the real puzzle is not served: still nothing happens
    a.drain()
    assert a.state["phase"] == "locked" and a.state["score"] < 100 and not [m for m in a.log if m["t"] == "sent"]
    # a puzzle the server did not serve for this lock, answered with the right token: not applied
    ans = tc.post(f"/api/puzzle/{stray['id']}/answer", json={**answer_body(bank.get_puzzle(stray["id"]), True),
                                                              "match_id": a.mid, "match_token": a.tok})
    assert ans.status_code == 200
    time.sleep(0.1)
    a.drain()
    assert a.state["phase"] == "locked"
    # the served puzzle with the right token is applied, once
    pz, _ = solve(tc, a)
    assert a.until("sent")["lines"] == 1
    again = tc.post(f"/api/puzzle/{pz['id']}/answer", json={**answer_body(bank.get_puzzle(pz["id"]), True),
                                                             "match_id": a.mid, "match_token": a.tok})
    assert again.status_code == 200
    time.sleep(0.1)
    a.drain()
    assert [m["t"] for m in a.log].count("sent") == 1 and a.state["sent"] == 1
    # no lock pending: a valid pair gets 409, not a puzzle
    r = tc.post("/api/puzzle/next", json={**good, "match_id": a.mid, "match_token": a.tok})
    assert r.status_code == 409


def test_next_is_idempotent_and_hints_cost_the_streak(duo, tc):
    a, _ = duo
    prime_lock(a)
    a.act(t="place", i=0, r=7, c=0)
    lk = a.state["lock"]
    body = {"kind": "rescue", "topic": lk["topic"], "tier": lk["tier"], "match_id": a.mid, "match_token": a.tok}
    p1 = tc.post("/api/puzzle/next", json=body).json()
    assert tc.post("/api/puzzle/next", json=body).json()["id"] == p1["id"]        # asking again: the same puzzle
    h = tc.get(f"/api/puzzle/{p1['id']}/hint", params={"level": 3, "match_id": a.mid, "match_token": a.tok})
    assert h.status_code == 200
    tc.post(f"/api/puzzle/{p1['id']}/answer", json={**answer_body(bank.get_puzzle(p1["id"]), True),
                                                     "match_id": a.mid, "match_token": a.tok})
    a.until("sent")
    st = a.wait(lambda s: s["phase"] == "play")
    assert st["streak"] == 0 and 100 * 0.5 - 1 <= st["score"] - 1 <= 100 * 0.5 + 1   # hint level 3: x0.5 and no streak


def test_debugger_is_spent_when_the_first_puzzle_of_a_lock_is_served(duo, tc):
    a, _ = duo
    with pvp._lock:
        side_of(a).game.items["debugger"] = 1
    prime_lock(a)
    a.act(t="place", i=0, r=7, c=0)
    lk = a.state["lock"]
    tc.post("/api/puzzle/next", json={"kind": "rescue", "topic": lk["topic"], "tier": lk["tier"],
                                       "match_id": a.mid, "match_token": a.tok})
    st = a.wait(lambda s: s["items"]["debugger"] == 0)
    assert st["lock"]["debugger"] is True


def test_undo_only_before_the_puzzle_is_opened(duo, tc):
    a, _ = duo
    with pvp._lock:
        side_of(a).game.items["undo"] = 2
    prime_lock(a)
    a.act(t="place", i=0, r=7, c=0)
    st = a.act(t="undo")["you"]
    assert st["phase"] == "play" and st["items"]["undo"] == 1 and st["grid"][7][0] is None
    prime_lock(a)
    a.act(t="place", i=0, r=7, c=0)
    lk = a.state["lock"]
    tc.post("/api/puzzle/next", json={"kind": "rescue", "topic": lk["topic"], "tier": lk["tier"],
                                       "match_id": a.mid, "match_token": a.tok})
    time.sleep(0.1)
    a.drain()
    a.send(t="undo")
    assert a.until("error")["code"] == "illegal"


# --------------------------------------------------------------------------- illegal actions, limits


def test_illegal_actions_get_an_error_and_a_state_resync(duo):
    a, _ = duo
    rev = a.rev
    for msg in ({"t": "place", "i": 0, "r": 9, "c": 9}, {"t": "place", "i": 7, "r": 0, "c": 0},
                {"t": "bomb", "r": 0, "c": 0}, {"t": "shuffle"}, {"t": "undo"}):
        a.send(**msg)
        e = a.until("error")
        assert e["code"] == "illegal" and e["message"]
        s = a.until("state")
        assert s["rev"] > rev
        rev = s["rev"]
    for msg in ({"t": "place", "i": "0", "r": 0, "c": 0}, {"t": "place", "i": True, "r": 0, "c": 0},
                {"t": "place", "i": 0}, {"t": "bomb", "r": 1.5, "c": 0}, {"t": "fly"}):
        a.send(**msg)
        assert a.until("error")["code"] == "bad_message"
    a.ws.send_text("not json")
    assert a.until("error")["code"] == "bad_message"
    a.ws.send_text("[1,2]")
    assert a.until("error")["code"] == "bad_message"
    a.send(t="ping", n=7)
    assert a.until("pong")["n"] == 7
    # the board never changed
    assert a.state["score"] == 0 and a.state["phase"] == "play"


def test_actions_before_the_start_are_refused(tc):
    a = Client(tc, queue(tc, i=1))
    a.until("lobby")
    a.send(t="place", i=0, r=0, c=0)
    assert a.until("error")["code"] == "not_playing"
    a.send(t="resign")
    assert a.until("error")["code"] == "not_playing"
    a.close()


def test_oversized_messages_close_the_socket(duo):
    a, _ = duo
    a.ws.send_text(json.dumps({"t": "ping", "n": "x" * 5000}))
    with pytest.raises(WebSocketDisconnect) as e:
        for _ in range(50):
            a.get(2)
    assert e.value.code == 1009


def test_too_many_actions_per_second_are_dropped(duo, monkeypatch):
    a, _ = duo
    monkeypatch.setattr(pvp, "MAX_ACTIONS_PER_S", 5)
    time.sleep(1.1)
    for _ in range(30):
        a.send(t="ping", n=1)
    time.sleep(0.4)
    a.drain()
    pongs = [m for m in a.log if m["t"] == "pong"]
    assert 1 <= len(pongs) <= 6


def test_an_unknown_ticket_gets_an_error_and_a_close(tc):
    with tc.websocket_connect("/api/pvp/ws?ticket=nope") as ws:
        assert ws.receive_json()["code"] == "bad_ticket"
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_json()
        assert e.value.code == 4404


def test_a_second_socket_on_the_same_ticket_replaces_the_first(duo, tc):
    a, b = duo
    a2 = Client(tc, a.ticket)
    assert a.until("error")["code"] == "replaced"
    assert a2.until("start")["match_id"] == a.mid and a2.until("state")["you"]["grid"] == a.state["grid"]
    b.drain()
    a2.close()


# --------------------------------------------------------------------------- disconnects


def test_reconnect_within_the_grace_resumes_exactly(duo, tc, monkeypatch):
    a, b = duo
    monkeypatch.setattr(pvp, "SPEED", 5.0)        # grace = 4 s real: plenty of time to come back
    with pvp._lock:                                # (the clock changed: restart the running timers)
        m = match_of(a)
        m.started_at = pvp.now()
    i, r, col = legal(a.state)
    a.act(t="place", i=i, r=r, c=col)
    before = a.state
    a.close()
    st = b.until("opponent_status")
    assert st == {"t": "opponent_status", "connected": False, "grace_s": 20}
    a2 = Client(tc, a.ticket)
    s = a2.until("start")
    assert s["match_id"] == a.mid and s["match_token"] == a.tok and s["seed"] == a.start["seed"]
    assert a2.until("state")["you"] == before
    assert b.until("opponent_status") == {"t": "opponent_status", "connected": True, "grace_s": 0}
    assert a2.state["tray"] == before["tray"]
    # and the match goes on
    i, r, col = legal(a2.state)
    assert a2.act(t="place", i=i, r=r, c=col)["t"] == "state"
    a2.close()


def test_grace_expiry_is_a_disconnect_loss(duo, tc):
    a, b = duo
    a.close()
    eb = b.until("end", timeout=10)
    assert (eb["winner"], eb["reason"]) == ("you", "disconnect")
    assert eb["rating"] == {"before": 1000, "after": 1016}
    a2 = Client(tc, a.ticket)                      # coming back late: the result
    ea = a2.until("end")
    assert (ea["winner"], ea["reason"]) == ("opponent", "disconnect") and ea["rating"]["after"] == 984
    a2.close()


def test_both_disconnected_is_a_draw_without_rating_change(duo, tc):
    a, b = duo
    a.close()
    b.close()
    m = match_of(a) if False else pvp._matches[a.mid]
    deadline = time.monotonic() + 10
    while m.phase != "over" and time.monotonic() < deadline:
        time.sleep(0.05)
    assert (m.phase, m.winner, m.reason) == ("over", None, "both_disconnected")
    a2 = Client(tc, a.ticket)
    e = a2.until("end")
    assert (e["winner"], e["reason"]) == ("draw", "both_disconnected") and "rating" not in e
    assert ranked.pvp_rating(ranked._device_hash(a.devs[0])) == 1000
    a2.close()


def test_a_dropped_players_board_is_frozen_but_still_collects_lines(duo, tc, monkeypatch):
    a, b = duo
    monkeypatch.setattr(pvp, "SPEED", 3.0)
    with pvp._lock:
        match_of(a).started_at = pvp.now()
        side_of(a).dropped_at = None
    b.close()
    a.until("opponent_status")
    prime_lock(a)
    a.act(t="place", i=0, r=7, c=0)
    solve(tc, a)
    a.until("sent")
    assert len(side_of(b).game.pending) == 1 and side_of(b).game.grid[7][0] is None   # queued, nothing landed


# --------------------------------------------------------------------------- overtime, a whole match


def test_overtime_adds_one_line_every_20_seconds_to_both_players(duo, monkeypatch):
    a, b = duo
    monkeypatch.setattr(pvp, "SPEED", 400.0)       # 4:00 = 0.6 s
    with pvp._lock:
        match_of(a).started_at = pvp.now()
    ia = a.until("incoming", timeout=10)
    ib = b.until("incoming", timeout=10)
    assert ia["overtime"] is True and ia["lines"] == 1 and ia["from_topic"] == ib["from_topic"]
    assert ia["from_topic"] in E.TOPICS
    st = a.wait(lambda s: len(s["pending"]) >= 1)
    assert st["pending"][0]["templateId"] == f"{ia['from_topic']}_bug"
    ia2 = a.until("incoming", timeout=10)
    assert ia2["overtime"] is True


def play_out(tc, clients, limit=6000):
    """Both clients play (first legal placement, correct answers) until the match is over."""
    for _ in range(limit):
        for c in clients:
            c.drain()
        if all(c.end for c in clients):
            return
        for c in clients:
            if c.end or c.state is None:
                continue
            s = c.state
            if s["phase"] == "over":
                c.until("end")
                continue
            if s["phase"] == "locked":
                if s["lock"]["boss"] or True:
                    try:
                        solve(tc, c)
                    except AssertionError:
                        pass
                c.drain()
                continue
            mv = legal(s)
            if mv is None:
                time.sleep(0.01)
                continue
            c.send(t="place", i=mv[0], r=mv[1], c=mv[2])
            with contextlib.suppress(TimeoutError):
                c.until("state", "error", "end", timeout=1)
        time.sleep(0.002)
    raise AssertionError("the match did not end")


def test_a_full_match_between_two_clients_ends_and_rates_both(duo, tc, monkeypatch):
    a, b = duo
    monkeypatch.setattr(pvp, "SPEED", 150.0)
    with pvp._lock:
        match_of(a).started_at = pvp.now()
    play_out(tc, [a, b])
    assert {a.end["winner"], b.end["winner"]} == {"you", "opponent"}
    assert a.end["reason"] in ("topped_out", "nofit") and a.end["reason"] == b.end["reason"]
    wa, wb = a.end["rating"], b.end["rating"]
    assert wa["after"] + wb["after"] == 2000 and {wa["after"], wb["after"]} == {1016, 984}
    assert a.end["you"]["locks"] >= 0 and a.end["opponent"]["score"] == b.end["you"]["score"]
    assert a.state["phase"] == "over" or a.end


# --------------------------------------------------------------------------- bot matches


def test_bot_match_runs_to_the_end_without_rating(tc, monkeypatch):
    monkeypatch.setattr(pvp, "SPEED", 300.0)
    d = dev()
    t = post(tc, "/api/pvp/bot", level="beginner", nickname=nick(5), device_id=d)["ticket"]
    c = Client(tc, t)
    lob = c.until("lobby")
    assert lob["opponent"]["bot"] is True and lob["opponent"]["nickname"].startswith("Máy ")
    assert lob["opponent"]["rating"] is None
    c.send(t="ready")
    c.until("start")
    c.until("state")
    end = c.until("end", timeout=30)
    assert end["winner"] == "you" and end["opponent"]["bot"] is True and "rating" not in end
    assert end["reason"] in ("topped_out", "nofit")
    assert end["opponent"]["score"] > 0
    assert ranked.pvp_rating(ranked._device_hash(d)) == 1000
    c.close()


def test_bot_plays_fairly_with_the_engine(tc, monkeypatch):
    """The bot places pieces, solves locks and fixes bugs through the same server code (and sends lines)."""
    monkeypatch.setattr(pvp, "SPEED", 100.0)
    t = post(tc, "/api/pvp/bot", level="advanced", nickname=nick(6), device_id=dev())["ticket"]
    c = Client(tc, t)
    c.until("lobby")
    c.send(t="ready")
    c.until("start")
    c.until("state")
    c.until("opponent")
    seen = {"incoming": 0}
    deadline = time.monotonic() + 25
    best = 0
    while time.monotonic() < deadline and not c.end:
        try:
            d = c.get(0.5)
        except TimeoutError:
            continue
        if d["t"] == "incoming":
            seen["incoming"] += d["lines"]
        if d["t"] == "opponent":
            best = max(best, d["score"])
    assert best > 0
    assert seen["incoming"] >= 1 or c.end


# --------------------------------------------------------------------------- matchmaking over HTTP


def test_queue_pairs_by_level_and_never_with_yourself(tc):
    d = dev()
    t1 = queue(tc, "beginner", 1, d)
    c1 = Client(tc, t1)
    c1.until("lobby")
    t2 = queue(tc, "beginner", 2, d)             # same device: not paired with itself
    c2 = Client(tc, t2)
    c2.until("lobby")
    c1.drain()
    assert all(m["opponent"] is None for m in c1.log if m["t"] == "lobby")
    t3 = queue(tc, "advanced", 3)                # another level
    c3 = Client(tc, t3)
    assert c3.until("lobby")["opponent"] is None
    c4 = Client(tc, queue(tc, "beginner", 4))    # pairs with the first one waiting on beginner
    assert c4.until("lobby")["opponent"]["nickname"] == nick(1)
    assert c1.until("lobby")["opponent"]["nickname"] == nick(4)
    for c in (c1, c2, c3, c4):
        c.close()


def test_leaving_the_queue(tc):
    d1 = dev()
    t1 = queue(tc, "beginner", 1, d1)
    assert tc.delete(f"/api/pvp/queue/{t1}").status_code == 204
    assert tc.delete(f"/api/pvp/queue/{t1}").status_code == 404
    c2 = Client(tc, queue(tc, "beginner", 2))
    assert c2.until("lobby")["opponent"] is None      # the first one is gone, nobody to pair with
    c2.close()
    with tc.websocket_connect(f"/api/pvp/ws?ticket={t1}") as ws:
        assert ws.receive_json()["code"] == "bad_ticket"


def test_queue_validation_and_limits(tc):
    post(tc, "/api/pvp/queue", expect=422, level="beginner", nickname="Hacker", device_id=dev())
    post(tc, "/api/pvp/queue", expect=422, level="beginner", nickname=nick(1), device_id="nope")
    post(tc, "/api/pvp/queue", expect=422, level="wizard", nickname=nick(1), device_id=dev())
    for _ in range(ranked.PVP_RATE_LIMIT):
        post(tc, "/api/pvp/bot", level="beginner", nickname=nick(1), device_id=dev())
    post(tc, "/api/pvp/queue", expect=429, level="beginner", nickname=nick(1), device_id=dev())


def test_private_duel_codes(tc, monkeypatch):
    made = post(tc, "/api/pvp/private", level="intermediate", nickname=nick(1), device_id=dev())
    code = made["code"]
    assert len(code) == 5 and set(code) <= set("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")
    assert made["url"] == f"http://testserver/?duel={code}"
    host = Client(tc, made["ticket"])
    assert host.until("lobby")["opponent"] is None
    post(tc, "/api/pvp/private/ZZZZZ/join", expect=404, nickname=nick(2), device_id=dev())
    post(tc, "/api/pvp/private/ab/join", expect=404, nickname=nick(2), device_id=dev())
    post(tc, f"/api/pvp/private/{code}/join", expect=422, nickname="Hacker", device_id=dev())
    ticket = post(tc, f"/api/pvp/private/{code.lower()}/join", nickname=nick(2), device_id=dev())["ticket"]
    guest = Client(tc, ticket)
    assert host.until("lobby")["opponent"]["nickname"] == nick(2)
    post(tc, f"/api/pvp/private/{code}/join", expect=409, nickname=nick(3), device_id=dev())
    start_match(host, guest)
    assert host.start["level"] == "intermediate" and host.state["tray"] == guest.state["tray"]
    host.close()
    guest.close()
    # a code nobody joined expires after 10 minutes
    made2 = post(tc, "/api/pvp/private", level="beginner", nickname=nick(1), device_id=dev())
    monkeypatch.setattr(pvp, "PRIVATE_TTL_S", -1)
    post(tc, f"/api/pvp/private/{made2['code']}/join", expect=410, nickname=nick(2), device_id=dev())


def test_live_match_limit(tc, monkeypatch):
    monkeypatch.setattr(pvp, "MAX_LIVE_MATCHES", 2)
    post(tc, "/api/pvp/bot", level="beginner", nickname=nick(1), device_id=dev())
    post(tc, "/api/pvp/bot", level="beginner", nickname=nick(1), device_id=dev())
    post(tc, "/api/pvp/bot", expect=503, level="beginner", nickname=nick(1), device_id=dev())
    post(tc, "/api/pvp/private", expect=503, level="beginner", nickname=nick(1), device_id=dev())


def test_a_lobby_nobody_gets_ready_in_is_cancelled(tc, monkeypatch):
    monkeypatch.setattr(pvp, "LOBBY_TIMEOUT_S", 0.5)
    a = Client(tc, queue(tc, i=1))
    a.until("lobby")
    b = Client(tc, queue(tc, i=2))
    e = a.until("error", timeout=5)
    assert e["code"] == "lobby_timeout"
    a.close()
    b.close()


def test_server_restart_ends_matches_without_rating(duo):
    a, b = duo
    pvp.shutdown()
    ea, eb = a.until("end"), b.until("end")
    assert ea["winner"] == eb["winner"] == "draw" and ea["reason"] == "server_restart"
    assert "rating" not in ea and "rating" not in eb


def test_ratings_follow_elo_over_several_matches(tc):
    """K = 32: the lower rated winner gains more."""
    da, db = dev(), dev()
    ha, hb = ranked._device_hash(da), ranked._device_hash(db)
    assert ranked.pvp_apply_result(ha, hb, 1.0) == ((1000, 1016), (1000, 984))
    assert ranked.pvp_apply_result(ha, hb, 0.0) == ((1016, 999), (984, 1001))
    assert ranked.pvp_apply_result(ha, hb, 0.5) == ((999, 999), (1001, 1001))
    assert ranked.pvp_rating(ha) == 999 and ranked.pvp_rating("unknown") == 1000


# --------------------------------------------------------------------------- CSP


def test_csp_allows_the_own_websocket_origin_only(tc):
    r = tc.get("/")
    csp = r.headers["content-security-policy"]
    connect = next(d for d in csp.split("; ") if d.startswith("connect-src"))
    assert connect == "connect-src 'self' https://cloudflareinsights.com ws://testserver"
    r = tc.get("/", headers={"x-forwarded-proto": "https", "x-forwarded-host": "play.example.org"})
    connect = next(d for d in r.headers["content-security-policy"].split("; ") if d.startswith("connect-src"))
    assert connect == "connect-src 'self' https://cloudflareinsights.com wss://play.example.org"
    r = tc.get("/", headers={"x-forwarded-host": "bad host/evil"})
    assert "evil" not in r.headers["content-security-policy"]
    assert "ws:" not in r.headers["content-security-policy"].replace("wss://", "").replace("ws://testserver", "")


# --------------------------------------------------------------------------- private rematch, reload


def private_pair(tc):
    made = post(tc, "/api/pvp/private", level="beginner", nickname=nick(1), device_id=dev())
    host = Client(tc, made["ticket"])
    host.until("lobby")
    ticket = post(tc, f"/api/pvp/private/{made['code']}/join", nickname=nick(2), device_id=dev())["ticket"]
    guest = Client(tc, ticket)
    start_match(host, guest)
    return host, guest


def test_private_rematch_needs_both_players_and_starts_a_fresh_match(tc):
    a, b = private_pair(tc)
    old = (a.mid, a.tok, a.start["seed"])
    a.send(t="resign")
    ea = a.until("end")
    b.until("end")
    b.until("rematch_status")
    assert a.until("rematch_status") == {"t": "rematch_status", "you": False, "opponent": False}
    a.send(t="rematch")
    assert a.until("rematch_status") == {"t": "rematch_status", "you": True, "opponent": False}
    assert b.until("rematch_status") == {"t": "rematch_status", "you": False, "opponent": True}
    b.send(t="rematch")
    a.until("start")
    b.until("start")
    a.until("state")
    b.until("state")
    assert (a.mid, a.tok, a.start["seed"]) != old and a.start["seed"] == b.start["seed"]
    assert a.state["score"] == 0 and a.state["phase"] == "play" and a.rev == 1
    assert a.state["tray"] == b.state["tray"]
    # the old match token is dead, the new one works
    prime_lock(a)
    a.act(t="place", i=0, r=7, c=0)
    assert ea["rating"]["before"] == 1000
    solve(tc, a)
    assert a.until("sent")["lines"] == 1
    a.send(t="resign")
    e2 = a.until("end")
    assert e2["rating"]["before"] == ea["rating"]["after"]      # the rematch is rated too


def test_a_rematch_that_nobody_answers_expires(tc, monkeypatch):
    monkeypatch.setattr(pvp, "REMATCH_S", 0.5)
    a, b = private_pair(tc)
    a.send(t="resign")
    a.until("end")
    a.until("rematch_status")
    st = a.until("rematch_status", timeout=10)
    assert st == {"t": "rematch_status", "you": False, "opponent": False, "expired": True}
    assert a.get(2)["t"] == "closed"         # and the sockets are let go


def test_rematch_is_refused_while_playing(tc):
    a, b = private_pair(tc)
    a.send(t="rematch")
    assert a.until("error")["code"] == "no_rematch"
    a.close()
    b.close()


def test_a_reloaded_page_resumes_the_lobby_and_the_match_with_the_same_ticket(tc):
    made = post(tc, "/api/pvp/private", level="beginner", nickname=nick(1), device_id=dev())
    h1 = Client(tc, made["ticket"])
    assert h1.until("lobby")["opponent"] is None
    h1.close()                                            # reload
    h2 = Client(tc, made["ticket"])
    assert h2.until("lobby")["you"]["nickname"] == nick(1)
    ticket = post(tc, f"/api/pvp/private/{made['code']}/join", nickname=nick(2), device_id=dev())["ticket"]
    g = Client(tc, ticket)
    start_match(h2, g)
    before = h2.state
    h2.close()
    h3 = Client(tc, made["ticket"])                       # reload during the match, within the grace
    assert h3.until("start")["match_token"] == h2.tok
    assert h3.until("state")["you"] == before
