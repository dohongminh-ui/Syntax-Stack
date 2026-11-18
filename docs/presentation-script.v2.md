# Syntax Stack — speaking script (Stack.pdf, v2)

The slides are deliberately minimal, so this script carries the depth: the *why* behind each point,
the concrete rules and the mechanisms the slide only names. The audience can read the slide; don't
read it back to them. Use the slide as the headline and talk about what sits under it.

| Presenter | Slides | Section | Target time |
| --- | --- | --- | --- |
| **Bui Manh Cuong** | 1–6 | Opening, Introduction, Context & Problem | ~3 min |
| **Tran Thuong Vu Lam** | 7–10 | Problem to Solve, Market Pain, Solution, Two modes | ~3 min 30 s |
| **Do Hong Minh** | 11–18 | Code Rescue flow, Learn from every run, Technology, Progress & Demo, Business, Roadmap, Q&A, Thank you | ~5 min + 1 min demo |

Slides 1–2 and 17–18 carry no "Presented by" label: here the first speaker opens and the team lead
closes. *Italics in brackets* are actions. **Bold** marks the words to stress. Lines starting with
"↳ Cut if short on time" can be dropped without breaking the flow.

---

## Bui Manh Cuong — slides 1 to 6

### Slide 1 — Title
Good morning, everyone. We are team **Le Rouge**, from BTEC FPT, class SE08301, supervised by
Ms. Ngo Thi Mai Loan. I'm Bui Manh Cuong, and with me are Tran Thuong Vu Lam and Do Hong Minh.
Our project is **Syntax Stack**.

### Slide 2 — Table of contents
We'll go from the problem, to the gap nobody fills, to our solution and how it's built, and finish with
where it goes next. Everything you'll hear about is already running: Minh will show it to you live.

### Slide 3 — 1. Project Introduction
Syntax Stack is a block-puzzle game in the browser where **the blocks are Python code**.

We chose the block-puzzle genre on purpose. Games like Block Blast are played by millions of people
because of one feeling: *"just one more round."* Short sessions, instant feedback, a satisfying moment
when a row clears. Learning to code has none of that. It's long, silent and frustrating. So we asked:
**what if we kept the feeling, but made every block a piece of a real program?**

Two rules make it work. First, **each row on the board is one line of code**, read top to bottom, so
the board *is* the program. Second, **a full row is not enough**: a row only clears when our validator
has actually run the code and confirmed it's correct. You can't fill the board by luck; you have to
write something that works.

Our first users are BTEC FPT students in their first programming module, and more broadly anyone
writing their first lines of Python.

### Slide 4 — 2. Context & Problem
To see why this matters, let's look at what learning to program is actually like for a beginner.

### Slide 5 — 2.1 Programming is a hard first step
The chart says **about one in three**. That figure comes from two well-known studies of introductory
programming courses, by Bennedsen and Caspersen in 2007 and by Watson and Li in 2014, who surveyed
courses across many countries and found average pass rates of around two-thirds. And that has stayed
stubborn for years, despite new tools and new languages.

Why is the first step so hard? Because a beginner is doing **three jobs at once**. They must get the
**syntax** right: the colon, the brackets, the indentation. They must put statements in the right
**order**. And they must solve the actual **logic** of the problem.

An experienced programmer handles the first two automatically and thinks only about the third. A
beginner has to think about all three, and here's the real problem: when the program fails, **they
can't tell which of the three went wrong**. Was it a typo? The wrong order? Or did they misunderstand
the problem? That's the "long silence": staring at code that doesn't work, with no idea where to start.

### Slide 6 — 2.2 Feedback that doesn't teach
And the feedback beginners get makes it worse.

**Error messages** are written for people who already understand them. Becker and colleagues
reviewed decades of research on this in 2019, and the conclusion is in the title of their paper:
compiler error messages are *considered unhelpful*. Think of a student who forgets one colon and gets
"SyntaxError: expected ':'" pointing at a line they think is fine.

**Practice websites** usually give one of two responses: "Wrong answer", which tells you nothing, or
the full solution, which tells you everything. Neither is teaching. Teaching lives in between: a nudge
that lets you find the mistake yourself.

And the result is predictable: students lose momentum, copy answers to get past the exercise, or wait
for the lecturer, who can't sit next to forty students at once.

