# Syntax Stack — presentation content (SERS template)

Slide order mirrors `SERS.pdf` (title → contents → context & problem → market pain → solution →
technology → flow → business → roadmap → Q&A → thank you), with one extra slide for the working
prototype. Language: English, like the template. Each slide lists the **title**, the **on-slide
text** (kept short, as in SERS), a **visual** suggestion and a one-line **speaker note**.

Screenshots referenced below are already in `frontend/_screens/v3/`.

> Before presenting: double-check the three cited figures on slides 4–6 against the original papers
> and adjust wording if your lecturer wants a specific citation style.

---

## Slide 1 — Title

**SYNTAX STACK**
Learn Python by stacking real code

- Competition: BTEC Best Coder 2026
- Team name: LE ROUGE
- Institution: BTEC FPT, class SE08301
- Supervising Lecturer: *(fill in)*
- Project Team Members:
  - Do Hong Minh (Team lead)
  - Tran Thuong Vu Lam
  - Ta Minh Hieu
  - Bui Manh Cuong
  - Dinh Quoc Hieu

**Visual:** the start screen keycap title (`start-desktop.png`, crop to the "SYNTAX STACK" keys).

---

## Slide 2 — Table of contents

1. Project Introduction
2. Context & Problem
3. Market Pain
4. Our Solution
5. Applied Technology
6. Current Progress & Demo
7. Business Potential
8. Development Roadmap

---

## Slide 3 — 1. Project Introduction

1. **What is it?** A browser block-puzzle game where the blocks *are* Python code.
2. **How it works:** every row on the board is one line of a program; a row only clears when a validator confirms the code is correct.
3. **Who it's for:** BTEC FPT students and anyone writing their first lines of Python.

> **Key message:** We don't use AI to grade. A validator decides right or wrong; hints only explain *why* and point the way.

**Speaker note:** "Think Block Blast, but every block you place is a piece of a Python program."

---

## Slide 4 — 2. Context & Problem (section divider)

**2. Context & Problem**

---

## Slide 5 — 2.1 Programming is a hard first step

- **High failure rate:** around 1 in 3 students fail their first programming course worldwide *(Bennedsen & Caspersen, 2007; Watson & Li, 2014)*.
- **Syntax overload:** beginners must handle syntax, statement order and problem-solving logic all at once.
- **Long silence:** when code doesn't run, a beginner often can't tell *which* of those three went wrong.

**Visual:** simple bar or donut: "Pass ≈ 67% / Fail ≈ 33%" (same style as the SERS fall-rate donut).

---

## Slide 6 — 2.2 Feedback that doesn't teach

- **Error messages confuse:** standard compiler/interpreter messages are written for experts, not novices *(Becker et al., 2019)*.
- **Right / wrong only:** most practice sites stop at "Wrong answer" or reveal the full solution straight away.
- **Motivation drops:** students lose momentum, copy answers, or wait for the lecturer.

**Visual:** a red Python traceback next to a confused-student icon.

---

## Slide 7 — 2.3 Problem to Solve

- **Urgent need:** a short, low-pressure way to practise that turns every mistake into a lesson.
- **Objective:** learners see *which line* is wrong, *what kind* of error it is, and get hints step by step instead of the answer.

---

## Slide 8 — 3. Market Pain – The Gap

- **Online judges (LeetCode, HackerRank…):** built for people who can already code; feedback is pass/fail on hidden tests.
- **Video courses:** passive; watching is not writing.
- **AI chatbots:** answer instantly and often give away the full solution; they can also be wrong, so they can't be the judge.
- **Casual puzzle games:** fun and habit-forming, but teach nothing.

> **The gap:** nothing combines the "one more round" pull of a casual game with real, verified code feedback for absolute beginners.

**Visual:** 2×2 grid (Fun ↔ Not fun / Verified feedback ↔ None) with Syntax Stack alone in the "fun + verified" corner.

---

## Slide 9 — 4. Our Solution (Syntax Stack)

1. **What is Syntax Stack?** A two-layer coding game: blocks are Python code, rows are lines, and indentation is the column a block sits in.
2. **Breakthrough:** a validator (not AI) checks every answer, so feedback is always correct; hints come in 3 levels: *Concept → Direction → Specific*.
3. **Core value:** practice that feels like a game, mistakes that teach, and no time pressure.

**Visual:** same numbered-circle layout as SERS slide 9.

---

## Slide 10 — 4.1 Two game modes

| | **Code Rescue** | **Syntax Rows** |
| --- | --- | --- |
| Blocks | Shapes coloured by topic | Real code tokens (1u–3u keys) |
| Row clears when… | You solve a code puzzle | Your program runs correctly |
| Failure | 2 wrong answers = system crash | Unlimited retries |
| Purpose | Reflexes under light pressure | Learn to write code calmly |

- **4 topics, colour-coded:** Variables · Conditions · Loops · Functions
- **4 puzzle types:** Fill the blank · Predict output · Parsons (reorder lines) · Find the bug

