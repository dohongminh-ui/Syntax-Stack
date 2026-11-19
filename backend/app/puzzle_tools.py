"""Helpers shared by the offline bank generator and the custom-code puzzle generator.

Everything here is either pure text/option logic or goes through ``validator.diagnose``. The offline
generator calls it in-process on reviewed template content. The custom generator (``custom_gen``)
calls it only inside the sandbox child process (see ``sandbox.py``), never in the web server.
"""
from __future__ import annotations

import random
import re

from . import validator as V

MAX_OUTPUT_LINES = 5
MAX_OUTPUT_LINE_CHARS = 40


class Drop(Exception):
    """Variant rejected by a verification rule. ``str(exc)`` is the reason (Vietnamese for the custom generator's
    learner-facing reasons); ``exc.en`` is the English reason (the same text for internal rule codes)."""

    def __init__(self, reason: str = "", en: str | None = None):
        super().__init__(reason)
        self.en = en if en is not None else reason


# ----------------------------------------------------------------------------- text helpers


def split_lines(code: str) -> list[tuple[int, str]]:
    """'for ...:\\n    print(i)' -> [(0, 'for ...:'), (1, 'print(i)')]"""
    out = []
    for raw in code.rstrip("\n").split("\n"):
        stripped = raw.lstrip(" ")
        indent_spaces = len(raw) - len(stripped)
        if indent_spaces % 4:
            raise ValueError(f"indent not a multiple of 4: {raw!r}")
        out.append((indent_spaces // 4, stripped))
    return out


def join_lines(items: list[tuple[int, str]]) -> str:
    return "\n".join("    " * ind + text for ind, text in items)


def output_ok(out: str) -> bool:
    if not out:
        return False
    lines = out.split("\n")
    return len(lines) <= MAX_OUTPUT_LINES and all(len(l) <= MAX_OUTPUT_LINE_CHARS for l in lines)


def place_options(n_options: int, rng: random.Random) -> list[int]:
    """Return for each option index (0 = correct, 1.. = distractors by priority) its slot 0..n-1.

    The correct answer always lands in slots a-c so beginners (who only see a-c) always get
    correct + 2 distractors; the lowest-priority distractor takes slot d.
    """
    if n_options <= 3:
        slots = list(range(n_options))
        rng.shuffle(slots)
        return slots
    p = rng.randrange(3)
    free = [i for i in range(3) if i != p]
    return [p, free[0], free[1], 3]


def letter(i: int) -> str:
    return "abcd"[i]


# ----------------------------------------------------------------------------- find_bug v2 options

_STR = re.compile(r"\"[^\"]*\"|'[^']*'")
_INT = re.compile(r"\b\d+\b")
_OP_SWAPS = [(" + ", " - "), (" - ", " + "), (" * ", " + "), (">=", ">"), ("<=", "<"), ("==", "!="),
             (" > ", " >= "), (" < ", " <= ")]


def _outside_strings(text: str):
    """Split into (is_string, chunk) pieces so edits never touch string literals."""
    out, pos = [], 0
    for m in _STR.finditer(text):
        if m.start() > pos:
            out.append((False, text[pos:m.start()]))
        out.append((True, m.group(0)))
        pos = m.end()
    if pos < len(text):
        out.append((False, text[pos:]))
    return out


def mutations(text: str) -> list[str]:
    """Plausible but wrong whole-line edits of a line (numbers off by one, swapped operators...)."""
    if text.startswith("def ") or text.rstrip(":") in ("else", "try"):
        return []
    pieces = _outside_strings(text)
    res: list[str] = []

    def rebuild(idx, new_chunk):
        return "".join(new_chunk if i == idx else c for i, (_, c) in enumerate(pieces))

    for idx, (is_str, chunk) in enumerate(pieces):
        if is_str:
            continue
        for m in _INT.finditer(chunk):
            n = int(m.group(0))
            for v in (n + 1, n - 1):
                if v >= 0:
                    res.append(rebuild(idx, chunk[:m.start()] + str(v) + chunk[m.end():]))
        for old, new in _OP_SWAPS:
            if old in chunk:
                res.append(rebuild(idx, chunk.replace(old, new, 1)))
    m = re.fullmatch(r"print\((\w+)\)", text)
    if m:
        res.append(f"print({m.group(1)} + 1)")
    seen, out = {text}, []
    for r in res:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def build_bug_form(items, bug_idx, fix, wrong_fixes, expected, rng):
    """find_bug v2: every option is a whole-line edit tied to a line_id; options span >= 2 lines.

    items: buggy program [(indent, text)]; wrong_fixes: [{name, text, note}] wrong edits of the bug line.
    Raises Drop when no valid option set exists.
    """
    def trial(idx, text):
        t = list(items)
        t[idx] = (items[idx][0], text)
        return V.diagnose(join_lines(t), expected)

    bug_id = f"l{bug_idx + 1}"
    wf, seen = [], {fix, items[bug_idx][1]}
    for w in wrong_fixes:
        if w["text"] in seen:
            continue
        seen.add(w["text"])
        diag = trial(bug_idx, w["text"])
        if diag.passed:
            raise Drop("ambiguous_distractor")
        wf.append({"line_id": bug_id, "text": w["text"], "name": w["name"], "group": "wrong_fix",
                   "actual_output": diag.actual_output, "message": diag.message, "message_en": diag.message_en,
                   "note": w["note"], "note_en": w.get("note_en")})
    if not wf:
        raise Drop("no_wrong_fix")

    cands = []
    for i, (_, t) in enumerate(items):
        if i == bug_idx:
            continue
        for m in mutations(t):
            diag = trial(i, m)
            if diag.passed:
                continue  # accidentally fixes the program: not a valid wrong option
            cands.append((i, m, diag))
    rng.shuffle(cands)
    cands.sort(key=lambda c: not (c[2].run is not None and c[2].run.ok))  # prefer edits that still run
    if not cands:
        raise Drop("no_other_line_edits")

    def other(c):
        i, m, diag = c
        return {"line_id": f"l{i + 1}", "text": m, "name": "edited_wrong_line", "group": "wrong_line",
                "actual_output": diag.actual_output, "message": diag.message, "message_en": diag.message_en,
                "note": None, "note_en": None}

    o1 = cands[0]
    o2 = next((c for c in cands[1:] if c[0] == o1[0]), None) or (cands[1] if len(cands) > 1 else None)
    third = other(o2) if o2 else (wf[1] if len(wf) > 1 else None)
    if third is None:
        raise Drop("too_few_options")
    # priority order: slots a-c get the first two, slot d the last; both orders keep beginners on >= 2 lines
    if o2 is not None and rng.random() < 0.5:
        dist = [other(o1), other(o2), wf[0]]
    else:
        dist = [wf[0], other(o1), third]
    slots = place_options(4, rng)
    opts: list = [None] * 4
    opts[slots[0]] = {"line_id": bug_id, "text": fix, "correct": True, "name": None, "group": None,
                      "actual_output": expected, "message": None, "note": None}
    for k, d in enumerate(dist):
        opts[slots[k + 1]] = dict(d, correct=False)
    for i, o in enumerate(opts):
        o["id"] = letter(i)
    assert len({(o["line_id"], o["text"]) for o in opts}) == 4
    assert len({o["line_id"] for o in opts[:3]}) >= 2 and len({o["line_id"] for o in opts}) >= 2
    bdiag = V.diagnose(join_lines(items), expected)
    return {"lines": [{"id": f"l{i + 1}", "text": t, "indent": ind} for i, (ind, t) in enumerate(items)],
            "bug_line": bug_id, "options": opts, "buggy_output": bdiag.actual_output,
            "buggy_message": bdiag.message, "buggy_message_en": bdiag.message_en}
