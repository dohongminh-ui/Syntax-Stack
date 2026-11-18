// Mock of the live-classroom endpoints (?mock=1 only). The summary is simulated: a few made-up players
// answer every couple of seconds, so the teacher dashboard can be judged without a backend.
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const fail = (status, detail) => Object.assign(new Error(detail), { status });

const TOPICS = ['variables', 'conditions', 'loops', 'functions'];
const TYPES = ['fill_blank', 'predict_output', 'parsons', 'find_bug'];
// Chance of a correct answer per topic x type, so the heatmap shows all three tints.
const SKILL = {
  variables: [0.95, 0.9, 0.82, 0.7],
  conditions: [0.85, 0.6, 0.7, 0.35],
  loops: [0.75, 0.4, 0.3, 0.55],
  functions: [0.9, 0.7, 0.5, 0.2],
};
const MISTAKES = {
  variables: ['Nhầm thứ tự gán biến', 'Quên cập nhật biến sau khi gán'],
  conditions: ['Quên dấu hai chấm (:) sau if', 'Nhầm == với ='],
  loops: ['range(n) dừng trước n', 'Sai thụt lề trong vòng lặp'],
  functions: ['Quên return trong hàm', 'Gọi hàm thiếu đối số'],
};
const UNSOLVED = [
  { puzzle_id: 'mock_u1', prompt: 'Tìm dòng sai để hàm trả về tổng của hai số a và b, rồi chọn cách sửa đúng.', topic: 'functions', base: 5 },
  { puzzle_id: 'mock_u2', prompt: 'Chương trình sau in ra gì khi vòng lặp for chạy với range(1, 4) và tổng cộng dồn?', topic: 'loops', base: 4 },
  { puzzle_id: 'mock_u3', prompt: 'Tìm bug trong câu lệnh if so sánh hai chuỗi.', topic: 'conditions', base: 3 },
];
const NAMES = ['Minh', 'Lan', 'Hải', 'Thảo', 'Quân', 'Vy', 'Nam', 'Trang'];
const rand = (a) => a[Math.floor(Math.random() * a.length)];

const rooms = new Map();

function newRoom(code, level = 'beginner', title = '') {
  const r = { code, level, title, open: true, created: Date.now(), players: [], grid: {}, mistakes: {}, unsolved: UNSOLVED.map((u) => ({ ...u, attempts: 0, who: new Set() })), recent: [], lastStep: 0, key: 'mock-key', sim: false };
  for (const t of TOPICS) {
    r.grid[t] = {};
    for (const ty of TYPES) r.grid[t][ty] = { answers: 0, correct: 0 };
  }
  rooms.set(code, r);
  return r;
}

function step(r, now) {
  if (!r.open) return;
  if (r.players.length < NAMES.length && (r.players.length < 3 || Math.random() < 0.25)) {
    r.players.push({ nickname: NAMES[r.players.length], score: 0, status: 'playing', answers: 0, correct: 0, seen: now });
  }
  const n = 1 + Math.floor(Math.random() * 3);
  for (let i = 0; i < n && r.players.length; i++) {
    const p = rand(r.players.filter((x) => x.status === 'playing')) || null;
    if (!p) break;
    const ti = Math.floor(Math.random() * 4);
    const topic = TOPICS[ti];
    const tyi = Math.floor(Math.random() * 4);
    const type = TYPES[tyi];
    const ok = Math.random() < SKILL[topic][tyi];
    const cell = r.grid[topic][type];
    cell.answers++;
    p.answers++;
    p.seen = now;
    let label = null;
    if (ok) {
      cell.correct++;
      p.correct++;
      p.score += 100 + Math.floor(Math.random() * 80);
    } else {
      label = rand(MISTAKES[topic]);
      const m = (r.mistakes[label] ||= { key: label, label, count: 0, topic, who: new Set() });
      m.count++;
      m.who.add(p.nickname);
      const u = r.unsolved.find((x) => x.topic === topic);
      if (u && Math.random() < 0.6) {
        u.attempts++;
        u.who.add(p.nickname);
      }
      if (Math.random() < 0.06) p.status = Math.random() < 0.5 ? 'crash' : 'nofit';
    }
    r.recent.push({ nickname: p.nickname, topic, type, correct: ok, mistake_label: label, at: now });
  }
  r.recent = r.recent.slice(-12);
  // one player drifts away so the "greyed out" state is visible
  if (r.players.length > 4) r.players[3].seen = Math.min(r.players[3].seen, now - 90000);
}

