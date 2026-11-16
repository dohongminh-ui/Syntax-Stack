"""Restricted Python runner + error classification, shared by Code Rescue and Syntax Rows.

Safety model
------------
1. The source is parsed with ``ast.parse`` and every node must be on a whitelist
   (no imports, attribute access, lambdas, comprehensions, try/with/class, dunder names...).
2. Calls are only allowed to a small set of builtins and to functions defined in the same program.
3. The program runs with a minimal ``__builtins__`` dict, a captured ``print``, a line-step limit
   (``sys.settrace``), a wall-clock limit and an output cap.

Running in-process is acceptable because the inputs are only ever assembled from fragments of the
content bank (Code Rescue puzzles, Syntax Rows token trays); the AST whitelist is still mandatory.
"""
from __future__ import annotations

import ast
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

# --------------------------------------------------------------------------- limits

STEP_LIMIT = 20_000
TIME_LIMIT_S = 1.5
OUTPUT_CAP = 2048
TRACE_LIMIT = 48
MAX_SOURCE_CHARS = 4000
MAX_INT_CONSTANT = 10**6
MAX_STR_CONSTANT = 200

ALLOWED_CALLS = frozenset(
    {"print", "range", "len", "str", "int", "float", "abs", "min", "max", "sum", "round"}
)

ALLOWED_NODES: tuple[type, ...] = (
    ast.Module, ast.Expr, ast.Assign, ast.AugAssign, ast.Name, ast.Constant,
    ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.If, ast.IfExp,
    ast.For, ast.While, ast.Break, ast.Continue, ast.Pass,
    ast.FunctionDef, ast.arguments, ast.arg, ast.Return, ast.Call,
    ast.List, ast.Tuple, ast.Subscript, ast.Slice,
    ast.JoinedStr, ast.FormattedValue, ast.keyword,
    # context nodes
    ast.Load, ast.Store,
    # operators (no Pow / shifts: they can blow up CPU or memory in a single bytecode)
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod,
    ast.USub, ast.UAdd, ast.Not,
    ast.And, ast.Or,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Is, ast.IsNot, ast.In, ast.NotIn,
)

_NODE_NAMES_VI = {
    "Import": "import", "ImportFrom": "import", "Attribute": "dấu chấm truy cập thuộc tính",
    "Lambda": "lambda", "ListComp": "list comprehension", "SetComp": "comprehension",
    "DictComp": "comprehension", "GeneratorExp": "generator", "Global": "global",
    "Nonlocal": "nonlocal", "With": "with", "Try": "try", "ClassDef": "class",
    "Pow": "phép lũy thừa **", "Dict": "dict", "Set": "set", "Starred": "dấu *",
    "AsyncFunctionDef": "async", "Delete": "del", "Assert": "assert", "Raise": "raise",
    "AnnAssign": "chú thích kiểu", "Yield": "yield", "Await": "await",
}

SAFE_BUILTIN_NAMES = ("range", "len", "str", "int", "float", "abs", "min", "max", "sum", "round")


_RECURSION_LOCK = threading.Lock()


class UnsafeCode(Exception):
    """Raised when the AST whitelist rejects a program."""

    def __init__(self, reason: str, lineno: Optional[int] = None):
        super().__init__(reason)
        self.reason = reason
        self.lineno = lineno


class _Abort(BaseException):
    """Internal: stops the user program (step / time / output limit)."""

    def __init__(self, kind: str):
        super().__init__(kind)
        self.kind = kind


# --------------------------------------------------------------------------- AST check


