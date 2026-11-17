# Syntax Rows

Syntax Rows is the mode where the board *is* a program. Each row of a 10-column grid is one line of
Python; the player places code tokens ("keys") on rows; the server assembles the rows into a
program, runs it with the shared validator and says whether it passes.

Rules: `Syntax_Rows_Gameplay_Spec.md`. Backend: `backend/app/rows.py`, `backend/content/levels/`.
Client rules: `frontend/js/rows-game.js`. Related: [validator-and-safety.md](validator-and-safety.md),
[ai-tutor.md](ai-tutor.md), [frontend.md](frontend.md), [api-contract.md](api-contract.md).

The five levels in the repo:

| Id | Title | Concept | Goal output | Board rows | Required constructs |
| --- | --- | --- | --- | --- | --- |
| `r1` | Biến đầu tiên | variables | `7` | 4 | `Assign` |
| `r2` | Đậu hay trượt | conditions | `Đậu` | 5 | `Assign`, `If` |
| `r3` | Đếm đến ba | loops | `0`, `1`, `2` | 4 | `For` |
| `r4` | Cộng dồn | loops | `6` | 6 | `Assign`, `For` |
| `r5` | Hàm nhân đôi | functions | `8` | 5 | `FunctionDef`, `Return` |

## 1. Level YAML schema

