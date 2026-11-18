"""Misaki, the AI opponent (docs/pvp.md section 5): the search, the ladder, training mode and the API.

The strength check plays full bot-vs-bot matches on the real match code with a virtual clock (``misaki_sim``).
"""
import random
import time
from pathlib import Path

import pytest

from app import nicknames, pvp, pvp_bot, pvp_coach, ranked
from app import rescue_engine as E

from . import misaki_sim
from .test_pvp_match import (Client, dev, legal, match_of, nick, post, prime_lock, side_of,  # noqa: F401 (fixtures)
                             solve, tc)

# --------------------------------------------------------------------------- helpers


def random_midgame(seed: int, target: int):
    """A pvp game after random legal play (locks cleared at once) until about ``target`` blocks are on the board."""
    r = random.Random(seed)
    g = E.RescueGame(seed, "intermediate", "pvp")
    for _ in range(400):
        if sum(1 for row in g.grid for x in row if x) >= target:
            break
        moves = [(i, rr, cc) for i, p in enumerate(g.tray) if p for rr in range(8) for cc in range(8)
                 if g.can_place(p, rr, cc)]
        if not moves:
            break
        i, rr, cc = r.choice(moves)
        res = g.place(i, rr, cc)
        if res and res["lock"]:
            for a, b in res["lock"]["cells"]:
                g.grid[a][b] = None
            g.lock = None
            g.phase = "play"
        if g.phase == "over":
            break
    return g


