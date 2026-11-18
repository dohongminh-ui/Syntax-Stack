# Syntax Stack — presentation content (SERS template), v3.3 (finals)

Slide-by-slide content for `Stack.pdf`, matched one-to-one with the speaking script
`docs/presentation-script.md` (v3.3). The talk is **10 minutes including a 3:20 live demo** (hard stop 3:45), so the
deck is 16 slides and the slides carry headlines, not paragraphs: the speakers carry the depth.
Each slide lists the **on-slide text**, a **visual**, and where the media comes from. Language: English,
like the template; the game itself is in Vietnamese. v2 of this file is in git history.

> Before presenting: double-check the three cited figures on slide 4 against the original papers.

> **Wording rule for Misaki (read before editing any slide).** Misaki is one AI character with two
> jobs. As the **tutor** she explains, using a large language model; as the **opponent** she is a
> **search-based game AI**. On slides never write "trained", "learns", "machine learning" or "our own
> model" about her. "AI tutor", "AI opponent" and "plans her moves with a search algorithm" are all true.
> The vendor (Google Gemini) is not on the slides; it is in the spoken Q&A answer, ready if asked.

## Changes from v2

- **19 → 16 slides.** Section dividers and "Learn from every run" are gone (that slide becomes part of
  the live demo). The two AI-tutor slides fold into the solution and the demo.
- **New demo slide (11)** built around three beats: live classroom, puzzles from pasted code, and
  "Vì sao?" (AI explains a wrong prediction). It carries the fallback recording.
- **New features shown:** live classroom with teacher dashboard, puzzles from pasted code (runs in a
  sandbox), skill map, AI explanation of wrong predictions, AI end-of-run debrief, "Đọc code" bonus.
- **Business slide:** the classroom package is **built**, not "an idea, not validated".
- **Numbers updated:** 559 playable puzzles (706 generated forms with debug-only variants); tests
  "more than 400" (421 on 18 Nov; recount the day before).
- **Q&A updated:** "Isn't running user code dangerous?" no longer says players never type code (they
  can paste code now); the answer is the sandbox, with the limits tested on the live server.
- **Still not claimed:** learning gains. Framed as the pilot.
- **v3.2: Misaki.** The AI tutor and the 1v1 AI opponent are one character, Misaki. Slides 8, 11, 12
  and 14 use her name; 1v1 (vs friends or Misaki, 4-level ladder, training mode with coaching) moves to
  "Built" on the roadmap.

## Screenshots to capture (new)

Capture at 1920×1080 for desktop shots and 390×844 for phone shots. Use **real** data, not mock
mode, for anything on the business or demo slide (mock screens are labelled "mô phỏng" on screen).

| File (suggested, in `frontend/_screens/v5/`) | How to get it |
| --- | --- |
| `classroom-dashboard-desktop.png` | Open a room, have 3–4 people answer ~15 puzzles with a few deliberate mistakes, wait for the heatmap to fill, capture the teacher screen. |
| `classroom-join-phone.png` | `/?room=<code>` on a phone in a random-names room: the "Tên của bạn: …" moment after tapping "Vào phòng". |
| `leaderboard-phone.png` | `Bảng xếp hạng` after a few real ranked runs (not mock: mock is labelled "dữ liệu mẫu"). |
| `custom-result-desktop.png` | `Tạo câu đố từ code` → paste the demo program → capture the four puzzle cards. |
| `skills-map-phone.png` | Play a few Rescue runs first so the map has all four mastery levels, then `Bản đồ kỹ năng`. |
| `predict-why-ai-phone.png` | Syntax Rows level 3, `range(2)`, predict 0 1 2, Run, tap "Vì sao?" with the tutor on: the "MISAKI · GIA SƯ AI" card. |
| `misaki-ladder-phone.png` | `Đối kháng 1v1` → "Đấu với Misaki" after beating level 1, so one level shows unlocked and two locked. |
| `misaki-coach-phone.png` | A training match ("Luyện tập cùng Misaki") with her coach bubble visible and a "Gợi ý nước đi" suggestion outlined on the board. |
| `end-debrief-ai-phone.png` | Lose a Rescue run with 2 mistakes, capture the "Tổng kết" block. |
| `demo-fallback.mp4` | 20-second screen recording of the three demo beats, for slide 11. |