def check_ast(tree: ast.AST) -> None:
    """Raise ``UnsafeCode`` if the tree contains anything outside the whitelist."""
    defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    allowed_call_names = ALLOWED_CALLS | defined

    for node in ast.walk(tree):
        line = getattr(node, "lineno", None)
        if not isinstance(node, ALLOWED_NODES):
            kind = type(node).__name__
            raise UnsafeCode(_NODE_NAMES_VI.get(kind, kind), line)
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise UnsafeCode(f"tên bắt đầu bằng dấu gạch dưới ({node.id})", line)
        if isinstance(node, ast.arg):
            if node.arg.startswith("_"):
                raise UnsafeCode(f"tên bắt đầu bằng dấu gạch dưới ({node.arg})", line)
            if node.annotation is not None:
                raise UnsafeCode("chú thích kiểu", line)
        if isinstance(node, ast.FunctionDef):
            if node.name.startswith("_"):
                raise UnsafeCode(f"tên hàm bắt đầu bằng dấu gạch dưới ({node.name})", line)
            if node.decorator_list or node.returns is not None or node.type_params:
                raise UnsafeCode("decorator hoặc chú thích kiểu", line)
            a = node.args
            if a.vararg or a.kwarg or a.kwonlyargs or a.posonlyargs:
                raise UnsafeCode("tham số đặc biệt (*args, **kwargs)", line)
        if isinstance(node, ast.keyword):
            if node.arg is None or node.arg.startswith("_"):
                raise UnsafeCode("đối số từ khóa không hợp lệ", line)
        if isinstance(node, ast.Call):
            f = node.func
            if not isinstance(f, ast.Name) or f.id not in allowed_call_names:
                name = f.id if isinstance(f, ast.Name) else "biểu thức"
                raise UnsafeCode(f"gọi hàm không được phép ({name})", line)
        if isinstance(node, ast.Constant):
            v = node.value
            if isinstance(v, bool) or v is None:
                continue
            if isinstance(v, int) and abs(v) > MAX_INT_CONSTANT:
                raise UnsafeCode("số quá lớn", line)
            if isinstance(v, str) and len(v) > MAX_STR_CONSTANT:
                raise UnsafeCode("chuỗi quá dài", line)
            if isinstance(v, (bytes, complex)):
                raise UnsafeCode("kiểu dữ liệu không hỗ trợ", line)
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if not isinstance(t, (ast.Name, ast.Tuple, ast.Subscript)):
                    raise UnsafeCode("phép gán không hợp lệ", line)


# --------------------------------------------------------------------------- results


@dataclass
class RunResult:
    ok: bool
    output: str = ""
    # None | "syntax" | "unsafe" | "runtime" | "limit"
    error_kind: Optional[str] = None
    error_group: Optional[str] = None
    message: Optional[str] = None  # short Vietnamese description of the error
    lineno: Optional[int] = None
    exc_name: Optional[str] = None
    tree: Optional[ast.AST] = field(default=None, repr=False)


@dataclass
class TraceStep:
    lineno: int
    scope: str
    bindings: dict[str, str]
    output: str


@dataclass
class ExecutionTrace:
    steps: list[TraceStep] = field(default_factory=list)
    truncated: bool = False



# --------------------------------------------------------------------------- helpers


def normalize_output(s: str) -> str:
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in s.split("\n")).rstrip("\n")


def describe_output(s: str) -> str:
    """Inline description used in messages: 0, 1, 2 (empty -> 'không in gì')."""
    s = normalize_output(s)
    if not s:
        return "không in gì"
    return ", ".join(s.split("\n"))


def _classify_syntax_error(exc: SyntaxError) -> tuple[str, str]:
    msg = (exc.msg or "").lower()
    if isinstance(exc, IndentationError) or "indent" in msg:
        if "expected an indented block" in msg:
            return "bad_indent", "Thiếu thụt lề: dòng sau lệnh kết thúc bằng dấu hai chấm cần được thụt vào."
        if "unexpected indent" in msg:
            return "bad_indent", "Dòng này bị thụt lề không đúng chỗ."
        return "bad_indent", "Thụt lề chưa đúng."
    if "expected ':'" in msg:
        return "missing_colon", "Thiếu dấu hai chấm ':' ở cuối lệnh."
    if "'return' outside function" in msg:
        return "syntax", "Lệnh return chỉ dùng được bên trong hàm."
    return "syntax", "Sai cú pháp: Python không hiểu dòng này."


