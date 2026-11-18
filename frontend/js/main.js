// Boot, screens and the Code Rescue controller (glue between game.js, board.js, the puzzle panel and the API).
import * as Game from './game.js';
import * as api from './api.js';
import { isMock } from './api.js';
import * as store from './storage.js';
import { Board } from './board.js';
import { openPuzzle } from './puzzle-modal.js';
import { TOPICS, TOPIC_NAMES, TOPIC_GLYPH } from './pieces.js';
import { el, toast, confirmDialog, wait } from './ui.js';
import { tutorNote } from './editor.js';
import { icon } from './icons.js';
import { sfx } from './sound.js';
import { keycap } from './keycap.js';
import { initStrip, showStrip, setMode, setScore, setStatus, setStreak, setLedMode } from './strip.js';
import { buildTitle, playWave, buildPreviews, buildBackdrop } from './start.js';
import { initRows, openPracticeRows, openSelect, runDemo } from './rows-screen.js';
import { setScreenTitle } from './title.js';
import { initSkills, openSkills } from './skills.js';
import { initCustom, openCustom } from './custom.js';
import * as Rooms from './rooms.js';
import { mulberry } from './rng.js';
import * as RunLog from './runlog.js';
import * as Ranked from './ranked.js';
import { initLeaderboard, openLeaderboard } from './leaderboard.js';
import { initRace, openRace } from './race.js';
import * as Pvp from './pvp-screen.js';

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);

// Diagnostics for headless checks (?diag=1): collect runtime errors into the DOM.
if (params.get('diag') === '1') {
  const log = el('pre', { id: 'errlog', hidden: true });
  document.body.append(log);
  window.addEventListener('error', (e) => (log.textContent += 'ERR ' + e.message + '\n'));
  window.addEventListener('unhandledrejection', (e) => (log.textContent += 'REJ ' + (e.reason?.message || e.reason) + '\n'));
  const origErr = console.error;
  console.error = (...a) => { log.textContent += 'CON ' + a.join(' ') + '\n'; origErr(...a); };
  setTimeout(() => (log.textContent += `W ${document.documentElement.scrollWidth}/${innerWidth}\n`), 3500);
}

let G = null;
let board = null;
let busy = false;
let ui = { selected: null, bomb: false };
const prefs = { mode: 'rescue', level: 'beginner', ...store.loadPrefs() };
const LEVEL_NAME = { beginner: 'Beginner', intermediate: 'Intermediate', advanced: 'Advanced' };

function show(id) {
  setScreenTitle(id);
  for (const s of document.querySelectorAll('.screen')) s.hidden = s.id !== id;
  if (['screen-start', 'screen-end', 'screen-pvp-end'].includes(id)) showStrip(false);
  $('strip').classList.toggle('strip-plain', ['screen-practice', 'screen-skills', 'screen-custom', 'screen-leaderboard', 'screen-race-new', 'screen-race', 'screen-pvp'].includes(id));
  Rooms.syncChip(id);
  window.scrollTo(0, 0);
}

function enterKey(label, onclick, { id } = {}) {
  const k = keycap({ tag: 'button', topic: 'neutral', legend: label, legendClass: 'kb-label', variant: 'btn', enter: true });
  k.type = 'button';
  if (id) k.id = id;
  k.addEventListener('click', onclick);
  return k;
}

// ---- start screen -----------------------------------------------------------------------------
function goHome() {
  G = null;
  Ranked.detach();
  Rooms.leaveAll();
  Pvp.leaveAll();
  show('screen-start');
  const hs = store.getHighScore();
  $('hs-line').textContent = hs ? `Điểm cao nhất (Rescue): ${hs}` : '';
}

function initStart() {
  for (const k of ['mode', 'level']) {
    const r = document.querySelector(`input[name=${k}][value=${prefs[k]}]`);
    if (r) r.checked = true;
    document.querySelectorAll(`input[name=${k}]`).forEach((i) =>
      i.addEventListener('change', () => {
        prefs[k] = i.value;
        store.savePrefs({ mode: prefs.mode, level: prefs.level });
      }),
    );
  }
  $('btn-play').addEventListener('click', () => playPrefs());
  const syncRankedNote = () => { $('ranked-note').hidden = prefs.mode !== 'ranked'; };
  document.querySelectorAll('input[name=mode]').forEach((i) => i.addEventListener('change', syncRankedNote));
  syncRankedNote();
  $('btn-rows').addEventListener('click', () => openSelect());
  $('btn-practice-tray').addEventListener('click', () => showPractice());
  $('btn-skills').addEventListener('click', () => openSkills());
  $('btn-custom').addEventListener('click', () => openCustom());
  $('practice-home').addEventListener('click', goHome);
  for (const [card, btn] of [['card-rescue', 'btn-play'], ['card-rows', 'btn-rows']]) {
    $(card).addEventListener('click', (e) => {
      if (!e.target.closest('button')) $(btn).click();
    });
  }
  const hs = store.getHighScore();
  $('hs-line').textContent = hs ? `Điểm cao nhất (Rescue): ${hs}` : '';
  buildPreviews();
  buildBackdrop();
  playWave(buildTitle());
  document.addEventListener('keydown', onPresenterShortcut);
}

