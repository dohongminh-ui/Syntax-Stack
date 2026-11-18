// Mock of the ranked-run, leaderboard and race endpoints (?mock=1 only). Sample data is made up and the UI marks it as such.
// QA switches (URL): ?reject=1 makes every finish come back "rejected"; ?you=63 pins a "you" row at rank 63.
import { getNickname } from './identity.js';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const fail = (status, detail) => Object.assign(new Error(detail), { status });
const qs = () => new URLSearchParams(location.search);

const NAMES = ['Minh', 'Lan Anh', 'Hải', 'Thảo', 'Quân', 'Vy', 'Nam', 'Trang', 'Bảo', 'Linh', 'Khoa', 'My', 'Phúc', 'Ngọc', 'Tùng', 'Hà', 'Duy', 'An', 'Khánh', 'Mai', 'Sơn', 'Chi', 'Long', 'Yến', 'Huy', 'Thu', 'Đạt', 'Ly', 'Kiên', 'Nhi'];
const ANIMALS = ['Mèo', 'Cáo', 'Gấu', 'Hổ', 'Cú', 'Rùa', 'Thỏ', 'Sói'];
const COLORS = ['Xanh', 'Đỏ', 'Vàng', 'Tím', 'Cam', 'Hồng', 'Nâu', 'Bạc'];
/** Mock GET /api/nickname: same shape as the real names ("Mèo Xanh 42"). */
export async function fetchNickname() {
  await sleep(180);
  const pick = (a) => a[Math.floor(Math.random() * a.length)];
  return { nickname: `${pick(ANIMALS)} ${pick(COLORS)} ${10 + Math.floor(Math.random() * 90)}` };
}
const LEVEL_BASE = { beginner: 5200, intermediate: 7800, advanced: 10400 };
const PERIOD_COUNT = { day: 9, week: 31, all: 60 };

function hash(str) {
  let h = 2166136261;
  for (const ch of str) h = Math.imul(h ^ ch.charCodeAt(0), 16777619) >>> 0;
  return h;
}

function sample(level, period) {
  if (level === 'advanced' && period === 'day') return []; // shows the empty state
  let h = hash(level + period);
  const rnd = () => ((h = (Math.imul(h, 1664525) + 1013904223) >>> 0) / 4294967296);
  const n = PERIOD_COUNT[period];
  const base = LEVEL_BASE[level] * (period === 'day' ? 0.55 : period === 'week' ? 0.8 : 1);
  let score = base;
  const out = [];
  for (let i = 0; i < n; i++) {
    score = Math.max(120, Math.round(score - (20 + rnd() * (base / n) * 1.6)));
    out.push({ nickname: NAMES[(i * 7 + (h % 5)) % NAMES.length] + (i >= NAMES.length ? ' ' + (i - NAMES.length + 2) : ''), score, locks: Math.max(1, Math.round(score / 330 + rnd() * 2)), at: new Date(Date.now() - rnd() * 86400000 * (period === 'day' ? 0.5 : period === 'week' ? 6 : 40)).toISOString() });
  }
  return out;
}

const mockBest = {}; // level -> best score this session
const runs = new Map();
const races = new Map();

export async function leaderboard({ level, period }) {
  await sleep(320);
  const list = sample(level, period);
  const mine = mockBest[level];
  const forced = Number(qs().get('you'));
  let you = null;
  if (mine != null) {
    list.push({ nickname: getNickname() || 'Bạn', score: mine, locks: Math.max(1, Math.round(mine / 330)), at: new Date().toISOString(), me: true });
  }
  list.sort((a, b) => b.score - a.score);
  list.forEach((e, i) => (e.rank = i + 1));
  const meRow = list.find((e) => e.me);
  if (meRow) you = { rank: meRow.rank, score: meRow.score };
  else if (forced > 0 && list.length) you = { rank: forced, score: Math.max(80, Math.round((list.at(-1)?.score || 400) * 0.6)) };
  return { level, period, entries: list.slice(0, 50).map(({ me, ...e }) => e), you };
}

