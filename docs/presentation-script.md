# Syntax Stack — speaking script (finals, v3, 10 minutes)

v2 is kept in `presentation-script.v2.md`. v3 cuts the talk to **10 minutes including a 3-minute live
demo**. Judges remember one strong moment, so the demo is one block, built around the live classroom.

| Presenter | Slides | Section | Time |
| --- | --- | --- | --- |
| **Bui Manh Cuong** | 1–5 | Opening, problem | 1:45 |
| **Tran Thuong Vu Lam** | 6–9 | Gap, solution, two modes | 2:00 |
| **Do Hong Minh** | 10–16 | Mistakes as lessons, **live demo**, technology, business, close | 5:30 (demo 3:00) |
| | | Buffer for transitions and network | 0:45 |

*Italics in brackets* are actions. **Bold** marks the words to stress. Lines starting with
"↳ Cut if short on time" can be dropped without breaking the flow. At about 130 words a minute, each
section's word count matches its time; don't add to it on the day.

## Before you walk on (checklist)

- [ ] Laptop and both phones on **one phone hotspot**, not the venue Wi-Fi.
- [ ] Laptop: **classroom room already open** on the teacher screen (`Lớp học trực tiếp` → `Mở phòng`),
      browser in fullscreen, on the projector. Note the room code.
- [ ] Cuong's and Lam's phones: **already joined the room** with nicknames, game started, sitting on a
      board where a row is about to fill with **coral (loops)** blocks.
- [ ] Laptop clipboard: the paste-code demo program (below). Second browser tab on `Tạo câu đố từ code`.
- [ ] Third tab: Syntax Rows level 3, "Đếm đến ba", with `range(2)` and `print(i)` already placed and
      "Dự đoán đầu ra" open.
- [ ] Fallback: a 20-second screen recording of the demo on the demo slide, plus screenshots.
- [ ] Rehearse with a timer at least twice. The demo always runs long the first time.

Paste-code demo program (keep it on the clipboard):

```python
tong = 0
for i in range(1, 5):
    tong = tong + i
print(tong)
```

## Slide changes from v2 (for Stack.pdf)

The full slide-by-slide content is in `docs/presentation-content.md` (v3, 16 slides); slide numbers
below and in the headings match it.

- Merge v2 slides 4–6 into **two** problem slides; keep the one-in-three pass-rate chart.
- v2 slide 12 ("Learn from every run") becomes part of the demo; drop it as a separate slide.
- New **demo slide** (fallback media: screen recording + classroom dashboard screenshot).
- Business slide: replace "a classroom package … could become a paid plan" with the dashboard
  screenshot: it's now built, not an idea.
- Update the numbers everywhere: **559 playable puzzles** (706 generated forms including debug-only
  variants), **"nearly 300 automated tests"** (297 today; recount the day before with
  `.venv\Scripts\python -m pytest -q` and use the real number).
- Skill map: one screenshot on the business or roadmap slide; it is not demoed live.

---

## Bui Manh Cuong — slides 1 to 5 (1:45)

### Slide 1 — Title
Good morning. We're team **Le Rouge** from BTEC FPT, class SE08301, supervised by Ms. Ngo Thi Mai Loan.
I'm Bui Manh Cuong, with Tran Thuong Vu Lam and Do Hong Minh. Our project is **Syntax Stack**.

### Slide 2 — Table of contents
Problem, the gap, our solution, then a live demo where **you can join in from your phone**.

### Slide 3 — Project introduction
Syntax Stack is a block-puzzle game in the browser where **the blocks are Python code**.

Block puzzles are played by millions because of one feeling: *"just one more round."* Learning to code
has none of that; it's long, silent and frustrating. So we kept the feeling and made **every block a
piece of a real program**. A row only clears when our validator has **run the code and confirmed it's
correct**. You can't win by luck.

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

And **AI chatbots** answer instantly and completely, so students skip the thinking, and they can be
**confidently wrong**, so they can't be trusted to judge code. Most teams here built an AI mentor.
We built something different.

### Slide 8 — Our solution
**One: the board is the program.** Each row is a line; the column where it starts is the indentation.
You can *see* that `print` is inside the loop.

**Two: a validator judges, AI only explains.** Every answer is checked by running the code in a safe,
limited environment. Right or wrong is **always correct**. AI is only allowed to explain a mistake the
validator has already confirmed.

### Slide 9 — Two modes
**Code Rescue** trains recognition. Blocks are coloured by topic: variables, conditions, loops,
functions. A full row **locks** and becomes a puzzle on that topic: fill the blank, predict the output,
reorder lines, or find the bug.

**Syntax Rows** trains writing: you build a program from code tiles and press Run, with unlimited
retries and distractor tiles to keep you honest.