// Prepare three real screens from home; use the browser's Ctrl+1/2/3 to switch tabs on stage.
async function onPresenterShortcut(e) {
  if (!e.ctrlKey || !e.altKey || e.shiftKey || e.metaKey || e.repeat || e.isComposing || e.defaultPrevented) return;
  if ($('screen-start').hidden || e.target.closest?.('input, textarea, select, [contenteditable]')) return;
  const open = {
    Digit1: () => Rooms.openRoomNew(),
    Digit2: () => openCustom(),
    Digit3: () => openPracticeRows('r3', 'predict', showPractice),
    Digit4: () => Pvp.openMisakiTraining(),
  }[e.code];
  if (!open) return;
  e.preventDefault();
  try {
    await open();
  } catch (err) {
    toast('Không mở được: ' + err.message);
  }
}

const PRACTICE_LEVEL = { variables: 'r1', conditions: 'r2', loops: 'r3', functions: 'r5' };

function showPractice() {
  const saved = store.practiceFocus(TOPICS);
  const topic = saved.topic || 'loops';
  const level = topic === 'loops' && saved.errorGroup === 'bad_indent' ? 'r4'
    : Object.values(PRACTICE_LEVEL).includes(saved.levelId) || saved.levelId === 'r4'
    ? saved.levelId : PRACTICE_LEVEL[topic];
  const back = () => showPractice();
  const title = $('practice-title');
  title.textContent = 'Luyện theo lỗi';
  $('practice-focus').textContent = saved.count ? `${TOPIC_NAMES[topic]} · ${saved.count} lần sai gần đây` : 'Bắt đầu với vòng lặp.';
  const items = [['Xem từng bước', () => openPracticeRows(level, 'trace', back), 'search', 'Xem giá trị biến sau từng dòng'],
    ['Sửa lỗi trên bàn', () => openPracticeRows(level, 'repair', back, level === saved.levelId ? saved.rows : null), 'bug', 'Bàn có sẵn một lỗi, tìm và sửa']];
  items.push(['Thử lại Code Rescue', async () => {
    const seed = saved.puzzleId || (await api.nextPuzzle({
      topic, level: 'beginner', tier: 1, kind: 'rescue',
    })).id;
    const result = await api.rematch(seed, 'beginner');
    if ($('screen-practice').hidden) return;
    await openPuzzle({ puzzle: result.puzzle, topic, title: 'Thử lại Code Rescue',
      tag: 'luyện tập', penalties: false, standalone: true, intro: result.text, introSource: result.source, closeLabel: 'Về bài luyện' });
  }, 'rotate', 'Một câu cùng khái niệm, có gia sư giải thích']);
  let opening = false;
  $('practice-items').replaceChildren(...items.map(([label, open, ic, desc]) => {
    const button = keycap({ tag: 'button', topic: 'neutral', legendClass: 'practice-body', cls: 'practice-key',
      legend: el('span', { class: 'practice-in' }, icon(ic, { size: 22, cls: 'practice-ico' }),
        el('span', { class: 'practice-text' }, el('span', { class: 'practice-label', text: label }), el('span', { class: 'practice-desc', text: desc })),
        icon('chevron-right', { size: 20, cls: 'practice-go' })) });
    button.type = 'button';
    button.addEventListener('click', async () => {
      if (opening) return;
      opening = true;
      button.disabled = true;
      try {
        await open();
      } catch (e) {
        toast('Không mở được bài luyện: ' + e.message);
      } finally {
        opening = false;
        button.disabled = false;
        if (!$('screen-practice').hidden) button.focus({ preventScroll: true });
      }
    });
    return el('li', { class: 'practice-item' }, button);
  }));
  show('screen-practice');
  showStrip(true, { back: goHome, backLabel: 'Về màn hình chính' });
  setMode('LUYỆN TẬP');
  setStreak(null);
  title.focus({ preventScroll: true });
}

