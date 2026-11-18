"""The bot of a PvP bot match (docs/pvp.md section 5): the decisions only. ``app/pvp.py`` runs them with the same
code path as a human player (same engine, same puzzle server, same limits); nothing here touches the network.

It places pieces with a simple heuristic (complete rows and columns, stay snug against other blocks and walls,
avoid closing holes, keep away from the top rows that incoming bug lines push blocks out of), answers puzzles after
a "thinking" delay of 4-9 s (longer for harder tiers) with a fixed accuracy per level, never opens a hint, and
uses Bomb / Shuffle / Debug puzzles when they help.
"""
from __future__ import annotations

import random
from typing import Optional

from . import rescue_engine as E

ACCURACY = {"beginner": 0.70, "intermediate": 0.80, "advanced": 0.88}
THINK_S = {1: (4.0, 6.0), 2: (5.0, 7.5), 3: (6.0, 9.0)}   # (min, max) seconds to answer one puzzle, by tier
PLACE_S = (0.8, 1.7)                                       # pause between two placements
FIRST_MOVE_S = 1.2


def _neighbours(r: int, c: int):
    return ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1))


def _blocked(occ: list[list[bool]], r: int, c: int) -> bool:
    return not (0 <= r < E.SIZE and 0 <= c < E.SIZE) or occ[r][c]


def _full_lines(g: E.RescueGame, occ: list[list[bool]]) -> int:
    """Rows and columns that are full of normal (non-bug) blocks, i.e. locks."""
    n = 0
    for r in range(E.SIZE):
        if all(occ[r][c] and not (g.grid[r][c] and g.grid[r][c]["bug"]) for c in range(E.SIZE)):
            n += 1
    for c in range(E.SIZE):
        if all(occ[r][c] and not (g.grid[r][c] and g.grid[r][c]["bug"]) for r in range(E.SIZE)):
            n += 1
    return n


def best_placement(g: E.RescueGame, rng: random.Random) -> Optional[tuple[float, int, int, int]]:
    """``(score, tray index, r, c)`` of the most attractive legal placement, or None when nothing fits."""
    base = [[bool(g.grid[r][c]) for c in range(E.SIZE)] for r in range(E.SIZE)]
    best: Optional[tuple[float, int, int, int]] = None
    for i, piece in enumerate(g.tray):
        if piece is None:
            continue
        for r in range(E.SIZE):
            for c in range(E.SIZE):
                if not g.can_place(piece, r, c):
                    continue
                cells = [(r + dr, c + dc) for dr, dc in piece.cells]
                for rr, cc in cells:
                    base[rr][cc] = True
                lines = _full_lines(g, base)
                own = set(cells)
                contact = 0
                touched_rows = {rr for rr, _ in cells}
                touched_cols = {cc for _, cc in cells}
                for rr, cc in cells:
                    for nr, nc in _neighbours(rr, cc):
                        if (nr, nc) not in own and _blocked(base, nr, nc):
                            contact += 1
                holes = 0
                seen = set()
                for rr, cc in cells:
                    for nr, nc in _neighbours(rr, cc):
                        if (nr, nc) in own or (nr, nc) in seen or _blocked(base, nr, nc):
                            continue
                        seen.add((nr, nc))
                        if all(_blocked(base, ar, ac) for ar, ac in _neighbours(nr, nc)):
                            holes += 1
                fullness = sum(sum(base[x]) for x in touched_rows) + sum(
                    sum(base[x][y] for x in range(E.SIZE)) for y in touched_cols)
                low = sum(rr for rr, _ in cells) / len(cells)       # no gravity: the top rows are the danger zone
                score = 9 * lines + 0.7 * contact - 4 * holes + 0.12 * fullness + 0.5 * low + rng.random() * 0.4
                if best is None or score > best[0]:
                    best = (score, i, r, c)
                for rr, cc in cells:
                    base[rr][cc] = False
    return best


def bomb_target(g: E.RescueGame) -> Optional[tuple[int, int]]:
    """The 3x3 centre that clears the most normal blocks, when that is worth a Bomb (at least 5 blocks)."""
    if g.items["bomb"] < 1:
        return None
    best, spot = 0, None
    for r in range(E.SIZE):
        for c in range(E.SIZE):
            n = 0
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    rr, cc = r + dr, c + dc
                    if 0 <= rr < E.SIZE and 0 <= cc < E.SIZE and g.grid[rr][cc] and not g.grid[rr][cc]["bug"]:
                        n += 1
            if n > best:
                best, spot = n, (r, c)
    return spot if best >= 5 else None


def filled(g: E.RescueGame) -> int:
    return sum(1 for row in g.grid for x in row if x)


class BotBrain:
    """The bot's timing and dice. All randomness comes from one seeded generator (reproducible in tests)."""

    def __init__(self, seed: int, level: str):
        self.rng = random.Random(f"{seed}:bot")
        self.accuracy = ACCURACY[level]
        self.next_at = 0.0               # match clock time of the next decision
        self.think_until: Optional[float] = None
        self.task: Optional[str] = None  # what it is thinking about: "lock" or "bug:<id>"

    def think_time(self, tier: int, parts: int = 1) -> float:
        lo, hi = THINK_S[min(max(tier, 1), 3)]
        return self.rng.uniform(lo, hi) * parts

    def place_pause(self) -> float:
        return self.rng.uniform(*PLACE_S)

    def answers_right(self) -> bool:
        return self.rng.random() < self.accuracy

    def wants_bug_fix(self, g: E.RescueGame) -> bool:
        if not g.bug_lines:
            return False
        crowded = filled(g) >= 30
        return crowded or len(g.bug_lines) >= 2 or self.rng.random() < 0.35