Unchanged screens can still come from `frontend/_screens/v3/` and `v4/`.

---

## Slide 1 — Title

**SYNTAX STACK**
Learn Python by stacking real code

- Competition: BTEC Best Coder 2026
- Team name: LE ROUGE
- Institution: BTEC FPT, class SE08301
- Supervising Lecturer: Ms. Ngo Thi Mai Loan
- Project Team Members:
  - Do Hong Minh (Team lead)
  - Tran Thuong Vu Lam
  - Ta Minh Hieu
  - Bui Manh Cuong
  - Dinh Quoc Hieu

**Visual:** the homepage keycap title over the spotlight and drifting code keys (desktop screenshot of `/`).

---

## Slide 2 — Contents

1. The problem
2. The gap
3. Our solution
4. **Live demo** (you can join from your phone)
5. Technology
6. Business & roadmap

---

## Slide 3 — Project introduction

**A block-puzzle game where the blocks are Python code.**

- Every row is one line of a program.
- A row clears only when our validator **runs the code** and confirms it is correct.
- For BTEC FPT students and anyone writing their first lines of Python.

**Visual:** `frontend/_screens/v3/rescue-board-desktop.png` cropped to the board.

---

## Slide 4 — Programming is a hard first step

- **~1 in 3** students fail their first programming course *(Bennedsen & Caspersen, 2007; Watson & Li, 2014)*.
- Beginners juggle **syntax, order and logic** at once, and can't tell which one broke.

**Visual:** donut "Pass ≈ 67% / Fail ≈ 33%" (SERS fall-rate style).

---

## Slide 5 — Feedback that doesn't teach

- Error messages are written for experts *(Becker et al., 2019)*.
- Practice sites say "Wrong" or show the whole answer. **Neither teaches.**

**Visual:** a red Python traceback next to a confused-student icon.

---

## Slide 6 — What a solution must do

1. **Short and low-stakes:** a few minutes, on a phone.
2. After a mistake, show **which line**, **what kind** of error, and **hints a little at a time**.

---

## Slide 7 — The gap

| | Engaging | Feedback you can trust |
| --- | --- | --- |
| Online judges (LeetCode…) | ✗ | pass/fail only |
| Video courses | ✗ | ✗ |
| **AI chatbots / AI mentors** | ✓ | ✗ can be confidently wrong |
| Casual puzzle games | ✓ | ✗ teach nothing |
| **Syntax Stack** | ✓ | ✓ **verified by running the code** |

**Visual:** the table, or the 2×2 (Fun ↔ Not fun / Verified ↔ None) with Syntax Stack alone in the
"fun + verified" corner.

---

## Slide 8 — Our solution

1. **The board is the program.** Rows are lines; the column is the indentation.
2. **A validator judges. AI only explains.** Every answer is checked by running the code. **Misaki**,
   our AI tutor, explains a mistake the validator has already confirmed, is labelled as AI, and falls
   back to hand-written text.
3. **No time pressure.** Thinking slowly is allowed.

**Visual:** numbered-circle layout (SERS slide 9).

---

## Slide 9 — Two modes

| | **Code Rescue** | **Syntax Rows** |
| --- | --- | --- |
| Blocks | Shapes coloured by topic | Real code tiles |
| Row clears when… | You solve a code puzzle | Your program runs correctly |
| Mistakes | One mistake = warning, two = crash | Unlimited retries |
| Trains | Reading & recognising code | Writing code |

- 4 topics: Variables · Conditions · Loops · Functions
- 4 puzzle types: Fill the blank · Predict output · Reorder lines (Parsons) · Find the bug

**Visual:** `frontend/_screens/v3/rescue-board-desktop.png` and `frontend/_screens/v4/trace-open-desktop.png`.

---

## Slide 10 — One wrong answer is a lesson

- **First mistake →** the row becomes a **bug line**; the game shows the answer and explains *your*
  mistake. Fix a puzzle on the same concept to get safe again.
- **Second mistake →** game over, with a **study plan**: every concept missed, an AI summary of the
  run, and one tap to practise the weakest topic.
- **Practice mode:** no losing, more blocks in your weakest topic.

**Visual:** the BUILD / WARN / CRASH LEDs + `end-debrief-ai-phone.png` (new).

---

## Slide 11 — Live demo *(target 3:20; hard stop 3:45)*

