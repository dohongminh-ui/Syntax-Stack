"""Puzzles from a learner's own program ("paste your code").

Two halves with very different trust levels:

* ``prepare_source`` / ``infer_topic`` / ``find_seq_multiplication`` only *read* the text (parse and
  walk the AST). The web server calls them before anything runs.
* ``generate`` EXECUTES the learner's program and many edited copies of it (through
  ``validator.run_program``). It must only ever run inside the sandbox child process
  (``sandbox_worker``). ``ENABLED`` is switched on by the worker; calling ``generate`` anywhere else
  raises, so a future endpoint cannot run pasted code inside the web server by accident.
"""
from __future__ import annotations

import ast
import hashlib
import io
import random
import re
import time
import tokenize
from dataclasses import dataclass
from typing import Optional

from . import validator as V
from .puzzle_tools import (
    _INT, Drop, _outside_strings, build_bug_form, join_lines, mutations, output_ok, place_options,
    letter, split_lines,
)

MAX_CODE_CHARS = 800
MIN_LINES, MAX_LINES = 2, 15
MAX_PARSONS_INDENT = 2          # bank._check_parsons accepts indent 0..2 only
GENERATION_BUDGET_S = 2.5       # stop starting new work after this (the child also has a hard limit)
MAX_MUTATION_RUNS = 150
TYPE_ORDER = ("predict_output", "find_bug", "fill_blank", "parsons")

# Set by sandbox_worker.main(). Never set in the web server process.
ENABLED = False


class InvalidSource(Exception):
    """The pasted program is rejected before anything runs. ``str(exc)`` is a Vietnamese reason."""


# --------------------------------------------------------------------------- reading the text


def _strip_comments(text: str) -> str:
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, SyntaxError, ValueError, RecursionError, MemoryError):
        return "\n".join(l for l in text.split("\n") if not l.lstrip().startswith("#"))
    lines = text.split("\n")
    for tok in tokens:
        if tok.type == tokenize.COMMENT:
            row, col = tok.start
            lines[row - 1] = lines[row - 1][:col]
    return "\n".join(lines)


def _seqish(node: ast.AST, tainted: set[str], seq_funcs: set[str]) -> bool:
    """True when the expression is (probably) a string or a list/tuple."""
    if isinstance(node, (ast.List, ast.Tuple, ast.JoinedStr)):
        return True
    if isinstance(node, ast.Constant):
        return isinstance(node.value, (str, bytes))
    if isinstance(node, ast.Name):
        return node.id in tainted
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return node.func.id == "str" or node.func.id in seq_funcs
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mult, ast.Mod)):
        return _seqish(node.left, tainted, seq_funcs) or (
            not isinstance(node.op, ast.Mod) and _seqish(node.right, tainted, seq_funcs))
    if isinstance(node, ast.IfExp):
        return _seqish(node.body, tainted, seq_funcs) or _seqish(node.orelse, tainted, seq_funcs)
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice):
        return _seqish(node.value, tainted, seq_funcs)
    return False


def find_seq_multiplication(tree: ast.AST) -> Optional[int]:
    """Line number of a ``*`` where an operand is (probably) a string or list, else ``None``.

    ``"ab" * n`` and ``items * n`` allocate n copies in one step, which the step counter cannot
    interrupt. This is a static, best-effort check (names are tracked through plain assignments); the
    sandbox limits are the real defence for what it cannot see.
    """
    tainted: set[str] = set()
    seq_funcs: set[str] = set()
    for _ in range(6):
        before = (len(tainted), len(seq_funcs))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and _seqish(node.value, tainted, seq_funcs):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        tainted.add(target.id)
            elif (isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name)
                  and isinstance(node.op, ast.Add) and _seqish(node.value, tainted, seq_funcs)):
                tainted.add(node.target.id)
            elif isinstance(node, ast.FunctionDef):
                for inner in ast.walk(node):
                    if (isinstance(inner, ast.Return) and inner.value is not None
                            and _seqish(inner.value, tainted, seq_funcs)):
                        seq_funcs.add(node.name)
        if before == (len(tainted), len(seq_funcs)):
            break
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
            if _seqish(node.left, tainted, seq_funcs) or _seqish(node.right, tainted, seq_funcs):
                return node.lineno
        if isinstance(node, ast.AugAssign) and isinstance(node.op, ast.Mult):
            if _seqish(node.value, tainted, seq_funcs) or (
                    isinstance(node.target, ast.Name) and node.target.id in tainted):
                return node.lineno
    return None


