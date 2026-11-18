"""The server-side replay of Code Rescue (app/rescue_engine.py) against the real frontend rules.

The golden test runs tests/js_harness/play.mjs, which plays hundreds of random but legal games with the REAL
frontend/js/game.js + pieces.js and prints the move list, the puzzle records and the final state of each.
The Python replay has to reproduce every final state exactly (score, grid, tray, items, streaks...), so a rule
that drifts between the JavaScript and the Python fails here. Without ``node`` on PATH the golden test is skipped.
"""
import copy
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app import rescue_engine as E

from .ranked_bot import Bot, OfflineSource

HARNESS = Path(__file__).resolve().parent / "js_harness" / "play.mjs"
GAMES = 360


# --------------------------------------------------------------------------- unit: RNG and rounding


def test_mulberry32_matches_the_javascript_sequence():
    # first five outputs of mulberry(seed) from frontend/js/rng.js (== main.js mulberry), printed by node
    golden = {
        0: [0.26642920868471265, 0.0003297457005828619, 0.2232720274478197, 0.1462021479383111, 0.46732782293111086],
        1: [0.6270739405881613, 0.002735721180215478, 0.5274470399599522, 0.9810509674716741, 0.9683778982143849],
        12345: [0.9797282677609473, 0.3067522644996643, 0.484205421525985, 0.817934412509203, 0.5094283693470061],
        3000000000: [0.7568875285796821, 0.3733226382173598, 0.9749945921357721, 0.3353162407875061,
                     0.43787257629446685],
        4294967295: [0.8964226141106337, 0.189478256739676, 0.7156526781618595, 0.9440599093213677,
                     0.8452364315744489],
    }
    for seed, want in golden.items():
        rng = E.mulberry32(seed)
        assert [rng() for _ in want] == want


def test_js_round_is_math_round_not_bankers_rounding():
    assert [E.js_round(x) for x in (0.5, 1.5, 2.5, 112.5, 187.5, 337.5, 0.49999999999999994, 269.99999999999994)] \
        == [1, 2, 3, 113, 188, 338, 0, 270]
    assert E.js_round(0.4) == 0 and E.js_round(100.0) == 100


def test_points_follow_the_spec():
    g = E.RescueGame(1, "intermediate")
    assert g.reward(250, 0, 0)["points"] == 250
    assert g.reward(250, 2, 0) == {"points": 188, "clean": False, "penalty_level": 2}  # 187.5 rounds up
    g.streak = 4
    assert g.reward(100, 0, 0)["points"] == 200          # 5th clean lock: x2
    assert g.reward(700, 3, 0)["points"] == 350          # hint 3: x0.5, streak restarts at 1
    beginner = E.RescueGame(1, "beginner")
    assert beginner.free_hint_level(False) == 1 and beginner.free_hint_level(True) == 2
    assert beginner.reward(100, 1, 1)["clean"] and not beginner.reward(100, 2, 1)["clean"]


# --------------------------------------------------------------------------- golden test against game.js


@pytest.fixture(scope="module")
def traces():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not on PATH: cannot run the real frontend/js/game.js for the golden test")
    out = subprocess.run([node, str(HARNESS), str(GAMES), "1"], capture_output=True, text=True, timeout=180,
                         encoding="utf-8")
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout)


def test_python_replay_reproduces_game_js_final_states(traces):
    assert len(traces) >= 200
    for i, t in enumerate(traces):
        got = E.replay(t["seed"], t["level"], t["moves"], t["records"])
        assert got == t["final"], f"game {i} (seed {t['seed']}, {t['level']}, {t['strategy']}) diverged"