↳ Cut if short on time: The four puzzle types come from research. Parsons problems, reordering lines,
give the same learning gains as writing code from scratch in less time (Ericson and colleagues).

*(Hand-off)* So what happens when a student gets it wrong? Minh.

---

## Do Hong Minh — slides 10 to 16 (5:30, including the 3:00 demo)

### Slide 10 — One wrong answer is a lesson (0:45)
Thank you, Lam. Code Rescue has one strict rule: **one mistake per game**. That makes students stop
guessing and read the code.

Your first mistake doesn't just say "wrong". The row becomes a **bug line**, and the game shows the
answer and **explains your exact mistake**. Tap the bug line for a puzzle on the same concept with
different numbers. Get it right and you're safe again. A second mistake ends the game with a **study
plan** of everything you missed.

↳ Cut if short on time: Practice mode removes losing entirely and gives you more blocks in your weakest
topic.

### Slide 11 — Live demo (3:00)
Everything is live at **syntax.screepai.moe**. *(Projector shows the classroom screen.)*

**1. Live classroom (1:30).** This is the teacher screen. Cuong and Lam are already in the room on their
phones. **Scan this QR code and you can join too.** No account, just a nickname.

*(Lam answers a loops puzzle wrong on purpose. Point at the heatmap.)*
Lam just made a mistake. Within two seconds, the **loops** cell on the class map turned red, and here's
**"Lỗi phổ biến nhất"**, the most common mistake in the room, by name: for example, "range() does not
include its end value".

This is what an AI mentor can't give a lecturer: a **reliable map of why the class is wrong**. Every
answer is checked and labelled by our validator on the server, so a phone can't fake it.

**2. Any code becomes practice (0:45).** *(Switch tab. Paste the program, press "Tạo câu đố".)*
A lecturer pastes any short program, and in under a second we get **four verified puzzles** from it:
predict, fix the bug, fill the blank, reorder. Every option was actually run. Pasted code runs in an
**isolated sandbox** with time, CPU and memory limits, so it can't harm the server.

**3. AI explains, never grades (0:45).** *(Switch tab: Syntax Rows, level 3.)*
I predict this prints 0, 1, 2 and press Run. *(Run.)* It prints 0, 1: my prediction was wrong. I tap
**"Vì sao?"** *(tap)* and the AI tutor explains **why**, using the validator's trace: `range(2)` stops
before 2. The validator decided; the AI only explained. If the AI is down, a hand-written explanation
appears instead.

*(If the network fails: play the recording on this slide and narrate the same three steps.)*

### Slide 12 — Technology (0:30)
In one breath: plain HTML, CSS and JavaScript on the front, Python and FastAPI on the back. The
**validator** parses code, blocks anything outside a beginner whitelist, runs it with step and time
limits, and names the error. **559 puzzles** are generated from templates, and every wrong option is
**proven wrong** by running it. Nearly 300 automated tests protect all of it.

### Slide 13 — Business potential (0:45)
**Free for students**, cheap to run: puzzles are generated once, in advance, and the AI tutor is capped
with free hand-written fallbacks.

And the paid part is no longer an idea. **You just used it**: a live classroom where a lecturer sees
which concepts the class struggles with, plus custom puzzles from the lecturer's own code. That's a
**classroom package for schools**, starting with BTEC FPT lecturers.

### Slide 14 — Roadmap (0:20)
Next: a **pilot with real students** to measure whether this actually improves learning (we don't
claim it yet), more Syntax Rows levels, and more languages like C# and JavaScript, which the validator
design allows.

↳ Cut if short on time: Each player also has a **skill map** *(point at screenshot)*, sixteen skills
that light up as they master them.

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
- **"What about privacy?"** (Minh) Nicknames only, no accounts, and a room's data is deleted 12 hours
  after it goes quiet. The teacher can delete it immediately.
- **"Isn't one mistake too harsh for beginners?"** (Minh) That's why Practice mode exists, and Syntax Rows
  has unlimited retries.
- **"How do you know students actually learn?"** (Minh) We don't claim it yet. The pilot measures it.
  The classroom data is exactly the tool we'll use to measure it.
- **"How is this different from Block Blast?"** (Cuong) We use the genre, not the game. Our blocks are
  code, and a row clears only when the code is correct.
- **"What does the AI cost?"** (Minh) It's capped per day and per visitor, cached, and the game works
  fully without it.
- *(Only if ranked play ships before the finals)* **"Is there competition between players?"** (Minh) Yes:
  a ranked leaderboard and friend races. The phone never sends a score; the server replays every move
  and computes it, so the board can't be faked.

### Slide 16 — Thank you
Try it now at **syntax.screepai.moe**.