def prepare_source(raw: str) -> tuple[str, ast.Module]:
    """Validate and normalise pasted code. Returns ``(clean_code, tree)`` or raises ``InvalidSource``.

    Normalisation: line endings unified, comments and blank lines removed, trailing spaces cut.
    Nothing here executes the code.
    """
    if len(raw) > MAX_CODE_CHARS:
        raise InvalidSource(f"Đoạn mã quá dài: tối đa {MAX_CODE_CHARS} ký tự.")
    if "\t" in raw:
        raise InvalidSource("Đoạn mã có ký tự Tab. Hãy thụt lề bằng 4 dấu cách.")
    if "\x00" in raw:
        raise InvalidSource("Đoạn mã có ký tự không hợp lệ.")
    text = _strip_comments(raw.replace("\r\n", "\n").replace("\r", "\n"))
    lines = [l.rstrip() for l in text.split("\n") if l.strip()]
    if len(lines) < MIN_LINES:
        raise InvalidSource(f"Đoạn mã quá ngắn: cần ít nhất {MIN_LINES} dòng lệnh.")
    if len(lines) > MAX_LINES:
        raise InvalidSource(f"Đoạn mã quá dài: tối đa {MAX_LINES} dòng lệnh.")
    for n, line in enumerate(lines, 1):
        indent = len(line) - len(line.lstrip(" "))
        if indent % 4:
            raise InvalidSource(f"Dòng {n} thụt lề {indent} dấu cách. Hãy thụt lề theo bội số của 4 dấu cách.")
    code = "\n".join(lines)
    try:
        tree = ast.parse(code, filename="<custom>")
    except SyntaxError as e:
        _, msg = V._classify_syntax_error(e)
        raise InvalidSource(f"{msg} (dòng {e.lineno})" if e.lineno else msg) from None
    except (ValueError, RecursionError, MemoryError):
        raise InvalidSource("Sai cú pháp: Python không hiểu đoạn mã này.") from None
    try:
        V.check_ast(tree)
    except V.UnsafeCode as e:
        where = f" (dòng {e.lineno})" if e.lineno else ""
        raise InvalidSource(f"Đoạn mã dùng thứ chưa được hỗ trợ: {e.reason}{where}.") from None
    bad = find_seq_multiplication(tree)
    if bad is not None:
        raise InvalidSource(f"Chưa hỗ trợ phép nhân chuỗi hoặc danh sách (dòng {bad}).")
    return code, tree


def infer_topic(tree: ast.AST) -> str:
    nodes = list(ast.walk(tree))
    if any(isinstance(n, ast.FunctionDef) for n in nodes):
        return "functions"
    if any(isinstance(n, (ast.For, ast.While)) for n in nodes):
        return "loops"
    if any(isinstance(n, (ast.If, ast.IfExp)) for n in nodes):
        return "conditions"
    return "variables"


# --------------------------------------------------------------------------- authored text

HINTS = {
    "predict_output": [
        "Hãy chạy chương trình từng dòng theo thứ tự, giống như máy tính.",
        "Ghi lại giá trị của các biến sau mỗi dòng (và sau mỗi vòng lặp nếu có).",
        "Chỉ lệnh print() mới tạo ra đầu ra: đếm xem print chạy mấy lần và in giá trị nào mỗi lần.",
    ],
    "find_bug": [
        "Chương trình chạy được nhưng in sai: lỗi thường là một con số hoặc một phép toán bị đổi.",
        "So sánh kết quả mong muốn với những gì chương trình đang in để đoán dòng nào làm lệch kết quả.",
        "Thử thay từng lựa chọn vào đúng dòng đó rồi chạy tay: chỉ một cách sửa cho ra đúng kết quả.",
    ],
    "fill_blank": [
        "Chỗ trống là một con số hoặc một phép toán: nó quyết định kết quả cuối cùng.",
        "Chạy tay chương trình với từng lựa chọn rồi đối chiếu với đầu ra mong muốn.",
        "Loại các lựa chọn cho ra đầu ra khác yêu cầu; chỉ một lựa chọn in đúng kết quả.",
    ],
    "parsons": [
        "Dòng nào tạo ra giá trị thì phải đứng trước dòng dùng giá trị đó.",
        "Dòng kết thúc bằng dấu hai chấm mở một khối: các dòng thuộc khối đó phải thụt vào.",
        "Đặt dòng khởi tạo trước, rồi vòng lặp hoặc điều kiện, rồi các dòng print theo đúng ý của chương trình.",
    ],
}

_TOKEN = re.compile(r"\d+|==|!=|<=|>=|//|\w+|\S")


