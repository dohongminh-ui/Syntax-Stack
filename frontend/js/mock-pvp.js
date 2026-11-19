// Mock of the real-time 1v1 server (?mock=1 only, docs/pvp.md). A fake WebSocket speaks the same JSON protocol as the
// real one and runs both games in the browser: you, and a fake opponent that places pieces, answers locks after a
// "thinking" delay and sends bug lines. Everything is labelled "mô phỏng" in the UI.
//
// QA switches (URL): ?pvpwait=30 quick match takes 30 s to find someone (to see the "Đấu với Misaki" offer)
//   ?pvpot=20 overtime starts at 0:20   ?pvpdrop=1 drops your socket once, 15 s into the match
//   ?pvpoppdrop=1 the opponent drops for ~12 s   ?pvpaggr=1 the opponent sends lines fast and never misses
//   ?pvpitems=1 start with one of every item   ?pvpfail=429 queue / private / bot answer 429
//   Misaki: ?mkunlock=3 levels 1..3 are open (default: what your mock wins unlocked)   ?mkend=win|lose ends a Misaki match
//   after 20 s so the end screens (and the unlock line) can be seen   ?mkcoach=1 training: the coach speaks every kind every 5 s
import * as Game from './game.js';
import { mulberry } from './rng.js';
import { TOPICS } from './pieces.js';

const SIZE = 8;
const SEND = [0, 1, 2, 3, 4];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const fail = (status, detail) => Object.assign(new Error(detail), { status });
const qs = () => new URLSearchParams(location.search);
const rand = (a, b) => a + Math.random() * (b - a);
const pick = (a) => a[Math.floor(Math.random() * a.length)];
const ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
const ANIMALS = ['Mèo', 'Cáo', 'Gấu', 'Hổ', 'Cú', 'Rùa', 'Thỏ', 'Sói'];
const COLORS = ['Xanh', 'Đỏ', 'Vàng', 'Tím', 'Cam', 'Hồng', 'Nâu', 'Bạc'];
const humanName = () => `${pick(ANIMALS)} ${pick(COLORS)} ${10 + Math.floor(Math.random() * 90)}`;
const TEMPLATE = { variables: 'var_name_bug', conditions: 'cond_colon_bug', loops: 'loop_range_bug', functions: 'func_return_bug' };
const ACCURACY = { beginner: 0.7, intermediate: 0.8, advanced: 0.88 };
const RATING_KEY = 'syntaxstack.pvp.rating';
const MK_KEY = 'syntaxstack.mock.misaki';
const MK_NAMES = ['', 'Tập sự', 'Khá', 'Giỏi', 'Bậc thầy'];
const MK_ACC = [0, 0.6, 0.72, 0.84, 0.93];
const MK_PACE = [0, 1.7, 1.3, 1, 0.7]; // multiplies the fake opponent's think time
const TOPIC_VI = { variables: 'Biến', conditions: 'Điều kiện', loops: 'Vòng lặp', functions: 'Hàm' };
// Misaki's coaching lines (a short copy of backend/content/misaki_coach.yaml; the server picks the real ones)
const COACH = {
  danger: ['Cẩn thận! {n} dòng lỗi sắp đẩy bàn lên. Dọn các ô đỏ ở trên cùng trước nhé.', 'Vùng đỏ là chỗ sắp bị đẩy ra ngoài. Đừng đặt khối ở {n} hàng trên cùng lúc này.'],
  incoming: ['Đối thủ vừa gửi dòng lỗi! Chúng xếp hàng ở thanh bên cạnh, bạn còn thời gian chặn.'],
  cancel: ['Tuyệt! Bạn vừa chặn được {n} dòng lỗi. Tấn công cũng là phòng thủ đấy.'],
  streak: ['{n} câu đúng liên tiếp! Giữ chuỗi này để gửi thêm dòng lỗi sang đối thủ.'],
  wrong: ['Không sao, sai là để học. Chạm vào dòng lỗi mới để sửa, hoặc hỏi tôi “Vì sao mình sai?”.', 'Hàng đó thành dòng lỗi rồi. Sửa nó bằng một câu cùng chủ đề {topic} nhé, bạn làm được.'],
  bugline: ['Bạn còn một dòng lỗi chưa sửa. Chạm vào nó: sửa xong là bàn rộng thêm một hàng.'],
  nofit_risk: ['Chỉ còn một khối đặt vừa thôi. Ưu tiên giải hàng để mở thêm chỗ.'],
  good: ['Đẹp quá! {n} hàng cùng lúc gửi đi nhiều dòng lỗi hơn.'],
};
const WHY = {
  line: 'Đặt ở đây sẽ hoàn thành {n} hàng.',
  safe: 'Chỗ này giữ phía trên trống và không tạo lỗ hổng.',
  danger: 'Đặt ở đây để tránh vùng đỏ sắp bị đẩy lên.',
  fit: 'Chỗ này để lại nhiều không gian nhất cho các khối sau.',
  none: 'Không còn chỗ nào đặt vừa. Hãy giải hàng hoặc dùng vật phẩm.',
};
const fill = (t, v = {}) => t.replace(/\{(\w+)\}/g, (_, k) => v[k] ?? '');
const mkRead = () => {
  let d = null;
  try { d = JSON.parse(localStorage.getItem(MK_KEY)); } catch { /* ignore */ }
  d = d && typeof d === 'object' ? d : { unlocked: 1, wins: {}, games: {} };
  const q = Number(qs().get('mkunlock')) || 1;
  return { unlocked: Math.min(4, Math.max(Number(d.unlocked) || 1, q)), wins: d.wins || {}, games: d.games || {} };
};
const mkWrite = (d) => {
  try { localStorage.setItem(MK_KEY, JSON.stringify(d)); } catch { /* storage blocked */ }
};
const SNAP_KEY = 'syntaxstack.mock.pvp';
const readRating = () => {
  try { return Number(localStorage.getItem(RATING_KEY)) || 1000; } catch { return 1000; }
};

