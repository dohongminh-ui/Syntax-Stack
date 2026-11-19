"""The two server-side match timers (docs/pvp.md rule 4 "timed landing" and rule 14 "lock limit").

Most tests drive a ``pvp.Match`` directly on a virtual clock (``pvp.now`` is replaced, as ``misaki_sim`` does), with two
human players behind a recording connection: no sleeping, exact to the tick. The last tests go through the real HTTP +
WebSocket API (accelerated clock) for the message shapes and for a late answer.
"""
import time

import pytest

from app import bank, pvp
from app import rescue_engine as E

from .ranked_bot import answer_body
from .test_pvp_match import Client, dev, legal, match_of, nick, post, queue, side_of, solve, start_match, tc  # noqa: F401

TICK = 0.1
REAL = {n: getattr(pvp, n) for n in ("LAND_DELAY_S", "LAND_DELAY_OVERTIME_S", "LOCK_LIMIT_S", "LOCK_LIMIT_BOSS_S")}


class Rec:
    """A connection that records what the server sends."""

    def __init__(self):
        self.msgs: list[dict] = []

    def send(self, msg):
        self.msgs.append(msg)

    def close(self, code=1000):
        pass

    def types(self):
        return [m["t"] for m in self.msgs]

    def last_state(self):
        return next(m for m in reversed(self.msgs) if m["t"] == "state")["you"]


@pytest.fixture
def clock(monkeypatch):
    t = [1000.0]
    monkeypatch.setattr(pvp, "now", lambda: t[0])
    return t


def new_match(clock, level="intermediate"):
    m = pvp.Match(level, "bot")                 # kind "bot": no rating is touched when it ends
    m.seed = 7
    players = []
    for idx in (0, 1):
        p = pvp.Player(level, f"P{idx}", None, "queue")
        p.conn, p.connected, p.ready = Rec(), True, True
        m.seat(p, idx)
        players.append(p)
    m.start()
    return m, players[0], players[1]


def advance(m, clock, seconds):
    for _ in range(round(seconds / TICK)):
        clock[0] += TICK
        m.tick()


def rows_to(m, p, n, topic="loops"):
    """The opponent's lines arrive on ``p`` (what ``Match.deliver`` does)."""
    p.game.queue_incoming([{"topic": topic, "template_id": f"{topic}_bug"}] * n)
    m.push_state(p)


def prime(p, rows=(7,), topic="variables"):
    """Make the next placement complete the given rows (all but column 0 are filled; tray piece 0 fits the gap)."""
    g = p.game
    for r in rows:
        for c in range(1, 8):
            g.grid[r][c] = {"topic": topic, "bug": False, "bug_id": None}
    if len(rows) == 1:
        g.tray[0] = E.Piece("dot", ((0, 0),), topic)
    else:                                       # a vertical bar down column 0
        g.tray[0] = E.Piece("bar", tuple((i, 0) for i in range(len(rows))), topic)
    g.tray[0].id = "px"


def make_lock(m, p, rows=(7,)):
    prime(p, rows)
    assert m.do_place(p, 0, rows[0], 0)
    assert p.game.phase == "locked" and p.game.lock is not None
    return p.game.lock


def landed(p):
    return [x for x in p.conn.msgs if x["t"] == "landed"]


# --------------------------------------------------------------------------- (a) timed landing, losing by nofit


def test_rows_land_after_four_seconds_without_a_placement(clock):
    m, a, b = new_match(clock)
    rows_to(m, a, 1)
    advance(m, clock, 3.8)
    assert len(a.game.pending) == 1 and landed(a) == []
    advance(m, clock, 0.4)
    assert a.game.pending == [] and len(a.game.bug_lines) == 1
    assert all(x and x["bug"] for x in a.game.grid[7])
    assert landed(a) == [{"t": "landed", "rows": 1, "timed": True}]
    # the player is told before the state that shows the landing
    kinds = a.conn.types()
    assert kinds[kinds.index("landed") + 1] == "state"
    assert a.conn.last_state()["pending"] == [] and a.conn.last_state()["land_in"] is None
    assert m.phase == "playing" and a.game.phase == "play"
    assert landed(b) == []                                   # the opponent's board is not touched
    assert a.game.snapshot is None                           # no undo snapshot after a landing