// ---- game setup -------------------------------------------------------------------------------
function ensureBoard() {
  if (board) return;
  const legend = $('legend');
  for (const t of TOPICS) {
    legend.append(el('li', {}, keycap({ topic: t, legend: TOPIC_GLYPH[t], legendClass: 'legend' }), TOPIC_NAMES[t]));
  }
  board = new Board({
    boardEl: $('board'),
    trayEl: $('tray'),
    itemsEl: $('items'),
    handlers: {
      getState: () => G,
      getUi: () => ui,
      onPlace,
      onBomb,
      onBugTap,
      onHint: (t) => toast(t, 1800),
      onSelect: (i, focusBoard, force) => {
        if (!G || G.phase !== 'play' || !G.tray[i]) return;
        ui.bomb = false;
        ui.selected = force ? i : ui.selected === i ? null : i;
        render();
        if (focusBoard && ui.selected != null) $('board').focus();
      },
      onItem,
    },
  });
}

async function exitGame() {
  if (busy) return;
  if (RunLog.active()) {
    // a ranked / race run ends with a "quit" move and is scored as it stands
    const ch = await confirmDialog({
      title: 'Kết thúc ván này?',
      text: 'Ván sẽ kết thúc ngay và được tính theo điểm hiện tại.',
      buttons: [{ label: 'Kết thúc ván', value: 'go', variant: 'danger' }, { label: 'Chơi tiếp', value: 'no', variant: 'ghost' }],
    });
    if (ch === 'go' && !busy && G && G.phase !== 'over') {
      busy = true;
      await finish('quit');
    }
    return;
  }
  const ch = await confirmDialog({
    title: 'Thoát ván chơi?',
    text: 'Tiến trình ván này sẽ mất.',
    buttons: [{ label: 'Thoát', value: 'go', variant: 'danger' }, { label: 'Chơi tiếp', value: 'no', variant: 'ghost' }],
  });
  if (ch === 'go') goHome();
}

/** Plays what the home setup says: a ranked run (server seed, move log) or a normal game. */
function playPrefs() {
  if (prefs.mode === 'ranked') return playRun('ranked', prefs.level);
  startGame({ mode: prefs.mode, level: prefs.level });
}

let runStarting = false;
/** Ranked / race run: nickname + POST /api/runs, then a rescue game dealt from the server seed. */
async function playRun(kind, level, race = null) {
  if (runStarting) return;
  runStarting = true;
  try {
    const res = await Ranked.beginRun({ kind, level, race });
    if (!res) return;
    if (res.unranked) startGame({ mode: 'rescue', level });
    else startGame({ mode: 'rescue', level: res.run.level }, null, res.run);
  } finally {
    runStarting = false;
  }
}

/** run (optional) = ranked/race run from Ranked.beginRun: the game is dealt from mulberry(run.seed) and every move is logged. */
function startGame(opts, setup, run = null) {
  ensureBoard();
  Rooms.resetProgress();
  Ranked.attach(run);
  const rng = run ? mulberry(run.seed) : params.get('demo') ? mulberry(7) : Math.random;
  G = Game.newGame({ ...opts, rng });
  ui = { selected: null, bomb: false };
  busy = false;
  if (setup) setup(G);
  show('screen-game');
  showStrip(true, { back: exitGame, backLabel: 'Thoát ván chơi' });
  setLedMode('rescue');
  const modeWord = run ? (run.kind === 'race' ? 'Đấu tốc độ' : 'Xếp hạng') : G.mode === 'rescue' ? 'Rescue' : 'Luyện tập';
  setMode(`CODE RESCUE · ${LEVEL_NAME[G.level]} · ${modeWord}`);
  render();
  if (G.lock) {
    G.phase = 'locked';
    render();
  }
}

function render(extra = {}) {
  board.render(G, { ...ui, ...extra });
  hud();
  banner();
}

function hud() {
  Rooms.reportProgress(G);
  setScore(G.score);
  setStreak(G.streak);
  setStatus(G.status);
}

function banner() {
  const b = $('lock-banner');
  const locked = G.phase === 'locked' && G.lock;
  $('tray-zone').classList.toggle('is-locked', !!locked);
  b.hidden = !locked;
  if (!locked) return;
  const L = G.lock;
  const tierText = L.boss ? 'Boss · 2 câu' : `Mức ${L.tier}`;
  b.className = 'lock-banner t-' + L.topic;
  b.textContent = '';
  b.append(
    el('div', { class: 'lb-title' }, icon('lock', { size: 22 }), `${L.count >= 4 ? '4+' : L.count} hàng bị khóa`),
    el('div', { class: 'lb-sub' }, el('span', { class: 'chip', text: TOPIC_NAMES[L.topic] }), `${tierText} · ${Game.baseFor(L)} điểm gốc`),
    el('div', { class: 'lb-actions' },
      enterKey('Giải đố', runLock, { id: 'btn-solve' }),
      G.items.undo > 0 && G.snapshot
        ? el('button', { class: 'btn', type: 'button', onclick: doUndo }, icon('undo', { size: 16 }), 'Hoàn tác')
        : null),
  );
}