def describe_edit(old: str, new: str) -> str:
    """Short Vietnamese description of how ``new`` differs from ``old`` (one token, else generic)."""
    a, b = _TOKEN.findall(old), _TOKEN.findall(new)
    if len(a) == len(b):
        diff = [(x, y) for x, y in zip(a, b) if x != y]
        if len(diff) == 1:
            x, y = diff[0]
            if x.isdigit() and y.isdigit():
                return f"con số {x} bị đổi thành {y}"
            return f"phép toán `{x}` bị đổi thành `{y}`"
    return "dòng này bị chỉnh sửa"


# --------------------------------------------------------------------------- running (sandbox only)


def _require_sandbox() -> None:
    if not ENABLED:
        raise RuntimeError("custom_gen.generate runs pasted code and may only run in the sandbox worker")


@dataclass
class _Mut:
    line: int
    text: str
    diag: V.Diagnosis

    @property
    def ran(self) -> bool:
        return self.diag.run is not None and self.diag.run.ok


class _Evaluator:
    """Runs edited copies of the program. Skips anything that would multiply a string or list."""

    def __init__(self, expected: str):
        self.expected = expected
        self._cache: dict[str, Optional[V.Diagnosis]] = {}

    def diagnose(self, items: list[tuple[int, str]]) -> Optional[V.Diagnosis]:
        code = join_lines(items)
        if code not in self._cache:
            result: Optional[V.Diagnosis]
            try:
                tree = ast.parse(code)
            except (SyntaxError, ValueError, RecursionError, MemoryError):
                tree = None
            if tree is not None and find_seq_multiplication(tree) is not None:
                result = None
            else:
                result = V.diagnose(code, self.expected)
            self._cache[code] = result
        return self._cache[code]


def _replace(items, idx, text):
    out = list(items)
    out[idx] = (items[idx][0], text)
    return out


def _options(correct: dict, wrong: list[dict], rng: random.Random) -> list[dict]:
    slots = place_options(4, rng)
    opts: list = [None] * 4
    opts[slots[0]] = correct
    for k, d in enumerate(wrong):
        opts[slots[k + 1]] = d
    for i, o in enumerate(opts):
        o["id"] = letter(i)
    return opts


def _inline(expected: str) -> str:
    return ", ".join(expected.split("\n"))


def _make_predict(code, items, expected, muts, rng):
    seen, picked, used_lines = {expected}, [], set()
    for pass_no in (0, 1):  # first pass: one distractor per edited line, second pass: fill up
        for mu in muts:
            if len(picked) == 3:
                break
            out = mu.diag.actual_output
            if not mu.ran or not out or out in seen or not output_ok(out):
                continue
            if pass_no == 0 and mu.line in used_lines:
                continue
            seen.add(out)
            used_lines.add(mu.line)
            picked.append(mu)
    if len(picked) < 3:
        raise Drop("Không tìm được 3 đầu ra sai khác nhau để làm đáp án nhiễu.")
    correct = {"text": expected, "correct": True, "name": None, "group": None, "note": None}
    wrong = [{"text": mu.diag.actual_output, "correct": False, "name": "edited_line", "group": "wrong_choice",
              "note": f"Đầu ra này chỉ xảy ra nếu dòng {mu.line + 1} bị đổi ({describe_edit(items[mu.line][1], mu.text)})."}
             for mu in picked]
    return {
        "type": "predict_output", "prompt": "Chương trình dưới đây in ra kết quả nào?", "code": code,
        "expected_output": expected, "solution_code": code,
        "explanation": (f"Chương trình thật sự in ra: {_inline(expected)}. Hãy chạy từng dòng và ghi lại giá trị "
                        "biến sau mỗi bước; các đáp án khác là đầu ra của những phiên bản chương trình bị sửa một chút."),
        "hints": HINTS["predict_output"], "data": {"options": _options(correct, wrong, rng)},
    }


def _make_bug(code, items, expected, muts, rng):
    cands = [mu for mu in muts if not mu.diag.passed]
    cands.sort(key=lambda mu: not mu.ran)  # stable: bugs that still run (wrong output, no crash) first
    if not cands:
        raise Drop("Mọi chỉnh sửa nhỏ đều cho đúng kết quả cũ, không tạo được lỗi rõ ràng.")
    for bug in cands[:10]:
        fix = items[bug.line][1]
        buggy_items = _replace(items, bug.line, bug.text)
        wrong_fixes = [
            {"name": "edited_bug_line", "text": m.text,
             "note": f"Với dòng này, {describe_edit(fix, m.text)} so với dòng đúng nên chương trình vẫn in sai."}
            for m in muts if m.line == bug.line and m.text != bug.text and not m.diag.passed][:3]
        try:
            form = build_bug_form(buggy_items, bug.line, fix, wrong_fixes, expected, rng)
        except (Drop, AssertionError):
            continue
        return {
            "type": "find_bug",
            "prompt": f"Chương trình in sai kết quả. Chọn cách sửa đúng để in ra {_inline(expected)}.",
            "code": None, "expected_output": expected, "solution_code": code,
            "explanation": (f"Lỗi nằm ở dòng {bug.line + 1}: `{bug.text}` cần sửa thành `{fix}` để in ra "
                            f"{_inline(expected)}. Sửa một dòng khác, hoặc sửa dòng này theo cách khác, vẫn cho kết quả sai."),
            "hints": HINTS["find_bug"], "data": form,
        }
    raise Drop("Không dựng được đủ phương án sửa khác nhau cho một lỗi (đoạn mã quá ngắn hoặc quá đơn giản).")