def test_an_idle_player_loses_by_nofit(clock):
    m, a, b = new_match(clock)
    rows_to(m, a, 8)                                         # a full board of bug rows leaves no room for any piece
    advance(m, clock, 4.2)
    assert a.game.phase == "over" and a.game.end_reason == "nofit"
    assert m.phase == "over" and m.winner == 1 and m.reason == "nofit"
    assert landed(a) == []                                   # not sent when the landing ended the game (as for a placement)


def test_an_idle_player_who_keeps_receiving_single_rows_eventually_loses(clock):
    m, a, b = new_match(clock)
    for _ in range(40):
        rows_to(m, a, 1)
        advance(m, clock, 4.2)
        if m.phase == "over":
            break
    assert m.phase == "over" and m.reason == "nofit" and m.winner == 1


def test_no_timed_landing_for_a_finished_game_or_a_player_who_is_away(clock):
    m, a, b = new_match(clock)
    rows_to(m, a, 1)
    a.dropped_at = clock[0]                                  # the socket dropped: the board is frozen
    a.conn.msgs.clear()
    advance(m, clock, 6.0)
    assert len(a.game.pending) == 1 and landed(a) == []
    # back after 6 s: the clock stood still for this player, so it lands 4 s after the row arrived (in away time)
    m.attach(a, a.conn)
    assert a.land_at is not None and a.land_at > clock[0]
    advance(m, clock, 3.0)
    assert len(a.game.pending) == 1
    advance(m, clock, 1.2)
    assert a.game.pending == []


# --------------------------------------------------------------------------- (b) the timer never extends


def test_more_rows_do_not_extend_the_timer(clock):
    m, a, b = new_match(clock)
    rows_to(m, a, 1)
    advance(m, clock, 3.0)
    rows_to(m, a, 2)                                         # arrives while the timer runs
    assert a.conn.last_state()["land_in"] == pytest.approx(1.0, abs=0.11)
    advance(m, clock, 0.8)
    assert len(a.game.pending) == 3
    advance(m, clock, 0.4)
    assert a.game.pending == [] and landed(a) == [{"t": "landed", "rows": 3, "timed": True}]
    # and a new queue after the landing starts a fresh 4 s
    rows_to(m, a, 1)
    assert a.conn.last_state()["land_in"] == 4.0


def test_a_placement_lands_early_and_clears_the_timer(clock):
    m, a, b = new_match(clock)
    rows_to(m, a, 2)
    advance(m, clock, 1.0)
    i, r, c = legal({"grid": pvp.state_view(a)["grid"], "tray": pvp.state_view(a)["tray"]})
    assert m.do_place(a, i, r, c)
    assert a.game.pending == [] and a.land_at is None
    assert landed(a) == [{"t": "landed", "rows": 2}]         # a placement landing keeps its old shape
    assert a.conn.last_state()["land_in"] is None
    advance(m, clock, 6.0)
    assert landed(a) == [{"t": "landed", "rows": 2}]         # nothing lands a second time


def test_fully_cancelled_rows_clear_the_timer(clock):
    m, a, b = new_match(clock)
    rows_to(m, a, 1)
    make_lock(m, a)
    assert a.land_at is not None
    row = m.serve(a, "rescue", None)
    m.answered(a, a.served[row["id"]], True)                 # clears the lock: sends 1, which cancels the one pending row
    assert a.game.pending == [] and a.land_at is None
    assert a.conn.last_state()["land_in"] is None
    advance(m, clock, 6.0)
    assert landed(a) == []


# --------------------------------------------------------------------------- (c) overtime


def test_two_seconds_in_overtime(clock):
    m, a, b = new_match(clock)
    advance(m, clock, pvp.OVERTIME_AT_S - 0.5)
    assert a.game.pending == []
    advance(m, clock, 0.7)                                   # 4:00: the overtime line is queued for both
    assert len(a.game.pending) == 1 and a.conn.last_state()["land_in"] == pytest.approx(2.0, abs=0.11)
    advance(m, clock, 1.6)
    assert len(a.game.pending) == 1 and len(b.game.pending) == 1
    advance(m, clock, 0.5)
    assert a.game.pending == [] and b.game.pending == []
    assert landed(a) == [{"t": "landed", "rows": 1, "timed": True}]


def test_rows_that_arrive_just_before_overtime_keep_the_four_second_timer(clock):
    m, a, b = new_match(clock)
    advance(m, clock, pvp.OVERTIME_AT_S - 1.0)
    rows_to(m, a, 1)
    assert a.conn.last_state()["land_in"] == 4.0
    advance(m, clock, 3.8)                                   # the overtime line joined the queue at 4:00: no new timer
    assert len(a.game.pending) == 2
    advance(m, clock, 0.4)
    assert a.game.pending == []


