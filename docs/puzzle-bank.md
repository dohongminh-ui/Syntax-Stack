# Puzzle bank (Code Rescue content)

Code Rescue never writes or runs a new puzzle while someone plays. A set of hand-written YAML
templates is expanded **offline** into a few hundred verified puzzles stored in SQLite. At play time
the server only *selects* a stored puzzle and *checks* an answer.

Rules this implements: `Code_Rescue_Gameplay_Spec.md` section 10. Related:
[validator-and-safety.md](validator-and-safety.md), [architecture.md](architecture.md),
[operations.md](operations.md#4-regenerating-the-puzzle-bank).

Files:

| Path | Role |
| --- | --- |
| `backend/content/templates/*.yaml` | 16 templates (source of truth, written by hand) |
| `backend/content/mistakes.yaml` | Short Vietnamese notes for named common mistakes |
| `backend/scripts/generate_bank.py` | Offline generator and verifier |
| `backend/data/puzzles.sqlite` | Generated output, committed to the repo |
| `backend/app/bank.py` | Selection, public view, answer checking at play time |
| `backend/app/puzzle_tools.py` | `mutations`, `build_bug_form`, `place_options`, `output_ok` and line helpers, shared by the generator and by the custom-code puzzles (`app/custom_gen.py`, see [api-contract.md](api-contract.md)) |

Current bank (seed `20260516`): **706 rows = 559 playable puzzles + 147 debug-only `find_bug` forms**.
`GET /api/health` reports 559, because `count_puzzles()` counts only `debug_only = 0`.

## 1. Template YAML schema

A template file is named after its `id` (`loops_range_fill.yaml`). The generator exits if the file
name and `id` differ or if `hints` does not have exactly three entries.

### 1.1 Template level

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | string | Must equal the file name without `.yaml`. Becomes the `template_id` of every variant. |
| `topic` | `variables` / `conditions` / `loops` / `functions` | Topic (colour) the puzzle belongs to. |
| `type` | `fill_blank` / `predict_output` / `parsons` / `find_bug` | Puzzle type. One type per template. |
| `hints` | list of 3 strings | Level 1 concept, level 2 direction, level 3 specific. Rendered with the variant's parameters, so they may contain `{name}` expressions. |
| `explanation` | string | Default explanation shown after a wrong answer (a block can override it). |
| `tiers` | map `1`, `2`, `3` to a list of blocks | Tier = how many rows the player cleared (1, 2, 3+). Each tier needs a list. |

### 1.2 Block level (inside `tiers`)

A block is a family of variants that share one code skeleton. Fields common to all types:

| Field | Required | Meaning |
| --- | --- | --- |
| `count` | yes | Maximum number of variants to keep from this block. The generator stops when it has accepted `count`. |
| `prompt` | yes | The question text shown to the player (Vietnamese). May use `{...}` expressions. |
| `code` | yes | Code skeleton, a YAML block scalar. Indentation must be a multiple of 4 spaces. Meaning depends on the type (below). |
| `params` | no | Map from parameter name to a list of values. The generator takes the cartesian product, shuffles it, and tries combinations in that order. |
| `derived` | no | Map from name to a Python expression computed from the parameters, in order (later ones can use earlier ones). |
| `where` | no | List of expressions; a combination is skipped unless **all** are truthy. |
| `explanation` | no | Overrides the template's `explanation` for this block. |
| `distractors` | yes | Wrong answers; shape depends on the type. |

Type-specific fields:

| Type | `code` is | Extra fields | `distractors` items |
| --- | --- | --- | --- |
| `fill_blank` | the skeleton with exactly **one** `___` | `answer`: the fragment that fills the blank | `{name, frag}`: a wrong fragment |
| `predict_output` | the full program | none (the correct output is computed by running it) | `{name, out}`: a wrong output string |
| `parsons` | the **correct** program (indentation = nesting) | none | `{name, code}`: a complete wrong arrangement of the lines |
| `find_bug` | the **buggy** program | `bug_line`: 1-based line number of the bug; `fix`: the corrected replacement for that line | `{name, rep}`: a wrong replacement for the buggy line |

`name` is a key into `content/mistakes.yaml`. If it has an entry, the note is shown after a wrong
answer that matches this distractor. Names without an entry simply get no note. Today 87 of the 145
distinct names used in templates have an entry; the other 58 show only the template explanation.

### 1.3 `{...}` rendering

Every string field (`prompt`, `code`, `answer`, `fix`, distractor fields, `hints`, `explanation`) is
rendered by `render()`: each `{expression}` is evaluated with Python `eval`, with `__builtins__`
empty and these names available: the parameters and derived values, plus `J` (join with newlines),
`range`, `len`, `sum`, `min`, `max`, `abs`, `str`, `int`, `list`, `sorted`. Examples from real files:
`{n-1}`, `{a*n}`, `{e+2}`. The regular expression is `\{([^{}]+)\}`: braces cannot be nested and a
literal brace cannot appear in a template. (`eval` is acceptable here because templates are trusted,
team-written content; it is not the validator.)

Extra names available in `prompt`, `hints` and `explanation` only (they need the computed output):
`expected` (output string), `expected_inline` (output with newlines replaced by `, `) and `answer`
(the fill fragment, or the `fix` for find_bug; empty for the other types).

If a derived or `where` expression raises `IndexError`, `KeyError` or `ZeroDivisionError`, that
combination is skipped. Other exceptions stop the generator.

### 1.4 Example (real file, abridged)

`backend/content/templates/loops_range_fill.yaml`:

```yaml
id: loops_range_fill
topic: loops
type: fill_blank
hints:
  - "range() dừng trước giá trị kết thúc."
  - "Đếm xem cần bao nhiêu số được in ra, và số đầu tiên là số nào."
  - "Giá trị kết thúc lớn hơn số cuối cùng cần in đúng một đơn vị."
explanation: "range(bắt_đầu, kết_thúc) chạy từ bắt_đầu đến kết_thúc - 1 ... Muốn in {expected_inline} thì giá trị kết thúc phải là {answer}."
tiers:
  1:
    - count: 10
      prompt: "Điền giá trị còn thiếu để chương trình in ra {expected_inline}."
      code: |
        for {v} in range(___):
            print({v})
      params:
        v: [i, j, k, n, so, dem]
        n: [2, 3, 4, 5]
      answer: "{n}"
      distractors:
        - {name: off_by_one_low,  frag: "{n-1}"}
        - {name: off_by_one_high, frag: "{n+1}"}
        - {name: start_at_one,    frag: "1, {n}"}
        - {name: too_long,        frag: "{n+2}"}
```

Tier 2 adds a start value with `derived: {end: "a + n"}`; tier 3 adds an `if i % 2 == 0` accumulator
(see the file).

## 2. The 16 templates

The generator requires exactly one template per topic x type (4 x 4 = 16). Counts are playable
variants per tier (T1/T2/T3) in the committed bank.

| Template id | Topic | Type | Concept | Tier 1 / 2 / 3 content | Variants T1/T2/T3 |
| --- | --- | --- | --- | --- | --- |
| `variables_assign_fill` | variables | fill_blank | Assigning and updating a value | T1 value or string for `v = ___`; T2 `v = v + ___`; T3 the same inside a `for` loop | 14 / 12 / 12 |
| `variables_bug` | variables | find_bug | Joining text and numbers needs `str()` | T1 one number; T2 sum of two; T3 loop total | 10 / 12 / 12 |
| `variables_order_parsons` | variables | parsons | Variables must exist before use; swap through a temp variable | T1 dependent assignments; T2 swap; T3 loop accumulation | 8 / 12 / 10 |
| `variables_reassign_predict` | variables | predict_output | Reassignment overwrites; string repeat and concatenation | T1 add or repeat; T2 two variables; T3 loop with prints | 14 / 14 / 12 |
| `conditions_cmp_fill` | conditions | fill_blank | Choosing the right comparison operator or threshold | T1 operator in `if`; T2 threshold in `elif`; T3 operator inside a loop (also `% 2 ___ 0`) | 16 / 12 / 12 |
| `conditions_bug` | conditions | find_bug | `=` versus `==`, missing colon, boundary `>` versus `>=` | T1 `=` in `if`; T2 missing `:`; T3 loop: `% 2 = 0` or a missing `:` after `>=` | 10 / 12 / 12 |
| `conditions_indent_parsons` | conditions | parsons | Order and indent `if`/`else` blocks | T1 `if`; T2 `if/else`; T3 `if` inside `for` plus a final print | 8 / 12 / 10 |
| `conditions_branch_predict` | conditions | predict_output | Which branch runs | T1 `if/else`; T2 `if/elif/else`; T3 loop with `if/else` | 12 / 12 / 14 |
| `loops_range_fill` | loops | fill_blank | The end value of `range()` | T1 `range(n)`; T2 `range(a, ___)`; T3 even-sum loop | 10 / 10 / 10 |
| `loops_bug` | loops | find_bug | Off-by-one in `range`, overwriting instead of accumulating, `>` versus `>=` | T1 range end; T2 `t = i` instead of `t = t + i`; T3 `>` instead of `>=` | 10 / 10 / 12 |
| `loops_body_parsons` | loops | parsons | What is inside and outside the loop body | T1 loop then print; T2 accumulator; T3 accumulator with `if` | 8 / 12 / 10 |
| `loops_sum_predict` | loops | predict_output | Tracing a loop and its total | T1 `range(n)` sum; T2 print inside loop; T3 odd numbers or `> k` | 8 / 12 / 14 |
| `functions_return_fill` | functions | fill_blank | The expression a function returns | T1 one parameter; T2 two parameters; T3 function called in a loop | 15 / 12 / 12 |
| `functions_bug` | functions | find_bug | Missing `return`, argument order, wrong call in a loop | T1 missing `return`; T2 argument order; T3 loop call or accumulation | 12 / 12 / 14 |
| `functions_order_parsons` | functions | parsons | Define before calling; body indent | T1 def and call; T2 body with a local; T3 call in a loop | 8 / 12 / 12 |
| `functions_call_predict` | functions | predict_output | Following a call, `return` versus no return | T1 simple call; T2 two parameters or no `return` (prints `None`); T3 accumulating or branching on a result | 10 / 14 / 16 |

Totals: variables 142, conditions 142, loops 126, functions 149 = 559. Debug-only forms exist for
the four `fill_blank` templates only (40 + 39 + 30 + 38 = 147).

Tier 3 puzzles must contain a `for` loop in the solution (checked by the generator; "nesting" in the
spec).

## 3. Generator pipeline (`backend/scripts/generate_bank.py`)

Run it with `python scripts/generate_bank.py [--out PATH] [--seed N] [--verbose]` from `backend/`.
Default seed `20260516`, default output `backend/data/puzzles.sqlite`.

Steps, in the order the code performs them:

1. **Load and sanity-check templates** (`load_templates`, `main`). File name must equal `id`; exactly
   3 hints; each tier a list. Exactly 16 templates and exactly one per topic x type, otherwise a
   `PROBLEM:` line is recorded.
2. **Seed.** For each template `rng = random.Random(f"{seed}:{template_id}")`. This makes output
   independent of the order of templates.
3. **Candidate parameter sets** (`candidate_contexts`). For each block: cartesian product of
   `params`, shuffled by `rng`; for each combination compute `derived`, then drop it unless every
   `where` is truthy.
4. **Make a variant** with the maker for the template's type (`make_fill`, `make_predict`,
   `make_parsons`, `make_bug`). A maker raises `Drop(reason)` to reject a candidate; the reason is
   counted (visible with `--verbose`). Generation of a block stops after `count` accepted variants.
