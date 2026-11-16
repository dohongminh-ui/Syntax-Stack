# Syntax Stack — Code Rescue API contract (v1)

Backend: Python FastAPI in `backend/`, serves the static frontend from `frontend/` at `/` and the API under `/api`.
Run: `cd backend && python -m uvicorn app.main:app --port 8000`
The server is stateless. Game state (grid, score, mistakes, streak) lives in the browser. The server owns puzzles and correctness.

All user-facing strings (prompt, message, explanation, hints) are Vietnamese with full diacritics.

## Enums

- `topic`: `"variables" | "conditions" | "loops" | "functions"`
- `type`: `"parsons" | "fill_blank" | "predict_output" | "find_bug"`
- `tier`: `1 | 2 | 3` (1 row cleared → 1, 2 rows → 2, 3+ rows → 3; a 4+ "Boss" clear = the client requests two tier-3 puzzles)
- `level`: `"beginner" | "intermediate" | "advanced"`
- `kind`: `"rescue" | "debug" | "last_commit"`
- `error_group`: `"wrong_order" | "bad_indent" | "syntax" | "output_mismatch" | "wrong_line" | "wrong_fix" | "wrong_choice"`

## GET /api/health
```json
{ "ok": true, "puzzles": 559,
  "tutor": { "configured": true, "calls_today": 12, "ai_today": 10, "fallback_today": 3, "limit": 500 } }
```
`puzzles` counts playable rows only; the debug-only `find_bug` forms are not included. `tutor` reports the AI tutor since local midnight (in-process, reset on restart): `configured` = URL and token are set; `calls_today` = real outbound calls (cache hits are not counted); `ai_today` = those that produced an AI reply; `fallback_today` = canned replies for any reason; `limit` = `SYNTAX_STACK_TUTOR_DAILY_LIMIT` (default 500, `0` = tutor disabled).

## POST /api/puzzle/next
Request:
```json
{
  "topic": "loops",
  "tier": 1,
  "level": "beginner",
  "kind": "rescue",
  "template_id": null,
  "exclude_ids": ["loops_range_fill__007"],
  "exclude_templates": ["loops_range_fill"]
}
```
- `kind: "last_commit"` selects like `rescue`, but `topic` is optional (a random topic is picked) and `tier` defaults to 3. `kind: "rescue"` requires `topic` and `tier`.
- `kind: "debug"` requires `template_id` (the template of the puzzle the player got wrong). Returns a different variant of that same template, as type `find_bug` if the template family has a find_bug form, otherwise the same type. `topic` and `tier` are ignored for debug; the client excludes the puzzle that was just answered with `exclude_ids`.
- `exclude_templates` is a soft preference (ignored if it would leave nothing). `exclude_ids` is hard.
- `level` changes option count: beginner max 3 options, intermediate/advanced 4.

Response (`Puzzle`, never contains the answer):
```json
{
  "id": "loops_range_fill__012",
  "template_id": "loops_range_fill",
  "topic": "loops",
  "type": "fill_blank",
  "tier": 1,
  "prompt": "Điền giá trị còn thiếu để chương trình in ra 0, 1, 2.",
  "code": "for i in range(___):\n    print(i)",
  "expected_output": "0\n1\n2",
  "lines": null,
  "options": [ { "id": "a", "text": "2" }, { "id": "b", "text": "3" }, { "id": "c", "text": "4" } ]
}
```
Per type:
- `fill_blank`: `code` contains exactly one `___`. `options` = candidate fragments. `expected_output` shown.
- `predict_output`: `code` is the full program. `options` = candidate outputs (multi-line strings allowed). `expected_output` is `null`.
- `parsons`: `code` is `null`. `lines` = shuffled `[{ "id": "l1", "text": "print(i)" }]`, text without leading indentation. Player orders all lines and sets each line's indent level (0, 1 or 2). `expected_output` shown. `options` is `null`.
- `find_bug` (v2): `lines` = the buggy program in order `[{ "id": "l1", "text": "for i in range(1, 4):", "indent": 0 }]`. `options` = whole-line edits, each tied to a line: `[{ "id": "a", "line_id": "l1", "text": "for i in range(1, 5):" }, { "id": "b", "line_id": "l2", "text": "print(i + 1)" }]`. Options must cover **at least two different lines** (the correct fix, 1–2 wrong edits of the buggy line, and 1–2 wrong edits of other lines), so the options never reveal which line is buggy. Every non-correct option must fail validation. The player picks one option. `expected_output` shown.

## POST /api/puzzle/{id}/answer
Request (one of, by type) plus `reveal`:
```json
{ "option_id": "b", "reveal": true }
{ "order": [ { "line_id": "l2", "indent": 0 }, { "line_id": "l1", "indent": 1 } ], "reveal": true }
{ "option_id": "c", "reveal": true }
```
(find_bug v2 answers with `option_id` only; a `line_id` field, if sent, is ignored. Wrong option on another line → `wrong_line`, wrong edit of the buggy line → `wrong_fix`.)
`reveal: true` on the player's final attempt (always true in Rescue mode, which has one attempt). When `reveal` is false and the answer is wrong, `solution` and `explanation` are `null`.

Response:
```json
{
  "correct": false,
  "error_group": "output_mismatch",
  "message": "Đầu ra không khớp: chương trình in 0, 1 nhưng cần 0, 1, 2.",
  "actual_output": "0\n1",
  "solution_code": "for i in range(3):\n    print(i)",
  "explanation": "range(n) dừng trước n, nên range(3) cho 0, 1, 2."
}
```

## GET /api/puzzle/{id}/hint?level=1|2|3
`{ "level": 1, "text": "range() dừng trước giá trị kết thúc.", "source": "canned" }`