def _runtime_message(exc: BaseException, lineno: Optional[int]) -> str:
    where = f" (dòng {lineno})" if lineno else ""
    name = type(exc).__name__
    text = str(exc)
    if isinstance(exc, NameError):
        var = getattr(exc, "name", None)
        return f"Tên '{var}' chưa được tạo trước khi dùng{where}." if var else f"Có tên chưa được tạo{where}."
    if isinstance(exc, TypeError):
        if "concatenate str" in text or "can only concatenate" in text:
            return f"Không thể cộng chuỗi với số{where}; hãy đổi số thành chuỗi bằng str()."
        if "positional argument" in text:
            return f"Số đối số khi gọi hàm không khớp với khai báo{where}."
        return f"Phép toán không hợp lệ giữa các kiểu dữ liệu{where} (TypeError)."
    if isinstance(exc, ZeroDivisionError):
        return f"Không thể chia cho 0{where}."
    if isinstance(exc, RecursionError):
        return f"Hàm gọi lại chính nó quá nhiều lần{where}."
    if isinstance(exc, (IndexError, KeyError)):
        return f"Truy cập vị trí không tồn tại{where}."
    if isinstance(exc, ValueError):
        return f"Giá trị không hợp lệ{where}."
    return f"Chương trình báo lỗi {name}{where}."


# --------------------------------------------------------------------------- runner


def _make_print(buf: list[str], size: list[int]):
    def _print(*args, sep=" ", end="\n"):
        if sep is None:
            sep = " "
        if end is None:
            end = "\n"
        if not isinstance(sep, str) or not isinstance(end, str):
            raise TypeError("sep và end phải là chuỗi")
        text = sep.join(str(a) for a in args) + end
        size[0] += len(text)
        if size[0] > OUTPUT_CAP:
            raise _Abort("output")
        buf.append(text)

    _print.__name__ = "print"
    return _print


def _defined_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            names.add(n.id)
        elif isinstance(n, ast.FunctionDef):
            names.add(n.name)
            names.update(a.arg for a in n.args.args)
    return names


def _trace_bindings(values) -> dict[str, str]:
    bindings = {}
    for name, value in values.items():
        if name.startswith("__"):
            continue
        kind = type(value)
        if kind is str:
            bindings[name] = repr(value if len(value) <= 60 else value[:59] + "…")
        elif kind is int:
            bindings[name] = repr(value) if value.bit_length() <= 256 else "…"
        elif kind in (bool, float, type(None)):
            bindings[name] = repr(value)
    return bindings