export async function createRun(body) {
  await sleep(250);
  if (qs().get('runfail') === '429') throw fail(429, 'Quá nhiều ván xếp hạng');
  if (qs().get('runfail') === '1') throw fail(0, 'Không kết nối được máy chủ.');
  if (body.kind === 'race' && !body.race) throw fail(422, 'Thiếu mã trận');
  let level = body.level;
  let seed = Math.floor(Math.random() * 4294967296);
  if (body.kind === 'race') {
    const r = raceFor(body.race);
    level = r.level;
    seed = r.seed;
    r.playing++;
  }
  const id = 'mock-run-' + (runs.size + 1);
  runs.set(id, { kind: body.kind, level, race: body.race || null, nickname: body.nickname, started: Date.now() });
  return { run_id: id, run_token: 'mock-token-' + id, seed, level, kind: body.kind, ...(body.race ? { race: body.race } : {}) };
}

export async function finishRun(id, body) {
  await sleep(700);
  if (qs().get('finishfail') === '1' && !finishRun.retried) {
    finishRun.retried = true; // fails once so the retry button can be seen
    throw fail(0, 'Không kết nối được máy chủ.');
  }
  const run = runs.get(id);
  if (!run) throw fail(404, 'Không tìm thấy ván chơi');
  if (qs().get('reject') === '1') return { status: 'rejected', reason: 'mock' };
  const moves = body.moves || [];
  const locks = moves.filter((m) => m.t === 'lock').length;
  const score = Math.max(0, Math.round(Number(body.client_score) || 0)); // the mock "verifies" by echoing the client score
  const crash = moves.some((m) => m.t === 'end' && m.reason === 'crash');
  const result = {
    status: 'verified',
    score,
    locks,
    mistakes: crash ? 2 : 0,
    bugs_fixed: moves.filter((m) => m.t === 'bugfix').length,
    best_streak: Math.min(locks, 6),
    duration_s: Math.max(1, Math.round((Date.now() - run.started) / 1000)),
    rank: null,
  };
  if (run.kind === 'ranked') {
    mockBest[run.level] = Math.max(mockBest[run.level] || 0, score);
    const rankIn = (period) => 1 + sample(run.level, period).filter((e) => e.score > score).length;
    result.rank = { day: rankIn('day'), week: rankIn('week'), all: rankIn('all') };
  } else {
    const r = raceFor(run.race);
    r.playing = Math.max(0, r.playing - 1);
    r.results.push({ nickname: run.nickname, score, locks, mistakes: result.mistakes, duration_s: result.duration_s, finished_at: new Date().toISOString() });
    result.race = raceView(r);
  }
  return result;
}

function raceFor(code) {
  if (code === 'NOPE0') throw fail(404, 'Không tìm thấy trận');
  if (code === 'GONE0') throw fail(410, 'Trận đã hết hạn');
  let r = races.get(code);
  if (!r) {
    const now = Date.now();
    r = {
      code, level: 'beginner', seed: hash(code), created_by: 'Minh', created_at: new Date(now - 14 * 60000).toISOString(),
      expires_at: new Date(now + 7 * 86400000).toISOString(), playing: 1,
      results: [
        { nickname: 'Lan Anh', score: 2140, locks: 7, mistakes: 2, duration_s: 412, finished_at: new Date(now - 6 * 60000).toISOString() },
        { nickname: 'Hải', score: 1580, locks: 5, mistakes: 2, duration_s: 301, finished_at: new Date(now - 9 * 60000).toISOString() },
        { nickname: 'Thảo', score: 1580, locks: 5, mistakes: 1, duration_s: 355, finished_at: new Date(now - 4 * 60000).toISOString() },
      ],
    };
    races.set(code, r);
  }
  return r;
}

function raceView(r) {
  const results = r.results
    .slice()
    .sort((a, b) => b.score - a.score || a.duration_s - b.duration_s)
    .map((x, i) => ({ rank: i + 1, ...x }));
  return { code: r.code, level: r.level, created_by: r.created_by, created_at: r.created_at, expires_at: r.expires_at, results, playing: r.playing };
}

export async function createRace(body) {
  await sleep(250);
  if (qs().get('racefail') === '429') throw fail(429, 'Tạo trận quá nhanh');
  const alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
  const code = Array.from({ length: 5 }, () => alphabet[Math.floor(Math.random() * alphabet.length)]).join('');
  const now = Date.now();
  races.set(code, { code, level: body.level, seed: hash(code), created_by: body.nickname, created_at: new Date(now).toISOString(), expires_at: new Date(now + 7 * 86400000).toISOString(), playing: 0, results: [] });
  return { code, seed: hash(code), level: body.level, url: `${location.origin}/?race=${code}` };
}

export async function getRace(code) {
  await sleep(150);
  return raceView(raceFor(code));
}