# --------------------------------------------------------------------------- (d) held while a lock is open


def test_the_landing_timer_is_held_while_a_lock_is_open(clock):
    m, a, b = new_match(clock)
    rows_to(m, a, 3)
    make_lock(m, a)
    advance(m, clock, 6.0)                                   # 4 s are over, 6 s into the lock (limit 40)
    assert a.game.phase == "locked" and len(a.game.pending) == 3 and landed(a) == []
    m.push_state(a)                                          # (the browser counts down between pushes)
    assert a.conn.last_state()["land_in"] < 0                # still reported, already expired
    row = m.serve(a, "rescue", None)
    m.answered(a, a.served[row["id"]], True)                 # 1 line sent: cancels 1 of the 3 pending rows
    assert a.game.phase == "play" and len(a.game.pending) == 2
    assert landed(a) == []                                   # not in the same step ...
    assert a.land_at is not None and a.land_at < clock[0]    # ... and the deadline was not reset
    advance(m, clock, TICK)
    assert a.game.pending == [] and landed(a) == [{"t": "landed", "rows": 2, "timed": True}]


def test_a_lock_that_resolves_before_the_deadline_lands_at_the_original_deadline(clock):
    m, a, b = new_match(clock)
    rows_to(m, a, 3)
    advance(m, clock, 1.0)
    make_lock(m, a)
    advance(m, clock, 1.0)
    row = m.serve(a, "rescue", None)
    m.answered(a, a.served[row["id"]], False)                # wrong: the lock becomes a bug line, the 3 rows stay
    assert a.game.phase == "play" and len(a.game.pending) == 3
    advance(m, clock, 1.8)
    assert len(a.game.pending) == 3
    advance(m, clock, 0.4)                                   # 4 s after the rows arrived, not after the lock
    assert a.game.pending == []


# --------------------------------------------------------------------------- (e) the lock limit


def test_an_unanswered_lock_becomes_a_bug_line_after_forty_seconds(clock):
    m, a, b = new_match(clock)
    a.game.streak = 2
    lk = make_lock(m, a)
    topic = lk["topic"]
    assert a.conn.last_state()["lock_in"] == 40.0
    advance(m, clock, 39.8)
    assert a.game.phase == "locked"
    a.conn.msgs.clear()
    advance(m, clock, 0.4)
    g = a.game
    assert g.phase == "play" and g.lock is None and a.lock_at is None
    assert len(g.bug_lines) == 1 and g.bug_lines[0]["topic"] == topic
    assert g.bug_lines[0]["template_id"] == f"{topic}_bug"
    assert g.streak == 0 and g.sent == 0 and g.mistakes == 0 and m.phase == "playing"
    kinds = a.conn.types()
    assert kinds[:2] == ["lock_timeout", "state"]
    assert a.conn.msgs[0] == {"t": "lock_timeout"}
    st = a.conn.last_state()
    assert st["lock"] is None and st["lock_in"] is None and st["phase"] == "play" and len(st["bugLines"]) == 1
    assert [x for x in b.conn.msgs if x["t"] == "incoming"] == []   # a wrong answer sends nothing


def test_an_opened_lock_times_out_the_same_way_and_a_late_answer_changes_nothing(clock):
    m, a, b = new_match(clock)
    make_lock(m, a)
    row = m.serve(a, "rescue", None)                         # the puzzle is open
    sv = a.served[row["id"]]
    advance(m, clock, 40.2)
    g = a.game
    assert g.phase == "play" and len(g.bug_lines) == 1 and g.bug_lines[0]["template_id"] == sv.template_id
    assert sv.answered and sv.correct is False
    before = (g.score, g.sent, g.streak, g.locks_cleared, len(g.bug_lines), a.rev)
    m.answered(a, sv, True)                                  # a late, correct answer: ignored
    assert (g.score, g.sent, g.streak, g.locks_cleared, len(g.bug_lines), a.rev) == before
    with pytest.raises(pvp.PvpError) as e:                   # and the lock is gone for any new puzzle request
        m.serve(a, "rescue", None)
    assert e.value.status == 409


