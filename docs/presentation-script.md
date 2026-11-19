# Syntax Stack — speaking script (finals, v3.4, 10 minutes)

v2 is kept in `presentation-script.v2.md`. The talk is **10 minutes including a 3:20 live demo**
(hard stop at 3:45). The theme is **AI in studying**: Misaki explains a specific mistake, the student
applies the explanation, then Misaki supports practice. The classroom closes the learning story.
**Misaki is not named before slide 8**: Cuong and Lam say "an AI tutor" until Lam's reveal,
"Introducing Misaki, our AI tutor", so her name lands as a moment.

| Presenter | Slides | Section | Time |
| --- | --- | --- | --- |
| **Bui Manh Cuong** | 1–5 | Opening, problem | 1:45 |
| **Tran Thuong Vu Lam** | 6–9 | Gap, solution, two modes | 2:00 |
| **Do Hong Minh** | 10–16 | Mistakes as lessons, **live demo**, technology, business, close | 5:50 (demo 3:20) |
| | | Buffer for transitions and network | 0:25 |

*Italics in brackets* are actions. **Bold** marks the words to stress. Lines starting with
"↳ Cut if short on time" can be dropped without breaking the flow. At about 130 words a minute, each
section's word count matches its time; don't add to it on the day.

## Before you walk on (checklist)

- [ ] Laptop and both phones on **one phone hotspot**, not the venue Wi-Fi.
- [ ] Laptop tab 1: from home press **Ctrl+Alt+3**. This opens the real r3 practice board, "Đếm đến ba",
      with `range(2)` and `print(i)` placed and prediction expanded. Leave it **unrun** and prediction empty.
- [ ] Tab 2: from home press **Ctrl+Alt+4**. Misaki level 1 and **Luyện tập cùng Misaki** are selected.
      Use **Chọn tên** to save a generated nickname before presenting. Leave the menu open; **do not start
      the match until this demo segment**, so it cannot finish while the tutor is on screen.
- [ ] Tab 3: from home press **Ctrl+Alt+1**, then **Mở phòng**. Have the real classroom already open
      with **Tên người chơi: Ngẫu nhiên** (the default), browser in fullscreen, on the projector. Note
      the room code.
- [ ] Cuong's and Lam's phones: **already joined the room**, game started, sitting on a board where a row
      is about to fill with **coral (loops)** blocks. Each phone gets a random name (e.g. "Cáo Nhanh 17"):
      **write both names down** so Minh can point at the right row.
- [ ] Because the room uses random names, a judge who scans the QR cannot put anything rude on the
      projector. If something unexpected shows anyway, the row's **"Ẩn"** button removes it.
- [ ] Use the browser's **Ctrl+1 / Ctrl+2 / Ctrl+3** to switch tabs on stage. The app's Ctrl+Alt shortcuts
      only work from home and outside text fields. No judge-demo menu, mock data or fake scores.
- [ ] Rehearse the exact wrong prediction and **Vì sao?** on the production tutor; check that the
      **MISAKI · GIA SƯ AI** card appears. A hand-written fallback does not demonstrate the language model.
      Keep a clearly labelled recording of a real AI response; allow at most **8 seconds** of visible waiting.
- [ ] Rehearse the correction: return `range(2)` to the tray, place `range(3)` in the same position,
      then run again. This is the learning payoff, not just an AI reply.
- [ ] Optional Q&A tab 4: **Ctrl+Alt+2** opens pasted-code puzzles. Keep the program below on the clipboard.
- [ ] Fallback: a 20-second screen recording of the demo on the demo slide, plus screenshots.
- [ ] Rehearse with a timer at least twice. The demo always runs long the first time.

Pasted-code program for Q&A (not in the timed demo):

```python
tong = 0
for i in range(1, 5):
    tong = tong + i
print(tong)
```

## Slide changes from v2 (for Stack.pdf)

The full slide-by-slide content is in `docs/presentation-content.md` (v3.4, 16 slides); slide numbers
below and in the headings match it.