// ---- HTTP side: tickets -------------------------------------------------------------------------------------------
const tickets = new Map(); // ticket -> { kind, level, nickname, code?, hostNick? }
const duels = new Map(); // private code -> { level, host }
let seq = 1;

function guard() {
  const f = qs().get('pvpfail');
  if (f) throw fail(Number(f) || 500, 'Lỗi mô phỏng');
}

export async function pvpQueue(body) {
  await sleep(180);
  guard();
  const ticket = 'mock-q-' + seq++;
  tickets.set(ticket, { kind: 'quick', level: body.level, nickname: body.nickname });
  return { ticket };
}

export async function pvpLeaveQueue(ticket) {
  await sleep(60);
  tickets.delete(ticket);
  return null;
}

export async function pvpPrivate(body) {
  await sleep(220);
  guard();
  const code = Array.from({ length: 5 }, () => ALPHABET[Math.floor(Math.random() * ALPHABET.length)]).join('');
  duels.set(code, { level: body.level, host: body.nickname });
  const ticket = 'mock-p-' + seq++;
  tickets.set(ticket, { kind: 'private', level: body.level, nickname: body.nickname, code });
  return { code, ticket, url: `${location.origin}/?mock=1&duel=${code}` };
}

export async function pvpJoinPrivate(code, body) {
  await sleep(220);
  guard();
  if (code === 'NOPE0' || code === 'NOPE1') throw fail(404, 'Không tìm thấy trận');
  if (code === 'FULL0') throw fail(409, 'Trận đã đủ người');
  if (code === 'GONE0') throw fail(410, 'Mã đã hết hạn');
  const d = duels.get(code);
  const ticket = 'mock-j-' + seq++;
  tickets.set(ticket, { kind: 'join', level: d?.level || 'beginner', nickname: body.nickname, code, hostNick: d?.host && d.host !== body.nickname ? d.host : humanName() });
  return { ticket };
}

/** body: { level, nickname, device_id, misaki, training }. 403 when that Misaki level is still locked. */
export async function pvpBot(body) {
  await sleep(180);
  guard();
  const misaki = Math.min(4, Math.max(1, Number(body.misaki) || 1));
  if (misaki > mkRead().unlocked) throw fail(403, 'Cấp này của Misaki chưa mở.');
  const ticket = 'mock-b-' + seq++;
  tickets.set(ticket, { kind: 'bot', level: body.level, nickname: body.nickname, misaki, training: !!body.training });
  return { ticket };
}

/** GET /api/pvp/misaki: the ladder for this device. */
export async function pvpMisaki() {
  await sleep(120);
  return mkRead();
}

// ---- hooks called by mock-api.js for puzzle calls that carry match_id ----------------------------------------------
const sims = new Map(); // ticket -> Sim
const byMatch = (id) => [...sims.values()].find((s) => s.matchId === id) || null;

export function pvpServed(req, puzzle) {
  const sim = byMatch(req.match_id);
  if (!sim || req.match_token !== sim.token) return;
  sim.served = { id: puzzle.id, kind: req.kind, templateId: req.template_id || null, topic: req.topic };
  // the Debugger is used up by the lock it is open for (free hint level 2); the new count comes back in `state`
  if (req.kind !== 'debug' && sim.me?.lock && !sim.lockDbg && sim.me.items.debugger > 0) {
    sim.me.items.debugger--;
    sim.lockDbg = true;
    sim.after(40, () => sim.sendState());
  }
}

export function pvpHinted(match, level) {
  const sim = byMatch(match.match_id);
  if (sim) sim.maxHint = Math.max(sim.maxHint, level);
}

export function pvpAnswered(id, body, result) {
  const sim = byMatch(body.match_id);
  if (!sim || body.match_token !== sim.token || sim.over) return;
  sim.answered(id, !!result.correct);
}

// ---- players ------------------------------------------------------------------------------------------------------
function newPlayer(seed, level, items) {
  const s = Game.newGame({ mode: 'pvp', level, rng: mulberry(seed) });
  s.pending = s.pending || [];
  s.sent = s.sent || 0;
  s.received = s.received || 0;
  s.locksWon = 0;
  s.endReason = null;
  if (items) s.items = { bomb: 1, shuffle: 1, undo: 1, debugger: 1 };
  return s;
}