One file per level in `backend/content/levels/` (`r1.yaml` to `r5.yaml`). All levels are loaded with
`yaml.safe_load` on first use and cached in memory (`rows.load_levels`); a running server must be
restarted to see an edited level.

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `id` | string | yes | Level id used in URLs (`r3`). |
| `order` | int | yes | Sort order and unlock order. |
| `title` | string | yes | Vietnamese title. |
| `concept` | string | yes | `variables` / `conditions` / `loops` / `functions`. Used for colours and the practice screen. |
| `goal` | string | yes | Vietnamese task text. |
| `expected_output` | string | yes | Output the program must print (lines joined with `\n`). |
| `twist_output` | string | no | Alternate target for the "Đổi một mảnh" challenge (section 7). All five levels have one. |
| `practice` | map | no | The authored mistake for the practice board (section 6). All five levels have one. |
| `predictions` | list of strings | no | Quick-pick candidates for the output prediction box. Only `r4` has them. |
| `rows` | int | yes | Number of board rows (the repo's levels use 4 to 6; the tests require 4 to 7). |
| `cols` | int | yes | Board width, 10 in all levels. |
| `indent_cols` | int | yes | The first token of a row may start at column 0 up to this value; the column is the indent level. 2 in all levels. |
| `tokens` | list | yes | See below. |
| `solution` | list | yes | Canonical solution: rows of `{indent, tokens: [ids]}`. |
| `required_constructs` | list of AST node class names | no | Constructs that must appear in the AST (`Assign`, `If`, `For`, `While`, `FunctionDef`, `Return`). Messages exist for these six in `CONSTRUCT_NAMES_VI`. |
| `hints` | list of 3 strings | yes | General hints (concept, direction, specific). |
| `group_hints` | map group to list of 3 strings | no | Hints per error group. |

A token is `{id, text, w, topic, is_distractor}`:

- `id`: unique within the level (`t1`...).
- `text`: the code fragment, for example `range(3)`, `:`, `print("Đậu")`.
- `w`: width in grid columns (`1`, `2` or `3`; the design calls these 1u, 2u, 3u keys). Validated at
  load: outside 1 to 3 raises `ValueError`. Duplicate token ids also raise.
- `topic`: colour group (`variables`, `conditions`, `loops`, `functions`, or `syntax` for neutral
  keys such as `for`, `in`, `:`, `=`).
- `is_distractor`: not sent to the player; used only to count unused distractors.

Example, `r3.yaml` (abridged):

```yaml
id: r3
order: 3
title: "Đếm đến ba"
concept: loops
goal: "Viết chương trình in ra 0, 1, 2, mỗi số một dòng."
expected_output: "0\n1\n2"
twist_output: "0\n1"
practice: {replace: t4, with: t1}      # swap range(3) for range(2)
rows: 4
cols: 10
indent_cols: 2
tokens:
  - {id: t1, text: "range(2)", w: 3, topic: loops,  is_distractor: true}
  - {id: t2, text: "for",      w: 1, topic: syntax, is_distractor: false}
  - {id: t4, text: "range(3)", w: 3, topic: loops,  is_distractor: false}
  # ...
solution:
  - {indent: 0, tokens: [t2, t7, t8, t4, t5]}   # for i in range(3) :
  - {indent: 1, tokens: [t3]}                    #     print(i)
required_constructs: [For]
hints: ["...", "...", "..."]
group_hints:
  output_mismatch: ["...", "...", "..."]
```

What is validated at load time: unique token ids and widths 1 to 3. What is only checked by tests
(`test_level_content_matches_spec`, `test_canonical_solution_passes`,
`test_all_levels_have_three_hints_and_group_hints`): 4 to 7 rows, 2 to 4 distractors, each solution
row fits in `cols`, the canonical solution passes, and every level has three hints and group hints
for `output_mismatch`, `wrong_order`, `bad_indent`, `missing_construct`.

### What the client may see

`GET /api/rows/levels` returns `{id, order, title, concept, rows, cols}` per level.
`GET /api/rows/levels/{id}` (`rows.public_level`) returns `id, order, title, concept, goal,
expected_output, twist_output, predictions, rows, cols, indent_cols` and the tokens as
`{id, text, w, topic}`. It never contains `solution`, `is_distractor`, `required_constructs`,
`hints`, `group_hints` or `practice`.

```json
{"id":"r3","order":3,"title":"Đếm đến ba","concept":"loops",
 "goal":"Viết chương trình in ra 0, 1, 2, mỗi số một dòng.",
 "expected_output":"0\n1\n2","twist_output":"0\n1","predictions":[],
 "rows":4,"cols":10,"indent_cols":2,
 "tokens":[{"id":"t1","text":"range(2)","w":3,"topic":"loops"},
           {"id":"t2","text":"for","w":1,"topic":"syntax"}]}
```

## 2. Board assembly rules

The request body is the same for run, twist (twice), teach-back and the coaching hint:

```json
{"rows": [{"row": 0, "tokens": [{"id": "t2", "col": 0}, {"id": "t7", "col": 1}, {"id": "t8", "col": 2},
                                {"id": "t4", "col": 3}, {"id": "t5", "col": 6}]},
          {"row": 1, "tokens": [{"id": "t3", "col": 1}]}]}
```

`rows.assemble(level, rows)` turns it into `AsmLine`s or raises `RowsError`, which `main.py` maps to
HTTP 422 `{"detail": "<Vietnamese message>"}`:

1. Rows are processed in ascending `row`. A row index must be in `0..rows-1`, and each index may
   appear once.
2. A row with no tokens is skipped. Gaps between rows do not matter, and rows do not have to start
   at row 0.
3. Within a row, tokens are sorted by `col`.
4. Every token id must exist in the level and be used **at most once on the whole board**.
5. A token must lie fully inside the grid: `col >= 0` and `col + w <= cols`.
6. Tokens in one row must not overlap: a token's `col` must be at or after the end (`col + w`) of
   the previous one.
7. The first token of a row must start at column `0..indent_cols`. That column **is** the indent
   level (0, 1 or 2), and each level is 4 spaces.
8. The line text is the token texts joined with a single space, in column order. The distance
   between tokens carries no meaning.

So row 0 above becomes `for i in range(3) :` (note the space before the colon) and row 1 becomes
`    print(i)`. The program passed to the validator is the lines joined with `\n`. The space before
`:` is harmless; it is why `code` in responses looks like `for i in range(2) :`.

The client enforces the same constraints (`rows-game.js: canPlace`, `localCheck`), so most of these
422s should be unreachable from the UI; `localCheck` returns a `bad_indent` result without calling
the server when a row starts past the indent columns.

Any program that passes is accepted, not only the canonical one (`test_any_correct_program_is_accepted_not_only_canonical`):
interchangeable tokens (two `diem` tokens, two `=` tokens) may be swapped.

## 3. Diagnosis order and row mapping

`rows.run_level(level, rows, include_trace=False, prediction=None, target_output=None)` runs these
steps and returns at the first one that fails:

| Step | Check | Result |
| --- | --- | --- |
| 1 | `assemble` | 422 on a structural error (section 2) |
| 2 | No lines | `error_group: "empty"`, `row: null`, `code: ""` |
| 3 | `validator.run_program(code, trace)` fails | the validator's group (`syntax`, `bad_indent`, `missing_colon`, `wrong_order` for use-before-assignment, `output_mismatch` for step/time/output limits); `row` = program line mapped to a board row; `actual_output` is whatever was printed before the failure, or `null` |
| 4 | The program ran | `prediction.correct` is computed here, if a prediction was sent |
| 5 | `required_constructs` | any construct class missing from the AST: `missing_construct`, `row: null`, message "Thiếu cấu trúc bắt buộc: ..." |
| 6 | Output differs from `expected_output` | `output_mismatch`, or `wrong_order` when the multiset of `(indent, text)` lines equals the canonical solution's (only the order is wrong); `row` = first line that differs from the canonical solution (indent or text), or the first extra line |
| 7 | Output matches | `passed: true`, `message: "Chính xác! Chương trình in đúng đầu ra."`, `unused_distractors` |

Notes:

- The construct check happens **before** the output comparison, so a program that prints the right
  thing without a required construct fails with `missing_construct`. Example from
  `test_missing_construct`: in `r2`, `diem = 8` followed by `print("Đậu")` with no `if` prints the
  goal output but is rejected for the missing `if`.
- Output comparison uses `normalize_output` on both sides (trailing spaces and newlines ignored).
- For `missing_colon` the message gets " (dòng *n*)" appended, with *n* the program line, which is
  not always the board row number.
- `row` is the **board row index** to mark red (zero-based). In the response, `code` is the
  assembled source so the client can show it.
- `unused_distractors` = number of distractor tokens in the level minus the number of placed token
  texts that go beyond what the canonical solution needs. It is only set on a pass.

Real responses (level `r3`, solution with `range(2)`):

```json
{"passed": false, "error_group": "output_mismatch", "row": 0,
 "message": "Đầu ra không khớp: chương trình in 0, 1 nhưng cần 0, 1, 2.",
 "actual_output": "0\n1", "expected_output": "0\n1\n2",
 "code": "for i in range(2) :\n    print(i)", "unused_distractors": null}
```

Missing colon (the `:` token left off):

```json
{"passed": false, "error_group": "missing_colon", "row": 0,
 "message": "Thiếu dấu hai chấm ':' ở cuối lệnh. (dòng 1)", "actual_output": null,
 "expected_output": "0\n1\n2", "code": "for i in range(3)\n    print(i)", "unused_distractors": null}
```

Pass:

```json
{"passed": true, "error_group": null, "row": null,
 "message": "Chính xác! Chương trình in đúng đầu ra.", "actual_output": "0\n1\n2",
 "expected_output": "0\n1\n2", "code": "for i in range(3) :\n    print(i)", "unused_distractors": 3}
```

Row-mapping rules for each group are in [validator-and-safety.md](validator-and-safety.md#43-mapping-a-failure-to-a-board-row-syntax-rows).

## 4. Trace

`"trace": true` in the run request (the web client always sends it) adds:

```json
"trace": {
  "steps": [
    {"row": 0, "code": "for i in range(2) :", "scope": null, "bindings": {"i": "0"}, "output": ""},
    {"row": 1, "code": "    print(i)",        "scope": null, "bindings": {"i": "0"}, "output": "0\n"}
  ],
  "truncated": false
}
```

- One step per executed line, in execution order. `row` is the zero-based board row; `code` is that
  line's source including its indent.
- `scope` is `null` for module-level code, otherwise the function name (`"gap_doi"`).
- `bindings` is the state **after** the line ran: only `str`, `int`, `bool`, `float`, `None`
  variables of the current frame, each as a display string (`repr`; strings cut at 60 characters).
- `output` is the cumulative printed output after that line.
- At most **48** steps are recorded (`TRACE_LIMIT`). When more would follow, `truncated` is `true` and
  the program still runs to completion. The UI then shows "Bản ghi dừng ở bước này. Chương trình đã
  tiếp tục chạy."
- A run that fails before executing (syntax error, whitelist, empty board) returns
  `{"steps": [], "truncated": false}`. The trace of a failing program that did start executing
  contains the steps up to the failure.

The trace is produced by the same tracer that enforces the step limit (see
[validator-and-safety.md](validator-and-safety.md#7-execution-trace)). The web client lets the
learner step with the keycaps or the left/right arrow keys (`rows-screen.js: moveTrace`).

## 5. Prediction

The learner may type what they think the program prints *before* running it.

- Request: `"prediction": "<text>"`, optional, at most **240** characters (`RunRequest.prediction`,
  422 above that).
- The web client only sends it when the "Dự đoán đầu ra" panel is open and the text is non-empty.
  For `r4` it offers quick picks from the level's `predictions` (`"6"` and `"1\n3\n6"`).
- Response: `"prediction": {"correct": true | false | null}`. `correct` compares the normalised
  prediction with the **actual** output, not with the goal. It is `null` if the program did not
  finish (empty board or any failure that stops execution). The key is absent when no prediction was
  sent.
- On the server it never changes `passed`, `error_group`, `row` or anything else in the grade
  (`test_prediction_is_compared_with_actual_output_separately_from_grade`). The browser may add the
  "Đọc code" score bonus from it (section 10).

```json
{"passed": false, "...": "...", "prediction": {"correct": false}}
```

## 6. Practice boards

`GET /api/rows/levels/{id}/practice` returns `{"rows": [...]}`: a board that is the canonical
solution with the level's authored mistake applied, as a board payload ready to be shown and then
run. For levels that define `practice` it always runs and fails with `output_mismatch`
(`test_practice_board_runs_and_exposes_the_authored_mistake`).

`practice` in the level YAML is one of:

| Form | Effect | Used by |
| --- | --- | --- |
| `{replace: tA, with: tB}` | One placed token id is replaced by another (`rows.practice_rows`) | r1 (`7` becomes `8`), r2 (`print("Đậu")` becomes `print("Trượt")`), r3 (`range(3)` becomes `range(2)`), r5 (`*` becomes `+`) |
| `{row: n, indent: k}` | Every token of canonical row `n` is shifted so the row starts at column `k` | r4 (`print(tong)` pushed into the loop, printing `1 3 6`) |

A level without `practice` returns 422 "Màn này chưa có bài luyện."

The client opens these from the practice screen ("Luyện theo lỗi" and "Demo cho giám khảo", see
[frontend.md](frontend.md#the-practice-screen)). Practice runs do not write progress or stars and
do not add to the mistake history.

## 7. Twist (alternate target)

After passing a level the learner can press "Đổi một mảnh": change exactly one token to reach a
different target output (`twist_output`).

`POST /api/rows/levels/{id}/twist`:

```json
{"baseline": [ /* a passing board */ ], "rows": [ /* the changed board */ ], "trace": true}
```

`rows.run_twist` does, in order:

1. The level must have `twist_output`, and `baseline` must pass `run_level`. Otherwise 422
   "Hãy hoàn thành màn trước khi bắt đầu thử thách."
2. Run `rows` with `target_output=twist_output` (so `expected_output` in the response is the twist
   target; `required_constructs` still apply).
3. Compare positions: the set of `(row, col)` positions must be identical in both boards and exactly
   one position must hold a different token id. Otherwise 422 "Thay đúng một mảnh mã ở cùng vị trí."

The step-3 check runs **after** the run, so a malformed `rows` fails first with the assembly error.

The response is the normal run response. Example (r3, `range(3)` swapped for `range(2)`):

```json
{"passed": true, "error_group": null, "row": null, "message": "Chính xác! Chương trình in đúng đầu ra.",
 "actual_output": "0\n1", "expected_output": "0\n1", "code": "for i in range(2) :\n    print(i)",
 "unused_distractors": 2}
```

(`unused_distractors` is computed against the canonical solution and carries no meaning in a twist.)
The twist replacements the tests use: r1 `t5` to `t3` (`8`), r2 `t2` to `t8` (`Trượt`), r3 `t4` to
`t1` (`0 1`), r4 `t10` to `t2` (`3`), r5 `t5` to `t7` (`6`). Twist results are not recorded as
progress.

## 8. Teach-back

`POST /api/rows/levels/{id}/teach-back` with `{"rows": [...], "reflection": "<text>"}`. The learner
explains the passing program in their own words and the tutor answers with one follow-up question.

- `reflection`: 1 to 400 characters (pydantic), then stripped; a whitespace-only value is rejected
  with 422 "Hãy viết lời giải thích của bạn."
- The board is re-run server-side; if it does not pass: 422 "Hãy hoàn thành màn trước khi giải
  thích."
- Tutor task `teach_back` with context `{goal, code, output, learner_explanation}`; the context
  contains the verified program and output, not the client's claim. Details in
  [ai-tutor.md](ai-tutor.md#task-teach_back).
- Response: `{"text": "...", "source": "ai" | "canned"}`. The canned text is a fixed Vietnamese
  question followed by an English translation of it ("Nếu đổi đúng một mảnh mã, đầu ra sẽ thay đổi
  thế nào? / What would change in the output if you swapped one tile?").

## 9. Hint endpoints

Three levels, all with `level` 1 to 3 (otherwise 422).

| Endpoint | Behaviour |
| --- | --- |
| `GET /api/rows/levels/{id}/hint?level=n&error_group=g` | Authored hint. With `error_group` (one of the seven groups, otherwise 422): the level's `group_hints[g][n-1]`, else the generic text in `hints.py: GENERIC_ROWS_HINTS[g]`. Without `error_group`: the level's `hints[n-1]`. Always `source: "canned"`. |
| `POST /api/rows/levels/{id}/hint?level=n` with a board, optional `trace_step` | The server re-runs the board. Empty or passing board: the canned hint, `source: "canned"`. Otherwise the tutor task `coach` with the verified diagnosis; `source: "ai"` on success, the canned hint (for the board's error group) on any failure. `trace_step` is a zero-based index into the server-built trace; the selected step is added to the tutor context. An index past the end is 422 "Bước chạy này không có trong chương trình." |

The web client uses POST once the learner has run the board at least once and GET before that. When
the trace panel is open it sends the displayed step, so the tutor can talk about "this step".
Context fields and fallback rules: [ai-tutor.md](ai-tutor.md#task-coach).

## 10. Stars and score

Computed in the browser (`rows-game.js`), not by the server. The server supplies
`unused_distractors`; the rest is client state.

```
runs      = number of runs that reached the server, including the passing one
            (a client-side bad_indent rejection and a failed request do not count)
hintsMax  = the highest number of hints opened (never decreases)

stars = 3  if runs <= 1 and hintsMax == 0
        2  if runs <= 3 and hintsMax <= 1
        1  otherwise

readBonus = true once per level attempt when a prediction (section 5) was correct for a program
            that had not run before and whose actual output is not the goal (notePrediction)

score = round(300 * stars / 3) + 50 * unused_distractors + (50 if readBonus)
```

| Stars | Score from stars | Bonus |
| --- | --- | --- |
| 3 | 300 | +50 for each distractor not used |
| 2 | 200 | same |
| 1 | 100 | same |

Plus **+50 "Đọc code"** (`PREDICT_BONUS`) once per level for reading a not-yet-correct program right.
Predicting the goal output earns nothing, because it is shown on screen, and neither does predicting a
board that already ran, because its output was just shown. The bonus (50) is smaller than one star
(100), so failing on purpose to earn it never pays. It is added only when the level is passed, and
the result receipt shows it as `read_code`.

The first hint button says "tối đa 2 sao", later ones "tối đa 1 sao", matching the rules. Stars and
score are stored per level as the best seen (`recordRowsResult`). A level unlocks when the previous
one has at least 1 star. Hints reset (the visible list) when the error group changes, but
`hintsMax` is never reset, so a learner cannot get stars back by switching groups. Replaying a level
may only raise stars and score. The strip shows the sum of the best scores. Practice runs and twist
runs do not record anything.

## 11. How to add a level

1. Create `backend/content/levels/r6.yaml` using the schema in section 1. Use ids `t1..tn`; every
   token needs `w` (1 to 3), `topic` and `is_distractor`.
2. Design the board so the canonical solution fits: for each solution row,
   `indent + sum(w of tokens) <= cols`, and rows <= `rows`. Keep 2 to 4 distractors (the tests assert
   this range) and make sure each distractor leads to a *wrong* result, not another valid solution.
3. Fill `required_constructs`, `expected_output`, `twist_output` (choose a one-token swap that
   passes and prints it), `practice`, three `hints` and `group_hints` for at least
   `output_mismatch`, `wrong_order`, `bad_indent`, `missing_construct` (add `missing_colon` if the
   level uses a colon token).
4. Pick `order` after the existing levels; the client unlocks levels in `order`.
5. Restart the server (levels are cached at first use).
6. Update tests: `LEVELS` and the listing assertions in `tests/test_rows.py`
   (`test_levels_listing` checks the exact id and concept list), add the level to the
   parametrised twist and practice tests (`tests/test_learning_features.py`) and, if relevant, to
   `DISTRACTOR_CASES`.
7. Frontend: nothing is required for the select screen (it reads `/api/rows/levels`). The practice
   shortcuts in `frontend/js/main.js` (`PRACTICE_LEVEL`, and a special case for `r4`) name levels
   explicitly; update them if the new level should be a practice target. The mock data in
   `frontend/js/mock-rows.js` only has the original five levels.
8. The Dockerfile and `.dockerignore` already include `backend/content/levels/*.yaml`.

## 12. Open questions

- The contract (`docs/api-contract.md`) does not list `twist_output` and `predictions` in the
  `GET /api/rows/levels/{id}` response, but the server returns them and the client depends on them.
- `rows.public_level` indexes `lv["indent_cols"]` directly while the client has a default of 2; a
  level file without `indent_cols` would raise a `KeyError`.
- Twist: the position-set check is made after running the board, so the error message for an
  unrelated bad payload is the assembly error, not "Thay đúng một mảnh". Probably harmless.
- `unused_distractors` in a twist response has no meaning.
- Stars and score are client-computed and stored in `localStorage`; they are not verifiable on the
  server.
- The spec (section 7) describes Beginner levels only; levels have no `level` (beginner / intermediate
  / advanced) field, and the start-screen level choice only affects Code Rescue.
