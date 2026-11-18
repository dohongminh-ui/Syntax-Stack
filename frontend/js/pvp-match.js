// The live 1v1 match ("Đối kháng", docs/pvp.md): your board, the pending-lines meter, the opponent mini-board,
// countdown / overtime / disconnect overlays, the puzzle flow and the end screen.
//
// The server is authoritative. Every `state` message replaces what is on screen. To feel instant, a placement
// (and a bomb) is also predicted locally with Game.place / Game.bomb; the prediction is kept in `unacked` and
// replayed on top of each new server state until the server has caught up (see settle() / rebuild()).
import * as Game from './game.js';
import * as api from './api.js';
import { openPuzzle } from './puzzle-modal.js';
import { TOPICS, TOPIC_NAMES } from './pieces.js';
import { el, anim, EASE, toast, confirmDialog, wait, reducedMotion } from './ui.js';
import { icon } from './icons.js';
import { keycap } from './keycap.js';
import { sfx } from './sound.js';
import { showStrip, setMode, setScore, setStatus, setStreak, setLedMode } from './strip.js';
import { LEVEL_NAME } from './rank-ui.js';
import { setRating, clearTicket } from './pvp.js';
import { misakiAvatar, misakiTitle } from './misaki.js';

const $ = (id) => document.getElementById(id);
const SIZE = 8;
const METER_SLOTS = 8;
const OVERTIME_S = (() => {
  const n = Number(new URLSearchParams(location.search).get('pvpot')); // QA: ?mock=1&pvpot=20 starts overtime at 0:20
  return api.isMock && n > 0 ? n : 240;
})();
const UNACKED_TTL_MS = 2000;
const COACH_DIM_MS = 8000; // the coach bubble fades to a quieter state after this
const COACH_CELLS_MS = 4500; // a coach hint outlines its cells for this long
const SUGGEST_MS = 9000; // a suggestion stays outlined this long (or until you place a piece)
const SUGGEST_COOLDOWN_MS = 3000;
const SEND_TABLE = [0, 1, 2, 3, 4];

const REASON = {
  win: {
    topped_out: 'Các dòng lỗi đã đẩy khối của đối thủ ra khỏi đỉnh bàn.',
    nofit: 'Đối thủ không còn khối nào đặt vừa bàn.',
    resign: 'Đối thủ đã bỏ cuộc.',
    disconnect: 'Đối thủ mất kết nối quá 20 giây.',
  },
  lose: {
    topped_out: 'Các dòng lỗi đã đẩy khối của bạn ra khỏi đỉnh bàn.',
    nofit: 'Không còn khối nào của bạn đặt vừa bàn.',
    resign: 'Bạn đã bỏ cuộc.',
    disconnect: 'Bạn mất kết nối quá 20 giây.',
  },
  draw: {
    both_disconnected: 'Cả hai cùng mất kết nối nên trận hòa.',
    server_restart: 'Máy chủ đang được cập nhật nên trận bị hủy. Xếp hạng không thay đổi.',
  },
};

const fmtClock = (s) => `${Math.floor(Math.max(0, s) / 60)}:${String(Math.floor(Math.max(0, s)) % 60).padStart(2, '0')}`;
const topicColor = (t) => (TOPICS.includes(t) ? `var(--cap-${t})` : 'var(--crash)');
const nOf = (v) => (Array.isArray(v) ? v.length : Number(v) || 0);

