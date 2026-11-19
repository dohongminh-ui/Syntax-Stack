"""Misaki, the AI opponent of a PvP bot match (docs/pvp.md section 5): the decisions only. ``app/pvp.py`` runs them with
the same code path as a human player (same engine, same puzzle server, same limits); nothing here touches the network.

What this is, and is not (keep it true in every sentence the product says about her):

* She is a **search-based game AI**. On her turn she looks at every order of her tray pieces and every legal position,
  keeps the best ``beam`` candidates after each piece (beam search), simulates the board with the rules engine's own
  rules (a completed row or column is a lock; incoming bug lines land after the first placement that makes no lock) and
  scores the result with a hand-written evaluation function. She plays the first placement of the best plan and
  re-plans after every placement.
* She is **not trained and does not learn**: no data, no model, no memory between matches. The evaluation weights below
  were tuned by hand against simulated matches (``tests/misaki_sim.py``), nothing more.
* She does **not read the code**: whether she answers a puzzle right is a dice roll at the accuracy of her level
  (``LADDER``), after a "thinking" pause; she never opens a hint.

The search runs on 64-bit integers (bit ``r * 8 + c`` is the cell in row ``r``, column ``c``; row 0 is the top) so that a
decision stays well under 50 ms even at beam 32. The rules themselves are never re-implemented here: the board rules the
search relies on (``find_lock``: full rows and columns of normal blocks; ``land_pending``: every cell moves up k rows,
the bottom k rows become bug rows, a non-empty cell above row 0 is a top-out) are mirrored bit-for-bit and checked
against ``rescue_engine.RescueGame`` in ``tests/test_misaki.py``.
"""
from __future__ import annotations

import random
import time
from typing import NamedTuple, Optional

from . import rescue_engine as E

SIZE = E.SIZE
_FULL = (1 << 64) - 1

# --------------------------------------------------------------------------- the ladder (docs/pvp.md section 5.2)

LADDER: dict[int, dict] = {
    1: {"name": "Tập sự", "beam": 1, "think": (2.0, 3.0), "accuracy": 0.60, "bomb": False, "shuffle": False},
    2: {"name": "Khá", "beam": 4, "think": (1.4, 2.2), "accuracy": 0.72, "bomb": True, "shuffle": False},
    3: {"name": "Giỏi", "beam": 12, "think": (0.9, 1.5), "accuracy": 0.84, "bomb": True, "shuffle": True},
    4: {"name": "Bậc thầy", "beam": 32, "think": (0.5, 1.0), "accuracy": 0.93, "bomb": True, "shuffle": True},
}
MAX_LEVEL = 4
NAME = "Misaki"
TRAINING_DELAY_SCALE = 1.5               # training mode: she is one level lower and thinks 1.5x as long
# (min, max) seconds to answer one puzzle, by tier; scaled down at higher levels and kept inside 3-8 s
PUZZLE_S = {1: (3.0, 5.0), 2: (4.0, 6.5), 3: (5.5, 8.0)}
PUZZLE_SPEED = {1: 1.0, 2: 0.95, 3: 0.9, 4: 0.85}
# the old "simple bot" of a match without a chosen level: the ladder level that matches the game level
LEGACY_LEVEL = {"beginner": 1, "intermediate": 2, "advanced": 3}


def title(level: int) -> str:
    return f"{NAME} · {LADDER[level]['name']}"


def effective_level(chosen: int, training: bool) -> int:
    """The ladder level she really plays at: one lower than chosen in training mode (never below 1)."""
    return max(1, chosen - 1) if training else chosen


# --------------------------------------------------------------------------- bitboard helpers

ROW_MASK = tuple(0xFF << (8 * r) for r in range(SIZE))
COL_MASK = tuple(sum(1 << (8 * r + c) for r in range(SIZE)) for c in range(SIZE))
TOP = tuple((1 << (8 * k)) - 1 for k in range(SIZE + 1))              # TOP[k]: the k top rows
BOTTOM = tuple(_FULL ^ TOP[SIZE - k] for k in range(SIZE + 1))        # BOTTOM[k]: the k bottom rows
_NOT_COL0 = _FULL ^ COL_MASK[0]
_NOT_COL7 = _FULL ^ COL_MASK[SIZE - 1]
_POP8 = tuple(bin(i).count("1") for i in range(256))

