# Syntax Stack — presentation content (SERS template), v2

Slide order mirrors `SERS.pdf` (title → contents → context & problem → market pain → solution →
technology → flow → business → roadmap → Q&A → thank you), with extra slides for the working
prototype and the new learning features. Language: English, like the template. Each slide lists the
**title**, the **on-slide text** (kept short, as in SERS), a **visual** suggestion and a one-line
**speaker note**. The game itself is in Vietnamese; slide text is English.

Screenshots referenced below are in `frontend/_screens/v4/` (new features) and
`frontend/_screens/v3/` (unchanged screens).

> Before presenting: double-check the three cited figures on slides 5–6 against the original papers
> and adjust wording if your lecturer wants a specific citation style.

> Screenshot caveat: in the `v4` captures the **GIA SƯ AI** cards show the same sample paragraph on
> every screen (hint, explanation, rematch, teach-back), and it does not always match the puzzle
> shown. Treat those cards as layout illustrations. For the final deck, re-capture them with the real
> tutor on, or crop to the label and footer only.

## Changes from v1

- **AI tutor is built, not planned.** Optional, runs through an n8n webhook, with authored fallbacks so the game always works without it. It is labelled **AI · Gia sư AI** with a "may be wrong" footer, and the validator still decides correctness.
- **Where the tutor helps:** Syntax Rows hints (including one tied to a trace step), "Vì sao mình sai?" after a wrong Code Rescue answer, the rematch bridge, and teach-back feedback.
- **New learning features:** step-by-step trace, predict the output, "Đổi một mảnh" twist, "Giải thích lại" teach-back, and "Luyện theo lỗi" practice built from the player's own mistakes.
- **Judge demo screen** at `/?demo=judge`; the live demo script (now slide 15) is rewritten around it, with a fallback line.
- **Numbers updated:** 559 playable puzzles plus 147 debug-only "find the bug" variants (706 rows) from 16 templates; **149 automated tests passing** (run on the day of writing; the count is still growing, so say "140+").
- **Roadmap updated:** the AI tutor moves from "short-term" to done. AI cost limits and usage logging are done too. Short-term is now the pilot with 20–30 students and Code Rescue's 3-level hints, which are still authored text.
- **Two new slides** in section 4 (4.3 learning features, 4.4 AI tutor), so later slide numbers shift by two. Slide 1 team names, the references and the verify-the-figures note are unchanged.
- **Not claimed:** learning gains, engagement and "hints are helpful" are not measured; they are framed as "to be tested in the pilot".

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

**Visual:** the start screen keycap title (`frontend/_screens/v3/start-desktop.png`, crop to the "SYNTAX STACK" keys).

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

> **Key message:** The validator decides right or wrong, never AI. An optional AI tutor only explains *why*, is labelled as AI, and the game works without it.

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
2. **Breakthrough:** a validator (not AI) checks every answer, so correctness is always reliable; hints come in 3 levels (*Concept → Direction → Specific*) and an optional AI tutor explains the mistake.
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

**Visual:** `frontend/_screens/v3/rescue-board-desktop.png` (left) and `frontend/_screens/v4/trace-open-desktop.png` (right; Syntax Rows with the new trace panel).

---

## Slide 11 — 4.2 One wrong answer is a lesson (Code Rescue flow)

**Level 1 – Stable (green):** full row locks → puzzle on that row's topic, **one answer only**.
- Correct → row clears, score + streak, may earn an item (bomb, shuffle, undo, debugger).

**Level 2 – Warning (yellow):** first wrong answer → the row becomes a **bug line**.
- The game shows the correct answer + an authored explanation; **"Vì sao mình sai?"** asks the AI tutor to explain *this* mistake.
- Tap the bug line → a *Debug* variant of the same concept. Fix it → **+150 "Redemption"**, back to green.

**Level 3 – System Crash (red):** second wrong answer → game over.
- An **error report** lists every concept missed, with a "Practise this topic again" button.

**Practice mode:** no losing, 3 tries per puzzle, extra blocks of the player's weakest topic.

**Visual:** three LEDs BUILD / WARN / CRASH from the header, plus `frontend/_screens/v4/rescue-wrong-desktop.png` (wrong answer, diff, authored explanation, "Vì sao mình sai?") and `frontend/_screens/v4/rescue-explain-ai-desktop.png` (the AI card).