// ---- input handlers ---------------------------------------------------------------------------
async function onPlace(idx, r, c) {
  if (busy || G.phase !== 'play') return;
  busy = true;
  const res = Game.place(G, idx, r, c);
  if (!res) {
    busy = false;
    return;
  }
  RunLog.place(idx, r, c);
  ui.selected = null;
  render({ dropped: res.placed, lock: !!res.lock });
  if (res.expired.length) toast('Bug line đã tự biến mất.');
  if (res.lock) {
    setTimeout(() => sfx('lock'), 70);
    G.phase = 'locked';
    render();
    busy = false;
    return;
  }
  await afterResolution();
  busy = false;
}

function onItem(key) {
  if (busy || G.phase !== 'play') return;
  if (key === 'bomb') {
    ui.bomb = !ui.bomb;
    ui.selected = null;
    render();
    if (ui.bomb) toast('Chạm vào một ô để nổ vùng 3×3.', 2200);
  } else if (key === 'shuffle' && Game.shuffle(G)) {
    RunLog.shuffle();
    ui.selected = null;
    render();
    toast('Đã xáo khay khối.');
    busy = true;
    afterResolution().then(() => (busy = false));
  }
}

async function onBomb(r, c) {
  if (busy) return;
  const cleared = Game.bomb(G, r, c);
  ui.bomb = false;
  if (!cleared) {
    toast('Không có ô nào để xóa ở đây (ô bug không bị bom xóa).');
    render();
    return;
  }
  RunLog.bomb(r, c);
  busy = true;
  board.lastPlaced = [[r, c]];
  sfx('bomb');
  render();
  await board.animateClear(cleared);
  render();
  await afterResolution();
  busy = false;
}

function doUndo() {
  if (busy || !Game.undo(G)) return;
  RunLog.undo();
  ui.selected = null;
  render();
  toast('Đã hoàn tác lần đặt khối.');
}

// ---- puzzle flow ------------------------------------------------------------------------------
// Demo hook against the real API: keep asking until the requested puzzle type shows up.
let demoType = !isMock && (params.get('demo') || '').startsWith('puzzle-') ? params.get('demo').slice(7).replace(/-/g, '_') : null;
let demoTries = 0;

async function fetchPuzzle(p) {
  for (;;) {
    try {
      const puzzle = await api.nextPuzzle({
        topic: p.topic,
        tier: p.tier,
        level: G.level,
        kind: p.kind,
        template_id: p.template_id ?? null,
        exclude_ids: G.seenIds.slice(-500), // the server caps this list at 1000
        exclude_templates: G.recentTemplates.slice(-3),
      });
      Game.noteSeen(G, puzzle);
      if (demoType && puzzle.type !== demoType && ++demoTries < 80) continue;
      demoType = null;
      return puzzle;
    } catch (e) {
      await confirmDialog({
        title: 'Không tải được câu đố',
        text: e.message + '. Kiểm tra kết nối rồi thử lại.',
        buttons: [{ label: 'Thử lại', value: 'retry', variant: 'primary' }],
      });
    }
  }
}

const attemptsFor = () => (G.mode === 'rescue' ? 1 : 3);

