# Validator and safety

`backend/app/validator.py` is the only module that executes Python. Both game modes, the offline
puzzle generator and the custom-code sandbox (section 5.1) use it. It has two jobs: decide whether a program is allowed to run and run it
under limits, and turn what happened into an `error_group` the game can show.

Related: [architecture.md](architecture.md), [syntax-rows.md](syntax-rows.md),
[puzzle-bank.md](puzzle-bank.md).

## 1. The pipeline

`run_program(code, *, trace=None) -> RunResult` never raises for bad player code. It returns a
`RunResult` with `ok`, `output`, `error_kind`, `error_group`, `message`, `lineno`, `exc_name` and the
parsed `tree`.

```
code
 ├─ len(code) > 4000                  -> error_kind "unsafe", group "syntax", "Chương trình quá dài."
 ├─ ast.parse()  fails                -> error_kind "syntax"  (classified below)
 ├─ check_ast()  rejects a node       -> error_kind "unsafe", group "syntax"
 ├─ compile()    fails                -> error_kind "syntax"  (e.g. 'return' outside function)
 └─ exec() with restricted globals, a tracer and a recursion cap
        ├─ _Abort("steps"|"time")     -> error_kind "limit", group "output_mismatch"
        ├─ _Abort("output")           -> error_kind "limit", group "output_mismatch"
        ├─ any exception              -> error_kind "runtime"
        └─ finished                   -> ok = True, output = captured print() text
```

`diagnose(code, expected_output)` wraps `run_program` and compares the normalised output with the
expected one. It returns a `Diagnosis(passed, error_group, message, actual_output, lineno, run)`.

## 2. The AST whitelist

`check_ast(tree)` walks every node with `ast.walk` and raises `UnsafeCode` on the first violation.
A program is only accepted if every node type is in `ALLOWED_NODES`:

| Category | Allowed nodes |
| --- | --- |
| Structure | `Module`, `Expr`, `Assign`, `AugAssign`, `If`, `IfExp`, `For`, `While`, `Break`, `Continue`, `Pass`, `FunctionDef`, `arguments`, `arg`, `Return` |
| Expressions | `Name`, `Constant`, `BinOp`, `UnaryOp`, `BoolOp`, `Compare`, `Call`, `List`, `Tuple`, `Subscript`, `Slice`, `JoinedStr`, `FormattedValue`, `keyword` |
| Context | `Load`, `Store` |
| Arithmetic | `Add`, `Sub`, `Mult`, `Div`, `FloorDiv`, `Mod`, `USub`, `UAdd` |
| Logic and comparison | `Not`, `And`, `Or`, `Eq`, `NotEq`, `Lt`, `LtE`, `Gt`, `GtE`, `Is`, `IsNot`, `In`, `NotIn` |

Not allowed (examples). When the node is listed in `_NODE_NAMES_VI` the player sees a Vietnamese reason; otherwise the message names the AST class (for example `LShift`):
`import`, attribute access (`x.y`), `lambda`, any comprehension or generator, `global`/`nonlocal`,
`with`, `try`, `class`, `**` (`Pow`), shifts and bit operators, `dict`, `set`, `*args` unpacking
(`Starred`), `async`, `del`, `assert`, `raise`, annotations, `yield`, `await`.

On top of the node whitelist, `check_ast` enforces these rules:

| Rule | Detail |
| --- | --- |
| No underscore names | Any `Name`, function name or parameter starting with `_` is rejected. This blocks `__import__`, `__builtins__`, `__class__`, etc. |
| Function definitions are plain | No decorators, no return annotation, no `type_params`, no `*args`, `**kwargs`, keyword-only or positional-only parameters. Parameter annotations are rejected too. |
| Keyword arguments | `f(**x)` (a `keyword` with `arg is None`) and keywords starting with `_` are rejected. |
| Calls | `node.func` must be a bare `Name` that is in `ALLOWED_CALLS` or is a function defined with `def` in the same program. Anything else is rejected, including calling a variable (`x = 1; x(2)`). |
| Constants | `abs(int) <= MAX_INT_CONSTANT` (10**6), `len(str) <= MAX_STR_CONSTANT` (200); `bytes` and `complex` rejected. `bool` and `None` pass. |
| Assignment targets | Only `Name`, `Tuple` or `Subscript` targets. |

`ALLOWED_CALLS` is `print, range, len, str, int, float, abs, min, max, sum, round`.