- Merge v2 slides 4–6 into **two** problem slides; keep the one-in-three pass-rate chart.
- v2 slide 12 ("Learn from every run") becomes part of the demo; drop it as a separate slide.
- New **demo slide** (fallback media: screen recording + classroom dashboard screenshot).
- Business slide: replace "a classroom package … could become a paid plan" with the dashboard
  screenshot: it's now built, not an idea.
- Update the numbers everywhere: **559 playable puzzles** (706 generated forms including debug-only
  variants), **"more than 400 automated tests"** (421 on 18 Nov; recount the day before with
  `.venv\Scripts\python -m pytest -q` and use the real number).
- Skill map: one screenshot on the business or roadmap slide; it is not demoed live.

---

## Bui Manh Cuong — slides 1 to 5 (1:45)

### Slide 1 — Title
Good morning. We're team **Le Rouge** from BTEC FPT, class SE08301, supervised by Ms. Ngo Thi Mai Loan.
I'm Bui Manh Cuong, with Tran Thuong Vu Lam and Do Hong Minh. Our project is **Syntax Stack**.

### Slide 2 — Table of contents
Problem, the gap, **our solution and a live demo**, with a classroom you can join from your phone.

### Slide 3 — Project introduction
Our theme is **AI in studying**. Syntax Stack is a Python-learning game with an **AI tutor** that
explains a student's specific mistake, so they can try again with understanding.

The blocks are Python code: students arrange a program, predict its output and test their thinking.
A validator checks the result. The tutor uses that checked context to explain why it happened.
The student still has to make the correction. That's the learning loop we will show.

### Slides 4–5 — Hard first step; feedback that doesn't teach
In introductory programming courses, **about one in three students fails**: Bennedsen and Caspersen
in 2007, Watson and Li in 2014.

A beginner does **three jobs at once**: syntax, order and logic. When the program fails, they **can't
tell which one went wrong**. And the feedback doesn't help: error messages are written for experts,
and practice sites either say "wrong" or show the whole answer. Neither one teaches.

*(Hand-off)* So what should a solution do? Lam.

---

## Tran Thuong Vu Lam — slides 6 to 9 (2:00)

### Slide 6 — What a solution must do
Thank you, Cuong. We set two requirements. Practice must be **short and low-stakes**: a few minutes on a
phone. And after a mistake, the learner must see **which line** is wrong, **what kind** of error it is,
and **hints that reveal a little at a time**.

### Slide 7 — The gap
Online judges like LeetCode are built for people who can already code. Video courses are passive.
Casual games are engaging but teach nothing.

An AI chatbot can give a student a complete answer before they try. Reading a good explanation feels like
understanding, but the student never tested their own thinking: an **illusion of understanding**.
We want AI to respond **after a real attempt**, using the student's code and the result of running it.
That is the job we gave our AI tutor.

### Slide 8 — Our solution
**One: the board is the program.** Each row is a line; the column where it starts is the indentation.
You can *see* that `print` is inside the loop.

**Two: an AI tutor that explains a checked result.** *(Pause; click to reveal her.)* Introducing
**Misaki, our AI tutor.** Our validator runs the supported exercises in a limited environment and
compares the output. Misaki gets the student's prediction and the actual execution trace, then
explains the mismatch. The student applies that explanation and runs again.

### Slide 9 — Two modes
**Code Rescue** trains recognition. Blocks are coloured by topic: variables, conditions, loops,
functions. A full row **locks** and becomes a puzzle on that topic: fill the blank, predict the output,
reorder lines, or find the bug.

**Syntax Rows** trains writing: you build a program from code tiles and press Run, with unlimited
retries and distractor tiles to keep you honest.

**Misaki is in both.** In Syntax Rows she explains a wrong output prediction and answers your own
explanation of the code. In Code Rescue she sums up your run and names the topic you missed most.

↳ Cut if short on time: The four puzzle types come from research. Parsons problems, reordering lines,
give the same learning gains as writing code from scratch in less time (Ericson and colleagues).

*(Hand-off)* So what happens when a student gets it wrong? Minh.

---

## Do Hong Minh — slides 10 to 16 (5:50, including the 3:20 demo)