async function runLock() {
  if (busy || G.phase !== 'locked') return;
  busy = true;
  G.phase = 'puzzle';
  render();
  const L = G.lock;
  const useDbg = G.items.debugger > 0;
  if (useDbg) G.items.debugger--;
  const free = Game.freeHintLevel(G, useDbg);
  const parts = L.boss ? 2 : 1;
  const base = Game.baseFor(L);
  let maxHint = 0;
  let failed = null;
  const served = [];

  for (let i = 0; i < parts; i++) {
    const puzzle = await fetchPuzzle({ topic: L.topic, tier: L.boss ? 3 : L.tier, kind: 'rescue' });
    served.push(puzzle.id);
    const countText = L.boss ? 'Boss' : `${L.count} hàng`;
    const res = await openPuzzle({
      puzzle,
      topic: L.topic,
      title: `${TOPIC_NAMES[L.topic]} · ${countText}`,
      boss: L.boss ? `Boss ${i + 1}/2` : null,
      maxAttempts: attemptsFor(),
      free,
      onResult: (r) => { if (!r.correct && G.mode === 'rescue' && G.mistakes >= 1) setStatus('crash'); },
      awardText: (h) => {
        if (i < parts - 1) return 'Đúng câu 1/2. Còn một câu nữa.';
        const r = Game.reward(G, { base, maxHint: Math.max(maxHint, h), free });
        return `+${r.points} điểm`;
      },
    });
    maxHint = Math.max(maxHint, res.maxHint);
    if (!res.correct) {
      failed = { puzzle, response: res.response, answer: res.answer };
      break;
    }
  }

  RunLog.lock(served, useDbg);
  if (!failed) {
    const r = Game.applyCorrect(G, { base, maxHint, free, lines: L.count });
    sfx('clear', { streak: G.streak });
    await board.animateClear(L.cells, { points: r.points, color: `var(--cap-${L.topic})` });
    Game.finishLock(G);
    render();
    toast(`+${r.points} điểm${r.clean ? '' : ' (đã dùng gợi ý)'}`);
    for (const it of r.newItems) toast(`Nhận vật phẩm: ${it}`, 3200);
    await afterResolution();
  } else {
    const w = Game.applyWrong(G, failed);
    if (w.result === 'crash') {
      await finish('crash');
    } else {
      sfx('wrong');
      await board.animateBug(L.cells);
      render();
      toast(G.mode === 'rescue' ? 'Hàng này thành bug line. Trạng thái: Cảnh báo.' : 'Hàng này thành bug line, sẽ tự biến mất sau 5 lượt.', 3400);
      await afterResolution();
    }
  }
  busy = false;
}

async function onBugTap(bugId) {
  if (busy || G.phase !== 'play') return;
  const bl = G.bugLines.find((b) => b.id === bugId);
  if (!bl) return;
  const rescue = G.mode === 'rescue';
  const ch = await confirmDialog({
    title: 'Sửa bug?',
    text: rescue ? 'Trả lời sai là thua ván.' : 'Giải câu đố Debug để xóa bug line này.',
    buttons: [
      { label: 'Sửa bug', value: 'go', variant: rescue ? 'danger' : 'primary' },
      { label: 'Để sau', value: 'no', variant: 'ghost' },
    ],
  });
  if (ch !== 'go') return;
  busy = true;
  const puzzle = await fetchPuzzle({ topic: bl.topic, tier: 1, kind: 'debug', template_id: bl.templateId });
  const res = await openPuzzle({
    puzzle,
    topic: puzzle.topic || bl.topic,
    title: `Debug · ${TOPIC_NAMES[puzzle.topic || bl.topic]}`,
    tag: 'DEBUG',
    maxAttempts: attemptsFor(),
    penalties: false,
    onResult: (r) => { if (!r.correct && G.mode === 'rescue') setStatus('crash'); },
    awardText: () => `+${Game.BUG_FIX_POINTS} điểm Redemption`,
  });
  RunLog.bugfix(bugId, puzzle.id);
  if (res.correct) {
    const fx = Game.fixBug(G, bugId);
    sfx('crack');
    await board.animateCrack(fx.cells);
    render();
    toast(`Đã sửa bug! +${fx.points} điểm. Trạng thái: Ổn định.`);
    for (const it of fx.newItems) toast(`Nhận vật phẩm: ${it}`, 3200);
    await afterResolution();
  } else {
    const w = Game.applyDebugWrong(G, { puzzle, response: res.response, answer: res.answer });
    if (w.result === 'crash') await finish('crash');
    else toast('Chưa sửa được bug line.');
  }
  busy = false;
}

// ---- stuck handling ---------------------------------------------------------------------------
async function afterResolution() {
  let tries = 0;
  while (G.phase !== 'over' && !Game.anyFit(G)) {
    if (G.mode === 'practice') {
      tries++;
      if (tries === 1) {
        const rows = Game.fullestRows(G);
        const cells = Game.cellsOfRows(G, rows);
        await board.animateClear(cells);
        Game.clearCells(G, cells);
        toast('Hết chỗ đặt khối: đã tự động dọn 3 hàng đầy nhất.', 3400);
      } else {
        Game.clearEverything(G);
        toast('Đã dọn lưới để bạn chơi tiếp.', 3000);
      }
      render();
      continue;
    }
    if (G.lastCommitUsed) {
      await finish('nofit');
      return;
    }
    const ch = await confirmDialog({
      title: 'Hết chỗ đặt khối',
      text: 'Last Commit (1 lần mỗi ván): giải đúng một câu đố mức 3 để dọn 3 hàng đầy nhất và chơi tiếp. Sai hoặc bỏ qua là kết thúc ván.',
      buttons: [
        { label: 'Last Commit', value: 'go', variant: 'primary' },
        { label: 'Bỏ qua', value: 'skip', variant: 'ghost' },
      ],
    });
    if (ch !== 'go') {
      await finish('nofit');
      return;
    }
    G.lastCommitUsed = true;
    const topic = Game.lastCommitTopic(G);
    const puzzle = await fetchPuzzle({ topic, tier: 3, kind: 'last_commit' });
    const res = await openPuzzle({
      puzzle,
      topic: puzzle.topic || topic,
      title: `Last Commit · ${TOPIC_NAMES[puzzle.topic || topic]}`,
      tag: 'LAST COMMIT',
      maxAttempts: 1,
      penalties: false,
      awardText: () => 'Dọn 3 hàng đầy nhất!',
    });
    RunLog.lastCommit(puzzle.id);
    if (!res.correct) {
      Game.failLastCommit(G, { puzzle, response: res.response, answer: res.answer });
      await finish('nofit', true);
      return;
    }
    const cells = Game.cellsOfRows(G, Game.fullestRows(G));
    await board.animateClear(cells);
    Game.clearCells(G, cells);
    render();
    toast('Last Commit thành công! Ván chơi tiếp tục.');
  }
  render();
}