/** Rows land from the bottom (used when game.js does not land pending rows itself). */
function landPending(s) {
  const k = s.pending.length;
  if (!k) return 0;
  for (let r = 0; r < k; r++) if (s.grid[r].some(Boolean)) {
    s.phase = 'over';
    s.endReason = 'topped_out';
    return 0;
  }
  s.grid = [...s.grid.slice(k), ...Array.from({ length: k }, () => Array(SIZE).fill(null))];
  for (const b of s.bugLines) b.cells = b.cells.map(([r, c]) => [r - k, c]);
  for (let i = 0; i < k; i++) {
    const row = SIZE - k + i;
    const p = s.pending[i];
    const id = s.nextBugId++;
    for (let c = 0; c < SIZE; c++) s.grid[row][c] = { topic: p.topic, bug: true, bugId: id };
    s.bugLines.push({ id, cells: Array.from({ length: SIZE }, (_, c) => [row, c]), topic: p.topic, templateId: p.templateId, placementsLeft: 99 });
  }
  s.pending = [];
  return k;
}

function receive(s, n, topic) {
  const entries = Array.from({ length: n }, () => ({ topic, templateId: TEMPLATE[topic] }));
  if (s.lock && s._since) s._since.push(...entries.map((e) => ({ ...e })));
  if (typeof Game.queueIncoming === 'function') Game.queueIncoming(s, entries);
  else {
    s.pending.push(...entries);
    s.received += n;
  }
}

function placeFor(s, i, r, c) {
  if (s.phase === 'over' || s.lock) return null;
  if (!s.tray[i]) return null;
  const res = Game.place(s, i, r, c);
  if (!res) return null;
  let landed = 0;
  if (res.lock) {
    s.phase = 'locked';
    s._snapPend = s.pending.map((p) => ({ ...p })); // undo: this queue + whatever arrives during the lock
    s._since = [];
  }
  else {
    landed = res.landed !== undefined ? res.landed : s.phase === 'over' ? 0 : landPending(s);
    if (s.phase !== 'over') s.phase = 'play';
    else if (!s.endReason) s.endReason = 'nofit';
  }
  if (s.phase !== 'over' && !s.lock && !Game.anyFit(s)) {
    s.phase = 'over';
    s.endReason = 'nofit';
  }
  return { res, landed };
}

function correctFor(s, maxHint, dbg = false) {
  const L = s.lock;
  const free = Game.freeHintLevel(s, dbg);
  const r = Game.applyCorrect(s, { base: Game.baseFor(L), maxHint, free, lines: L.count });
  let send;
  let cancelled;
  if (r.send !== undefined) {
    send = r.send;
    cancelled = r.cancelled | 0;
  } else {
    const total = (L.boss ? 4 : SEND[Math.min(L.count, 4)]) + (r.clean && s.streak >= 3 ? 1 : 0);
    cancelled = Math.min(s.pending.length, total);
    s.pending.splice(0, cancelled);
    send = total - cancelled;
    s.sent += send;
  }
  s.locksWon++;
  Game.finishLock(s);
  if (!Game.anyFit(s)) {
    s.phase = 'over';
    s.endReason = 'nofit';
  }
  return { send, cancelled, topic: L.topic };
}

function wrongFor(s) {
  const L = s.lock;
  Game.applyWrong(s, { puzzle: { topic: L.topic, id: 'mock', template_id: TEMPLATE[L.topic], prompt: '' }, response: null, answer: null });
  if (!Game.anyFit(s)) {
    s.phase = 'over';
    s.endReason = 'nofit';
  }
}

const serialize = (s) => ({
  grid: s.grid,
  tray: s.tray,
  score: s.score,
  streak: s.streak,
  items: s.items,
  pending: s.pending,
  received: s.received,
  bugLines: s.bugLines.map((b) => ({ id: b.id, cells: b.cells, topic: b.topic, templateId: b.templateId })),
  lock: s.lock,
  phase: s.phase === 'over' ? 'over' : s.lock ? 'locked' : 'play',
});

/** Empty cells boxed in on all four sides: the fake opponent avoids creating them. */
function holes(grid, added) {
  const filled = (r, c) => r < 0 || r >= SIZE || c < 0 || c >= SIZE || !!grid[r][c] || added.has(r * SIZE + c);
  let n = 0;
  for (let r = 0; r < SIZE; r++)
    for (let c = 0; c < SIZE; c++) if (!filled(r, c) && filled(r + 1, c) && filled(r - 1, c) && filled(r, c + 1) && filled(r, c - 1)) n++;
  return n;
}

/** The fake opponent's move: complete rows first, hug existing blocks, avoid holes, stay low. */
function botMove(s) {
  let best = null;
  for (let i = 0; i < 3; i++) {
    const p = s.tray[i];
    if (!p) continue;
    for (let r = 0; r < SIZE; r++)
      for (let c = 0; c < SIZE; c++) {
        if (!Game.canPlace(s.grid, p, r, c)) continue;
        const { rows, cols } = Game.completedLines(s.grid, p, r, c);
        const added = new Set(p.cells.map(([dr, dc]) => (r + dr) * SIZE + c + dc));
        let contact = 0;
        for (const [dr, dc] of p.cells)
          for (const [nr, nc] of [[r + dr + 1, c + dc], [r + dr - 1, c + dc], [r + dr, c + dc + 1], [r + dr, c + dc - 1]])
            if (nr < 0 || nr >= SIZE || nc < 0 || nc >= SIZE || s.grid[nr]?.[nc]) contact++;
        const score = (rows.length + cols.length) * 20 + contact - holes(s.grid, added) * 7 + r * 0.4 + Math.random() * 2;
        if (!best || score > best.score) best = { i, r, c, score };
      }
  }
  return best;
}