The exec environment gives the program only those names. `run_program` builds
`{"__builtins__": safe_builtins, "__name__": "puzzle"}` where `safe_builtins` contains a captured
`print` plus `range, len, str, int, float, abs, min, max, sum, round` (`SAFE_BUILTIN_NAMES`). Nothing
else (`open`, `eval`, `exec`, `getattr`, `__import__`) exists in that namespace, and the whitelist
also rejects the syntax needed to reach them.

Two layers, same intent: the AST check stops anything unexpected before it runs, and the minimal
namespace means a mistake in the AST check would still not hand over `open` or `__import__` by name.

## 3. Limits and how they are enforced

| Constant | Value | Where it applies | How it is enforced |
| --- | --- | --- | --- |
| `MAX_SOURCE_CHARS` | 4000 | Length of the program text | Checked before parsing. |
| `MAX_INT_CONSTANT` | 10**6 | Every integer literal in the source | `check_ast`. Does not limit results of arithmetic (`1000000 * 100` is accepted). |
| `MAX_STR_CONSTANT` | 200 | Every string literal | `check_ast`. Does not limit string multiplication. |
| `STEP_LIMIT` | 20 000 | "line" events inside the player's code | `local_trace` increments `steps` on every `line` event; above the limit it raises `_Abort("steps")`. |
| `TIME_LIMIT_S` | 1.5 s | Wall clock | `time.monotonic()` is compared with the deadline only every 1024 line events (`(steps & 0x3FF) == 0`). |
| `OUTPUT_CAP` | 2048 chars | Total characters passed to `print` | Custom `print` adds `len(text)`; above the cap it raises `_Abort("output")`. |
| Recursion | `min(old_limit, 400)` | Python call depth | `sys.setrecursionlimit` for the duration of the run, restored in a `finally`. Exceeding it is a `RecursionError`, reported as a runtime error. |
| `TRACE_LIMIT` | 48 | Recorded trace steps (Syntax Rows trace only) | Recording stops; execution continues. See section 7. |

How tracing works: `sys.settrace(global_trace)` is installed for the duration of `exec`.
`global_trace` returns the line tracer only for frames whose `co_filename == "<puzzle>"`, so
builtins and the runner itself are not counted. `_Abort` derives from `BaseException` so a
player program cannot swallow it (and `try` is not allowed anyway).

Messages: steps and time both produce "Chương trình chạy quá lâu, có thể có vòng lặp vô hạn."; the
output cap produces "Chương trình in ra quá nhiều dòng." Both are classified as
`output_mismatch` so the game treats them as a wrong result, not a crash.

Observed behaviour (run locally with `run_program`):

| Program | Result |
| --- | --- |
| `while True: pass` | `limit`, stops in about 4 ms (step limit, not the clock) |
| `for i in range(1000000): pass` | `limit`, about 4 ms |
| `while True:\n    print('a')` | `limit` with `exc_name == "output"`, output length 2048 |
| `def f(n): return f(n+1)` | `runtime`, `RecursionError`, "Hàm gọi lại chính nó quá nhiều lần" |
| `print(2**8)` | `unsafe`, "phép lũy thừa **" |

Because 20 000 line events are used up in a few milliseconds, the wall-clock check is mostly a
backstop for loops whose lines are individually slow.

## 4. Error classification

Every failure ends up in one `error_group`. The tables show where each group comes from.

### 4.1 From the validator (shared)

| Condition | `error_kind` | `error_group` | Message (Vietnamese, abridged) |
| --- | --- | --- | --- |
| `SyntaxError` / `IndentationError` with "expected an indented block" | `syntax` | `bad_indent` | Thiếu thụt lề: dòng sau lệnh kết thúc bằng dấu hai chấm cần được thụt vào. |
| "unexpected indent" | `syntax` | `bad_indent` | Dòng này bị thụt lề không đúng chỗ. |
| any other indentation error | `syntax` | `bad_indent` | Thụt lề chưa đúng. |
| "expected ':'" | `syntax` | `missing_colon` | Thiếu dấu hai chấm ':' ở cuối lệnh. |
| "'return' outside function" (raised by `compile`) | `syntax` | `syntax` | Lệnh return chỉ dùng được bên trong hàm. |
| any other syntax error, null bytes, absurd nesting | `syntax` | `syntax` | Sai cú pháp: Python không hiểu dòng này. |
| AST whitelist violation, program too long | `unsafe` | `syntax` | Chương trình dùng thứ chưa được hỗ trợ: *reason*. |
| `NameError` for a name that the program assigns, defines or takes as a parameter somewhere | `runtime` | `wrong_order` | Tên '*x*' chưa được tạo trước khi dùng (dòng *n*). |
| `NameError` for a name that exists nowhere | `runtime` | `syntax` | same message |
| `TypeError`, `ZeroDivisionError`, `IndexError`/`KeyError`, `ValueError`, `RecursionError`, anything else | `runtime` | `syntax` | specific text per type, e.g. "Không thể cộng chuỗi với số", "Không thể chia cho 0" |
| step, time or output limit | `limit` | `output_mismatch` | see section 3 |
| ran fine, output differs (`diagnose`) | none | `output_mismatch` | Đầu ra không khớp: chương trình in *a* nhưng cần *b*. |