*(Hand-off)* So what exactly should a solution do? Vu Lam.

---

## Tran Thuong Vu Lam — slides 7 to 10

### Slide 7 — 2.3 Problem to Solve
Thank you, Cuong.

From that, we set ourselves two requirements.

The first is about **pressure**. Practice has to be **short and low-stakes**: a few minutes, on a
phone, between classes, so a mistake feels like part of the game, not a failed exam.

The second is about **feedback**, and we made it measurable. After a mistake, the learner must see three
things: **which line** is wrong; **what kind** of error it is (a missing colon, wrong indentation,
wrong order, or a program that runs but prints the wrong thing); and **hints that reveal a little at
a time**, so they still do the thinking. If our game can't point to the line and name the error type,
we haven't solved the problem.

### Slide 8 — 3. Market Pain – The Gap
We looked at what students use today, and each option fails one of those two requirements.

**Online judges** like LeetCode and HackerRank are excellent, but for people who can already code.
You submit a whole program, it runs against hidden tests, and you get pass or fail. For a beginner,
"failed test 3 of 10" is the same silence Cuong described.

**Video courses** explain well, but they're passive. Watching someone type a loop doesn't build the
skill of typing one, just like watching football doesn't make you a player.

**AI chatbots** are the newest option, and they have two problems. They answer instantly and
completely, so the student skips the thinking. And they can be **confidently wrong**, which means
they can't be trusted to judge whether code is correct.

**Casual puzzle games** have exactly the engagement we want: people play them daily, for free, by
choice. But they teach nothing.

So the gap is clear: **the engagement of a casual game, with feedback you can trust, for complete
beginners.** Nobody sits in that corner yet.

### Slide 9 — 4. Our Solution (Syntax Stack)
Syntax Stack sits in that corner, and three design decisions put it there.

**One: the board is the program.** Rows are lines, and the **column** where the first block sits is
the **indentation level**. Indentation is one of the most common Python beginner errors, because it's
invisible. On our board it's physical: you can *see* that `print` is one column in, inside the loop.

**Two: a validator judges, not AI.** Every answer is checked by actually running the code in a safe,
limited environment and comparing the output with the expected result. That gives us something a
chatbot can't: the right/wrong decision is **always correct**. Hints come in three levels. Level one
reminds you of the **concept**, for example "`range()` stops before its end value." Level two points
in a **direction**: "Check the end value of your range." Level three is **specific**: "You need three
iterations, starting from 0." Each level gives away a little more, so the student chooses how much
help they take.

**Three: no time pressure.** There's no countdown anywhere in the game. Thinking slowly is allowed.
Our only pressure is a limited number of mistakes, and Minh will show why that's a teaching tool.

### Slide 10 — 4.1 Two game modes
We built two modes because beginners need two different things.

**Code Rescue** trains **recognition and reflexes**. It looks like a classic block puzzle: an 8 by 8
board and three shapes at a time. Each block's colour is a **topic**: green for variables, yellow for
conditions, coral for loops, blue for functions. When a row fills up, it **locks**, and you get a
puzzle on the topic of the colour that fills most of that row. That makes placement strategic:
if you're weak at loops, you can avoid building coral rows, but the board gets harder to manage. And
clearing several rows at once means a harder puzzle for more points: 100 for one row, up to 700 for
four, which comes with a two-part "boss" puzzle.

The four puzzle types are chosen from research. **Parsons problems**, where you reorder lines of code,
were shown by Ericson and colleagues to give the same learning gains as writing code from scratch, in
less time. **Fill the blank**, **predict the output** and **find the bug** each train a different skill:
writing, reading and debugging.

**Syntax Rows** trains **writing**. The blocks are real code tokens, sized like keyboard keys: a colon
is one unit wide, `print(i)` is three. You build the program row by row and press Run. If it's wrong,
nothing disappears and you try again, as many times as you want. Stars reward getting it right with
fewer runs and fewer hints. Each level also includes **distractor tiles**, like `range(2)` and `range(4)`
next to `range(3)`, so you have to understand, not just use every piece.

*(Hand-off)* So what happens when a student gets it wrong? Minh.

---

## Do Hong Minh — slides 11 to 18

### Slide 11 — 4.2 One wrong answer is a lesson
Thank you, Lam.