// ---- the fake server for one match ---------------------------------------------------------------------------------
class Sim {
  constructor(ticket, rec) {
    this.ticket = ticket;
    this.rec = rec;
    this.kind = rec.kind;
    this.level = rec.level || 'beginner';
    this.sock = null;
    this.seed = Math.floor(Math.random() * 4294967296);
    this.matchId = 'mock-m-' + seq++;
    this.token = 'mock-mt-' + seq++;
    this.rev = 0;
    this.started = false;
    this.over = false;
    this.endMsg = null;
    this.landAt = null; // timed landing deadline (ms), null when nothing waits or a lock holds it
    this.landHeld = null; // ms left on the landing timer while a lock is open
    this.lockAt = null; // lock limit deadline (ms)
    this.maxHint = 0;
    this.bossDone = 0;
    this.lockDbg = false;
    this.rmYou = false;
    this.rmOpp = false;
    this.served = null;
    this.timers = new Set();
    this.opponent = null;
    this.oppAway = false;
    this.oppSolving = null; // { until }
    this.t0 = 0;
    this.otDone = 0;
    this.dropped = false;
    this.lastOppEmit = 0;
    this.oppEmitTimer = null;
    this.aggr = qs().get('pvpaggr') === '1';
    this.misaki = Number(rec.misaki) || 0;
    this.training = !!rec.training && this.misaki > 0;
    const eff = this.training ? Math.max(1, this.misaki - 1) : this.misaki; // training: she plays one level lower and slower
    this.pace = this.misaki ? MK_PACE[eff] * (this.training ? 1.5 : 1) : 1;
    this.acc = this.misaki ? MK_ACC[eff] : ACCURACY[this.level] || 0.7;
    this.lastCoach = 0;
    this.lastSuggest = 0;
    this.coachSeen = new Set();
    this.bugSince = 0;
    this.nofitAt = 0;
  }

  // -- Misaki as coach (training only) --
  coach(kind, vars = {}, cells = null, force = false) {
    if (!this.training || this.over) return;
    const now = Date.now();
    if (!force && now - this.lastCoach < 4000) return;
    this.lastCoach = now;
    const list = COACH[kind];
    const msg = { t: 'coach', kind, text: fill(list[Math.floor(Math.random() * list.length)], vars) };
    if (cells && cells.length) msg.cells = cells;
    this.emit(msg);
  }

  /** After the player's state changed: danger / streak / bug line / no-fit checks. */
  coachWatch() {
    if (!this.training || !this.me) return;
    const me = this.me;
    const n = me.pending.length;
    let top = SIZE;
    for (let r = 0; r < SIZE && top === SIZE; r++) if (me.grid[r].some(Boolean)) top = r;
    if (n > 0 && top < SIZE && n > top) {
      const cells = [];
      for (let r = 0; r < Math.min(n, SIZE); r++) for (let c = 0; c < SIZE; c++) if (me.grid[r][c]) cells.push([r, c]);
      this.coach('danger', { n }, cells);
    }
    if (me.streak === 3 && !this.coachSeen.has('streak' + this.matchId)) {
      this.coachSeen.add('streak' + this.matchId);
      this.coach('streak', { n: 3 });
    }
    if (me.bugLines.length) this.bugSince = this.bugSince || Date.now();
    else this.bugSince = 0;
    if (this.bugSince && Date.now() - this.bugSince > 30000) {
      this.bugSince = Date.now();
      this.coach('bugline', { topic: TOPIC_VI[me.bugLines[0].topic] || '' }, me.bugLines[0].cells);
    }
    if (!me.lock && Date.now() - this.nofitAt > 20000) {
      const fits = me.tray.filter((p) => p && Game.fitsAnywhere(me.grid, p)).length;
      if (me.tray.some(Boolean) && fits === 1) {
        this.nofitAt = Date.now();
        this.coach('nofit_risk');
      }
    }
  }

  /** {t:"suggest"} -> {t:"suggestion"}: the best move for the player's current state. */
  suggest() {
    if (!this.training) return this.emit({ t: 'error', code: 'not_training', message: 'Gợi ý chỉ có trong chế độ luyện tập.' });
    const now = Date.now();
    if (now - this.lastSuggest < 3000) return this.emit({ t: 'error', code: 'rate_limited', message: 'Bạn thao tác quá nhanh.' });
    this.lastSuggest = now;
    const me = this.me;
    const mv = me && !me.lock ? botMove(me) : null;
    if (!mv) return this.emit({ t: 'suggestion', none: true, why: me?.lock ? 'Hãy giải câu đố để mở khoá hàng trước, rồi tôi gợi ý tiếp.' : WHY.none }, 400);
    const p = me.tray[mv.i];
    const { rows, cols } = Game.completedLines(me.grid, p, mv.r, mv.c);
    const lines = rows.length + cols.length;
    const why = lines ? fill(WHY.line, { n: lines }) : me.pending.length ? WHY.danger : pick([WHY.safe, WHY.fit]);
    this.emit({ t: 'suggestion', i: mv.i, r: mv.r, c: mv.c, cells: p.cells.map(([dr, dc]) => [mv.r + dr, mv.c + dc]), why }, 400);
  }