### Slide 10 — One wrong answer is a lesson (0:45)
Thank you, Lam. Code Rescue has one strict rule: **one mistake per game**. That makes students stop
guessing and read the code.

Your first mistake doesn't just say "wrong". The row becomes a **bug line**, and the game shows the
answer and **explains your exact mistake**. Tap the bug line for a puzzle on the same concept with
different numbers. Get it right and you're safe again. A second mistake ends the game with a **study
plan** of everything you missed.

↳ Cut if short on time: Practice mode removes losing entirely and gives you more blocks in your weakest
topic.

### Slide 11 — Live demo (target 3:20, hard stop 3:45)

| Clock | Action | Evidence to point at |
| --- | --- | --- |
| 0:00–0:15 | Tab 1: bring Misaki back beside the prepared r3 exercise. | A specific student task, not an open-ended chatbot. |
| 0:15–1:35 | Predict `0`, `1`, `2`, run, tap **Vì sao?**, then replace `range(2)` with `range(3)` and run again. | Checked mismatch → labelled AI explanation → the student's correction passes. |
| 1:35–2:35 | Ctrl+2: start the prepared level-1 training match; after countdown tap **Gợi ý nước đi** and place one suggested piece. | Misaki as an opponent, a legal highlighted suggestion and its reason. |
| 2:35–3:10 | Ctrl+3: Lam answers the prepared classroom puzzle wrong. | Teacher sees the actual named mistake; briefly invite QR joins without waiting. |
| 3:10–3:20 | Connect the three beats. | AI explanation, guided practice and a teacher who can still see the class. |

**Misaki, the tutor.** Lam introduced **Misaki**; let's see her at work. I predict this loop prints 0, 1, 2.
*(Run.)* It prints 0, 1. The validator has checked the mismatch. I ask **Vì sao?**.
*(Point at the AI card.)* Misaki explains using my prediction and the program's execution trace:
`range(2)` stops before 2. She has the context of my actual attempt.
*(Replace the range tile and run.)* I make the correction myself. Now it passes.
**The explanation leads to another attempt**, not just an answer to copy.

**Misaki, the practice partner.** *(Ctrl+2, start training, wait for countdown.)* Here Misaki is also
an AI opponent. In training I can ask **Gợi ý nước đi**. *(Tap and point at the highlighted cells and reason;
place that piece.)* The suggestion helps me make a move while I stay in control.
Her game moves and suggestions use **search**, not the tutor's language model; the event-coaching
lines are authored. We use each technique for a different job.

**The teacher stays involved.** *(Ctrl+3; Lam answers wrong.)* AI support doesn't hide the student
from the lecturer. Here is Lam's mistake on the live classroom dashboard. These are server-checked
results, not an AI guess about the class. You can scan the QR to join too.

**Close.** Misaki explains, the student applies it and practises, and the teacher sees where help
is still needed. That is **AI supporting studying**.

**Timing rules:** don't wait for audience joins or a match result. Pasted-code generation, ranked
play, the full ladder and the skill map are Q&A material. If the tutor has no result after 8 seconds,
show the clearly labelled recording of a real AI response and continue; don't repeatedly request it.
If only authored text appears, identify it as the fallback, not as AI. Don't claim measured learning gains.
Use the 25-second talk buffer if needed, then stop the demo at **3:45**.

### Slide 12 — Technology (0:30)
In one breath: plain HTML, CSS and JavaScript on the front, Python and FastAPI on the back. The
**validator** parses code, blocks anything outside a beginner whitelist, runs it with step and time
limits, and names the error. **559 puzzles** are generated from templates, and every wrong option is
**proven wrong** by running it. More than 400 automated tests protect all of it.

### Slide 13 — Business potential (0:45)
**Free for students**, cheap to run: puzzles are generated once, in advance, and Misaki, the AI tutor, is capped
with free hand-written fallbacks.

And the paid part is no longer an idea. You just saw the live classroom dashboard alongside Misaki's
student support. Lecturers can also generate verified practice from their own code. That's a
**classroom package for schools**, starting with BTEC FPT lecturers.

