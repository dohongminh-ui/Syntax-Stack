# Operations

How to set up, run, test, regenerate content for and deploy Syntax Stack, and what to check when
something goes wrong. Related: [architecture.md](architecture.md), [puzzle-bank.md](puzzle-bank.md),
[ai-tutor.md](ai-tutor.md), `backend/README.md`.

## 1. Requirements

- **Python 3.12 or newer.** The validator reads `ast.FunctionDef.type_params`, which exists from
  Python 3.12. The Dockerfile uses `python:3.12-slim`; the virtual environment used for these docs
  runs Python 3.14.7. Older versions are not supported (inferred from the code, not tested).
- Packages (`backend/requirements.txt`, unpinned minimums): `fastapi>=0.115`, `uvicorn>=0.30`,
  `PyYAML>=6.0`, `pytest>=8.0`, `httpx>=0.27`. `httpx` is needed at run time by the tutor client;
  `pytest` is only for tests but lives in the same file.
- A browser. No Node.js, no build step.
- Internet access for the fonts (see section 8). The tutor additionally needs an n8n webhook.

## 2. Setup

Run these from the repository root.

### Windows (PowerShell)

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Call `.venv\Scripts\python` directly; there is no need to activate the environment (which avoids the
PowerShell execution-policy prompt).

### macOS / Linux

```bash
cd backend
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

(In Git Bash on Windows the interpreter is `.venv/Scripts/python`.)

## 3. Running

From `backend/`:

```bash
# Windows:        .venv\Scripts\python -m uvicorn app.main:app --port 8000
# macOS / Linux:  .venv/bin/python -m uvicorn app.main:app --port 8000
```

Or from the repository root (this is what `.claude/launch.json` does):

```bash
backend/.venv/Scripts/python -m uvicorn app.main:app --port 8000 --app-dir backend
```

Then open `http://localhost:8000/`. Also available: `http://localhost:8000/docs` (FastAPI's
interactive API page) and `GET /api/health`, which returns `{"ok": true, "puzzles": 559}` with the
committed bank (`puzzles: 0` means the database file is missing).

The frontend is served from `../frontend` (mounted last so it never shadows `/api`) only if that
folder exists. All frontend requests use relative URLs, so any port works.

Do not use `--reload` in production: Syntax Rows levels are cached after first use, so edits to
`content/levels/*.yaml` need a restart anyway.

### Environment variables

| Variable | Used by | Default | Meaning |
| --- | --- | --- | --- |
| `SYNTAX_STACK_DB` | `app/bank.py` (read at import) | `backend/data/puzzles.sqlite` | Path of the puzzle database. |
| `SYNTAX_STACK_LEVELS` | `app/rows.py` (read at import) | `backend/content/levels` | Folder with Syntax Rows level YAML files. |
| `SYNTAX_STACK_TUTOR_URL` | `app/tutor.py` (read on every call) | unset | n8n webhook URL. With the token unset the tutor is off. |
| `SYNTAX_STACK_TUTOR_TOKEN` | `app/tutor.py` (read on every call) | unset | Shared secret, sent as header `X-Syntax-Stack-Token`. |
| `SYNTAX_STACK_TUTOR_DAILY_LIMIT` | `app/tutor.py` (read on every call) | `500` | Maximum real tutor calls per local day, counted in process. `0` turns the tutor off (always canned). An unparsable value falls back to 500. |
| `SYNTAX_STACK_BIND` | `compose.yaml` only | `127.0.0.1` | Address uvicorn binds to inside the compose service. Use the host's LAN address to allow LAN access. |
| `PYTHONDONTWRITEBYTECODE` | `Dockerfile` | `1` | Avoids `.pyc` files in the image. |

Everything else (port, host, workers) is a uvicorn command-line option. Nothing reads a `.env` file;
set variables in the shell or the service definition.