  after(ms, fn) {
    const t = setTimeout(() => {
      this.timers.delete(t);
      fn();
    }, ms);
    this.timers.add(t);
    return t;
  }

  every(ms, fn) {
    const t = setInterval(fn, ms);
    this.timers.add(t);
    return t;
  }

  stop() {
    for (const t of this.timers) { clearTimeout(t); clearInterval(t); }
    this.timers.clear();
    clearTimeout(this.oppEmitTimer);
  }

  emit(obj, delay = 25) {
    const sock = this.sock;
    if (!sock) return;
    setTimeout(() => sock.deliver(obj), delay);
  }

  attach(sock) {
    this.sock = sock;
    if (this.started) {
      // reconnect inside the grace (or a reload): lobby, start and state again, so the board resumes exactly
      this.emit(this.lobbyMsg());
      if (this.revived) {
        this.revived = false;
        this.startLoops();
      }
      this.emit({ t: 'start', seed: this.seed, level: this.level, match_id: this.matchId, match_token: this.token, at: this.t0 });
      this.sendState();
      this.sendOpp(true);
      return;
    }
    this.lobby();
  }

  lobbyMsg(startsIn = null) {
    return {
      t: 'lobby',
      you: { nickname: this.rec.nickname, rating: this.kind === 'bot' ? undefined : readRating() },
      opponent: this.opponent ? { ...this.opponent } : null,
      level: this.level,
      starts_in: startsIn,
    };
  }

  lobby() {
    const k = this.kind;
    this.emit(this.lobbyMsg());
    const found = (opp, delay) => this.after(delay, () => {
      this.opponent = opp;
      this.emit(this.lobbyMsg(3));
      this.after(3000, () => this.begin());
    });
    if (k === 'quick') {
      const wait = Number(qs().get('pvpwait')) || rand(2.5, 4.5);
      found({ nickname: humanName(), bot: false, connected: true, rating: 960 + Math.floor(Math.random() * 90) }, wait * 1000);
    } else if (k === 'private') found({ nickname: humanName(), bot: false, connected: true, rating: 1000 }, 7000);
    else if (k === 'join') found({ nickname: this.rec.hostNick, bot: false, connected: true, rating: 1000 }, 400);
    else if (this.misaki) found({ nickname: 'Misaki', bot: true, misaki: this.misaki, title: `Misaki · ${MK_NAMES[this.misaki]}`, training: this.training, connected: true, rating: null }, 300);
    else found({ nickname: `Máy ${pick(ANIMALS)}`, bot: true, connected: true }, 300);
  }

  begin() {
    if (this.started || this.over) return;
    this.started = true;
    this.t0 = Date.now();
    const items = qs().get('pvpitems') === '1';
    this.me = newPlayer(this.seed, this.level, items);
    this.opp = newPlayer(this.seed, this.level, false);
    this.emit({ t: 'start', seed: this.seed, level: this.level, match_id: this.matchId, match_token: this.token, at: this.t0 });
    this.sendState();
    this.sendOpp(true);
    this.startLoops();
    if (qs().get('pvpdrop') === '1') this.after(15000, () => this.dropMine());
    if (qs().get('pvpoppdrop') === '1' && this.kind !== 'bot') this.after(20000, () => this.dropOpp());
    const mkend = qs().get('mkend');
    if (this.misaki && (mkend === 'win' || mkend === 'lose')) this.after(20000, () => this.finish(mkend === 'win' ? 'you' : 'opponent', 'nofit'));
    if (this.training && qs().get('mkcoach') === '1') {
      const kinds = Object.keys(COACH);
      let k = 0;
      this.every(5000, () => {
        const kind = kinds[k++ % kinds.length];
        const cells = kind === 'danger' || kind === 'bugline' ? [[0, 0], [0, 1], [0, 2], [1, 0], [1, 1]] : null;
        this.coach(kind, { n: 2, topic: 'Vòng lặp' }, cells, true);
      });
    }
  }

  startLoops() {
    this.after(rand(1200, 1800), () => this.botStep());
    this.every(1000, () => this.clock());
    this.every(250, () => this.limitTick());
  }

  // -- reload resume: the browser keeps a snapshot, a revived sim carries on from it --
  persist() {
    if (this.over || !this.started) return;
    const dump = (p) => Object.fromEntries(Object.entries(p).filter(([k, v]) => typeof v !== 'function' && k !== 'snapshot' && !k.startsWith('_')));
    try {
      sessionStorage.setItem(SNAP_KEY, JSON.stringify({ ticket: this.ticket, rec: this.rec, seed: this.seed, level: this.level, matchId: this.matchId, token: this.token, t0: this.t0, rev: this.rev, otDone: this.otDone, opponent: this.opponent, me: dump(this.me), opp: dump(this.opp) }));
    } catch { /* storage blocked */ }
  }

