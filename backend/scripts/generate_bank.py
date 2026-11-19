#!/usr/bin/env python
"""Offline generator for the Code Rescue puzzle bank.

    python scripts/generate_bank.py [--out data/puzzles.sqlite] [--seed N]

Reads ``content/templates/*.yaml`` (16 hand-written templates) and expands each into
30-50 verified variants stored in SQLite. Nothing here runs at play time.

Verification per variant (see Code_Rescue_Gameplay_Spec.md section 10.2):
  * the correct program is run by the shared validator -> expected_output
  * every distractor is run too; the variant is DROPPED if any distractor also yields the
    correct output (ambiguous puzzle)
  * predict_output options must all differ from each other and from the correct output
  * parsons shuffles must not already be a correct program
  * duplicate visible puzzles, empty outputs and outputs that are too long are dropped
Exit status is non-zero unless every template has >= 20 variants AND every topic x tier >= 20.
"""
from __future__ import annotations

import argparse
import ast
import itertools
import json
import os
import random
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app import validator as V  # noqa: E402
# Shared with the custom-code puzzle generator (app/custom_gen.py); re-exported under the old names.
from app.puzzle_tools import (  # noqa: E402,F401
    MAX_OUTPUT_LINE_CHARS, MAX_OUTPUT_LINES, Drop, build_bug_form, join_lines, letter, mutations,
    output_ok, place_options, split_lines,
)

TEMPLATE_DIR = BACKEND / "content" / "templates"
MISTAKES_FILE = BACKEND / "content" / "mistakes.yaml"
DEFAULT_OUT = BACKEND / "data" / "puzzles.sqlite"
DEFAULT_SEED = 20260516

TOPICS = ["variables", "conditions", "loops", "functions"]
TYPES = ["parsons", "fill_blank", "predict_output", "find_bug"]
MIN_PROGRAM_LINES, MAX_PROGRAM_LINES = 2, 7
MAX_PROGRAM_LINE_CHARS = 48
MAX_DISTRACTORS = 4
MIN_TEMPLATE_VARIANTS = 20
MIN_CELL_VARIANTS = 20


# ----------------------------------------------------------------------------- rendering

HELPERS = {
    "J": lambda xs: "\n".join(str(x) for x in xs),
    "range": range, "len": len, "sum": sum, "min": min, "max": max, "abs": abs,
    "str": str, "int": int, "list": list, "sorted": sorted,
}
_EXPR = re.compile(r"\{([^{}]+)\}")


def _env(ctx: dict) -> dict:
    env = {"__builtins__": {}}
    env.update(HELPERS)
    env.update(ctx)
    return env


def render(text: str, ctx: dict) -> str:
    def sub(m: re.Match) -> str:
        return str(eval(m.group(1), _env(ctx)))  # trusted, hand-written template content
    return _EXPR.sub(sub, text)


def ev(expr: str, ctx: dict):
    return eval(expr, _env(ctx))


# ----------------------------------------------------------------------------- helpers


def check_program(code: str) -> None:
    lines = [l for l in code.split("\n") if l.strip()]
    if not (MIN_PROGRAM_LINES <= len(lines) <= MAX_PROGRAM_LINES):
        raise Drop("program_length")
    if any(len(l) > MAX_PROGRAM_LINE_CHARS for l in lines):
        raise Drop("program_line_too_long")


def run_expected(code: str) -> str:
    check_program(code)
    res = V.run_program(code)
    if not res.ok:
        raise Drop(f"correct_program_error:{res.exc_name}")
    out = V.normalize_output(res.output)
    if not output_ok(out):
        raise Drop("output_empty_or_too_long")
    return out


def has_for_loop(code: str) -> bool:
    return any(isinstance(n, ast.For) for n in ast.walk(ast.parse(code)))


# ----------------------------------------------------------------------------- variant makers


