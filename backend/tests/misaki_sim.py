"""Bot-vs-bot simulation of Misaki's ladder on the real match code (``app.pvp.Match``) with a virtual clock.

Two Misakis of chosen ladder levels play a full PvP match: the same engine, the same puzzle server, the same overtime
rule and the same bot code path as a live match; only the clock is virtual (no sleeping), so a whole match takes a
second or two. Used by ``test_misaki.py`` (strength check) and, as a script, for the honest numbers the team may quote:

    cd backend && .venv\\Scripts\\python -m tests.misaki_sim 60
"""
from __future__ import annotations

import sys
import time
from typing import Optional

from app import pvp, pvp_bot

TICK_S = 0.1
LIMIT_S = 1200.0           # a match cannot outlast the overtime (it always ends long before this)


def run_match(levels: tuple[int, int], seed: int, level: str = "intermediate", training: bool = False):
    """Play one match between Misaki ``levels[0]`` (seat 0) and ``levels[1]`` (seat 1) on the seed; returns the finished
    ``Match`` (``winner``: seat index or None, ``reason``, ``elapsed_s`` = virtual match time)."""
    clock = [0.0]
    real_now = pvp.now
    pvp.now = lambda: clock[0]
    try:
        m = pvp.Match(level, "bot")
        m.seed = seed
        for idx, lv in enumerate(levels):
            p = pvp.Player(level, pvp_bot.NAME, None, "bot", bot=True)
            p.misaki, p.training = lv, training
            m.seat(p, idx)
        m.start()
        while m.phase == "playing" and clock[0] < LIMIT_S:
            clock[0] += TICK_S
            m.tick()
        m.elapsed_s = clock[0]
        return m
    finally:
        pvp.now = real_now


def head_to_head(strong: int, weak: int, games: int, seed0: int = 1000) -> dict:
    """``games`` matches of Misaki ``strong`` against Misaki ``weak`` (seats alternate). Returns the win count of
    ``strong``, the draws and the average decision time of the search (ms) and match length (s)."""
    wins = draws = 0
    search_s = decisions = 0
    length = 0.0
    for k in range(games):
        seats = (strong, weak) if k % 2 == 0 else (weak, strong)
        m = run_match(seats, seed0 + k)
        length += m.elapsed_s
        for p in m.players():
            search_s += p.brain.search_s
            decisions += p.brain.decisions
        if m.winner is None:
            draws += 1
        elif seats[m.winner] == strong:
            wins += 1
    return {"strong": strong, "weak": weak, "games": games, "wins": wins, "draws": draws,
            "rate": wins / games, "avg_decision_ms": 1000 * search_s / max(1, decisions),
            "avg_match_s": length / games}


def main(argv: Optional[list[str]] = None) -> None:
    games = int((argv or sys.argv[1:] or ["40"])[0])
    for strong in range(2, pvp_bot.MAX_LEVEL + 1):
        t = time.perf_counter()
        r = head_to_head(strong, strong - 1, games)
        print(f"Misaki {strong} vs {strong - 1}: {r['wins']}/{r['games']} = {r['rate']:.0%}  (draws {r['draws']}, "
              f"search {r['avg_decision_ms']:.1f} ms/decision, match {r['avg_match_s']:.0f} s, "
              f"{time.perf_counter() - t:.0f} s wall)", flush=True)


if __name__ == "__main__":
    main()