function ensure(code) {
  const r = rooms.get(code) || newRoom(code, 'beginner', 'Lớp Python 10A (mô phỏng)');
  if (!r.sim) {
    r.sim = true;
    // pre-seed some history
    let t = Date.now() - 60000;
    for (let i = 0; i < 14; i++, t += 4000) step(r, t);
    r.lastStep = Date.now();
  }
  return r;
}

export async function createRoom(body) {
  await sleep(250);
  const code = Array.from({ length: 5 }, () => 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'[Math.floor(Math.random() * 32)]).join('');
  newRoom(code, body.level, body.title || '');
  return { code, teacher_key: 'mock-key', join_url: `${location.origin}/?room=${code}`, level: body.level, title: body.title || '' };
}

export async function getRoom(code) {
  await sleep(200);
  if (code === 'NOPE0') throw fail(404, 'Không tìm thấy phòng');
  if (code === 'CLOSD') throw fail(410, 'Phòng đã đóng');
  const r = rooms.get(code) || newRoom(code, 'beginner', 'Lớp Python 10A (mô phỏng)');
  return { code, level: r.level, title: r.title, open: r.open, players: r.players.length };
}

export async function joinRoom(code, nickname) {
  await sleep(250);
  const r = rooms.get(code) || newRoom(code, 'beginner', 'Lớp Python 10A (mô phỏng)');
  if (!r.open) throw fail(410, 'Phòng đã đóng');
  if (!nickname.trim()) throw fail(422, 'Biệt danh không hợp lệ');
  return { player_id: 'mock-player', player_token: 'mock-token', nickname: nickname.trim(), level: r.level };
}

export async function roomSummary(code, key) {
  await sleep(120);
  if (key !== 'mock-key') throw fail(403, 'Sai khoá phòng');
  const r = ensure(code);
  const now = Date.now();
  if (now - r.lastStep > 1800) {
    step(r, now);
    r.lastStep = now;
  }
  const ago = (t) => Math.max(0, Math.round((now - t) / 1000));
  const grid = {};
  let answers = 0;
  let correct = 0;
  for (const t of TOPICS) {
    grid[t] = {};
    for (const ty of TYPES) {
      const c = r.grid[t][ty];
      grid[t][ty] = { ...c };
      answers += c.answers;
      correct += c.correct;
    }
  }
  return {
    code, title: r.title, level: r.level, open: r.open, created_at: new Date(r.created).toISOString(),
    totals: { players: r.players.length, answers, correct },
    players: r.players.map((p) => ({ nickname: p.nickname, score: p.score, status: p.status, answers: p.answers, correct: p.correct, last_seen_s: ago(p.seen) })),
    grid,
    top_mistakes: Object.values(r.mistakes).sort((a, b) => b.count - a.count).slice(0, 5)
      .map((m) => ({ key: m.key, label: m.label, count: m.count, topic: m.topic, players: m.who.size })),
    unsolved: r.unsolved.filter((u) => u.attempts > 1).sort((a, b) => b.attempts - a.attempts)
      .map((u) => ({ puzzle_id: u.puzzle_id, prompt: u.prompt, topic: u.topic, attempts: u.attempts, players: u.who.size })),
    recent: r.recent.slice(-8).reverse().map((e) => ({ nickname: e.nickname, topic: e.topic, type: e.type, correct: e.correct, mistake_label: e.mistake_label, ago_s: ago(e.at) })),
  };
}

export async function closeRoom(code, key) {
  await sleep(150);
  if (key !== 'mock-key') throw fail(403, 'Sai khoá phòng');
  const r = rooms.get(code);
  if (r) r.open = false;
  return { open: false };
}

export async function deleteRoom(code, key) {
  await sleep(150);
  if (key !== 'mock-key') throw fail(403, 'Sai khoá phòng');
  rooms.delete(code);
  return null;
}