async function finish(reason, alreadyOver) {
  if (!alreadyOver) Game.endGame(G, reason);
  RunLog.end(reason);
  render();
  if (reason === 'crash') await board.animateCrash();
  else await wait(500);
  if (G.mode === 'rescue' && !Ranked.isRun()) store.setHighScore(G.score);
  showEnd();
}

// ---- end screen -------------------------------------------------------------------------------
function rematchButton(wrong) {
  const game = G;
  const button = el('button', { class: 'btn', type: 'button', text: 'Thử lại lỗi này' });
  button.addEventListener('click', async () => {
    if (game.rematchBusy) return;
    game.rematchBusy = true;
    button.disabled = true;
    button.textContent = 'Đang tải câu đố…';
    try {
      const result = await api.rematch(wrong.puzzleId, game.level);
      if (G !== game || $('screen-end').hidden) return;
      await openPuzzle({
        puzzle: result.puzzle, topic: result.puzzle.topic, title: 'Thử lại lỗi này',
        tag: 'luyện tập', penalties: false, standalone: true,
        intro: result.text, introSource: result.source,
      });
    } catch (e) {
      toast('Không tải được câu đố: ' + e.message);
    } finally {
      game.rematchBusy = false;
      button.disabled = false;
      button.textContent = 'Thử lại lỗi này';
      if (!$('screen-end').hidden) button.focus({ preventScroll: true });
    }
  });
  return button;
}

function showEnd() {
  const crash = G.endReason === 'crash';
  const badge = $('end-badge');
  badge.className = 'end-badge';
  badge.textContent = '';
  badge.append(el('i', { class: 'led on', style: { '--c': crash ? 'var(--crash)' : 'var(--warn)' } }), crash ? 'SYSTEM CRASH' : 'GAME OVER');
  const quit = G.endReason === 'quit';
  $('end-title').textContent = crash ? 'Hệ thống sập' : quit ? 'Ván đã kết thúc' : 'Hết chỗ đặt khối';
  $('end-sub').textContent = crash ? 'Bạn đã sai lần thứ hai trong ván này.' : quit ? 'Bạn đã chọn kết thúc ván.' : 'Không còn khối nào đặt vừa lưới.';
  $('end-score').textContent = G.score;
  $('end-score').dataset.v = String(G.score);
  $('end-streak').textContent = G.bestStreak;
  $('end-bugs').textContent = G.bugsFixed;
  $('end-mist').textContent = G.wrongLog.length;
  const hs = store.getHighScore();
  $('end-hs').textContent = Ranked.isRun() ? '' : G.mode === 'rescue' ? (G.score >= hs && G.score > 0 ? 'Kỷ lục mới!' : `Điểm cao nhất: ${hs}`) : 'Chế độ Luyện tập không tính điểm xếp hạng.';

  const ul = $('end-report');
  ul.textContent = '';
  if (!G.wrongLog.length) ul.append(el('li', { class: 'empty', text: 'Không có câu trả lời sai nào trong ván này.' }));
  for (const w of G.wrongLog) {
    ul.append(
      el('li', { class: 'rep t-' + w.topic },
        el('div', { class: 'rep-top' },
          el('span', { class: 'chip', text: TOPIC_NAMES[w.topic] }),
          w.kind === 'debug' || w.kind === 'last_commit' ? el('span', { class: 'cm', text: w.kind === 'debug' ? 'Debug' : 'Last Commit' }) : null),
        el('p', { class: 'rep-prompt', text: w.prompt }),
        w.explanation ? el('p', { class: 'rep-explain', text: w.explanation }) : null,
        w.puzzleId ? rematchButton(w) : null),
    );
  }

  const topics = [...new Set(G.wrongLog.map((w) => w.topic))];
  const pr = $('end-practice');
  pr.textContent = '';
  pr.append(el('div', { class: 'pv-label', text: topics.length ? 'Luyện lại chủ đề này' : 'Luyện tập theo chủ đề' }));
  const row = el('div', { class: 'row' });
  for (const t of topics.length ? topics : TOPICS) {
    const k = keycap({ tag: 'button', topic: t, legend: `Luyện lại: ${TOPIC_NAMES[t]}`, legendClass: 'kb-label', variant: 'btn' });
    k.type = 'button';
    k.dataset.topic = t;
    k.addEventListener('click', () => startGame({ mode: 'practice', level: G.level, focusTopic: t }));
    row.append(k);
  }
  pr.append(row);
  show('screen-end');
  $('end-title').focus({ preventScroll: true });
  Ranked.afterEnd(G);
  loadDebrief();
}

