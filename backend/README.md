# Syntax Stack backend

FastAPI service for the two game modes (Code Rescue and Syntax Rows). API contract:
`../docs/api-contract.md`. All player-facing strings are Vietnamese.

## Install

Requires **Python 3.12 or newer** (the validator reads `type_params` from the AST; `app/main.py` raises
a `RuntimeError` at startup on older versions).

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

(Git Bash / macOS / Linux: use `.venv/Scripts/python` or `.venv/bin/python`.)

## Generate the Code Rescue puzzle bank (offline)

```powershell
.venv\Scripts\python scripts\generate_bank.py            # writes data\puzzles.sqlite, prints coverage
.venv\Scripts\python scripts\generate_bank.py --verbose  # also prints why variants were dropped
```

The bank is built in a temporary file next to `data/puzzles.sqlite` and only moved over it when the
coverage check passes; on failure the existing bank is left untouched.

Deterministic (fixed seed). Exits non-zero unless every one of the 16 templates has at least 20
variants and every topic x tier cell has at least 20. Nothing is generated at play time.
`data/puzzles.sqlite` is committed output; regenerate it after editing `content/templates/*.yaml`
or `content/mistakes.yaml`.

## Test

```powershell
.venv\Scripts\python -m pytest -q
```

The suite re-verifies every stored puzzle with the validator (solution passes, every distractor
fails) and covers both APIs.

## Run

```powershell
.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

* API under `/api` (`/api/health`, `/api/puzzle/...`, `/api/rows/...`).
* If `../frontend` exists it is served as static files at `/` (mounted after the API routes).
* CORS allows `http://localhost:*` and `http://127.0.0.1:*`.
* `/api/health` also reports tutor counters (`tutor: {configured, calls_today, ai_today, fallback_today, limit}`).
* Environment overrides: `SYNTAX_STACK_DB` (puzzle database path), `SYNTAX_STACK_LEVELS` (levels dir), and the tutor variables below.

## n8n tutor

Import `../deploy/n8n-tutor.json` into n8n. Assign the Gemini API and Vertex service account
credentials, replace `YOUR_VERTEX_PROJECT_ID` in the Vertex node, and assign a Header Auth
credential with the header `X-Syntax-Stack-Token`. Publish the workflow and set
`SYNTAX_STACK_TUTOR_URL` to the production webhook URL and
`SYNTAX_STACK_TUTOR_TOKEN` to the matching header value in the FastAPI environment.
Tutor environment variables (read on every call):

| Variable | Default | Meaning |
| --- | --- | --- |
| `SYNTAX_STACK_TUTOR_URL` | unset | n8n webhook URL. Tutor is off unless URL and token are both set. |
| `SYNTAX_STACK_TUTOR_TOKEN` | unset | Shared secret sent as `X-Syntax-Stack-Token`. |
| `SYNTAX_STACK_TUTOR_DAILY_LIMIT` | `500` | Real tutor calls per local day (in-process, resets at midnight). `0` disables the tutor. Cache hits do not count. |
| `SYNTAX_STACK_TUTOR_CLIENT_LIMIT` | `40` | Real tutor calls per visitor (IP) per day. |
| `SYNTAX_STACK_API_DOCS` | off | `1` serves `/docs`, `/redoc`, `/openapi.json` (keep off in production). |

Each tutor attempt logs one INFO line (task, outcome `ai`/`cached`/`canned:<reason>`, latency in ms)
and never the context or reply text. The coach context carries `hint_level`; `tier` is a deprecated
alias kept for existing n8n workflows.

The workflow tries Gemini 3.8 Flash for board coaching and Flash-Lite for the shorter explanation
and rematch requests. Gemini 3.7 Flash is the second Developer API attempt. Vertex is reached
only if both Gemini requests return a quota or availability error. When the tutor is unavailable,
the game uses the authored feedback and verified puzzle bank.

On a Linux host running n8n on loopback port 5678, `docker compose up -d --build` from the
project root runs the game on port 8000. Set `SYNTAX_STACK_BIND` to the host's LAN address
to allow LAN access. Supply the tutor token through the server's Compose environment.

## Draft content for review

The `content_review` task in the n8n workflow drafts Vietnamese hints, a follow-up exercise,
and three mistakes for a selected YAML template. The script uses a verified bank variant as
reference, executes the draft programs, and writes a JSON packet for editorial review.

```bash
docker compose exec -T game python backend/scripts/review_content.py loops_range_fill > loops-review.json
```

The packet contains the verified output and each mistake's validator diagnosis. Review the
lesson and wording before adapting the draft into a YAML template. Run the existing bank
generator after making a reviewed change to a template.

## Layout

| Path | What |
| --- | --- |
| `app/main.py` | FastAPI routes, CORS, static mount |
| `app/validator.py` | AST whitelist + restricted runner + error classification (shared by both modes) |
| `app/bank.py` | Code Rescue bank access, selection (rescue / debug / last_commit), answer checking |
| `app/hints.py` | Canned (authored) hints, `source: "canned"` |
| `app/custom.py`, `app/custom_gen.py` | Paste-your-own-code puzzle sets: validation, generation, SQLite store (`data/custom.sqlite`) |
| `app/sandbox.py`, `app/sandbox_worker.py` | Child-process runner for pasted code (timeouts, rlimits); see `docs/validator-and-safety.md` 5.1 |
| `app/puzzle_tools.py` | Helpers shared by `scripts/generate_bank.py` and `custom_gen.py` |
| `app/tutor.py` | Optional n8n tutor: AI feedback with cache, daily cap, usage log and canned fallback |
| `app/rows.py` | Syntax Rows level loading, board -> program assembly, run + diagnosis |
| `content/templates/*.yaml` | 16 Code Rescue templates (4 topics x 4 types) |
| `content/mistakes.yaml` | Notes for named common mistakes (shown after a wrong answer) |
| `content/levels/r1..r5.yaml` | Syntax Rows levels |
| `scripts/generate_bank.py` | Offline bank generator and verifier |
| `scripts/review_content.py` | Drafts and checks template content for editorial review (n8n `content_review`) |
| `tests/` | pytest suite |

## Writing a template

A template file has `id` (= file name), `topic`, `type` (`fill_blank | predict_output | parsons |
find_bug`), three `hints`, an `explanation`, and `tiers: {1: [block...], 2: [...], 3: [...]}`.
Each block has `count` (variants to keep), `prompt`, `code`, `params` (cartesian product),
optional `derived` (Python expressions) and `where` (constraints), plus per type:

* `fill_blank`: `code` with exactly one `___`, `answer`, `distractors: [{name, frag}]`
* `predict_output`: `distractors: [{name, out}]` (wrong outputs; the right one is computed by running the code)
* `parsons`: `code` is the correct program (indentation = nesting), `distractors: [{name, code}]` (wrong arrangements)
* `find_bug` (v2): `code` is the buggy program, `bug_line` (1-based), `fix`, `distractors: [{name, rep}]` (wrong edits of the bug line). The generator adds wrong edits of other lines automatically so options span at least 2 lines (`line_id` per option)

`{name}` or `{expression}` inside any string is rendered from the parameters; `{expected_inline}` and
`{answer}` are also available in prompt / hints / explanation. `fill_blank` templates also produce
`debug_only` find_bug forms (used for `kind: "debug"`).

## Safety note

The validator runs code in-process. That is acceptable because it only ever receives programs
assembled from content-bank fragments (puzzle lines, Syntax Rows tokens), and the AST whitelist
(no imports, attributes, lambdas, comprehensions, try/with/class, dunder names, `**`, calls outside a
fixed builtin set) plus step, time and output limits are always applied.