def test_a_late_answer_does_not_touch_a_newer_lock(clock):
    m, a, b = new_match(clock)
    make_lock(m, a)
    old = a.served[m.serve(a, "rescue", None)["id"]]
    advance(m, clock, 40.2)
    g = a.game
    g.items["undo"] = 0
    make_lock(m, a, rows=(6,))                               # a new lock (row 6) opens on the same board
    assert g.phase == "locked"
    m.answered(a, old, True)
    assert g.phase == "locked" and a.lock_parts == []        # the old puzzle was not for this lock


def test_a_boss_lock_has_seventy_seconds(clock):
    m, a, b = new_match(clock)
    lk = make_lock(m, a, rows=(4, 5, 6, 7))
    assert lk["boss"] and a.conn.last_state()["lock_in"] == 70.0
    advance(m, clock, 50.0)
    assert a.game.phase == "locked"
    assert a.conn.last_state()["lock_in"] == 70.0            # the state is pushed on changes only; the deadline is fixed
    advance(m, clock, 19.8)
    assert a.game.phase == "locked"
    advance(m, clock, 0.4)
    assert a.game.phase == "play" and len(a.game.bug_lines) == 1 and a.game.sent == 0


def test_a_boss_lock_with_the_first_puzzle_right_still_times_out_as_a_wrong_answer(clock):
    m, a, b = new_match(clock)
    make_lock(m, a, rows=(4, 5, 6, 7))
    row = m.serve(a, "rescue", None)
    m.answered(a, a.served[row["id"]], True)                 # part 1 correct: the second puzzle is next
    assert a.game.phase == "locked"
    advance(m, clock, 70.2)
    assert a.game.phase == "play" and len(a.game.bug_lines) == 1 and a.game.sent == 0 and a.game.streak == 0


def test_the_lock_limit_counts_even_when_the_puzzle_was_never_opened(clock):
    m, a, b = new_match(clock)
    make_lock(m, a)
    assert a.lock_opened is False
    advance(m, clock, 40.2)
    assert a.game.phase == "play" and len(a.game.bug_lines) == 1


def test_a_lock_timeout_can_end_the_match_by_nofit(clock):
    m, a, b = new_match(clock)
    g = a.game
    for r in range(8):                                       # a board where the only gap is the lock row
        for c in range(8):
            if not (r == 7 and c == 0):
                g.grid[r][c] = {"topic": "loops", "bug": True, "bug_id": 99 + r}
    g.tray = [E.Piece("dot", ((0, 0),), "variables"), None, None]
    g.tray[0].id = "px"
    for c in range(1, 8):
        g.grid[7][c] = {"topic": "variables", "bug": False, "bug_id": None}
    assert m.do_place(a, 0, 7, 0)
    assert g.phase == "locked"
    advance(m, clock, 40.2)
    assert g.phase == "over" and g.end_reason == "nofit" and m.phase == "over" and m.winner == 1
    assert "lock_timeout" in a.conn.types()


def test_the_lock_timer_is_held_while_the_player_is_away_and_resumes_on_return(clock):
    m, a, b = new_match(clock)
    make_lock(m, a)
    advance(m, clock, 10.0)
    a.dropped_at = clock[0]
    advance(m, clock, 15.0)
    assert a.game.phase == "locked"
    m.attach(a, a.conn)
    assert a.conn.last_state()["lock_in"] == pytest.approx(30.0, abs=0.11)
    advance(m, clock, 29.8)
    assert a.game.phase == "locked"
    advance(m, clock, 0.4)
    assert a.game.phase == "play"


# --------------------------------------------------------------------------- (f) undo


def test_undo_clears_the_lock_deadline(clock):
    m, a, b = new_match(clock)
    a.game.items["undo"] = 2
    make_lock(m, a)
    advance(m, clock, 20.0)
    assert a.lock_at is not None
    assert m.do_undo(a)
    assert a.game.lock is None and a.lock_at is None and a.conn.last_state()["lock_in"] is None
    advance(m, clock, 30.0)                                  # the old deadline (t0 + 40) passes: nothing happens
    assert a.game.phase == "play" and a.game.bug_lines == []
    assert "lock_timeout" not in a.conn.types()
    make_lock(m, a)                                          # a new lock gets a fresh 40 s
    assert a.conn.last_state()["lock_in"] == 40.0


# --------------------------------------------------------------------------- (g) the state carries the countdowns