  static revive(ticket) {
    let d;
    try {
      d = JSON.parse(sessionStorage.getItem(SNAP_KEY));
    } catch {
      return null;
    }
    if (!d || d.ticket !== ticket) return null;
    const sim = new Sim(ticket, d.rec);
    Object.assign(sim, { seed: d.seed, level: d.level, matchId: d.matchId, token: d.token, t0: d.t0, rev: d.rev, otDone: d.otDone, opponent: d.opponent, started: true, revived: true });
    const mk = (data, salt) => {
      const p = newPlayer(d.seed, d.level, false);
      Object.assign(p, data);
      p.rng = mulberry(((d.seed ^ 0x9e3779b9 ^ (d.rev * 2654435761) ^ salt) >>> 0)); // pieces dealt after a reload differ from before (mock only)
      return p;
    };
    sim.me = mk(d.me, 1);
    sim.opp = mk(d.opp, 2);
    return sim;
  }

  // -- rematch after `end` (private duels): both sides ask, then a fresh `start` comes on the same socket --
  askRematch() {
    if (!this.over || this.kind === 'quick' || this.kind === 'bot') return;
    this.rmYou = true;
    this.emit({ t: 'rematch_status', you: true, opponent: this.rmOpp });
    if (qs().get('pvprematch') !== '0' && !this.rmOpp) {
      this.after(rand(2500, 5000), () => {
        this.rmOpp = true;
        this.emit({ t: 'rematch_status', you: this.rmYou, opponent: true });
        this.checkRematch();
      });
    }
    this.checkRematch();
  }

  checkRematch() {
    if (!this.over || !this.rmYou || !this.rmOpp) return;
    this.rmYou = this.rmOpp = false;
    this.seed = Math.floor(Math.random() * 4294967296);
    this.matchId = 'mock-m-' + seq++;
    this.token = 'mock-mt-' + seq++;
    Object.assign(this, { over: false, started: false, endMsg: null, rev: 0, otDone: 0, oppSolving: null, oppAway: false, served: null, maxHint: 0, bossDone: 0, lockDbg: false, dropped: true, landAt: null, landHeld: null, lockAt: null });
    this.after(500, () => this.begin());
  }

  dropMine() {
    if (this.over || !this.sock || this.dropped) return;
    this.dropped = true;
    const sock = this.sock;
    this.sock = null;
    sock.drop();
  }

  dropOpp() {
    this.oppAway = true;
    this.emit({ t: 'opponent_status', connected: false, grace_s: 20 });
    this.sendOpp(true);
    this.after(12000, () => {
      this.oppAway = false;
      this.emit({ t: 'opponent_status', connected: true, grace_s: 0 });
      this.sendOpp(true);
      this.after(1200, () => this.botStep());
    });
  }

  /** Same rules as the real server: pending lines land 4 s (2 s in overtime) after the queue became non-empty, held while a lock is open; a lock must be solved in 40 s (boss 70 s). */
  syncTimers() {
    const me = this.me;
    const now = Date.now();
    const ot = Number(qs().get('pvpot')) || 240;
    const full = (now - this.t0) / 1000 >= ot ? 2000 : 4000;
    if (!me.pending.length) {
      this.landAt = this.landHeld = null;
    } else if (me.lock) {
      if (this.landAt != null) {
        this.landHeld = this.landAt - now;
        this.landAt = null;
      } else if (this.landHeld == null) this.landHeld = full;
    } else if (this.landHeld != null) {
      this.landAt = now + Math.max(0, this.landHeld);
      this.landHeld = null;
    } else if (this.landAt == null) this.landAt = now + full;
    if (!me.lock) this.lockAt = null;
    else if (this.lockAt == null) this.lockAt = now + (me.lock.boss ? 70000 : 40000);
    const landMs = this.landAt != null ? this.landAt - now : this.landHeld;
    return {
      land_in: me.pending.length && landMs != null ? Math.max(0, landMs) / 1000 : null,
      lock_in: me.lock && this.lockAt != null ? Math.max(0, this.lockAt - now) / 1000 : null,
    };
  }

  sendState() {
    this.rev++;
    this.emit({ t: 'state', you: { ...serialize(this.me), ...this.syncTimers() }, rev: this.rev });
  }

  /** 250 ms loop: the timed landing and the lock limit. */
  limitTick() {
    if (this.over || !this.started || !this.me) return;
    const me = this.me;
    const now = Date.now();
    if (me.lock && this.lockAt != null && now >= this.lockAt) {
      this.served = null;
      this.bossDone = 0;
      this.lockDbg = false;
      wrongFor(me); // expiry counts as a wrong answer: the lock becomes your own bug line
      this.emit({ t: 'lock_timeout' });
      this.sendState();
      this.coach('wrong', { topic: '' }, me.bugLines.length ? me.bugLines[me.bugLines.length - 1].cells : null);
      if (me.phase === 'over') this.finish('opponent', me.endReason || 'nofit');
      return;
    }
    if (!me.lock && me.pending.length && this.landAt != null && now >= this.landAt) {
      const k = landPending(me);
      if (me.phase === 'over') {
        this.sendState();
        return this.finish('opponent', me.endReason || 'topped_out');
      }
      if (k) this.emit({ t: 'landed', rows: k, timed: true });
      this.sendState();
    }
  }