_PLACE_CACHE: dict[tuple, tuple] = {}


def placements(cells: tuple) -> tuple:
    """Every legal-on-an-empty-board anchor of a piece: ``(r, c, mask, row masks touched, column masks touched)``."""
    got = _PLACE_CACHE.get(cells)
    if got is None:
        h = max(r for r, _ in cells) + 1
        w = max(c for _, c in cells) + 1
        out = []
        for r in range(SIZE - h + 1):
            for c in range(SIZE - w + 1):
                m = 0
                for dr, dc in cells:
                    m |= 1 << ((r + dr) * SIZE + c + dc)
                rows = tuple(sorted({ROW_MASK[r + dr] for dr, _ in cells}))
                cols = tuple(sorted({COL_MASK[c + dc] for _, dc in cells}))
                out.append((r, c, m, rows, cols))
        got = _PLACE_CACHE[cells] = tuple(out)
    return got


def board_bits(grid: list) -> tuple[int, int]:
    """``(occupied, normal)`` bitboards of an engine grid: every block, and the non-bug blocks (those that can lock)."""
    occ = normal = 0
    for r in range(SIZE):
        row = grid[r]
        for c in range(SIZE):
            x = row[c]
            if x:
                b = 1 << (r * SIZE + c)
                occ |= b
                if not x["bug"]:
                    normal |= b
    return occ, normal


def transpose(x: int) -> int:
    """Flip an 8x8 bit matrix along its main diagonal (rows become columns)."""
    t = 0x0F0F0F0F00000000 & (x ^ (x << 28))
    x ^= t ^ (t >> 28)
    t = 0x3333000033330000 & (x ^ (x << 14))
    x ^= t ^ (t >> 14)
    t = 0x5500550055005500 & (x ^ (x << 7))
    x ^= t ^ (t >> 7)
    return x