export class PvpMatch {
  /**
   * opts: { board, client, show, you, opponent, level, onRematch(), onHome() }
   * you: { nickname, rating? }   opponent: { nickname, bot, connected, rating? }
   */
  constructor(opts) {
    this.o = opts;
    this.board = opts.board;
    this.client = opts.client;
    this.level = opts.level || 'beginner';
    this.you = opts.you || {};
    this.opponent = opts.opponent || {};
    this.started = false;
    this.ended = false;
    this.conn = 'open';
    this.matchId = null;
    this.rev = null;
    this.server = null; // last normalized `state.you`
    this.unacked = []; // predicted actions the server has not reflected yet
    this.frozen = false; // puzzle open: the board keeps its picture, server states are only stored
    this.puzzleOpen = false;
    this.busy = false;
    this.ui = { selected: null, bomb: false };
    this.t0 = 0;
    this.opp = null;
    this.oppAway = null; // { until }
    this.stateWaiters = [];
    this.sentBuf = null;
    this.sentWaiters = [];
    this.lastLandAt = 0;
    this.landRows = 0;
    this.landAt = 0;
    this.stateAt = 0;
    this.meterPrev = 0;
    this.countDeadline = 0;
    this.countShown = null;
    this.timers = [];
    this.marks = []; // coach / suggestion outlines on the board: { el, kind }
    this.hintWait = false;
    this.endSignal = new Promise((res) => (this.resolveEnd = res));
    this.view = this.emptyView();

    this.prevHandlers = this.board.h;
    this.board.h = this.handlers();
    this.buildDom();
    this.onUnload = (e) => {
      if (this.ended) return;
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', this.onUnload);
    if (new URLSearchParams(location.search).get('diag') === '1') window.__pvpMatch = this; // headless checks only
    this.enter();
  }

  /** Playing Misaki (the AI character) and whether this is the coached "Luyện tập" mode. */
  get isMisaki() {
    return !!this.opponent.misaki;
  }

  get training() {
    return this.isMisaki && !!this.opponent.training;
  }

  oppLabel() {
    return this.isMisaki ? this.opponent.title || misakiTitle(this.opponent.misaki) : this.opponent.nickname || 'Đối thủ';
  }

  modeLabel() {
    const mock = api.isMock ? ' · MÔ PHỎNG' : '';
    if (this.isMisaki) return `${this.training ? 'LUYỆN TẬP' : 'ĐỐI KHÁNG'} · ${this.oppLabel().toUpperCase()}${mock}`;
    return `ĐỐI KHÁNG · ${LEVEL_NAME[this.level] || this.level}${mock}`;
  }

  // ---- screen setup -------------------------------------------------------------------------------------------
  handlers() {
    return {
      getState: () => this.view,
      getUi: () => this.ui,
      onPlace: (i, r, c) => this.place(i, r, c),
      onBomb: (r, c) => this.bomb(r, c),
      onBugTap: (id) => this.bugTap(id),
      onHint: (t) => toast(t, 1800),
      onSelect: (i, focusBoard, force) => {
        const v = this.view;
        if (v.phase !== 'play' || !v.tray[i]) return;
        this.ui.bomb = false;
        this.ui.selected = force ? i : this.ui.selected === i ? null : i;
        this.paint();
        if (focusBoard && this.ui.selected != null) $('board').focus();
      },
      onItem: (key) => this.item(key),
    };
  }

  enter() {
    api.setRunContext(null);
    this.o.show('screen-game');
    document.title = 'Đối kháng — Syntax Stack';
    const screen = $('screen-game');
    screen.classList.add('is-pvp');
    for (const id of ['pvp-opp', 'pvp-meter']) $(id).hidden = false;
    showStrip(true, { back: () => this.requestExit(), backLabel: 'Bỏ cuộc và thoát' });
    setLedMode('rescue');
    setMode(this.modeLabel());
    setScore(0, { roll: false });
    setStreak(0);
    setStatus('ok', { blink: false });
    this.paint();
    this.paintOpp();
    this.buildCoach();
    this.timers.push(setInterval(() => this.tick(), 250));
    this.showOverlay('wait');
  }

  buildDom() {
    // meter (beside the board)
    const meter = $('pvp-meter');
    meter.replaceChildren();
    this.segs = [];
    const track = el('div', { class: 'pm-track', 'aria-hidden': 'true' });
    for (let i = 0; i < METER_SLOTS; i++) {
      const s = el('i', { class: 'pm-seg' });
      s.addEventListener('animationend', () => {
        if (s.classList.contains('out')) {
          s.classList.remove('out');
          s.style.removeProperty('--c');
        }
      });
      this.segs.push(s);
      track.append(s);
    }
    this.meterN = el('b', { class: 'pm-n', hidden: true });
    meter.append(track, this.meterN);

    // opponent panel
    const cells = [];
    this.mini = el('div', { class: 'po-mini', role: 'img', 'aria-label': 'Bàn của đối thủ' });
    for (let i = 0; i < SIZE * SIZE; i++) {
      const c = el('i', { class: 'mc' });
      cells.push(c);
      this.mini.append(c);
    }
    this.miniCells = cells;
    this.oppOvlN = el('b', { class: 'po-ovl-n', 'aria-hidden': 'true' });
    this.oppOvlT = el('span', { class: 'po-ovl-t', role: 'status' });
    this.oppOvl = el('div', { class: 'po-ovl', hidden: true }, this.oppOvlN, this.oppOvlT);
    this.poBoard = el('div', { class: 'po-board' }, this.mini, this.oppOvl);

    this.poAv = el('span', { class: 'po-av', hidden: true }, misakiAvatar());
    this.poAi = el('span', { class: 'po-tag po-ai', text: 'AI', hidden: true, title: 'Misaki là AI' });
    this.poNick = el('span', { class: 'po-nick' });
    this.poBot = el('span', { class: 'po-tag po-bot', text: 'MÁY', hidden: true, title: 'Đối thủ là máy' });
    this.poMock = el('span', { class: 'po-tag po-mock', text: 'mô phỏng', hidden: !api.isMock });
    this.poRating = el('span', { class: 'po-rating', hidden: true });
    this.poScore = el('b', { class: 'po-score', text: '0' });
    this.poPend = el('b', { class: 'po-pend', text: '0' });
    this.poClock = el('b', { class: 'po-clock', text: '0:00' });
    this.poLed = el('i', { class: 'led', style: { '--c': 'var(--ok)' } });
    this.poStateT = el('span', { text: '' });
    this.poOt = el('p', { class: 'po-ot', role: 'status', 'aria-live': 'polite' }, icon('alert', { size: 14 }),
      el('span', { text: 'Hiệp phụ: mỗi 20 giây thêm 1 dòng lỗi cho cả hai' }));
    this.poOt.classList.add('is-off');
    const stat = (label, node) => el('span', { class: 'po-stat' }, el('i', { text: label }), node);
    const info = el('div', { class: 'po-info' },
      el('div', { class: 'po-name' }, this.poAv, this.poNick, this.poAi, this.poBot, this.poMock, this.poRating),
      el('div', { class: 'po-stats' }, stat('Điểm', this.poScore), stat('Chờ', this.poPend), stat('Giờ', this.poClock)),
      el('p', { class: 'po-state' }, this.poLed, this.poStateT),
      this.poOt);
    $('pvp-opp').replaceChildren(this.poBoard, info);
    this.poPendWrap = this.poPend.parentElement;

    // overlay on my board (countdown / reconnecting)
    this.ovl = $('pvp-ovl');
  }

  // ---- state shapes -------------------------------------------------------------------------------------------
  emptyView() {
    const v = Game.newGame({ mode: 'pvp', level: this.level, rng: () => 0.5 });
    v.grid = Array.from({ length: SIZE }, () => Array(SIZE).fill(null));
    v.tray = [null, null, null];
    v.items = { bomb: 0, shuffle: 0, undo: 0, debugger: 0 };
    v.pending = [];
    v.phase = 'wait';
    return v;
  }

  /** Server `you` -> the plain fields of a Game state. Missing fields get safe defaults. */
  normalize(you) {
    const prevTray = this.server?.tray || [];
    const cell = (c) => {
      if (!c) return null;
      if (typeof c === 'string') return c === 'bug' ? { topic: 'conditions', bug: true, bugId: null } : { topic: c, bug: false, bugId: null };
      return { topic: c.topic, bug: !!c.bug, bugId: c.bugId ?? null };
    };
    const grid = Array.from({ length: SIZE }, (_, r) => Array.from({ length: SIZE }, (_, c) => cell(you.grid?.[r]?.[c])));
    const tray = [0, 1, 2].map((i) => {
      const p = you.tray?.[i];
      if (!p || !Array.isArray(p.cells)) return null;
      const cells = p.cells.map(([r, c]) => [r, c]);
      const w = p.w ?? Math.max(...cells.map((x) => x[1])) + 1;
      const h = p.h ?? Math.max(...cells.map((x) => x[0])) + 1;
      const sig = `${p.topic}:${JSON.stringify(cells)}`;
      const prev = prevTray[i];
      const id = p.id ?? (prev && prev.sig === sig ? prev.id : `s${this.rev ?? 0}-${i}-${Math.random().toString(36).slice(2, 6)}`);
      return { id, sig, shape: p.shape, cells, w, h, topic: p.topic };
    });
    let pending = you.pending;
    if (!Array.isArray(pending)) pending = Array.from({ length: Number(pending) || 0 }, () => ({ topic: null, templateId: null }));
    pending = pending.map((p) => ({ topic: p?.topic ?? null, templateId: p?.templateId ?? p?.template_id ?? null }));
    const bugLines = (you.bugLines || []).map((b) => {
      let cells = b.cells;
      if (!cells || !cells.length) {
        cells = [];
        for (let r = 0; r < SIZE; r++) for (let c = 0; c < SIZE; c++) if (grid[r][c]?.bug && grid[r][c].bugId === b.id) cells.push([r, c]);
      }
      return { id: b.id, cells: cells.map((x) => x.slice()), topic: b.topic, templateId: b.templateId ?? b.template_id ?? null, placementsLeft: b.placementsLeft ?? 99 };
    });
    return {
      grid, tray, pending, bugLines,
      received: Number(you.received) || 0,
      score: Number(you.score) || 0,
      streak: Number(you.streak) || 0,
      items: { bomb: 0, shuffle: 0, undo: 0, debugger: 0, ...(you.items || {}) },
      lock: you.lock && you.lock.cells ? { ...you.lock, cells: you.lock.cells.map((x) => x.slice()), rows: you.lock.rows || [], cols: you.lock.cols || [] } : null,
      phase: you.phase,
    };
  }

  /** A fresh Game-shaped object holding a copy of `src`'s data (so Game.place / Game.bomb can run on it). */
  cloneView(src) {
    const n = Game.newGame({ mode: 'pvp', level: this.level, rng: () => 0.5 });
    n.grid = src.grid.map((row) => row.map((c) => (c ? { ...c } : null)));
    n.tray = src.tray.slice();
    n.score = src.score;
    n.streak = src.streak;
    n.bestStreak = src.streak;
    n.items = { ...src.items };
    n.pending = src.pending.map((p) => ({ ...p }));
    n.bugLines = src.bugLines.map((b) => ({ ...b, cells: b.cells.map((c) => c.slice()) }));
    n.lock = src.lock ? { ...src.lock } : null;
    n.nextBugId = 10000;
    n.sent = 0;
    n.received = 0;
    n.snapshot = null;
    return n;
  }

  phaseFor(v) {
    if (this.ended) return 'over';
    if (!this.started || !this.server || this.conn !== 'open' || v._over) return 'wait';
    if (this.puzzleOpen) return 'puzzle';
    return v.lock ? 'locked' : 'play';
  }

  // ---- server messages ----------------------------------------------------------------------------------------
  handle(msg) {
    switch (msg.t) {
      case 'lobby': return this.onLobby(msg);
      case 'start': return this.onStart(msg);
      case 'state': return this.onState(msg);
      case 'opponent': return this.onOpponent(msg);
      case 'sent': return this.onSent(msg);
      case 'incoming': return this.onIncoming(msg);
      case 'landed': return this.onLanded(msg);
      case 'opponent_status': return this.onOppStatus(msg);
      case 'end': return this.onEnd(msg);
      case 'rematch_status': return this.onRematchStatus(msg);
      case 'coach': return this.onCoach(msg);
      case 'suggestion': return this.onSuggestion(msg);
      case 'error': return this.onError(msg);
      default:
    }
  }

  onLobby(msg) {
    if (msg.opponent) this.opponent = { ...this.opponent, ...msg.opponent };
    if (msg.you) this.you = { ...this.you, ...(typeof msg.you === 'string' ? { nickname: msg.you } : msg.you) };
    if (msg.level) this.level = msg.level;
    setMode(this.modeLabel());
    this.buildCoach();
    if (msg.starts_in != null && !this.started) {
      this.countDeadline = Date.now() + Number(msg.starts_in) * 1000;
      this.tick();
    }
    this.paintOpp();
  }

  onStart(msg) {
    if (msg.level) this.level = msg.level;
    api.setMatchContext({ id: msg.match_id, token: msg.match_token });
    if (this.started && this.matchId === msg.match_id) return; // re-sent after a reconnect
    this.matchId = msg.match_id;
    this.started = true;
    this.t0 = Date.now();
    this.countDeadline = 0;
    // The server says how long the match has run (`elapsed`, seconds): immune to a wrong phone clock.
    const elapsed = Number(msg.elapsed);
    if (Number.isFinite(elapsed) && elapsed > 0 && elapsed < 30 * 60) this.t0 = Date.now() - elapsed * 1000;
    if (this.o.resumed) {
      // back after a reload: no GO; fall back to the start time only if the server sent no `elapsed`
      if (!(Number.isFinite(elapsed) && elapsed > 0)) {
        const at = Number(msg.at);
        const gone = Date.now() - (at > 1e12 ? at : at * 1000);
        if (gone > 0 && gone < 30 * 60 * 1000) this.t0 = Date.now() - gone;
      }
      this.ovl.hidden = true;
      this.ovl.dataset.kind = '';
    } else this.hideOverlayAfterGo();
    this.paint();
    this.tick();
  }

  onState(msg) {
    if (!msg.you) return;
    if (msg.rev != null && this.rev != null && msg.rev < this.rev) return; // stale
    const rev = msg.rev ?? (this.rev ?? 0) + 1;
    this.rev = rev;
    this.server = this.normalize(msg.you);
    this.stateAt = Date.now();
    this.settle();
    for (const w of this.stateWaiters.splice(0)) w(rev);
    if (this.ended) return;
    if (this.frozen) {
      this.paintMeter();
      return;
    }
    this.rebuild();
    this.tryLand();
  }

  onOpponent(msg) {
    this.opp = msg;
    if (msg.connected === false && !this.oppAway) this.oppAway = { until: Date.now() + 20000 };
    if (msg.connected !== false && this.oppAway) this.oppAway = null;
    this.paintOpp();
  }

  onOppStatus(msg) {
    if (msg.connected === false) {
      this.oppAway = { until: Date.now() + (Number(msg.grace_s) || 20) * 1000 };
      toast('Đối thủ mất kết nối. Bạn có thể chơi tiếp.', 2600);
    } else {
      if (this.oppAway) toast('Đối thủ đã kết nối lại.', 2000);
      this.oppAway = null;
    }
    if (this.opp) this.opp = { ...this.opp, connected: msg.connected !== false };
    this.paintOpp();
  }

  onIncoming(msg) {
    const n = Number(msg.lines) || 0;
    if (!n) return;
    sfx('incoming');
    const meter = $('pvp-meter');
    this.pulse(meter, 'hit', 700);
    if (!this.ended) this.fly(`+${n}`, this.poBoard, meter, topicColor(msg.from_topic));
    this.paintOpp();
  }

  onSent(msg) {
    if (this.puzzleOpen) {
      // the board is dimmed behind the puzzle: play it together with the clear animation
      this.sentBuf = msg;
      for (const w of this.sentWaiters.splice(0)) w(msg);
      return;
    }
    this.playSent(msg);
  }

  playSent(msg) {
    const lines = Number(msg.lines) || 0;
    const cancelled = Number(msg.cancelled) || 0;
    if (cancelled > 0) {
      this.pulse($('pvp-meter'), 'cancel', 600);
      const r = $('pvp-meter').getBoundingClientRect();
      this.floatAt(`−${cancelled}`, r.left + r.width / 2, r.top + r.height * 0.35, 'var(--ok)');
    }
    if (lines > 0) {
      sfx('send');
      this.fly(`+${lines}`, $('board'), this.poBoard, 'var(--mustard)');
    } else if (cancelled > 0) {
      sfx('crack');
    }
  }

  onLanded(msg) {
    const rows = Number(msg.rows) || 0;
    if (!rows) return;
    if (Date.now() - this.lastLandAt < 1200) return; // already played from the local prediction
    this.landRows = rows;
    this.landAt = Date.now();
    this.tryLand();
  }

  tryLand() {
    if (!this.landRows) return;
    const now = Date.now();
    if (now - this.landAt > 1500) {
      this.landRows = 0;
      return;
    }
    if (this.stateAt >= this.landAt - 400 && !this.frozen) {
      const k = this.landRows;
      this.landRows = 0;
      this.playLand(k);
    }
  }

  onError(msg) {
    this.unacked = [];
    this.ui.bomb = false;
    this.ui.selected = null;
    if (this.server && !this.frozen && !this.ended) this.rebuild();
    const text = {
      illegal: 'Không đặt được ở vị trí này.',
      stale_state: 'Có dòng lỗi mới vừa tới. Hãy xem lại bàn rồi đặt khối.',
      not_playing: 'Chưa thể thao tác lúc này.',
      rate_limited: 'Bạn thao tác quá nhanh.',
      not_training: 'Gợi ý nước đi chỉ có trong chế độ luyện tập.',
    }[msg.code] || msg.message || 'Máy chủ từ chối thao tác này.';
    toast(text, 2200);
  }

  // ---- prediction + reconcile ---------------------------------------------------------------------------------
  /** A server state arrived: the oldest predicted action is (most likely) now part of it. */
  settle() {
    const now = Date.now();
    this.unacked = this.unacked.filter((a) => now - a.at < UNACKED_TTL_MS);
    if (this.unacked.length) this.unacked.shift();
  }

  /** view = server state + the still-unacknowledged predicted actions, drawn. */
  rebuild() {
    let v = this.cloneView(this.server);
    for (const a of this.unacked) {
      const next = a.t === 'place' ? this.predictPlace(v, a.i, a.r, a.c) : this.predictBomb(v, a.r, a.c);
      if (!next) {
        this.unacked = []; // the replay no longer fits: trust the server
        v = this.cloneView(this.server);
        break;
      }
      v = next.v;
    }
    this.view = v;
    this.paint();
  }

  predictPlace(base, i, r, c) {
    const v = this.cloneView(base);
    const res = Game.place(v, i, r, c);
    if (!res) return null;
    // an emptied tray is refilled from the server's seeded RNG: do not show made-up pieces, wait for the state
    if (v.tray.some((p) => p && !base.tray.includes(p))) v.tray = [null, null, null];
    if (v.phase === 'over') v._over = true; // topped out: the server decides, wait for `end`
    v.phase = 'play';
    return { v, res };
  }

  predictBomb(base, r, c) {
    const v = this.cloneView(base);
    const cleared = Game.bomb(v, r, c);
    if (!cleared) return null;
    return { v, res: { cleared } };
  }

  canAct() {
    return this.started && !this.ended && !this.frozen && !this.busy && this.conn === 'open' && this.server && this.view.phase === 'play';
  }

  place(i, r, c) {
    if (!this.canAct()) return;
    this.clearMarks('sug');
    const next = this.predictPlace(this.view, i, r, c);
    if (!next) return;
    if (!this.client.send({ t: 'place', i, r, c, received: this.server.received })) {
      toast('Mất kết nối, chưa gửi được nước đi.', 2000);
      return;
    }
    this.unacked.push({ t: 'place', i, r, c, at: Date.now() });
    this.ui.selected = null;
    this.view = next.v;
    const { res } = next;
    this.paint({ dropped: res.placed, lock: !!res.lock });
    if (res.lock) setTimeout(() => sfx('lock'), 70);
    if (res.landed && !next.v._over) {
      this.lastLandAt = Date.now();
      this.playLand(res.landed);
    }
  }

  async bomb(r, c) {
    if (this.busy || !this.canAct()) return;
    const next = this.predictBomb(this.view, r, c);
    this.ui.bomb = false;
    if (!next) {
      toast('Không có ô nào để xóa ở đây (ô bug không bị bom xóa).');
      this.paint();
      return;
    }
    if (!this.client.send({ t: 'bomb', r, c })) {
      toast('Mất kết nối, chưa gửi được nước đi.', 2000);
      this.paint();
      return;
    }
    this.unacked.push({ t: 'bomb', r, c, at: Date.now() });
    this.busy = true;
    this.board.lastPlaced = [[r, c]];
    sfx('bomb');
    this.paint();
    await this.board.animateClear(next.res.cleared);
    this.busy = false;
    if (this.ended) return;
    this.view = next.v;
    this.paint();
  }

  item(key) {
    if (!this.canAct()) return;
    if (key === 'bomb') {
      this.ui.bomb = !this.ui.bomb;
      this.ui.selected = null;
      this.paint();
      if (this.ui.bomb) toast('Chạm vào một ô để nổ vùng 3×3.', 2200);
    } else if (key === 'shuffle' && this.view.items.shuffle > 0) {
      if (this.client.send({ t: 'shuffle' })) {
        this.ui.selected = null;
        toast('Đang xáo khay khối…', 1400);
      }
    }
  }

  undo() {
    if (this.ended || this.busy || this.frozen || this.conn !== 'open') return;
    if (this.view.items.undo > 0 && this.view.lock && this.client.send({ t: 'undo' })) toast('Đã hoàn tác lần đặt khối.', 1600);
  }

  // ---- puzzles ------------------------------------------------------------------------------------------------
  async drainUnacked(ms = 1500) {
    const end = Date.now() + ms;
    while (this.unacked.length && Date.now() < end && !this.ended) await wait(40);
  }

  /** Resolves with the rev of the first state newer than `rev0`, or null after `ms`. */
  waitState(rev0, ms) {
    return new Promise((resolve) => {
      if (this.rev != null && rev0 != null && this.rev > rev0) return resolve(this.rev);
      const done = (rev, force = false) => {
        if (!force && rev0 != null && rev <= rev0) {
          this.stateWaiters.push(done); // an old / duplicate state: keep waiting
          return;
        }
        clearTimeout(timer);
        resolve(rev);
      };
      const timer = setTimeout(() => {
        this.stateWaiters = this.stateWaiters.filter((w) => w !== done);
        resolve(null);
      }, ms);
      this.stateWaiters.push(done);
    });
  }

  takeSent(ms) {
    return new Promise((resolve) => {
      if (this.sentBuf) {
        const m = this.sentBuf;
        this.sentBuf = null;
        return resolve(m);
      }
      const timer = setTimeout(() => {
        this.sentWaiters = this.sentWaiters.filter((w) => w !== done);
        resolve(null);
      }, ms);
      const done = (m) => {
        clearTimeout(timer);
        this.sentBuf = null;
        resolve(m);
      };
      this.sentWaiters.push(done);
    });
  }

  async fetchPuzzle(p) {
    for (;;) {
      if (this.ended) return null;
      try {
        return await api.nextPuzzle({ topic: p.topic, tier: p.tier, level: this.level, kind: p.kind, template_id: p.template_id ?? null });
      } catch (e) {
        if (this.ended) return null;
        if ([403, 404, 409, 410].includes(e.status)) {
          await confirmDialog({ title: 'Không lấy được câu đố', text: 'Trận này không còn nhận câu trả lời nữa. ' + e.message, buttons: [{ label: 'Đã hiểu', value: 'ok', variant: 'primary' }] });
          return null;
        }
        await confirmDialog({ title: 'Không tải được câu đố', text: e.message + '. Kiểm tra kết nối rồi thử lại.', buttons: [{ label: 'Thử lại', value: 'retry', variant: 'primary' }] });
      }
    }
  }

  /** openPuzzle, but it gives up (null) when the match ends under the open panel. */
  async puzzleOrEnd(opts) {
    const r = await Promise.race([openPuzzle(opts), this.endSignal]);
    return this.ended ? null : r;
  }

  /** Lines this lock will send if answered cleanly, after cancelling your own pending rows. */
  expectedSend(L, clean) {
    const base = L.boss ? 4 : SEND_TABLE[Math.min(L.count, 4)];
    const bonus = clean && this.view.streak + 1 >= 3 ? 1 : 0;
    const total = base + bonus;
    const cancel = Math.min(this.view.pending.length, total);
    return { total, cancel, send: total - cancel };
  }

  async runLock() {
    if (this.ended || this.busy || this.frozen || this.conn !== 'open' || !this.server || this.view.phase !== 'locked') return;
    const L = this.view.lock;
    this.busy = true;
    this.frozen = true;
    this.puzzleOpen = true;
    this.sentBuf = null;
    this.paint();
    let outcome = null; // 'correct' | 'wrong'
    const rev0 = this.rev;
    const scoreBefore = this.view.score;
    try {
      await this.drainUnacked();
      // the Debugger is used up automatically by the lock it is open for: free hint level 2 (the next state confirms it)
      const useDbg = this.view.items.debugger > 0;
      const free = Game.freeHintLevel(this.view, useDbg);
      if (useDbg) {
        this.view.items.debugger--;
        this.paint();
        toast('Đã dùng Debugger: Gợi ý 2 miễn phí cho câu này.', 2800);
      }
      const parts = L.boss ? 2 : 1;
      let maxHint = 0;
      for (let i = 0; i < parts; i++) {
        const puzzle = await this.fetchPuzzle({ topic: L.topic, tier: L.boss ? 3 : L.tier, kind: 'rescue' });
        if (!puzzle || this.ended) return;
        const res = await this.puzzleOrEnd({
          puzzle,
          topic: L.topic,
          title: `${TOPIC_NAMES[L.topic]} · ${L.boss ? 'Boss' : `${L.count} hàng`}`,
          boss: L.boss ? `Boss ${i + 1}/2` : null,
          maxAttempts: 1,
          free,
          track: false,
          awardText: (h) => {
            if (i < parts - 1) return 'Đúng câu 1/2. Còn một câu nữa.';
            const e = this.expectedSend(L, h <= free);
            const cancelTxt = e.cancel ? `Hủy ${e.cancel} dòng đang chờ của bạn` + (e.send ? `, gửi ${e.send} dòng lỗi sang đối thủ` : '') : `Gửi ${e.send} dòng lỗi sang đối thủ`;
            return cancelTxt;
          },
        });
        if (!res || this.ended) return;
        maxHint = Math.max(maxHint, res.maxHint);
        if (!res.correct) {
          outcome = 'wrong';
          break;
        }
        outcome = 'correct';
      }
      this.puzzleOpen = false;
      if (outcome === 'correct') {
        sfx('clear', { streak: this.view.streak + 1 });
        const sentP = this.takeSent(1100);
        const stateP = this.waitState(rev0, 1600);
        await this.board.animateClear(L.cells, { color: `var(--cap-${L.topic})` });
        await stateP;
        const sent = await sentP;
        if (this.ended) return;
        this.frozen = false;
        this.rebuild();
        const gain = this.view.score - scoreBefore;
        if (gain > 0) toast(`+${gain} điểm`);
        if (sent) this.playSent(sent);
      } else {
        sfx('wrong');
        const stateP = this.waitState(rev0, 1600);
        await this.board.animateBug(L.cells);
        await stateP;
        if (this.ended) return;
        this.frozen = false;
        this.rebuild();
        toast('Hàng này thành dòng lỗi của bạn. Bạn không bị loại.', 3000);
      }
    } finally {
      this.puzzleOpen = false;
      this.frozen = false;
      this.busy = false;
      if (!this.ended && this.server) this.rebuild();
    }
  }

  async bugTap(bugId) {
    if (!this.canAct()) return;
    const bl = this.view.bugLines.find((b) => b.id === bugId);
    if (!bl) return;
    const ch = await confirmDialog({
      title: 'Sửa dòng lỗi?',
      text: 'Giải câu đố Debug để xóa dòng lỗi này. Trả lời sai thì dòng vẫn còn, bạn không bị loại.',
      buttons: [{ label: 'Sửa bug', value: 'go', variant: 'primary' }, { label: 'Để sau', value: 'no', variant: 'ghost' }],
    });
    if (ch !== 'go' || this.ended || !this.canAct()) return;
    this.busy = true;
    this.frozen = true;
    this.puzzleOpen = true;
    this.paint();
    const rev0 = this.rev;
    const scoreBefore = this.view.score;
    try {
      await this.drainUnacked();
      const puzzle = await this.fetchPuzzle({ topic: bl.topic, tier: 1, kind: 'debug', template_id: bl.templateId });
      if (!puzzle || this.ended) return;
      const res = await this.puzzleOrEnd({
        puzzle,
        topic: puzzle.topic || bl.topic,
        title: `Debug · ${TOPIC_NAMES[puzzle.topic || bl.topic]}`,
        tag: 'DEBUG',
        maxAttempts: 1,
        penalties: false,
        track: false,
        awardText: () => `+${Game.BUG_FIX_POINTS} điểm Redemption`,
      });
      if (!res || this.ended) return;
      this.puzzleOpen = false;
      const stateP = this.waitState(rev0, 1600);
      if (res.correct) {
        sfx('crack');
        await this.board.animateCrack(bl.cells);
        await stateP;
        if (this.ended) return;
        this.frozen = false;
        this.rebuild();
        toast(`Đã sửa dòng lỗi! +${Math.max(0, this.view.score - scoreBefore)} điểm`);
      } else {
        await stateP;
        if (this.ended) return;
        this.frozen = false;
        this.rebuild();
        toast('Chưa sửa được dòng lỗi. Dòng vẫn còn đó.');
      }
    } finally {
      this.puzzleOpen = false;
      this.frozen = false;
      this.busy = false;
      if (!this.ended && this.server) this.rebuild();
    }
  }

  // ---- drawing ------------------------------------------------------------------------------------------------
  paint(extra = {}) {
    const v = this.view;
    v.phase = this.phaseFor(v);
    this.board.render(v, { ...this.ui, ...extra });
    this.paintHud();
    this.paintBanner();
    this.paintMeter();
    this.paintBoardState();
  }

  paintHud() {
    const v = this.view;
    setScore(v.score);
    setStreak(v.streak);
    setStatus(v.bugLines.length ? 'warn' : 'ok');
  }

  paintBanner() {
    const v = this.view;
    const b = $('lock-banner');
    const locked = v.phase === 'locked' && v.lock;
    $('tray-zone').classList.toggle('is-locked', !!locked);
    b.hidden = !locked;
    if (!locked) {
      b.dataset.sig = '';
      return;
    }
    const L = v.lock;
    const canUndo = v.items.undo > 0;
    const sig = JSON.stringify([L.rows, L.cols, L.topic, canUndo, v.pending.length, v.items.debugger]);
    if (b.dataset.sig === sig) return;
    b.dataset.sig = sig;
    const e = this.expectedSend(L, v.streak + 1 >= 3);
    const tierText = L.boss ? 'Boss · 2 câu' : `Mức ${L.tier}`;
    b.className = 'lock-banner t-' + L.topic;
    const solve = keycap({ tag: 'button', topic: 'neutral', legend: 'Giải đố', legendClass: 'kb-label', variant: 'btn', enter: true });
    solve.type = 'button';
    solve.id = 'btn-solve';
    solve.addEventListener('click', () => this.runLock());
    b.replaceChildren(
      el('div', { class: 'lb-title' }, icon('lock', { size: 22 }), `${L.count >= 4 ? '4+' : L.count} hàng bị khóa`),
      el('div', { class: 'lb-sub' }, el('span', { class: 'chip', text: TOPIC_NAMES[L.topic] }), `${tierText} · đúng thì gửi tối đa ${e.total} dòng lỗi${v.items.debugger > 0 ? ' · dùng Debugger: Gợi ý 2 miễn phí' : ''}`),
      el('div', { class: 'lb-actions' }, solve,
        canUndo ? el('button', { class: 'btn', type: 'button', onclick: () => this.undo() }, icon('undo', { size: 16 }), 'Hoàn tác') : null));
  }

  paintBoardState() {
    const screen = $('screen-game');
    screen.classList.toggle('is-away', this.conn !== 'open');
    screen.classList.toggle('is-solving', this.puzzleOpen);
  }

  paintMeter() {
    const src = this.frozen && this.server ? this.server.pending : this.view.pending;
    const pend = src || [];
    const n = pend.length;
    const prev = this.meterPrev;
    for (let i = 0; i < METER_SLOTS; i++) {
      const seg = this.segs[i];
      const p = pend[i];
      if (p) {
        seg.classList.remove('out');
        seg.classList.add('on');
        seg.style.setProperty('--c', topicColor(p.topic));
      } else if (i < prev && !reducedMotion()) {
        seg.classList.remove('on');
        seg.classList.add('out'); // keeps its colour while it flashes away
      } else {
        seg.classList.remove('on', 'out');
        seg.style.removeProperty('--c');
      }
    }
    this.meterPrev = Math.min(n, METER_SLOTS);
    this.meterN.hidden = n === 0;
    this.meterN.textContent = n > METER_SLOTS ? `${n}` : String(n);
    // would landing these rows push a block off the top?
    let top = SIZE;
    outer: for (let r = 0; r < SIZE; r++) for (let c = 0; c < SIZE; c++) if (this.view.grid[r][c]) { top = r; break outer; }
    const danger = n > 0 && top < SIZE && n > top;
    // Show the danger on the board itself: the top n rows are where pending lines will push blocks off.
    // Code Rescue has no gravity, so players do not expect "the top" to matter; this makes it visible.
    const zone = Math.min(n, SIZE);
    for (const cell of document.querySelectorAll('#board .cell')) {
      const r = +cell.dataset.r;
      const inZone = r < zone;
      cell.classList.toggle('pvp-danger', inZone);
      cell.classList.toggle('pvp-doomed', inZone && !cell.classList.contains('empty'));
    }
    const meter = $('pvp-meter');
    meter.classList.toggle('danger', danger);
    meter.setAttribute('role', 'img');
    meter.setAttribute('aria-label', n ? `Dòng lỗi đang chờ: ${n}${danger ? '. Cảnh báo: khối có thể bị đẩy ra khỏi bàn' : ''}` : 'Không có dòng lỗi đang chờ');
  }

  paintOpp() {
    const o = this.opp;
    const op = this.opponent;
    const mk = this.isMisaki;
    this.poNick.textContent = mk ? this.oppLabel() : op.nickname || 'Đối thủ';
    this.poAv.hidden = !mk;
    this.poAi.hidden = !mk;
    this.poBot.hidden = !op.bot || mk;
    if (op.rating != null && !mk) {
      this.poRating.hidden = false;
      this.poRating.textContent = String(op.rating);
      this.poRating.title = 'Xếp hạng đối kháng';
    } else this.poRating.hidden = true;
    $('pvp-opp').classList.toggle('is-bot', !!op.bot);
    const grid = o?.grid;
    for (let r = 0; r < SIZE; r++)
      for (let c = 0; c < SIZE; c++) {
        const g = grid?.[r]?.[c];
        const node = this.miniCells[r * SIZE + c];
        const k = !g ? '' : g === 'bug' || g.bug ? 'bug' : typeof g === 'string' ? g : g.topic;
        if (node.dataset.k !== k) node.dataset.k = k;
      }
    let filled = 0;
    for (const c of this.miniCells) if (c.dataset.k) filled++;
    this.mini.setAttribute('aria-label', `Bàn của đối thủ: ${filled} ô đã đặt`);
    this.poScore.textContent = String(o?.score ?? 0);
    const pend = nOf(o?.pending);
    this.poPend.textContent = String(pend);
    this.poPendWrap.classList.toggle('is-hot', pend > 0);
    const away = o ? o.connected === false : op.connected === false;
    const solving = !!o?.lock && !away;
    this.poBoard.classList.toggle('is-solving', solving);
    this.poBoard.classList.toggle('is-away', away);
    this.oppOvl.hidden = !away;
    let text = 'Đang xếp khối';
    let color = 'var(--ok)';
    let blink = false;
    if (away) {
      text = 'Mất kết nối';
      color = 'var(--crash)';
    } else if (o?.phase === 'over') {
      text = 'Hết nước đi';
      color = 'var(--crash)';
    } else if (solving) {
      text = 'Đang giải đố…';
      color = 'var(--warn)';
      blink = true;
    } else if (!this.started) {
      text = op.connected === false ? 'Chưa vào trận' : 'Đã sẵn sàng';
    }
    this.poLed.style.setProperty('--c', color);
    this.poLed.classList.toggle('on', true);
    this.poLed.classList.toggle('rk-pulse', blink);
    if (this.poStateT.textContent !== text) this.poStateT.textContent = text;
    this.tickAway();
  }

  tickAway() {
    if (!this.oppAway || this.oppOvl.hidden) return;
    const left = Math.max(0, Math.ceil((this.oppAway.until - Date.now()) / 1000));
    this.oppOvlN.textContent = `${left}s`;
    const t = 'Đối thủ mất kết nối…';
    if (this.oppOvlT.textContent !== t) this.oppOvlT.textContent = t;
  }

  // ---- Misaki's coach (training mode only) ---------------------------------------------------------------------
  buildCoach() {
    const root = $('pvp-coach');
    root.hidden = !this.training;
    if (!this.training || this.coachBuilt) return;
    this.coachBuilt = true;
    this.coachText = el('p', { class: 'coach-text', role: 'status', 'aria-live': 'polite', text: 'Tôi sẽ nhắc bạn khi có điều cần để ý. Muốn biết nên đặt khối ở đâu, bấm “Gợi ý nước đi”.' });
    this.coachBubble = el('div', { class: 'coach-bubble is-dim' }, misakiAvatar({ cls: 'coach-av' }), this.coachText);
    this.hintBtn = keycap({
      tag: 'button', topic: 'neutral', variant: 'btn', legendClass: 'kb-label', cls: 'key-sm coach-hint',
      legend: el('span', { class: 'coach-hint-in' }, icon('bulb', { size: 16 }), 'Gợi ý nước đi'),
    });
    this.hintBtn.type = 'button';
    this.hintBtn.addEventListener('click', () => this.requestHint());
    root.replaceChildren(
      el('div', { class: 'coach-top' },
        el('span', { class: 'coach-name', text: 'MISAKI' }),
        el('span', { class: 'po-tag po-train', text: 'LUYỆN TẬP' }),
        this.hintBtn),
      this.coachBubble);
  }

  /** Marks cells on your board with a soft outline: `kind` 'coach' (Misaki's note) or 'sug' (a suggested move). */
  markCells(cells, { color, ms, kind }) {
    this.clearMarks(kind);
    const boardEl = $('board');
    for (const [r, c] of cells || []) {
      if (!(r >= 0 && r < SIZE && c >= 0 && c < SIZE)) continue;
      const n = el('i', { class: 'coach-frame ' + kind, 'aria-hidden': 'true' });
      n.style.gridRow = String(r + 1);
      n.style.gridColumn = String(c + 1);
      n.style.color = color;
      boardEl.append(n);
      this.marks.push({ el: n, kind });
    }
    clearTimeout(this['markT_' + kind]);
    this['markT_' + kind] = setTimeout(() => this.clearMarks(kind), ms);
  }

  clearMarks(kind) {
    clearTimeout(this['markT_' + kind]);
    this.marks = this.marks.filter((m) => {
      if (m.kind !== kind) return true;
      m.el.remove();
      return false;
    });
    if (kind === 'sug') for (const sl of $('tray').children) sl.classList.remove('is-suggested');
  }

  showCoach(text, cells) {
    if (!this.training || !this.coachText) return;
    this.coachText.textContent = text || '';
    this.coachBubble.classList.remove('is-dim');
    anim(this.coachBubble, [{ opacity: 0, transform: 'translateY(6px)' }, { opacity: 1, transform: 'none' }], { duration: 240, easing: EASE.out });
    clearTimeout(this.dimT);
    this.dimT = setTimeout(() => this.coachBubble.classList.add('is-dim'), COACH_DIM_MS);
    if (cells && cells.length) this.markCells(cells, { color: 'var(--text)', ms: COACH_CELLS_MS, kind: 'coach' });
  }

  onCoach(msg) {
    if (!this.training || this.ended || !msg.text) return;
    this.showCoach(String(msg.text), Array.isArray(msg.cells) ? msg.cells : null);
  }

  requestHint() {
    if (!this.training || this.hintWait || this.ended || !this.started) return;
    if (this.conn !== 'open' || !this.client.send({ t: 'suggest' })) {
      toast('Mất kết nối, chưa gửi được yêu cầu gợi ý.', 2000);
      return;
    }
    this.hintWait = true;
    this.hintBtn.setAttribute('aria-disabled', 'true');
    this.hintBtn.classList.add('is-off');
    this.timers.push(setTimeout(() => {
      this.hintWait = false;
      this.hintBtn.removeAttribute('aria-disabled');
      this.hintBtn.classList.remove('is-off');
    }, SUGGEST_COOLDOWN_MS));
  }

  onSuggestion(msg) {
    if (!this.training || this.ended) return;
    if (msg.none) {
      this.clearMarks('sug');
      this.showCoach(msg.why || 'Không còn chỗ nào đặt vừa. Hãy giải hàng hoặc dùng vật phẩm.');
      return;
    }
    const piece = this.view.tray[msg.i];
    let cells = Array.isArray(msg.cells) ? msg.cells : null;
    if (!cells && piece) cells = piece.cells.map(([dr, dc]) => [msg.r + dr, msg.c + dc]);
    this.markCells(cells, { color: piece ? topicColor(piece.topic) : 'var(--mustard)', ms: SUGGEST_MS, kind: 'sug' });
    const slot = $('tray').children[msg.i];
    if (slot) slot.classList.add('is-suggested');
    this.showCoach(msg.why || '');
  }

  // ---- clock, overtime, countdown ----------------------------------------------------------------------------
  tick() {
    if (this.ended) return;
    const now = Date.now();
    if (this.started) {
      const s = (now - this.t0) / 1000;
      this.poClock.textContent = fmtClock(s);
      const ot = s >= OVERTIME_S;
      this.poOt.classList.toggle('is-off', !ot);
      this.poClock.parentElement.classList.toggle('is-ot', ot);
    } else if (this.countDeadline) {
      const left = Math.ceil((this.countDeadline - now) / 1000);
      if (left > 0 && left !== this.countShown) {
        this.countShown = left;
        this.showOverlay('count', left);
        sfx('tick');
      }
    }
    this.tickAway();
  }

  showOverlay(kind, n) {
    const o = this.ovl;
    o.hidden = false;
    o.dataset.kind = kind;
    o.classList.remove('is-go');
    if (kind === 'count') {
      const k = keycap({ topic: TOPICS[n % 4], legend: String(n), legendClass: 'legend legend-c', cls: 'pvp-count-key' });
      o.replaceChildren(el('p', { class: 'pvp-vs', text: `${this.you.nickname || 'Bạn'}  vs  ${this.oppLabel()}` }), k,
        el('p', { class: 'pvp-count-hint', text: 'Cùng một bộ khối. Giải đố đúng để gửi dòng lỗi.' }));
      anim(k, [{ transform: 'scale(1.35)', opacity: 0 }, { transform: 'scale(1)', opacity: 1 }], { duration: 260, easing: EASE.out });
    } else if (kind === 'wait') {
      o.replaceChildren(el('p', { class: 'pvp-vs', text: `${this.you.nickname || 'Bạn'}  vs  ${this.oppLabel()}` }),
        el('p', { class: 'pvp-wait', role: 'status', text: 'Đang chuẩn bị trận…' }));
    } else if (kind === 'reconnect') {
      o.replaceChildren(el('i', { class: 'led on rk-pulse', style: { '--c': 'var(--warn)' } }),
        el('p', { class: 'pvp-wait', role: 'status', text: 'Đang kết nối lại…' }),
        el('p', { class: 'pvp-count-hint', text: 'Bàn của bạn được giữ nguyên trong lúc chờ.' }));
    }
  }

  hideOverlayAfterGo() {
    const o = this.ovl;
    if (o.dataset.kind === 'reconnect') return;
    sfx('go');
    o.dataset.kind = 'go';
    const g = keycap({ topic: 'variables', legend: 'GO', legendClass: 'legend legend-c', cls: 'pvp-count-key is-go' });
    o.replaceChildren(g);
    anim(g, [{ transform: 'scale(.8)', opacity: 0 }, { transform: 'scale(1.1)', opacity: 1, offset: 0.4 }, { transform: 'scale(1)', opacity: 1 }], { duration: 300, easing: EASE.out });
    setTimeout(() => {
      if (o.dataset.kind === 'go') o.hidden = true;
    }, 520);
  }

  // ---- connection ---------------------------------------------------------------------------------------------
  onConnection(status, info = {}) {
    if (this.ended) return;
    if (status === 'reconnecting') {
      if (this.conn === 'open') toast('Mất kết nối. Đang thử lại…', 2200);
      this.conn = 'reconnecting';
      this.ui.bomb = false;
      this.showOverlay('reconnect');
      this.paint();
    } else if (status === 'open' && this.conn !== 'open') {
      this.conn = 'open';
      this.ovl.hidden = true;
      this.ovl.dataset.kind = '';
      if (info.reconnected) toast('Đã kết nối lại.', 1800);
      this.paint();
    } else if (status === 'failed') {
      this.onEnd({ t: 'end', winner: 'unknown', reason: 'link_lost', you: {}, opponent: {} });
    }
  }

  // ---- animations ---------------------------------------------------------------------------------------------
  pulse(node, name, ms) {
    node.classList.remove('pm-' + name);
    void node.offsetWidth;
    node.classList.add('pm-' + name);
    setTimeout(() => node.classList.remove('pm-' + name), ms);
  }

  floatAt(text, x, y, color) {
    const n = el('div', { class: 'float-pts', text, 'aria-hidden': 'true', style: { left: x + 'px', top: y + 'px', color } });
    document.body.append(n);
    anim(n, [
      { transform: 'translate(-50%, 0)', opacity: 0 },
      { transform: 'translate(-50%, -8px)', opacity: 1, offset: 0.2 },
      { transform: 'translate(-50%, -26px)', opacity: 1, offset: 0.65 },
      { transform: 'translate(-50%, -26px)', opacity: 0 },
    ], { duration: 800, easing: EASE.out, fill: 'forwards' }).finished.then(() => n.remove());
  }

  /** A "+N" token that travels from one element to another (fades in place under reduced motion). */
  fly(text, fromEl, toEl, color) {
    if (!fromEl || !toEl) return;
    const a = fromEl.getBoundingClientRect();
    const b = toEl.getBoundingClientRect();
    if (!a.width || !b.width) return;
    const x0 = a.left + a.width / 2;
    const y0 = a.top + a.height / 2;
    const x1 = b.left + b.width / 2;
    const y1 = b.top + b.height / 2;
    const n = el('div', { class: 'float-pts pvp-fly', text, 'aria-hidden': 'true', style: { left: '0px', top: '0px', color } });
    document.body.append(n);
    if (reducedMotion()) {
      n.style.left = x1 + 'px';
      n.style.top = y1 + 'px';
      anim(n, [{ opacity: 0 }, { opacity: 1, offset: 0.3 }, { opacity: 0 }], { duration: 150, fill: 'forwards' }).finished.then(() => n.remove());
      return;
    }
    anim(n, [
      { transform: `translate(${x0}px, ${y0}px) translate(-50%, -50%) scale(.7)`, opacity: 0 },
      { transform: `translate(${x0}px, ${y0}px) translate(-50%, -50%) scale(1.25)`, opacity: 1, offset: 0.18 },
      { transform: `translate(${x1}px, ${y1}px) translate(-50%, -50%) scale(1)`, opacity: 1, offset: 0.85 },
      { transform: `translate(${x1}px, ${y1}px) translate(-50%, -50%) scale(.8)`, opacity: 0 },
    ], { duration: 720, easing: 'cubic-bezier(0.45, 0, 0.2, 1)', fill: 'forwards' }).finished.then(() => n.remove());
  }

  /** Rows rise from the bottom: everything shifts up k rows, the new ERR rows slide in under it. */
  playLand(k) {
    sfx('land');
    const m = this.board.metrics();
    const pitch = m.sy || 40;
    const rise = pitch * Math.min(k, 3);
    this.pulse($('pvp-meter'), 'land', 500);
    for (let r = 0; r < SIZE; r++)
      for (let c = 0; c < SIZE; c++) {
        const g = this.view.grid[r][c];
        if (!g) continue;
        const fresh = r >= SIZE - k;
        const key = this.board.keyOf(r, c);
        anim(key, [
          { transform: `translateY(${rise}px)`, opacity: fresh ? 0 : 1 },
          { transform: 'translateY(0)', opacity: 1 },
        ], { duration: 360, delay: fresh ? c * 14 : 0, easing: EASE.out, fill: 'backwards' });
        if (fresh) {
          const top = key.firstElementChild;
          anim(top, [{ transform: 'translateY(0)' }, { transform: 'translateY(3px)', offset: 0.4 }, { transform: 'translateY(0)' }], { duration: 110, delay: 340 + c * 14, easing: EASE.out });
        }
      }
    anim(this.board.boardEl, [{ transform: 'translateY(0)' }, { transform: 'translateY(3px)', offset: 0.5 }, { transform: 'translateY(0)' }], { duration: 160, delay: 300, easing: EASE.out });
    toast(`${k} dòng lỗi vừa rơi xuống bàn của bạn`, 2000);
  }

  // ---- leaving / ending ---------------------------------------------------------------------------------------
  async requestExit() {
    if (this.ended) return this.o.onHome();
    if (this.exiting) return;
    if (!this.started || this.conn !== 'open') return this.o.onHome();
    this.exiting = true;
    const ch = await confirmDialog({
      title: 'Bỏ cuộc trận này?',
      text: 'Thoát lúc này là chịu thua. Đối thủ sẽ thắng.',
      buttons: [{ label: 'Bỏ cuộc', value: 'go', variant: 'danger' }, { label: 'Chơi tiếp', value: 'no', variant: 'ghost' }],
    });
    this.exiting = false;
    if (ch !== 'go' || this.ended) return;
    if (!this.client.send({ t: 'resign' })) return this.o.onHome();
    this.timers.push(setTimeout(() => { if (!this.ended) this.o.onHome(); }, 2500));
  }

  forceCloseOverlays() {
    for (const id of ['modal-root', 'dialog-root']) $(id).replaceChildren();
    $('app').inert = false;
    $('screen-game').classList.remove('dim');
    document.body.classList.remove('modal-open');
  }

  async onEnd(msg) {
    if (this.ended) return;
    this.ended = true;
    this.client.markFinished();
    this.resolveEnd(null);
    this.forceCloseOverlays();
    this.puzzleOpen = false;
    this.frozen = false;
    this.ui = { selected: null, bomb: false };
    this.ovl.hidden = true;
    this.clearMarks('coach');
    this.clearMarks('sug');
    for (const w of this.stateWaiters.splice(0)) w(this.rev ?? 0, true);
    for (const w of this.sentWaiters.splice(0)) w(null);
    api.setMatchContext(null);
    clearTicket();
    const outcome = msg.winner === 'you' ? 'win' : msg.winner === 'opponent' ? 'lose' : msg.winner === 'draw' ? 'draw' : 'unknown';
    if (this.server && !this.frozen) this.view = this.cloneView(this.server);
    this.paint();
    if (msg.rating && msg.rating.after != null) setRating(msg.rating.after);
    if (outcome === 'lose' && msg.reason === 'topped_out') await this.board.animateCrash();
    else await wait(outcome === 'unknown' ? 0 : 650);
    sfx(outcome === 'win' ? 'win' : outcome === 'lose' ? 'lose' : 'chime');
    this.showEnd(msg, outcome);
  }

  teardown() {
    for (const t of this.timers) { clearInterval(t); clearTimeout(t); }
    this.timers = [];
    window.removeEventListener('beforeunload', this.onUnload);
    this.forceCloseOverlays();
    api.setMatchContext(null);
    for (const cell of document.querySelectorAll('#board .cell')) cell.classList.remove('pvp-danger', 'pvp-doomed');
    if (this.prevHandlers) this.board.h = this.prevHandlers;
    const screen = $('screen-game');
    screen.classList.remove('is-pvp', 'is-away', 'is-solving');
    for (const id of ['pvp-opp', 'pvp-meter', 'pvp-ovl', 'pvp-coach']) $(id).hidden = true;
    this.clearMarks('coach');
    this.clearMarks('sug');
    clearTimeout(this.dimT);
    $('lock-banner').dataset.sig = '';
    this.resolveEnd(null);
    this.ended = true;
  }

  // ---- rematch (private duels: the server keeps the socket open after `end`) --------------------------------------
  paintEndActions() {
    const act = $('pe-actions');
    const outcome = this.endOutcome;
    const home = el('button', { class: 'btn', type: 'button', text: 'Về trang chủ', onclick: () => this.o.onHome() });
    if (outcome === 'unknown') return act.replaceChildren(home);
    if (this.isMisaki) return this.paintMisakiActions(act, outcome, home);
    const waiting = !!this.rematching;
    const again = keycap({ tag: 'button', topic: 'neutral', legend: waiting ? 'Đang chờ đối thủ…' : 'Đấu lại', legendClass: 'kb-label', variant: 'btn', enter: !waiting });
    again.type = 'button';
    again.disabled = waiting;
    again.addEventListener('click', () => this.requestRematch());
    const kids = [again];
    if (waiting) kids.push(el('button', { class: 'btn', type: 'button', text: 'Tạo mã trận mới', onclick: () => this.fallbackRematch() }));
    kids.push(home);
    act.replaceChildren(...kids);
  }

  /** End-screen buttons against Misaki: same level again, the next level once unlocked, real match out of training. */
  paintMisakiActions(act, outcome, home) {
    const mk = this.endMsg?.misaki || {};
    const level = Number(mk.level) || Number(this.opponent.misaki) || 1;
    const next = Number(mk.unlocked_now) || 0;
    const training = this.training;
    const go = (misaki, train) => () => this.o.onMisaki({ misaki, training: train });
    const primary = (label, fn) => {
      const k = keycap({ tag: 'button', topic: 'neutral', legend: label, legendClass: 'kb-label', variant: 'btn', enter: true });
      k.type = 'button';
      k.addEventListener('click', fn);
      return k;
    };
    const plain = (label, fn) => el('button', { class: 'btn', type: 'button', text: label, onclick: fn });
    const kids = [];
    if (outcome === 'win' && next) {
      kids.push(primary('Đấu ngay', go(next, false)), plain('Đấu lại', go(level, false)));
    } else if (outcome === 'win') {
      kids.push(training ? primary('Đấu thật', go(level, false)) : primary('Đấu lại', go(level, false)));
      if (training) kids.push(plain('Luyện tập lại', go(level, true)));
    } else {
      kids.push(primary('Thử lại', go(level, training)));
      if (training) kids.push(plain('Đấu thật', go(level, false)));
    }
    kids.push(home);
    act.replaceChildren(...kids);
  }

  requestRematch() {
    if (this.rematching) return;
    if (!this.canRematch) return this.o.onRematch(); // quick match / bot: a fresh search or bot match
    if (!this.client.send({ t: 'rematch' })) return this.fallbackRematch();
    this.rematching = { at: Date.now(), you: true, opponent: false };
    this.paintEndActions();
    this.paintRematchNote();
    this.timers.push(setInterval(() => {
      if (!this.rematching) return;
      if (Date.now() - this.rematching.at >= 60000) return this.fallbackRematch(true);
      this.paintRematchNote();
    }, 500));
    $('pe-actions').querySelector('.btn')?.focus({ preventScroll: true });
  }

  onRematchStatus(msg) {
    if (!this.ended || !this.rematching) {
      // the opponent asked first: remember it so the note can say so
      this.oppWantsRematch = !!msg.opponent;
      if (this.ended && $('pe-note')) $('pe-note').textContent = msg.opponent ? 'Đối thủ muốn đấu lại. Bấm "Đấu lại" để bắt đầu.' : '';
      return;
    }
    this.rematching.you = msg.you !== false;
    this.rematching.opponent = !!msg.opponent;
    this.paintRematchNote();
  }

  paintRematchNote() {
    const r = this.rematching;
    if (!r) return;
    const left = Math.max(0, 60 - Math.floor((Date.now() - r.at) / 1000));
    $('pe-note').replaceChildren(
      el('span', { text: r.opponent ? 'Đối thủ đã đồng ý. Đang bắt đầu trận mới…' : 'Đã gửi lời mời đấu lại. Đang chờ đối thủ đồng ý.' }),
      el('span', { class: 'pe-rm', text: ` Bạn: sẵn sàng · Đối thủ: ${r.opponent ? 'sẵn sàng' : 'chưa'} · còn ${left}s`, 'aria-hidden': 'true' }));
  }

  /** The opponent did not answer (or the link is gone): fall back to a fresh private duel with a new code. */
  fallbackRematch(timedOut = false) {
    this.rematching = null;
    if (timedOut) toast('Đối thủ chưa đồng ý. Tạo mã trận mới để mời lại.', 3200);
    this.o.onRematch();
  }

  // ---- end screen ---------------------------------------------------------------------------------------------
  showEnd(msg, outcome) {
    for (const t of this.timers) { clearInterval(t); clearTimeout(t); }
    this.timers = [];
    window.removeEventListener('beforeunload', this.onUnload);
    const title = $('pe-title');
    const sub = $('pe-sub');
    const badge = $('pe-badge');
    this.endMsg = msg;
    const mkLevel = Number(msg.misaki?.level) || Number(this.opponent.misaki) || 0;
    let head = { win: 'Bạn thắng!', lose: 'Bạn thua', draw: 'Hòa', unknown: 'Mất kết nối' }[outcome];
    if (this.isMisaki && outcome === 'win') head = `Bạn đã thắng ${misakiTitle(mkLevel)}!`;
    const cancelled = msg.reason === 'server_restart';
    title.textContent = cancelled ? 'Trận bị hủy' : head;
    let reason = (REASON[outcome] && REASON[outcome][msg.reason]) || '';
    if (outcome === 'unknown') reason = 'Không kết nối lại được máy chủ. Nếu bạn vắng mặt quá 20 giây, bạn bị tính là thua.';
    if (!reason && msg.reason) reason = 'Trận đã kết thúc.';
    if (this.isMisaki) reason = reason.replace(/^Đối thủ/, 'Misaki');
    sub.textContent = reason;
    const color = cancelled ? 'var(--warn)' : outcome === 'win' ? 'var(--ok)' : outcome === 'lose' ? 'var(--crash)' : 'var(--warn)';
    // replaceChildren() would print a null argument as the text "null": only pass real nodes
    const badgeText = this.isMisaki ? `${this.training ? 'LUYỆN TẬP' : 'ĐỐI KHÁNG'} · ${misakiTitle(mkLevel).toUpperCase()}` : `ĐỐI KHÁNG · ${LEVEL_NAME[this.level] || this.level}`;
    badge.replaceChildren(...[el('i', { class: 'led on', style: { '--c': color } }), badgeText,
      this.isMisaki ? el('span', { class: 'po-tag po-ai', text: 'AI' }) : null,
      api.isMock ? el('span', { class: 'po-tag po-mock', text: 'mô phỏng' }) : null].filter((x) => x != null));
    $('pe-card').dataset.outcome = cancelled ? 'cancel' : outcome;

    // rating
    const rp = $('pe-rating');
    if (msg.rating && msg.rating.before != null && msg.rating.after != null) {
      const d = msg.rating.after - msg.rating.before;
      rp.hidden = false;
      rp.replaceChildren(
        el('span', { class: 'pe-rate-l', text: 'Xếp hạng đối kháng' }),
        el('p', { class: 'pe-rate' },
          el('span', { class: 'pe-rate-b', text: String(msg.rating.before) }), el('span', { class: 'pe-arrow', 'aria-hidden': 'true', text: '→' }),
          el('b', { class: 'pe-rate-a', text: String(msg.rating.after) }),
          el('span', { class: 'pe-delta ' + (d > 0 ? 'up' : d < 0 ? 'down' : ''), text: (d > 0 ? '+' : d < 0 ? '−' : '±') + Math.abs(d) })));
    } else if (this.isMisaki) {
      rp.hidden = false;
      const unlocked = Number(msg.misaki?.unlocked_now) || 0;
      const note = this.training ? 'Luyện tập không tính điểm và không mở khoá cấp mới.' : 'Đấu với Misaki không tính xếp hạng.';
      rp.replaceChildren(...[
        unlocked ? el('p', { class: 'pe-unlock', role: 'status' }, misakiAvatar({ cls: 'pe-unlock-av' }), el('span', {}, el('b', { text: 'Đã mở khoá: ' + misakiTitle(unlocked) }), el('i', { text: 'Cấp mới đã sẵn sàng.' }))) : null,
        el('p', { class: 'rk-note', text: note }),
      ].filter((x) => x != null));
      if (unlocked) anim(rp.firstElementChild, [{ opacity: 0, transform: 'scale(.94)' }, { opacity: 1, transform: 'scale(1.03)', offset: 0.6 }, { opacity: 1, transform: 'none' }], { duration: 420, delay: 200, easing: EASE.out, fill: 'backwards' });
    } else if (this.opponent.bot) {
      rp.hidden = false;
      rp.replaceChildren(el('p', { class: 'rk-note', text: 'Trận đấu với máy không tính xếp hạng.' }));
    } else if (cancelled) {
      rp.hidden = false;
      rp.replaceChildren(el('p', { class: 'rk-note', text: 'Xếp hạng không thay đổi.' }));
    } else {
      rp.hidden = true;
      rp.replaceChildren();
    }

    // both players side by side
    const tbl = $('pe-table');
    const me = msg.you || {};
    const op = msg.opponent || {};
    const num = (v) => (v == null ? '–' : String(v));
    const win = outcome === 'win' ? 'you' : outcome === 'lose' ? 'opp' : '';
    const row = (label, a, b) => el('tr', {}, el('th', { scope: 'row', text: label }), el('td', { text: num(a) }), el('td', { text: num(b) }));
    tbl.replaceChildren(
      el('caption', { class: 'sr-only', text: 'So sánh hai người chơi' }),
      el('thead', {}, el('tr', {},
        el('td', {}),
        el('th', { scope: 'col', class: win === 'you' ? 'is-win' : '' }, el('span', { class: 'pe-who', text: this.you.nickname || 'Bạn' }), el('span', { class: 'pe-you', text: 'bạn' })),
        el('th', { scope: 'col', class: win === 'opp' ? 'is-win' : '' }, el('span', { class: 'pe-who', text: this.oppLabel() }), this.isMisaki ? el('span', { class: 'po-tag po-ai', text: 'AI' }) : this.opponent.bot ? el('span', { class: 'po-tag po-bot', text: 'MÁY' }) : null))),
      el('tbody', {},
        row('Điểm', me.score, op.score),
        row('Dòng đã gửi', me.sent, op.sent),
        row('Dòng nhận', me.received, op.received),
        row('Hàng đã gỡ', me.locks, op.locks)));
    tbl.hidden = outcome === 'unknown';

    this.endOutcome = outcome;
    this.canRematch = !!this.o.rematch && outcome !== 'unknown' && !cancelled && this.client.open;
    this.paintEndActions();
    $('pe-note').textContent = this.canRematch ? 'Đấu lại với bạn bè: cả hai cùng bấm "Đấu lại" trong 60 giây.' : this.o.rematchNote ? this.o.rematchNote() : '';
    this.o.show('screen-pvp-end');
    document.title = 'Kết quả đối kháng — Syntax Stack';
    title.focus({ preventScroll: true });
  }
}