**syntax.screepai.moe** · *Scan to join the class* → [room QR, shown live on the projector]

1. **Live classroom:** the teacher sees *why* the class is wrong, live.
2. **Any code → verified puzzles:** paste a program, get four puzzles.
3. **Misaki explains, never grades:** "Vì sao?" after a wrong prediction.

**Visual:** this slide is mostly a backdrop: the demo runs in the browser. Put
`classroom-dashboard-desktop.png` behind the text and embed `demo-fallback.mp4` (hidden, play only
if the network fails).

Prepare the three real browser tabs with the home-screen shortcuts `Ctrl+Alt+1` (classroom setup),
`Ctrl+Alt+2` (code editor), `Ctrl+Alt+3` (r3 practice/prediction). Switch with the browser's `Ctrl+1/2/3`.
The timed actions and the eight-second waiting limit are in the speaking script. No judge-demo button
or mock setup is used. Keep PvP, ranked play and the skill map for Q&A.

---

## Slide 12 — Technology

- **Frontend:** HTML, CSS, JavaScript, no framework; phone to projector.
- **Backend:** Python + FastAPI.
- **Validator:** whitelist of beginner Python, step/time/output limits, named error types, line trace.
- **Puzzle bank:** 16 templates → **559 verified puzzles**; every wrong option is proven wrong by running it.
- **Pasted code:** runs in an **isolated sandbox process** (time, 3 s CPU, 256 MB memory limits).
- **Misaki, AI tutor:** explains only, capped per day and per visitor, hand-written fallback.
- **Misaki, AI opponent:** plans her moves with a search algorithm on the server; 4 levels.
- **Ranked play is server-verified:** the phone sends only its moves; the server replays the game and computes the score.
- **More than 400 automated tests.**

**Visual:** architecture strip: Phone/Browser → FastAPI → Validator → SQLite bank; side boxes
"Sandbox (pasted code)", "Misaki · tutor (explains only)" with a dashed "hand-written fallback" arrow,
and "Misaki · opponent (search AI)" next to a "Live 1v1 (WebSocket)" box.

---

## Slide 13 — Business potential

1. **Free for students, cheap to run:** puzzles are generated once in advance; AI is optional and capped.
2. **Classroom package for schools, already built:** live class dashboard showing which concepts and
   which mistakes the class struggles with, and practice generated from the lecturer's own code.
3. **Easy to reach and to scale:** a QR code in class; new topics are new template files, not new code.

**Visual:** `classroom-dashboard-desktop.png` (new) + `custom-result-desktop.png` (new), small.

---

## Slide 14 — Roadmap

- **Built:** ranked leaderboard and friend races (scores verified by server replay), random friendly
  names, skill map, and **real-time 1v1**: against a friend, or against **Misaki** at four levels you
  unlock one by one, with a training mode where she coaches you.
- **Next:** a pilot with real students to measure learning, using the classroom dashboard as the
  instrument. *(Learning gains are not claimed yet.)*
- **Later:** more Syntax Rows levels (Intermediate, Advanced); more languages (C#, JavaScript), which
  the validator design allows; more topics (lists, strings).

**Visual:** `skills-map-phone.png`, `leaderboard-phone.png` and `misaki-ladder-phone.png` (new), small.
Optionally `misaki-coach-phone.png` instead of the skill map.

> 1v1 is shown here, not demoed: the timed demo stays on the classroom. Only mention it aloud if it
> has been rehearsed (the script marks that line as cuttable).

---

## Slide 15 — Questions

**Questions?**

*Prepared answers are in the speaking script (slide 15 section), each with an owner.*

---

## Slide 16 — Thank you

**Thank you**
Try it now: **syntax.screepai.moe**

**Visual:** a QR code to the site (not the room).

---

## References

- Bennedsen, J. & Caspersen, M. E. (2007). *Failure rates in introductory programming.* ACM SIGCSE Bulletin, 39(2).
- Watson, C. & Li, F. W. B. (2014). *Failure rates in introductory programming revisited.* ITiCSE '14.
- Becker, B. A. et al. (2019). *Compiler error messages considered unhelpful.* ITiCSE-WGR '19.
- Ericson, B. J. et al. (2017). *Solving Parsons problems versus fixing and writing code.* Koli Calling '17 (supports the Parsons puzzle type).