def test_golden_games_cover_the_rules(traces):
    """Guards the golden test itself: it must exercise every branch that is easy to get subtly wrong."""
    total: dict[str, int] = {}
    for t in traces:
        for k, v in t["stats"].items():
            total[k] = total.get(k, 0) + v
    print("golden coverage:", total)
    assert {t["level"] for t in traces} == set(E.LEVELS)
    assert len({t["seed"] > 2**31 for t in traces}) == 2          # seeds above 2^31 too
    assert total["locks"] >= 1000 and total["lockFail"] >= 100
    assert total["boss"] >= 5 and total["bossFail"] >= 1           # boss locks, also failed ones
    assert total["bossFirstWrong"] >= 1                             # a boss lock logged with ONE puzzle id
    assert total["bomb"] >= 50 and total["shuffle"] >= 30 and total["undo"] >= 1
    assert total["debugger"] >= 50 and total["hinted"] >= 200       # Debugger item and hint penalties
    assert total["bugfix"] >= 50 and total["bugfixWrong"] >= 5     # bug lines fixed / failed
    assert total["crash"] >= 20                                     # second mistake ends the run
    assert total["lastCommit"] >= 100 and total["lastCommitOk"] >= 50 and total["lastCommitFail"] >= 5
    assert total["nofit"] >= 100 and total["quit"] >= 5
    assert total["orphans"] >= 10                                   # served-but-unused puzzles are tolerated
    assert {t["final"]["end_reason"] for t in traces} == {"crash", "nofit", "quit"}
    assert {t["final"]["streak"] for t in traces} != {0}


def test_golden_replay_detects_a_changed_rule(traces, monkeypatch):
    """If the Python rules drift (here: the x1.2 streak bonus is forgotten), the golden comparison must notice."""
    monkeypatch.setattr(E, "streak_factor", lambda n: 2 if n >= 5 else 1.5 if n >= 3 else 1)
    mismatches = 0
    for t in traces:
        try:
            if E.replay(t["seed"], t["level"], t["moves"], t["records"]) != t["final"]:
                mismatches += 1
        except E.Rejected:
            mismatches += 1
    assert mismatches > 0


# --------------------------------------------------------------------------- tampering (no node needed)


def play(seed=7, level="intermediate", wrong=(), hint_every=0, max_moves=120, fix_bugs=False):
    source = OfflineSource(hint_every=hint_every)
    bot = Bot(seed, level, source, wrong=wrong)
    bot.fix_bugs = fix_bugs
    moves = bot.play(max_moves)
    return bot, moves, source.records


def reject(seed, level, moves, records):
    with pytest.raises(E.Rejected) as e:
        E.replay(seed, level, moves, records)
    return e.value.reason


def test_a_legal_bot_game_replays_to_its_own_state():
    bot, moves, records = play(wrong=(1,), hint_every=2)
    assert any(m["t"] == "lock" for m in moves)
    assert E.replay(7, "intermediate", moves, records) == bot.g.summary()


def test_moves_are_not_modified_by_replay():
    bot, moves, records = play()
    before = copy.deepcopy((moves, records))
    E.replay(7, "intermediate", moves, records)
    assert (moves, records) == before


def test_illegal_place_is_rejected():
    _, moves, records = play()
    first = next(i for i, m in enumerate(moves) if m["t"] == "place")
    bad = copy.deepcopy(moves)
    bad[first]["c"] = 7                       # the first piece cannot start in the last column
    bad.insert(first, {"t": "place", "i": 0, "r": 7, "c": 7})
    assert reject(7, "intermediate", bad, records) in ("illegal_place", "no_lock")
    # placing on an occupied cell
    twice = moves[:first + 1] + [dict(moves[first])] + moves[first + 1:]
    assert reject(7, "intermediate", twice, records) == "illegal_place"
    # tray slot that is already used up
    again = [dict(moves[first]), {"t": "place", "i": moves[first]["i"], "r": 7, "c": 0}] + moves[first + 1:]
    assert reject(7, "intermediate", again, records) == "illegal_place"


def test_malformed_moves_are_rejected():
    _, moves, records = play()
    for bad_move in ({"t": "place", "i": "0", "r": 0, "c": 0}, {"t": "place", "i": True, "r": 0, "c": 0},
                     {"t": "place", "i": 3, "r": 0, "c": 0}, {"t": "place", "i": 0, "r": -1, "c": 0},
                     {"t": "place", "i": 0, "r": 0}, {"t": "fly"}, {"t": "bomb", "r": 99, "c": 0}, [], "place"):
        assert reject(7, "intermediate", [bad_move], records) == "bad_move"
    assert reject(7, "intermediate", {"t": "end"}, records) == "too_many_moves"
    assert reject(7, "intermediate", [{"t": "place", "i": 0, "r": 0, "c": 0}] * (E.MAX_MOVES + 1), records) \
        == "too_many_moves"
    assert reject(7, "wizard", moves, records) == "bad_level"


