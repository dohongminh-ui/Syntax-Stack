# Syntax Stack — presentation content (SERS template), v3.5 (finals)

Slide-by-slide content for the finals deck, matched one-to-one with the speaking script
`docs/presentation-script.md` (v3.5). The talk is **10 minutes including a 3:30 live demo** (hard stop 3:45), so the
deck uses 17 slides, including a separate Misaki reveal. The speakers carry the depth.
Each slide lists the **on-slide text**, a **visual**, and where the media comes from. Language: English,
like the template; the game has a VI | EN switch, and the deck and demo use English. v2 of this file is in git history.

**Theme: AI in studying.** Misaki is central: the student makes an attempt, gets a contextual
explanation, applies it and practises. The teacher dashboard supports this story. Pasted-code
generation is optional Q&A material; it is verified program generation, not language-model tutoring.

> Before presenting: double-check the three cited figures on slide 4 against the original papers.

> **Wording rule for Misaki (read before editing any slide).** Misaki is one AI character with two
> jobs. As the **tutor** she explains checked attempts and creates practice puzzles using a language
> model and the game's validator. As the **opponent** she is a
> **search-based game AI**. On slides never write "trained", "learns", "machine learning" or "our own
> model" about her. "AI tutor", "AI opponent" and "plans her moves with a search algorithm" are all true.
> The vendor (Google Gemini) is not on the slides; it is in the spoken Q&A answer, ready if asked.

## Changes from v2

- **19 → 17 slides.** Section dividers were removed and “Learn from every run” moved into the live
  demo. Misaki has her own reveal slide.
- **Demo slide (12)** starts in Chat with Misaki, covers both game modes and a checked puzzle review,
  then shows the teacher dashboard updating. It carries the fallback recording.
- **New features shown:** live classroom with teacher dashboard, puzzles from pasted code (runs in a
  sandbox), skill map, AI explanation of wrong predictions, AI end-of-run debrief, "Read the code" bonus.
- **Business slide:** the classroom package is **built**, not "an idea, not validated".
- **Numbers updated:** 559 playable puzzles (706 generated forms with debug-only variants); tests
  "more than 400" (421 on 18 Nov; recount the day before).
- **Q&A updated:** "Isn't running user code dangerous?" no longer says players never type code (they
  can paste code now); the answer is the sandbox, with the limits tested on the live server.
- **Still not claimed:** learning gains. Framed as the pilot.
- **v3.2: Misaki.** The AI tutor and the 1v1 AI opponent are one character, Misaki. The 1v1 ladder
  and training mode move to “Built” on the roadmap.
- **v3.4: AI-in-studying focus.** Tutor → correction → training → teacher visibility. The language-model
  explanation and search-based game suggestions are identified separately. Pasted-code generation moves to Q&A.
- **v3.5** starts the live demo in Chat with Misaki and moves 1v1 training to Q&A.

## Screenshots to capture (new)

Capture at 1920×1080 for desktop shots and 390×844 for phone shots. Use **real** data, not mock
mode, for anything on the business or demo slide (mock screens are labelled "simulated" on screen).

| File (suggested, in `frontend/_screens/v5/`) | How to get it |
| --- | --- |
| `classroom-dashboard-desktop.png` | In production, have 3–4 people answer ~15 puzzles with a few deliberate mistakes, then capture the dashboard. Crop the test room's QR code if the slide will be projected. Show the working QR code from the live room. |
| `classroom-join-phone.png` | `/?room=<code>` on a phone in a random-names room: the "Your name: …" moment after tapping "Join room". |
| `leaderboard-phone.png` | `Leaderboard` after a few real ranked runs (not mock: mock is labelled "sample data"). |
| `custom-result-desktop.png` | `Make puzzles from code` → paste the demo program → capture the four puzzle cards. |
| `skills-map-phone.png` | Play a few Rescue runs first so the map has all four mastery levels, then `Skill Map`. |
| `predict-why-ai-phone.png` | Syntax Rows level 3, `range(2)`, predict 0 1 2, Run, tap "Why?" with the tutor on: the "MISAKI · AI TUTOR" card. |
| `misaki-review-desktop.png` | Generate a loop puzzle in chat, submit an incorrect and a correct prediction, then click **Review with Misaki**. Capture the review and Live2D model. |
| `misaki-ladder-phone.png` | `1v1 Duel` → "Play against Misaki" after beating level 1, so one level shows unlocked and two locked. |
| `misaki-coach-phone.png` | A training match ("Practice with Misaki") with her coach bubble visible and a "Suggest a move" suggestion outlined on the board. |
| `end-debrief-ai-phone.png` | Lose a Rescue run with 2 mistakes, capture the "Summary" block. |
| `demo-fallback.mp4` | Labelled 20-second recording of a real Misaki review and the classroom dashboard updating. |

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

