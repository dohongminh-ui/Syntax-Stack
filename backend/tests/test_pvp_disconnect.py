"""The away budget (docs/pvp.md section 4): each human may spend AWAY_BUDGET_S seconds disconnected per match, all drops
together, so drop / rejoin / drop can not pause a game for ever. Virtual clock, two humans behind recording connections."""
import pytest

from app import pvp

from .test_pvp_timers import advance, clock, new_match  # noqa: F401


def status(p):
    return [m for m in p.conn.msgs if m["t"] == "opponent_status"]


def drop(m, p, clock_, seconds):
    """``p``'s socket drops, ``seconds`` pass (ticking), the socket comes back (if the match is still on)."""
    conn = p.conn
    m.detach(p, conn)
    advance(m, clock_, seconds)
    if m.phase == "playing":
        m.attach(p, conn)


def test_the_budget_is_thirty_seconds_and_a_fresh_player_has_all_of_it(clock):
    assert pvp.AWAY_BUDGET_S == 30.0
    m, a, b = new_match(clock)
    assert a.conn.last_state()["away_left"] == 30.0 and b.conn.last_state()["away_left"] == 30.0


def test_a_single_short_drop_still_resumes_and_spends_its_time(clock):
    m, a, b = new_match(clock)
    drop(m, a, clock, 8.0)
    assert m.phase == "playing" and a.connected
    assert a.conn.last_state()["away_left"] == pytest.approx(22.0, abs=0.11)
    assert b.conn.msgs[-1]["t"] in ("opponent_status", "opponent", "state") and \
        status(b) == [{"t": "opponent_status", "connected": False, "grace_s": 20},
                      {"t": "opponent_status", "connected": True, "grace_s": 0}]


def test_repeated_drop_and_rejoin_exhausts_the_budget_then_the_next_drop_loses_at_once(clock):
    m, a, b = new_match(clock)
    drop(m, a, clock, 19.0)                                  # the old exploit: just inside the 20 s grace, again and again
    assert m.phase == "playing"
    drop(m, a, clock, 10.0)                                  # 29 s used: 1 s left (the grace of this drop was 11 s)
    assert m.phase == "playing"
    assert a.conn.last_state()["away_left"] == pytest.approx(1.0, abs=0.11)
    m.detach(a, a.conn)                                      # the third drop: 1 s of grace, no more
    assert m.phase == "playing" and status(b)[-1] == {"t": "opponent_status", "connected": False, "grace_s": 1.0}
    advance(m, clock, 1.2)
    assert (m.phase, m.winner, m.reason) == ("over", 1, "disconnect")


def test_a_drop_with_the_budget_already_spent_loses_at_once(clock):
    m, a, b = new_match(clock)
    drop(m, a, clock, 19.0)
    drop(m, a, clock, 11.0)                                  # the second grace is capped to 11 s: it ends the match here
    assert (m.phase, m.winner, m.reason) == ("over", 1, "disconnect")
    # a budget used up exactly by completed drops: the next detach finishes in the call, without waiting for a tick
    m, a, b = new_match(clock)
    a.away_used = pvp.AWAY_BUDGET_S
    m.detach(a, a.conn)
    assert (m.phase, m.winner, m.reason) == ("over", 1, "disconnect")
    assert "opponent_status" not in [x["t"] for x in b.conn.msgs if x.get("connected") is False]


def test_grace_is_capped_by_the_remaining_budget_and_the_opponent_is_told(clock):
    m, a, b = new_match(clock)
    drop(m, a, clock, 15.0)                                  # 15 used, 15 left
    b.conn.msgs.clear()
    m.detach(a, a.conn)
    assert status(b) == [{"t": "opponent_status", "connected": False, "grace_s": 15.0}]
    advance(m, clock, 14.5)
    assert m.phase == "playing"                              # not before the capped grace is over (it is 15, not 20)
    advance(m, clock, 0.7)
    assert (m.phase, m.winner, m.reason) == ("over", 1, "disconnect")


def test_the_second_player_has_a_budget_of_their_own(clock):
    m, a, b = new_match(clock)
    drop(m, a, clock, 19.0)
    drop(m, b, clock, 5.0)
    assert b.conn.last_state()["away_left"] == pytest.approx(25.0, abs=0.11)
    assert status(a)[-2:] == [{"t": "opponent_status", "connected": False, "grace_s": 20},
                              {"t": "opponent_status", "connected": True, "grace_s": 0}]


def test_state_reports_the_budget_left_while_away_counts_too(clock):
    m, a, b = new_match(clock)
    conn = a.conn
    m.detach(a, conn)
    advance(m, clock, 4.0)
    assert a.away_left() == pytest.approx(26.0, abs=0.11)
    m.attach(a, conn)
    assert a.conn.last_state()["away_left"] == pytest.approx(26.0, abs=0.11)
    advance(m, clock, 10.0)
    assert a.conn.last_state()["away_left"] == pytest.approx(26.0, abs=0.11)   # connected time is free


def test_both_dropped_is_still_a_draw(clock):
    m, a, b = new_match(clock)
    m.detach(a, a.conn)
    m.detach(b, b.conn)
    advance(m, clock, 20.5)
    assert (m.phase, m.winner, m.reason) == ("over", None, "both_disconnected")


def test_a_budget_spent_drop_while_the_other_is_gone_is_a_draw(clock):
    m, a, b = new_match(clock)
    m.detach(b, b.conn)
    a.away_used = pvp.AWAY_BUDGET_S
    m.detach(a, a.conn)
    assert (m.phase, m.winner, m.reason) == ("over", None, "both_disconnected")


def test_a_rematch_resets_the_budget(clock):
    m, a, b = new_match(clock)
    drop(m, a, clock, 12.0)
    assert a.away_used == pytest.approx(12.0, abs=0.11)
    m.new_round()
    assert a.away_used == 0.0 and b.away_used == 0.0
    assert a.conn.last_state()["away_left"] == 30.0


def test_the_bot_is_not_limited(clock):
    m = pvp.Match("intermediate", "bot")
    m.seed = 7
    h = pvp.Player("intermediate", "H", None, "queue")
    h.conn, h.connected, h.ready = None, True, True
    bot = pvp.Player("intermediate", "Bot", None, "bot", bot=True)
    m.seat(h, 0)
    m.seat(bot, 1)
    m.start()
    advance(m, clock, 60.0)
    assert bot.connected and bot.dropped_at is None and m.phase == "playing"