def test_run_must_end_and_nothing_may_follow_the_end():
    _, moves, records = play(max_moves=10)
    assert moves[-1] == {"t": "end", "reason": "quit"}
    assert reject(7, "intermediate", moves[:-1], records) == "incomplete"
    assert reject(7, "intermediate", [], records) == "incomplete"
    assert reject(7, "intermediate", moves + [{"t": "place", "i": 0, "r": 0, "c": 0}], records) == "moves_after_end"
    assert reject(7, "intermediate", moves + [moves[-1]], records) == "moves_after_end"
    assert reject(7, "intermediate", moves[:-1] + [{"t": "end", "reason": "crash"}], records) == "bad_end"
    assert reject(7, "intermediate", moves[:-1] + [{"t": "end", "reason": "nofit"}], records) == "bad_end"


def test_placing_while_a_lock_is_pending_is_rejected():
    _, moves, records = play()
    k = next(i for i, m in enumerate(moves) if m["t"] == "lock")
    bad = moves[:k] + [{"t": "place", "i": 0, "r": 0, "c": 0}] + moves[k:]
    assert reject(7, "intermediate", bad, records) == "illegal_phase"
    # a lock move with no lock pending
    assert reject(7, "intermediate", [moves[k]] + moves, records) == "no_lock"


def test_puzzles_must_be_served_in_this_run_and_for_this_lock():
    _, moves, records = play()
    k = next(i for i, m in enumerate(moves) if m["t"] == "lock")

    def with_lock(**changes):
        bad = copy.deepcopy(moves)
        bad[k].update(changes)
        return bad

    assert reject(7, "intermediate", with_lock(puzzles=["never-served"]), records) == "puzzle_not_served"
    assert reject(7, "intermediate", with_lock(puzzles=[123]), records) == "puzzle_not_served"
    assert reject(7, "intermediate", with_lock(puzzles=[]), records) == "bad_move"
    assert reject(7, "intermediate", with_lock(puzzles=["a", "b", "c"]), records) == "bad_move"
    assert reject(7, "intermediate", with_lock(puzzles=moves[k]["puzzles"] * 2), records) == "bad_lock"  # extra puzzle
    assert reject(7, "intermediate", with_lock(**{"debugger": True}), records) == "debugger_mismatch"

    wrong_topic = copy.deepcopy(records)
    next(r for r in wrong_topic if r["id"] == moves[k]["puzzles"][0])["req_topic"] = "other-topic"
    assert reject(7, "intermediate", moves, wrong_topic) == "puzzle_mismatch"

    wrong_tier = copy.deepcopy(records)
    next(r for r in wrong_tier if r["id"] == moves[k]["puzzles"][0])["req_tier"] += 1
    assert reject(7, "intermediate", moves, wrong_tier) == "puzzle_mismatch"

    wrong_kind = copy.deepcopy(records)
    next(r for r in wrong_kind if r["id"] == moves[k]["puzzles"][0])["kind"] = "debug"
    assert reject(7, "intermediate", moves, wrong_kind) == "puzzle_mismatch"

    steered = copy.deepcopy(records)  # a template_id asked for to pick an easier puzzle
    next(r for r in steered if r["id"] == moves[k]["puzzles"][0])["req_template"] = "loops_easy"
    assert reject(7, "intermediate", moves, steered) == "puzzle_mismatch"

    unanswered = copy.deepcopy(records)
    next(r for r in unanswered if r["id"] == moves[k]["puzzles"][0])["correct"] = None
    assert reject(7, "intermediate", moves, unanswered) == "puzzle_not_answered"


def test_a_puzzle_can_only_be_used_once_and_in_serving_order():
    _, moves, records = play(max_moves=300)
    locks = [i for i, m in enumerate(moves) if m["t"] == "lock"]
    assert len(locks) >= 2
    reuse = copy.deepcopy(moves)
    reuse[locks[1]]["puzzles"] = list(moves[locks[0]]["puzzles"])
    assert reject(7, "intermediate", reuse, records) in ("puzzle_reused", "puzzle_mismatch")
    swapped = copy.deepcopy(moves)
    swapped[locks[0]]["puzzles"], swapped[locks[1]]["puzzles"] = moves[locks[1]]["puzzles"], moves[locks[0]]["puzzles"]
    assert reject(7, "intermediate", swapped, records) in ("puzzle_order", "puzzle_mismatch")