class Ctx:
    """Everything needed to render the text fields of one variant."""

    def __init__(self, tpl, block, ctx, expected, answer=""):
        self.tpl, self.block = tpl, block
        self.ctx = dict(ctx)
        self.ctx["expected"] = expected
        self.ctx["expected_inline"] = ", ".join(expected.split("\n"))
        self.ctx["answer"] = answer

    def text(self, s: str) -> str:
        return render(s, self.ctx)

    def common(self, mistakes: dict) -> dict:
        """The text fields of a variant, Vietnamese and English. The English text is rendered from the ``_en``
        siblings with the very same parameters; nothing here touches a random generator."""
        tpl, block = self.tpl, self.block
        hints = [self.text(h) for h in tpl["hints"]]
        explanation = self.text(block.get("explanation") or tpl["explanation"])
        hints_en = [self.text(h) for h in tpl["hints_en"]]
        explanation_en = self.text(block.get("explanation_en") or tpl["explanation_en"])
        return {"prompt": self.text(block["prompt"]), "hints": hints, "explanation": explanation,
                "prompt_en": self.text(block["prompt_en"]), "hints_en": hints_en,
                "explanation_en": explanation_en}


def note_for(name: str, mistakes: dict) -> str | None:
    return mistakes.get(name)


def note_en_for(name: str, mistakes: dict) -> str | None:
    """English note of a named mistake: the ``<name>_en`` sibling in content/mistakes.yaml."""
    return mistakes.get(name + "_en")


def make_fill(tpl, tier, block, ctx, rng, mistakes):
    answer = render(block["answer"], ctx)
    skeleton = render(block["code"], ctx).rstrip("\n")
    if skeleton.count("___") != 1:
        raise ValueError(f"{tpl['id']}: skeleton must contain exactly one ___")
    correct_code = skeleton.replace("___", answer)
    expected = run_expected(correct_code)

    ds, seen = [], {answer}
    for d in block["distractors"]:
        frag = render(d["frag"], ctx)
        if frag == answer:
            raise Drop("distractor_equals_answer")
        if frag in seen:
            continue
        seen.add(frag)
        diag = V.diagnose(skeleton.replace("___", frag), expected)
        if diag.passed:
            raise Drop("ambiguous_distractor")
        ds.append({
            "name": d["name"], "text": frag, "group": diag.error_group or "output_mismatch",
            "actual_output": diag.actual_output, "message": diag.message, "message_en": diag.message_en,
            "note": note_for(d["name"], mistakes), "note_en": note_en_for(d["name"], mistakes),
        })
        if len(ds) == MAX_DISTRACTORS:
            break
    if len(ds) < 3:
        raise Drop("too_few_distractors")

    cx = Ctx(tpl, block, ctx, expected, answer)
    base = cx.common(mistakes)
    slots = place_options(4, rng)
    opts: list = [None] * 4
    opts[slots[0]] = {"text": answer, "correct": True, "name": None, "group": None,
                      "actual_output": expected, "message": None, "note": None}
    for k in range(3):
        opts[slots[k + 1]] = dict(ds[k], correct=False)
    for i, o in enumerate(opts):
        o["id"] = letter(i)

    key = (skeleton, answer)
    primary = dict(base, type="fill_blank", code=skeleton, expected_output=expected,
                   solution_code=correct_code, data={"options": opts}, key=key)

    # --- find_bug form (used only for kind=debug): the blank is filled with a wrong fragment
    debug = None
    others = ds[1:4]
    if others:
        sk_lines = split_lines(skeleton)
        bug_idx = next(i for i, (_, t) in enumerate(sk_lines) if "___" in t)
        buggy_items = [(ind, t.replace("___", ds[0]["text"])) for ind, t in sk_lines]
        fixed_line = sk_lines[bug_idx][1].replace("___", answer)
        wrong_fixes = [{"name": o["name"], "text": sk_lines[bug_idx][1].replace("___", o["text"]),
                        "note": o["note"], "note_en": o["note_en"]} for o in others]
        try:
            form = build_bug_form(buggy_items, bug_idx, fixed_line, wrong_fixes, expected, rng)
        except Drop:
            form = None
        if form is not None:
            bug_prompt = (f"Chương trình dưới đây chạy chưa đúng. Chọn cách sửa đúng "
                          f"để in ra {cx.ctx['expected_inline']}.")
            bug_prompt_en = (f"The program below does not work right yet. Choose the right fix "
                             f"to print {cx.ctx['expected_inline']}.")
            debug = dict(base, type="find_bug", prompt=bug_prompt, prompt_en=bug_prompt_en, code=None,
                         expected_output=expected,
                         solution_code=correct_code, data=form, key=("debug",) + key)
    return primary, debug


