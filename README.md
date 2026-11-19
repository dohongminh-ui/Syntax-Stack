# Syntax Stack

Syntax Stack is a browser game that teaches beginner Python, built by team Le Rouge at BTEC FPT for
the BTEC Best Coder 2026 competition. Live: **https://syntax.screepai.moe**.

- **Code Rescue**: an 8x8 block puzzle. Every full row or column locks until the player solves a short
  code puzzle (fill the blank, predict the output, reorder lines, find the bug). One wrong answer leaves
  a bug line; the second ends the run with a study plan.
- **Syntax Rows**: each row of the board is a line of Python built from code tiles; rows only clear
  when the program runs correctly. Students can predict the output first and explain their code back.
- **Misaki**: one AI character with two jobs. As the **AI tutor** she explains a student's actual
  attempt using a language model (an optional n8n webhook), and the game falls back to authored text
  whenever the tutor is off or fails. As the **AI opponent** in 1v1 she plans her moves with a search
  algorithm (four levels, plus a training mode where she coaches you).
- **Play together**: real-time 1v1 duels (against a friend or Misaki), a ranked leaderboard and friend
  races whose scores the server verifies by replaying the moves, and a **live classroom** where a
  teacher sees the class's weak topics and most common mistakes.
- **More**: puzzles generated from pasted code (run in a sandbox), a skill map, generated friendly
  nicknames, and a **VI | EN** language switch (Vietnamese by default; `?lang=en` also works).

A restricted Python validator, not an AI, decides what is correct. One FastAPI process serves the JSON
API, the 1v1 WebSocket and the plain HTML/CSS/JS frontend.

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
`GET /api/health` returns `{"ok": true, "puzzles": 706, "tutor": {...}}`: 706 generated forms, 559 of
them playable in Code Rescue (the rest are debug-only variants).

**Run the tests** (from `backend/`):

```bash
.venv/bin/python -m pytest -q        # Windows: .venv\Scripts\python -m pytest -q
```

Expected: about 540 passed (538 on 19 Nov 2026). The golden tests replay games in the real
`game.js` (needs Node.js) and require the Python engine to reach the same result.

The tutor is optional. To enable it, set `SYNTAX_STACK_TUTOR_URL` and `SYNTAX_STACK_TUTOR_TOKEN` in the
server's environment ([docs/ai-tutor.md](docs/ai-tutor.md)). Without them everything works with
authored hints and explanations.

Run uvicorn with **one worker**: 1v1 matches live in the server process.