`normalize_output` makes comparison forgiving about line endings and trailing spaces:
`\r\n`/`\r` become `\n`, trailing spaces on each line are stripped, trailing newlines removed.

The `wrong_order` rule is a heuristic: "this name is assigned somewhere in the program but used
before it exists" means the lines are in the wrong order.

### 4.2 Extra groups added by the callers

| Group | Where | Condition |
| --- | --- | --- |
| `empty` | `rows.run_level` | The board has no tokens. |
| `missing_construct` | `rows.run_level` | The program ran, but a construct in the level's `required_constructs` (AST node names such as `For`, `If`, `Assign`, `FunctionDef`, `Return`) is absent. Checked before the output comparison. |
| `wrong_order` (output case) | `rows.run_level` | Output is wrong but the assembled lines, as a multiset of `(indent, text)`, equal the canonical solution: only the order is off. |
| `wrong_order` / `bad_indent` (parsons) | `bank._check_parsons` | The program ran but printed the wrong thing; if the line order differs from the stored solution it is `wrong_order`, else if only the indents differ it is `bad_indent`. |
| `wrong_choice` | `bank.check_answer` | Wrong option in `predict_output`. |
| `wrong_line` | `bank.check_answer` | Wrong option in `find_bug` whose `line_id` is not the buggy line. |
| `wrong_fix` | `bank.check_answer` | Wrong option in `find_bug` on the buggy line. |

Full list of groups in the API: `wrong_order`, `bad_indent`, `syntax`, `output_mismatch`,
`wrong_line`, `wrong_fix`, `wrong_choice` (Code Rescue) and `missing_colon`, `missing_construct`,
`empty` (added for Syntax Rows). `syntax`, `bad_indent`, `wrong_order` and `output_mismatch` appear
in both.

### 4.3 Mapping a failure to a board row (Syntax Rows)

The assembled program has one line per non-empty board row, so line *n* of the program is the *n*th
non-empty row, not board row *n*. `rows.py` keeps `AsmLine.row` for the mapping.

| Group | Row returned | Rule |
| --- | --- | --- |
| `syntax`, `bad_indent`, `missing_colon`, runtime errors | `_row_of_lineno(lines, res.lineno)` | Program line number, clamped into `1..len(lines)`, mapped to its board row. For a runtime error `lineno` is the innermost traceback frame inside `<puzzle>`, so an error inside a function body points at the row of that body line. |
| `output_mismatch`, `wrong_order` (output case) | `_first_diff_row(lv, lines)` | First assembled line whose `(indent, text)` differs from the canonical solution, or the first extra line. `null` if every line matches the canonical but the output is still wrong. |
| limit errors (`lineno` is `None`) | `null` | No line is known. |
| `missing_construct`, `empty` | `null` | |
| pass | `null` | |

For `missing_colon` the message gets " (dòng *n*)" appended (the program line number, which can
differ from the board row number when rows are skipped).

### 4.4 Code Rescue answers

Code Rescue does not run a diagnosis for the chosen option at answer time (except parsons). The
group, message and actual output of each wrong option were computed with `diagnose()` when the bank
was generated and stored in the option. `bank.check_answer` only reads them back.

## 5. Threat model

### What is protected

