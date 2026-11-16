"""Syntax Rows: level loading, program assembly from the board, run + diagnosis."""
from __future__ import annotations

import ast
import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from . import validator as V

LEVELS_DIR = Path(os.environ.get("SYNTAX_STACK_LEVELS", Path(__file__).resolve().parents[1] / "content" / "levels"))

ERROR_GROUPS = (
    "syntax", "bad_indent", "missing_colon", "wrong_order", "output_mismatch",
    "missing_construct", "empty",
)

CONSTRUCT_NAMES_VI = {
    "Assign": "phép gán biến", "If": "câu lệnh if", "For": "vòng lặp for", "While": "vòng lặp while",
    "FunctionDef": "định nghĩa hàm (def)", "Return": "lệnh return",
}


class RowsError(ValueError):
    """Bad board payload (HTTP 422)."""


class LevelNotFound(KeyError):
    """Unknown level id (HTTP 404)."""


@dataclass
class AsmLine:
    row: int
    indent: int
    token_ids: list[str]
    texts: list[str]

    @property
    def text(self) -> str:
        return " ".join(self.texts)

    @property
    def source(self) -> str:
        return "    " * self.indent + self.text


# --------------------------------------------------------------------------- loading

_cache: Optional[dict[str, dict]] = None


def _prepare(level: dict) -> dict:
    tokens = {t["id"]: t for t in level["tokens"]}
    if len(tokens) != len(level["tokens"]):
        raise ValueError(f"{level['id']}: duplicate token ids")
    for t in tokens.values():
        if not 1 <= t["w"] <= 3:
            raise ValueError(f"{level['id']}: token {t['id']} width out of range")
    level["_tokens"] = tokens
    level["_canonical"] = [
        (row["indent"], " ".join(tokens[i]["text"] for i in row["tokens"])) for row in level["solution"]
    ]
    return level


def load_levels(force: bool = False) -> dict[str, dict]:
    global _cache
    if _cache is not None and not force:
        return _cache
    levels: dict[str, dict] = {}
    for f in sorted(LEVELS_DIR.glob("*.yaml")):
        lv = _prepare(yaml.safe_load(f.read_text(encoding="utf-8")))
        levels[lv["id"]] = lv
    _cache = levels
    return levels


def get_level(level_id: str) -> dict:
    lv = load_levels().get(level_id)
    if lv is None:
        raise LevelNotFound(f"Không tìm thấy màn '{level_id}'.")
    return lv


def list_levels() -> list[dict]:
    return [
        {"id": lv["id"], "order": lv["order"], "title": lv["title"], "concept": lv["concept"],
         "rows": lv["rows"], "cols": lv["cols"]}
        for lv in sorted(load_levels().values(), key=lambda l: l["order"])
    ]


def public_level(lv: dict) -> dict:
    """Player-facing level: no solution, no ``is_distractor``."""
    return {
        "id": lv["id"], "order": lv["order"], "title": lv["title"], "concept": lv["concept"],
        "goal": lv["goal"], "expected_output": lv["expected_output"],
        "twist_output": lv.get("twist_output"), "predictions": lv.get("predictions", []),
        "rows": lv["rows"], "cols": lv["cols"], "indent_cols": lv.get("indent_cols", 2),
        "tokens": [{"id": t["id"], "text": t["text"], "w": t["w"], "topic": t["topic"]} for t in lv["tokens"]],
    }


# --------------------------------------------------------------------------- assembly


def assemble(lv: dict, rows: list[dict]) -> list[AsmLine]:
    """Turn the board payload into program lines. Raises RowsError on structural violations."""
    tokens = lv["_tokens"]
    cols, indent_cols = lv["cols"], lv.get("indent_cols", 2)
    used: set[str] = set()
    seen_rows: set[int] = set()
    lines: list[AsmLine] = []
    for r in sorted(rows, key=lambda r: r["row"]):
        ridx = r["row"]
        if not 0 <= ridx < lv["rows"]:
            raise RowsError(f"Hàng {ridx} nằm ngoài bàn chơi (0 đến {lv['rows'] - 1}).")
        if ridx in seen_rows:
            raise RowsError(f"Hàng {ridx} xuất hiện nhiều lần.")
        seen_rows.add(ridx)
        placed = r["tokens"]
        if not placed:
            continue
        placed = sorted(placed, key=lambda p: p["col"])
        prev_end = 0
        for p in placed:
            tid = p["id"]
            if tid not in tokens:
                raise RowsError(f"Mảnh '{tid}' không thuộc màn này.")
            if tid in used:
                raise RowsError(f"Mảnh '{tid}' được dùng nhiều hơn một lần.")
            used.add(tid)
            col, w = p["col"], tokens[tid]["w"]
            if col < 0 or col + w > cols:
                raise RowsError(f"Mảnh '{tid}' vượt ra ngoài bàn chơi (cột {col}, rộng {w}, tối đa {cols} cột).")
            if col < prev_end:
                raise RowsError(f"Mảnh '{tid}' chồng lên mảnh khác ở hàng {ridx}.")
            prev_end = col + w
        first = placed[0]["col"]
        if first > indent_cols:
            raise RowsError(f"Mảnh đầu tiên của hàng {ridx} phải nằm ở cột 0 đến {indent_cols}.")
        lines.append(AsmLine(ridx, first, [p["id"] for p in placed], [tokens[p["id"]]["text"] for p in placed]))
    return lines


