"""The classroom leaderboard cap: ``rooms.score_ceiling`` must be an upper bound for every legal Code Rescue run.

Two sources of games are replayed against it:

* the golden games of ``js_harness/play.mjs``, played with the REAL frontend/js/game.js (skipped without ``node``), and
* long games played with ``rescue_engine.RescueGame`` (the Python port, kept identical by test_rescue_engine.py),
  with bomb / shuffle / undo / bug fixes / Last Commit, random wrong answers and hints.

For each game the facts a room would hold are rebuilt from the puzzles the game served: every answered puzzle is a
logged answer, a rescue lock puzzle has the lock's tier (boss: 3), Last Commit is tier 3, and a Debug puzzle is given
tier 1 (the lowest, so the cheapest per-answer ceiling: the worst case for the bound).
"""
import json
import random
import shutil
import subprocess
from pathlib import Path

import pytest

from app import rescue_engine as E
from app import rooms

HARNESS = Path(__file__).resolve().parent / "js_harness" / "play.mjs"
RATIOS: list[float] = []


# --------------------------------------------------------------------------- unit


def test_per_answer_ceiling_is_derived_from_the_rules():
    # lock: 2 x base + cells of t lines; boss: two answers share 2 x 700 + 64 cells; bug fix: 150 + 64; Bombs: +3
    assert rooms.PER_ANSWER_CEILING == {1: 217, 2: 519, 3: 927}
    assert rooms.score_ceiling({}) == 64
    assert rooms.score_ceiling({1: 2, 3: 1}) == 64 + 2 * 217 + 927
    assert rooms.score_ceiling({1: -4}) == 64


def test_counted_correct_ignores_wrong_and_repeated_answers():
    rows = [("a", 1, 1), ("a", 1, 1), ("a", 1, 1), ("b", 0, 2), ("c", 1, 3), ("d", 1, None), ("e", 1, 9)]
    assert rooms.counted_correct(rows) == {1: 1, 2: 0, 3: 3}   # unknown tiers count as 3; "a" only once
    many = [("p", 1, 2)] * 1000
    assert rooms.counted_correct(many) == {1: 0, 2: 3, 3: 0}  # 1 + 1000 // 500 honest repeats at most


# --------------------------------------------------------------------------- facts of one game


def ceiling_of(records):
    """records: ``(puzzle_id, correct, tier)`` of the answered puzzles of one game."""
    return rooms.score_ceiling(rooms.counted_correct(records))


def check(score, records, label):
    ceiling = ceiling_of(records)
    RATIOS.append(score / ceiling)
    assert score <= ceiling, f"{label}: score {score} above the ceiling {ceiling}"


# --------------------------------------------------------------------------- golden games (game.js)


def golden(games, seed0):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not on PATH: cannot run the real frontend/js/game.js")
    out = subprocess.run([node, str(HARNESS), str(games), str(seed0)], capture_output=True, text=True, timeout=240,
                         encoding="utf-8")
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout)


def facts_of_trace(t):
    tiers = {"rescue": None, "debug": 1, "last_commit": 3}
    return [(r["id"], bool(r["correct"]), r["req_tier"] if tiers[r["kind"]] is None else tiers[r["kind"]])
            for r in t["records"] if r["correct"] is not None]


@pytest.mark.parametrize("games,seed0", [(360, 1), (400, 70001)])
def test_ceiling_bounds_every_game_played_with_the_real_game_js(games, seed0):
    traces = golden(games, seed0)
    assert len(traces) >= 200
    for t in traces:
        check(t["final"]["score"], facts_of_trace(t), f"seed {t['seed']} {t['level']} {t['strategy']}")
    # the golden games must exercise the paths that add points
    assert sum(t["stats"]["locks"] for t in traces) >= 1000 and sum(t["stats"]["bugfix"] for t in traces) >= 50
    assert sum(t["stats"]["bomb"] for t in traces) >= 50 and sum(t["stats"]["lastCommitOk"] for t in traces) >= 50


# --------------------------------------------------------------------------- long games (rescue_engine)


def best_move(g, rng):
    """The strongest-looking legal placement: completes the most lines, hugs walls and other pieces (bitmasks)."""
    occ, fill, colfill = [0] * 8, [0] * 8, [0] * 8   # occupied cells, non-bug cells per row / per column
    for r in range(8):
        for c in range(8):
            x = g.grid[r][c]
            if x:
                occ[r] |= 1 << c
                if not x["bug"]:
                    fill[r] |= 1 << c
                    colfill[c] |= 1 << r
    best, best_score = None, -1e9
    for i, p in enumerate(g.tray):
        if p is None:
            continue
        h = max(dr for dr, _ in p.cells) + 1
        w = max(dc for _, dc in p.cells) + 1
        rowbits: dict[int, int] = {}
        colbits: dict[int, int] = {}
        for dr, dc in p.cells:
            rowbits[dr] = rowbits.get(dr, 0) | (1 << dc)
            colbits[dc] = colbits.get(dc, 0) | (1 << dr)
        for r in range(8 - h + 1):
            for c in range(8 - w + 1):
                if any(occ[r + dr] & (b << c) for dr, b in rowbits.items()):
                    continue
                lines = sum(1 for dr, b in rowbits.items() if (fill[r + dr] | (b << c)) == 255)
                lines += sum(1 for dc, b in colbits.items() if (colfill[c + dc] | (b << r)) == 255)
                own = {(r + dr, c + dc) for dr, dc in p.cells}
                touch = sum(1 for rr, cc in own for a, b2 in ((rr - 1, cc), (rr + 1, cc), (rr, cc - 1), (rr, cc + 1))
                            if not (0 <= a < 8 and 0 <= b2 < 8) or ((a, b2) not in own and (occ[a] >> b2) & 1))
                score = 15 * lines + 0.8 * touch + rng.random()
                if score > best_score:
                    best, best_score = (i, r, c), score
    return best


