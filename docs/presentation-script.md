# Syntax Stack — speaking script (finals, v3.5, 10 minutes)

v2 is kept in `presentation-script.v2.md`. The talk is **10 minutes including a 3:30 live demo**
(hard stop at 3:45). Start in Chat with Misaki, launch both game modes from her chat, and have her
review the student's checked puzzle attempts. The live classroom closes the demo.
Cuong and Lam say "an AI tutor" until Lam introduces Misaki on slide 9.

| Presenter | Slides | Section | Time |
| --- | --- | --- | --- |
| **Bui Manh Cuong** | 1–5 | Opening, problem | 1:45 |
| **Tran Thuong Vu Lam** | 6–10 | Gap, solution, Misaki reveal, two modes | 2:00 |
| **Do Hong Minh** | 11–17 | Mistakes as lessons, **live demo**, technology, business, close | 6:00 (demo 3:30) |
| | | Buffer for transitions and network | 0:15 |

*Italics in brackets* are actions. **Bold** marks the words to stress. Lines starting with
"↳ Cut if short on time" can be dropped without breaking the flow. At about 130 words a minute, each
section's word count matches its time; don't add to it on the day.

## Before you walk on (checklist)

- [ ] Laptop and both phones on **one phone hotspot**, not the venue Wi-Fi.
- [ ] **Everything in English:** on the laptop and both phones, tap **EN** at the top right of the home
      screen (or open the site with `?lang=en`). It is remembered per browser; check each device once.