def make_predict(tpl, tier, block, ctx, rng, mistakes):
    code = render(block["code"], ctx).rstrip("\n")
    expected = run_expected(code)
    ds, seen = [], {expected}
    for d in block["distractors"]:
        out = V.normalize_output(render(d["out"], ctx))
        if out == expected:
            raise Drop("ambiguous_distractor")
        if out in seen or not output_ok(out):
            continue
        seen.add(out)
        ds.append({"name": d["name"], "text": out, "note": note_for(d["name"], mistakes),
                   "note_en": note_en_for(d["name"], mistakes)})
        if len(ds) == MAX_DISTRACTORS:
            break
    if len(ds) < 3:
        raise Drop("too_few_distractors")
    cx = Ctx(tpl, block, ctx, expected)
    base = cx.common(mistakes)
    slots = place_options(4, rng)
    opts: list = [None] * 4
    opts[slots[0]] = {"text": expected, "correct": True, "name": None, "group": None, "note": None}
    for k in range(3):
        opts[slots[k + 1]] = {"text": ds[k]["text"], "correct": False, "name": ds[k]["name"],
                              "group": "wrong_choice", "note": ds[k]["note"], "note_en": ds[k]["note_en"]}
    for i, o in enumerate(opts):
        o["id"] = letter(i)
    return dict(base, type="predict_output", code=code, expected_output=expected,
                solution_code=code, data={"options": opts}, key=(code,)), None


def make_parsons(tpl, tier, block, ctx, rng, mistakes):
    code = render(block["code"], ctx).rstrip("\n")
    expected = run_expected(code)
    items = split_lines(code)
    n = len(items)
    if not (3 <= n <= 7):
        raise Drop("parsons_length")
    norm_solution = join_lines(items)
    ds = []
    for d in block["distractors"]:
        dcode = render(d["code"], ctx).rstrip("\n")
        diag = V.diagnose(dcode, expected)
        if diag.passed:
            raise Drop("ambiguous_distractor")
        ds.append({"name": d["name"], "code": join_lines(split_lines(dcode)),
                   "group": diag.error_group, "note": note_for(d["name"], mistakes),
                   "note_en": note_en_for(d["name"], mistakes)})
    if not ds:
        raise Drop("no_distractors")

    perm = None
    for _ in range(80):
        cand = rng.sample(range(n), n)
        if cand == list(range(n)):
            continue
        flat = "\n".join(items[i][1] for i in cand)  # all indent 0, as the player first sees it
        if not V.diagnose(flat, expected).passed:
            perm = cand
            break
    if perm is None:
        raise Drop("no_wrong_shuffle")

    lines = [{"id": f"l{j+1}", "text": items[perm[j]][1]} for j in range(n)]
    id_of_original = {perm[j]: f"l{j+1}" for j in range(n)}
    solution = [{"line_id": id_of_original[i], "indent": items[i][0]} for i in range(n)]
    cx = Ctx(tpl, block, ctx, expected)
    base = cx.common(mistakes)
    return dict(base, type="parsons", code=None, expected_output=expected, solution_code=norm_solution,
                data={"lines": lines, "solution": solution, "distractors": ds},
                key=(norm_solution,)), None


def make_bug(tpl, tier, block, ctx, rng, mistakes):
    buggy = render(block["code"], ctx).rstrip("\n")
    items = split_lines(buggy)
    bug_idx = int(block["bug_line"]) - 1
    fix = render(block["fix"], ctx)
    fixed_items = list(items)
    fixed_items[bug_idx] = (items[bug_idx][0], fix)
    fixed_code = join_lines(fixed_items)
    expected = run_expected(fixed_code)
    bdiag = V.diagnose(join_lines(items), expected)
    if bdiag.passed:
        raise Drop("buggy_program_is_correct")

    ds, seen = [], {fix, items[bug_idx][1]}
    for d in block["distractors"]:
        rep = render(d["rep"], ctx)
        if rep == fix:
            raise Drop("distractor_equals_answer")
        if rep in seen:
            continue
        seen.add(rep)
        ds.append({"name": d["name"], "text": rep, "note": note_for(d["name"], mistakes),
                   "note_en": note_en_for(d["name"], mistakes)})
        if len(ds) == 3:
            break
    data = build_bug_form(items, bug_idx, fix, ds, expected, rng)  # also rejects ambiguous distractors
    cx = Ctx(tpl, block, ctx, expected, fix)
    base = cx.common(mistakes)
    return dict(base, type="find_bug", code=None, expected_output=expected, solution_code=fixed_code,
                data=data, key=(buggy, fix)), None