---

## Slide 12 — 4.3 Learn from every run *(new)*

- **Predict the output** before you run. It never affects the grade.
- **Step-by-step trace:** variable values and output after each line.
- **"Đổi một mảnh" (twist):** after passing, change one piece to hit a new target output.
- **"Giải thích lại" (teach-back):** explain your solution in your own words.
- **"Luyện theo lỗi":** practice built from the player's own recent mistakes.

> Whether these improve learning is **to be tested in the pilot**.

**Visual:** `frontend/_screens/v4/predict-result-desktop.png`, `frontend/_screens/v4/trace-open-desktop.png`, `frontend/_screens/v4/pass-teachback-input-desktop.png`; practice screen `frontend/_screens/v4/practice-desktop.png`. Phone versions: same names with `-phone.png`.

**Speaker note:** "The validator already knows what each line does, so we let learners watch it run, guess before it runs, and say it back in their own words."

---

## Slide 13 — 4.4 AI tutor: explains, never grades *(new)*

- **Optional:** n8n webhook; without it the game uses authored hints and explanations.
- **Used in four places:** Syntax Rows hints (incl. a trace step) · "Vì sao mình sai?" · rematch bridge · teach-back feedback.
- **Labelled:** every AI text sits in an **AI · Gia sư AI** card with "may be wrong, check with Run" footer.
- **Validator decides:** AI text is only displayed; it never sets pass/fail, stars or score.
- **Safe by design:** only validator-verified context is sent, plus the learner's own words in teach-back.

**Visual:** `frontend/_screens/v4/trace-hint-ai-desktop.png` (AI card under the trace) next to an authored hint (muted `# comment` line) to show the difference.

**Speaker note:** "If the tutor is wrong, you can see it is AI, and the validator still has the last word."

---

## Slide 14 — 5. Applied Technology

- **Frontend:** plain HTML, CSS and JavaScript (ES modules, no framework); responsive from 375 px phones to desktop; "mechanical keyboard" design: every block is a keycap.
- **Backend:** Python + FastAPI, REST API for both modes.
- **Validator (core):** parses code into an AST, allows only a whitelist of safe Python, runs it with step/time/output limits, and classifies errors (missing colon, wrong indent, wrong order, output mismatch…). It also records the per-line trace.
- **Puzzle bank:** 16 hand-written templates (4 topics × 4 types) generate **559 playable puzzles plus 147 debug-only "find the bug" variants (706 rows)** offline, stored in SQLite; every puzzle is re-verified (the solution passes, every distractor fails).
- **AI tutor (optional):** n8n webhook → short text (≤ 750 characters), cached, max 2 calls at once, a daily call cap and a usage log. Any failure falls back to authored text.
- **Tests:** 140+ automated tests (149 passing at writing).

**Visual:** architecture strip: Browser → FastAPI → Validator → SQLite bank, with "AI tutor (optional, explains only)" as a side box and a dashed "authored fallback" arrow.

---

## Slide 15 — 6. Current Progress & Demo

**Built and working today:**
- Both modes playable end to end in the browser, desktop and phone.
- Code Rescue: 8×8 board, line locking, all 4 puzzle types, bug line + Debug, crash and end report.
- Syntax Rows: 5 Beginner levels (*First variable · Pass or fail · Count to three · Running total · Double function*), star rating, error row highlighted in red.
- **AI tutor** integrated with authored fallback; **trace, predict, twist, teach-back** and **mistake-based practice** working.
- **559** playable puzzles (**706** rows with debug variants) across 4 topics × 3 difficulty tiers.
- **140+ automated tests** (149 passing).

**Next up:** pilot with 20–30 students; deploy to https://syntax.screepai.moe.

**Visual:** 3 phone screenshots side by side: `frontend/_screens/v4/trace-hint-ai-phone.png`, `frontend/_screens/v4/pass-teachback-ai-phone.png`, `frontend/_screens/v4/rescue-explain-ai-phone.png`. Use this slide for the live demo; the judge screen is `frontend/_screens/v4/practice-judge-desktop.png`.

