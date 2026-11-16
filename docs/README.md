# Documentation index

Technical documentation for Syntax Stack, written for the team that maintains it and for judges who
want to read the technical side. Start with [architecture.md](architecture.md).

## Documents

| Document | Purpose |
| --- | --- |
| [architecture.md](architecture.md) | Components, who owns which state, request flows (Mermaid diagrams), trust boundaries, the "validator decides, AI explains" principle, directory map. |
| [validator-and-safety.md](validator-and-safety.md) | The restricted Python runner: AST whitelist, limits, error groups, board-row mapping, threat model and its honest gaps, test coverage. |
| [puzzle-bank.md](puzzle-bank.md) | Code Rescue content: template YAML schema, the 16 templates, the offline generator, SQLite schema, selection rules, how to add content. |
| [syntax-rows.md](syntax-rows.md) | Syntax Rows: level YAML schema, board assembly, diagnosis order, trace, prediction, practice, twist, teach-back, hints, stars and score, how to add a level. |
| [ai-tutor.md](ai-tutor.md) | The optional n8n tutor: tasks and exact requests, limits, fallback, privacy, cost controls, responsible-AI rules, n8n setup. |
| [frontend.md](frontend.md) | Module map, screens, game state machines, rendering, drag system, puzzle panel, design system, motion, accessibility, local storage, mock mode and demo hooks. |
| [operations.md](operations.md) | Setup, running, environment variables, regenerating the bank, tests, deployment, troubleshooting. |
| [api-contract.md](api-contract.md) | The HTTP API contract (endpoints, enums, JSON examples). Not edited by these documents; see "Open questions" in each document for places where code goes beyond it. |
| [design-brief.md](design-brief.md) | Visual design brief v2 ("Keycap"): tokens, keycap component, layout, motion rules. |
| [presentation-content.md](presentation-content.md) | Slide text for the competition presentation (SERS template). |

Outside `docs/`:

| File | Purpose |
| --- | --- |
| [../README.md](../README.md) | Project overview, quick start, repository layout. |
| [../backend/README.md](../backend/README.md) | Backend install, bank generation, tests, running, n8n note, template writing guide. |
| [../Code_Rescue_Gameplay_Spec.md](../Code_Rescue_Gameplay_Spec.md) | Code Rescue rules (Vietnamese). |
| [../Syntax_Rows_Gameplay_Spec.md](../Syntax_Rows_Gameplay_Spec.md) | Syntax Rows rules (Vietnamese). |
| `../Syntax_Stack_BTEC_Best_Coder_2026_Proposal.pdf` | The project proposal (Vietnamese). |

## Suggested reading order

- **New maintainer:** `README.md` (root), [architecture.md](architecture.md), then the document for the
  area you are changing, then [operations.md](operations.md).
- **Judge, technical side:** [architecture.md](architecture.md) (principle and trust boundaries),
  [validator-and-safety.md](validator-and-safety.md), [ai-tutor.md](ai-tutor.md) (sections 5 to 8),
  [puzzle-bank.md](puzzle-bank.md) (verification pipeline).
- **Adding content:** [puzzle-bank.md](puzzle-bank.md) section 7 or [syntax-rows.md](syntax-rows.md) section 11.

## Conventions used in these documents

- Paths are relative to the repository root, for example `backend/app/validator.py`.
- In-game strings are Vietnamese and are quoted as they appear in the product.
- A claim in these documents was checked in the code (or the tests) when they were written. Where the
  code, the contract or the specs disagree, or something looks unfinished, it is listed under an
  "Open questions" heading at the end of the relevant document instead of being guessed.
- Counts are from the repository state at the time of writing: 559 playable puzzles plus 147
  debug-only forms in the bank, 16 templates, 5 Syntax Rows levels, 130 tests.

## Glossary

