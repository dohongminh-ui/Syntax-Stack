# Optional AI tutor

The AI tutor is an *optional* layer that turns validator results into short, readable feedback. The
game is complete without it: every tutor-backed endpoint has an authored fallback, and when the tutor
is not configured nothing ever calls out.

Code: `backend/app/tutor.py` (client), `backend/app/main.py` (what is sent), `deploy/n8n-tutor.json`
(a reference n8n workflow). Frontend labelling: `frontend/js/editor.js: tutorNote`.
Related: [architecture.md](architecture.md), [validator-and-safety.md](validator-and-safety.md),
[syntax-rows.md](syntax-rows.md), [operations.md](operations.md).

## 1. Design in one paragraph

The server decides correctness with the validator, then calls `tutor.feedback(task, context,
fallback)`. If both `SYNTAX_STACK_TUTOR_URL` and `SYNTAX_STACK_TUTOR_TOKEN` are set and a concurrency
slot is free, it POSTs `{task, context}` to an n8n webhook, validates the reply, caches it, and
returns `{"text": ..., "source": "ai"}`. In every other case (not configured, busy, timeout, HTTP
error, malformed reply) it returns `{"text": <authored fallback>, "source": "canned"}`. The browser
shows the `source` so the learner can tell which is which. The tutor's text is only ever displayed.

## 2. The four tasks and the exact request

Every request body is the JSON object `{"task": "<name>", "context": {...}}` serialised with
`ensure_ascii=False` (`tutor.feedback`). The context is built in `main.py` from server-side data
(the stored puzzle row, the re-run board), never copied from what the client says about itself,
except the learner's own words in `teach_back` and the answer they chose.

### Task `explain`

Endpoint: `POST /api/puzzle/{id}/explain` (Code Rescue). Body: the same attempt fields as the answer
endpoint (`option_id` or `order`). The server first calls `bank.check_answer(..., reveal=True)`.
A correct answer returns HTTP 422 "Câu trả lời này đã đúng."; unknown option ids and malformed
orders are 422 as well.

Context (`main.py: puzzle_explain`):

| Key | Value |
| --- | --- |
| `prompt` | the puzzle prompt |
| `type` | `fill_blank`, `predict_output`, `parsons` or `find_bug` |
| `code` | the stored skeleton or program; for `find_bug` the buggy program rebuilt from `lines`; `null` for `parsons` (they have no `code`) |
| `choice` | the learner's answer as text: the option text; for `find_bug` `"Dòng N: <edited line>"`; for `parsons` the arrangement as indented lines |
| `diagnosis` | the validator or stored message for this choice (`result["message"]`) |
| `actual_output` | output this choice produced (may be `null`) |
| `expected_output` | the correct output (the stored value, including for `predict_output`) |
| `reference` | the authored explanation, with the mistake note prepended when there is one |
| `solution` | the correct program (`solution_code`) |

Fallback text: the authored explanation (`result["explanation"]`), or the diagnosis message if that is
empty. The tutor receives the solution here because the learner has already answered wrongly and the
result screen shows the solution anyway.

Real fallback response:

```json
{"text": "Lệch một đơn vị (thiếu): chọn giá trị nhỏ hơn đáp án đúng một đơn vị. range(5) cho các số từ 0 đến 4, tức là 0, 1, 2, 3, 4. range() không bao giờ gồm số kết thúc.",
 "source": "canned"}
```

### Task `rematch`

Endpoint: `GET /api/puzzle/{id}/rematch?level=beginner|intermediate|advanced`. The server picks a
different verified variant (same template and tier), then asks the tutor for a short bridging
sentence. Context:

| Key | Value |
| --- | --- |
| `previous_prompt` | prompt of the puzzle just answered |
| `next_prompt` | prompt of the new puzzle |
| `topic` | topic of the original puzzle |
| `hint` | level 1 hint of the new puzzle |

Fallback: "Thử áp dụng lại quy tắc vừa gặp vào câu đố mới này." Response: the usual
`{text, source}` plus `puzzle` (the public view of the new puzzle for that level):

```json
{"text": "Thử áp dụng lại quy tắc vừa gặp vào câu đố mới này.", "source": "canned",
 "puzzle": {"id": "loops_range_fill__003", "template_id": "loops_range_fill", "topic": "loops",
            "type": "fill_blank", "tier": 1, "prompt": "Điền giá trị còn thiếu để chương trình in ra 0, 1.",
            "code": "for n in range(___):\n    print(n)", "expected_output": "0\n1", "lines": null,
            "options": [{"id": "a", "text": "2"}, {"id": "b", "text": "1"}, {"id": "c", "text": "3"}]}}
```