def _row_of_lineno(lines: list[AsmLine], lineno: Optional[int]) -> Optional[int]:
    if lineno is None or not lines:
        return None
    return lines[min(max(lineno, 1), len(lines)) - 1].row


def _first_diff_row(lv: dict, lines: list[AsmLine]) -> Optional[int]:
    canon = lv["_canonical"]
    for i, line in enumerate(lines):
        if i >= len(canon):
            return line.row  # extra line the solution does not have
        if (line.indent, line.text) != canon[i]:
            return line.row
    return None


def _unused_distractors(lv: dict, lines: list[AsmLine]) -> int:
    # text multiset of tokens the canonical solution needs; any placed token beyond it is a distractor
    needed = Counter()
    for row in lv["solution"]:
        for tid in row["tokens"]:
            needed[lv["_tokens"][tid]["text"]] += 1
    placed = Counter(t for line in lines for t in line.texts)
    extra = sum(max(0, placed[t] - needed[t]) for t in placed)
    total = sum(1 for t in lv["tokens"] if t["is_distractor"])
    return max(0, total - extra)


# --------------------------------------------------------------------------- judging


def run_level(lv: dict, rows: list[dict], *, include_trace: bool = False,
              prediction: Optional[str] = None, target_output: Optional[str] = None) -> dict:
    lines = assemble(lv, rows)
    expected = lv["expected_output"] if target_output is None else target_output
    base = {"passed": False, "error_group": None, "row": None, "message": "", "actual_output": None,
            "expected_output": expected, "code": "", "unused_distractors": None}
    trace = V.ExecutionTrace() if include_trace else None
    if include_trace:
        base["trace"] = {"steps": [], "truncated": False}
    if prediction is not None:
        base["prediction"] = {"correct": None}
    if not lines:
        base.update(error_group="empty", message="Bàn chơi đang trống. Hãy kéo các mảnh mã lên các hàng.")
        return base

    code = "\n".join(l.source for l in lines)
    base["code"] = code
    res = V.run_program(code, trace=trace)
    if trace is not None:
        base["trace"] = {
            "steps": [
                {"row": lines[step.lineno - 1].row, "code": lines[step.lineno - 1].source,
                 "scope": None if step.scope == "<module>" else step.scope,
                 "bindings": step.bindings, "output": step.output}
                for step in trace.steps
            ],
            "truncated": trace.truncated,
        }

    if not res.ok:
        base.update(
            error_group=res.error_group, message=res.message or "Chương trình bị lỗi.",
            row=_row_of_lineno(lines, res.lineno),
            actual_output=V.normalize_output(res.output) if res.output else None,
        )
        if res.error_group == "missing_colon" and res.message:
            base["message"] = f"{res.message} (dòng {res.lineno})" if res.lineno else res.message
        return base

    actual = V.normalize_output(res.output)
    base["actual_output"] = actual
    if prediction is not None:
        base["prediction"]["correct"] = V.normalize_output(prediction) == actual

    names = {type(n).__name__ for n in ast.walk(res.tree)}
    missing = [c for c in lv.get("required_constructs", []) if c not in names]
    if missing:
        what = ", ".join(CONSTRUCT_NAMES_VI.get(c, c) for c in missing)
        base.update(error_group="missing_construct", message=f"Thiếu cấu trúc bắt buộc: {what}.")
        return base

    if actual != V.normalize_output(expected):
        group = "output_mismatch"
        # same lines, same indents, only reordered -> an ordering problem
        if sorted((l.indent, l.text) for l in lines) == sorted(lv["_canonical"]):
            group = "wrong_order"
        base.update(error_group=group, message=V.mismatch_message(actual, expected),
                    row=_first_diff_row(lv, lines))
        return base

    base.update(passed=True, message="Chính xác! Chương trình in đúng đầu ra.",
                unused_distractors=_unused_distractors(lv, lines))
    return base


def canonical_rows(lv: dict) -> list[dict]:
    """The canonical solution as a board payload (used by tests)."""
    out = []
    for ridx, row in enumerate(lv["solution"]):
        col, toks = row["indent"], []
        for tid in row["tokens"]:
            toks.append({"id": tid, "col": col})
            col += lv["_tokens"][tid]["w"]
        out.append({"row": ridx, "tokens": toks})
    return out


def practice_rows(lv: dict) -> list[dict]:
    """Start with a runnable board which exhibits the authored mistake."""
    rows = canonical_rows(lv)
    change = lv.get("practice")
    if not change:
        raise RowsError("Màn này chưa có bài luyện.")
    if "row" in change:
        row = rows[change["row"]]
        offset = change["indent"] - row["tokens"][0]["col"]
        for token in row["tokens"]:
            token["col"] += offset
    else:
        token = next(t for row in rows for t in row["tokens"] if t["id"] == change["replace"])
        token["id"] = change["with"]
    return rows


def run_twist(lv: dict, original: list[dict], changed: list[dict], *, include_trace: bool) -> dict:
    target = lv.get("twist_output")
    if target is None or not run_level(lv, original)["passed"]:
        raise RowsError("Hãy hoàn thành màn trước khi bắt đầu thử thách.")
    result = run_level(lv, changed, include_trace=include_trace, target_output=target)
    before = {(r["row"], t["col"]): t["id"] for r in original for t in r["tokens"]}
    after = {(r["row"], t["col"]): t["id"] for r in changed for t in r["tokens"]}
    if before.keys() != after.keys() or sum(before[pos] != after[pos] for pos in before) != 1:
        raise RowsError("Thay đúng một mảnh mã ở cùng vị trí.")
    return result