| Term | Meaning |
| --- | --- |
| **Code Rescue** | Mode 1: 8x8 block puzzle. A full row or column is locked until a code puzzle is solved. |
| **Syntax Rows** | Mode 2: rows of the board are lines of Python and the pieces are code tokens. |
| **Topic** | One of `variables`, `conditions`, `loops`, `functions`. Each has a colour (Matcha, Mustard, Coral, Ice). The puzzle topic is the majority colour in the locked line. |
| **Type** (puzzle type) | `fill_blank`, `predict_output`, `parsons`, `find_bug`. |
| **Parsons** | A puzzle where shuffled lines of code must be put in order and indented. |
| **Tier** | Puzzle difficulty 1 to 3 = number of rows cleared at once (3 means 3 or more). A Boss clear (4+) asks two tier 3 puzzles. Not the same as level. |
| **Level (player level)** | `beginner`, `intermediate`, `advanced`: how many options are shown (3 or 4) and which puzzle types are favoured. |
| **Level (Syntax Rows)** | One authored Syntax Rows challenge, `r1` to `r5`, defined in a YAML file. |
| **Template** | A hand-written YAML puzzle family with parameters. There are 16 (4 topics x 4 types). |
| **Variant** | One concrete puzzle generated from a template by filling in parameters. Stored in SQLite with an id like `loops_range_fill__004`. |
| **Block** | One entry in a template's `tiers` list: a code skeleton with `params`, distractors and a `count`. |
| **Distractor** | A deliberately wrong option. Every distractor is verified to fail. |
| **Ambiguous puzzle** | A variant in which a distractor also gives the right output. The generator drops it. |
| **Debug-only form** | A `find_bug` variant derived from a `fill_blank` puzzle (`debug_only = 1`), used only for the Debug puzzle. |
| **Lock** | State of a full row or column that must be cleared by solving a puzzle. |
| **Bug line** | A locked line after the first wrong answer: grey, stays on the grid, shown as `ERR` keys. |
| **Debug** | The puzzle shown when the player taps a bug line: another variant of the failed template; one answer in Rescue, three in practice. Fixing it gives +150 and returns to BUILD. |
| **Last Commit** | One-time puzzle offered when no piece fits; correct clears the 3 fullest rows. |
| **SYSTEM CRASH** | Losing a Rescue run: the second wrong answer. |
| **BUILD / WARN / CRASH** | The three status LEDs in the header. In Syntax Rows the LEDs read RUN / FAIL / PASS. |
| **Rescue / Luyện tập** | The two Code Rescue play modes. Rescue: one answer per puzzle, two mistakes lose. Practice: three answers per puzzle, no losing. |
| **Streak (Clean Build)** | Consecutive correct answers without a penalised hint; multiplies points. |
| **Keycap** | The UI building block: every block, token and button is drawn as a mechanical keyboard key (skirt, cap, legend). |
| **Legend** | The text or glyph printed on a keycap (`for`, `x=`, `ERR`). |
| **1u / 2u / 3u** | Width of a Syntax Rows token in grid columns, borrowed from keyboard key widths. Field `w` in the level YAML. |
| **Socket** | An empty board cell, drawn as an empty key well. The first two Syntax Rows columns are indent sockets. |
| **Token** | A code fragment in Syntax Rows (`for`, `range(3)`, `:`). Used at most once per board. |
| **Required construct** | A Python syntax element a Syntax Rows level demands (`For`, `If`, `FunctionDef` ...), checked on the AST. |
| **Validator** | `backend/app/validator.py`: the AST whitelist, restricted runner and error classification. The only place Python is executed. |
| **Error group** | The category of a failure: `wrong_order`, `bad_indent`, `syntax`, `missing_colon`, `output_mismatch`, `wrong_line`, `wrong_fix`, `wrong_choice`, `missing_construct`, `empty`. |
| **Reveal** | Request flag on the answer endpoint; `true` on the final attempt so the server returns the solution and explanation of a wrong answer. |
| **Trace** | Per-line record of a Syntax Rows run: row, code, scope, variable values and cumulative output after each line (up to 48 steps). |
| **Prediction** | The learner's guess of the program output, typed before running; compared with the real output without affecting the grade. |
| **Practice board** | A runnable board with one authored mistake (`GET .../practice`) used by the practice screen. |
| **Twist** | After passing a level, change exactly one token to reach the level's alternate target output (`twist_output`). |
| **Teach-back** | After passing, the learner explains the program in their own words and gets one follow-up question from the tutor. |
| **Tutor** | The optional AI layer (`backend/app/tutor.py`) that phrases feedback. It never decides correctness. |
| **canned vs ai** | The `source` field of tutor responses. `canned`: authored text. `ai`: text from the n8n webhook. The UI labels `ai` text "GIA SƯ AI". |
| **Task** | The `task` name sent to the tutor webhook: `explain`, `rematch`, `teach_back`, `coach` (and `content_review` for editors). |
| **Rematch** | A different verified variant of the same template and tier, with a short tutor sentence, offered after a mistake. |
| **Bank** | The SQLite file of generated puzzles, `backend/data/puzzles.sqlite`. |
| **Mock mode** | `?mock=1`: the browser uses built-in fake API data for UI work. |
| **Hint levels** | Three levels: concept, direction, specific. Each costs points (Code Rescue) or caps stars (Syntax Rows). |
