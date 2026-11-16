// Syntax Rows mock (spec section 7). MOCK ONLY: assembles the code and compares it with the canonical
// solution, plus a tiny output table. The real client never sees the solution (docs/api-contract.md).
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const S = 'syntax';

// token: [text, w, topic, isDistractor]; sol: [[tokenIndexes], indent]
const ROW_LEVELS = [
  { id: 'r1', order: 1, title: 'Biến đầu tiên', concept: 'variables', rows: 4, out: '7', req: [],
    goal: 'Viết chương trình in ra 7.',
    tokens: [['diem', 1, 'variables'], ['=', 1, S], ['7', 1, 'variables'], ['print(diem)', 3, 'variables'], ['8', 1, 'variables', 1], ['print("diem")', 3, 'variables', 1]],
    sol: [[[0, 1, 2], 0], [[3], 0]] },
  { id: 'r2', order: 2, title: 'Đậu hay trượt', concept: 'conditions', rows: 5, out: 'Đậu', req: ['if'],
    goal: 'Cho diem = 8. In ra Đậu nếu điểm từ 5 trở lên.',
    tokens: [['diem', 1, 'variables'], ['=', 1, S], ['8', 1, 'variables'], ['if', 1, S], ['diem', 1, 'variables'], ['>=', 1, S], ['5', 1, 'conditions'], [':', 1, S], ['print("Đậu")', 3, 'conditions'],
      ['<', 1, S, 1], ['print("Trượt")', 3, 'conditions', 1], ['=', 1, S, 1]],
    sol: [[[0, 1, 2], 0], [[3, 4, 5, 6, 7], 0], [[8], 1]] },
  { id: 'r3', order: 3, title: 'Đếm đến ba', concept: 'loops', rows: 4, out: '0\n1\n2', req: ['for'],
    goal: 'Viết chương trình in ra 0, 1, 2, mỗi số một dòng.',
    tokens: [['for', 1, S], ['i', 1, 'loops'], ['in', 1, S], ['range(3)', 3, 'loops'], [':', 1, S], ['print(i)', 3, 'loops'], ['range(2)', 3, 'loops', 1], ['range(4)', 3, 'loops', 1], ['while', 2, S, 1]],
    sol: [[[0, 1, 2, 3, 4], 0], [[5], 1]] },
  { id: 'r4', order: 4, title: 'Cộng dồn', concept: 'loops', rows: 6, out: '6', req: ['for'],
    goal: 'Tính tổng 1 + 2 + 3 bằng vòng lặp rồi in ra 6.',
    tokens: [['tong', 1, 'variables'], ['=', 1, S], ['0', 1, 'variables'], ['for', 1, S], ['i', 1, 'loops'], ['in', 1, S], ['range(1, 4)', 3, 'loops'], [':', 1, S],
      ['tong', 1, 'variables'], ['=', 1, S], ['tong', 1, 'variables'], ['+', 1, S], ['i', 1, 'loops'], ['print(tong)', 3, 'variables'],
      ['range(1, 3)', 3, 'loops', 1], ['print(tong)', 3, 'variables', 1]],
    sol: [[[0, 1, 2], 0], [[3, 4, 5, 6, 7], 0], [[8, 9, 10, 11, 12], 1], [[13], 0]] },
  { id: 'r5', order: 5, title: 'Hàm nhân đôi', concept: 'functions', rows: 5, out: '8', req: ['def'],
    goal: 'Định nghĩa hàm gap_doi(x) trả về x nhân 2, rồi in gap_doi(4).',
    tokens: [['def', 1, S], ['gap_doi(x)', 3, 'functions'], [':', 1, S], ['return', 2, S], ['x', 1, 'functions'], ['*', 1, S], ['2', 1, 'functions'], ['print(gap_doi(4))', 3, 'functions'],
      ['+', 1, S, 1], ['print(x * 2)', 3, 'functions', 1]],
    sol: [[[0, 1, 2], 0], [[3, 4, 5, 6], 1], [[7], 0]] },
];

function expand(lv) {
  const tokens = lv.tokens.map((t, i) => ({ id: 't' + (i + 1), text: t[0], w: t[1], topic: t[2], d: !!t[3] }));
  const txt = (idx) => idx.map((i) => tokens[i].text).join(' ');
  const canonLines = lv.sol.map(([idx, indent]) => '    '.repeat(indent) + txt(idx));
  return { lv, tokens, canonLines };
}
const ROWS = ROW_LEVELS.map(expand);
const byId = (id) => ROWS.find((r) => r.lv.id === id);

export async function rowsLevels() {
  await sleep(120);
  return ROWS.map(({ lv }) => ({ id: lv.id, order: lv.order, title: lv.title, concept: lv.concept, rows: lv.rows, cols: 10 }));
}

export async function rowsLevel(id) {
  await sleep(120);
  const r = byId(id);
  if (!r) throw new Error('Không tìm thấy màn chơi');
  return {
    id: r.lv.id, order: r.lv.order, title: r.lv.title, goal: r.lv.goal, expected_output: r.lv.out,
    rows: r.lv.rows, cols: 10, indent_cols: 2,
    tokens: r.tokens.map(({ id: tid, text, w, topic }) => ({ id: tid, text, w, topic })),
  };
}