UI work without the backend: `python -m http.server 5173 -d frontend`, then open
`http://localhost:5173/?mock=1` ([docs/frontend.md](docs/frontend.md#14-mock-mode-and-demo-hooks)).

## Deploying

The live site (https://syntax.screepai.moe) deploys from GitHub: **push to `main`** and the server picks
it up within 5 minutes, rebuilds, checks `/api/health` and rolls back on its own if the new build does
not answer. Details and manual commands: [docs/operations.md](docs/operations.md#production-server-updates-pull-from-github).

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
│   ├── n8n-tutor.json                 importable n8n workflow for the tutor webhook
│   ├── update.sh                      server: pull main from GitHub and redeploy (cron, every 5 min)
│   └── server-setup.sh                one-time server setup: git checkout + cron job
├── docs/                              documentation (index: docs/README.md)
│   ├── presentation-script.md         finals speaking script (10 minutes, 3 speakers)
│   ├── presentation-content.md        finals slide-by-slide content
│   └── Syntax-Stack-finals.pptx       finals deck, with the script in the speaker notes
├── backend/
│   ├── app/
│   │   ├── main.py                    FastAPI routes, request models, CORS, static mount
│   │   ├── i18n.py                    X-Lang middleware and vi/en text helpers
│   │   ├── validator.py               AST whitelist + restricted runner + error classification
│   │   ├── bank.py                    Code Rescue: select puzzles, build public view, check answers
│   │   ├── rows.py                    Syntax Rows: levels, board assembly, run, trace, twist, practice
│   │   ├── hints.py                   authored (canned) hints
│   │   ├── rescue_engine.py           Python port of game.js for server-side replay
│   │   ├── ranked.py                  ranked runs, races and leaderboards (verified by replay)
│   │   ├── pvp.py                     real-time 1v1 matches over WebSocket
│   │   ├── pvp_bot.py, pvp_coach.py   Misaki as opponent (search) and as training coach
│   │   ├── rooms.py                   live classroom rooms and the teacher dashboard data
│   │   ├── nicknames.py               generated friendly nicknames (vi and en)
│   │   ├── custom.py, custom_gen.py   paste-your-own-code puzzle sets (store, API logic, generator)
│   │   ├── sandbox.py, sandbox_worker.py  child-process runner for pasted code
│   │   ├── puzzle_tools.py            helpers shared by generate_bank.py and custom_gen.py
│   │   └── tutor.py                   optional n8n tutor client (cache per language, fallback)
│   ├── content/
│   │   ├── templates/*.yaml           16 Code Rescue templates (4 topics x 4 types), vi + *_en text
│   │   ├── levels/r1..r5.yaml         5 Syntax Rows levels
│   │   ├── mistakes.yaml, mistake_labels.yaml  named common mistakes and their short labels
│   │   ├── misaki_coach.yaml          Misaki's authored coaching lines
│   │   └── nickname_words.yaml, name_blocklist.yaml  nickname words, free-name filter
│   ├── data/
│   │   ├── puzzles.sqlite             generated puzzle bank (committed output)
│   │   └── review/                    sample editorial review packet
│   ├── scripts/
│   │   ├── generate_bank.py           offline bank generator and verifier
│   │   └── review_content.py          editorial draft checker (needs the tutor webhook)
│   ├── tests/                         pytest suite; js_harness/ plays the real game.js in Node
│   └── requirements.txt, pytest.ini, README.md
└── frontend/
    ├── index.html                     all screens; loads js/main.js
    ├── css/                           base, game, rows, modal, features, ranked, rooms, pvp
    ├── tools/i18n-coverage.mjs        checks every Vietnamese UI string has an English translation
    └── js/                            ES modules, no build step
        ├── main.js                    boot, screens, Code Rescue controller, demo shortcuts
        ├── i18n.js, i18n-core.js, i18n-en.js  language switch and the English dictionary
        ├── game.js, pieces.js, rng.js Code Rescue rules, block shapes, seeded RNG (no DOM)
        ├── board.js                   Code Rescue board, tray, drag, animations
        ├── puzzle-modal.js            puzzle panel (4 puzzle types, hints, commit, result)
        ├── rows-game.js, rows-board.js, rows-screen.js  Syntax Rows rules, board, screens
        ├── pvp.js, pvp-screen.js, pvp-match.js, misaki.js  1v1 lobby, match UI, Misaki
        ├── ranked.js, race.js, leaderboard.js, runlog.js, rank-ui.js  ranked play and races
        ├── rooms.js                   live classroom (teacher and student)
        ├── custom.js, skills.js       puzzles from pasted code, skill map
        ├── identity.js                nicknames and device id
        ├── editor.js, highlight.js    editor-window components, Python highlighter
        ├── keycap.js, icons.js, ui.js, sound.js  shared UI, motion helper, sound and haptics
        ├── strip.js, start.js, title.js  header strip, start screen and backdrop, page titles
        ├── api.js, storage.js         fetch/WebSocket client (sends X-Lang), localStorage
        └── mock-*.js                  fake API for ?mock=1
```

## Documentation

| Document | Purpose |
| --- | --- |
| [docs/README.md](docs/README.md) | Index of all documents and a glossary |
| [docs/architecture.md](docs/architecture.md) | Components, state ownership, diagrams, trust boundaries |
| [docs/validator-and-safety.md](docs/validator-and-safety.md) | The restricted runner and the threat model |
| [docs/puzzle-bank.md](docs/puzzle-bank.md) | Templates, generator pipeline, selection, adding content |
| [docs/pvp.md](docs/pvp.md) | Real-time 1v1 rules and protocol, Misaki as opponent and coach |
| [docs/ranked-and-race.md](docs/ranked-and-race.md) | Ranked runs, races, leaderboards, server replay |
| [docs/syntax-rows.md](docs/syntax-rows.md) | Syntax Rows levels, assembly, trace, twist, stars, adding a level |
| [docs/ai-tutor.md](docs/ai-tutor.md) | The optional AI tutor, privacy, cost, n8n setup |
| [docs/frontend.md](docs/frontend.md) | Frontend modules, state machines, drag, design system, motion, accessibility |
| [docs/operations.md](docs/operations.md) | Setup, environment variables, tests, deployment, troubleshooting |
| [docs/api-contract.md](docs/api-contract.md) | HTTP API contract |
| [docs/design-brief.md](docs/design-brief.md) | Visual design brief |
| [docs/presentation-script.md](docs/presentation-script.md), [docs/presentation-content.md](docs/presentation-content.md) | Finals talk and slides |
| [backend/README.md](backend/README.md) | Backend quick reference |
| [Code_Rescue_Gameplay_Spec.md](Code_Rescue_Gameplay_Spec.md), [Syntax_Rows_Gameplay_Spec.md](Syntax_Rows_Gameplay_Spec.md) | Game rules (Vietnamese) |