## POST /api/puzzle/{id}/explain
Accepts the same attempt fields as the answer endpoint. Invalid placements and correct answers
return 422 (an unknown puzzle id returns 404). A wrong answer returns `{ "text": "...", "source": "ai" }` or `"canned"` fallback.
The game shows this explanation on the result screen.

## GET /api/puzzle/{id}/rematch?level=beginner
`level` is optional (default `intermediate`) and only affects option count. Returns `{ "puzzle": { ... }, "text": "...", "source": "ai" }`, with `"canned"` as fallback.
The puzzle is a different verified variant of the same template and tier. Its shape matches
`POST /api/puzzle/next` and the response contains the same public fields.

---

# Syntax Rows API (see `Syntax_Rows_Gameplay_Spec.md`)

Levels live in `backend/content/levels/*.yaml` (5 Beginner levels from spec §7). Each level file holds: id, order, title, goal (Vietnamese), expected_output, rows, cols (10), tokens (id, text, w in 1..3, topic or "syntax", is_distractor), canonical solution as rows of token ids with indent, required AST constructs (e.g. `For`, `If`, `FunctionDef`), 3 general hints, and 3 hints per error_group.

Additional `error_group` values for Syntax Rows: `"missing_colon" | "missing_construct" | "empty"`.

## GET /api/rows/levels
`[ { "id": "r1", "order": 1, "title": "Biến đầu tiên", "concept": "variables", "rows": 4, "cols": 10 } ]`

## GET /api/rows/levels/{id}
Never contains the solution or which tokens are distractors.
- `twist_output`: the level's alternate target output for the twist step, or `null` if the level has none.
- `predictions`: authored candidate outputs for the predict-the-output step (for example `["6", "1
3
6"]` on r4); `[]` when the level has none, as on r3.
- `indent_cols`: how many columns the first token of a row may start at to count as indentation. Defaults to `2` when a level file omits it.
```json
{
  "id": "r3", "order": 3, "title": "Đếm đến ba",
  "goal": "Viết chương trình in ra 0, 1, 2, mỗi số một dòng.",
  "expected_output": "0\n1\n2",
  "twist_output": "0\n1",
  "predictions": [],
  "rows": 4, "cols": 10, "indent_cols": 2,
  "tokens": [ { "id": "t1", "text": "for", "w": 1, "topic": "syntax" },
              { "id": "t4", "text": "range(3)", "w": 3, "topic": "loops" } ]
}
```

## POST /api/rows/levels/{id}/run
```json
{ "rows": [ { "row": 0, "tokens": [ { "id": "t1", "col": 0 }, { "id": "t2", "col": 1 } ] },
            { "row": 1, "tokens": [ { "id": "t7", "col": 1 } ] } ] }
```
Server rules: a token id may appear at most once; first token col ≤ 2 gives indent level = col (4 spaces per level); tokens in a row are joined by one space in col order; empty rows are skipped; overlapping tokens or col + w > cols → 422.
Response:
```json
{
  "passed": false,
  "error_group": "output_mismatch",
  "row": 0,
  "message": "Đầu ra không khớp: chương trình in 0, 1 nhưng cần 0, 1, 2.",
  "actual_output": "0\n1",
  "expected_output": "0\n1\n2",
  "code": "for i in range(2) :\n    print(i)",
  "unused_distractors": null
}
```
`row` = the board row index to mark red (from the syntax error line, or the first row that differs from the canonical solution when the output is wrong; `null` if unknown). On `passed: true`, `error_group`/`row` are null and `unused_distractors` = number of distractor tokens not placed.

Set `"trace": true` alongside `rows` to include `trace: { steps, truncated }`. Each step gives
the zero-based board `row`, the line's `code`, its function `scope` (or null), visible scalar
`bindings` as display strings, and cumulative `output` after the line. The recorder keeps up
to 48 steps, and a run that fails before execution has an empty trace.

The optional `prediction` field contains the player's predicted output (at most 240 characters, else 422). The response adds
`prediction: { correct }`, where `correct` compares against the actual output when execution
finishes, or is null when execution fails. The prediction has no effect on the board grade.

## GET /api/rows/levels/{id}/practice
Returns `{ rows }` for a runnable board with an authored mistake.

## POST /api/rows/levels/{id}/twist
`trace_step`/`prediction` limits are listed under Input limits below. Send the `rows` of the changed board and the `baseline` rows of a passing board. One token ID
must differ at the same position. The response uses the run format, with the level's alternate
target output. The optional trace works the same way.

## POST /api/rows/levels/{id}/teach-back
Send a passing board in `rows` and a short `reflection` (1 to 400 characters after trimming; empty, whitespace-only or over-long text and a board that has not passed return 422). Returns `{ text, source }` from the
tutor using the verified program and the player's own words.

## GET /api/rows/levels/{id}/hint?level=1|2|3&error_group=output_mismatch
`{ "level": 1, "text": "...", "source": "canned" }`. Without `error_group`, returns the level's general hint.

## POST /api/rows/levels/{id}/hint?level=1|2|3
Send the last attempt in the same format as the run endpoint. The server diagnoses that board
and returns `{ "level": 1, "text": "...", "source": "ai" }` for contextual coaching when available.
An optional zero-based `trace_step` (integer >= 0; a step that is not in the trace returns 422) gives the tutor the selected step from the server-verified trace.
An empty or passing board or an unavailable tutor returns `"canned"`.

## Input limits
- `prediction`: at most 240 characters (run, hint and teach-back requests share the run body).
- `reflection` (teach-back): 1 to 400 characters.
- `trace_step` (rows coach hint): integer >= 0 and less than the number of recorded trace steps.
- `level` (hint query): 1 to 3.

---

## Errors
`404 { "detail": "..." }` for unknown puzzle id or no puzzle matching the filters, `422` for a malformed body.
