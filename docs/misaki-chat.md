# Chat with Misaki

Status: in development. This is the spec the feature is built from; sections marked *(built)* are checked in code.

A screen where the learner talks to Misaki, the game's AI character, drawn as a Live2D model. She asks
what is troubling them (a Python topic, a mistake that keeps coming back, being bored or stuck), then
either **recommends** something already in the game or **makes a puzzle**: she writes a short Python
program and the existing custom-puzzle pipeline turns it into verified Code Rescue puzzles.

The project principle still holds: **the validator decides, the AI explains.** Misaki never decides
whether code is correct. Every program she writes goes through `custom.create_set` (AST whitelist,
sandbox, generator) exactly like a pasted program, and every action she proposes is checked against a
fixed whitelist on the server.

Related: [ai-tutor.md](ai-tutor.md) (quota, fallback, n8n), [validator-and-safety.md](validator-and-safety.md),
[frontend.md](frontend.md), [pvp.md](pvp.md) (Misaki the character).

## 1. Scope

- **In:** Python and game troubles; light mood ("I'm bored", "this is hard", "I keep failing").
- **Out:** counselling. Anything that reads as a serious personal or safety issue gets a fixed, authored
  reply that points to a trusted adult or a helpline (section 5), with no AI call.
- Misaki only proposes things that exist in the stacking game: Code Rescue (rescue / practice, level,
  focus topic), Syntax Rows levels, practice by mistakes, the skill map, PvP training with Misaki, and
  custom puzzles she writes.

## 2. API

### `POST /api/misaki/chat`

Request:

```json
{
  "messages": [
    {"role": "misaki", "text": "Chào bạn! Hôm nay bạn đang vướng chỗ nào?"},
    {"role": "user", "text": "Mình hay sai vòng lặp range"}
  ],
  "context": {"level": "beginner", "weak_topics": ["loops"]}
}
```

- `messages`: 1 to 12 items, the last one has `role: "user"`. `role` is `user` or `misaki`, and `text`
  is 1 to 500 characters. The client keeps the history; the server stores nothing.
- `voice_language`: optional `"vi"`, `"en"`, or `"ja"` with `voice: true`. The voice selector in the chat
  header is saved in the browser. Written replies always use the game's language (`X-Lang`).
- `context` is optional and is a hint only. `level` is a `Level` and `weak_topics` holds 0 to 4 topics.
  It comes from the learner's own local mistake history.
- `context.puzzle_review`, when present, contains `set_id` and up to eight recent submissions to the last
  Misaki set the learner attempted. Each has `puzzle_id`, `option_id` or `order`, and the answer's `reveal`
  flag. The browser keeps these in the current tab's chat session. The server checks each submission
  against the stored puzzle and gives Misaki the verdict, the learner's choice, and the diagnosis.
  Verified solutions and prediction outputs enter the review after a correct or revealed attempt.

Response:

```json
{
  "text": "range(5) dừng trước 5 nên hay bị lệch một. Thử vài câu đố vòng lặp nhé?",
  "source": "ai",
  "mood": "thinking",
  "action": {"type": "make_puzzle", "topic": "loops", "idea": "range bắt đầu từ 1"}
}
```

- `source`: `ai`, `canned` (no AI, the rule-based reply in section 4) or `safety` (section 5).
- `mood`: one of `neutral`, `happy`, `excited`, `thinking`, `worried`, `sad`, `shy`, `dizzy`. Anything
  else becomes `neutral`.
- `text`: at most 600 characters, plain text, inline `code` spans allowed, URLs stripped.
- `action`: `null` for a `reply` tool call or exactly one of the shapes below for a game tool call.
  The server validates the tool and its arguments. Malformed calls or actions targeting a different
  topic from the learner's request use the authored fallback.

| `type` | Extra fields | Client does |
| --- | --- | --- |
| `rescue` | `mode`: `rescue` or `practice`; `level`: Level; `focus_topic`: topic or null | `startGame(...)` |
| `rows` | `level_id`: an existing Syntax Rows level id | `openLevel(id)` |
| `practice_tray` | none | `showPractice()` |
| `skills` | none | `openSkills()` |
| `pvp_training` | `misaki`: 1 to 4 | opens 1v1 with Misaki in training mode at that level |
| `make_puzzle` | `topic`: topic; `idea`: 0 to 200 characters | calls `POST /api/misaki/puzzle` |

The client shows the validated action as one keycap button under Misaki's bubble. A player click
starts the activity. The tool call supplies the action, and the app supplies the button label.

### `POST /api/misaki/puzzle`