// ---- tiny output table (mock only) ----
function fakeRun(levelId, lines) {
  const body = lines.map((l) => l.trim());
  const joined = body.join('\n');
  const has = (re) => body.some((l) => re.test(l));
  switch (levelId) {
    case 'r1': {
      const m = joined.match(/diem = (\d+)/);
      if (has(/^print\(diem\)$/)) return m ? m[1] : '';
      if (has(/^print\("diem"\)$/)) return 'diem';
      return '';
    }
    case 'r2': {
      const ok = has(/^if diem >= 5 :$/);
      if (has(/^print\("Trượt"\)$/)) return ok ? '' : 'Trượt';
      if (has(/^print\("Đậu"\)$/)) return ok ? 'Đậu' : '';
      return '';
    }
    case 'r3': {
      const m = joined.match(/range\((\d+)\)/);
      return m ? Array.from({ length: +m[1] }, (_, i) => i).join('\n') : '';
    }
    case 'r4': {
      const m = joined.match(/range\(1, (\d)\)/);
      const end = m ? +m[1] : 4;
      const inside = lines.some((l) => /^ {4}print\(tong\)$/.test(l));
      let t = 0;
      const out = [];
      for (let i = 1; i < end; i++) {
        t += i;
        if (inside) out.push(t);
      }
      if (!inside) out.push(t);
      return out.join('\n');
    }
    case 'r5':
      if (has(/^return x \+ 2$/)) return '6';
      if (has(/^print\(x \* 2\)$/)) return '8\nNone';
      return '';
    default:
      return '';
  }
}

const fail = (group, row, message, actual, lv, code) => ({
  passed: false, error_group: group, row, message, actual_output: actual, expected_output: lv.out, code, unused_distractors: null,
});

export async function rowsRun(id, body) {
  await sleep(260);
  const r = byId(id);
  if (!r) throw new Error('Không tìm thấy màn chơi');
  const seen = new Set();
  const lines = [];
  for (const row of [...(body.rows || [])].sort((a, b) => a.row - b.row)) {
    const toks = [...row.tokens].sort((a, b) => a.col - b.col).map((t) => {
      const tk = r.tokens.find((x) => x.id === t.id);
      if (!tk || seen.has(t.id)) throw new Error('Mảnh mã không hợp lệ (422)');
      seen.add(t.id);
      return { ...t, tk };
    });
    for (let i = 0; i < toks.length; i++) {
      if (toks[i].col + toks[i].tk.w > 10 || (toks[i + 1] && toks[i].col + toks[i].tk.w > toks[i + 1].col)) throw new Error('Các mảnh chồng lên nhau (422)');
    }
    if (!toks.length) continue;
    lines.push({ row: row.row, indent: Math.min(toks[0].col, 2), badIndent: toks[0].col > 2, text: toks.map((t) => t.tk.text).join(' ') });
  }
  const lv = r.lv;
  const flat = lines.map((l) => '    '.repeat(l.indent) + l.text);
  const code = flat.join('\n');
  if (!lines.length) return fail('empty', null, 'Chưa có dòng mã nào trên bàn. Hãy kéo các mảnh lên hàng.', '', lv, '');
  const unused = r.tokens.filter((t) => t.d && !seen.has(t.id)).length;
  if (code === r.canonLines.join('\n')) {
    return { passed: true, error_group: null, row: null, message: 'Chương trình chạy đúng.', actual_output: lv.out, expected_output: lv.out, code, unused_distractors: unused };
  }
  // first board row whose line differs from the canonical line at the same position
  const firstDiff = () => {
    for (let i = 0; i < Math.max(flat.length, r.canonLines.length); i++) if (flat[i] !== r.canonLines[i]) return (lines[i] || lines[lines.length - 1]).row;
    return null;
  };
  for (const w of lv.req) {
    if (!lines.some((l) => l.text.split(' ').includes(w))) {
      return fail('missing_construct', null, `Thiếu cấu trúc bắt buộc: màn này cần dùng \`${w}\`.`, '', lv, code);
    }
  }
  const bi = lines.find((l) => l.badIndent);
  if (bi) return fail('bad_indent', bi.row, 'Sai thụt lề: khối đầu tiên của hàng này nằm quá xa bên phải.', '', lv, code);
  const colon = lines.find((l) => /^(for|if|def) /.test(l.text) && !l.text.endsWith(':'));
  if (colon) return fail('missing_colon', colon.row, 'Thiếu dấu hai chấm ở cuối dòng.', '', lv, code);
  const plain = flat.map((x) => x.trim());
  const canonPlain = r.canonLines.map((x) => x.trim());
  const sorted = (a) => a.slice().sort().join('\n');
  if (plain.join('\n') !== canonPlain.join('\n') && sorted(plain) === sorted(canonPlain)) {
    return fail('wrong_order', firstDiff(), 'Sai thứ tự: các dòng đã đủ nhưng chưa đúng thứ tự chạy.', '', lv, code);
  }
  const actual = fakeRun(lv.id, flat);
  const say = (t) => (t === '' ? 'không in gì' : 'in ' + t.replace(/\n/g, ', '));
  if (plain.join('\n') === canonPlain.join('\n')) {
    return fail('bad_indent', firstDiff(), `Sai thụt lề: chương trình ${say(actual)} thay vì ${lv.out.replace(/\n/g, ', ')}.`, actual, lv, code);
  }
  return fail('output_mismatch', firstDiff(), `Đầu ra không khớp: chương trình ${say(actual)} nhưng cần ${lv.out.replace(/\n/g, ', ')}.`, actual, lv, code);
}