MAKERS = {"fill_blank": make_fill, "predict_output": make_predict,
          "parsons": make_parsons, "find_bug": make_bug}


# ----------------------------------------------------------------------------- expansion


def candidate_contexts(block: dict, rng: random.Random):
    params = block.get("params") or {}
    keys = list(params)
    combos = list(itertools.product(*[params[k] for k in keys])) if keys else [()]
    rng.shuffle(combos)
    for combo in combos:
        ctx = dict(zip(keys, combo))
        try:
            for k, expr in (block.get("derived") or {}).items():
                ctx[k] = ev(expr, ctx)
            if not all(ev(w, ctx) for w in (block.get("where") or [])):
                continue
        except (IndexError, KeyError, ZeroDivisionError):
            continue
        yield ctx


def expand_template(tpl: dict, seed: int, mistakes: dict):
    rng = random.Random(f"{seed}:{tpl['id']}")
    primaries: list[dict] = []
    debugs: list[dict] = []
    drops: Counter = Counter()
    seen_keys: set = set()
    for tier in sorted(tpl["tiers"]):
        for block in tpl["tiers"][tier]:
            accepted = 0
            for ctx in candidate_contexts(block, rng):
                if accepted >= block["count"]:
                    break
                try:
                    primary, debug = MAKERS[tpl["type"]](tpl, tier, block, ctx, rng, mistakes)
                except Drop as d:
                    drops[str(d)] += 1
                    continue
                if primary["key"] in seen_keys:
                    drops["duplicate"] += 1
                    continue
                if tier == 3 and not has_for_loop(primary["solution_code"]):
                    raise ValueError(f"{tpl['id']}: tier 3 puzzle without a loop (no nesting)")
                seen_keys.add(primary["key"])
                primary.update(tier=int(tier), template_id=tpl["id"], topic=tpl["topic"])
                primaries.append(primary)
                accepted += 1
                if debug is not None and debug["key"] not in seen_keys:
                    seen_keys.add(debug["key"])
                    debug.update(tier=int(tier), template_id=tpl["id"], topic=tpl["topic"])
                    debugs.append(debug)
    for i, p in enumerate(primaries, 1):
        p["id"] = f"{tpl['id']}__{i:03d}"
        p["debug_only"] = 0
    for i, p in enumerate(debugs, 1):
        p["id"] = f"{tpl['id']}__d{i:03d}"
        p["debug_only"] = 1
    return primaries, debugs, drops


# ----------------------------------------------------------------------------- storage