  sendOpp(now = false) {
    const go = () => {
      this.lastOppEmit = Date.now();
      this.emit({ t: 'opponent', grid: this.opp.grid, score: this.opp.score, pending: this.opp.pending.length, lock: !!this.oppSolving, phase: this.opp.phase === 'over' ? 'over' : 'play', connected: !this.oppAway }, 5);
    };
    if (now) return go();
    if (this.oppEmitTimer) return;
    this.oppEmitTimer = setTimeout(() => {
      this.oppEmitTimer = null;
      go();
    }, Math.max(0, 250 - (Date.now() - this.lastOppEmit)));
  }

  clock() {
    if (this.over) return;
    this.persist();
    const ot = Number(qs().get('pvpot')) || 240;
    const s = (Date.now() - this.t0) / 1000;
    if (s >= ot) {
      const n = Math.floor((s - ot) / 20) + 1;
      while (this.otDone < n) {
        this.otDone++;
        const topic = pick(TOPICS);
        receive(this.me, 1, topic);
        receive(this.opp, 1, topic);
        this.emit({ t: 'incoming', lines: 1, from_topic: topic });
        this.sendState();
        this.sendOpp(true);
      }
    }
    this.sendOpp();
  }

  // -- the fake opponent --
  botStep() {
    if (this.over) return;
    const s = this.opp;
    const again = (ms) => this.after(ms * this.pace, () => this.botStep());
    if (this.oppAway) return;
    if (this.oppSolving) {
      if (Date.now() < this.oppSolving.until) return this.after(500, () => this.botStep());
      const dbg = this.oppSolving.debug;
      this.oppSolving = null;
      if (dbg) {
        if (Math.random() < this.acc && s.bugLines[0]) Game.fixBug(s, s.bugLines[0].id);
        this.sendOpp(true);
        return again(rand(700, 1100));
      }
      const ok = this.aggr || Math.random() < this.acc;
      if (ok) {
        const r = correctFor(s, 0);
        if (r.send > 0) {
          receive(this.me, r.send, r.topic);
          this.emit({ t: 'incoming', lines: r.send, from_topic: r.topic });
          this.sendState();
          if (!this.coachSeen.has('incoming' + this.matchId)) {
            this.coachSeen.add('incoming' + this.matchId);
            this.coach('incoming');
          }
          this.coachWatch();
        }
      } else wrongFor(s);
      this.sendOpp(true);
      if (s.phase === 'over') return this.finish('you', s.endReason || 'nofit');
      return again(rand(900, 1400));
    }
    if (s.bugLines.length && !s.lock && Math.random() < 0.18) {
      this.oppSolving = { until: Date.now() + rand(3500, 6000), debug: true };
      this.sendOpp(true);
      return again(500);
    }
    const mv = botMove(s);
    if (!mv) {
      s.phase = 'over';
      s.endReason = 'nofit';
      return this.finish('you', 'nofit');
    }
    const out = placeFor(s, mv.i, mv.r, mv.c);
    if (!out) return again(800);
    if (s.phase === 'over') {
      this.sendOpp(true);
      return this.finish('you', s.endReason);
    }
    if (s.lock) {
      const base = this.level === 'advanced' ? 4000 : this.level === 'intermediate' ? 5200 : 6200;
      this.oppSolving = { until: Date.now() + (this.aggr ? 3000 : rand(base, base + 3000) * (this.misaki ? this.pace : 1)) };
    }
    this.sendOpp();
    again(this.aggr ? rand(900, 1300) : rand(1100, 1900));
  }

  // -- messages from the player --
  receive(msg) {
    if (this.over && msg.t !== 'ping' && msg.t !== 'rematch') return;
    switch (msg.t) {
      case 'ping': return this.emit({ t: 'pong', n: msg.n }, 5);
      case 'ready': return;
      case 'suggest': return this.suggest();
      case 'rematch': return this.askRematch();
      case 'resign': return this.finish('opponent', 'resign');
      case 'place': return this.act(() => {
        if (msg.received !== undefined && msg.received !== this.me.received) {
          this.emit({ t: 'error', code: 'stale_state', message: 'Có dòng lỗi mới vừa tới. Hãy xem lại bàn rồi đặt khối.' });
          return true; // send the current state without applying the stale placement
        }
        const out = placeFor(this.me, msg.i, msg.r, msg.c);
        if (!out) return false;
        if (out.landed) this.emit({ t: 'landed', rows: out.landed });
        return true;
      });
      case 'bomb': return this.act(() => !this.me.lock && !!Game.bomb(this.me, msg.r, msg.c));
      case 'shuffle': return this.act(() => !this.me.lock && Game.shuffle(this.me));
      case 'undo': return this.act(() => {
        const s = this.me;
        if (!s.lock || !s.snapshot || s.items.undo < 1) return false;
        Game.undo(s);
        s.pending = [...(s._snapPend || []), ...(s._since || [])]; // as before the lock-creating placement, plus lines received since
        s.phase = 'play';
        return true;
      });
      default:
    }
  }

  act(fn) {
    if (!this.started) return this.emit({ t: 'error', code: 'not_playing', message: 'Trận chưa bắt đầu.' });
    const ok = fn();
    if (!ok) this.emit({ t: 'error', code: 'illegal', message: 'Không thực hiện được.' });
    this.sendState();
    if (this.me.phase === 'over') this.finish('opponent', this.me.endReason || 'nofit');
    else this.coachWatch();
  }

