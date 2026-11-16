# Syntax Stack — design brief v2 ("Keycap")

Replaces v1. Read with `Code_Rescue_Gameplay_Spec.md`, `Syntax_Rows_Gameplay_Spec.md` and `docs/api-contract.md`.
UI language: Vietnamese. Plain HTML/CSS + vanilla JS ES modules, no framework, no build step.

## Why v1 looked generic

| v1 | Problem |
| --- | --- |
| Navy + pastel purple/blue/mint, pills everywhere | The default "AI dark dashboard" palette; nothing owned |
| Emoji as icons (💣🔀↩️🔍🔥🐞🟢🟡) | Reads as placeholder, renders differently on every OS |
| Flat rounded squares with a centred faint glyph | Blocks have no material, no reason to exist |
| Every panel is the same rounded card | No hierarchy; the board doesn't feel like the hero |
| Motion = generic fades and pulses | Nothing tells you the game *heard* you |

## The idea: a mechanical keyboard you write code on

Programmers' most physical tool is the keyboard. Every block is a **keycap**, the board is a **switch plate** with empty sockets, and placing code is pressing keys. This gives the game a material, a sound-less "thock" in the motion, and a unit system that fits Syntax Rows exactly: tokens are **1u / 2u / 3u keys**, like a real keyboard's key widths.

Everything below follows from that one metaphor. When in doubt, ask "what would a keyboard do?"

## Tokens (define on `:root`)

### Surfaces (warm graphite, not navy)
| Token | Value | Use |
| --- | --- | --- |
| `--bg` | `#141518` | page |
| `--bg-grain` | subtle SVG noise at 3% opacity over `--bg` | kills the flat-digital look |
| `--case` | `#1D1F24` | the board case / main panels |
| `--case-hi` | `#2A2D34` | case top-edge highlight (1px inset) |
| `--plate` | `#0F1013` | socket well colour |
| `--line` | `rgba(236,232,223,.07)` | hairlines |
| `--text` | `#ECE8DF` | warm off-white body text |
| `--muted` | `#8E8A80` | secondary |
| `--faint` | `#5C5952` | tertiary, disabled |

### Keycap colourways (cap = top face, skirt = side, legend = text)
| Topic | Name | `--cap` | `--skirt` | `--legend` |
| --- | --- | --- | --- | --- |
| variables | Matcha | `#9BCF9F` | `#5F9467` | `#14261A` |
| conditions | Mustard | `#F2C14E` | `#B98C1F` | `#33240A` |
| loops | Coral | `#F2876A` | `#B95A3F` | `#3A140A` |
| functions | Ice | `#86C9E6` | `#4F92B1` | `#0C2633` |
| neutral (UI keys, Syntax Rows syntax tokens) | Alpha | `#E6E0D2` | `#A9A291` | `#24231F` |
| bug | Error | `#2E2729` | `#1C1718` | `#FF5D5D` |

Status indicator LEDs: ok `#7EE081`, warn `#FFC447`, crash `#FF5D5D`, each with a 6px glow of the same colour at 60%.