Request: `{"topic": "loops", "idea": "range bắt đầu từ 1", "level": "beginner"}`. `idea` is 0 to 200
characters.

1. If the tutor is configured, ask the AI task `misaki_puzzle` for `{"code", "note"}`. `code` is a Python
   program of at most 15 lines, in the custom-puzzle subset, on `topic`.
2. Pass `code` to `custom.create_set(code, level, client)`. If the AI fails, or `create_set` raises
   (invalid code, timeout, no puzzle could be made), fall back to one of the authored programs for that
   topic (two per topic, in `backend/app/misaki.py`) and call `create_set` with it.
3. Response: `{"set": <create_set view>, "source": "ai" | "canned", "note": "<one line from Misaki>"}`.
   The client plays the set through the custom-puzzle screen.

After submitting an answer, the learner can choose **Review with Misaki** on the set screen to discuss
their work in chat. Follow-up messages use the same evidence. The review uses up to two recent
submissions per puzzle, including an earlier miss when the learner then gets it right.
The **Review with Misaki** and **Try a follow-up** buttons set `context.puzzle_request` to `review` and
`follow_up` respectively. **Try a follow-up** offers another puzzle on the last checked topic even
when the tutor is unavailable. For a typed request, Gemini can call `follow_up_puzzle` and suggest one
change to the previous example. The game supplies the topic and verifies the resulting code.

The `previous_action` field carries the offer from the immediately preceding Misaki turn. Gemini calls
`repeat_offer` when the learner accepts it in chat, and the game reuses the validated action. The
player clicks the button to start the activity.

In solo Code Rescue and Syntax Rows, **Ask Misaki** uses the current puzzle or board for hints and the
checked attempt for explanations. Code Rescue offers a related checked prediction after review and
features one practice topic in the run summary. Syntax Rows can compare a correct board with the
previous failed board and uses its existing one-tile challenge where available.

The custom-set rate limit (`custom.RATE_LIMIT`) still applies. A 429 is passed through, and Misaki
says so in her own words on the client.

### Listening to a reply

Misaki reads new chat replies aloud after the learner sends a message. The sound button in the
game header mutes her, and the speaker button on a reply stops or replays that clip. The chat response
carries an expiring playback ticket for `POST /api/misaki/voice`, which returns WAV audio. The server
sends Misaki's reply to Gemini 3.8 Flash-Lite TTS, which speaks Vietnamese, English, and Japanese with
the Leda voice. On a provider rate limit, speech falls back to Gemini 3.8 Flash TTS with Leda.
Voice calls share the tutor's quotas.

When the voice language differs from the game's language, the same chat tool call supplies a spoken
translation. The browser reveals the reply when playback starts. If audio fails or has not started
after 15 seconds, it shows the reply and cancels autoplay. Muted speech also leaves the text visible.
While audio plays, the current phrase is highlighted using estimated timing from the clip and transcript.

The browser estimates vowel shapes from the speech audio and blends the rig's mouth opening, form,
pucker and funnel during playback. The current expression takes over when playback ends. Sending
a new message stops the previous clip. The most recent clip can be replayed in the tab.
Publish the updated n8n workflow alongside the app to enable speech through the production webhook.

## 3. AI tasks (n8n)

Both tasks share the existing tutor client's quotas, two concurrency slots, and logging (`tutor.py`).
The workflow in `deploy/n8n-tutor.json` and the direct Gemini integration use the same prompts,
function declarations, and puzzle response schema. Tests keep them in sync. n8n is preferred when
both providers are configured. See [operations.md](operations.md).

- `misaki_chat`: Gemini must return one native function call. `reply` carries ordinary chat, and each
  game function carries Misaki's `text`, `mood`, and that activity's typed arguments. The workflow
  forwards the candidate's `function_calls` to the backend, which decodes the call and validates any
  proposed action. Puzzle review uses checked evidence. Publish the updated n8n workflow with the
  app release so n8n can return the native tool envelope.
- `misaki_puzzle`: system prompt = the editorial constraints the custom pipeline accepts (variables, if,
  for, simple functions, print, range, basic arithmetic; 2 to 15 lines; 4-space indent; deterministic;
  no input()). JSON schema `{code, note}`.

## 4. Without AI (canned Misaki)

When the tutor is not configured, busy or over quota, `misaki.py` answers with authored keyword rules
(Vietnamese and English, accent-insensitive). Topic words (`vòng lặp`, `loop`, `range`, `if`, `hàm`,
`function`, `biến`...) lead to a `make_puzzle` or a focused `rescue practice`. "chán" / "bored" leads to
`pvp_training`. "khó" / "stuck" / "sai hoài" leads to `practice_tray`. Anything else gets a friendly
question that lists what she can help with. The demo works fully offline this way, and `?mock=1` mirrors
it in `mock-api.js`.