| Asset | Threat | Defence |
| --- | --- | --- |
| The server process and its files | Player code reads files, imports modules, reaches `__builtins__`, uses reflection | Node whitelist (no import, no attribute access, no dunder names), restricted call set, minimal `__builtins__` |
| CPU time | Infinite or very long loops | 20 000 line-event cap plus a clock check; recursion cap 400 |
| Response size and memory from output | Huge `print` output | 2048-character cap |
| Parser abuse | Giant or deeply nested source | 4000-character cap before `ast.parse`; `ValueError`/`RecursionError`/`MemoryError` from parse and compile are caught |
| Answer leakage | Reading the solution from a public endpoint | `bank.public_puzzle` and `rows.public_level` build the player view from an explicit list of fields. `test_public_views_never_leak` and `test_get_level_never_leaks` assert it. |

### Why player code is never free-form

This is the main control. The strongest line of defence is not the whitelist but what can reach it:

- **Code Rescue**: the program is assembled from `lines[].text` stored in the bank (parsons), from a
  stored skeleton plus a stored option (fill_blank), or is stored whole (predict_output). The player
  chooses *among* stored fragments and orders and indents them. `indent` is validated to be 0..2 and
  the set of `line_id`s must match exactly.
- **Syntax Rows**: the program is assembled from level token texts. The request carries token ids,
  not text. Unknown ids are rejected with 422, so a client cannot inject new text.
- **Generator**: programs come from hand-written YAML templates, reviewed by the team.
- **The tutor**: its output is never executed. `review_content.py` does execute drafted programs, but
  only through `validator.diagnose`, and only for an editor to review.

This matches the proposal's safety rule: code comes from a content bank and is checked in a limited
environment; arbitrary player or AI code is not run on the main server. The proposal also says that if
free-form code is ever added, a separate sandbox with time and resource limits is required. The
in-process runner is not that sandbox. "Paste your own code" (section 5.1) is the one place free-form
code exists, and it uses the separate-process sandbox described there.

### 5.1 Custom code ("paste your own code") runs in a child process

`POST /api/custom/sets` accepts a program typed or pasted by the learner and turns it into up to four
puzzles. This is the only path where free-form text is executed, and it never reaches
`validator.run_program` inside the web server process. Everything that runs it, for generation and for
later answer checks of those puzzles, goes through `app/sandbox.py`.

**Before anything runs** (`custom_gen.prepare_source`, text and AST only, no execution):

| Rule | Detail |
| --- | --- |
| Size | At most 800 characters and 2 to 15 non-empty lines (comments and blank lines are dropped first). |
| Layout | No tab characters; every indent is a multiple of 4 spaces. |
| AST | Must pass `validator.check_ast` (the same whitelist as everywhere else; the integer cap 10**6 stays). |
| No sequence multiplication | `*` is rejected when an operand is a string literal, f-string, list or tuple, `str(...)`, or a name or function result that the program assigned from one of those (`"ab" * n`, `[0] * n`, `s = "x"; s * n`). This is a static, best-effort check: it cannot follow every value (for example a function parameter), which is why the sandbox limits below exist. |

**The sandbox** (`sandbox.py` and `sandbox_worker.py`):

- One child per job: `python -I -c <bootstrap>` with the backend directory as working directory.
  `-I` (isolated mode) ignores `PYTHON*` variables and the user site directory. The child gets a scrubbed
  environment: nothing from the server's environment (so not the tutor token), only `SYSTEMROOT` on
  Windows.
- Generation is **one child call per set**. All candidate runs (the program, its mutated copies, the
  fill-in alternatives) happen inside that one child. Answer checks that need execution (parsons) are
  one child call each. fill_blank, predict_output and find_bug checks read the stored, already verified
  option and run nothing.
- The child imports `validator`, so the whitelist, restricted builtins, 20 000 step limit, 1.5 s clock
  and 2048 character output cap still apply inside it. The wall-clock limit below catches what those
  cannot (a single long C-level call such as `sum(range(10**12))`).
- At most 4 children at once. A fifth request waits up to 3 s, then gets 429.
- `custom_gen.generate` refuses to run unless the worker has switched on `custom_gen.ENABLED`, so
  calling it from the web server by mistake raises instead of executing pasted code.
- Per-client limit: 10 new sets per hour (in memory, keyed by a hash of `_client_ip`), answered with 429.
  Rejected input (422 before anything runs) does not use the quota.

| Limit | Linux (the Docker image) | Windows (development) |
| --- | --- | --- |
| Wall clock for a generation job | 5 s, then the parent kills the child | 5 s, then `TerminateProcess` |
| Wall clock for an answer check | 2 s | 2 s |
| `RLIMIT_AS` (address space) | 256 MB (a `MemoryError` inside the program is reported as a runtime error) | not available |
| `RLIMIT_CPU` | 3 s soft (SIGXCPU), 4 s hard | not available |
| `RLIMIT_NPROC` | 0: the worker cannot fork or start threads | not available |
| `RLIMIT_FSIZE` / `NOFILE` / `CORE` | 1 MB / 32 / 0 | not available |
| Result size | 512 KB read from the child | same |