def cells_of(mask: int) -> list[tuple[int, int]]:
    return [(b // SIZE, b % SIZE) for b in range(64) if mask >> b & 1]


def lock_lines(normal: int) -> tuple[int, int]:
    """``(lines, cleared mask)``: the complete rows and columns of normal blocks (``find_lock``), and their cells."""
    lines = clear = 0
    for rm in ROW_MASK:
        if normal & rm == rm:
            lines += 1
            clear |= rm
    for cm in COL_MASK:
        if normal & cm == cm:
            lines += 1
            clear |= cm
    return lines, clear


def land(occ: int, normal: int, k: int) -> tuple[int, int, int]:
    """``land_pending`` for k rows: the new ``(occ, normal, lost)``; ``lost`` blocks were pushed off the top."""
    k = min(k, SIZE)
    if k == 0:
        return occ, normal, 0
    return (occ >> (SIZE * k)) | BOTTOM[k], normal >> (SIZE * k), (occ & TOP[k]).bit_count()


# --------------------------------------------------------------------------- the evaluation function

# Weights of the board evaluation (hand-tuned, see tests/misaki_sim.py). Higher is better for her.
LINE_REWARD = (0.0, 14.0, 32.0, 54.0, 80.0)   # a lock she expects to clear, by lines, shaped like PVP_SEND
W_HOLE = 2.0           # an empty cell with a block above it in its column
W_POCKET = 6.0         # an empty cell closed in on all four sides (only a single block fits: "covered")
W_HEIGHT = 0.5         # aggregate column height (counted from the bottom: landing bug rows push blocks up)
W_BUMP = 1.5           # differences between the heights of neighbouring columns
W_DANGER = 12.0        # a block in the top `pending` rows: it would be pushed off the board (= W_LOST)
W_PROGRESS = 4.2       # rows and columns on their way to a lock (squared fill, bug-free lines only)
W_MOBILITY = 60.0      # how many of the 13 shapes (weighted by how often they are dealt) still fit somewhere
W_UNPLACED = 30.0      # a tray piece of the plan that fits nowhere any more
W_LOST = 12.0          # a block pushed off the top by landing bug rows (destroyed: wasted space and a lost lock)
TOPPED_OUT = -1e6

_PROGRESS = tuple((n / SIZE) ** 2 for n in range(SIZE + 1))
_PROGRESS_BYTE = tuple(_PROGRESS[_POP8[i]] for i in range(256))


def board_score(occ: int, normal: int, pending: int) -> float:
    """The evaluation of a board (without the lock reward and without mobility)."""
    # "shadow": cells that have a block somewhere above them in their column
    s = (occ << 8) & _FULL
    s |= (s << 8) & _FULL
    s |= (s << 16) & _FULL
    s |= (s << 32) & _FULL
    holes = (s & ~occ).bit_count()
    cover = s | occ                                   # column heights, as cells
    height = cover.bit_count()
    bump = ((cover ^ (cover >> 1)) & _NOT_COL7).bit_count()
    up = ((occ << 8) & _FULL) | TOP[1]
    down = (occ >> 8) | BOTTOM[1]
    left = ((occ << 1) & _NOT_COL0) | COL_MASK[0]
    right = ((occ >> 1) & _NOT_COL7) | COL_MASK[SIZE - 1]
    pockets = (_FULL ^ occ) & up & down & left & right
    progress = 0.0
    for nb, ob in zip(normal.to_bytes(8, "little"), occ.to_bytes(8, "little")):
        if nb == ob:
            progress += _PROGRESS_BYTE[nb]
    for nb, ob in zip(transpose(normal).to_bytes(8, "little"), transpose(occ).to_bytes(8, "little")):
        if nb == ob:
            progress += _PROGRESS_BYTE[nb]
    score = (W_PROGRESS * progress - W_HOLE * holes - W_POCKET * pockets.bit_count() - W_HEIGHT * height
             - W_BUMP * bump)
    if pending:
        score -= W_DANGER * (occ & TOP[min(pending, SIZE)]).bit_count()
    return score


def _shape_table() -> tuple:
    table = []
    for key, (cells, weight) in E._BASE.items():
        orient, cur = [], E._normalize(cells)
        for _ in range(4):
            if cur not in orient:
                orient.append(cur)
            cur = E._rotate(cur)
        table.append((weight, tuple(tuple(m for _, _, m, _, _ in placements(o)) for o in orient)))
    return tuple(table)


_SHAPES = _shape_table()
_SHAPE_TOTAL = sum(w for w, _ in _SHAPES)


def mobility(occ: int) -> float:
    """0..1: the share of the next pieces (the 13 shapes, weighted as they are dealt, every rotation) that still fit."""
    total = 0.0
    for weight, orients in _SHAPES:
        fit = 0
        for masks in orients:
            for m in masks:
                if not m & occ:
                    fit += 1
                    break
        total += weight * fit / len(orients)
    return total / _SHAPE_TOTAL


# --------------------------------------------------------------------------- the search


class Plan(NamedTuple):
    score: float
    i: int                 # tray index of the first placement
    r: int
    c: int
    lines: int             # lines the first placement completes
    topped: bool           # every plan tops her out (the first one found is returned)
    steps: int             # pieces in the plan


class _State(NamedTuple):
    occ: int
    normal: int
    pend: int
    used: int
    first: Optional[tuple]
    first_lines: int
    reward: float
    steps: int


MOBILITY_POOL = 4         # candidates that get the (more expensive) mobility term even at beam 1


def search(occ: int, normal: int, tray: list, pending: int, beam: int, accuracy: float = 0.9) -> Optional[Plan]:
    """Beam search over the tray: the best plan's first placement, or None when no piece fits.

    Every order of the pieces and every legal position is tried, the best ``beam`` boards are kept after each piece
    (beam 1: greedy, one piece), a completed row or column is assumed to be cleared (its reward is weighted by
    ``accuracy``: how often she expects to answer the lock right) and the first placement that makes no lock lands the
    ``pending`` bug rows, exactly as the engine does."""
    pieces = [(i, p.cells) for i, p in enumerate(tray) if p is not None]
    if not pieces:
        return None
    depth = len(pieces) if beam > 1 else 1
    frontier = [_State(occ, normal, pending, 0, None, 0, 0.0, 0)]
    finals: list[tuple[float, _State]] = []
    fallback: Optional[_State] = None
    for stage in range(depth):
        nxt: dict[tuple, tuple[float, _State]] = {}
        for st in frontier:
            expanded = False
            for i, cells in pieces:
                bit = 1 << i
                if st.used & bit:
                    continue
                used = st.used | bit
                for r, c, m, rowm, colm in placements(cells):
                    if m & st.occ:
                        continue
                    o2, n2 = st.occ | m, st.normal | m
                    clear = 0
                    lines = 0
                    for rm in rowm:
                        if n2 & rm == rm:
                            clear |= rm
                            lines += 1
                    for cm in colm:
                        if n2 & cm == cm:
                            clear |= cm
                            lines += 1
                    p2, reward = st.pend, st.reward
                    if lines:
                        o2 &= ~clear
                        n2 &= ~clear
                        reward += LINE_REWARD[min(lines, 4)] * accuracy
                    elif p2:
                        o2, n2, lost = land(o2, n2, p2)
                        reward -= W_LOST * lost             # blocks pushed off the top are gone (not fatal)
                        p2 = 0
                    expanded = True
                    key = (o2, n2, used, p2)
                    old = nxt.get(key)
                    if old is not None and old[1].reward >= reward:
                        continue
                    first = st.first or (i, r, c)
                    fl = st.first_lines if st.first else lines
                    sc = reward + board_score(o2, n2, p2)
                    nxt[key] = (sc, _State(o2, n2, p2, used, first, fl, reward, st.steps + 1))
            if not expanded and st.first:                   # the rest of the tray fits nowhere: the plan ends here
                left = len(pieces) - bin(st.used).count("1")
                finals.append((st.reward + board_score(st.occ, st.normal, st.pend) - W_UNPLACED * left, st))
        keep = beam if stage < depth - 1 else max(beam, MOBILITY_POOL)
        frontier = [v[1] for v in sorted(nxt.values(), key=lambda v: -v[0])[:keep]]
        scores = {id(v[1]): v[0] for v in nxt.values()}
        if stage == depth - 1:
            finals.extend((scores[id(s)], s) for s in frontier)
        if not frontier:
            break
    best: Optional[tuple[float, _State]] = None
    for sc, st in finals:
        total = sc + W_MOBILITY * mobility(st.occ)
        if best is None or total > best[0]:
            best = (total, st)
    if best is None:                                         # every placement tops her out (or nothing fits)
        if fallback is None or fallback.first is None:
            return None
        i, r, c = fallback.first
        return Plan(TOPPED_OUT, i, r, c, 0, True, 1)
    st = best[1]
    i, r, c = st.first
    return Plan(best[0], i, r, c, st.first_lines, False, st.steps)


# --------------------------------------------------------------------------- items

BOMB_MIN_CELLS = 4        # a Bomb must clear at least this many blocks
BOMB_MIN_GAIN = 28.0      # ... and improve the board's evaluation by at least this much
CROWDED_CELLS = 34        # blocks on the board from which a Bomb is considered even without a bad plan
SHUFFLE_BELOW = -60.0     # a plan scoring below this makes her shuffle (when she owns one and may)


def bomb_options(occ: int, normal: int, pending: int) -> list[tuple[float, int, int, int]]:
    """``(evaluation after the Bomb, r, c, cleared)`` for every centre that clears at least ``BOMB_MIN_CELLS`` blocks."""
    out = []
    for r in range(SIZE):
        for c in range(SIZE):
            m = 0
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    rr, cc = r + dr, c + dc
                    if 0 <= rr < SIZE and 0 <= cc < SIZE:
                        m |= 1 << (rr * SIZE + cc)
            hit = m & normal
            n = hit.bit_count()
            if n >= BOMB_MIN_CELLS:
                out.append((board_score(occ & ~hit, normal & ~hit, pending), r, c, n))
    return out


def filled(g: E.RescueGame) -> int:
    return sum(1 for row in g.grid for x in row if x)


# --------------------------------------------------------------------------- the player


class BotBrain:
    """Misaki's timing, dice and decisions for one match. All randomness comes from one seeded generator (reproducible)."""

    def __init__(self, seed: int, level: int, training: bool = False, stream: str = "bot"):
        self.level = level
        spec = LADDER[level]
        self.beam: int = spec["beam"]
        self.accuracy: float = spec["accuracy"]
        self.uses_bomb: bool = spec["bomb"]
        self.uses_shuffle: bool = spec["shuffle"]
        self.delay = tuple(x * (TRAINING_DELAY_SCALE if training else 1.0) for x in spec["think"])
        self.rng = random.Random(f"{seed}:{stream}")
        self.next_at = 0.0                # match clock time of the next decision
        self.think_until: Optional[float] = None
        self.task: Optional[int] = None   # the bug line she is thinking about fixing
        self.decisions = 0                # statistics: searches made
        self.search_s = 0.0               # ... and the time they took

    # ---- timing and dice ----
    def think_time(self, tier: int, parts: int = 1) -> float:
        lo, hi = PUZZLE_S[min(max(tier, 1), 3)]
        one = self.rng.uniform(lo, hi) * PUZZLE_SPEED[self.level]
        return min(8.0, max(3.0, one)) * parts

    def place_delay(self) -> float:
        return self.rng.uniform(*self.delay)

    def answers_right(self) -> bool:
        return self.rng.random() < self.accuracy

    def answers(self, need: int) -> list[bool]:
        """The outcomes of the puzzles of one lock, in serving order; the first wrong one ends the list."""
        out: list[bool] = []
        for _ in range(need):
            ok = self.answers_right()
            out.append(ok)
            if not ok:
                break
        return out

    def wants_bug_fix(self, g: E.RescueGame, in_danger: bool) -> bool:
        if not g.bug_lines:
            return False
        crowded = filled(g) >= 30
        return in_danger or crowded or len(g.bug_lines) >= 2 or self.rng.random() < 0.35

    @staticmethod
    def pick_bug(g: E.RescueGame) -> int:
        """The bug line closest to the top (the first to be pushed off the board)."""
        return min(g.bug_lines, key=lambda b: (sum(r for r, _ in b["cells"]) / len(b["cells"]), b["id"]))["id"]

    # ---- decisions ----
    def step(self, g: E.RescueGame, t: float) -> Optional[tuple]:
        """What to do now, or None to wait. The caller executes the action and calls again later:

        ``("solve", [bool, ...])`` answer the open lock (one puzzle per entry, in order);
        ``("fix", bug_id, correct)`` answer the Debug puzzle of a bug line;
        ``("place", i, r, c)``, ``("bomb", r, c)``, ``("shuffle",)``."""
        if g.phase == "over" or t < self.next_at:
            return None
        if g.phase == "locked":
            lk = g.lock
            need = 2 if lk["boss"] else 1
            if self.think_until is None:
                self.think_until = t + self.think_time(3 if lk["boss"] else lk["tier"], need)
                return None
            if t < self.think_until:
                return None
            self.think_until = None
            self.next_at = t + self.place_delay()
            return ("solve", self.answers(need))
        if self.task is not None:                            # thinking about a Debug puzzle
            if t < (self.think_until or 0.0):
                return None
            bug = self.task
            self.task = self.think_until = None
            self.next_at = t + self.place_delay()
            if any(b["id"] == bug for b in g.bug_lines):
                return ("fix", bug, self.answers_right())
            return None
        occ, normal = board_bits(g.grid)
        pend = len(g.pending)
        t0 = _clock()
        plan = search(occ, normal, g.tray, pend, self.beam, self.accuracy)
        self.search_s += _clock() - t0
        self.decisions += 1
        if plan is None:                                     # cannot happen: no fit ends the game
            return None
        # items
        if self.uses_bomb and g.items["bomb"] > 0 and (plan.topped or plan.score < SHUFFLE_BELOW
                                                        or occ.bit_count() >= CROWDED_CELLS):
            options = bomb_options(occ, normal, pend)
            if options:
                base = board_score(occ, normal, pend) if plan.topped else plan.score
                sc, r, c, _ = max(options, key=lambda x: x[0])
                if plan.topped or sc - base >= BOMB_MIN_GAIN:
                    self.next_at = t + self.place_delay()
                    return ("bomb", r, c)
        if self.uses_shuffle and g.items["shuffle"] > 0 and not plan.topped and plan.score < SHUFFLE_BELOW:
            self.next_at = t + self.place_delay()
            return ("shuffle",)
        if g.bug_lines and self.wants_bug_fix(g, plan.topped):
            self.task = self.pick_bug(g)
            self.think_until = t + self.think_time(1)
            return None
        self.next_at = t + self.place_delay()
        return ("place", plan.i, plan.r, plan.c)


def _clock() -> float:
    return time.perf_counter()


# --------------------------------------------------------------------------- a suggestion for a human (training mode)


class Suggestion(NamedTuple):
    i: int
    r: int
    c: int
    cells: list
    reason: str            # line | danger | safe | fit
    n: int                 # lines the placement completes (reason "line")


SUGGEST_ACCURACY = 0.9


def suggest(g: E.RescueGame) -> Optional[Suggestion]:
    """Misaki's best placement for the state of ``g`` (any game, e.g. the human's), found with her level-4 search.

    The placement is always legal on the current grid (only empty cells are used). None when nothing fits or when the
    board is not in the ``play`` phase (no placement is possible while a lock is open)."""
    if g.phase != "play":
        return None
    occ, normal = board_bits(g.grid)
    pend = len(g.pending)
    plan = search(occ, normal, g.tray, pend, LADDER[MAX_LEVEL]["beam"], SUGGEST_ACCURACY)
    if plan is None or plan.topped:
        plan = _any_legal(g, occ, normal, pend)
        if plan is None:
            return None
    piece = g.tray[plan.i]
    cells = [(plan.r + dr, plan.c + dc) for dr, dc in piece.cells]
    m = 0
    for r, c in cells:
        m |= 1 << (r * SIZE + c)
    o2, n2 = occ | m, normal | m
    lines, clear = lock_lines(n2)
    reason = "fit"
    if lines:
        reason = "line"
    elif pend and not (m & TOP[min(pend, SIZE)]):
        reason = "danger"
    else:
        def holes_of(x: int) -> int:
            s = (x << 8) & _FULL
            s |= (s << 8) & _FULL
            s |= (s << 16) & _FULL
            s |= (s << 32) & _FULL
            return (s & ~x).bit_count()
        if holes_of(o2) <= holes_of(occ) and not (o2 & TOP[2]):
            reason = "safe"
    return Suggestion(plan.i, plan.r, plan.c, [list(x) for x in cells], reason, lines)


def _any_legal(g: E.RescueGame, occ: int, normal: int, pend: int) -> Optional[Plan]:
    """The least bad legal placement when every plan tops the player out (the lowest placement of the first piece)."""
    best = None
    for i, p in enumerate(g.tray):
        if p is None:
            continue
        for r, c, m, _, _ in placements(p.cells):
            if not m & occ:
                sc = board_score(occ | m, normal | m, pend)
                if best is None or sc > best.score:
                    best = Plan(sc, i, r, c, 0, True, 1)
    return best