def run_program(code: str, *, trace: Optional[ExecutionTrace] = None) -> RunResult:
    """Parse, whitelist-check and execute ``code``. Never raises for bad user code."""
    if len(code) > MAX_SOURCE_CHARS:
        return RunResult(False, error_kind="unsafe", error_group="syntax", message="Chương trình quá dài.")
    try:
        tree = ast.parse(code, filename="<puzzle>")
    except SyntaxError as e:
        group, msg = _classify_syntax_error(e)
        return RunResult(False, error_kind="syntax", error_group=group, message=msg, lineno=e.lineno,
                         exc_name=type(e).__name__)
    except (ValueError, RecursionError, MemoryError) as e:  # null bytes, absurd nesting
        return RunResult(False, error_kind="syntax", error_group="syntax",
                         message="Sai cú pháp: Python không hiểu chương trình này.", exc_name=type(e).__name__)

    try:
        check_ast(tree)
    except UnsafeCode as e:
        return RunResult(False, error_kind="unsafe", error_group="syntax",
                         message=f"Chương trình dùng thứ chưa được hỗ trợ: {e.reason}.",
                         lineno=e.lineno, exc_name="UnsafeCode", tree=tree)

    try:
        compiled = compile(tree, "<puzzle>", "exec")
    except SyntaxError as e:  # e.g. 'return' outside function
        group, msg = _classify_syntax_error(e)
        return RunResult(False, error_kind="syntax", error_group=group, message=msg, lineno=e.lineno,
                         exc_name=type(e).__name__, tree=tree)
    except (ValueError, RecursionError, MemoryError):
        return RunResult(False, error_kind="syntax", error_group="syntax",
                         message="Sai cú pháp: Python không hiểu chương trình này.", tree=tree)

    buf: list[str] = []
    size = [0]
    safe_builtins = {"print": _make_print(buf, size)}
    import builtins as _b
    for name in SAFE_BUILTIN_NAMES:
        safe_builtins[name] = getattr(_b, name)
    glb = {"__builtins__": safe_builtins, "__name__": "puzzle"}

    steps = 0
    deadline = time.monotonic() + TIME_LIMIT_S
    previous_lines: dict[int, int] = {}

    def local_trace(frame, event, arg):
        nonlocal steps
        # The next event in a frame sees the effects of that frame's previous line.
        if trace is not None and not trace.truncated and event in ("line", "return"):
            frame_id = id(frame)
            previous = previous_lines.pop(frame_id, None)
            if previous is not None:
                if len(trace.steps) == TRACE_LIMIT:
                    trace.truncated = True
                else:
                    trace.steps.append(TraceStep(previous, frame.f_code.co_name,
                                                 _trace_bindings(frame.f_locals), "".join(buf)))
            if event == "line":
                previous_lines[frame_id] = frame.f_lineno
        if event == "line":
            steps += 1
            if steps > STEP_LIMIT:
                raise _Abort("steps")
            if (steps & 0x3FF) == 0 and time.monotonic() > deadline:
                raise _Abort("time")
        return local_trace

    def global_trace(frame, event, arg):
        if frame.f_code.co_filename == "<puzzle>":
            return local_trace
        return None

    error: Optional[BaseException] = None
    tb_line: Optional[int] = None
    try:
        # The recursion limit is process-wide, so set -> run -> restore is serialised.
        with _RECURSION_LOCK:
            old_trace = sys.gettrace()
            old_limit = sys.getrecursionlimit()
            try:
                sys.setrecursionlimit(min(old_limit, 400))
                sys.settrace(global_trace)
                exec(compiled, glb)
            finally:
                sys.settrace(old_trace)
                sys.setrecursionlimit(old_limit)
    except _Abort as a:
        output = "".join(buf)
        if a.kind == "output":
            msg = "Chương trình in ra quá nhiều dòng."
        else:
            msg = "Chương trình chạy quá lâu, có thể có vòng lặp vô hạn."
        return RunResult(False, output=output, error_kind="limit", error_group="output_mismatch",
                         message=msg, exc_name=a.kind, tree=tree)
    except BaseException as e:  # noqa: BLE001 - user program errors
        error = e
        tb = e.__traceback__
        while tb is not None:
            if tb.tb_frame.f_code.co_filename == "<puzzle>":
                tb_line = tb.tb_lineno
            tb = tb.tb_next

    output = "".join(buf)
    if error is None:
        return RunResult(True, output=output, tree=tree)

    group = "syntax"
    if isinstance(error, NameError):
        var = getattr(error, "name", None)
        if var and var in _defined_names(tree):
            group = "wrong_order"
    return RunResult(False, output=output, error_kind="runtime", error_group=group,
                     message=_runtime_message(error, tb_line), lineno=tb_line,
                     exc_name=type(error).__name__, tree=tree)


# --------------------------------------------------------------------------- diagnosis


@dataclass
class Diagnosis:
    passed: bool
    error_group: Optional[str]
    message: str
    actual_output: Optional[str]
    lineno: Optional[int] = None
    run: Optional[RunResult] = field(default=None, repr=False)


def mismatch_message(actual: str, expected: str) -> str:
    got = "không in gì" if not normalize_output(actual) else f"in {describe_output(actual)}"
    return f"Đầu ra không khớp: chương trình {got} nhưng cần {describe_output(expected)}."


def diagnose(code: str, expected_output: str) -> Diagnosis:
    """Run ``code`` and compare with ``expected_output``; classify the failure if any."""
    res = run_program(code)
    if not res.ok:
        actual = normalize_output(res.output) if res.output else None
        return Diagnosis(False, res.error_group, res.message or "Chương trình bị lỗi.", actual, res.lineno, res)
    actual = normalize_output(res.output)
    if actual == normalize_output(expected_output):
        return Diagnosis(True, None, "Chính xác! Chương trình in đúng đầu ra.", actual, None, res)
    return Diagnosis(False, "output_mismatch", mismatch_message(actual, expected_output), actual, None, res)