  /** An HTTP answer arrived for the player's current puzzle. */
  answered(id, correct) {
    const s = this.me;
    const served = this.served;
    if (!served || served.id !== id || !this.started) return;
    this.served = null;
    if (served.kind === 'debug') {
      if (correct) {
        const bl = s.bugLines.find((b) => b.templateId === served.templateId) || s.bugLines[0];
        if (bl) Game.fixBug(s, bl.id);
      }
      this.after(60, () => this.sendState());
      return;
    }
    if (!s.lock) return;
    const hint = this.maxHint;
    this.maxHint = 0;
    if (correct && s.lock.boss && ++this.bossDone < 2) return; // boss: two puzzles, the second decides
    this.bossDone = 0;
    const dbg = this.lockDbg;
    this.lockDbg = false;
    const lockCount = s.lock.count;
    const lockTopic = s.lock.topic;
    this.after(60, () => {
      if (this.over || !s.lock) return;
      if (correct) {
        const r = correctFor(s, hint, dbg);
        if (r.send > 0) receive(this.opp, r.send, r.topic);
        this.emit({ t: 'sent', lines: r.send, cancelled: r.cancelled });
        this.sendState();
        this.sendOpp(true);
        if (r.cancelled > 0) this.coach('cancel', { n: r.cancelled });
        else if (lockCount >= 2) this.coach('good', { n: lockCount });
        this.coachWatch();
      } else {
        wrongFor(s);
        this.sendState();
        this.coach('wrong', { topic: TOPIC_VI[lockTopic] || '' }, s.bugLines.length ? s.bugLines[s.bugLines.length - 1].cells : null);
      }
      if (s.phase === 'over') this.finish('opponent', s.endReason || 'nofit');
    });
  }

  finish(winner, reason) {
    if (this.over) return;
    this.over = true;
    const stats = (p) => ({ score: p.score, sent: p.sent, received: p.received, locks: p.locksWon });
    const msg = { t: 'end', winner, reason, you: stats(this.me), opponent: stats(this.opp) };
    if (this.misaki) {
      const d = mkRead();
      let unlocked = null;
      if (!this.training) {
        d.games[this.misaki] = (d.games[this.misaki] || 0) + 1;
        if (winner === 'you') {
          d.wins[this.misaki] = (d.wins[this.misaki] || 0) + 1;
          if (this.misaki === d.unlocked && this.misaki < 4) {
            d.unlocked = this.misaki + 1;
            unlocked = d.unlocked;
          }
        }
        mkWrite(d);
      }
      msg.misaki = { level: this.misaki, unlocked_now: unlocked };
    }
    if (this.kind !== 'bot') {
      const before = readRating();
      const after = before + (winner === 'you' ? 16 : winner === 'opponent' ? -16 : 0);
      msg.rating = { before, after };
    }
    this.endMsg = msg;
    try { sessionStorage.removeItem(SNAP_KEY); } catch { /* ignore */ }
    this.stop();
    this.emit(msg);
  }
}

// ---- WebSocket look-alike -----------------------------------------------------------------------------------------
export class MockPvpSocket {
  constructor(ticket) {
    this.readyState = 0;
    this.onopen = null;
    this.onmessage = null;
    this.onclose = null;
    this.onerror = null;
    this.ticket = ticket;
    setTimeout(() => this.open(), 90);
  }

  open() {
    if (this.readyState !== 0) return;
    const rec = tickets.get(this.ticket);
    let sim = sims.get(this.ticket);
    if (!rec && !sim) {
      sim = Sim.revive(this.ticket); // a page reload inside a match
      if (!sim) return this.shut(4404);
      sims.set(this.ticket, sim);
    }
    this.readyState = 1;
    if (this.onopen) this.onopen({});
    if (!sim) {
      sim = new Sim(this.ticket, rec);
      sims.set(this.ticket, sim);
    }
    this.sim = sim;
    if (sim.over) {
      sim.sock = this;
      if (sim.endMsg) sim.emit(sim.endMsg);
      return;
    }
    sim.attach(this);
  }

  deliver(obj) {
    if (this.readyState !== 1) return;
    if (this.onmessage) this.onmessage({ data: JSON.stringify(obj) });
  }

  send(data) {
    if (this.readyState !== 1) throw new Error('socket closed');
    let msg;
    try {
      msg = JSON.parse(data);
    } catch {
      return;
    }
    if (this.sim) this.sim.receive(msg);
  }

  /** The server side hangs up without the client asking (a network drop). */
  drop() {
    this.shut(1006);
  }

  close(code = 1000) {
    if (this.readyState === 3) return;
    const sim = this.sim;
    this.shut(code);
    if (sim && sim.sock === this) {
      sim.stop();
      sims.delete(this.ticket);
      try { sessionStorage.removeItem(SNAP_KEY); } catch { /* ignore */ }
    }
    tickets.delete(this.ticket);
  }

  shut(code) {
    if (this.readyState === 3) return;
    this.readyState = 3;
    setTimeout(() => this.onclose && this.onclose({ code, wasClean: code === 1000 }), 0);
  }
}