**An AI tutor helps a student understand a mistake and try again.**

- **AI in studying:** an explanation of the student's actual attempt, followed by a correction they make.
- The practice environment is a Python block-puzzle game; a validator checks the program's output.
- For BTEC FPT students and anyone writing their first lines of Python. Learning gains are a pilot question.

**Visual:** the student's code and checked output, with the tutor card's text but **not** Misaki's name
or portrait (crop or blur the "MISAKI" label; she is revealed on slide 9).

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
| **AI chatbots / AI mentors** | ✓ | ✗ illusion of understanding |
| Casual puzzle games | ✓ | ✗ teach nothing |
| **Syntax Stack** | ✓ | ✓ **verified by running the code** |

**Visual:** the table, or the 2×2 (Fun ↔ Not fun / Verified ↔ None) with Syntax Stack alone in the
"fun + verified" corner.

---

## Slide 8 — Our solution

1. **The board is the program.** Rows are lines; the column is the indentation.
2. **An AI tutor explains the student's attempt.** The language-model tutor gets the prediction and
   execution trace after the validator checks the output. The student makes the correction and tests it
   again. AI explanations are labelled; authored fallbacks are identified separately.
3. **No time pressure.** Thinking slowly is allowed.

**Visual:** numbered-circle layout (SERS slide 9). Advance to the reveal after point 2.

---

## Slide 9 — Introducing Misaki

**Introducing Misaki, our AI tutor**

She opens practice, writes puzzles the game checks, and explains the learner's attempts.

**Visual:** keep the Misaki keycaps and show one checked reply. The presenter can mention that she
reads her replies in Vietnamese, English, or Japanese.

---

## Slide 10 — Two modes

| | **Code Rescue** | **Syntax Rows** |
| --- | --- | --- |
| Blocks | Shapes coloured by topic | Real code tiles |
| Row clears when… | You solve a code puzzle | Your program runs correctly |
| Mistakes | One mistake = warning, two = crash | Unlimited retries |
| Trains | Reading & recognising code | Writing code |
| Misaki | Sums up your run, names the topic you missed most | Explains a wrong prediction, answers your explanation |

- 4 topics: Variables · Conditions · Loops · Functions
- 4 puzzle types: Fill the blank · Predict output · Reorder lines (Parsons) · Find the bug

**Visual:** `frontend/_screens/v3/rescue-board-desktop.png` and `frontend/_screens/v4/trace-open-desktop.png`.

---

## Slide 11 — One wrong answer is a lesson

- **First mistake →** the row becomes a **bug line**; the game shows the answer and explains *your*
  mistake. Fix a puzzle on the same concept to get safe again.
- **Second mistake →** game over, with a **study plan**: every concept missed, an AI summary of the
  run, and one tap to practise the weakest topic.
- **Practice mode:** no losing, more blocks in your weakest topic.

**Visual:** the BUILD / WARN / CRASH LEDs + `end-debrief-ai-phone.png` (new).

---

## Slide 12 — Live demo *(target 3:30, hard stop 3:45)*

**AI that helps the student take the next step** · **syntax.screepai.moe**

1. **Start in Chat with Misaki** and launch Code Rescue and Syntax Rows.
2. **Try, correct, and review** with a puzzle Misaki writes and the game checks.
3. **See the class's mistakes live** on the teacher dashboard.