- [ ] Laptop tab 1: open [Chat with Misaki](https://syntax.screepai.moe/?demo=misaki&lang=en). Start a
      **New chat**, turn sound on, and select **EN** for her voice. Keep the three prompts below handy.
- [ ] Tab 2: from home press **Ctrl+Alt+1**, then **Open room**. Use **Player names: Random** (the
      default). Keep the teacher dashboard open and note the room code.
- [ ] Lam's phone: scan the QR, start playing, and stop at a Code Rescue puzzle before submitting.
      Write down the assigned nickname so Minh can point at the right row.
- [ ] Because the room uses random names, a judge who scans the QR cannot put anything rude on the
      projector. If something unexpected shows anyway, the row's **"Hide"** button removes it.
- [ ] Use **Ctrl+1** for Misaki and **Ctrl+2** for the teacher dashboard. The app's Ctrl+Alt shortcuts
      work from home with focus outside text fields. Rehearse with a real room and the production tutor.
- [ ] Rehearse the first Code Rescue clear and the Syntax Rows prediction explanation. Check that the
      generated puzzle set offers **Predict the output**, and that **Review with Misaki** can discuss
      your wrong and correct attempts. Check speech on the laptop before going on stage.
- [ ] Rehearse the correction: return `range(2)` to the tray, place `range(3)` in the same position,
      then run again. This is the learning payoff, not just an AI reply.
- [ ] Optional Q&A tab: **Ctrl+Alt+2** opens pasted-code puzzles. Keep the program below handy.
- [ ] Fallback: a labelled 20-second recording of a real Misaki review and the classroom update.
- [ ] Rehearse with a timer at least twice. The demo always runs long the first time.

Pasted-code program for Q&A (not in the timed demo):

```python
total = 0
for i in range(1, 5):
    total = total + i
print(total)
```

## Slide changes from v2 (for Stack.pdf)

The [slide content](presentation-content.md) follows the 17 slides in the finals deck, including
the separate Misaki reveal.

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

## Tran Thuong Vu Lam — slides 6 to 10 (2:00)

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

**Two: an AI tutor that explains a checked result.** *(Advance to the reveal.)*

### Slide 9 — Introducing Misaki

Introducing **Misaki, our AI tutor.** Our validator runs the supported exercises in a limited environment and
compares the output. Misaki gets the student's prediction and the actual execution trace, then
explains the mismatch. The student applies that explanation and runs again.

### Slide 10 — Two modes
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

## Do Hong Minh — slides 11 to 17 (6:00, including the 3:30 demo)

### Slide 11 — One wrong answer is a lesson (0:45)
Thank you, Lam. Code Rescue has one strict rule: **one mistake per game**. That makes students stop
guessing and read the code.

Your first mistake doesn't just say "wrong". The row becomes a **bug line**, and the game shows the
answer and **explains your exact mistake**. Tap the bug line for a puzzle on the same concept with
different numbers. Get it right and you're safe again. A second mistake ends the game with a **study
plan** of everything you missed.

↳ Cut if short on time: Practice mode removes losing entirely and gives you more blocks in your weakest
topic.

### Slide 12 — Live demo (target 3:30, hard stop 3:45)

Before the presentation, clear Syntax Rows Levels 1 and 2 in the presenter’s browser profile to
unlock Level 3. Start on the English homepage and press **Ctrl+Alt+M** to open the prepared chat.
Paste the three prompts below as written.

| Clock | Action | Evidence to point at |
| --- | --- | --- |
| 0:00–0:45 | Open Code Rescue from chat and clear one locked line. | Solving a Python puzzle unlocks the line. |
| 0:45–1:50 | Open Syntax Rows Level 3, run a wrong prediction, ask **Why?**, and fix the loop. | The trace shows what ran, and the learner makes the correction. |
| 1:50–2:55 | Generate a loop puzzle, submit a wrong answer and then the right one, and click **Review with Misaki**. | Misaki explains both server-checked attempts. |
| 2:55–3:30 | Switch to the teacher tab. Lam answers the prepared classroom puzzle wrong. | The dashboard updates with the student's result and the class mistake breakdown. |

**1. Launch Code Rescue.** Paste this prompt into chat.

> Start a beginner Code Rescue run. I want to practice Python loops.

Click Misaki's activity button. Fill one line, solve the Python puzzle that locks it, and show the
line clearing. Return home and reopen **Chat with Misaki** in the same tab.

**2. Build, predict, and correct in Syntax Rows.** Paste the next prompt.

> Now open Syntax Rows Level 3, Count to three. I want to build a loop with code tiles and predict its output.

Build `for i in range(2):` with `print(i)` indented underneath. Predict `0`, `1`, and `2` on separate
lines. Run it, show the trace stopping at `1`, then click **Why?** for Misaki's explanation.
Replace `range(2)` with `range(3)` and run again. Return to the chat.

**3. Generate a puzzle and review both attempts.** Paste the final prompt.

> Make a beginner Python loop puzzle set. Use a short for loop with range(1, 4), and let me predict the output before you explain it.

Click **Make puzzles** and open **Predict the output**. Submit a wrong answer, then select the
output with `1`, `2`, and `3` on separate lines. Click **Review with Misaki**. When the validator
confirms that sequence, Misaki plays the prepared review. Keep **Try a follow-up** for Q&A because
it uses the live tutor.

**4. Show the live classroom.** Press **Ctrl+2** and cue Lam to submit a wrong answer. Point to the
student's result and **Most common mistakes** as the dashboard updates. Keep the QR code visible
for anyone who wants to join.

> “Misaki helps a student understand their own mistake. The classroom dashboard helps the teacher see which mistakes the class needs to work on.”

**Timing rules.** Save duels, ranked play, pasted-code generation, and the skill map for Q&A. If a
tutor response takes more than eight seconds, use the labelled recording and keep moving. Identify
authored replies as fallbacks if they appear. Use the 15-second talk buffer if needed and stop
at **3:45**.

### Slide 13 — Technology (0:30)
In one breath: plain HTML, CSS and JavaScript on the front, Python and FastAPI on the back. The
**validator** parses code, blocks anything outside a beginner whitelist, runs it with step and time
limits, and names the error. **559 puzzles** are generated from templates, and every wrong option is
**proven wrong** by running it. More than 400 automated tests protect all of it.

### Slide 14 — Business potential (0:45)
**Free for students**, cheap to run: puzzles are generated once, in advance, and Misaki, the AI tutor, is capped
with free hand-written fallbacks.

And the paid part is no longer an idea. You just saw the live classroom dashboard alongside Misaki's
student support. Lecturers can also generate verified practice from their own code. That's a
**classroom package for schools**, starting with BTEC FPT lecturers.

### Slide 15 — Roadmap (0:20)
Already built beyond the demo: a **ranked leaderboard** and **friend races**, where the server replays
every game, so a score can't be faked. Next: a **pilot with real students** to measure learning (we
don't claim it yet), and more languages like C# and JavaScript.

↳ Cut if short on time: Each player also has a **skill map** *(point at screenshot)*, sixteen skills
that light up as they master them.

↳ *(Only if 1v1 is rehearsed)* And a real-time **1v1 mode**: solve a lock and you send bug lines to your
opponent's board, against a friend or against **Misaki**, who can also coach you while you play.

### Slide 16 — Close and questions (0:10)
Syntax Stack keeps the feeling of a game people love, and puts **verified code** underneath it, so
every mistake becomes a lesson. Thank you. We'd be happy to take your questions.

### Slide 16 — Prepared answers

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
- **"Who or what is Misaki?"** (Minh) As the **tutor**, she uses **Google Gemini** to suggest
  activities, draft practice puzzles, and explain the learner's checked attempts. The validator checks
  the puzzles and decides whether answers are correct. As the **opponent**, she plans each move by
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
  a lock sends bug lines to the opponent, and the server runs both boards, so nobody can cheat. Bug
  lines drop on their own after four seconds and every lock has a time limit, so stalling never wins. When
  nobody else is online you play **Misaki**: four levels you unlock by beating the one before, and a
  training mode where she coaches you during the match. Players see their own progress by climbing
  her levels.

### Slide 17 — Thank you
Try it now at **syntax.screepai.moe**.