The puzzle is always returned; only the sentence depends on the tutor. The context does not include
the learner's wrong choice.

### Task `teach_back`

Endpoint: `POST /api/rows/levels/{id}/teach-back` (Syntax Rows). Body `{rows, reflection}`.
`reflection` is 1 to 400 characters. The board is re-run and must pass (else 422). Context:

| Key | Value |
| --- | --- |
| `goal` | the level's goal text |
| `code` | the assembled program of the passing board |
| `output` | the program's actual output |
| `learner_explanation` | the learner's text, stripped |

Fallback (fixed text, Vietnamese then English): "Nếu đổi đúng một mảnh mã, đầu ra sẽ thay đổi thế
nào? / What would change in the output if you swapped one tile?"

### Task `coach`

Endpoint: `POST /api/rows/levels/{id}/hint?level=1..3` with the last attempt `{rows, trace_step?}`.
The server re-runs the board (with a trace when `trace_step` is given). If the board is empty or
already passes it returns the canned hint and does not call the tutor. Otherwise the context is:

| Key | Value |
| --- | --- |
| `goal` | the level's goal |
| `hint_level` | the hint level, 1 to 3 |
| `tier` | deprecated duplicate of `hint_level`, kept so existing n8n workflows keep working (it is the hint level, not a puzzle tier) |
| `code` | the assembled program |
| `diagnosis` | the validator message |
| `error_group` | `syntax`, `bad_indent`, `missing_colon`, `wrong_order`, `output_mismatch`, or `missing_construct` |
| `error_row` | zero-based board row of the error, or `null` |
| `actual_output` | output of the run, or `null` |
| `expected_output` | the level's target output |
| `reference` | the canned hint text for this level and group (an authored hint the tutor may build on) |
| `current_step` | only when `trace_step` was sent: `{step (1-based), row, code, scope, bindings, output}` copied from the server-built trace |

The context does **not** include the canonical solution or which tokens are distractors.
Fallback: the canned hint for the board's error group and the requested level. A `trace_step`
past the end of the trace is 422 (for failing boards).

Real shape of a successful response (`level` is added by the endpoint):

```json
{"level": 1, "text": "Vòng lặp dừng trước số nào?", "source": "ai"}
```

### Editorial task `content_review` (not used while playing)

`backend/scripts/review_content.py` sends `{"task": "content_review", "context": {template, reference}}`
with an 80 s timeout to the same webhook and expects `text` to be a JSON string with `hints` (3),
`mistakes` (3) and `followup`. The script then checks every drafted program with the validator, and
prints a packet marked `needs_editor_review` (see `backend/README.md`). It does not use the cache or
the slots (it calls `tutor.request_tutor` directly), and its output never enters the bank by itself.

## 3. What the tutor client expects back

`tutor.request_tutor(url, payload, timeout)` sends:

```
POST <SYNTAX_STACK_TUTOR_URL>
Content-Type: application/json
X-Syntax-Stack-Token: <SYNTAX_STACK_TUTOR_TOKEN>

{"task": "...", "context": {...}}
```

with `httpx`, `trust_env=False` (so `HTTP_PROXY` and similar variables are ignored), a 38 second
timeout for play-time calls, and `raise_for_status()`.

The reply must be a JSON **object**. `_ask` reads its `text` key and accepts it only if it is a string
whose stripped length is between 1 and 750 characters. The stripped text is returned. Any other key
is ignored (the reference workflow also returns `status`, `error_category`, `finish_reason`,
`provider` and `model`; only `review_content.py` looks at the first two).

```json
{"text": "Hãy xem lại giá trị kết thúc của range(): Python dừng trước giá trị đó."}
```

## 4. Environment variables and runtime limits

| Setting | Value | Notes |
| --- | --- | --- |
| `SYNTAX_STACK_TUTOR_URL` | n8n production webhook URL | Read with `os.getenv` at each call. Unset or empty means canned only. |
| `SYNTAX_STACK_TUTOR_TOKEN` | the shared secret | Sent as `X-Syntax-Stack-Token`. Both variables must be non-empty, or the tutor is skipped. |
| `SYNTAX_STACK_TUTOR_DAILY_LIMIT` | integer, default `500` | Real calls per local day (resets at local midnight, in process). `0` disables the tutor (always canned, reason `limit`). Cache hits do not count. |
| Request timeout | 38 s (`_ask`) | 80 s for `review_content.py`. |
| Reply limit | 1 to 750 characters after `strip()` | Violations raise `ValueError` and fall back. |
| Cache | manual 128-entry LRU dict keyed by `(url, payload)` in `feedback()` | See below. |
| Concurrency | `BoundedSemaphore(2)` | See below. |