**Visual:** `rescue-board-desktop.png` (left) and `rows-3-desktop.png` (right).

---

## Slide 11 — 4.2 One wrong answer is a lesson (Code Rescue flow)

**Level 1 – Stable (green):** full row locks → puzzle on that row's topic, **one answer only**.
- Correct → row clears, score + streak, may earn an item (bomb, shuffle, undo, debugger).

**Level 2 – Warning (yellow):** first wrong answer → the row becomes a **bug line**.
- The game shows the correct answer + an explanation.
- Tap the bug line → a *Debug* variant of the same concept. Fix it → **+150 "Redemption"**, back to green.

**Level 3 – System Crash (red):** second wrong answer → game over.
- An **error report** lists every concept missed, with a "Practise this topic again" button.

**Practice mode:** no losing, 3 tries per puzzle, extra blocks of the player's weakest topic.

**Visual:** three LEDs BUILD / WARN / CRASH from the header, plus `flow-wrong-result-desktop.png`.

---

## Slide 12 — 5. Applied Technology

- **Frontend:** plain HTML, CSS and JavaScript (ES modules, no framework); responsive from 375 px phones to desktop; "mechanical keyboard" design: every block is a keycap.
- **Backend:** Python + FastAPI, REST API for both modes.
- **Validator (core):** parses code into an AST, allows only a whitelist of safe Python, runs it with step/time/output limits, and classifies errors (missing colon, wrong indent, wrong order, output mismatch…).
- **Puzzle bank:** 16 hand-written templates (4 topics × 4 types) generate **706 puzzles offline**, stored in SQLite; every puzzle is re-verified (the solution passes, every distractor fails).
- **AI tutor:** plugs into a ready hint interface; today hints are hand-written so the game always works offline.

**Visual:** architecture strip: Browser → FastAPI → Validator → SQLite bank, with "AI tutor (hints only)" as a side box.

---

## Slide 13 — 6. Current Progress & Demo

**Built and working today:**
- Both modes playable end to end in the browser, desktop and phone.
- Code Rescue: 8×8 board, line locking, all 4 puzzle types, bug line + Debug, crash and end report.
- Syntax Rows: 5 Beginner levels (*First variable · Pass or fail · Count to three · Running total · Double function*), star rating, error row highlighted in red.
- **706** verified puzzles across 4 topics × 3 difficulty tiers.
- **106 automated tests passing.**

**Next up:** live AI hints, pilot with 20–30 students.

**Visual:** 3 phone screenshots side by side: `rescue-lock-phone.png`, `puzzle-parsons-phone.png`, `rows-pass-phone.png`. Use this slide for the live demo.

**Speaker note (demo script, ~60 s):** play Syntax Rows level 3, place `range(2)`, run → validator flags output `0 1` and the hint says "range() stops before the end value"; swap to `range(3)`, run → rows clear top to bottom.

---

## Slide 14 — 7. Business Potential

1. **Cost optimisation:** runs in any browser with no install; a free core version for students, with AI and hosting costs tracked from day one.
2. **Large user base:** BTEC FPT students in intro programming courses, then high-school and university beginners, coding clubs and self-learners.
3. **Easy to scale:** new topics and puzzles are added by writing a template, not code; a classroom package with progress reports for lecturers could become a paid plan for schools.

**Visual:** same numbered layout as SERS slide 12.

---

## Slide 15 — 8. Development Roadmap

- **Short-term:** connect the AI tutor for hints and explanations (with the hand-written hints as a fallback); run a pilot with 20–30 students comparing the two modes (completion rate, retries, hints used).
- **Medium-term:** more Syntax Rows levels at Intermediate and Advanced; accounts, progress tracking and a teacher dashboard.
- **Long-term:** a classroom tool for BTEC/FPT lecturers, with more languages (C#, JavaScript) and more topics (lists, strings).

---

## Slide 16 — Question Time

**Question Time**

*Likely questions, short answers:*
- **"Why not let AI grade the code?"** AI can be wrong. A wrong mark in a game where you can only fail once is unfair. The validator is always right; AI only explains.
- **"Isn't running user code dangerous?"** Players never type free code; they assemble pieces from our bank, and the validator blocks imports, file access and long loops.
- **"How is this different from Block Blast?"** We use the genre, not the game: our blocks are code, and rows clear only when the code is correct.

---

## Slide 17 — Thank You

**Thank You**

---

## References

- Bennedsen, J. & Caspersen, M. E. (2007). *Failure rates in introductory programming.* ACM SIGCSE Bulletin, 39(2).
- Watson, C. & Li, F. W. B. (2014). *Failure rates in introductory programming revisited.* ITiCSE '14.
- Becker, B. A. et al. (2019). *Compiler error messages considered unhelpful.* ITiCSE-WGR '19.
- Ericson, B. J. et al. (2017). *Solving Parsons problems versus fixing and writing code.* Koli Calling '17 (supports the Parsons puzzle type).
