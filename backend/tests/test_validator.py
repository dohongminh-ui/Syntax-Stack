import time

import pytest

from app import validator as V


def run(code):
    return V.run_program(code)


@pytest.mark.parametrize("code,reason", [
    ("import os", "import"),
    ("from os import path", "import"),
    ("x = ().__class__", "thuộc tính"),
    ("print(().__class__.__bases__)", "thuộc tính"),
    ("x = __import__('os')", "__import__"),
    ("open('x')", "open"),
    ("eval('1+1')", "eval"),
    ("exec('print(1)')", "exec"),
    ("__builtins__", "gạch dưới"),
    ("_x = 1", "gạch dưới"),
    ("__name__", "gạch dưới"),
    ("def _f():\n    pass", "gạch dưới"),
    ("def f(__a):\n    pass", "gạch dưới"),
    ("f = lambda x: x", "lambda"),
    ("x = [i for i in range(3)]", "comprehension"),
    ("x = {1: 2}", "dict"),
    ("global x", "global"),
    ("with open('x') as f:\n    pass", "with"),
    ("try:\n    pass\nexcept:\n    pass", "try"),
    ("class A:\n    pass", "class"),
    ("print(2 ** 3)", "lũy thừa"),
    ("x = 10 ** 100", "lũy thừa"),
    ("undefined_fn(1)", "undefined_fn"),
    ("getattr(1, 'x')", "getattr"),
    ("x = 99999999999", "quá lớn"),
])
def test_rejects_unsafe(code, reason):
    r = run(code)
    assert not r.ok
    assert r.error_kind == "unsafe"
    assert r.error_group == "syntax"
    assert reason in r.message


def test_while_true_pass_returns_fast_and_fails_cleanly():
    t = time.monotonic()
    r = run("while True: pass")
    assert time.monotonic() - t < 2.0
    assert not r.ok and r.error_kind == "limit"
    assert "vô hạn" in r.message


def test_infinite_loop_with_body_and_output_cap():
    t = time.monotonic()
    r = run("x = 0\nwhile True:\n    x = x + 1\n    print(x)")
    assert time.monotonic() - t < 2.0
    assert not r.ok and r.error_kind == "limit"
    assert len(r.output) <= V.OUTPUT_CAP


def test_for_loop_step_limit():
    r = run("t = 0\nfor i in range(1000000):\n    t = t + i\nprint(t)")
    assert not r.ok and r.error_kind == "limit"


def test_trace_stops_recording_without_stopping_execution():
    trace = V.ExecutionTrace()
    result = V.run_program("for i in range(100):\n    last = i\nprint(last)", trace=trace)
    assert result.ok and result.output == "99\n"
    assert trace.truncated and len(trace.steps) == V.TRACE_LIMIT
    assert all(not step.output for step in trace.steps)


def test_runaway_recursion_is_an_error_not_a_crash():
    r = run("def f(x):\n    return f(x)\nprint(f(1))")
    assert not r.ok and r.error_kind == "runtime"


def test_runs_normal_program_and_captures_unicode():
    r = run('diem = 8\nif diem >= 5:\n    print("Đậu")\nprint(1, 2, sep="-")\nprint("a", end="")\nprint("b")')
    assert r.ok
    assert r.output == "Đậu\n1-2\nab\n"


def test_function_and_builtins():
    r = run("def f(x):\n    return x * 2\nprint(f(4), len('abc'), max(1, 5), round(2.6), str(3) + 'x')")
    assert r.ok and r.output == "8 3 5 3 3x\n"


def test_no_leaking_between_runs():
    run("x = 5")
    r = run("print(x)")
    assert not r.ok and r.error_kind == "runtime"


def test_error_classification():
    assert run("if 1 == 1\n    print(1)").error_group == "missing_colon"
    assert run("for i in range(3)\n    print(i)").error_group == "missing_colon"
    assert run("def f(x)\n    return x").error_group == "missing_colon"
    assert run("for i in range(3):\nprint(i)").error_group == "bad_indent"
    assert run("x = 1\n    y = 2").error_group == "bad_indent"
    assert run("x = = 1").error_group == "syntax"
    assert run("return 3").error_group == "syntax"
    # name used before it is assigned somewhere in the program -> wrong_order
    assert run("print(x)\nx = 1").error_group == "wrong_order"
    # name that is never defined -> plain error
    assert run("print(y)").error_group == "syntax"
    assert run('print("a" + 1)').error_group == "syntax"
    assert run("print(1 / 0)").error_group == "syntax"


def test_diagnose():
    d = V.diagnose("print(1)\nprint(2)", "1\n2\n3")
    assert not d.passed and d.error_group == "output_mismatch"
    assert "1, 2" in d.message and "1, 2, 3" in d.message
    assert V.diagnose("print(1)", "1\n").passed
    assert V.diagnose("pass", "1").message.startswith("Đầu ra không khớp: chương trình không in gì")


def test_syntax_error_line_numbers():
    r = run("x = 1\nif x == 1\n    print(x)")
    assert r.lineno == 2