`compose.yaml` sets `SYNTAX_STACK_TUTOR_URL` to `http://127.0.0.1:5678/webhook/syntax-stack-tutor`
and passes `SYNTAX_STACK_TUTOR_TOKEN` from the host environment.

### Cache

`feedback()` keeps a manual `OrderedDict` cache (128 entries, least recently used evicted) so a cache hit can be told from a real call. The key is the pair `(url, payload string)`, so only an
**identical** task and context (same prompt, same code, same wrong choice, same learner text) is
served from memory. Only successful replies are cached (exceptions are not). It is per process, has
no expiry, and is cleared on restart. With several uvicorn workers each has its own cache.

### Concurrency and non-blocking behaviour

`feedback()` does `_slots.acquire(blocking=False)`. If both slots are in use the call returns the
canned fallback immediately; it never waits in a queue. The slot is released in a `finally` block.
The cache is checked before the slot, so a cache hit never needs a slot. During a tutor call the worker thread of that request is blocked for up to 38 s
(FastAPI runs these endpoints in a thread pool).

### Fallback rules

`feedback()` returns canned text when any of the following is true:

1. `SYNTAX_STACK_TUTOR_URL` or `SYNTAX_STACK_TUTOR_TOKEN` is unset or empty.
2. No slot is free (`busy`).
3. The daily limit is reached or is 0 (`limit`).
4. `httpx.HTTPError`, `httpx.InvalidURL` (for example a malformed URL), `ValueError`, `KeyError` or `TypeError`
   is raised (`error`): timeouts, connection errors, any non-2xx status, a body that is not JSON or not
   an object, `text` missing, not a string, empty, or longer than 750 characters.

The reason is logged at WARNING level as `Tutor unavailable (<exception class name>)` and nothing
else; no payloads are logged.

### Usage log and counters

Every attempt logs one INFO line: `tutor task=<task> outcome=<outcome> latency_ms=<n>`, where outcome
is `ai`, `cached` or `canned:<reason>` (`not_configured`, `busy`, `limit`, `error`). The context and
the reply text are never logged. `GET /api/health` returns `tutor: {configured, calls_today,
ai_today, fallback_today, limit}`: `calls_today` counts real outbound calls (successful or not, the
thing the cap limits), `ai_today` the successful ones, `fallback_today` every canned reply for any
reason. Cache hits are in none of the counters. They reset at local midnight and on restart.

Tests that cover this (`backend/tests/test_tutor.py`, `test_learning_features.py`): the AI path
for `coach` (context carries the verified code, row and output), the selected trace step in the
context, a 422 for an out-of-range step, fallback when the webhook raises `ReadTimeout`
(response equals the canned hint), canned `explain` and verified `rematch` for all four puzzle types
with the URL unset, and `teach_back` receiving the verified output and the learner's words. These
tests replace `tutor._ask`, so they do not exercise the HTTP call, the 750-character rule or the
semaphore. `backend/tests/test_tutor_cost.py` replaces `tutor.request_tutor` and covers the bad URL
fallback, the daily cap, the counters, the cache rule and the log line.

## 5. Privacy: what is and is not sent

Sent to the webhook (and from there to the model provider):

- Puzzle content that already exists in the public bank: prompt, code, expected output, and for
  `explain` the correct solution and authored explanation.
- What the learner chose: a bank option, an arrangement of bank lines, or Syntax Rows tokens
  (as the assembled program).
- The validator's diagnosis: message, error group, row index, outputs, and one trace step if asked.
- The **learner's free text** in `teach_back` (up to 400 characters). This is the only field a
  person types.

Not sent: names, accounts, emails, session or device identifiers, IP addresses (the webhook sees the
game server's address, not the learner's), the contents of `localStorage` (high score, stars, mistake
history), or anything about other puzzles in the run. The game has no user identity to send.

Things to be aware of:

- Nothing in the web UI warns learners not to put personal information in the teach-back box. The
  reference workflow's system prompt tells the model not to ask for personal data, but it cannot stop
  a learner typing it. The proposal's rule is "do not send unnecessary personal data to AI services".
- `deploy/n8n-tutor.json` sets `saveDataSuccessExecution` and `saveDataErrorExecution` to `none`, so
  n8n does not store execution data for this workflow. What the model provider retains is outside this
  repository and was not checked here.