### Type
- **Display:** Bricolage Grotesque 800 (titles, big numbers' labels, screen headers). Vietnamese subset.
- **UI:** Be Vietnam Pro 400/600.
- **Code and key legends:** JetBrains Mono 500/700, `font-variant-numeric: tabular-nums` for all numbers (score, counters).
- Scale: 12 / 14 / 16 / 20 / 28 / 44 / 64. Tight tracking (-0.02em) on display sizes only.

### Radii and spacing
Keycap radius 7px (top face 6px inset), case 18px, panels 14px, small controls 8px. **No pill shapes** except the status LED housing. 4px spacing grid.

## The keycap (core component, build it once, use it everywhere)

Pure CSS, no images:
- Outer element = skirt colour, radius 7px, `padding-bottom: 4px` (the skirt visible below the top face).
- Inner `.cap-top` = cap colour, radius 6px, a soft radial highlight (`radial-gradient(120% 90% at 50% 0%, rgba(255,255,255,.28), transparent 60%)`) so the top looks slightly dished, and a 1px top inner highlight.
- Drop shadow under the key: `0 2px 0 rgba(0,0,0,.35), 0 6px 14px rgba(0,0,0,.25)`.
- **Legend:** top-left aligned, JetBrains Mono 700, legend colour, like a real keycap legend, 6px inset. Code Rescue cells: `x=` / `if` / `for` / `f()`. Syntax Rows tokens: the token text, centred, since it is the content.
- **Pressed state** (`:active`, and the "thock" after placement): top face translates down 2px, skirt shrinks from 4px to 2px, shadow tightens. 90ms down, 140ms up.
- Width in units: `--u` = one socket. 2u/3u keys span sockets plus the gaps between them.
- Empty socket: `--plate`, radius 6px, inset shadow `inset 0 2px 4px rgba(0,0,0,.6)`, and a tiny **MX stem cross** (`+`, 8px, `--line` colour) in the centre. This one detail sells the whole metaphor.
- Bug cap: Error colourway, legend `ERR` in red mono, a 1px red hairline crack (an SVG diagonal polyline) across the top face, and it sits 1px lower than normal keys (feels dead).

UI buttons are keycaps too: primary actions use the Alpha colourway; **"Chạy kiểm tra" is styled as an Enter key** (wide cap, `↵` legend bottom-right in mono). Secondary actions are flat text buttons with an underline on hover, not boxed.

## Icons

No emoji anywhere. Inline SVG, 1.75px stroke, 20px, `currentColor`, rounded joins (Lucide-style, hand-written in a `js/icons.js` map): bomb, shuffle, undo, bug, search/debug, flame (streak), lock, check, x, lightbulb (hint), chevrons. Items are shown as small Alpha keycaps with the icon as legend and a mono count `×2` on the skirt edge.

## Layout

### Header = keyboard indicator strip
A slim bar (52px) like the LED strip above a keyboard's numpad:
- Left: wordmark `syntax_stack` in JetBrains Mono 700, with the underscore blinking like a caret (1.1s steps, the only perpetual animation, paused when reduced motion).
- Centre (desktop): mode label in small caps mono, level.
- Right: three **indicator LEDs** labelled `BUILD`, `WARN`, `CRASH` (tiny mono labels under 6px dots). The current one is lit with glow, the others are dim `#3A3833`. This replaces the status pill. Score in big tabular mono next to them. Streak = flame icon + `×3` in mono, coloured Mustard when ≥2.

### Desktop (≥ 1024px)
Two columns, board left (the hero, max 600px square for Code Rescue), side column right (max 380px): tray, items, legend. The puzzle modal **docks into the side column area** as a panel that slides over it (not a centred overlay), so the board and its locked line stay visible on the left. The board dims to 55% except the locked cells.

### Phone (< 1024px)
Header strip collapses to wordmark, LEDs (dots only), score. Board full width with a 16px gutter. Tray below, items row below that. Puzzle opens as a bottom sheet (max 88vh) with a grab handle; the board stays visible above it when it fits. Touch targets ≥ 44px. No horizontal scroll at 375px.

### The case
The board sits in a "case": `--case` background, 18px radius, 14px padding, a 1px `--case-hi` top inner edge and a long soft shadow `0 30px 60px -20px rgba(0,0,0,.6)`. Socket gap 6px. In Syntax Rows the case has a left gutter with row numbers (mono, `--faint`, current error row in red) and the first two socket columns are **indent sockets** (dashed 1px outline instead of the inset well, label `⇥` on hover).

## Screens

1. **Start.** The title "SYNTAX STACK" set as two rows of Alpha keycaps, one letter per key (Code Rescue's colourways sprinkled on 4 random letters). On first load the keys press in a left-to-right wave (rare, once: delight allowed). Under it two large mode cards side by side (stack on phone): **Code Rescue** ("Xếp khối, giải đố để dọn hàng. Sai 2 lần là sập.") and **Syntax Rows** ("Mỗi hàng là một dòng Python. Viết đúng thì hàng biến mất."). Each card shows a tiny live preview (a 4×4 mini plate with a few caps for Code Rescue, a 2-line code row of caps for Syntax Rows). Below: level choice as three keycaps (Beginner/Intermediate/Advanced, the selected one shown pressed) and, for Code Rescue, a Rescue/Luyện tập toggle as a two-key switch.
2. **Code Rescue game.**
3. **Syntax Rows level select:** 5 levels as wide keycaps in a row (wrap on phone), number legend + title, stars below each (SVG stars, filled Mustard), locked levels show a lock icon and are dimmed.
4. **Syntax Rows game** (see spec).
5. **End / result screens:** big score in Bricolage 64, the run's numbers as a mono "receipt" (`streak_max ....... 5`, `bugs_fixed ..... 1`) with dotted leaders, the Báo cáo lỗi list as a code-review style list (red left rule, topic chip, prompt, explanation), and keycap buttons.

## Puzzle panel (Code Rescue) and editor panel (Syntax Rows)

Styled as an **editor window**, not a generic card:
- Title bar with a tab: `vong_lap.py` (topic file name: `bien.py`, `dieu_kien.py`, `vong_lap.py`, `ham.py`), the tab has a 3px top border in the topic colour; right side shows tier as mono `tier 2/3` or `BOSS 1/2`.
- Gutter with line numbers, code in JetBrains Mono 15px, light syntax highlighting with a restrained palette (keywords Coral, strings Matcha, numbers Mustard, functions Ice, all at 85% lightness so they don't scream).
- `___` blank = a dashed empty socket inline in the code.
- Expected output shown as a mini terminal block (`$ python main.py` faint prompt line, then output).
- Options are Alpha keycaps (fill_blank / predict_output / find_bug replacements); selected = pressed + topic-coloured cap.
- Parsons lines are wide keycaps (draggable), with ⇤ ⇥ indent keys and ↑ ↓ reorder keys as small 1u caps.
- Hints: a lightbulb row "Gợi ý 1/3 · −10% điểm" that expands inline like a code comment (`# range() dừng trước giá trị kết thúc.` in muted italic mono).
- Commit = Enter key. Confirm step appears in place of the footer: "Commit câu trả lời này? Chỉ có 1 lần." with Enter key "Commit ↵" and a text button "Xem lại".
- Result: correct = the title-bar tab gets a check and the panel edge flashes Matcha once; wrong = a red diff view: the player's line with `-` in red, the solution line with `+` in Matcha, then the explanation as a comment.

## Motion

Easing tokens on `:root`:
```css
--ease-out: cubic-bezier(0.23, 1, 0.32, 1);
--ease-in-out: cubic-bezier(0.77, 0, 0.175, 1);
--ease-drawer: cubic-bezier(0.32, 0.72, 0, 1);
```
Rules: animate only `transform`, `opacity`, `filter`, `clip-path`. Never `transition: all`. Never scale from 0 (min 0.9). Exits faster than entrances. Hover effects only inside `@media (hover: hover) and (pointer: fine)`. Nothing animates on keyboard-driven actions except state feedback. Interruptible UI uses transitions; one-off sequences use WAAPI (`el.animate`).

| Moment | Frequency | Motion |
| --- | --- | --- |
| Pick up a piece | very often | Lifts 1:1 with the pointer (no lag, pointer capture), scale 1.04, shadow grows. Ghost on the board = sockets light up in the topic cap colour at 35%; invalid = no ghost and the piece tints 10% red. |
| Place a piece | very often | Caps drop from `translateY(-6px) scale(1.03)` to rest in 120ms ease-out, then a "thock": 2px press and release in 90ms. Stagger 12ms across the piece's cells. Total < 220ms. |
| Tray refill | every 3 placements | 3 pieces enter `translateY(8px)`+opacity, delays 0/40/90ms, 220ms ease-out. |
| Line locks | often | Locked caps press down 2px and stay down; a light sweep runs under the row once via `clip-path` inset left→right, 380ms ease-in-out; then a slow 2.4s breathing glow (opacity only) on the row outline while the puzzle is open. |
| Puzzle opens | often | Desktop: panel enters `translateX(24px)`+opacity, 260ms ease-out. Phone: sheet `translateY(100%)` → 0, 340ms ease-drawer. Close: 180ms ease-out. |
| Correct → clear | often | Each cap pops: `translateY(-16px) rotate(±4–8deg random) scale(.92)` + opacity 0, 260ms ease-out, stagger 22ms from the end nearest the last placed piece. `+375` floats up 24px from the row centre, 700ms, then fades. Score number rolls (tabular digits, 400ms). |
| Wrong → bug line | rare | Caps shake (3 cycles, 6px, 300ms), then crossfade to Error caps with `filter: blur(2px)` masking the swap (200ms). WARN LED blinks twice and stays lit. |
| Debug fixed | rare | Error caps crack apart: each cap splits into two halves (two pseudo-elements) that drift ±10px and fade, 320ms. BUILD LED relights. |
| Crash | rare | CRASH LED lights, the board flickers once (opacity 1→.4→1, 120ms), then caps fall row by row from the bottom: `translateY(110vh) rotate(random ±25deg)`, 700ms with `cubic-bezier(.5,0,.75,0)` (gravity is the one place ease-in is right), 30ms stagger. |
| Syntax Rows pass | per level | Rows compile top to bottom: each row's caps flash Matcha (120ms) then lift away like a clear, 80ms between rows; the output panel types the program output line by line (20ms/char, capped at 600ms total). Stars fill in one by one with a 1.15 → 1 settle. |
| Syntax Rows fail | per run | The error row's caps shake once (200ms) and the gutter number turns red; the validator line in the editor slides down from the title bar (200ms). |
| Buttons/keys pressed | always | Keycap press (2px down, skirt shrink), 90ms down / 140ms up. |
| Hover | desktop only | Keycaps rise 1px and brighten 4%, 150ms ease. |

Reduced motion: keep opacity and colour changes (LEDs, flashes, fades of 150ms), remove all translate/rotate/scale and the falling crash. The caret blink stops.

## Quality bar

- Looks intentional at 375px and at 1440px; nothing touches a screen edge on phone without the 16px gutter.
- No emoji, no default browser focus rings (replace with a 2px Mustard focus outline offset 2px, keyboard focus only via `:focus-visible`).
- Numbers never jitter (tabular-nums).
- Every interactive element has a pressed state.