The rlimits are set by the child itself at start-up (`sandbox_worker.apply_limits`), not with
`preexec_fn`: `preexec_fn` is documented as unsafe in a multi-threaded parent, and the web server
runs requests in a thread pool. The effect is the same because it happens before any learner code is
read. The Linux column is implemented and unit-tested with a stand-in `resource` module, but the
real kernel enforcement could only be exercised on Linux, not on the Windows development machine.

**What the sandbox does not guarantee.** It is a resource and crash boundary, not a security jail.

- No network namespace and no seccomp filter: the child runs as the same OS user as the server, can
  open sockets and can read any file that user can read, if code ever escaped the AST whitelist. What
  keeps that from being reachable is the same two layers as before (node whitelist and minimal
  builtins), now inside a process that holds no secrets in its environment.
- No filesystem isolation (no chroot, no read-only mount, no separate user). `RLIMIT_FSIZE` caps what
  one file write could be, nothing more.
- On Windows only the wall-clock timeout applies; memory is not limited. Do not expose the custom
  endpoint from a Windows host.
- Memory is limited per child, not for all children together (4 x 256 MB at the worst).
- A learner can still make the server spend about 5 s of CPU per request, within the 10 per hour and 4
  at a time limits.

Custom puzzles are stored in `backend/data/custom.sqlite` (created on demand, in `.gitignore`, deleted
after 30 days). The Docker image has no volume for it, so sets are lost when the container is
re-created.

### What is not protected

Be honest about these when presenting the project.

1. **A single expression cannot be interrupted.** The step and time checks run only on Python line
   events. A long-running operation inside one line (a C-level loop such as `sum(range(n))`, or a
   very large string or list multiplication) does not yield line events while it runs. The integer
   constant cap (10**6) limits literals, not results: `x = 1000000 * 100` is accepted, and
   `print(sum(range(x)))` ran to completion in about 0.8 s here (under the clock limit only because
   the number is small). A bigger product would run proportionally longer, with no way to stop it.
   Likewise `'a' * 999999 * 999` (about 10**9 characters) completed in about 0.3 s. These are
   mitigated only by the fact that bank fragments never contain such expressions.
2. **No process isolation.** `exec` runs in the server's own process. A memory spike or a hang
   affects the server, not a throwaway child process.
3. **`sys.setrecursionlimit` is process-wide.** `run_program` lowers the limit to at most 400 and
   restores the previous value in a `finally`. That set, run, restore section is now serialised by a
   module-level `threading.Lock` (`_RECURSION_LOCK`), so overlapping runs from the thread pool can no
   longer capture each other's lowered value. The cost is that program execution is serial. `sys.settrace`
   itself is per-thread and was never affected.
4. **No rate limiting on run endpoints.** The tutor has a concurrency cap and `POST /api/custom/sets`
   has a per-client limit; `/run`, `/answer` and `/puzzle/next` do not.
5. **Not authentication.** Anyone who can reach the server can call any endpoint.
6. **Python version.** The whitelist reads `node.type_params`, which only exists on Python 3.12+. The
   Dockerfile uses 3.12; the local virtual environment used for these docs is 3.14.7. Older versions
   are not supported: `app/main.py` raises a `RuntimeError` at import below 3.12.

The design accepts these because the inputs are bank-only. That assumption is the thing to protect
when changing the code: do not add an endpoint that sends player-typed text to `run_program` in the
web server process. Text a learner typed goes through `sandbox.py` (5.1) or nowhere. Items 1 to 3
describe the in-process runner; the sandbox child has the same weaknesses, but a hang there ends at the
wall-clock limit and a memory spike ends in the child.

## 6. Normalisation and messages used by both games

- `describe_output(s)` turns `0\n1\n2` into `0, 1, 2` for messages; empty output becomes
  "không in gì".
- `mismatch_message(actual, expected)` builds "Đầu ra không khớp: chương trình in *a* nhưng cần *b*."

## 7. Execution trace

Used by Syntax Rows (`POST /api/rows/levels/{id}/run` with `"trace": true`, and the hint endpoint
when a `trace_step` is given). Not used by Code Rescue.