/** Tutor summary between the receipt and the error report. Silent on failure; never writes into a stale screen. */
function loadDebrief() {
  const game = G;
  document.getElementById('end-debrief')?.remove();
  const wrong = game.wrongLog.filter((w) => w.puzzleId).slice(-12);
  if (!wrong.length) return;
  const slot = el('div', { id: 'end-debrief', class: 'end-debrief' },
    el('h2', { class: 'report-h', text: 'Tổng kết' }), tutorNote({ loading: true }));
  $('end-report').previousElementSibling.before(slot);
  const body = {
    level: game.level,
    mode: game.mode,
    end_reason: game.endReason === 'crash' ? 'crash' : 'nofit',
    wrong: wrong.map((w) => ({ puzzle_id: w.puzzleId, kind: w.kind, ...w.attempt })),
  };
  api.debrief(body).then((r) => {
    if (G !== game || $('screen-end').hidden || !slot.isConnected) return;
    slot.replaceChildren(el('h2', { class: 'report-h', text: 'Tổng kết' }),
      tutorNote({ text: r.text, source: r.source === 'ai' ? 'ai' : 'canned', context: 'tổng kết' }));
    const k = r.focus_topic && $('end-practice').querySelector(`[data-topic="${r.focus_topic}"]`);
    if (k) {
      k.classList.add('enter-key');
      const ret = el('span', { class: 'ret', 'aria-hidden': 'true' }, icon('enter', { size: 14 }));
      k.querySelector('.cap-top').append(ret);
      k.parentElement.prepend(k);
    }
  }).catch(() => {
    if (slot.isConnected) slot.remove();
  });
}

$('btn-again').addEventListener('click', () => {
  const run = Ranked.lastRun(); // ranked: a fresh ranked run; race: a new run of the same race code
  if (run) playRun(run.kind, run.level, run.race);
  else startGame({ mode: G.mode, level: G.level });
});
$('btn-menu').addEventListener('click', goHome);
$('btn-end-skills').addEventListener('click', () => openSkills());

// ---- demo hooks (?mock=1&demo=board | lock | puzzle-<type> | rows-select | rows-3 | rows-3-fail | rows-pass | end) ----
function demoSetup(s) {
  const map = { v: 'variables', c: 'conditions', l: 'loops', f: 'functions' };
  const rows = ['........', '..vv....', '.vvvcc..', 'llvvccf.', 'lllc.fff', 'llccfff.', '........', 'BBBBBBBB'];
  rows.forEach((str, r) =>
    [...str].forEach((ch, c) => {
      if (ch === '.') return;
      s.grid[r][c] = ch === 'B' ? { topic: 'conditions', bug: true, bugId: 1 } : { topic: map[ch], bug: false, bugId: null };
    }),
  );
  s.bugLines = [{ id: 1, cells: [...Array(8)].map((_, c) => [7, c]), topic: 'conditions', templateId: isMock ? 'cond_colon_bug' : 'conditions_bug', placementsLeft: 5 }];
  s.nextBugId = 2;
  s.mistakes = 1;
  s.score = 1240;
  s.streak = 3;
  s.bestStreak = 3;
  s.items.bomb = 1;
  s.items.undo = 1;
  s.seenIds = [];
  Game.refreshStatus(s);
  const demo = params.get('demo');
  if (demo === 'lock' || demo.startsWith('puzzle-')) {
    // complete row 5 (loops/functions majority) to create a lock
    s.grid[5][7] = { topic: 'loops', bug: false, bugId: null };
    s.snapshot = { grid: s.grid.map((r) => r.map((c) => (c ? { ...c } : null))), tray: s.tray.slice(), score: s.score, placements: 0, bugLines: s.bugLines.map((b) => ({ ...b })) };
    s.lock = Game.findLock(s);
    s.lock.topic = 'loops';
  }
}

