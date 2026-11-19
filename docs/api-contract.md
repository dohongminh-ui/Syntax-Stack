# Syntax Stack — Code Rescue API contract (v1)

Backend: Python FastAPI in `backend/`, serves the static frontend from `frontend/` at `/` and the API under `/api`.
Run: `cd backend && python -m uvicorn app.main:app --port 8000`
The server is stateless. Game state (grid, score, mistakes, streak) lives in the browser. The server owns puzzles and correctness.

All user-facing strings (prompt, message, explanation, hints) are Vietnamese with full diacritics, unless the request
asks for English (next section).

## Language (Vietnamese or English)

Every HTTP request may send the header `X-Lang: en` or `X-Lang: vi`. Missing or unknown means `vi`, and the Vietnamese
responses are byte-identical to what the server sent before English existed. The language only changes display text
(prompts, hints, explanations, `message`, `detail` of errors, level titles and goals, dashboard labels, canned tutor
fallbacks); the code, the options and their order, the answers, the verdicts, the puzzle selection and every ranked / PvP
replay are the same in both languages. Program code and output stay as authored (`diem`, `"Tổng: 3"`, `"Đậu"`).

The PvP WebSocket takes the language per connection: `/api/pvp/ws?ticket=...&lang=en`. Messages sent to that player
(coach lines, suggestions, errors, the cancel reason, Misaki's title) are in it; the two players of a match may differ.
Without `lang` the connection keeps the language of the request that created the ticket (`X-Lang`, default `vi`).

Generated nicknames follow the language of the request too (`GET /api/nickname`, random classroom names, the "Bot" opponent): Vietnamese
"Mèo Xanh 42", English "Blue Cat 42" (`<adjective> <animal> <NN>`, same length rules). A name already chosen is never translated, and
the check that a ranked / race name is a generated one accepts both forms.

Misaki's AI tutor: the body sent to n8n for every task is `{"task", "lang": "en" | "vi", "context"}`, and the reply cache
is keyed by the language as well.

Implementation: `backend/app/i18n.py` (`LangMiddleware`, `tr(vi, en)`, `pick(obj, field)`). Authored content keeps the
English text in a sibling field with an `_en` suffix (`prompt_en`, `hints_en`, `explanation_en`, `title_en`, `goal_en`,
`group_hints_en`, and `<name>_en` keys in `mistakes.yaml`, `mistake_labels.yaml` and `misaki_coach.yaml`).

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
`puzzles` counts playable rows only; the debug-only `find_bug` forms are not included. `tutor` reports the AI tutor since local midnight (in-process, reset on restart): `configured` = URL and token are set; `calls_today` = real outbound calls (cache hits are not counted); `ai_today` = those that produced an AI reply; `fallback_today` = canned replies for any reason; `limit` = `SYNTAX_STACK_TUTOR_DAILY_LIMIT` (default 500, `0` = tutor disabled); `client_limit` = `SYNTAX_STACK_TUTOR_CLIENT_LIMIT` (default 40 real calls per visitor per day).

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

## POST /api/rescue/debrief
End-of-run summary for Code Rescue.
```json
{ "level": "intermediate", "mode": "rescue", "end_reason": "crash",
  "wrong": [ { "puzzle_id": "loops_range_fill__003", "kind": "rescue", "option_id": "b" } ] }
```
`mode` is `rescue` or `practice`; `end_reason` is `crash` or `nofit`; `wrong` has 1 to 12 items
`{ puzzle_id (max 80), kind: rescue|debug|last_commit, option_id?, order?, line_id? }`. Unknown puzzle ids
are skipped; if none remain the answer is 422 "Không có lỗi nào để tổng kết.". The server builds the
context from the bank (topic counts, most-missed topic, prompts, diagnoses); the client sends no free text.
Response: `{ "text": "...", "source": "ai" | "canned", "focus_topic": "loops" }` where `focus_topic` is
`variables`, `conditions`, `loops` or `functions` (ties go to the topic seen first).

---

# Custom puzzle sets ("paste your own code")

A learner pastes one program; the server runs it in a sandbox child process (see
`docs/validator-and-safety.md` section 5.1), and returns up to four verified puzzles built from it.
Puzzle ids are `c-<setid>-<n>` (`setid` = 8 lowercase base32 characters: `a-z`, `2-7`). Sets live in
`backend/data/custom.sqlite` for 30 days.

## POST /api/custom/sets
Request: `{ "code": "<program>", "level": "beginner" | "intermediate" | "advanced" }` (`level` optional,
default `intermediate`; it only decides how many options a view shows, like everywhere else).

Input rules (checked before anything runs; failures are 422): at most 800 characters; 2 to 15 non-empty
lines (comments and blank lines are removed first); no tab; indentation in multiples of 4 spaces; must
pass the validator whitelist (no import, attribute access, lambda, `**`, ...); `*` is refused when an
operand is a string, f-string, list or tuple (`"ab" * n`, `[0] * n`). The program must then run without
error and print 1 to 5 lines of at most 40 characters.

Response 200:
```json
{
  "id": "k3x7q2mf",
  "topic": "loops",
  "code": "total = 0\nfor i in range(1, 5):\n    total = total + i\nprint(total)",
  "expected_output": "10",
  "puzzles": [
    { "id": "c-k3x7q2mf-1", "template_id": "custom", "topic": "loops", "type": "predict_output", "tier": 1,
      "prompt": "...", "code": "...", "expected_output": null, "lines": null,
      "options": [ { "id": "a", "text": "11" } ] }
  ],
  "skipped": [ { "type": "parsons", "reason": "Cần ít nhất 3 dòng để làm bài sắp xếp." } ]
}
```
- `code` is the normalised source (comments and blank lines removed). `expected_output` is what the
  program prints. (It is also the answer to the predict puzzle; the learner wrote the program, so this
  is by design, but a UI that shows the set header should not show it before a predict puzzle is answered.)
- `puzzles` holds the generated puzzles in this order, each only when it could be made unambiguous:
  `predict_output`, `find_bug`, `fill_blank`, `parsons`. Each view has exactly the fields of
  `POST /api/puzzle/next` (`bank.public_puzzle`) and never contains answers. `tier` is always 1,
  `template_id` is `"custom"`, `topic` is inferred: a `def` means `functions`, else `for`/`while` means
  `loops`, else `if` means `conditions`, else `variables`.
- `skipped` lists every type that was not made, with a Vietnamese reason. `puzzles` is never empty on a
  200.
- Every option was verified by running it: the correct option gives the expected output, every wrong one
  does not; predict outputs are distinct; find_bug options span at least two lines; a parsons starting
  order does not already pass. Parsons needs 3 or more distinct lines and indents of at most 2 levels,
  and is checked by running the assembled program, so any order and indent that prints the expected
  output is accepted.

Errors (`{ "detail": "<Vietnamese reason>" }`):

| Status | When |
| --- | --- |
| 422 | too long / too short / too many lines, tab, indent not a multiple of 4, syntax error, unsafe construct, string or list multiplication, program raises an error, runs too long (step limit, 5 s wall clock or memory), prints nothing, prints more than 5 lines or a line over 40 characters, or no puzzle could be generated (the reasons are in the message). A missing `code` or an invalid `level` is the usual FastAPI 422 with a list `detail`. |
| 429 | more than 10 sets per hour from the same client (`CF-Connecting-IP` or the peer address), or the sandbox is busy (4 programs already running). |

## GET /api/custom/sets/{id}?level=beginner|intermediate|advanced
Same body as the 200 above for the stored set, without running anything, except that `code` and
`expected_output` are `null`: together they answer every puzzle in the set, so only the creator's POST
response carries them. A student opening a shared link never receives them. `level` is optional (default
`intermediate`). `404 { "detail": "..." }` for an unknown, malformed or expired (older than 30 days) id.

## Existing puzzle endpoints with `c-` ids
- `POST /api/puzzle/{id}/answer`, `GET /api/puzzle/{id}/hint?level=` and `POST /api/puzzle/{id}/explain`
  accept custom ids and behave exactly as for bank puzzles. Answers for `fill_blank`, `predict_output` and
  `find_bug` read the stored verified options; a `parsons` answer is run in the sandbox. If that run
  times out or fails, the answer counts as wrong (`output_mismatch`). Hints are three generic Vietnamese
  hints per type; the explanation is a short generic text per type. An unknown or expired id is 404.
- `GET /api/puzzle/{id}/rematch` with a custom id returns 422
  `{ "detail": "Câu đố tự tạo không có bản luyện lại." }`.

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

## POST /api/rows/levels/{id}/explain-prediction
Body: the run body with a required `prediction` (1 to 240 characters after trimming) and `rows`
(`trace` is ignored). The server re-runs the board. 422 when the prediction is empty, when the
program did not finish ("Chương trình chưa chạy xong để đối chiếu dự đoán.") or when the prediction is
already correct ("Dự đoán này đã đúng."). Otherwise `{ "text": "...", "source": "ai" | "canned" }`.
The tutor gets the goal, code, prediction, actual and expected output, `passed` and at most 40 trace steps.

## GET /api/rows/levels/{id}/hint?level=1|2|3&error_group=output_mismatch
`{ "level": 1, "text": "...", "source": "canned" }`. Without `error_group`, returns the level's general hint.

## POST /api/rows/levels/{id}/hint?level=1|2|3
Send the last attempt in the same format as the run endpoint. The server diagnoses that board
and returns `{ "level": 1, "text": "...", "source": "ai" }` for contextual coaching when available.
An optional zero-based `trace_step` (integer >= 0; a step that is not in the trace returns 422) gives the tutor the selected step from the server-verified trace.
An empty or passing board or an unavailable tutor returns `"canned"`.

## Input limits
- `prediction`: at most 240 characters (run, hint and teach-back requests share the run body).
- `prediction`: required (non-empty after trimming) for explain-prediction.
- `reflection` (teach-back): 1 to 400 characters.
- `wrong` (debrief): 1 to 12 items.
- `trace_step` (rows coach hint): integer >= 0 and less than the number of recorded trace steps.
- `level` (hint query): 1 to 3.

---

# Live classroom rooms

A teacher opens a room, students join with a nickname and play normally, and the teacher's dashboard
shows what the class is getting wrong. Data is server-verified: correctness and the mistake are computed
from the bank when `POST /api/puzzle/{id}/answer` checks an answer, never taken from the client. Only
nicknames are stored (no other personal data), in `rooms.sqlite` beside the custom-sets file. A room
expires 12 hours after its last student activity (create, join, answer, progress) and is purged lazily.
All errors are `{ "detail": "<Vietnamese message>" }`. Room codes are case-insensitive.

## POST /api/rooms
`{ "level": "beginner"|"intermediate"|"advanced", "title"?: str (max 40, no control characters), "names"?: "random"|"free" (default "random") }` ->
```json
{ "code": "K7M2Q", "teacher_key": "<32 hex, secret>", "join_url": "https://host/?room=K7M2Q",
  "level": "intermediate", "title": "Lớp 10A", "names": "random" }
```
`code` is 5 characters from `ABCDEFGHJKLMNPQRSTUVWXYZ23456789`. `title` is `""` when omitted. `join_url` is
built from the request, honouring `X-Forwarded-Proto` / `X-Forwarded-Host`; the env var
`SYNTAX_STACK_PUBLIC_URL` (e.g. `https://syntaxstack.example`) overrides it. The teacher key is shown
only here (the server keeps just its hash). Limit: 5 rooms per hour per client IP, then 429.

## GET /api/rooms/{code}
-> `{ "code", "level", "title", "open": true, "players": 12, "names": "random"|"free" }` (players = count). 404 for an unknown or expired room.

## POST /api/rooms/{code}/join
`{ "nickname"?: str }`. In a `random` room the body's nickname is optional and ignored: the server assigns a
generated name (`"<animal> <adjective> <NN>"`, see `GET /api/nickname`) that is unique in the room. In a `free`
room `nickname` is required (trimmed, 1 to 20 characters, no control or invisible-format characters; 422
otherwise) and is also checked against the name blocklist: `422 "Biệt danh này không được dùng. Hãy chọn tên khác."`.
A free nickname already in the room (case-insensitive) gets " 2", " 3", ... appended. Response:
`{ "player_id", "player_token": "<32 hex>", "nickname", "level" }`, where `nickname` is always the final name. 404 unknown
room, 410 closed room, 409 when the room already has 60 players. Keep `player_token`; it is the player's
only credential.

## POST /api/puzzle/{id}/answer (extended)
The body gains optional `room: str` and `player_token: str`. When both are valid (open room, token
belongs to that room) and the id is a bank puzzle (not `c-`), the server also records
`{room, player, puzzle_id, template_id, topic, type, correct, mistake_key, ts, tier}` (`tier` of the bank puzzle,
1 to 3: it bounds the leaderboard score, see `progress`). `mistake_key` is the chosen
option's named mistake if it has one, else the result's `error_group`, else `null` (correct answers).
Parsons use the `error_group`. An invalid room or token is ignored silently: the response is identical and
nothing is logged. A failed or malformed check (422) is never logged, and logging can never fail the
answer. Every call is logged, so send `room` / `player_token` only on the call that is the player's real
attempt (not on a second `reveal` call for the same attempt).

## POST /api/rooms/{code}/progress
`{ "player_token", "score": int 0..10000000, "status": "playing"|"crash"|"nofit", "bugs_fixed": int 0..1000000 }`
-> `204`. Used only for the leaderboard, and the server caps what it stores: `score` is stored as
`min(score, ceiling)`, where the ceiling is the most a Code Rescue run could score given the correct answers the
server logged for that player, and `bugs_fixed` as `min(bugs_fixed, those correct answers)`. Nothing is rejected
and the response never changes: an honest score is stored as sent, an impossible one is lowered to the ceiling.
The ceiling is `64 + 217 * n1 + 519 * n2 + 927 * n3`, where `n1`, `n2`, `n3` are the player's correct answers to
distinct tier 1, 2 and 3 puzzles (a puzzle answered again counts once; see `rooms.score_ceiling` for the
derivation: the 8x8 board bounds the placement points, the lock and bug-fix rewards need an answer each). A new
player with nothing verified can show at most 64. It is an upper bound, not a replay: exact scores are what
ranked runs and races verify. The score is the run being played now, not a total over runs, and the browser
must report Rescue games only (a Practice game clears rows for free and has no such bound). 403 for an unknown
token; a closed room ignores it (204). Syntax Rows sends nothing to a room.

## GET /api/rooms/{code}/summary   (header `X-Teacher-Key`; 403 if wrong or missing)
```json
{ "code": "K7M2Q", "title": "Lớp 10A", "level": "intermediate", "open": true, "created_at": 1767225600,
  "totals": { "players": 12, "answers": 140, "correct": 96 },
  "players": [ { "player_id": "p1a2b3c4", "nickname": "An", "score": 420, "status": "playing", "answers": 14, "correct": 11, "last_seen_s": 8 } ],
  "grid": { "loops": { "fill_blank": { "answers": 9, "correct": 6 }, "predict_output": {}, "parsons": {}, "find_bug": {} } },
  "top_mistakes": [ { "key": "off_by_one_high", "label": "Lệch một đơn vị (thừa)", "count": 7, "topic": "loops", "players": 5 } ],
  "unsolved": [ { "puzzle_id": "loops_range_fill__003", "prompt": "...", "topic": "loops", "attempts": 4, "players": 3 } ],
  "recent": [ { "nickname": "An", "topic": "loops", "type": "fill_blank", "correct": false,
                "mistake_label": "Lệch một đơn vị (thừa)", "ago_s": 12 } ] }
```
- `created_at`: Unix seconds. `players` is sorted by `score` descending (ties by nickname); a player who
  never reported progress has `score` 0, `status` `"playing"`. `last_seen_s`: seconds since their last answer or progress.
- `grid` always has all 4 topics (`variables`, `conditions`, `loops`, `functions`) x 4 types (`fill_blank`,
  `predict_output`, `parsons`, `find_bug`); empty cells are `{ "answers": 0, "correct": 0 }`.
- `top_mistakes`: top 5 wrong-answer keys by count; `topic` is the key's most frequent topic, `players` the
  number of distinct players. `label` is short Vietnamese: for a named mistake the text of
  `content/mistakes.yaml` before the first ":" (else its first sentence), at most 60 characters; for error
  groups `output_mismatch` "Sai kết quả đầu ra", `wrong_order` "Sai thứ tự", `bad_indent` "Sai thụt lề",
  `syntax` "Lỗi cú pháp", `wrong_fix` "Sửa sai dòng", `wrong_line` "Sửa nhầm dòng", `runtime` "Lỗi khi chạy",
  anything else (including `wrong_choice` without a named mistake) "Lỗi khác".
- `unsolved`: puzzles with at least 2 wrong attempts and 0 correct ones, top 5 by `attempts` (wrong attempts).
- `recent`: the last 10 answers, newest first; `mistake_label` is `null` for correct answers.

## POST /api/rooms/{code}/players/{player_id}/kick   (header `X-Teacher-Key`; 403 if wrong or missing)
-> `204`. 404 for an unknown player. The player and all their answers disappear from every part of the summary
(players, grid, top_mistakes, unsolved, recent, totals); their `player_token` stops working (answers are not
logged, `progress` answers 403) and cannot be used to rejoin. Joining again creates a new player; to stop that,
close the room.

## GET /api/nickname
-> `{ "nickname": "Mèo Xanh 42" }`, a fresh random generated name on every call. 60 per minute per client IP, then 429.
Ranked runs and races accept only such names (`422 "Hãy dùng tên được tạo ngẫu nhiên."` otherwise).

## POST /api/rooms/{code}/close   (header `X-Teacher-Key`)
-> `{ "open": false }`. New joins get 410, answers stop being logged, the summary stays readable.

## DELETE /api/rooms/{code}   (header `X-Teacher-Key`)
-> `204`. Removes the room, its players and all its answers.

## GET /api/rooms/{code}/qr.svg
`image/svg+xml` QR code of the room's `join_url`: dark modules `#141518` on white (dark-on-light so phone cameras can scan it),
quiet zone 2, `Cache-Control: private, max-age=300`. 404 for an unknown room. (The page CSP already
allows it: `img-src 'self'`.)

---

# Ranked runs, leaderboard and races

Full contract and rules: [`ranked-and-race.md`](ranked-and-race.md). Summary of the endpoints (errors are
`{ "detail": "<Vietnamese message>" }`):

| Endpoint | Body / query | Response |
| --- | --- | --- |
| `POST /api/runs` | `{kind: "ranked"\|"race", level?, nickname, device_id, race?}` | `{run_id, run_token, seed, level, kind, race?, practice?}`. 404 unknown race, 410 race expired or full (30 players), 409 5 practice runs already used in this race, 422 bad nickname / device id / missing level or race code, 429 over 30 runs per hour per client IP |
| `POST /api/runs/{run_id}/finish` | `{run_token, moves: [...], client_score?}` (up to 3000 moves; body limit 192 KB) | `{status: "verified", score, locks, mistakes, bugs_fixed, best_streak, duration_s, rank, practice?, race?}` or `{status: "rejected", reason}`. 403 bad token, 404 unknown, 409 already finished, 410 older than 3 hours |
| `GET /api/leaderboard` | `level`, `period=day\|week\|all` (default `all`), `device_id?` | `{level, period, entries: [{rank, nickname, score, locks, at}], you: {rank, score} \| null}` (top 50, ranked runs only, Asia/Ho_Chi_Minh day / week) |
| `POST /api/races` | `{level, nickname, device_id}` | `{code, level, url}` (no seed: it is only returned when a run starts); 10 races per hour per client IP |
| `GET /api/races/{code}` | `device_id?` | `{code, level, created_by, created_at, expires_at, results: [{rank, nickname, score, locks, mistakes, duration_s, finished_at, you?}], playing, practice_runs}`; results are each device's first (official) run only (`docs/ranked-and-race.md` 5.1); `you` only with a valid `device_id` |

Extended existing endpoints (all fields optional; invalid values are ignored and never change the response):

- `POST /api/puzzle/next` also accepts `run_id` + `run_token`. With a valid pair the puzzle is picked
  deterministically from the run's seed (the run's level is used and `exclude_*` are ignored) and recorded.