**Visual:** this slide is mostly a backdrop: the demo runs in the browser. Put
`misaki-review-desktop.png` and `classroom-dashboard-desktop.png` behind the text. Keep the
labelled `demo-fallback.mp4` ready if the network fails.

Prepare two tabs with [Chat with Misaki](https://syntax.screepai.moe/?demo=misaki&lang=en) first and
the open teacher dashboard second. Use `Ctrl+Alt+1` from home to set up the classroom, and cue a
teammate to submit one answer after the tab switch. The [speaking script](presentation-script.md)
contains the exact prompts, timing, and fallback. Keep duels, ranked play, pasted-code puzzles, and
the skill map for Q&A.

---

## Slide 13 — Technology

- **Frontend:** HTML, CSS, JavaScript, no framework; phone to projector.
- **Backend:** Python + FastAPI.
- **Validator:** whitelist of beginner Python, step/time/output limits, named error types, line trace.
- **Puzzle bank:** 16 templates → **559 verified puzzles**; every wrong option is proven wrong by running it.
- **Pasted code:** runs in an **isolated sandbox process** (time, 3 s CPU, 256 MB memory limits).
- **Misaki, AI tutor:** proposes activities, writes verified practice, and explains checked attempts. Usage is capped with authored fallbacks.
- **Misaki, AI opponent:** plans her moves with a search algorithm on the server; 4 levels.
- **Ranked play is server-verified:** the phone sends only its moves; the server replays the game and computes the score.
- **More than 400 automated tests.**

**Visual:** architecture strip: Phone/Browser → FastAPI → Validator → SQLite bank; side boxes
"Sandbox (pasted and Misaki-written code)", "Misaki · tutor" with a dashed "authored fallback" arrow,
and "Misaki · opponent (search AI)" next to a "Live 1v1 (WebSocket)" box.

---

## Slide 14 — Business potential

1. **Free for students, cheap to run:** puzzles are generated once in advance; AI is optional and capped.
2. **Classroom package for schools, already built:** live class dashboard showing which concepts and
   which mistakes the class struggles with, and practice generated from the lecturer's own code.
3. **Easy to reach and to scale:** a QR code in class; new topics are new template files, not new code.

**Visual:** `classroom-dashboard-desktop.png` (new) + `custom-result-desktop.png` (new), small.

---

## Slide 15 — Roadmap

- **Built:** ranked leaderboard and friend races (scores verified by server replay), random friendly
  names, skill map, and **real-time 1v1**: against a friend, or against **Misaki** at four levels you
  unlock one by one, with a training mode where she coaches you.
- **Next:** a pilot with real students to measure learning, using the classroom dashboard as the
  instrument. *(Learning gains are not claimed yet.)*
- **Later:** more Syntax Rows levels (Intermediate, Advanced); more languages (C#, JavaScript), which
  the validator design allows; more topics (lists, strings).

**Visual:** `skills-map-phone.png`, `leaderboard-phone.png` and `misaki-ladder-phone.png` (new), small.
Optionally `misaki-coach-phone.png` instead of the skill map.

> Mention the competition features here. Keep 1v1 training and ladder progression for Q&A.

---

## Slide 16 — Questions

**Questions?**

*Prepared answers are in the speaking script (slide 16 section), each with an owner.*

---

## Slide 17 — Thank you

**Thank you**
Try it now: **syntax.screepai.moe**

**Visual:** a QR code to the site (not the room).

---

## References

- Bennedsen, J. & Caspersen, M. E. (2007). *Failure rates in introductory programming.* ACM SIGCSE Bulletin, 39(2).
- Watson, C. & Li, F. W. B. (2014). *Failure rates in introductory programming revisited.* ITiCSE '14.
- Becker, B. A. et al. (2019). *Compiler error messages considered unhelpful.* ITiCSE-WGR '19.
- Ericson, B. J. et al. (2017). *Solving Parsons problems versus fixing and writing code.* Koli Calling '17 (supports the Parsons puzzle type).
