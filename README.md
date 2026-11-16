# Syntax Stack

Syntax Stack is a browser game that teaches beginner Python, built by a student team at BTEC FPT for
the BTEC Best Coder 2026 competition. It has two modes: **Code Rescue**, an 8x8 block puzzle where
every full row or column is locked until the player solves a short code puzzle (one wrong answer
leaves a bug line, the second ends the run), and **Syntax Rows**, where each row of the board is a
line of Python assembled from code tokens and rows only clear when the program runs correctly. A
restricted Python validator, not an AI, decides what is correct; an optional AI tutor (an n8n
webhook) only explains, and the game falls back to authored text whenever the tutor is off or fails.
One FastAPI process serves the JSON API and the plain HTML/CSS/JS frontend. The UI is in Vietnamese.

## Quick start

Requires Python 3.12 or newer. Commands start in the repository root.

**Windows (PowerShell)**

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python scripts\generate_bank.py        # optional: data\puzzles.sqlite is already committed
.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

**macOS / Linux**

```bash
cd backend
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/generate_bank.py            # optional: data/puzzles.sqlite is already committed
.venv/bin/python -m uvicorn app.main:app --port 8000
```

Open **http://localhost:8000/**. API explorer: http://localhost:8000/docs. Health check:
`GET /api/health` returns `{"ok": true, "puzzles": 559}`.

**Run the tests** (from `backend/`):

```bash
.venv/bin/python -m pytest -q        # Windows: .venv\Scripts\python -m pytest -q
```

Expected: `130 passed`.

The tutor is optional. To enable it, set `SYNTAX_STACK_TUTOR_URL` and `SYNTAX_STACK_TUTOR_TOKEN` in the
server's environment ([docs/ai-tutor.md](docs/ai-tutor.md)). Without them everything works with
authored hints and explanations.

UI work without the backend: `python -m http.server 5173 -d frontend`, then open
`http://localhost:5173/?mock=1` ([docs/frontend.md](docs/frontend.md#14-mock-mode-and-demo-hooks)).

## Repository layout

```
sextax/
├── README.md                          this file
├── Dockerfile, compose.yaml           container build and run (Linux host)
├── .dockerignore                      whitelist of files that go into the image
├── Code_Rescue_Gameplay_Spec.md       Code Rescue rules (Vietnamese)
├── Syntax_Rows_Gameplay_Spec.md       Syntax Rows rules (Vietnamese)
├── Syntax_Stack_BTEC_Best_Coder_2026_Proposal.pdf   project proposal (Vietnamese)
├── SERS.pdf                           presentation template
├── deploy/
│   └── n8n-tutor.json                 importable n8n workflow for the tutor webhook
├── docs/                              documentation (index: docs/README.md)
│   ├── api-contract.md                HTTP API contract
│   └── design-brief.md                visual design brief v2 ("Keycap")
├── backend/
│   ├── app/
│   │   ├── main.py                    FastAPI routes, request models, CORS, static mount
│   │   ├── validator.py               AST whitelist + restricted runner + error classification
│   │   ├── bank.py                    Code Rescue: select puzzles, build public view, check answers
│   │   ├── rows.py                    Syntax Rows: levels, board assembly, run, trace, twist, practice
│   │   ├── hints.py                   authored (canned) hints
│   │   └── tutor.py                   optional n8n tutor client (cache, 2 slots, fallback)
│   ├── content/
│   │   ├── templates/*.yaml           16 Code Rescue templates (4 topics x 4 types)
│   │   ├── mistakes.yaml              named common mistakes -> short Vietnamese notes
│   │   └── levels/r1..r5.yaml         5 Syntax Rows levels
│   ├── data/
│   │   ├── puzzles.sqlite             generated puzzle bank (committed output)
│   │   └── review/                    sample editorial review packet
│   ├── scripts/
│   │   ├── generate_bank.py           offline bank generator and verifier
│   │   └── review_content.py          editorial draft checker (needs the tutor webhook)
│   ├── tests/                         pytest suite (130 tests)
│   ├── requirements.txt, pytest.ini, README.md
└── frontend/
    ├── index.html                     all screens; loads js/main.js
    ├── css/                           base.css, game.css, rows.css, modal.css
    └── js/                            ES modules, no build step
        ├── main.js                    boot, screens, Code Rescue controller, demo hooks
        ├── game.js, pieces.js         Code Rescue rules and block shapes (no DOM)
        ├── board.js                   Code Rescue board, tray, drag, animations
        ├── puzzle-modal.js            puzzle panel (4 puzzle types, hints, commit, result)
        ├── rows-game.js               Syntax Rows rules (no DOM)
        ├── rows-board.js              Syntax Rows board and token tray
        ├── rows-screen.js             Syntax Rows screens, editor panel, trace, teach-back
        ├── editor.js, highlight.js    editor-window components, Python highlighter
        ├── keycap.js, icons.js, ui.js shared UI building blocks and motion helper
        ├── strip.js, start.js         header strip, start screen
        ├── api.js, storage.js         fetch client, localStorage
        └── mock-api.js, mock-rows.js  fake API for ?mock=1
```

## Documentation

| Document | Purpose |
| --- | --- |
| [docs/README.md](docs/README.md) | Index of all documents and a glossary |
| [docs/architecture.md](docs/architecture.md) | Components, state ownership, diagrams, trust boundaries |
| [docs/validator-and-safety.md](docs/validator-and-safety.md) | The restricted runner and the threat model |
| [docs/puzzle-bank.md](docs/puzzle-bank.md) | Templates, generator pipeline, selection, adding content |
| [docs/syntax-rows.md](docs/syntax-rows.md) | Syntax Rows levels, assembly, trace, twist, stars, adding a level |
| [docs/ai-tutor.md](docs/ai-tutor.md) | The optional AI tutor, privacy, cost, n8n setup |
| [docs/frontend.md](docs/frontend.md) | Frontend modules, state machines, drag, design system, motion, accessibility |
| [docs/operations.md](docs/operations.md) | Setup, environment variables, tests, deployment, troubleshooting |
| [docs/api-contract.md](docs/api-contract.md) | HTTP API contract |
| [docs/design-brief.md](docs/design-brief.md) | Visual design brief |
| [backend/README.md](backend/README.md) | Backend quick reference |
| [Code_Rescue_Gameplay_Spec.md](Code_Rescue_Gameplay_Spec.md), [Syntax_Rows_Gameplay_Spec.md](Syntax_Rows_Gameplay_Spec.md) | Game rules (Vietnamese) |