def test_state_carries_land_in_and_lock_in(clock):
    m, a, b = new_match(clock)
    st = a.conn.last_state()
    assert st["land_in"] is None and st["lock_in"] is None
    rows_to(m, a, 2)
    assert a.conn.last_state()["land_in"] == 4.0 and a.conn.last_state()["lock_in"] is None
    advance(m, clock, 1.3)
    m.push_state(a)
    assert a.conn.last_state()["land_in"] == pytest.approx(2.7, abs=0.01)
    make_lock(m, a)
    st = a.conn.last_state()
    assert st["lock_in"] == 40.0 and isinstance(st["land_in"], float)
    advance(m, clock, 7.0)
    m.push_state(a)
    st = a.conn.last_state()
    assert st["lock_in"] == pytest.approx(33.0, abs=0.01) and st["land_in"] < 0
    # the opponent is not given the countdowns (only its own board view)
    assert "land_in" not in pvp.opponent_view(a) and "lock_in" not in pvp.opponent_view(a)


def test_the_timers_stop_when_the_game_is_over(clock):
    m, a, b = new_match(clock)
    rows_to(m, a, 1)
    make_lock(m, a)
    m.finish(1, "resign")
    st = a.conn.last_state()
    assert st["land_in"] is None and st["lock_in"] is None and a.land_at is None and a.lock_at is None


# --------------------------------------------------------------------------- over the real API


@pytest.fixture
def live(tc, monkeypatch):
    """The ``tc`` fixture switches the timers off; here they run on the accelerated clock (SPEED 20: 4 s = 0.2 s)."""
    for name, v in REAL.items():
        monkeypatch.setattr(pvp, name, v)
    return tc


def test_over_the_socket_a_timed_landing_arrives_as_landed_with_timed(live):
    tc = live
    ta, tb = queue(tc, i=1), queue(tc, i=2)
    a, b = Client(tc, ta), Client(tc, tb)
    a.until("lobby")
    b.until("lobby")
    start_match(a, b)
    m, pb = match_of(b), side_of(b)
    with pvp._lock:
        rows_to(m, pb, 2)
    st = b.until("state")
    assert st["you"]["land_in"] is not None and 0 < st["you"]["land_in"] <= 4.0 and st["you"]["lock_in"] is None
    msg = b.until("landed", timeout=5)
    assert msg == {"t": "landed", "rows": 2, "timed": True}
    st = b.wait(lambda s: s["pending"] == [] and len(s["bugLines"]) == 2)
    assert st["land_in"] is None
    a.close()
    b.close()


def test_over_the_socket_a_lock_timeout_and_a_late_answer(live, monkeypatch):
    tc = live
    ta, tb = queue(tc, i=1), queue(tc, i=2)
    a, b = Client(tc, ta), Client(tc, tb)
    a.until("lobby")
    b.until("lobby")
    start_match(a, b)
    m, pa = match_of(a), side_of(a)
    with pvp._lock:
        prime(pa)
    a.send(t="place", i=0, r=7, c=0)
    st = a.wait(lambda s: s["phase"] == "locked")
    assert 0 < st["lock_in"] <= 40.0
    body = {"kind": "rescue", "match_id": a.mid, "match_token": a.tok, "level": "intermediate",
            "topic": st["lock"]["topic"], "tier": st["lock"]["tier"]}
    r = tc.post("/api/puzzle/next", json=body)
    assert r.status_code == 200, r.text
    pz = r.json()
    with pvp._lock:                                          # the limit runs out now (instead of waiting 2 s of real time)
        pa.lock_at = pvp.now() - 0.01
    assert a.until("lock_timeout") == {"t": "lock_timeout"}
    st = a.wait(lambda s: s["phase"] == "play")
    assert st["lock"] is None and st["lock_in"] is None and len(st["bugLines"]) == 1 and st["streak"] == 0
    # the late answer is checked as always but not applied
    ans = tc.post(f"/api/puzzle/{pz['id']}/answer", json={**answer_body(bank.get_puzzle(pz["id"]), True),
                                                           "match_id": a.mid, "match_token": a.tok})
    assert ans.status_code == 200 and ans.json()["correct"] is True
    time.sleep(0.3)
    a.drain()
    assert a.state["phase"] == "play" and a.state["sent"] == 0 and len(a.state["bugLines"]) == 1
    # a new puzzle for the gone lock is refused
    r = tc.post("/api/puzzle/next", json=body)
    assert r.status_code == 409
    a.close()
    b.close()