Code Rescue has one strict rule: **one answer per puzzle, and only one mistake per game**. That sounds
harsh, so let me explain why it's the core of the learning design.

When you know you only get one try, you **stop guessing**. You read the code properly. And you start
using hints honestly. A hint costs points: level one keeps 90% of the score, level two 75%, level
three 50%. So a hint is a trade you make consciously: safety for points.

*(Point at the levels.)* **Green, Stable**: full row, one puzzle, one answer. Get it right, the row
clears, and your **streak** multiplies the score: up to double at five correct answers in a row without
hints. Streaks also earn items, but items only help with *placing blocks*: a bomb, a shuffle, an undo.
**No item ever gives you an extra mistake.** The rule stays clear.

**Yellow, Warning**: your first mistake. The row doesn't disappear; it becomes a grey **bug line** that
stays on the board, taking up space, as a reminder. At that moment, and only then, the game shows you
the correct answer and **explains why your answer was wrong**. After a mistake, showing the answer is
no longer giving it away; it's the lesson.

Then you have a choice. Tap the bug line and you get a **Debug puzzle**: the *same concept*, but with
different numbers and names, so you can't just remember the answer, you have to have understood it.
Get it right: the bug line clears, you get **150 Redemption points**, and you're back to green with
your safety restored. Get it wrong, and the game is over. So the question the game asks is: *do you
really understand your mistake now?* That self-assessment is exactly the skill we want to build.

**Red, System Crash**: the game ends with an **error report**: every concept you missed, with the
explanation, and a button to practise that topic again. So even losing ends with a study plan.

And for students who find this too stressful, **Practice mode** removes losing entirely: three tries
per puzzle, bug lines vanish after a few turns, and the game quietly gives you **more blocks in your
weakest topic**, based on your recent mistakes.

### Slide 12 — 4.3 Learn from every run
These are real screens from Syntax Rows. *(Point left to right.)*

On the left, level 4, "Running total": add 1, 2 and 3 in a loop and print 6. This level hides a trap
we designed on purpose: if you indent the `print` one column, it goes *inside* the loop and prints
1, 3, 6 instead of 6. The validator doesn't just say "wrong"; it points at **that exact row**.

On the right, level 3, "Count to three", with a mistake: `range(2)`. The program prints 0, 1 instead of
0, 1, 2. The row is marked in red, the error type is **output mismatch**, and you can **step through
the program line by line**, watching `i` change, until you see the loop stop one step early.

In the middle, the level solved perfectly: three stars. But passing isn't the end. Three more
features turn a pass into understanding. **Predict the output**: before you run, you can write what
you think the program will print. **Twist**: after you pass, change one tile and see how the output
changes. And **Teach-back**: you explain your solution in your own words, and the AI tutor responds to
your explanation. Explaining something is one of the strongest ways to learn it.

### Slide 13 — 5. Applied Technology
Let me go one level deeper into how it's built, because the important parts are invisible.

The **frontend** is plain HTML, CSS and JavaScript, with no framework and no build step. That keeps it
light: it loads fast on a cheap phone on campus Wi-Fi. The whole interface follows one idea, a
**mechanical keyboard**. Every block is a keycap, the board is the plate, and placing code feels like
pressing keys.

The **backend** is Python with FastAPI.

The **validator** is the core, and it does four things. One: it parses the code into a **syntax tree**
before running anything. Two: it checks that tree against a **whitelist**. No imports, no file access,
no hidden tricks, only the Python a beginner needs. Three: it **runs** the code with hard limits on
steps, time and output, so an infinite loop can't freeze anything. Four: it **classifies** what went
wrong into a named error group, like missing colon, wrong indentation, wrong order or output mismatch,
and that group decides which hint you see.

The **puzzle bank** solves a problem every quiz game has: repetition. A long game needs 20 to 30
puzzles, and if you've seen them before, you remember answers instead of understanding. So we don't
write puzzles one by one; we write **templates**. Sixteen of them, four topics times four puzzle types.
Each template has parameters (numbers, variable names, operators) and a list of **common beginner
mistakes** that become the wrong options. From those, we generate **706 puzzles** in advance. Then, the
important part: every single puzzle is **run through the validator**. The correct answer must pass,
and **every wrong option must fail**. If two options could both be right, the puzzle is thrown away.
In a game where you only get one mistake, an ambiguous question would be unfair, so we guarantee there
are none.