SCHEMA = """
CREATE TABLE puzzles (
    id TEXT PRIMARY KEY,
    template_id TEXT NOT NULL,
    topic TEXT NOT NULL,
    type TEXT NOT NULL,
    tier INTEGER NOT NULL,
    debug_only INTEGER NOT NULL DEFAULT 0,
    prompt TEXT NOT NULL,
    code TEXT,
    expected_output TEXT NOT NULL,
    solution_code TEXT NOT NULL,
    explanation TEXT NOT NULL,
    hints TEXT NOT NULL,
    data TEXT NOT NULL,
    prompt_en TEXT NOT NULL,
    explanation_en TEXT NOT NULL,
    hints_en TEXT NOT NULL
);
CREATE INDEX idx_puzzles_select ON puzzles (topic, tier, debug_only);
CREATE INDEX idx_puzzles_template ON puzzles (template_id);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def write_db(path: Path, puzzles: list[dict], seed: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    try:
        con.executescript(SCHEMA)
        con.executemany(
            "INSERT INTO puzzles VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(p["id"], p["template_id"], p["topic"], p["type"], p["tier"], p["debug_only"], p["prompt"],
              p["code"], p["expected_output"], p["solution_code"], p["explanation"],
              json.dumps(p["hints"], ensure_ascii=False), json.dumps(p["data"], ensure_ascii=False),
              p["prompt_en"], p["explanation_en"], json.dumps(p["hints_en"], ensure_ascii=False))
             for p in puzzles])
        con.execute("INSERT INTO meta VALUES ('seed', ?)", (str(seed),))
        con.commit()
    finally:
        con.close()


# ----------------------------------------------------------------------------- main


def load_templates() -> list[dict]:
    tpls = []
    for f in sorted(TEMPLATE_DIR.glob("*.yaml")):
        tpl = yaml.safe_load(f.read_text(encoding="utf-8"))
        if tpl["id"] != f.stem:
            raise SystemExit(f"{f.name}: id {tpl['id']!r} does not match file name")
        if len(tpl["hints"]) != 3:
            raise SystemExit(f"{f.name}: needs exactly 3 hints")
        if len(tpl.get("hints_en") or []) != 3 or not tpl.get("explanation_en"):
            raise SystemExit(f"{f.name}: needs hints_en (3) and explanation_en (English siblings, see app/i18n.py)")
        for tier, blocks in tpl["tiers"].items():
            if not isinstance(blocks, list):
                raise SystemExit(f"{f.name}: tier {tier} must be a list of blocks")
            for block in blocks:
                if not block.get("prompt_en"):
                    raise SystemExit(f"{f.name}: tier {tier} block without prompt_en")
        tpls.append(tpl)
    return tpls


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--verbose", action="store_true", help="print drop reasons per template")
    args = ap.parse_args(argv)

    mistakes = {}
    if MISTAKES_FILE.exists():
        mistakes = yaml.safe_load(MISTAKES_FILE.read_text(encoding="utf-8")) or {}

    templates = load_templates()
    problems: list[str] = []
    if len(templates) != 16:
        problems.append(f"expected 16 templates, found {len(templates)}")
    combos = Counter((t["topic"], t["type"]) for t in templates)
    for topic in TOPICS:
        for typ in TYPES:
            if combos[(topic, typ)] != 1:
                problems.append(f"topic/type {topic}/{typ}: {combos[(topic, typ)]} templates (want 1)")

    all_puzzles: list[dict] = []
    per_template: dict[str, int] = {}
    per_debug: dict[str, int] = {}
    cell: Counter = Counter()
    drop_report: dict[str, Counter] = {}
    for tpl in templates:
        prim, dbg, drops = expand_template(tpl, args.seed, mistakes)
        per_template[tpl["id"]] = len(prim)
        per_debug[tpl["id"]] = len(dbg)
        drop_report[tpl["id"]] = drops
        for p in prim:
            cell[(p["topic"], p["tier"])] += 1
        all_puzzles.extend(prim)
        all_puzzles.extend(dbg)

    ids = [p["id"] for p in all_puzzles]
    if len(ids) != len(set(ids)):
        problems.append("duplicate puzzle ids")
    # Build in a temp file next to the target; only replace the bank once coverage passes.
    tmp_out = args.out.with_name(f".{args.out.name}.{os.getpid()}.tmp")
    write_db(tmp_out, all_puzzles, args.seed)

    # ---- report
    print(f"Seed {args.seed} -> {args.out}")
    print()
    print("Per template (primary variants / debug-only find_bug forms):")
    for tpl in templates:
        n = per_template[tpl["id"]]
        flag = "" if n >= MIN_TEMPLATE_VARIANTS else "   <-- below minimum"
        print(f"  {tpl['id']:<28} {tpl['type']:<15} {n:>3} / {per_debug[tpl['id']]:>2}{flag}")
        if n < MIN_TEMPLATE_VARIANTS:
            problems.append(f"template {tpl['id']} has only {n} variants")
        if args.verbose and drop_report[tpl["id"]]:
            print("      drops:", dict(drop_report[tpl["id"]].most_common()))
    print()
    print("Per topic x tier:")
    print(f"  {'topic':<12} {'tier 1':>7} {'tier 2':>7} {'tier 3':>7}  total")
    for topic in TOPICS:
        row = [cell[(topic, t)] for t in (1, 2, 3)]
        print(f"  {topic:<12} {row[0]:>7} {row[1]:>7} {row[2]:>7}  {sum(row):>5}")
        for t, n in zip((1, 2, 3), row):
            if n < MIN_CELL_VARIANTS:
                problems.append(f"topic {topic} tier {t} has only {n} variants")
    primary_total = sum(per_template.values())
    print()
    print(f"Total: {primary_total} puzzles + {sum(per_debug.values())} debug-only find_bug forms")
    if problems:
        print()
        for p in problems:
            print("PROBLEM:", p)
        tmp_out.unlink(missing_ok=True)
        print(f"Existing {args.out} left untouched.")
        return 1
    os.replace(tmp_out, args.out)
    print("Coverage OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