- `GET /api/puzzle/{id}/hint?level=n` also accepts `run_id` + `run_token` (query) and records the highest hint level.
- `POST /api/puzzle/{id}/answer` also accepts `run_id` + `run_token` and records the checked result (first
  answer counts). Room fields keep working alongside.

---

## Real-time 1v1 "Đối kháng" (`/api/pvp/*`, full contract in [`pvp.md`](pvp.md))

Nicknames must be generated names and `device_id` 32 hex chars (422 otherwise, as for `/api/runs`); 60 requests
per hour per client IP across the four POST endpoints (429); 503 when 200 matches are live.

- `POST /api/pvp/queue` `{level, nickname, device_id}` → `{ticket}`. Joins the quick-match queue of that level.
- `DELETE /api/pvp/queue/{ticket}` → 204; 404 unknown ticket; 409 match already started.
- `POST /api/pvp/private` `{level, nickname, device_id}` → `{code, ticket, url}` (`url` = `<public base>/?duel=<code>`).
- `POST /api/pvp/private/{code}/join` `{nickname, device_id}` → `{ticket}`. 404 unknown, 409 full, 410 expired.
- `POST /api/pvp/bot` `{level, nickname, device_id, misaki?, training?}` → `{ticket}`. A match against the built-in bot
  (no rating). `misaki` (1..4) plays Misaki, the search-based AI opponent, of that ladder level: 403 while it is locked
  for the device, 422 for a value outside 1..4. `training` (needs `misaki`) adds coaching; nothing is ranked or
  unlocked in training. Without `misaki`: the generic "Máy <animal>" bot. See [`pvp.md`](pvp.md) section 5.