// Sample skill data for ?demo=skills (shown only, never saved).
function demoSkills() {
  const now = Date.now();
  const mk = (topic, type, recent, wrong = '') => ({ topic, type, attempts: recent.length + 2, correct: recent.filter(Boolean).length + 2, recent, lastWrongPrompt: wrong, updatedAt: now });
  return {
    loops_range_fill: mk('loops', 'fill_blank', [true, true, true, true, true, true]),
    loops_x_bug: mk('loops', 'find_bug', [true, false, true, true, true], 'Tìm dòng sai để chương trình in ra 0, 1, 2.'),
    loops_y_predict: mk('loops', 'predict_output', [false, false, true]),
    vars_a_fill: mk('variables', 'fill_blank', [true, true, true, true]),
    vars_a_parsons: mk('variables', 'parsons', [true, false, true, false]),
    cond_a_bug: mk('conditions', 'find_bug', [false, true], 'Câu lệnh if phải kết thúc bằng dấu hai chấm (:).'),
    func_a_fill: mk('functions', 'fill_blank', [true, true, true]),
  };
}

async function boot() {
  initStrip();
  initRows({ show, home: goHome });
  initSkills({
    show,
    home: goHome,
    practice: (focusTopic) => startGame({ mode: 'practice', level: prefs.level, focusTopic }),
    play: () => playPrefs(),
  });
  initCustom({ show, home: goHome, level: () => prefs.level });
  initStart();
  Ranked.initRanked({ openBoard: (level) => openLeaderboard({ level }) });
  initLeaderboard({ show, home: goHome, level: () => prefs.level, playRun });
  initRace({ show, home: goHome, level: () => prefs.level, playRun });
  Pvp.initPvp({ show, home: goHome, level: () => prefs.level, getBoard: () => { ensureBoard(); return board; } });
  Rooms.initRooms({ show, home: goHome, level: () => prefs.level, play: (level) => startGame({ mode: 'rescue', level: LEVEL_NAME[level] ? level : prefs.level }) });
  if (Pvp.resumeIfAny()) return;
  const duelCode = params.get('duel');
  if (duelCode) return Pvp.openDuel(duelCode);
  const teach = params.get('teach');
  if (teach) return Rooms.openTeach(teach);
  const roomCode = params.get('room');
  if (roomCode) return Rooms.openJoin(roomCode);
  const raceCode = params.get('race');
  if (raceCode) return openRace(raceCode);
  const setId = params.get('set');
  if (setId) return openCustom({ shared: setId });
  const demo = params.get('demo');
  if (!demo) return;
  if (demo === 'skills') return openSkills({ sample: demoSkills() });
  if (demo === 'custom') return openCustom();
  if (demo === 'judge') return showPractice(); // legacy URL: ordinary practice, without a separate judge flow
  if (demo.startsWith('rows-')) return runDemo(demo);
  const mode = params.get('mode') || 'rescue';
  if (demo === 'end') {
    // ?mock=1&demo=end&run=ranked|race[&rcode=DEMO1] shows the ranked / race end screen (needs a saved nickname)
    const kind = params.get('run');
    const begun = kind ? await Ranked.beginRun({ kind, level: params.get('level') || 'beginner', race: kind === 'race' ? params.get('rcode') || 'DEMO1' : null }) : null;
    startGame({ mode, level: params.get('level') || 'beginner' }, (s) => {
      demoSetup(s);
      s.grid = s.grid.map((r) => r.map(() => null));
      s.bugLines = [];
      s.wrongLog = [
        { topic: 'loops', prompt: 'Điền giá trị còn thiếu để chương trình in ra 0, 1, 2.', explanation: 'range(n) dừng trước n, nên range(3) cho 0, 1, 2.', kind: 'rescue' },
        { topic: 'conditions', prompt: 'Tìm dòng sai để chương trình in ra "lớn".', explanation: 'Câu lệnh if phải kết thúc bằng dấu hai chấm (:).', kind: 'debug' },
      ];
      s.bugsFixed = 1;
      s.bestStreak = 5;
      s.score = 2180;
    }, begun?.run || null);
    Game.endGame(G, 'crash');
    RunLog.end('crash');
    store.setHighScore(1500);
    return showEnd();
  }
  startGame({ mode, level: params.get('level') || 'beginner' }, demoSetup);
  if (demo.startsWith('puzzle-')) await runLock();
}
boot();
