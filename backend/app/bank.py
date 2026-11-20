"""Code Rescue puzzle bank access, selection and answer checking.

The bank (``data/puzzles.sqlite``) is produced offline by ``scripts/generate_bank.py``.
At play time nothing is generated: puzzles are only *selected* from the bank. Parsons answers are
run through the shared validator because the player's arrangement is free-form.
"""
from __future__ import annotations

import json
import os
import random
import sqlite3
from pathlib import Path
from typing import Optional

from . import i18n
from . import validator as V
from .i18n import tr

DB_PATH = Path(os.environ.get("SYNTAX_STACK_DB", Path(__file__).resolve().parents[1] / "data" / "puzzles.sqlite"))

TOPICS = ("variables", "conditions", "loops", "functions")
TYPES = ("parsons", "fill_blank", "predict_output", "find_bug")
LEVELS = ("beginner", "intermediate", "advanced")
MAX_INDENT = 2

# Selection weights per level (spec 4.2): advanced favours find_bug / predict_output.
TYPE_WEIGHTS = {
    "beginner": {"fill_blank": 3, "parsons": 3, "predict_output": 2, "find_bug": 1},
    "intermediate": {"fill_blank": 2, "parsons": 2, "predict_output": 2, "find_bug": 2},
    "advanced": {"fill_blank": 1, "parsons": 1, "predict_output": 3, "find_bug": 3},
}


class BankError(Exception):
    """Base for errors that map to HTTP statuses."""

    status = 400


class NotFound(BankError):
    status = 404


class Malformed(BankError):
    status = 422


# --------------------------------------------------------------------------- access