### Slide 14 — Roadmap (0:20)
Already built beyond the demo: a **ranked leaderboard** and **friend races**, where the server replays
every game, so a score can't be faked. Next: a **pilot with real students** to measure learning (we
don't claim it yet), and more languages like C# and JavaScript.

↳ Cut if short on time: Each player also has a **skill map** *(point at screenshot)*, sixteen skills
that light up as they master them.

↳ *(Only if 1v1 is rehearsed)* And a real-time **1v1 mode**: solve a lock and you send bug lines to your
opponent's board, against a friend or against **Misaki**, who can also coach you while you play.

### Slide 15 — Close and questions (0:10)
Syntax Stack keeps the feeling of a game people love, and puts **verified code** underneath it, so
every mistake becomes a lesson. Thank you. We'd be happy to take your questions.

### Slide 15 — Prepared answers

- **"Why not let AI grade the code?"** (Lam) AI can be confidently wrong. In a game where you only get one
  mistake, one wrong grade is unfair. The validator runs the code, so it's always right. AI explains.
- **"Isn't running pasted code on your server dangerous?"** (Minh) Pasted code never runs inside the
  server. It runs in a **separate process** with a time limit, a 3-second CPU limit and a 256 MB memory
  limit, after a whitelist check that blocks imports and file access. We tested infinite loops and
  memory bombs on the live server: they're stopped and the server keeps running. Game puzzles
  themselves only use code from our bank.
- **"Can students cheat the classroom data?"** (Minh) No. The phone sends only which option was chosen;
  the server checks it and names the mistake itself.
- **"What about privacy?"** (Minh) No accounts and no real names: players get random names, and a
  room's data is deleted 12 hours after it goes quiet. The teacher can delete it immediately.
- **"What if someone types a rude name?"** (Minh) On the leaderboard and in races they can't type a
  name at all: the server only accepts names from our generator. In class the default is random names
  too. If a lecturer chooses free names, a Vietnamese and English word filter applies and the teacher
  can hide any player from the screen with one tap.
- **"Isn't one mistake too harsh for beginners?"** (Minh) That's why Practice mode exists, and Syntax Rows
  has unlimited retries.
- **"How do you know students actually learn?"** (Minh) We don't claim it yet. The pilot measures it.
  The classroom data is exactly the tool we'll use to measure it.
- **"How is this different from Block Blast?"** (Cuong) We use the genre, not the game. Our blocks are
  code, and a row clears only when the code is correct.
- **"What does the AI cost?"** (Minh) It's capped per day and per visitor, cached, and the game works
  fully without it.
- **"Who or what is Misaki?"** (Minh) Misaki is our AI character, with two jobs, and we're precise
  about both. As the **tutor**, her explanations come from a large language model, **Google Gemini**,
  through our own prompts, limits and hand-written fallbacks; she only explains what the validator has
  already decided. As the **opponent**, she's a **search-based game AI**: she plans each move by
  searching the possible placements and scoring the boards, the same family of technique classic game
  engines use. She isn't trained on data and doesn't learn; her four levels differ in how far she
  searches and how fast she plays.
- **"Is Misaki machine learning?"** (Minh) No. The tutor uses an existing language model, and the
  opponent is a search algorithm. We chose search for the opponent because it's predictable, explainable
  and runs instantly on our server.
- **"Is there competition between players?"** (Minh) Yes: a ranked leaderboard and friend races. The
  phone never sends a score; it sends only its moves, and the server replays the whole game with the
  same rules and computes the score itself. We check that the server's copy of the rules matches the
  game exactly by replaying hundreds of games in both. A faked score is simply rejected.
- **"Can you play against each other live?"** (Minh) Yes, 1v1: both players get the same pieces, solving
  a lock sends bug lines to the opponent, and the server runs both boards, so nobody can cheat. When
  nobody else is online you play **Misaki**: four levels you unlock by beating the one before, and a
  training mode where she coaches you during the match. Players see their own progress by climbing
  her levels.

### Slide 16 — Thank you
Try it now at **syntax.screepai.moe**.