def random_move(g, rng):
    moves = [(i, r, c) for i, p in enumerate(g.tray) if p is not None
             for r in range(E.SIZE) for c in range(E.SIZE) if g.can_place(p, r, c)]
    return rng.choice(moves)


def play_long_game(seed, level, max_steps):
    """One legal game with the engine: skilful placement (completes lines, snug), random answers and hints."""
    rng = random.Random(seed)
    g = E.RescueGame(seed, level)
    p_correct = rng.choice([0.6, 0.9, 0.97, 0.995, 1.0])
    p_hint = rng.choice([0.0, 0.05, 0.3])
    greedy = rng.choice([0.3, 0.8, 1.0])        # how often the player picks the strongest placement
    facts, n = [], 0

    def serve(kind, tier):
        nonlocal n
        n += 1
        hint = rng.choice([1, 2, 3]) if rng.random() < p_hint else 0
        ok = rng.random() < p_correct
        facts.append((f"s{seed}-{n}", ok, {"rescue": tier, "debug": 1, "last_commit": 3}[kind]))
        return ok, hint

    def stuck_choice():
        if rng.random() < 0.1:
            g.end_game("nofit")
            return
        g.last_commit_used = True
        topic = g.last_commit_topic()
        ok, _ = serve("last_commit", 3)
        g.stuck = False
        if not ok:
            g.fail_last_commit(topic, "t")
        else:
            g.clear_fullest_rows()
            g.settle()
            if g.stuck:
                stuck_choice()

    def settle():
        g.settle()
        if g.stuck and g.phase != "over":
            stuck_choice()

    steps = 0
    while g.phase != "over" and steps < max_steps:
        steps += 1
        if g.phase == "locked":
            if g.items["undo"] > 0 and g.snapshot and rng.random() < 0.5:
                g.undo()
                continue
            lk = g.lock
            use_dbg = g.items["debugger"] > 0
            if use_dbg:
                g.items["debugger"] -= 1
            free = g.free_hint_level(use_dbg)
            base = g.base_for(lk)
            tier = 3 if lk["boss"] else lk["tier"]
            max_hint, failed = 0, False
            for _ in range(2 if lk["boss"] else 1):
                ok, hint = serve("rescue", tier)
                max_hint = max(max_hint, hint)
                if not ok:
                    failed = True
                    break
            if not failed:
                g.apply_correct(base, max_hint, free, lk["count"])
                g.finish_lock()
                settle()
            else:
                topic = lk["topic"]
                if g.apply_wrong(topic, "t") == "bug":
                    settle()
            continue
        if g.items["bomb"] > 0 and rng.random() < 0.4:
            if g.bomb(rng.randrange(E.SIZE), rng.randrange(E.SIZE)) is not None:
                settle()
                continue
        if g.items["shuffle"] > 0 and rng.random() < 0.3 and g.shuffle():
            settle()
            continue
        if g.bug_lines and rng.random() < 0.35:
            bl = rng.choice(g.bug_lines)
            ok, _ = serve("debug", 1)
            if ok:
                g.fix_bug(bl["id"])
                settle()
            else:
                g.apply_debug_wrong(bl["topic"], bl["template_id"])
            continue
        i, r, c = best_move(g, rng) if rng.random() < greedy else random_move(g, rng)
        res = g.place(i, r, c)
        assert res is not None
        if res["lock"]:
            g.phase = "locked"
        else:
            settle()
    return g.score, facts, steps


def test_ceiling_bounds_long_random_games_played_with_the_engine():
    long_games = 0
    best = 0.0
    for k in range(240):
        level = E.LEVELS[k % 3]
        long_run = k % 4 == 0
        score, facts, steps = play_long_game(910_000 + k, level, 2500 if long_run else 500)
        check(score, facts, f"engine game {k} ({level})")
        best = max(best, score / ceiling_of(facts))
        long_games += steps >= 400
    print(f"engine games: 240, with 400+ steps: {long_games}, best score/ceiling: {best:.3f}")
    assert long_games >= 10


def test_ratio_report():
    if not RATIOS:
        pytest.skip("run together with the game tests")
    print(f"games checked: {len(RATIOS)}, max score/ceiling: {max(RATIOS):.3f}")
    assert max(RATIOS) <= 1


def test_the_bound_test_notices_a_ceiling_that_is_too_low(monkeypatch):
    """Guards the test itself: a smaller per-answer ceiling (a tier-1 answer worth 150, not 217) is caught."""
    monkeypatch.setattr(rooms, "PER_ANSWER_CEILING", {1: 150, 2: 400, 3: 700})
    broken = 0
    for k in range(60):
        score, facts, _ = play_long_game(910_000 + k, E.LEVELS[k % 3], 500)
        broken += score > ceiling_of(facts)
    assert broken >= 1