- `GET /api/pvp/misaki?device_id=` → `{unlocked: n, wins: {"1": k, ...}, games: {"1": k, ...}}` (the Misaki ladder of a
  device; 422 for a bad device id).
- `GET /api/pvp/ws?ticket=<ticket>` (WebSocket). JSON messages `{"t": ...}`; client → server `ready, place, bomb,
  shuffle, undo, resign, ping, rematch, suggest` (`suggest`: training matches only, else `error not_training`);
  server → client `lobby, start, state, opponent, sent, incoming, landed, opponent_status, end, rematch_status,
  coach, suggestion, error, pong`. Against Misaki the lobby `opponent` also has `misaki, title, training, plays_as`
  (`misaki`/`title` = the level the player chose) and `end` has `misaki: {level, unlocked_now}`. Same-origin only in the page's CSP (`connect-src` names
  `wss://<host>` explicitly).

Puzzle endpoints inside a match (fields from the `start` message):

- `POST /api/puzzle/next`: extra optional body fields `match_id`, `match_token`, `bug` (id of the tapped bug line,
  for `kind: "debug"`). With a valid pair the server ignores `topic`, `tier`, `level` and the exclude lists and picks
  the puzzle for the player's current lock (or for bug line `bug`); 409 when there is nothing to solve.
- `POST /api/puzzle/{id}/answer`: extra optional `match_id`, `match_token`. The response is unchanged; with a valid
  pair and a puzzle served to the player for their current lock / bug line the outcome is applied to their game and
  pushed on the socket.
- `GET /api/puzzle/{id}/hint?level=n`: extra optional query `match_id`, `match_token` (records the hint level).
Invalid or missing pairs are ignored: the endpoints then behave as before.

## Errors
`404 { "detail": "..." }` for unknown puzzle id or no puzzle matching the filters (custom sets: see the custom section for 422 and 429; rooms: see the live classroom section for 403, 404, 409, 410 and 429), `422` for a malformed body (including lists over their caps: `exclude_ids` 1000, `exclude_templates` 50, `order` 30, `rows`/`baseline` 30, `tokens` per row 30; ids up to 40 characters, `template_id` 80), `413 { "detail": "Yêu cầu quá lớn." }` for a request body over 64 KB.