The tutor needs **both** `SYNTAX_STACK_TUTOR_URL` and `SYNTAX_STACK_TUTOR_TOKEN`. Details and the
fallback rules: [ai-tutor.md](ai-tutor.md#4-environment-variables-and-runtime-limits).

## 4. Regenerating the puzzle bank

The bank is generated offline from `backend/content/templates/*.yaml` and
`backend/content/mistakes.yaml`. `data/puzzles.sqlite` is committed output, so you only regenerate it
after changing those files.

```bash
cd backend
.venv/bin/python scripts/generate_bank.py             # Windows: .venv\Scripts\python scripts\generate_bank.py
.venv/bin/python scripts/generate_bank.py --verbose   # also shows why variants were dropped
.venv/bin/python scripts/generate_bank.py --out /tmp/test.sqlite --seed 7   # experiments, leaves the real file alone
```

Output (abridged, committed content):

```
Seed 20260516 -> ...\backend\data\puzzles.sqlite

Per template (primary variants / debug-only find_bug forms):
  conditions_branch_predict    predict_output   38 /  0
  conditions_cmp_fill          fill_blank       40 / 40
  ...
Per topic x tier:
  topic         tier 1  tier 2  tier 3  total
  variables         46      50      46    142
  ...
Total: 559 puzzles + 147 debug-only find_bug forms
Coverage OK.
```

- **Exit status**: 0 when coverage is met; 1 if any template has fewer than 20 variants, any topic x
  tier cell has fewer than 20, the template set is not 16 (one per topic x type) or ids collide.
  The file is written *before* these checks, so a failing run still replaces the database.
- **Deterministic?** Yes for the same seed, templates and Python. For these docs the default seed was
  regenerated into a temporary file and all 706 rows were identical to the committed database
  (Python 3.14.7). Other Python versions were not tested.
- Nothing is generated while the game runs. The server opens the database read-only on every request,
  so a regenerated file is picked up without a restart, though restarting is the safe habit.
- After regenerating: run the tests (section 5), commit `puzzles.sqlite` with the YAML change. The
  Docker image copies the committed file; it does not generate one.

Editorial helper (optional, needs the tutor webhook):

```bash
# inside the container
docker compose exec -T game python backend/scripts/review_content.py loops_range_fill > loops-review.json
# or locally, with SYNTAX_STACK_TUTOR_URL and SYNTAX_STACK_TUTOR_TOKEN set
.venv/bin/python scripts/review_content.py loops_range_fill --tier 1
```

It prints a JSON "review packet" (`status: needs_editor_review`) with a drafted follow-up, three
hints and three mistakes, each checked with the validator. A human decides what, if anything, to copy
into a template. A sample is in `backend/data/review/loops-range-fill.json`.

## 5. Tests

```bash
cd backend
.venv/bin/python -m pytest -q          # Windows: .venv\Scripts\python -m pytest -q
```

Observed for these docs: **149 passed, 1 warning in about 14 s** (Python 3.14.7). The warning is a
Starlette deprecation notice about `TestClient` and `httpx`; it does not affect results.

Configuration: `backend/pytest.ini` (`testpaths = tests`, ignores `DeprecationWarning`).
`tests/conftest.py` puts `backend/` on `sys.path`, **generates the bank automatically if the database
file is missing**, and provides three fixtures: `client` (a FastAPI `TestClient`), `all_rows` (every
stored puzzle with decoded JSON) and the session-wide bank check.

| File | Tests | What it covers |
| --- | --- | --- |
| `tests/test_validator.py` | 36 | AST whitelist (25 rejection cases), step / output limits, recursion, Unicode output, builtins, no state leaking between runs, error classification, diagnosis messages, syntax-error line numbers |
| `tests/test_rows.py` | 43 | Level listing and no answer leaks, level content shape, canonical solutions pass, distractor swaps fail with the expected group and row, trace content, alternative correct programs, empty / missing colon / bad indent / syntax / wrong order / missing construct, ten 422 payload cases, hints and group fallbacks, hint validation |
| `tests/test_rescue_api.py` | 26 | Health, all four puzzle types reachable and no leaks, option counts per level, exclusions and 404, request validation, answers (correct, wrong, reveal on and off), `find_bug` line-tied options and `wrong_line` / `wrong_fix`, parsons groups, 404 and 422 on answers, hints, debug selection and errors, last commit tier, CORS |
| `tests/test_learning_features.py` | 13 | Practice boards for all 5 levels, prediction semantics, twist for all 5 levels and its 422s, teach-back (verified output in the context, 422 on empty reflection or failed board), editorial review rejecting wrong packets |
| `tests/test_tutor.py` | 7 | Coaching context built from the re-run board, selected trace step, 422 for an invalid step, fallback on webhook timeout, canned explain plus verified rematch for each of the four puzzle types |
| `tests/test_tutor_cost.py` | 15 | Bad tutor URL and other request errors fall back to canned, daily cap, limit 0, cache hits not counted against the cap, counters, 128-entry cache bound, log line has no context or reply text, `/api/health` tutor block, coach context `hint_level` plus deprecated `tier` |
| `tests/test_hardening.py` | 2 | Eight concurrent validator runs give correct results and restore the recursion limit; a level without `indent_cols` defaults to 2 |
| `tests/test_generator_safety.py` | 2 | A failed coverage check leaves the existing bank byte-identical and removes the temp file; a successful run replaces it |
| `tests/test_bank_integrity.py` | 5 | Bank shape and coverage, every puzzle self-consistent, **every solution passes and every distractor fails through the validator**, `find_bug` options span two lines, public views never leak |

Total 5 + 13 + 26 + 43 + 7 + 15 + 2 + 2 + 36 = 149. The tests do not cover the frontend, the HTTP call of the tutor
client (`request_tutor` is monkeypatched) or the tutor semaphore.

## 6. Deploying

Syntax Stack is one FastAPI process that serves both the API and the static frontend, so there is one
thing to deploy and no separate web server is required.

### What has to be on the server

- `backend/app/*.py`, `backend/requirements.txt`
- `backend/data/puzzles.sqlite` (read-only at run time)
- `backend/content/levels/*.yaml` (needed at run time)
- `backend/content/templates/*.yaml` and `backend/scripts/*.py` (only for regenerating or review; the
  image includes them)
- `frontend/index.html`, `frontend/css/*.css`, `frontend/js/*.js`

`.dockerignore` whitelists exactly these paths, so `.venv`, tests, screenshots (`frontend/_screens`)
and documents stay out of the image.

### With Docker (as configured in the repository)

`Dockerfile`: `python:3.12-slim`, installs `backend/requirements.txt`, copies the files above, runs as
user `10001`. It has **no `CMD`**; the command comes from `compose.yaml`.

`compose.yaml`: one service `game`, `network_mode: host` (so it can reach n8n on the loopback address),
`restart: unless-stopped`, environment `SYNTAX_STACK_TUTOR_URL` (default
`http://127.0.0.1:5678/webhook/syntax-stack-tutor`) and `SYNTAX_STACK_TUTOR_TOKEN` (from the host
environment, empty by default), command:

```
python -m uvicorn app.main:app --app-dir backend --host ${SYNTAX_STACK_BIND:-127.0.0.1} --port 8000
```

```bash
export SYNTAX_STACK_TUTOR_TOKEN='<shared secret>'     # omit to run without the tutor
export SYNTAX_STACK_BIND=192.168.1.20                  # optional: allow LAN access
docker compose up -d --build
```

Notes: `network_mode: host` works as intended on a Linux host; on Docker Desktop (Windows, macOS) host
networking may not behave the same way (not tested), so use the plain Python route there or change the
networking. With the tutor token empty the game runs and simply uses canned text.

### Without Docker

```bash
cd backend && .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Put a reverse proxy in front for HTTPS (the app does not terminate TLS). Because the frontend uses
relative URLs and is served by the same app, no CORS setup is needed.

### Things to know before going live

- **Google Fonts dependency.** `frontend/index.html` loads Be Vietnam Pro, Bricolage Grotesque and
  JetBrains Mono from `fonts.googleapis.com` / `fonts.gstatic.com` (`subset=vietnamese`). If those
  hosts are unreachable (offline lab, blocked network) the CSS falls back to system fonts defined in
  `--f-display`, `--f-ui`, `--f-mono`; Vietnamese text still renders, the look changes. To remove the
  dependency, self-host the font files and replace the `<link>` with `@font-face` rules (not done).
- **Statelessness.** There is no session or database for players, so any number of workers or
  instances can serve any request. Each worker has its own tutor cache and its own 2 tutor slots, and
  its own cached level files.
- **No authentication and no rate limiting** on the API. Run behind the school or LAN network, or add a
  proxy-level limit, if it will be public.
- **The validator runs player-assembled programs in the web process.** Read
  [validator-and-safety.md](validator-and-safety.md#5-threat-model) before changing what can reach it.
- **Secrets.** Keep `SYNTAX_STACK_TUTOR_TOKEN` out of git; the default in `compose.yaml` is the empty
  string.
- **Health check.** `GET /api/health`; treat `puzzles: 0` as a deployment error (database missing).
- **Static files** are served by Starlette with its default caching headers; there is no cache busting
  or minification.

## 7. Troubleshooting

| Symptom | Likely cause | What to do |
| --- | --- | --- |
| `Address already in use` / `[Errno 10048]` when starting uvicorn | Another process uses the port | Pick another port (`--port 8003`); the frontend works on any port. Find the owner with `netstat -ano \| findstr :8000` (Windows) or `lsof -i :8000` (macOS / Linux). |
| The page loads but puzzles never appear; a dialog "Không tải được câu đố" with "Thử lại" | API unreachable or returning an error | Open `/api/health`. Check the server console. The dialog repeats until the request succeeds. |
| `GET /api/health` shows `"puzzles": 0`, and `POST /api/puzzle/next` returns 404 "Chưa có ngân hàng câu đố (puzzles.sqlite). Chạy scripts/generate_bank.py trước." | The database file is missing or `SYNTAX_STACK_DB` points to the wrong path | Run `scripts/generate_bank.py`, or fix the variable. `pytest` creates the file by itself if it is missing. |
| A level edit has no effect | Levels are cached at first use | Restart the server. |
| `ModuleNotFoundError: app` when running tests or uvicorn | Wrong working directory | Run from `backend/`, or add `--app-dir backend` from the repository root. |
| `UnicodeEncodeError` printing Vietnamese in a Windows console | Console code page is not UTF-8 | Set `PYTHONUTF8=1` (PowerShell: `$env:PYTHONUTF8='1'`) or run `chcp 65001`. Relevant to scripts that print Vietnamese, such as `review_content.py`. |
| The tutor never shows ("GIA SƯ AI" block missing, `# ...` comment instead) | The game is using the canned fallback | Work through the checklist below. |
| Browser console shows CORS errors | The page is not served by the FastAPI app | See the CORS section below. |
| `docker compose up` starts but the tutor cannot be reached | `network_mode: host` may not behave like Linux (Docker Desktop), or n8n is not on `127.0.0.1:5678` | Change `SYNTAX_STACK_TUTOR_URL`, or run without Docker. |

### Tutor unavailable, game uses canned text

The game cannot tell a user that the tutor failed; it returns `source: "canned"`. Check in this
order:

1. Are **both** `SYNTAX_STACK_TUTOR_URL` and `SYNTAX_STACK_TUTOR_TOKEN` set in the environment of the
   *running* process? They are read per call, but a process only sees variables that existed when it
   started, so restart after changing them.
2. Does the URL answer from the game server? Use the `curl` command in
   [ai-tutor.md](ai-tutor.md#9-setting-up-the-n8n-side). It must return JSON with a non-empty `text`
   of at most 750 characters, within 38 seconds, with HTTP 2xx.
3. Is the n8n workflow **published** and is the URL the *production* one
   (`/webhook/...`, not `/webhook-test/...`)?
4. Does the header value in n8n match `SYNTAX_STACK_TUTOR_TOKEN` exactly? A mismatch is a non-2xx
   status, which falls back.
5. Look at the server's stderr for `Tutor unavailable (<ExceptionName>)` (for example `ReadTimeout`,
   `ConnectError`, `HTTPStatusError`, `ValueError`). The repo has no logging configuration, so Python's
   default handler prints just that line.
6. Busy? Only 2 tutor calls run at once per process; extra concurrent requests get canned text
   immediately by design.
7. The same request twice returns the same text: identical requests are cached (128 entries per
   process).

### CORS

The frontend is meant to be opened through the FastAPI server (`http://localhost:8000/`). All its URLs
are relative, so there is no cross-origin request and CORS never applies. The middleware allows only
origins matching `^http://(localhost|127\.0\.0\.1)(:\d+)?$` (any port), all methods and headers, no
credentials; other origins, including a LAN IP address, get no CORS header (`test_cors_headers`).

If you serve `frontend/` from a different server (for example `python -m http.server 5173 -d
frontend`) and open it **without** `?mock=1`, its `/api/...` requests go to that static server, not to
FastAPI, and fail. Use `?mock=1` for UI work, or open the app on the FastAPI port. A genuinely
separate frontend origin would need absolute API URLs in `frontend/js/api.js`, which is not
supported today.

## 8. Maintenance checklist

- Changed a template or `mistakes.yaml`: regenerate, read the report, run tests, commit the database.
- Changed a level: update tests if the id list changed, restart the server.
- Changed validator limits or the whitelist: run `test_validator.py` and `test_bank_integrity.py`
  (the bank is re-verified with the new rules; the generator should be re-run too).
- Changed an API field: update `docs/api-contract.md`, `frontend/js/api.js`, the mocks and the tests.
- Before a demo: start the server, open `/api/health`, play one puzzle and one level, and test the
  tutor path once if it is configured.

## 9. Open questions

- `requirements.txt` has no upper bounds or lock file; a future FastAPI or Starlette release could
  change behaviour (the Starlette `TestClient` warning is an early sign).
- ~~Python 3.12 is the minimum by inspection of the code, but `backend/README.md` does not say so.~~
  **Resolved:** `app/main.py` raises a `RuntimeError` below 3.12 at import, and `requirements.txt` and
  `backend/README.md` state the requirement.
- The Docker image installs `pytest` and `httpx` together with the runtime packages and has no
  health check or `CMD`.
- There is no automated check that the committed `puzzles.sqlite` equals a fresh generation; the
  equality was verified by hand for these docs.