def bits_to_set(mask):
    return {(b // 8, b % 8) for b in range(64) if mask >> b & 1}


# --------------------------------------------------------------------------- the bitboard mirrors the engine


def test_transpose_flips_the_matrix():
    rng = random.Random(1)
    for _ in range(100):
        x = rng.getrandbits(64)
        naive = sum(1 << (c * 8 + r) for r in range(8) for c in range(8) if x >> (r * 8 + c) & 1)
        assert pvp_bot.transpose(x) == naive


def test_lock_lines_and_land_mirror_the_engine():
    rng = random.Random(2)
    for n in range(150):
        g = E.RescueGame(n, "beginner", "pvp")
        for r in range(8):
            for c in range(8):
                if rng.random() < 0.55:
                    g.grid[r][c] = {"topic": "loops", "bug": rng.random() < 0.12, "bug_id": None}
        for r in rng.sample(range(8), rng.randint(0, 2)):        # some full rows / columns
            for c in range(8):
                g.grid[r][c] = {"topic": "loops", "bug": False, "bug_id": None}
        for c in rng.sample(range(8), rng.randint(0, 1)):
            for r in range(8):
                g.grid[r][c] = {"topic": "loops", "bug": False, "bug_id": None}
        occ, normal = pvp_bot.board_bits(g.grid)
        lock = g.find_lock()
        lines, clear = pvp_bot.lock_lines(normal)
        assert lines == (lock["count"] if lock else 0)
        assert bits_to_set(clear) == (set(lock["cells"]) if lock else set())
        # landing k rows
        k = rng.randint(1, 4)
        g.pending = [{"topic": "loops", "template_id": "loops_bug"}] * k
        want = pvp_bot.land(occ, normal, k)
        g.land_pending()
        if want is None:
            assert g.phase == "over" and g.end_reason == "topped_out"
        else:
            assert g.phase != "over"
            assert pvp_bot.board_bits(g.grid) == want


# --------------------------------------------------------------------------- the search


def test_search_takes_a_line_and_returns_a_legal_placement():
    g = E.RescueGame(5, "intermediate", "pvp")
    for c in range(1, 8):
        g.grid[7][c] = {"topic": "loops", "bug": False, "bug_id": None}
    g.tray = [E.Piece("dot", ((0, 0),), "loops"), E.Piece("i3", ((0, 0), (0, 1), (0, 2)), "loops"), None]
    occ, normal = pvp_bot.board_bits(g.grid)
    for beam in (1, 4, 32):
        plan = pvp_bot.search(occ, normal, g.tray, 0, beam, 0.9)
        assert (plan.i, plan.r, plan.c, plan.lines) == (0, 7, 0, 1)
        assert g.can_place(g.tray[plan.i], plan.r, plan.c)


def test_search_plans_are_legal_on_many_boards_and_none_when_nothing_fits():
    for seed in range(40):
        g = random_midgame(seed, 12 + seed % 30)
        if g.phase == "over":
            continue
        occ, normal = pvp_bot.board_bits(g.grid)
        for beam in (1, 12):
            plan = pvp_bot.search(occ, normal, g.tray, seed % 3, beam)
            if plan is not None:
                assert g.can_place(g.tray[plan.i], plan.r, plan.c)
    g = E.RescueGame(1, "beginner", "pvp")
    g.grid = [[{"topic": "loops", "bug": True, "bug_id": 1} for _ in range(8)] for _ in range(8)]
    occ, normal = pvp_bot.board_bits(g.grid)
    assert pvp_bot.search(occ, normal, g.tray, 0, 32) is None


def test_search_avoids_a_top_out_when_it_can():
    g = E.RescueGame(3, "intermediate", "pvp")
    g.grid[0][0] = {"topic": "loops", "bug": False, "bug_id": None}      # a block in the top row
    for c in range(1, 8):
        g.grid[7][c] = {"topic": "loops", "bug": False, "bug_id": None}
    g.tray = [E.Piece("dot", ((0, 0),), "loops"), E.Piece("dot", ((0, 0),), "loops"), None]
    occ, normal = pvp_bot.board_bits(g.grid)
    # one pending row would push (0, 0) off the board unless the placement makes a lock (which keeps it pending)
    plan = pvp_bot.search(occ, normal, g.tray, 1, 4)
    assert not plan.topped and plan.lines == 1 and (plan.r, plan.c) == (7, 0)


def test_decision_time_stays_small_at_beam_32():
    times = []
    for seed in range(25):
        g = random_midgame(100 + seed, 22 + seed % 14)
        if g.phase == "over":
            continue
        occ, normal = pvp_bot.board_bits(g.grid)
        t = time.perf_counter()
        pvp_bot.search(occ, normal, g.tray, seed % 3, 32, 0.93)
        times.append(time.perf_counter() - t)
    assert len(times) >= 15
    # the target is < 50 ms on the server; CI machines are slower and noisier, so the bounds are generous
    assert sum(times) / len(times) < 0.1
    assert max(times) < 0.25


def test_the_brain_is_deterministic_and_follows_the_ladder_table():
    g = random_midgame(9, 20)

    def first(seed):
        b = pvp_bot.BotBrain(seed, 3)
        return b.step(g, 100.0), b.next_at

    assert first(7) == first(7)
    for lv, spec in pvp_bot.LADDER.items():
        b = pvp_bot.BotBrain(1, lv)
        assert (b.beam, b.accuracy) == (spec["beam"], spec["accuracy"])
        for _ in range(50):
            assert spec["think"][0] <= b.place_delay() <= spec["think"][1]
            assert 3.0 <= b.think_time(1) <= 8.0 and 3.0 <= b.think_time(3) <= 8.0
        bt = pvp_bot.BotBrain(1, lv, training=True)
        assert bt.delay == (spec["think"][0] * 1.5, spec["think"][1] * 1.5)
    assert [(lv, pvp_bot.LADDER[lv]["beam"]) for lv in (1, 2, 3, 4)] == [(1, 1), (2, 4), (3, 12), (4, 32)]
    assert pvp_bot.effective_level(3, True) == 2 and pvp_bot.effective_level(1, True) == 1
    assert pvp_bot.effective_level(3, False) == 3
    assert pvp_bot.title(3) == "Misaki · Giỏi" and pvp_bot.title(4) == "Misaki · Bậc thầy"


def test_item_use_follows_the_level():
    g = random_midgame(11, 40)
    g.items["bomb"] = 1
    g.items["shuffle"] = 1
    assert pvp_bot.LADDER[1]["bomb"] is False and pvp_bot.LADDER[2]["bomb"] and not pvp_bot.LADDER[2]["shuffle"]
    assert pvp_bot.LADDER[3]["bomb"] and pvp_bot.LADDER[3]["shuffle"]
    for lv in (1, 2):
        b = pvp_bot.BotBrain(1, lv)
        act = None
        for _ in range(3):
            act = b.step(g, 1e6)
            b.next_at = 0
        assert act is None or act[0] not in ("shuffle",) and (lv > 1 or act[0] != "bomb")


# --------------------------------------------------------------------------- strength (bot against bot)


def test_each_level_beats_the_one_below_in_a_clear_majority():
    games = 40
    rates = {}
    for strong in (2, 3, 4):
        r = misaki_sim.head_to_head(strong, strong - 1, games)
        rates[strong] = r["rate"]
        print(f"Misaki {strong} beats Misaki {strong - 1}: {r['wins']}/{games} (draws {r['draws']})")
    assert all(rate >= 0.65 for rate in rates.values()), rates


# --------------------------------------------------------------------------- suggestions


def test_suggestions_are_legal_on_the_current_state():
    seen = set()
    for seed in range(60):
        g = random_midgame(200 + seed, 8 + seed % 32)
        if g.phase == "over":
            continue
        g.queue_incoming([{"topic": "loops", "template_id": "loops_bug"}] * (seed % 3))
        sg = pvp_bot.suggest(g)
        assert sg is not None
        piece = g.tray[sg.i]
        assert piece is not None and g.can_place(piece, sg.r, sg.c)
        assert sorted(map(tuple, sg.cells)) == sorted((sg.r + dr, sg.c + dc) for dr, dc in piece.cells)
        assert all(g.grid[r][c] is None for r, c in sg.cells)
        assert sg.reason in ("line", "safe", "danger", "fit")
        seen.add(sg.reason)
    assert {"line", "fit"} <= seen or len(seen) >= 2


def test_suggestion_reasons_and_none():
    g = E.RescueGame(5, "intermediate", "pvp")
    for c in range(1, 8):
        g.grid[7][c] = {"topic": "loops", "bug": False, "bug_id": None}
    g.tray = [E.Piece("dot", ((0, 0),), "loops"), None, None]
    sg = pvp_bot.suggest(g)
    assert (sg.reason, sg.n, sg.r, sg.c) == ("line", 1, 7, 0)
    assert pvp_coach.suggestion_text("line", 1) == "Đặt ở đây sẽ hoàn thành 1 hàng."
    # nothing fits
    g.grid = [[{"topic": "loops", "bug": True, "bug_id": 1} for _ in range(8)] for _ in range(8)]
    assert pvp_bot.suggest(g) is None
    # no placement while a lock is open
    g2 = E.RescueGame(5, "intermediate", "pvp")
    g2.phase = "locked"
    assert pvp_bot.suggest(g2) is None


# --------------------------------------------------------------------------- the coach (pure logic)


def test_the_coach_copy_is_complete_and_short():
    assert set(pvp_coach.KINDS) <= set(pvp_coach.TEXTS)
    for kind in pvp_coach.KINDS:
        assert len(pvp_coach.TEXTS[kind]) >= 2
        for text in pvp_coach.TEXTS[kind]:
            out = pvp_coach._format(text, 8, "Vòng lặp")
            assert 0 < len(out) <= pvp_coach.MAX_TEXT and "{" not in out, out
    for key in pvp_coach.SUGGESTION_KEYS:
        assert 0 < len(pvp_coach.suggestion_text(key, 4)) <= pvp_coach.MAX_TEXT


def test_the_coach_picks_the_variant_from_the_seed_and_throttles():
    a, b, c = pvp_coach.Coach(1234), pvp_coach.Coach(1234), pvp_coach.Coach(1234)
    ma = [a.event("good", 10.0 + 10 * i, n=2)["text"] for i in range(4)]
    mb = [b.event("good", 50.0 + 10 * i, n=2)["text"] for i in range(4)]
    assert ma == mb                                      # same seed, same story (independent of the clock)
    variants = {pvp_coach.Coach(s).event("good", 0.0, n=2)["text"] for s in range(30)}
    assert len(variants) == len(pvp_coach.TEXTS["good"])
    # at most one message every 4 s; an event that waits is sent when the pause is over
    m1 = c.event("streak", 100.0, n=3)
    assert m1["kind"] == "streak" and m1["t"] == "coach" and "{" not in m1["text"]
    assert c.event("good", 101.0, n=2) is None
    assert c.due(102.0) is None
    m2 = c.due(104.1)
    assert m2["kind"] == "good"
    assert c.due(110.0) is None
    # a deferred event does not wait for ever
    c.event("cancel", 120.0, n=1)
    assert c.event("wrong", 121.0, topic="Hàm") is None
    assert c.due(127.5) is None


def test_the_coach_prefers_the_more_important_deferred_event():
    c = pvp_coach.Coach(5)
    c.event("streak", 0.0, n=3)
    c.event("cancel", 1.0, n=1)
    c.event("wrong", 2.0, topic="Biến")
    c.event("streak", 3.0, n=3)
    assert c.due(4.5)["kind"] == "wrong"


def test_coach_state_kinds_danger_bugline_and_nofit():
    g = E.RescueGame(3, "intermediate", "pvp")
    c = pvp_coach.Coach(9)
    assert c.observe(g, 0.0) is None
    g.grid[0][3] = {"topic": "loops", "bug": False, "bug_id": None}
    g.pending = [{"topic": "loops", "template_id": "loops_bug"}] * 2
    m = c.observe(g, 1.0)
    assert m["kind"] == "danger" and m["cells"] == [[0, 3]] and "2" in m["text"] and len(m["text"]) <= 120
    assert c.observe(g, 6.0) is None                     # not again within 15 s while it lasts
    assert c.observe(g, 17.0)["kind"] == "danger"
    # a bug line unfixed for 30 s (once per bug line)
    g2 = E.RescueGame(4, "intermediate", "pvp")
    g2.bug_lines = [{"id": 1, "cells": [(7, 0)], "topic": "loops", "template_id": "loops_bug"}]
    c2 = pvp_coach.Coach(9)
    assert c2.observe(g2, 100.0) is None
    assert c2.observe(g2, 129.0) is None
    m = c2.observe(g2, 130.5)
    assert m["kind"] == "bugline"
    assert c2.observe(g2, 200.0) is None
    # only one piece still fits
    g3 = E.RescueGame(4, "intermediate", "pvp")
    g3.grid = [[{"topic": "loops", "bug": True, "bug_id": 1} for _ in range(8)] for _ in range(8)]
    g3.grid[7][7] = None
    g3.tray = [E.Piece("dot", ((0, 0),), "loops"), E.Piece("i3", ((0, 0), (0, 1), (0, 2)), "loops"),
               E.Piece("sq2", ((0, 0), (0, 1), (1, 0), (1, 1)), "loops")]
    m = pvp_coach.Coach(1).observe(g3, 5.0)
    assert m["kind"] == "nofit_risk"
    # the first lines the opponent sends are announced once
    c4 = pvp_coach.Coach(2)
    assert c4.event("incoming", 0.0)["kind"] == "incoming"
    assert c4.event("incoming", 50.0) is None


# --------------------------------------------------------------------------- the API


def device_hash(d):
    return ranked._device_hash(d)


@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(pvp, "SPEED", 5.0)


def start_bot(tc, d=None, misaki=1, training=False, expect=200, **extra):
    if d is None:
        d = dev()
        for lv in range(1, (misaki or 1)):             # a device that has beaten the levels below
            ranked.misaki_record(device_hash(d), lv, True)
    body = dict(level="intermediate", nickname=nick(7), device_id=d, **extra)
    if misaki is not None:
        body["misaki"] = misaki
    if training:
        body["training"] = True
    r = tc.post("/api/pvp/bot", json=body)
    assert r.status_code == expect, r.text
    return r.json()["ticket"] if expect == 200 else r.json()


def go(tc, ticket):
    c = Client(tc, ticket)
    lob = c.until("lobby")
    c.send(t="ready")
    c.until("start")
    c.until("state")
    return c, lob


def test_misaki_status_and_validation(tc):
    d = dev()
    r = tc.get("/api/pvp/misaki", params={"device_id": d})
    assert r.status_code == 200
    assert r.json() == {"unlocked": 1, "wins": {"1": 0, "2": 0, "3": 0, "4": 0},
                        "games": {"1": 0, "2": 0, "3": 0, "4": 0}}
    assert tc.get("/api/pvp/misaki", params={"device_id": "nope"}).status_code == 422
    assert tc.get("/api/pvp/misaki").status_code == 422
    for bad in (0, 5):
        assert tc.post("/api/pvp/bot", json={"level": "beginner", "nickname": nick(1), "device_id": d,
                                             "misaki": bad}).status_code == 422
    assert tc.post("/api/pvp/bot", json={"level": "beginner", "nickname": nick(1), "device_id": d,
                                         "training": True}).status_code == 422


def test_locked_levels_are_refused_until_the_level_below_is_beaten(tc):
    d = dev()
    for lv in (2, 3, 4):
        r = start_bot(tc, d, misaki=lv, expect=403)
        assert "detail" in r
    h = device_hash(d)
    assert ranked.misaki_record(h, 1, False) is None              # a loss unlocks nothing
    start_bot(tc, d, misaki=2, expect=403)
    assert ranked.misaki_record(h, 1, True) == 2
    assert ranked.misaki_record(h, 1, True) is None               # already open
    assert tc.get("/api/pvp/misaki", params={"device_id": d}).json() == {
        "unlocked": 2, "wins": {"1": 2, "2": 0, "3": 0, "4": 0}, "games": {"1": 3, "2": 0, "3": 0, "4": 0}}
    start_bot(tc, d, misaki=2)
    start_bot(tc, d, misaki=3, expect=403)
    assert ranked.misaki_record(h, 3, True) == 4
    assert ranked.misaki_record(h, 4, True) is None               # nothing is above level 4
    assert ranked.misaki_unlocked(h) == 4
    # training is subject to the same lock
    other = dev()
    start_bot(tc, other, misaki=2, training=True, expect=403)


def test_the_lobby_describes_misaki_and_she_needs_no_generated_name(tc, fast):
    assert not nicknames.is_generated("Misaki")
    d = dev()
    ranked.misaki_record(device_hash(d), 1, True)
    ranked.misaki_record(device_hash(d), 2, True)
    c, lob = go(tc, start_bot(tc, d, misaki=3))
    assert lob["opponent"] == {"nickname": "Misaki", "bot": True, "misaki": 3, "title": "Misaki · Giỏi",
                               "training": False, "plays_as": 3, "connected": True, "rating": None}
    c.close()
    c2, lob2 = go(tc, start_bot(tc, d, misaki=3, training=True))
    # the chosen level is reported; she plays one lower in training
    assert lob2["opponent"]["misaki"] == 3 and lob2["opponent"]["title"] == "Misaki · Giỏi"
    assert lob2["opponent"]["training"] is True and lob2["opponent"]["plays_as"] == 2
    bot = next(p for p in match_of(c2).players() if p.bot)
    lo, hi = pvp_bot.LADDER[2]["think"]
    assert bot.brain.level == 2 and bot.brain.delay == (lo * 1.5, hi * 1.5)
    c2.close()
    # the generic bot keeps the old look
    t = post(tc, "/api/pvp/bot", level="beginner", nickname=nick(5), device_id=dev())["ticket"]
    c3 = Client(tc, t)
    lob3 = c3.until("lobby")
    assert lob3["opponent"]["nickname"].startswith("Máy ") and "misaki" not in lob3["opponent"]
    c3.close()


def test_winning_against_misaki_unlocks_the_next_level_and_is_not_rated(tc, monkeypatch):
    monkeypatch.setattr(pvp, "SPEED", 300.0)
    d = dev()
    c, _ = go(tc, start_bot(tc, d, misaki=1))                  # the human idles; overtime beats her
    end = c.until("end", timeout=60)
    assert end["winner"] == "you" and "rating" not in end
    assert end["misaki"] == {"level": 1, "unlocked_now": 2}
    prog = tc.get("/api/pvp/misaki", params={"device_id": d}).json()
    assert prog["unlocked"] == 2 and prog["wins"]["1"] == 1 and prog["games"]["1"] == 1
    assert ranked.pvp_rating(device_hash(d)) == 1000
    c.close()


def test_losing_counts_a_game_but_unlocks_nothing(tc, fast):
    d = dev()
    ranked.misaki_record(device_hash(d), 1, True)
    c, _ = go(tc, start_bot(tc, d, misaki=2))
    c.send(t="resign")
    end = c.until("end")
    assert end["winner"] == "opponent" and end["misaki"] == {"level": 2, "unlocked_now": None}
    prog = tc.get("/api/pvp/misaki", params={"device_id": d}).json()
    assert prog["unlocked"] == 2 and prog["games"]["2"] == 1 and prog["wins"]["2"] == 0
    c.close()


def test_training_matches_never_count_or_unlock(tc, monkeypatch):
    monkeypatch.setattr(pvp, "SPEED", 300.0)
    d = dev()
    c, _ = go(tc, start_bot(tc, d, misaki=1, training=True))
    end = c.until("end", timeout=60)
    assert end["winner"] == "you" and end["misaki"] == {"level": 1, "unlocked_now": None}
    assert tc.get("/api/pvp/misaki", params={"device_id": d}).json()["unlocked"] == 1
    assert tc.get("/api/pvp/misaki", params={"device_id": d}).json()["games"]["1"] == 0
    c.close()


# --------------------------------------------------------------------------- training mode over the socket


def test_suggest_outside_training_is_an_error(tc, fast):
    c, _ = go(tc, start_bot(tc, misaki=1))
    c.send(t="suggest")
    assert c.until("error")["code"] == "not_training"
    c.close()
    t = post(tc, "/api/pvp/bot", level="beginner", nickname=nick(5), device_id=dev())["ticket"]
    g = Client(tc, t)
    g.until("lobby")
    g.send(t="ready")
    g.until("state")
    g.send(t="suggest")
    assert g.until("error")["code"] == "not_training"
    g.close()


def test_training_suggestion_is_legal_and_rate_limited(tc, fast):
    c, _ = go(tc, start_bot(tc, misaki=2, training=True))
    c.send(t="suggest")
    sg = c.until("suggestion")
    assert "none" not in sg and sg["why"] and len(sg["why"]) <= 120
    piece = c.state["tray"][sg["i"]]
    assert piece is not None and len(sg["cells"]) == len(piece["cells"])
    assert sorted(map(tuple, sg["cells"])) == sorted((sg["r"] + dr, sg["c"] + dc) for dr, dc in piece["cells"])
    assert all(0 <= r < 8 and 0 <= cc < 8 and c.state["grid"][r][cc] is None for r, cc in sg["cells"])
    # the suggested placement is accepted by the server
    st = c.act(t="place", i=sg["i"], r=sg["r"], c=sg["c"])
    assert st["t"] == "state" and st["you"]["score"] > 0
    # one every 3 s: the second one is dropped silently
    c.send(t="suggest")
    c.send(t="suggest")
    time.sleep(0.3)
    c.drain()
    assert [m["t"] for m in c.log].count("suggestion") == 1      # the two quick ones were dropped
    c.close()


def test_suggestion_says_none_when_a_lock_is_open(tc, fast):
    c, _ = go(tc, start_bot(tc, misaki=1, training=True))
    prime_lock(c)
    c.act(t="place", i=0, r=7, c=0)
    c.send(t="suggest")
    sg = c.until("suggestion")
    assert sg["none"] is True and sg["why"] == pvp_coach.suggestion_text("none")
    c.close()


def coach_messages(c):
    return [m for m in c.log if m["t"] == "coach"]


def test_training_coach_reacts_to_a_wrong_answer_and_a_streak_and_is_throttled(tc, monkeypatch):
    monkeypatch.setattr(pvp, "SPEED", 5.0)
    c, _ = go(tc, start_bot(tc, misaki=1, training=True))
    prime_lock(c, "loops")
    c.act(t="place", i=0, r=7, c=0)
    solve(tc, c, correct=False)
    m = c.until("coach")
    assert m["kind"] == "wrong" and 0 < len(m["text"]) <= 120 and "{" not in m["text"]
    c.close()


def test_training_coach_warns_about_danger_with_the_cells(tc, monkeypatch):
    monkeypatch.setattr(pvp, "SPEED", 5.0)
    c, _ = go(tc, start_bot(tc, misaki=1, training=True))
    side = side_of(c)
    with pvp._lock:
        g = side.game
        g.grid[0][2] = {"topic": "loops", "bug": False, "bug_id": None}
        g.queue_incoming([{"topic": "loops", "template_id": "loops_bug"}] * 2)
        match_of(c).push_state(side)
        match_of(c).coach_look(side)
    m = c.until("coach")
    assert m["kind"] == "danger" and m["cells"] == [[0, 2]] and "2" in m["text"]
    c.close()


def test_no_coach_outside_training(tc, monkeypatch):
    monkeypatch.setattr(pvp, "SPEED", 5.0)
    c, _ = go(tc, start_bot(tc, misaki=1))
    prime_lock(c, "loops")
    c.act(t="place", i=0, r=7, c=0)
    solve(tc, c, correct=False)
    c.wait(lambda s: s["phase"] == "play")
    time.sleep(0.2)
    c.drain()
    assert coach_messages(c) == [] and side_of(c).coach is None
    c.close()


# --------------------------------------------------------------------------- deployment


def test_the_dockerfile_ships_the_coach_copy():
    docker = (Path(__file__).resolve().parents[2] / "Dockerfile").read_text(encoding="utf-8")
    assert "backend/content/misaki_coach.yaml" in docker