**Speaker note (live demo, ~90 s, open `/?demo=judge`):**
1. (0:00) Tap **Dự đoán đầu ra**: guess the output of the running-total program, run it, and compare your guess with the real output.
2. (0:20) Back, tap **Theo dõi vòng lặp**: the loop with `range(2)` runs and the validator says the output is `0 1` but `0 1 2` is needed. Step through the trace and watch `i` and the output change.
3. (0:45) Tap **Gợi ý bước này**: the **AI · Gia sư AI** card explains this step, with its "may be wrong" footer.
4. (1:00) Swap `range(2)` for `range(3)`, **Chạy kiểm tra**: pass, rows clear.
5. (1:15) Open **Giải thích lại**, type one sentence, tap **Hỏi gia sư** for feedback.

**Fallback line:** "If the tutor is offline, the same flow shows the authored hints instead of the AI card; the validator, trace and pass are identical."

---

## Slide 16 — 7. Business Potential

1. **Cost optimisation:** runs in any browser with no install; a free core version for students. AI use is optional, short, cached and capped per day, with every call counted and logged.
2. **Large user base:** BTEC FPT students in intro programming courses, then high-school and university beginners, coding clubs and self-learners.
3. **Easy to scale:** new topics and puzzles are added by writing a template, not code; a classroom package with progress reports for lecturers could become a paid plan for schools *(an idea, not validated)*.

**Visual:** same numbered layout as SERS slide 12.

---

## Slide 17 — 8. Development Roadmap

- **Done:** AI tutor (optional, labelled, with authored fallback, daily call cap and usage log), trace, predict, twist, teach-back, mistake-based practice, judge demo.
- **Short-term:** pilot with 20–30 students comparing the two modes (completion rate, retries, hints used, how helpful hints felt; learning gains are **to be tested in the pilot**); a per-student AI quota on top of the daily cap; Code Rescue's 3-level hints are still authored text, with AI hints an option for later.
- **Medium-term:** more Syntax Rows levels at Intermediate and Advanced; accounts, progress tracking and a teacher dashboard.
- **Long-term:** a classroom tool for BTEC/FPT lecturers, with more languages (C#, JavaScript) and more topics (lists, strings).

---

## Slide 18 — Question Time

**Question Time**

*Likely questions, short answers:*
- **"Why not let AI grade the code?"** AI can be wrong. A wrong mark in a game where you can only fail once is unfair. The validator is always right; AI only explains.
- **"What if the AI tutor is wrong?"** Its text is labelled AI with a "may be wrong" footer, it cannot grade (it never sets pass/fail, stars or score), and the validator decides. Learners re-check with Run, and if the tutor fails the game shows authored text.
- **"How much does the AI cost / what data do you send?"** Only validator-verified game context (puzzle, code, output, diagnosis) plus the learner's own words in teach-back; no names, accounts or other personal data are asked for. Replies are short and cached, at most 2 calls run at once, there is a daily call cap (500 by default), and every call is logged (task, outcome, time; never the text).
- **"What happens with no internet / AI down?"** The game falls back to authored hints and explanations and stays fully playable. The core game runs from our own server; only Google Fonts come from the internet, and system fonts take over if they are blocked.
- **"Isn't running user code dangerous?"** Players never type code that gets run: they assemble pieces from our bank (predictions and teach-back are plain text, never executed), and the validator blocks imports, file access and long loops.
- **"How is this different from Block Blast?"** We use the genre, not the game: our blocks are code, and rows clear only when the code is correct.
- **"Does it actually improve learning?"** Not measured yet. The pilot with 20–30 volunteers will compare the two modes; we report observed changes only.

---

## Slide 19 — Thank You

**Thank You**

---

## References

- Bennedsen, J. & Caspersen, M. E. (2007). *Failure rates in introductory programming.* ACM SIGCSE Bulletin, 39(2).
- Watson, C. & Li, F. W. B. (2014). *Failure rates in introductory programming revisited.* ITiCSE '14.
- Becker, B. A. et al. (2019). *Compiler error messages considered unhelpful.* ITiCSE-WGR '19.
- Ericson, B. J. et al. (2017). *Solving Parsons problems versus fixing and writing code.* Koli Calling '17 (supports the Parsons puzzle type).