_OP_TOKEN = re.compile(r"(?<= )(==|!=|<=|>=|//|[-+*/%<>])(?= )")
_OP_GROUPS = (("+", "-", "*", "//", "%", "/"), ("==", "!=", "<", "<=", ">", ">="))


def fragment_sites(text: str) -> list[tuple[int, int, str, str]]:
    """Blankable fragments of a line: ``(start, end, kind, fragment)``; never inside a string literal."""
    sites, offset = [], 0
    for is_str, chunk in _outside_strings(text):
        if not is_str:
            for m in _INT.finditer(chunk):
                s, e = offset + m.start(), offset + m.end()
                before = text[s - 1] if s > 0 else ""
                after = text[e] if e < len(text) else ""
                if before in ".-" or after == ".":
                    continue  # part of a float, or a negative number
                sites.append((s, e, "number", m.group(0)))
            for m in _OP_TOKEN.finditer(chunk):
                sites.append((offset + m.start(), offset + m.end(), "op", m.group(0)))
        offset += len(chunk)
    return sites


def _wrong_fragments(kind: str, frag: str) -> list[str]:
    if kind == "number":
        n = int(frag)
        values = [n + 1, n - 1, n + 2, n - 2, 0, 1, n * 2, 10]
        out = []
        for v in values:
            if 0 <= v <= 1000 and str(v) != frag and str(v) not in out:
                out.append(str(v))
        return out
    for group in _OP_GROUPS:
        if frag in group:
            return [o for o in group if o != frag]
    return []


def _make_fill(code, items, expected, ev, rng, deadline):
    if "___" in code:
        raise Drop("Mã có chuỗi ___ nên không thể làm chỗ trống.")
    sites = [(i, s) for i, (_, text) in enumerate(items) for s in fragment_sites(text)]
    if not sites:
        raise Drop("Không có số hoặc phép toán nào để làm chỗ trống.")
    rng.shuffle(sites)
    for i, (start, end, kind, frag) in sites[:12]:
        if time.monotonic() > deadline:
            raise Drop("Hết thời gian xử lý.")
        text = items[i][1]
        found = []
        for alt in _wrong_fragments(kind, frag):
            d = ev.diagnose(_replace(items, i, text[:start] + alt + text[end:]))
            if d is None or d.passed:
                continue
            found.append((alt, d))
        if len(found) < 3:
            continue
        # prefer wrong answers that give different outputs from each other
        picked, outputs = [], set()
        for alt, d in found:
            key = d.actual_output if d.actual_output is not None else d.message
            if key not in outputs:
                outputs.add(key)
                picked.append((alt, d))
        for alt, d in found:
            if len(picked) >= 3:
                break
            if (alt, d) not in picked:
                picked.append((alt, d))
        picked = picked[:3]
        skeleton_items = _replace(items, i, text[:start] + "___" + text[end:])
        skeleton = join_lines(skeleton_items)
        what = "con số" if kind == "number" else "phép toán"
        correct = {"text": frag, "correct": True, "name": None, "group": None,
                   "actual_output": expected, "message": None, "note": None}
        wrong = [{"text": alt, "correct": False, "name": "wrong_fragment",
                  "group": d.error_group or "output_mismatch", "actual_output": d.actual_output,
                  "message": d.message, "note": f"Với `{alt}` ở chỗ trống, đầu ra khác với kết quả cần in."}
                 for alt, d in picked]
        return {
            "type": "fill_blank",
            "prompt": f"Điền {what} còn thiếu để chương trình in ra {_inline(expected)}.",
            "code": skeleton, "expected_output": expected, "solution_code": code,
            "explanation": (f"Điền `{frag}` vào chỗ trống thì chương trình in ra {_inline(expected)}. Mỗi lựa chọn khác "
                            "làm đầu ra thay đổi: hãy thay từng lựa chọn vào chương trình và chạy tay để thấy khác biệt."),
            "hints": HINTS["fill_blank"], "data": {"options": _options(correct, wrong, rng)},
        }
    raise Drop("Không có chỗ trống nào cho ra ít nhất 3 đáp án sai khác với đáp án đúng.")