Finally, the **AI tutor**. It receives the validator's diagnosis, never raw guesses, so it explains a
mistake the system has already confirmed. It **only explains; it never decides** right or wrong. And
it's built to fail safely: replies are cached, there's a daily usage limit to control cost, and if the
AI is slow, busy or unavailable, the game instantly falls back to our **hand-written hints**. The
student never sees an error, and the game always works.

### Slide 14 — 6. Current Progress & Demo
Everything I've described is built and deployed at **syntax.screepai.moe**.

Both modes are playable end to end, on phone and desktop. 706 verified puzzles across four topics and
three difficulty tiers. And **161 automated tests**, all passing, including a test that re-runs every
puzzle in the bank through the validator, so a broken puzzle can never reach a student.

Let me show you. *(Live demo, about 60 seconds.)*
1. *Open Syntax Rows, level 3, "Count to three".*
2. *Row 1: `for`, `i`, `in`, `range(2)`, `:`. Row 2, one column in: `print(i)`. Press Run.*
   "It printed 0, 1, but we need 0, 1, 2. Row 1 is marked, the error is output mismatch, and the first
   hint reminds me that `range()` stops **before** its end value."
3. *Swap `range(2)` for `range(3)`. Press Run.*
   "The rows clear from top to bottom, and the level is complete."

*(If the network fails: use the screenshots on this slide and slide 12 and narrate the same steps.)*

### Slide 15 — 7. Business Potential
Three reasons this can grow beyond a competition project.

**It's cheap to run and free to use.** A browser link, nothing to install, no expensive device. The
heavy work, generating and checking puzzles, happens once, in advance, not every time someone plays.
The only running cost that grows with users is the AI tutor, and that's capped by the daily limit and
the cache, with free hand-written hints behind it.

**The audience is large and easy to reach.** We start where we are: BTEC FPT students in introductory
programming, reachable through lecturers and coding clubs, with a QR code in class. Then high-school
and university beginners and self-learners.

**It scales through content, not code.** A new topic or a new set of puzzles is a new template file.
The generator and the validator do the rest, including the safety checks. The business model follows
from that: the core stays **free for students**, and a **classroom package**, with progress reports
showing lecturers which concepts their class struggles with, could become a paid plan for schools.

### Slide 16 — 8. Development Roadmap
**Short term**: a **pilot with 20 to 30 students**. We'll measure completion rate, number of retries
and hints used, and compare the two modes. That answers our biggest open question: does the
one-mistake rule make students think more carefully, or does it make them quit? We also keep
improving the AI tutor's explanations based on what students actually ask.

**Medium term**: more Syntax Rows levels at intermediate and advanced, plus accounts, progress
tracking and the **teacher dashboard**.

**Long term**: a classroom tool for BTEC and FPT lecturers, with more languages like C# and
JavaScript, which the validator design allows, and more topics like lists and strings.

### Slide 17 — Question Time
To sum up: Syntax Stack keeps the feeling of a game people already love, and puts real, verified code
underneath it, so every mistake becomes a lesson. We'd be happy to take your questions.

*Prepared answers:*
- **"Why not let AI grade the code?"** (Lam) AI can be confidently wrong. In a game where you only get
  one mistake, one wrong grade is unfair. The validator runs the code, so it's always right. AI explains.
- **"Isn't running student code dangerous?"** (Minh) Players never type free code; they assemble
  pieces from our bank. On top of that, the whitelist blocks imports and file access, and the limits
  stop infinite loops.
- **"Isn't one mistake too harsh for beginners?"** (Minh) That's why Practice mode exists, and why
  Syntax Rows has unlimited retries. The pilot will tell us which works better for which students.
- **"How is this different from Block Blast?"** (Cuong) We use the genre, not the game. Our blocks are
  code, and a row clears only when the code is correct.
- **"How do you know students actually learn?"** (Minh) We don't claim it yet. That's what the pilot
  measures: completion, retries and hints across the two modes.
- **"What does the AI cost?"** (Minh) It's capped by a daily limit and a cache, and the game works
  fully without it thanks to the hand-written hints.

### Slide 18 — Thank You
Thank you for listening. Try it yourself right now at **syntax.screepai.moe**.