5. **Verify the correct program.** `run_expected()` checks size (`check_program`: 2 to 7 non-empty
   lines, each at most 48 characters), runs it with `validator.run_program`, and requires non-empty
   output of at most 5 lines with at most 40 characters each. The output becomes `expected_output`.
6. **Ambiguity check on every distractor.** Each distractor is run (`validator.diagnose`) and the
   variant is **dropped** (`ambiguous_distractor`) if any distractor also produces the correct
   output. For `predict_output` an output equal to the correct one drops the variant; duplicates
   and over-long outputs are skipped.
7. **Minimum distractors.** `fill_blank` and `predict_output` need at least 3 usable distractors
   (`too_few_distractors`), at most `MAX_DISTRACTORS = 4` are examined.
8. **Type-specific work** (details in 3.1 to 3.4).
9. **De-duplication.** Each variant has a key (for example the skeleton and the answer); a repeated
   key is counted as `duplicate` and skipped.
10. **Tier 3 rule.** A tier 3 variant whose solution has no `for` loop raises `ValueError` and stops
    the generator.
11. **IDs.** Playable variants: `{template_id}__001`, `__002`, ... in acceptance order across tiers.
    Debug-only forms: `{template_id}__d001`, ...
12. **Write SQLite** (`write_db`): the old file is deleted, the schema is created, rows are inserted,
    `meta('seed', ...)` is stored.