- `ExecutionTrace` holds `steps: list[TraceStep]` and `truncated: bool`.
- `local_trace` records a step on the *next* `line` or `return` event in the same frame, so the
  bindings and output captured for a line are the state **after** that line ran. `previous_lines`
  remembers the pending line per frame (`id(frame)`).
- A step is `TraceStep(lineno, scope, bindings, output)`. `scope` is the code object name
  (`<module>` or the function name). `output` is everything printed so far.
- `_trace_bindings(frame.f_locals)` keeps only `str` (shown with `repr`, cut at 60 characters),
  `int` (shown as `repr`, replaced by an ellipsis if above 256 bits), `bool`, `float` and `None`.
  Lists, tuples and names starting with `__` are dropped. Inside a function the locals are the
  function's; at module level they are the globals.
- When 48 steps are stored and another would be added, `truncated` becomes `True` and recording
  stops. The program keeps running to its normal end (`test_trace_stops_recording_without_stopping_execution`).
- A program that fails before execution (syntax error, whitelist violation) has an empty trace.

`rows.run_level` then maps each step's `lineno` to the board row and to the displayed source line.
Full response format: [syntax-rows.md](syntax-rows.md#4-trace).

## 8. How the tests cover it

`backend/tests/test_validator.py` (36 test cases, most from one parametrised list):

| Test | What it proves |
| --- | --- |
| `test_rejects_unsafe` (25 parametrised cases) | imports, `__class__`, `__import__`, `open`, `eval`, `exec`, dunder and underscore names (also as def names and parameters), lambda, comprehension, dict, global, with, try, class, `**`, undefined function call, `getattr`, over-large integer: each is rejected with `error_kind == "unsafe"`, group `syntax`, and a message containing the expected reason. |
| `test_while_true_pass_returns_fast_and_fails_cleanly` | `while True: pass` returns in under 2 s with `error_kind == "limit"`. |
| `test_infinite_loop_with_body_and_output_cap` | an endless print loop stops, output length <= `OUTPUT_CAP`. |
| `test_for_loop_step_limit` | a million-iteration loop hits the step limit. |
| `test_trace_stops_recording_without_stopping_execution` | the trace caps at `TRACE_LIMIT` and the program still prints its result. |
| `test_runaway_recursion_is_an_error_not_a_crash` | infinite recursion is a `runtime` error. |
| `test_concurrent_runs_are_correct_and_restore_the_recursion_limit` (in `test_hardening.py`) | eight threaded runs all give the right output and the recursion limit is unchanged afterwards. |
| `test_runs_normal_program_and_captures_unicode` | real programs run, Unicode output, `sep` and `end` work. |
| `test_function_and_builtins` | user functions and every allowed builtin. |
| `test_no_leaking_between_runs` | a variable from one run is not visible in the next. |
| `test_error_classification` | every row of table 4.1 that concerns syntax, indentation, colons and `NameError`. |
| `test_diagnose` | mismatch message and pass/fail. |
| `test_syntax_error_line_numbers` | the reported line number. |

Indirectly, `test_bank_integrity.py` re-runs the validator on every stored puzzle, and
`test_rows.py` checks the row mapping (`test_distractor_swap_fails`, `test_syntax_error_row`,
`test_missing_colon`, `test_bad_indent`, `test_wrong_order`, `test_missing_construct`,
`test_unsafe_input_cannot_be_built_from_tokens`, `test_422_cases`).

What the tests do not cover: the clock limit on its own (no test makes a slow single line), the
single-expression cases in section 5.

## 9. Open questions

- ~~**Recursion-limit race.**~~ **Resolved:** the set, run, restore section is guarded by
  `_RECURSION_LOCK` in `app/validator.py`; a threaded test checks results and the restored limit.
- **Uninterruptible single expressions.** Should the validator also cap the *result* of `*` on
  strings and the argument of `range()` (for example by evaluating constants at check time)? Today it
  relies entirely on the bank never containing such expressions.
- **Time limit versus step limit.** The 1.5 s clock is only checked every 1024 line events and the
  step limit is hit first in practice. If slow-line programs matter, the check frequency needs
  revisiting.
- ~~**Minimum Python version**~~ **Resolved:** stated in `backend/README.md` and at the top of
  `requirements.txt`, and enforced by a startup check in `app/main.py`. `requirements.txt` still has no
  version pins.