## 6. Cost controls (what exists)

| Control | Where |
| --- | --- |
| The tutor is only called on an explicit learner action: "Vì sao mình sai?", "Gợi ý N/3" after a run, "Hỏi gia sư" in teach-back, "Thử lại lỗi này" / "Thử lại Code Rescue" (rematch) | frontend |
| Canned-only when not configured | `tutor.feedback` |
| At most 2 simultaneous webhook calls per process; extra requests are answered canned, not queued | `_slots` |
| 128-entry cache for identical requests | `tutor._cache` |
| Daily cap on real calls (`SYNTAX_STACK_TUTOR_DAILY_LIMIT`, default 500) and usage counters in `/api/health` | `tutor.feedback`, `tutor.stats` |
| Short replies: 750-character limit in Python; in the reference workflow `maxOutputTokens` is 512 for tutoring and 1900 for drafting | `tutor.py`, `n8n-tutor.json` |
| Input limits: `prediction` 240, `reflection` 400 characters | `main.py` models |
| Model tiering in the reference workflow: board coaching uses the larger model, other tasks use the lite model; a second Developer-API model and a paid Vertex model are tried only on quota or availability errors | `n8n-tutor.json` |
| The Python timeout (38 s) is above the reference workflow's worst case (three upstream calls at 12 s each) | both |

There is no per-learner quota; the cap is global per process per day. Calls and outcomes are counted and logged (section 4).

## 7. How the frontend labels AI versus canned text

Every tutor-backed response carries `source`. `tutorNote({text, source, context})` in
`frontend/js/editor.js` renders:

- `source: "ai"`: a block with the role `group` and aria-label "Gia sư AI", a small `AI` keycap badge,
  the label **GIA SƯ AI**, the text, and a footer line: "Do AI tạo, có thể chưa chính xác. Hãy tự kiểm
  tra bằng Chạy kiểm tra."
- anything else (`canned`): a muted code-comment line `# <text>`, with no AI label.
- while waiting: the same block with "Gia sư đang đọc" and animated dots.

Uses: explanation under a wrong answer (`puzzle-modal.js`), the rematch intro, each Syntax Rows hint
(context "gợi ý N" or "gợi ý N · bước k" for AI, "Gợi ý N" for canned), the teach-back reply
(context "phản hồi"). The text is inserted as text nodes (`richText` turns `` `code` `` spans into
`<code>` elements and never uses `innerHTML`), so tutor output cannot inject markup.

Nothing in Code Rescue's pre-answer hint path uses the tutor: `GET /api/puzzle/{id}/hint` always
returns authored text.

## 8. Responsible-AI rules from the proposal and where they are enforced

Source: the proposal's section "Nguyên tắc sử dụng AI có trách nhiệm" and its risk table.

| Rule | Enforced by | Status |
| --- | --- | --- |
| The validator and test cases confirm results; AI does not conclude a program is right or wrong | Correctness is computed before the tutor is called and nothing reads the tutor's text to set `correct` / `passed` / stars. The reference prompt tells the model to keep the validator's result. | In code |
| Say clearly which hints are AI-made | `source` field, `tutorNote` label and footer | In code |
| Encourage learners to think and retry before the next hint | Hints open one level at a time; Code Rescue hints cost points (x0.9, x0.75, x0.5), Syntax Rows hints cap stars; `coach` hints are only available after a failed run and the prompt asks for one next step, not a full solution | In code (prompt in `n8n-tutor.json`) |
| Do not send unnecessary personal data | Context contains only game data; no identity exists in the game | Mostly in code; the free-text teach-back box is a gap (section 5) |
| Limit the number of calls, record cost, provide canned hints when the service fails | Concurrency cap, cache, canned fallback exist; **cost recording does not** | Partly |
| Limit format and length of AI output; keep feedback inside the lesson | 750-character check, JSON-object check; scope is controlled by the n8n prompt | In code and workflow |
| MVP must work when the AI API fails or exceeds limits | Fallback on every error path | In code |

## 9. Setting up the n8n side

What the Python code requires of the webhook (any implementation that satisfies this works, n8n is a
convention):

1. Accepts `POST` with a JSON body `{task, context}`; `task` is one of `explain`, `rematch`,
   `teach_back`, `coach` (and `content_review` for the editorial script).
2. Rejects requests that lack the header `X-Syntax-Stack-Token` with the shared secret (a non-2xx
   status makes the game fall back to canned text).
