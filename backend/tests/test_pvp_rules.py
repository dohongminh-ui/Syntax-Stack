"""The Code Rescue "Đối kháng" rules (docs/pvp.md section 2): the Python engine against the real game.js.

``tests/js_harness/play.mjs <games> <seed0> pvp`` plays pvp games with the REAL frontend/js/game.js: random
incoming rows (queued at random times, also while a lock is pending), cancels, landings, top-outs, no-fit losses,
undo across pending rows, overtime-style single rows, items, bug fixes. ``rescue_engine.replay_pvp`` has to reach
exactly the same final state for every one of them. The rescue/ranked golden test stays in test_rescue_engine.py.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app import rescue_engine as E

HARNESS = Path(__file__).resolve().parent / "js_harness" / "play.mjs"
GAMES = 400


@pytest.fixture(scope="module")
def traces():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not on PATH: cannot run the real frontend/js/game.js for the golden test")
    out = subprocess.run([node, str(HARNESS), str(GAMES), "1", "pvp"], capture_output=True, text=True, timeout=180,
                         encoding="utf-8")
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout)


def mismatches(traces):
    bad = 0
    for t in traces:
        try:
            if E.replay_pvp(t["seed"], t["level"], t["events"]) != t["final"]:
                bad += 1
        except E.Rejected:
            bad += 1
    return bad


def test_python_pvp_rules_reproduce_game_js_final_states(traces):
    assert len(traces) >= 300
    for i, t in enumerate(traces):
        got = E.replay_pvp(t["seed"], t["level"], t["events"])
        assert got == t["final"], f"pvp game {i} (seed {t['seed']}, {t['level']}, {t['strategy']}) diverged"


def test_pvp_golden_games_cover_the_rules(traces):
    total: dict[str, int] = {}
    for t in traces:
        for k, v in t["stats"].items():
            total[k] = total.get(k, 0) + v
    print("pvp golden coverage:", total)
    assert {t["level"] for t in traces} == set(E.LEVELS)
    assert total["incoming"] >= 500 and total["landings"] >= 300 and total["bigLanding"] >= 20
    assert total["landedOverBugs"] >= 20                         # landing shifts existing bug lines up
    assert total["queuedDuringLock"] >= 50 and total["landedAfterLock"] >= 10   # rows queued while a lock is open
    assert total["lockedWithPending"] >= 50                      # locks resolved with rows waiting
    assert total["cancels"] >= 50 and total["fullyCancelled"] >= 20             # cancelling, also all of it
    assert total["sends"] >= 200 and total["sendBonus"] >= 50                   # sending, with the streak bonus
    assert total["toppedOut"] == 0                                              # landing never ends a game
    assert total["pushedOff"] >= 50                                             # ... but destroys blocks
    assert total["nofitOnPlace"] >= 10 and total["nofitOnLock"] >= 1 and total["nofitOnWrong"] >= 1
    assert total["resign"] >= 1 and total["quit"] >= 1
    assert total["undo"] >= 20 and total["undoWithPending"] >= 3 and total["undoQueuedDuring"] >= 1
    assert total["bugfix"] >= 100 and total["bugfixWrong"] >= 10                # wrong Debug answers never crash
    assert total["timedLand"] >= 50 and total["lockTimeout"] >= 20              # the two server timers (replay events)
    assert total["lockFail"] >= 50                                              # wrong lock answers never crash
    assert total["bomb"] >= 50 and total["shuffle"] >= 50 and total["debugger"] >= 50 and total["hinted"] >= 50
    assert {t["final"]["end_reason"] for t in traces} >= {"nofit", "resign", "quit"}
    assert "crash" not in {t["final"]["end_reason"] for t in traces}
    assert sum(t["final"]["landed"] for t in traces) >= 800 and sum(t["final"]["cancelled"] for t in traces) >= 100


@pytest.mark.parametrize("what", ["send_table", "cancel_off", "landing_order", "no_streak_bonus", "undo_drops_pending",
                                  "nofit_ignored"])
def test_golden_pvp_comparison_detects_a_broken_rule(traces, monkeypatch, what):
    """Deliberately break one pvp rule in the Python engine: the golden comparison has to notice."""
    G = E.RescueGame
    if what == "send_table":
        monkeypatch.setattr(E, "PVP_SEND", (0, 1, 2, 4, 4))
    elif what == "cancel_off":
        real = G.apply_correct

        def no_cancel(self, base, max_hint, free, lines):
            held, self.pending = self.pending, []
            r = real(self, base, max_hint, free, lines)
            self.pending = held
            self.sent -= 0
            return r

        monkeypatch.setattr(G, "apply_correct", no_cancel)
    elif what == "landing_order":
        real = G.queue_incoming

        def reversed_rows(self, entries):
            return real(self, list(reversed(entries)))

        monkeypatch.setattr(G, "queue_incoming", reversed_rows)
    elif what == "no_streak_bonus":
        real = G.apply_correct

        def no_bonus(self, base, max_hint, free, lines):
            r = real(self, base, max_hint, free, lines)
            if r["clean"] and self.streak >= 3 and r["send"] > 0:
                r["send"] -= 1
                self.sent -= 1
            return r

        monkeypatch.setattr(G, "apply_correct", no_bonus)
    elif what == "undo_drops_pending":
        real = G.undo

        def forgetful(self):
            ok = real(self)
            if ok:
                self.pending = []
            return ok

        monkeypatch.setattr(G, "undo", forgetful)
    elif what == "nofit_ignored":
        monkeypatch.setattr(G, "check_no_fit", lambda self: False)
    assert mismatches(traces) > 0, f"breaking '{what}' went unnoticed"


# --------------------------------------------------------------------------- unit tests of the rules (no node needed)


def cell(topic="loops", bug=False, bug_id=None):
    return {"topic": topic, "bug": bug, "bug_id": bug_id}


def pvp(seed=3, level="intermediate"):
    return E.RescueGame(seed, level, "pvp")


def fill_row_except(g, r, col, topic="variables"):
    for c in range(E.SIZE):
        g.grid[r][c] = None if c == col else cell(topic)


def entries(*topics):
    return [{"topic": t, "template_id": f"{t}_x"} for t in topics]


def test_incoming_rows_wait_and_land_after_a_placement_that_makes_no_lock():
    g = pvp()
    g.queue_incoming(entries("loops", "functions"))
    assert g.received == 2 and len(g.pending) == 2
    g.tray[0] = E.Piece("dot", ((0, 0),), "variables")
    res = g.place(0, 3, 0)
    assert res["lock"] is None and res["landed"] == 2 and g.pending == []
    # the two new rows are the bottom two, each a full row of bug cells and its own bug line, oldest on top
    assert [x["topic"] for x in g.grid[6]] == ["loops"] * 8 and [x["topic"] for x in g.grid[7]] == ["functions"] * 8
    assert all(x["bug"] for x in g.grid[6] + g.grid[7])
    assert [(b["id"], b["topic"], b["template_id"]) for b in g.bug_lines] == [
        (1, "loops", "loops_x"), (2, "functions", "functions_x")]
    assert g.bug_lines[0]["cells"] == [(6, c) for c in range(8)] and g.grid[6][0]["bug_id"] == 1
    assert g.status == "warn"
    # the piece placed before landing moved up two rows (its top-left cell was at row 3)
    assert g.grid[1][0] is not None and g.grid[3][0] is None


def test_a_placement_that_makes_a_lock_keeps_the_rows_pending_until_after_the_lock():
    g = pvp()
    fill_row_except(g, 7, 0)
    g.tray = [E.Piece("dot", ((0, 0),), "variables"), E.make_piece(g.rng), E.make_piece(g.rng)]
    g.queue_incoming(entries("loops"))
    res = g.place(0, 7, 0)
    assert res["lock"] is not None and res["landed"] == 0 and len(g.pending) == 1
    g.phase = "locked"
    g.queue_incoming(entries("conditions"))          # more rows arrive while the puzzle is open
    out = g.pvp_resolve_lock(False, [{"correct": True, "hint": 0, "topic": "variables", "template_id": "variables_t"}])
    assert out["result"] == "ok" and out["send"] == 0 and out["cancelled"] == 1   # 1 line sent, cancels 1 pending
    assert len(g.pending) == 1 and g.pending[0]["topic"] == "conditions"            # the older row was cancelled
    assert g.phase == "play" and g.locks_cleared == 1
    res = g.place(1, 0, 0)                                                          # next placement without lock
    assert res["lock"] is None and res["landed"] == 1 and g.pending == []


def test_landing_destroys_blocks_pushed_off_the_top_but_never_ends_the_game():
    g = pvp()
    g.grid[0][3] = cell("loops")                          # a block in the top row is pushed off
    g.grid[1][4] = cell("loops")
    g.queue_incoming(entries("loops"))
    assert g.land_pending() == 1
    assert g.phase == "play" and g.end_reason is None and g.pending == []
    assert g.grid[0][4] is not None and sum(1 for row in g.grid[:7] for x in row if x) == 1
    k = pvp()
    k.grid[2][3] = cell("loops")
    k.queue_incoming(entries("loops", "loops"))
    assert k.land_pending() == 2 and k.phase == "play" and k.grid[0][3] is not None
    # a bug line pushed off the top is gone, together with its cells
    b = pvp()
    b.queue_incoming(entries("loops"))
    b.land_pending()
    b.queue_incoming(entries(*["functions"] * 8))
    assert b.land_pending() == 8 and [x["topic"] for x in b.bug_lines] == ["functions"] * 8
    flood = pvp()
    flood.queue_incoming(entries(*(["loops"] + ["functions"] * 8)))
    assert flood.land_pending() == 9 and flood.phase == "play"     # the oldest row is pushed off as well
    assert len(flood.bug_lines) == 8 and all(x["bug"] for row in flood.grid for x in row)
    assert flood.check_no_fit() and flood.end_reason == "nofit"     # a full board: no piece fits, that loses


def test_landing_moves_existing_bug_lines_with_their_cells():
    g = pvp()
    for c in range(8):
        g.grid[7][c] = cell("variables", True, 5)
    g.bug_lines.append({"id": 5, "cells": [(7, c) for c in range(8)], "topic": "variables", "template_id": "v_t"})
    g.next_bug_id = 6
    g.queue_incoming(entries("loops"))
    assert g.land_pending() == 1
    old = next(b for b in g.bug_lines if b["id"] == 5)
    assert old["cells"] == [(6, c) for c in range(8)] and g.grid[6][0]["bug_id"] == 5
    assert g.grid[7][0]["bug_id"] == 6


def test_send_table_streak_bonus_and_cancelling():
    for lines, want in ((1, 1), (2, 2), (3, 3), (4, 4), (6, 4)):
        g = pvp()
        assert g.apply_correct(100, 0, 0, lines)["send"] == want
    g = pvp()
    g.streak = 2                                           # the 3rd clean answer in a row: +1 line
    assert g.apply_correct(100, 0, 0, 1)["send"] == 2
    g = pvp()
    g.streak = 2
    assert g.apply_correct(100, 1, 0, 1)["send"] == 1      # a paid hint: no bonus
    g = pvp()
    g.queue_incoming(entries("loops", "loops", "functions"))
    r = g.apply_correct(100, 0, 0, 2)                      # 2 lines cancel 2 of the 3 pending rows (oldest first)
    assert (r["send"], r["cancelled"], g.sent, len(g.pending)) == (0, 2, 0, 1) and g.pending[0]["topic"] == "functions"
    r = g.apply_correct(250, 0, 0, 3)
    assert (r["send"], r["cancelled"], g.sent, g.pending) == (2, 1, 2, [])


def test_wrong_answers_never_crash_in_pvp():
    g = pvp()
    for n in range(3):
        fill_row_except(g, 7, 0)
        g.grid[7][0] = cell("loops")
        g.lock = g.find_lock()
        g.phase = "locked"
        out = g.pvp_resolve_lock(False, [{"correct": False, "hint": 0, "topic": "loops", "template_id": "loops_t"}])
        assert out["result"] == "bug" and g.phase == "play" and g.end_reason is None
        assert len(g.bug_lines) == 1 and g.grid[7][0]["bug"]
        g.fix_bug(g.bug_lines[0]["id"])
    assert g.apply_debug_wrong("loops", "loops_t") == "stay" and g.phase == "play"
    assert g.streak == 0 and g.status == "ok"


def test_fixing_a_bug_line_sends_nothing_and_pays_a_debugger():
    g = pvp()
    g.queue_incoming(entries("loops"))
    g.land_pending()
    assert g.fix_bug(g.bug_lines[0]["id"]) and g.sent == 0 and g.items["debugger"] == 1
    assert g.bug_lines == [] and all(x is None for row in g.grid for x in row) and g.score == E.BUG_FIX_POINTS


def test_undo_restores_the_board_but_keeps_the_rows_queued_meanwhile():
    g = pvp()
    g.items["undo"] = 1
    fill_row_except(g, 7, 0)
    g.tray = [E.Piece("dot", ((0, 0),), "variables"), E.make_piece(g.rng), E.make_piece(g.rng)]
    g.queue_incoming(entries("loops"))
    g.place(0, 7, 0)
    g.phase = "locked"
    g.queue_incoming(entries("conditions"))
    assert g.undo() and g.phase == "play" and g.grid[7][0] is None and g.items["undo"] == 0
    assert [p["topic"] for p in g.pending] == ["loops", "conditions"] and g.tray[0] is not None


def test_no_fit_loses_and_a_full_board_is_not_a_crash():
    g = pvp()
    for r in range(E.SIZE):
        for c in range(E.SIZE):
            g.grid[r][c] = cell("loops", True, 1) if r == 7 else None
    g.grid[0][0] = cell("loops")
    g.tray = [E.Piece("sq3", ((0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2), (2, 0), (2, 1), (2, 2)), "loops")] * 3
    assert g.check_no_fit() is False                       # still room for a 3x3
    for r in range(E.SIZE):
        for c in range(E.SIZE):
            if (r + c) % 2 == 0 and not g.grid[r][c]:
                g.grid[r][c] = cell("functions", True, 2)
    assert g.check_no_fit() is True and g.phase == "over" and g.end_reason == "nofit"
    assert g.check_no_fit() is False                       # only reported once


def test_both_players_get_the_same_pieces_even_after_locks():
    """pvp breaks lock-topic ties without the RNG, so two players keep drawing the same pieces."""
    a, b = pvp(11), pvp(11)
    for g in (a, b):
        fill_row_except(g, 7, 0, "variables")
        g.grid[7][1] = cell("loops")                       # a tie between two topics in the lock row
        g.tray[0] = E.Piece("dot", ((0, 0),), "functions")
    la = a.place(0, 7, 0)["lock"]
    assert la["topic"] in ("variables", "loops")
    assert a.rng() == pvp(11).rng(), "the lock must not have consumed the piece RNG"
    assert b.place(0, 7, 0)["lock"]["topic"] == la["topic"]


def test_replay_pvp_rejects_illegal_events():
    def bad(events):
        with pytest.raises(E.Rejected) as e:
            E.replay_pvp(5, "beginner", events)
        return e.value.reason

    assert bad([{"t": "place", "i": 0, "r": 7, "c": 7}]) == "illegal_place"
    assert bad([{"t": "undo"}]) == "illegal_phase"
    assert bad([{"t": "bomb", "r": 0, "c": 0}]) == "item_not_owned"
    assert bad([{"t": "shuffle"}]) == "item_not_owned"
    assert bad([{"t": "lock", "parts": []}]) == "no_lock"
    assert bad([{"t": "bugfix", "bug": 1, "correct": True}]) == "bad_bug"
    assert bad([{"t": "incoming", "entries": []}]) == "bad_move"
    assert bad([{"t": "fly"}]) == "bad_move"
    assert bad([{"t": "end", "reason": "nofit"}]) == "bad_end"
    assert bad([{"t": "end", "reason": "resign"}, {"t": "place", "i": 0, "r": 0, "c": 0}]) == "moves_after_end"
    assert bad({"t": "end"}) == "too_many_moves"
    with pytest.raises(E.Rejected):
        E.replay_pvp(5, "wizard", [])
    out = E.replay_pvp(5, "beginner", [{"t": "place", "i": 0, "r": 0, "c": 0}, {"t": "end", "reason": "resign"}])
    assert out["end_reason"] == "resign" and out["phase"] == "over"