13. **Report and exit status.** It prints per-template and per topic x tier counts and exits 1 if
    any template has fewer than 20 variants (`MIN_TEMPLATE_VARIANTS`), any topic x tier cell has
    fewer than 20 (`MIN_CELL_VARIANTS`), the template count is not 16, or ids repeat. Note that the
    database is written **before** this check, so a failing run still replaces the file.

### 3.1 `fill_blank`

- The skeleton must contain exactly one `___`.
- The correct answer is substituted and run to get `expected_output`.
- Distractor fragments are deduplicated, substituted, and diagnosed. For each the stored option keeps
  `group` (the validator's error group, defaulting to `output_mismatch`), `actual_output`,
  `message` and the `note` from `mistakes.yaml`.
- Options: 4 slots `a` to `d`. The correct answer is put in one of `a`, `b`, `c` (random); the other
  three slots get the first three distractors in priority order.
- **Debug-only form** (used for `kind: "debug"`): the buggy program is the skeleton filled with the
  first distractor; the fix is the line filled with the correct answer; wrong fixes are the line
  filled with the remaining distractors (`ds[1:4]`). It goes through `build_bug_form` below. If that
  raises `Drop`, the variant simply has no debug form. The type of the stored row is `find_bug`,
  `debug_only = 1`, and the prompt is "Chương trình dưới đây chạy chưa đúng. Chọn cách sửa đúng
  để in ra ...".

### 3.2 `predict_output`

- The expected output is computed by running the code. Distractors are literal output strings from
  the template (`out`), normalised, deduplicated, and length-checked.
- Options: correct output plus the first three wrong outputs, group `wrong_choice`, correct one in
  slot `a` to `c`.

### 3.3 `parsons`

- Lines are split by indent (4 spaces per level). Between 3 and 7 lines are required.
- Each distractor is a full wrong arrangement; it is run and must fail, and its group is stored.
  Distractors are not shown as options for parsons; they are used to attach a `note` when the
  player's final arrangement equals a distractor's code, and to prove the puzzle is not ambiguous.
  At least one is required.
- Shuffle: up to 80 random permutations are tried. A permutation is accepted if it is not the
  identity **and** the lines with indent 0 in that order do not already pass. The shown ids are
  `l1..ln` in shuffled order; `solution` lists `{line_id, indent}` in the correct order.

### 3.4 `find_bug` (v2) and option building

`make_bug` runs the fixed program for `expected_output`, requires the buggy program to fail, takes up
to 3 distinct wrong replacements of the bug line, then calls `build_bug_form` (shared with the
debug-only forms):

1. Every wrong replacement of the bug line is run and must fail (otherwise `ambiguous_distractor`).
   At least one is required (`no_wrong_fix`). These options get group `wrong_fix`.
2. **Edits of other lines.** For every other line, `mutations(text)` proposes plausible wrong
   whole-line edits: integers changed by +1 or -1 (not below 0), operator swaps (`+`/`-`, `*` to `+`,
   `>=`/`>`, `<=`/`<`, `==`/`!=`, `>`/`>=`, `<`/`<=`), and `print(x)` to `print(x + 1)`. String
   literals are never touched; `def` lines, `else:` and `try:` are skipped. Each edit is run; an
   edit that happens to make the program pass is discarded.
3. The remaining candidates are shuffled and sorted so that edits that still run (wrong output
   rather than an error) come first. None left means `no_other_line_edits`.
4. **Choose the 4 options.** `o1` is the first candidate, `o2` prefers another edit of the same line
   as `o1`; the third distractor is `o2`, or else a second wrong fix of the bug line. With
   probability 0.5 the order is `[o1, o2, wrong_fix_0]`, otherwise `[wrong_fix_0, o1, third]`.
5. **Slots.** `place_options(4)` puts the correct fix in `a`, `b` or `c`; the first two
   distractors fill the other two of `a` to `c` and the third takes `d`.
6. **Invariants asserted in code:** four distinct `(line_id, text)` pairs; the first three options
   (what a beginner sees) span at least two lines, and all four span at least two lines. So the
   option list never reveals which line is buggy. Other-line edits get group `wrong_line`.

### 3.5 Option storage

All variable data is stored as JSON in the `data` column. Real shapes:

`fill_blank` and `predict_output`:

```json
{"options": [
  {"id": "a", "text": "4", "correct": false, "name": "off_by_one_low", "group": "output_mismatch",
   "actual_output": "0\n1\n2\n3",
   "message": "Đầu ra không khớp: chương trình in 0, 1, 2, 3 nhưng cần 0, 1, 2, 3, 4.",
   "note": "Lệch một đơn vị (thiếu): chọn giá trị nhỏ hơn đáp án đúng một đơn vị."},
  {"id": "b", "text": "5", "correct": true, "name": null, "group": null,
   "actual_output": "0\n1\n2\n3\n4", "message": null, "note": null}
]}
```

(`predict_output` options have `text`, `correct`, `name`, `group: "wrong_choice"`, `note`.)

`parsons`:

```json
{"lines": [{"id": "l1", "text": "so2 = tam"}, {"id": "l2", "text": "print(so1, so2)"}],
 "solution": [{"line_id": "l5", "indent": 0}, {"line_id": "l3", "indent": 0}],
 "distractors": [{"name": "print_too_early", "code": "so1 = 7\n...", "group": "output_mismatch", "note": "..."}]}
```

`find_bug`:

```json
{"lines": [{"id": "l1", "text": "for so in range(0, 3):", "indent": 0},
           {"id": "l2", "text": "print(so)", "indent": 1}],
 "bug_line": "l1",
 "options": [
   {"id": "b", "line_id": "l1", "text": "for so in range(0, 4):", "correct": true, ...},
   {"id": "c", "line_id": "l2", "text": "print(so + 1)", "group": "wrong_line", ...}],
 "buggy_output": "0\n1\n2", "buggy_message": "Đầu ra không khớp: ..."}
```

### 3.6 SQLite schema

```sql
CREATE TABLE puzzles (
    id TEXT PRIMARY KEY,            -- loops_range_fill__004, loops_range_fill__d019
    template_id TEXT NOT NULL,
    topic TEXT NOT NULL,
    type TEXT NOT NULL,             -- fill_blank | predict_output | parsons | find_bug
    tier INTEGER NOT NULL,          -- 1..3
    debug_only INTEGER NOT NULL DEFAULT 0,
    prompt TEXT NOT NULL,
    code TEXT,                      -- skeleton / program; NULL for parsons and find_bug
    expected_output TEXT NOT NULL,
    solution_code TEXT NOT NULL,
    explanation TEXT NOT NULL,
    hints TEXT NOT NULL,            -- JSON list of 3 strings
    data TEXT NOT NULL              -- JSON, shapes in 3.5
);
CREATE INDEX idx_puzzles_select ON puzzles (topic, tier, debug_only);
CREATE INDEX idx_puzzles_template ON puzzles (template_id);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);   -- one row: seed
```

`bank._connect()` opens the file with `file:...?mode=ro` for every request, so the server cannot
modify the bank.

## 4. Selection at play time (`bank.select_puzzle`)

### 4.1 Request

`POST /api/puzzle/next` body (`NextRequest` in `main.py`): `topic`, `tier`, `level` (default
`intermediate`), `kind` (default `rescue`), `template_id`, `exclude_ids`, `exclude_templates`.
`kind: "rescue"` needs `topic` and `tier`; `kind: "debug"` needs `template_id`; otherwise 422.

### 4.2 `rescue` and `last_commit`

1. `topic` missing defaults to a random topic; `tier` missing defaults to 3 (so `last_commit` without
   a tier gets tier 3).
2. SQL: `topic = ? AND tier = ? AND debug_only = 0`.
3. Remove ids in `exclude_ids` (hard: if nothing is left the answer is 404).
4. If `template_id` is given keep only that template.
5. `exclude_templates` is a **soft** preference: rows from other templates are used if any exist,
   otherwise the excluded templates are allowed. The client sends its last 3 templates.
6. Choose with `random.choices`, weight per **row** taken from `TYPE_WEIGHTS[level]`:

| Level | fill_blank | parsons | predict_output | find_bug |
| --- | --- | --- | --- | --- |
| beginner | 3 | 3 | 2 | 1 |
| intermediate | 2 | 2 | 2 | 2 |
| advanced | 1 | 1 | 3 | 3 |

Because the weight is per row, the real chance of a type is `weight x rows of that type in the pool`.
For `loops`, tier 1 there are 10 fill, 8 parsons, 8 predict and 10 find_bug rows; a beginner draws
30 / 24 / 16 / 10, that is 37.5 %, 30 %, 20 % and 12.5 %.

### 4.3 `debug`

1. All rows of `template_id` (404 if the template does not exist), minus `exclude_ids`.
2. Prefer rows of type `find_bug` (this includes native `find_bug` puzzles and the `debug_only`
   forms); if the template has none (parsons and predict templates), use its non-debug-only rows.
3. Pick uniformly at random. `topic`, `tier` and type weights are ignored, so a debug puzzle can
   have a different tier from the puzzle that was failed (a real example: a tier 1 `loops_range_fill`
   failure produced tier 2 `loops_range_fill__d019`).

The server does not remember which puzzle was failed. The browser passes it in `exclude_ids`
(`G.seenIds`) so the same variant is not returned.

### 4.4 Rematch

`GET /api/puzzle/{id}/rematch?level=` calls `select_puzzle(kind="rescue", ...)` with the original
puzzle's topic, tier and template and `exclude_ids=[original id]`, so the new puzzle is a different
variant of the same template and tier.

## 5. The player view and the per-level option shuffle

`bank.public_puzzle(row, level)` returns only: `id, template_id, topic, type, tier, prompt, code,
expected_output, lines, options`. It never contains `correct`, `solution_code`, `explanation`,
`hints`, `group`, `name`, `note`, `actual_output`, `bug_line` or `distractors`
(`test_public_views_never_leak`).

- `predict_output`: `expected_output` is `null`.
- `parsons`: `code` is `null`, `options` is `null`, `lines` is `[{id, text}]` without indent.
- `find_bug`: `lines` carries `indent`; each option carries `line_id`.

Options are shown through `_view_options(options, puzzle_id, level)`:

1. Keep the first 3 stored options for `beginner`, all 4 otherwise. The generator guarantees the
   correct option is in slots `a` to `c`, so beginners always see it.
2. Shuffle the kept options with `random.Random(f"{puzzle_id}:{level}")`. Without this the 4th
   stored slot would never be correct. The shuffle is deterministic per puzzle and level, and
   option ids are not changed, so answer checking does not depend on display order.

## 6. Answer checking (`bank.check_answer`)

| Type | How correctness is decided | Group on a wrong answer |
| --- | --- | --- |
| `fill_blank` | The chosen option's stored `correct` flag | the option's stored `group` (`output_mismatch`, `syntax`, ...) |
| `predict_output` | Stored `correct` flag | `wrong_choice` |
| `find_bug` | Stored `correct` flag; `line_id` in the request is ignored | `wrong_line` if the option's `line_id` is not `bug_line`, else `wrong_fix` |
| `parsons` | The order and indents are validated, assembled into a program, and run with `validator.diagnose` | the diagnosis, refined to `wrong_order` or `bad_indent` when the program ran but printed the wrong thing |

Response shaping (`_result`): a correct answer always returns `solution_code` and `explanation`; a
wrong one returns them only when `reveal` is true (the final attempt). For a wrong answer the
explanation is `"{note} {explanation}"` when the option has a note. Invalid input (unknown
`option_id`, missing `order`, wrong set of `line_id`s, indent outside 0 to 2) is HTTP 422.

## 7. How to add a variant or a template

### 7.1 More variants for an existing concept (the normal case)

1. Open the template, for example `backend/content/templates/loops_range_fill.yaml`.
2. Under the tier you want, add a new block (or extend `params` of an existing block).
3. Give the block a `prompt`, a `code` skeleton, `params`, optional `derived`/`where`, the answer
   field for the type, and distractors. For each distractor use a `name`; add a note for new names
   in `content/mistakes.yaml`.
4. Make sure every distractor is genuinely wrong: the generator will drop ambiguous variants, but a
   block whose distractors are always ambiguous yields zero variants.
5. Regenerate and read the report: `python scripts/generate_bank.py --verbose` shows per-template
   counts and why variants were dropped.
6. Run `python -m pytest -q`. `test_bank_integrity.py` re-verifies every stored puzzle.
7. Commit `puzzles.sqlite` together with the YAML (the Dockerfile copies the committed database; it
   does not regenerate it).

### 7.2 A new template (new concept)

The generator and tests currently hard-code "exactly 16, one per topic x type". To add a seventeenth
template you must change that rule deliberately:

1. Create `content/templates/<topic>_<name>_<type>.yaml` (file name = `id`).
2. In `generate_bank.py: main()` relax the `len(templates) != 16` check and the
   `combos[(topic, typ)] != 1` check.
3. In `tests/test_bank_integrity.py: test_bank_shape` change the assertion
   `len({r["template_id"] for r in primary}) == 16`.
4. Update the documents that say 16 (`README.md`, `backend/README.md`, this file).
5. Regenerate and run the tests.

Replacing one of the 16 (same topic and type, new `id`) needs only steps 1 and 5, and a
`mistakes.yaml` update.

### 7.3 Coverage requirements

| Requirement | Enforced by |
| --- | --- |
| Every template has at least 20 playable variants | `generate_bank.py` exit status; `test_bank_shape` |
| Every topic x tier cell has at least 20 playable variants | same |
| 16 templates, one per topic x type | `generate_bank.py` (`PROBLEM:`), `test_bank_shape` |
| At least 500 playable rows; at least 280 `find_bug` rows (including debug forms) | `test_bank_shape`, `test_find_bug_options_span_two_lines_even_for_beginners` |
| Program of 2 to 7 non-empty lines, each at most 48 chars; output at most 5 lines of at most 40 chars | `check_program`, `output_ok`; re-asserted by `test_every_puzzle_is_consistent` |
| Parsons has 3 to 7 lines and a wrong starting shuffle | `make_parsons`; `test_solutions_pass_and_distractors_fail` |
| Tier 3 solution contains a `for` loop | generator raises; `test_every_puzzle_is_consistent` |
| Solution passes; every distractor fails | `test_solutions_pass_and_distractors_fail` |
| Exactly one correct option; the correct option is among `a` to `c`; distinct option texts; 4 options for playable puzzles | `test_every_puzzle_is_consistent` |
| `find_bug` options span at least 2 lines, also in the first three | `test_find_bug_options_span_two_lines_even_for_beginners` |
| No placeholder `{` left in prompt, explanation or hints; 3 non-empty hints | `test_every_puzzle_is_consistent` |
| Public view never leaks the answer | `test_public_views_never_leak` |

## 8. Determinism

Same seed, same templates, same Python gives the same file. Verified for these docs: regenerating
to a temporary path with the default seed produced all 706 rows identical to the committed
`puzzles.sqlite` (Python 3.14.7). Other Python versions were not tested; the generator relies on
`random.Random(str)` seeding with `shuffle`, `sample`, `randrange` and `random`, so a change in the
standard library's shuffling algorithm could change the output.

## 9. Open questions

- **Spec says 30 to 50 variants per template.** The generator docstring repeats it, but the counts
  are set by each block's `count`: 28 to 40 playable variants per template (plus debug forms).
- **Parsons size.** The spec says 2 to 4 lines (section 4.1); the generator requires 3 to 7.
- **Spec colour names.** The spec calls the loops colour purple; the UI (design brief v2) uses coral
  for loops. Topic names are consistent; only the colour word differs.
- **Spec section 10.3 "remember seen variants per player across games"** is not implemented. Seen ids
  live only in the current game (`seenIds`).
- **The generator writes the database even when coverage fails**, then exits with status 1. A failed
  run therefore leaves a smaller bank in place.
- **58 of 145 distractor names have no note** in `mistakes.yaml` (they still get the template
  explanation). Decide whether that is intended.
- **Debug puzzle tier.** The contract says `topic`/`tier` are ignored for debug; the effect is that
  the difficulty of a debug puzzle is not tied to the failed puzzle.