const ROW_HINTS = {
  r1: ['Biến là một cái tên giữ một giá trị.', 'Gán giá trị cho biến bằng dấu =, rồi dùng print để in biến ra.', 'Dòng 1: diem = 7. Dòng 2: print(diem).'],
  r2: ['Câu lệnh if chỉ chạy dòng bên trong khi điều kiện đúng.', 'Đậu khi điểm từ 5 trở lên. Dòng bên trong if được thụt vào một cột.', 'diem = 8, rồi if diem >= 5 :, rồi print("Đậu") thụt vào một cột.'],
  r3: ['Vòng lặp for lặp lại một khối lệnh nhiều lần.', 'range(n) cho các số từ 0 đến n−1. Dòng print(i) phải thụt vào bên trong vòng lặp.', 'for i in range(3) : ở cột 0, rồi print(i) ở cột thụt lề 1.'],
  r4: ['Biến tong giữ tổng đang cộng dồn, bắt đầu từ 0.', 'Cộng i vào tong bên trong vòng lặp, nhưng chỉ in tong một lần sau khi lặp xong.', 'tong = 0, for i in range(1, 4) :, tong = tong + i thụt vào, rồi print(tong) ở cột 0.'],
  r5: ['Hàm đóng gói một đoạn mã để dùng lại, và return trả giá trị về.', 'Thân hàm thụt vào một cột; lời gọi print(gap_doi(4)) nằm ngoài hàm.', 'def gap_doi(x) :, return x * 2 thụt vào, rồi print(gap_doi(4)).'],
};
const GROUP_HINTS = {
  output_mismatch: ['Đầu ra của chương trình khác đầu ra mong đợi.', 'So sánh giá trị bạn đặt trong mã với yêu cầu của màn.', 'Kiểm tra lại các mảnh có số hoặc range(): chúng quyết định đầu ra.'],
  bad_indent: ['Vị trí cột của mảnh đầu tiên quyết định thụt lề của dòng.', 'Dòng nằm bên trong for, if hoặc def phải thụt vào một cột; dòng ngoài thì không.', 'Hàng bị tô đỏ đang thụt lề sai: dời mảnh đầu tiên của hàng đó sang cột đúng.'],
  wrong_order: ['Chương trình chạy từ hàng trên xuống hàng dưới.', 'Biến phải được tạo trước khi dùng; for/if/def đi trước thân của chúng.', 'Đổi chỗ các hàng cho đúng thứ tự: khai báo, cấu trúc, rồi lệnh in.'],
  missing_colon: ['Các dòng for, if, def kết thúc bằng một ký hiệu đặc biệt.', 'Đó là dấu hai chấm ( : ).', 'Đặt mảnh : vào cuối dòng bị tô đỏ.'],
  missing_construct: ['Màn này yêu cầu một cấu trúc lập trình cụ thể.', 'Đọc lại mục tiêu: nó cần for, if hay def?', 'Dùng đúng từ khóa của cấu trúc đó thay vì mảnh gây nhiễu.'],
  empty: ['Bàn đang trống.', 'Kéo các mảnh từ khay lên hàng, mỗi hàng là một dòng lệnh.', 'Bắt đầu từ dòng đầu tiên của chương trình ở hàng trên cùng.'],
  syntax: ['Python có quy tắc viết rất chặt.', 'Kiểm tra lại các dấu và từ khóa trên hàng bị tô đỏ.', 'Đối chiếu từng mảnh với mục tiêu của màn.'],
};
const R3_MISMATCH = ['range() dừng trước giá trị kết thúc.', 'Đếm xem cần in bao nhiêu số: 0, 1, 2 là ba số.', 'Dùng range(3) để được 0, 1, 2.'];
const R4_INDENT = ['print(tong) bên trong vòng lặp sẽ in nhiều lần.', 'Chỉ in tổng một lần, sau khi vòng lặp kết thúc.', 'Dời print(tong) về cột 0, ngang hàng với for.'];

export async function rowsHint(id, level, group) {
  await sleep(100);
  if (!byId(id)) throw new Error('Không tìm thấy màn chơi');
  let list = ROW_HINTS[id];
  if (group) {
    list = GROUP_HINTS[group] || list;
    if (id === 'r3' && group === 'output_mismatch') list = R3_MISMATCH;
    if (id === 'r4' && group === 'bad_indent') list = R4_INDENT;
  }
  return { level: Number(level), text: list[Number(level) - 1], source: 'canned' };
}