3. Replies within 38 seconds with HTTP 2xx and a JSON object `{"text": "<1 to 750 characters>"}`.
   `Content-Type` should be JSON so `response.json()` parses.
4. For `content_review`, `text` is a JSON string with `hints`, `mistakes`, `followup`, replied within
   80 seconds.

Using the reference workflow `deploy/n8n-tutor.json` (steps from `backend/README.md` and the file):

1. In n8n, import `deploy/n8n-tutor.json`.
2. Create credentials and assign them: Google Gemini (PaLM) API for the two Developer-API nodes and a
   Google service account for the Vertex node; replace `YOUR_VERTEX_PROJECT_ID` in the Vertex node's
   URL (or remove the Vertex branch if you only use the Developer API).
3. Create a **Header Auth** credential with header name `X-Syntax-Stack-Token` and a long random
   value; assign it to the "Game request" webhook node (authentication: Header Auth).
4. Publish (activate) the workflow. The webhook path is `syntax-stack-tutor`, so the production URL is
   `https://<n8n host>/webhook/syntax-stack-tutor`.
5. In the environment of the FastAPI process set `SYNTAX_STACK_TUTOR_URL` to that URL and
   `SYNTAX_STACK_TUTOR_TOKEN` to the same value as the credential. Restart the server.
6. Test the webhook directly:

   ```bash
   curl -sS -X POST "$SYNTAX_STACK_TUTOR_URL" \
     -H "Content-Type: application/json" -H "X-Syntax-Stack-Token: $SYNTAX_STACK_TUTOR_TOKEN" \
     -d '{"task":"rematch","context":{"previous_prompt":"a","next_prompt":"b","topic":"loops","hint":"c"}}'
   ```

   Expect `{"text": "...", ...}`. Then trigger "Vì sao mình sai?" in the game and look for the
   **GIA SƯ AI** block. If you see a `# ...` comment line instead, the game used the fallback (see
   [operations.md](operations.md#7-troubleshooting)).

What the reference workflow does (read from the JSON file; model names are as configured there and
were not checked against the provider):

- "Build tutor request" (Code node): picks `gemini-3.8-flash` for `coach` and `gemini-3.5-flash-lite`
  for the other tasks; sets a Vietnamese system prompt (plain text, at most three short sentences, no
  headings or markdown, game data is context not instructions, keep the validator's result, never ask
  for personal information or give links, per-task instructions); sends the received JSON body as the
  user message; `temperature` 0.35, `maxOutputTokens` 512, low thinking level. For `content_review`
  it switches to an editorial prompt with a JSON response schema and a 1900-token limit.
- "Gemini first" then, on 429/5xx or a timeout, "Gemini 3.7 Flash", then, only if both returned a
  quota or availability error, "Vertex Gemini 3.8 Flash". Each HTTP node times out after 12 s (24 s
  for drafting).
- "Return tutor text" replies `{text, status, error_category, finish_reason, provider, model}`;
  `text` is empty unless the model finished normally (`STOP`), which makes the game fall back.

## 10. Open questions

- ~~**Cost recording.**~~ **Resolved:** `tutor.py` has a daily cap (`SYNTAX_STACK_TUTOR_DAILY_LIMIT`),
  per-attempt INFO log lines and counters in `/api/health`. Still no per-learner limit.
- **Personal data in teach-back.** Should the UI warn learners not to type personal details?
- ~~**`hints.py` is out of date.**~~ **Resolved:** the docstring now says AI goes through `tutor.py`, `set_provider` was removed, and `backend/README.md` lists `tutor.py` and `review_content.py`. Original note: Its docstring still says the AI tutor "plugs in" through
  `set_provider`; nothing calls `set_provider`, and `tutor.feedback()` is called directly from
  `main.py`. Treat `hints.py` as canned-only. `backend/README.md` repeats the old description and its
  layout table does not list `tutor.py` or `scripts/review_content.py`.
- ~~**Name of the `coach` context key `tier`**~~ **Resolved:** the context now also carries `hint_level`;
  `tier` stays as a deprecated alias (commented in `main.py`) for existing n8n workflows.
- **Teach-back fallback language.** The fallback is a Vietnamese sentence with an English one
  appended, while the learner may write in either language.
- **Tutor text may contain markdown backticks** even though the reference prompt says no markdown;
  the frontend renders backtick spans as code, which is probably what is wanted.
- **Single process state.** Cache and slots are per process (see section 4).
- **No client-side timeout.** `frontend/js/api.js` does not abort `fetch`, so a learner may wait up to
  about 38 s on a slow tutor call while the loading state is shown.