## 5. Safety

- Before any AI call, the last user message is checked against an authored list of crisis phrases
  (Vietnamese and English, accent-insensitive: self-harm, suicide, abuse, being hurt, wanting to die...).
  On a match, the reply is fixed text: Misaki says she is glad they told her, that this is important and
  she is only a game character, and asks them to talk to a trusted adult or teacher now. Vietnamese adds
  *Tổng đài quốc gia bảo vệ trẻ em 111* (free, 24/7); English says "your local emergency number or a
  child helpline". `source: "safety"`, `mood: "worried"`, no action.
- The persona prompt repeats this rule for cases the list misses. It also says never to ask for
  personal information.
- Replies are plain text rendered as text nodes (never innerHTML). URLs are stripped server-side.
- No chat content is logged or stored, as with the tutor.
- The UI labels Misaki as AI ("Do AI tạo, có thể chưa chính xác"), as the tutor card does.

## 6. The Live2D model

The model is **DeepSeek-chan** (illustration and PSD: Kamiya Ryoko; Live2D rigging: 霓虹猫_NeonNeko),
distributed free by Kamiya Ryoko. Its terms forbid redistributing the complete model files and require
credit, so:

- The model files are **not committed**. `tools/setup_live2d.py <model folder>` copies them into
  `frontend/live2d/misaki/` (gitignored). It downscales the 4096px textures to 2048px, gives the
  expression and motion files ASCII names, and writes `misaki.model3.json` with Expressions and Motions
  registered.
- With the folder missing, the screen shows the existing Misaki keycap avatar. Nothing breaks.
- The chat screen always shows the credit line for the model under the stage.
- The creator has given permission for the site to serve the model. The model is still not in the public
  repository: it is copied to the server once into `/opt/stacks/syntax-stack/frontend/live2d/`, and
  `compose.yaml` mounts that folder read-only into the container. Deploys (`git reset`) leave the ignored
  folder alone, and the image never contains it.

Runtime: PixiJS + pixi-live2d-display (MIT, vendored in `frontend/vendor/`), plus Live2D Cubism Core
loaded from Live2D's official URL, which is allowed in the CSP by that exact path. They load lazily, only
when the chat screen opens and the model is present. The CSP never gains `'unsafe-eval'`.

Mood to model mapping:

| mood | expression | motion |
| --- | --- | --- |
| neutral | relaxed face | idle |
| happy | closed-mouth smile | hand on chest |
| excited | open smile | hand on chest |
| thinking | raised brow, slack-open mouth, white circle eyes | finger up |
| worried | concerned mouth and brow, sweat | idle |
| sad | lowered mouth corners, raised inner brows, tears | idle |
| shy | small smile, squeezed eyes | idle |
| dizzy | parted lips, white circle eyes | idle |

The face sliders blend into each new mood. The stage clears the outgoing arm switch and joint angles
when it changes gestures. While Misaki waits for a reply or writes a puzzle, the loading icon appears
over her thinking face. With reduced motion enabled, the face changes immediately and the arms stay idle.

The blush and heart-eye expressions are not used: on the tall form they read as flirtatious, which is
wrong for a character talking to students. Every reply is labelled "MISAKI". The chat footer explains
that Misaki uses AI and that the game checks her puzzles.

**Body type.** The model has a body-type parameter, `Clothes2` (default 0, 体型1 0.4, 体型2 1.0). The
chibi form is the default. A "Dáng" switch on the stage (Chibi / Thường) changes it and the choice is
kept in localStorage. The parameter is written directly every frame, not as an expression, so mood
expressions never reset it.

**Hide panel.** A button in the chat title bar ("Ẩn Misaki" / "Hiện Misaki") collapses the stage so the
chat fills the screen. The render loop pauses while the stage is hidden, and the choice is kept in
localStorage. The default is shown.

The model looks toward the pointer on desktop. Her eyes, head and body follow the pointer, and she
breathes and sways slowly when idle. This rig does not read `ParamAngle*`/`ParamBodyAngle*` directly: its
physics takes its own tracking inputs (`AngleX/Y/Z`, `PositionX/Y/Z`, `ParamBreath`) and writes the angles
from them. `misaki-stage.js` therefore drives those inputs before physics runs, and replaces the library's
breath cycle, which clips half of each breath at 0. `prefers-reduced-motion` keeps the idle loop, drops
mouse-follow and motions, and still shows expressions.