def _make_parsons(code, items, expected, rng):
    n = len(items)
    if n < 3:
        raise Drop("Cần ít nhất 3 dòng để làm bài sắp xếp.")
    if len({t for _, t in items}) != n:
        raise Drop("Có dòng trùng nhau nên không thể kiểm tra thứ tự một cách chắc chắn.")
    if max(ind for ind, _ in items) > MAX_PARSONS_INDENT:
        raise Drop(f"Thụt lề sâu hơn {MAX_PARSONS_INDENT} mức, bài sắp xếp chỉ hỗ trợ tối đa {MAX_PARSONS_INDENT} mức.")
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
        raise Drop("Không tìm được cách xáo trộn làm chương trình in sai.")
    lines = [{"id": f"l{j + 1}", "text": items[perm[j]][1]} for j in range(n)]
    id_of = {perm[j]: f"l{j + 1}" for j in range(n)}
    solution = [{"line_id": id_of[i], "indent": items[i][0]} for i in range(n)]
    return {
        "type": "parsons",
        "prompt": f"Sắp xếp và thụt lề các dòng để chương trình in ra {_inline(expected)}.",
        "code": None, "expected_output": expected, "solution_code": code,
        "explanation": ("Chương trình chạy từ trên xuống dưới; các dòng thuộc một khối lệnh (sau dấu hai chấm) phải "
                        f"thụt vào 4 dấu cách. Sắp xếp đúng thì chương trình in ra {_inline(expected)}."),
        "hints": HINTS["parsons"], "data": {"lines": lines, "solution": solution, "distractors": []},
    }


def generate(raw_code: str) -> dict:
    """Run the program and build up to four verified puzzles from it. SANDBOX ONLY.

    Returns ``{"ok": False, "message": ...}`` for an unusable program, otherwise
    ``{"ok": True, "code", "expected_output", "puzzles": [...], "skipped": [{"type", "reason"}]}``.
    """
    _require_sandbox()
    deadline = time.monotonic() + GENERATION_BUDGET_S
    try:
        code, _ = prepare_source(raw_code)
    except InvalidSource as e:
        return {"ok": False, "message": str(e)}
    res = V.run_program(code)
    if not res.ok:
        if res.error_kind == "limit":
            return {"ok": False, "message": "Chương trình chạy quá lâu hoặc in quá nhiều dòng (có thể có vòng lặp vô hạn)."}
        if res.error_kind == "runtime":
            return {"ok": False, "message": f"Chương trình bị lỗi khi chạy: {res.message}"}
        return {"ok": False, "message": res.message or "Chương trình không chạy được."}
    expected = V.normalize_output(res.output)
    if not expected:
        return {"ok": False, "message": "Chương trình không in ra gì. Hãy dùng print() để in kết quả."}
    if not output_ok(expected):
        return {"ok": False, "message": "Đầu ra quá dài: tối đa 5 dòng và mỗi dòng không quá 40 ký tự."}

    items = split_lines(code)
    rng = random.Random(int(hashlib.sha1(code.encode("utf-8")).hexdigest()[:16], 16))
    ev = _Evaluator(expected)

    table = [(i, m) for i, (_, text) in enumerate(items) for m in mutations(text)]
    rng.shuffle(table)
    muts: list[_Mut] = []
    for i, m in table[:MAX_MUTATION_RUNS]:
        if time.monotonic() > deadline:
            break
        d = ev.diagnose(_replace(items, i, m))
        if d is not None:
            muts.append(_Mut(i, m, d))

    makers = {
        "predict_output": lambda: _make_predict(code, items, expected, muts, rng),
        "find_bug": lambda: _make_bug(code, items, expected, muts, rng),
        "fill_blank": lambda: _make_fill(code, items, expected, ev, rng, deadline),
        "parsons": lambda: _make_parsons(code, items, expected, rng),
    }
    puzzles, skipped = [], []
    for typ in TYPE_ORDER:
        if time.monotonic() > deadline:
            skipped.append({"type": typ, "reason": "Hết thời gian xử lý."})
            continue
        try:
            puzzles.append(makers[typ]())
        except Drop as e:
            skipped.append({"type": typ, "reason": str(e)})
    return {"ok": True, "code": code, "expected_output": expected, "puzzles": puzzles, "skipped": skipped}