def test_a_wrong_answer_cannot_be_flipped_and_a_hint_cannot_be_hidden():
    bot, moves, records = play(wrong=(0,))
    first_lock = next(m for m in moves if m["t"] == "lock")
    honest = E.replay(7, "intermediate", moves, records)
    flipped = copy.deepcopy(records)
    next(r for r in flipped if r["id"] == first_lock["puzzles"][0])["correct"] = True
    try:  # the record, not the client, decides: the game changes (or no longer matches the move list)
        assert E.replay(7, "intermediate", moves, flipped) != honest
    except E.Rejected:
        pass
    assert honest["mistakes"] >= 1 and honest["status"] in ("warn", "crash")

    bot, moves, records = play(hint_every=1)
    with_hints = E.replay(7, "intermediate", moves, records)
    no_hints = copy.deepcopy(records)
    for r in no_hints:
        r["hint"] = 0
    assert E.replay(7, "intermediate", moves, no_hints)["score"] > with_hints["score"]


def test_items_not_owned_are_rejected():
    start = [{"t": "place", "i": 0, "r": 0, "c": 0}]
    assert reject(7, "intermediate", start + [{"t": "bomb", "r": 0, "c": 0}], []) == "item_not_owned"
    assert reject(7, "intermediate", start + [{"t": "shuffle"}], []) == "item_not_owned"
    assert reject(7, "intermediate", start + [{"t": "undo"}], []) == "illegal_phase"   # not locked
    assert reject(7, "intermediate", start + [{"t": "bugfix", "bug": 1, "puzzle": "x"}], []) == "bad_bug"
    assert reject(7, "intermediate", start + [{"t": "last_commit", "puzzle": "x"}], []) == "not_stuck"
    # undo while a lock is pending but no Undo item owned
    bot, moves, records = play()
    k = next(i for i, m in enumerate(moves) if m["t"] == "lock")
    assert reject(7, "intermediate", moves[:k] + [{"t": "undo"}] + moves[k:], records) == "item_not_owned"


def test_bug_fix_needs_the_right_bug_and_the_right_puzzle():
    bot, moves, records = play(wrong=(0,), fix_bugs=True, max_moves=60)
    fixes = [m for m in moves if m["t"] == "bugfix"]
    assert fixes, "the bot should have fixed the bug line it created"
    assert E.replay(7, "intermediate", moves, records)["bugs_fixed"] == 1
    k = moves.index(fixes[0])
    wrong_bug = copy.deepcopy(moves)
    wrong_bug[k]["bug"] = 99
    assert reject(7, "intermediate", wrong_bug, records) == "bad_bug"
    steered = copy.deepcopy(records)
    next(r for r in steered if r["id"] == fixes[0]["puzzle"])["req_template"] = "something_else"
    assert reject(7, "intermediate", moves, steered) == "puzzle_mismatch"


def test_second_mistake_crashes_and_the_run_must_say_so():
    bot, moves, records = play(wrong=(0, 1), max_moves=300)
    assert bot.g.end_reason == "crash" and moves[-1] == {"t": "end", "reason": "crash"}
    assert E.replay(7, "intermediate", moves, records)["status"] == "crash"
    assert E.replay(7, "intermediate", moves[:-1], records)["end_reason"] == "crash"   # end is optional after a crash
    assert reject(7, "intermediate", moves[:-1] + [{"t": "end", "reason": "quit"}], records) == "bad_end"
    assert reject(7, "intermediate", moves + [{"t": "place", "i": 0, "r": 0, "c": 0}], records) == "moves_after_end"


def test_same_seed_same_game_different_seed_different_game():
    a = E.RescueGame(5, "beginner")
    b = E.RescueGame(5, "beginner")
    c = E.RescueGame(6, "beginner")
    view = lambda g: [(p.shape, p.cells, p.topic) for p in g.tray]  # noqa: E731
    assert view(a) == view(b) and view(a) != view(c)