def _connect() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise NotFound(tr(f"Chưa có ngân hàng câu đố ({DB_PATH.name}). Chạy scripts/generate_bank.py trước.",
                          f"The puzzle bank ({DB_PATH.name}) is missing. Run scripts/generate_bank.py first."))
    con = sqlite3.connect(f"{DB_PATH.as_uri()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _row_to_dict(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["hints"] = json.loads(d["hints"])
    d["data"] = json.loads(d["data"])
    if d.get("hints_en"):
        d["hints_en"] = json.loads(d["hints_en"])
    return d


def count_puzzles() -> int:
    if not DB_PATH.exists():
        return 0
    con = _connect()
    try:
        return con.execute("SELECT COUNT(*) FROM puzzles WHERE debug_only = 0").fetchone()[0]
    finally:
        con.close()


def get_puzzle(puzzle_id: str) -> dict:
    con = _connect()
    try:
        r = con.execute("SELECT * FROM puzzles WHERE id = ?", (puzzle_id,)).fetchone()
    finally:
        con.close()
    if r is None:
        raise NotFound(tr(f"Không tìm thấy câu đố '{puzzle_id}'.", f"Puzzle '{puzzle_id}' was not found."))
    return _row_to_dict(r)


# --------------------------------------------------------------------------- public view


def _view_options(options: list[dict], puzzle_id: str, level: str) -> list[dict]:
    """The options a level sees, in display order.

    The bank stores the correct option within the first three so the beginner view always contains
    it. Showing that stored order as-is would mean the 4th option is never correct, so the view is
    re-ordered with a shuffle seeded by (puzzle id, level): deterministic per request, and ids are
    unchanged so answer checking does not depend on display order.
    """
    limit = 3 if level == "beginner" else 4
    view = list(options[:limit])
    random.Random(f"{puzzle_id}:{level}").shuffle(view)
    return view


def _public_options(options: list[dict], puzzle_id: str, level: str) -> list[dict]:
    return [{"id": o["id"], "text": o["text"]} for o in _view_options(options, puzzle_id, level)]


def public_puzzle(row: dict, level: str = "intermediate", lang: Optional[str] = None) -> dict:
    """The player-facing puzzle. Never contains the answer. ``lang`` (default: the request's) only picks the
    language of the prompt; the code, the options and their order are the same in both languages."""
    typ, data = row["type"], row["data"]
    out = {
        "id": row["id"], "template_id": row["template_id"], "topic": row["topic"], "type": typ,
        "tier": row["tier"], "prompt": i18n.pick(row, "prompt", lang), "code": row["code"],
        "expected_output": None if typ == "predict_output" else row["expected_output"],
        "lines": None, "options": None,
    }
    if typ in ("fill_blank", "predict_output"):
        out["options"] = _public_options(data["options"], row["id"], level)
    elif typ == "parsons":
        out["lines"] = [{"id": l["id"], "text": l["text"]} for l in data["lines"]]
    elif typ == "find_bug":
        out["lines"] = [{"id": l["id"], "text": l["text"], "indent": l["indent"]} for l in data["lines"]]
        out["options"] = [{"id": o["id"], "line_id": o["line_id"], "text": o["text"]}
                          for o in _view_options(data["options"], row["id"], level)]
    return out


# --------------------------------------------------------------------------- selection


def select_puzzle(*, kind: str, topic: Optional[str], tier: Optional[int], level: str,
                  template_id: Optional[str], exclude_ids: list[str],
                  exclude_templates: list[str], rng: Optional[random.Random] = None) -> dict:
    """Pick one puzzle. With ``rng`` (ranked runs and races) the pick is reproducible: the candidates are
    put in a fixed order and every random choice comes from ``rng`` instead of the global generator."""
    rand = rng if rng is not None else random
    excl_ids = set(exclude_ids or [])
    excl_tpl = set(exclude_templates or [])
    con = _connect()
    try:
        if kind == "debug":
            if not template_id:
                raise Malformed(tr("kind 'debug' cần có template_id.", "kind 'debug' needs a template_id."))
            rows = con.execute("SELECT id, type, debug_only FROM puzzles WHERE template_id = ?",
                               (template_id,)).fetchall()
            if not rows:
                raise NotFound(tr(f"Không tìm thấy mẫu câu đố '{template_id}'.",
                                  f"Puzzle template '{template_id}' was not found."))
            rows = [r for r in rows if r["id"] not in excl_ids]
            if rng is not None:
                rows.sort(key=lambda r: r["id"])
            bug_rows = [r for r in rows if r["type"] == "find_bug"]
            pool = bug_rows or [r for r in rows if not r["debug_only"]]
            if not pool:
                raise NotFound(tr("Không còn biến thể nào của mẫu này để dùng cho câu đố Debug.",
                                  "There are no variants of this template left for a Debug puzzle."))
        else:
            if topic is None:
                topic = rand.choice(TOPICS)
            if tier is None:
                tier = 3
            rows = con.execute(
                "SELECT id, template_id, type FROM puzzles WHERE topic = ? AND tier = ? AND debug_only = 0",
                (topic, tier)).fetchall()
            rows = [r for r in rows if r["id"] not in excl_ids]
            if rng is not None:
                rows.sort(key=lambda r: r["id"])
            if template_id:
                rows = [r for r in rows if r["template_id"] == template_id]
            if not rows:
                raise NotFound(tr("Không có câu đố nào khớp với bộ lọc.", "No puzzle matches the filter."))
            preferred = [r for r in rows if r["template_id"] not in excl_tpl]
            pool = preferred or rows  # exclude_templates is only a soft preference
        if kind == "debug":
            chosen = rand.choice(pool)
        else:
            weights = TYPE_WEIGHTS.get(level, TYPE_WEIGHTS["intermediate"])
            chosen = rand.choices(pool, weights=[weights[r["type"]] for r in pool], k=1)[0]
        r = con.execute("SELECT * FROM puzzles WHERE id = ?", (chosen["id"],)).fetchone()
        return _row_to_dict(r)
    finally:
        con.close()


# --------------------------------------------------------------------------- answers


def prediction_followup(row: dict, level: str) -> Optional[dict]:
    """A checked prediction from the same template family when one is available."""
    stem, _, suffix = row["template_id"].rpartition("_")
    preferred = f"{stem}_predict" if suffix in {"fill", "predict", "parsons", "bug"} else row["template_id"]
    con = _connect()
    try:
        candidates = con.execute(
            "SELECT * FROM puzzles WHERE id != ? AND topic = ? AND type = 'predict_output' AND debug_only = 0 "
            "ORDER BY (template_id != ?), abs(tier - ?), id LIMIT 30",
            (row["id"], row["topic"], preferred, row["tier"]),
        )
        for candidate in candidates:
            if candidate["code"] != row["solution_code"] and candidate["expected_output"] != row["expected_output"]:
                return public_puzzle(_row_to_dict(candidate), level)
        return None
    finally:
        con.close()


def _result(row: dict, correct: bool, reveal: bool, group: Optional[str], message: str,
            actual: Optional[str], note: Optional[str] = None, lang: Optional[str] = None) -> dict:
    show = correct or reveal
    explanation = None
    if show:
        text = i18n.pick(row, "explanation", lang)
        explanation = text if correct or not note else f"{note} {text}"
    return {
        "correct": correct,
        "error_group": None if correct else group,
        "message": message,
        "actual_output": actual,
        "solution_code": row["solution_code"] if show else None,
        "explanation": explanation,
    }


def _find_option(data: dict, option_id: Optional[str]) -> dict:
    if not option_id:
        raise Malformed(tr("Thiếu option_id.", "option_id is missing."))
    for o in data["options"]:
        if o["id"] == option_id:
            return o
    raise Malformed(tr(f"option_id '{option_id}' không thuộc câu đố này.",
                       f"option_id '{option_id}' does not belong to this puzzle."))


def attempt_context(row: dict, result: dict, *, option_id: Optional[str] = None,
                    order: Optional[list[dict]] = None) -> dict:
    """Tutor evidence for an already checked attempt, limited to what the game revealed."""
    typ, data = row["type"], row["data"]
    code = row["code"]
    if typ == "parsons":
        lines = {line["id"]: line["text"] for line in data["lines"]}
        choice = "\n".join("    " * item["indent"] + lines[item["line_id"]] for item in order or [])
    else:
        option = _find_option(data, option_id)
        choice = option["text"]
        if typ == "find_bug":
            number = next(i for i, line in enumerate(data["lines"], 1) if line["id"] == option["line_id"])
            choice = tr(f"Dòng {number}: {choice}", f"Line {number}: {choice}")
            code = "\n".join("    " * line["indent"] + line["text"] for line in data["lines"])
    return {
        "prompt": i18n.pick(row, "prompt"), "type": typ, "code": code,
        "choice": choice, "diagnosis": result["message"], "actual_output": result["actual_output"],
        "expected_output": row["expected_output"] if typ != "predict_output" or result["solution_code"] is not None else None,
        "reference": result["explanation"], "solution": result["solution_code"],
    }


def check_answer(row: dict, *, option_id: Optional[str] = None, order: Optional[list[dict]] = None,
                 line_id: Optional[str] = None, reveal: bool = False, diagnose=None,
                 lang: Optional[str] = None) -> dict:
    """``diagnose`` replaces ``validator.diagnose`` for parsons (custom puzzles pass the sandboxed one).
    ``lang`` (default: the request's) only chooses the language of the messages; the verdict never depends on it."""
    typ, data = row["type"], row["data"]
    lang = i18n.resolve(lang)
    ok_msg = tr("Chính xác! Chương trình in đúng đầu ra.", "Correct! The program prints the right output.", lang)

    def opt_text(opt: dict, field: str) -> Optional[str]:
        return i18n.pick_get(opt, field, lang)

    if typ == "fill_blank":
        opt = _find_option(data, option_id)
        if opt["correct"]:
            return _result(row, True, reveal, None, ok_msg, opt["actual_output"], lang=lang)
        return _result(row, False, reveal, opt["group"], opt_text(opt, "message"), opt["actual_output"],
                       opt_text(opt, "note"), lang)

    if typ == "predict_output":
        opt = _find_option(data, option_id)
        if opt["correct"]:
            return _result(row, True, reveal, None, tr("Chính xác!", "Correct!", lang), row["expected_output"],
                           lang=lang)
        msg = (tr("Chưa đúng. Chương trình thật sự in ra: " + V.describe_output(row["expected_output"], "vi") + ".",
                  "Not quite. The program really prints: " + V.describe_output(row["expected_output"], "en") + ".",
                  lang)
               if reveal else tr("Chưa đúng, hãy theo dõi lại chương trình từng dòng.",
                                 "Not quite, trace the program again line by line.", lang))
        return _result(row, False, reveal, "wrong_choice", msg,
                       row["expected_output"] if reveal else None, opt_text(opt, "note"), lang)

    if typ == "find_bug":  # v2: the player picks one whole-line edit; any line_id sent is ignored
        opt = _find_option(data, option_id)
        if opt["correct"]:
            return _result(row, True, reveal, None,
                           tr("Chính xác! Sau khi sửa, chương trình in đúng đầu ra.",
                              "Correct! After the fix, the program prints the right output.", lang),
                           opt["actual_output"], lang=lang)
        if opt["line_id"] != data["bug_line"]:
            msg = (tr("Dòng này không phải dòng bị lỗi nên chương trình vẫn chạy sai. ",
                      "This is not the bug line, so the program still runs wrong. ", lang)
                   + (opt_text(opt, "message") or ""))
            return _result(row, False, reveal, "wrong_line", msg.strip(), opt["actual_output"],
                           opt_text(opt, "note"), lang)
        return _result(row, False, reveal, "wrong_fix", opt_text(opt, "message"), opt["actual_output"],
                       opt_text(opt, "note"), lang)

    if typ == "parsons":
        return _check_parsons(row, order, reveal, diagnose or V.diagnose, lang)

    raise Malformed(tr("Loại câu đố không được hỗ trợ.", "This puzzle type is not supported."))  # pragma: no cover


def _check_parsons(row: dict, order: Optional[list[dict]], reveal: bool, diagnose, lang: str) -> dict:
    data = row["data"]
    if not order:
        raise Malformed(tr("Thiếu 'order'.", "'order' is missing."))
    texts = {l["id"]: l["text"] for l in data["lines"]}
    ids = [o["line_id"] for o in order]
    if sorted(ids) != sorted(texts):
        raise Malformed(tr("'order' phải chứa mỗi dòng đúng một lần.", "'order' must contain every line exactly once."))
    for o in order:
        if not (0 <= o["indent"] <= MAX_INDENT):
            raise Malformed(tr(f"indent phải từ 0 đến {MAX_INDENT}.", f"indent must be from 0 to {MAX_INDENT}."))
    code = "\n".join("    " * o["indent"] + texts[o["line_id"]] for o in order)
    diag = diagnose(code, row["expected_output"])
    if diag.passed:
        return _result(row, True, reveal, None,
                       tr("Chính xác! Chương trình in đúng đầu ra.", "Correct! The program prints the right output.", lang),
                       diag.actual_output, lang=lang)

    group = diag.error_group
    if diag.run is not None and diag.run.ok:  # ran, but printed something else: say why structurally
        sol = data["solution"]
        if ids != [s["line_id"] for s in sol]:
            group = "wrong_order"
        elif [o["indent"] for o in order] != [s["indent"] for s in sol]:
            group = "bad_indent"
    note = None
    for d in data.get("distractors", []):
        if d["code"] == code:
            note = i18n.pick_get(d, "note", lang)
            break
    return _result(row, False, reveal, group, diag.msg(lang), diag.actual_output, note, lang)
