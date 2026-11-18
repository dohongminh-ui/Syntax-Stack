// Mock of the real API (docs/api-contract.md). Used ONLY with ?mock=1.
// Answers live here and are checked client-side for the mock only; the real client never sees them.

const T = {
  variables: 'var',
  conditions: 'cond',
  loops: 'loop',
  functions: 'func',
};

// ---- puzzle bank -----------------------------------------------------------------------------
// Compact definitions; expanded to public puzzles + private answers below.
const DEFS = [
  // ---- variables
  { id: 'var_add_fill__001', tpl: 'var_add_fill', topic: 'variables', type: 'fill_blank', tier: 1,
    prompt: 'Điền số còn thiếu để chương trình in ra 7.',
    code: 'x = 5\nx = x + ___\nprint(x)', out: '7',
    options: ['2', '3', '1', '7'], answer: 0,
    hints: ['x = x + ... cộng thêm vào giá trị cũ của x.', 'x đang là 5, cần ra 7.', 'Số cần thêm = 7 − 5.'],
    solution: 'x = 5\nx = x + 2\nprint(x)', explain: 'x ban đầu là 5. Muốn in ra 7 thì phải cộng thêm 2.', group: 'output_mismatch' },
  { id: 'var_copy_pred__001', tpl: 'var_copy_pred', topic: 'variables', type: 'predict_output', tier: 1,
    prompt: 'Chương trình sau in ra gì?',
    code: 'a = 3\nb = a * 2\na = 10\nprint(b)', options: ['6', '10', '3', '20'], answer: 0,
    hints: ['b được tính ngay tại dòng 2.', 'Đổi a sau đó không làm b thay đổi.', 'b = 3 * 2.'],
    solution: 'Đầu ra: 6', explain: 'b nhận giá trị 6 lúc a còn là 3. Việc gán lại a = 10 sau đó không ảnh hưởng đến b.', group: 'output_mismatch' },
  { id: 'var_order_parsons__001', tpl: 'var_order_parsons', topic: 'variables', type: 'parsons', tier: 2,
    prompt: 'Sắp xếp các dòng để chương trình in ra 8.',
    sol: [['x = 4', 0], ['y = x * 2', 0], ['print(y)', 0]], out: '8',
    hints: ['Biến phải được tạo trước khi dùng.', 'x cần có trước y.', 'print nằm cuối cùng.'],
    solution: 'x = 4\ny = x * 2\nprint(y)', explain: 'Phải gán x trước, rồi tính y từ x, cuối cùng mới in y.', group: 'wrong_order' },
  { id: 'var_name_bug__001', tpl: 'var_name_bug', topic: 'variables', type: 'find_bug', tier: 2,
    prompt: 'Tìm dòng sai để chương trình in ra 13.',
    src: [['x = 10', 0], ['y = 3', 0], ['print(x + z)', 0]], bug: 2, out: '13',
    options: ['print(x + y)', 'print(x - y)', 'print(x + 3 + z)'], answer: 0,
    hints: ['Có một tên biến chưa được tạo.', 'Nhìn lại dòng cuối.', 'z chưa từng được gán.'],
    solution: 'x = 10\ny = 3\nprint(x + y)', explain: 'z chưa được định nghĩa nên gây lỗi. Cần dùng y.', group: 'wrong_fix' },
  { id: 'var_name_bug__002', tpl: 'var_name_bug', topic: 'variables', type: 'find_bug', tier: 2,
    prompt: 'Tìm dòng sai để chương trình in ra 14.',
    src: [['a = 7', 0], ['b = 2', 0], ['print(a * c)', 0]], bug: 2, out: '14',
    options: ['print(a * b)', 'print(a + b)', 'print(a * 2 * c)'], answer: 0,
    hints: ['Có một tên biến chưa được tạo.', 'Nhìn lại dòng cuối.', 'c chưa từng được gán.'],
    solution: 'a = 7\nb = 2\nprint(a * b)', explain: 'c chưa được định nghĩa. Cần dùng b.', group: 'wrong_fix' },

  // ---- conditions
  { id: 'cond_ge_fill__001', tpl: 'cond_ge_fill', topic: 'conditions', type: 'fill_blank', tier: 1,
    prompt: 'Điền toán tử để chương trình in "Đậu" khi điểm từ 7 trở lên.',
    code: 'score = 7\nif score ___ 7:\n    print("Đậu")\nelse:\n    print("Rớt")', out: 'Đậu',
    options: ['>=', '<', '>', '=='], answer: 0,
    hints: ['"Từ 7 trở lên" gồm cả 7.', 'Toán tử > không gồm 7.', 'Dùng >=.'],
    solution: 'score = 7\nif score >= 7:\n    print("Đậu")\nelse:\n    print("Rớt")', explain: '"Từ 7 trở lên" gồm cả 7, nên dùng >=. Toán tử > sẽ loại 7.', group: 'output_mismatch' },
  { id: 'cond_elif_pred__001', tpl: 'cond_elif_pred', topic: 'conditions', type: 'predict_output', tier: 2,
    prompt: 'Chương trình sau in ra gì?',
    code: 'n = 4\nif n > 5:\n    print("A")\nelif n > 2:\n    print("B")\nelse:\n    print("C")', options: ['B', 'A', 'C', 'B\nC'], answer: 0,
    hints: ['Kiểm tra từng nhánh từ trên xuống.', 'n > 5 sai, n > 2 đúng.', 'Chỉ nhánh đúng đầu tiên chạy.'],
    solution: 'Đầu ra: B', explain: 'n > 5 sai, nhưng n > 2 đúng nên in B. Các nhánh còn lại bị bỏ qua.', group: 'output_mismatch' },
  { id: 'cond_adult_parsons__001', tpl: 'cond_adult_parsons', topic: 'conditions', type: 'parsons', tier: 3,
    prompt: 'Sắp xếp và thụt lề đúng để in "Người lớn".',
    sol: [['age = 20', 0], ['if age >= 18:', 0], ['print("Người lớn")', 1], ['else:', 0], ['print("Trẻ em")', 1]], out: 'Người lớn',
    hints: ['Dòng if đi trước nhánh của nó.', 'Lệnh print bên trong if/else được thụt vào 1 cấp.', 'else thẳng hàng với if.'],
    solution: 'age = 20\nif age >= 18:\n    print("Người lớn")\nelse:\n    print("Trẻ em")', explain: 'Thân của if và else phải thụt lề một cấp; if và else thẳng hàng với nhau.', group: 'bad_indent' },
  { id: 'cond_colon_bug__001', tpl: 'cond_colon_bug', topic: 'conditions', type: 'find_bug', tier: 1,
    prompt: 'Tìm dòng sai để chương trình in ra "lớn".',
    src: [['x = 8', 0], ['if x > 5', 0], ['print("lớn")', 1], ['else:', 0], ['print("nhỏ")', 1]], bug: 1, out: 'lớn',
    options: ['if x > 5:', 'if x => 5:', 'if x > 5;'], answer: 0,
    hints: ['Có một ký hiệu bị thiếu.', 'Sau điều kiện if phải có dấu gì?', 'Thiếu dấu hai chấm.'],
    solution: 'x = 8\nif x > 5:\n    print("lớn")\nelse:\n    print("nhỏ")', explain: 'Câu lệnh if phải kết thúc bằng dấu hai chấm (:).', group: 'wrong_fix' },
  { id: 'cond_colon_bug__002', tpl: 'cond_colon_bug', topic: 'conditions', type: 'find_bug', tier: 1,
    prompt: 'Tìm dòng sai để chương trình in ra "chẵn".',
    src: [['n = 6', 0], ['if n % 2 == 0', 0], ['print("chẵn")', 1], ['else:', 0], ['print("lẻ")', 1]], bug: 1, out: 'chẵn',
    options: ['if n % 2 == 0:', 'if n % 2 = 0:', 'if n / 2 == 0:'], answer: 0,
    hints: ['Có một ký hiệu bị thiếu.', 'Sau điều kiện if phải có dấu gì?', 'Thiếu dấu hai chấm.'],
    solution: 'n = 6\nif n % 2 == 0:\n    print("chẵn")\nelse:\n    print("lẻ")', explain: 'Câu lệnh if phải kết thúc bằng dấu hai chấm (:).', group: 'wrong_fix' },

  // ---- loops
  { id: 'loop_range_fill__001', tpl: 'loop_range_fill', topic: 'loops', type: 'fill_blank', tier: 1,
    prompt: 'Điền giá trị còn thiếu để chương trình in ra 0, 1, 2.',
    code: 'for i in range(___):\n    print(i)', out: '0\n1\n2',
    options: ['3', '2', '4', '1'], answer: 0,
    hints: ['range() dừng trước giá trị kết thúc.', 'Đếm xem cần bao nhiêu số được in ra.', 'In ra 3 số nên cần range(3).'],
    solution: 'for i in range(3):\n    print(i)', explain: 'range(n) dừng trước n, nên range(3) cho 0, 1, 2.', group: 'output_mismatch' },
  { id: 'loop_sum_pred__001', tpl: 'loop_sum_pred', topic: 'loops', type: 'predict_output', tier: 2,
    prompt: 'Chương trình sau in ra gì?',
    code: 'total = 0\nfor i in range(1, 4):\n    total = total + i\nprint(total)', options: ['6', '10', '3', '4'], answer: 0,
    hints: ['i nhận các giá trị 1, 2, 3.', 'range(1, 4) không gồm 4.', '1 + 2 + 3.'],
    solution: 'Đầu ra: 6', explain: 'i chạy 1, 2, 3 (không gồm 4) nên tổng là 1 + 2 + 3 = 6.', group: 'output_mismatch' },
  { id: 'loop_done_parsons__001', tpl: 'loop_done_parsons', topic: 'loops', type: 'parsons', tier: 2,
    prompt: 'Sắp xếp và thụt lề để in 0, 1, 2 rồi in "Xong".',
    sol: [['for i in range(3):', 0], ['print(i)', 1], ['print("Xong")', 0]], out: '0\n1\n2\nXong',
    hints: ['Vòng lặp for đi trước thân của nó.', 'print(i) nằm trong vòng lặp.', '"Xong" chỉ in một lần, sau vòng lặp.'],
    solution: 'for i in range(3):\n    print(i)\nprint("Xong")', explain: 'print(i) thụt vào để lặp lại; print("Xong") thẳng hàng với for nên chỉ chạy một lần sau cùng.', group: 'bad_indent' },
  { id: 'loop_range_bug__001', tpl: 'loop_range_bug', topic: 'loops', type: 'find_bug', tier: 1,
    prompt: 'Tìm dòng sai để chương trình in ra 1, 2, 3.',
    src: [['for i in range(1, 3):', 0], ['print(i)', 1]], bug: 0, out: '1\n2\n3',
    options: ['for i in range(1, 4):', 'for i in range(0, 3):', 'for i in range(1, 2):'], answer: 0,
    hints: ['Giá trị kết thúc của range không được in.', 'Chương trình đang thiếu số 3.', 'Cần kết thúc ở 4.'],
    solution: 'for i in range(1, 4):\n    print(i)', explain: 'range(1, 3) chỉ cho 1, 2. Muốn có 3 thì kết thúc phải là 4.', group: 'wrong_fix' },
  { id: 'loop_range_bug__002', tpl: 'loop_range_bug', topic: 'loops', type: 'find_bug', tier: 1,
    prompt: 'Tìm dòng sai để chương trình in ra 2, 3, 4.',
    src: [['for k in range(2, 4):', 0], ['print(k)', 1]], bug: 0, out: '2\n3\n4',
    options: ['for k in range(2, 5):', 'for k in range(3, 4):', 'for k in range(1, 4):'], answer: 0,
    hints: ['Giá trị kết thúc của range không được in.', 'Chương trình đang thiếu số 4.', 'Cần kết thúc ở 5.'],
    solution: 'for k in range(2, 5):\n    print(k)', explain: 'range(2, 4) chỉ cho 2, 3. Muốn có 4 thì kết thúc phải là 5.', group: 'wrong_fix' },

  // ---- functions
  { id: 'func_add_fill__001', tpl: 'func_add_fill', topic: 'functions', type: 'fill_blank', tier: 1,
    prompt: 'Điền biểu thức để hàm trả về tổng hai số.',
    code: 'def add(a, b):\n    return ___\n\nprint(add(2, 3))', out: '5',
    options: ['a + b', 'a - b', 'a * b', 'a'], answer: 0,
    hints: ['Hàm phải trả về một giá trị.', 'Tổng nghĩa là phép cộng.', 'return a + b.'],
    solution: 'def add(a, b):\n    return a + b\n\nprint(add(2, 3))', explain: 'Tổng của hai số là a + b; return trả giá trị đó về cho nơi gọi hàm.', group: 'output_mismatch' },
  { id: 'func_double_pred__001', tpl: 'func_double_pred', topic: 'functions', type: 'predict_output', tier: 2,
    prompt: 'Chương trình sau in ra gì?',
    code: 'def double(n):\n    return n * 2\n\nprint(double(4) + 1)', options: ['9', '8', '10', '5'], answer: 0,
    hints: ['Tính double(4) trước.', 'double(4) = 8.', 'Sau đó cộng thêm 1.'],
    solution: 'Đầu ra: 9', explain: 'double(4) trả về 8, cộng thêm 1 được 9.', group: 'output_mismatch' },
  { id: 'func_greet_parsons__001', tpl: 'func_greet_parsons', topic: 'functions', type: 'parsons', tier: 2,
    prompt: 'Sắp xếp và thụt lề để in "Xin chào, An".',
    sol: [['def greet(name):', 0], ['return "Xin chào, " + name', 1], ['print(greet("An"))', 0]], out: 'Xin chào, An',
    hints: ['Hàm phải được định nghĩa trước khi gọi.', 'Thân hàm được thụt vào 1 cấp.', 'Lệnh gọi hàm thẳng hàng với def.'],
    solution: 'def greet(name):\n    return "Xin chào, " + name\nprint(greet("An"))', explain: 'Định nghĩa hàm trước, thân hàm thụt lề, rồi mới gọi hàm ở ngoài.', group: 'bad_indent' },
  { id: 'func_return_bug__001', tpl: 'func_return_bug', topic: 'functions', type: 'find_bug', tier: 2,
    prompt: 'Tìm dòng sai để chương trình in ra 5 (và không in thêm None).',
    src: [['def add(a, b):', 0], ['print(a + b)', 1], ['s = add(2, 3)', 0], ['print(s)', 0]], bug: 1, out: '5',
    options: ['return a + b', 'return a', 'print(a - b)'], answer: 0,
    hints: ['Hàm cần trả giá trị về, không chỉ in.', 'Biến s nhận được gì từ hàm?', 'Dùng return.'],
    solution: 'def add(a, b):\n    return a + b\ns = add(2, 3)\nprint(s)', explain: 'print chỉ in ra màn hình, còn s sẽ là None. Cần return để trả giá trị.', group: 'wrong_fix' },
  { id: 'func_return_bug__002', tpl: 'func_return_bug', topic: 'functions', type: 'find_bug', tier: 2,
    prompt: 'Tìm dòng sai để chương trình in ra 12 (và không in thêm None).',
    src: [['def mul(a, b):', 0], ['print(a * b)', 1], ['p = mul(3, 4)', 0], ['print(p)', 0]], bug: 1, out: '12',
    options: ['return a * b', 'return a + b', 'print(a + b)'], answer: 0,
    hints: ['Hàm cần trả giá trị về, không chỉ in.', 'Biến p nhận được gì từ hàm?', 'Dùng return.'],
    solution: 'def mul(a, b):\n    return a * b\np = mul(3, 4)\nprint(p)', explain: 'print chỉ in ra màn hình, còn p sẽ là None. Cần return để trả giá trị.', group: 'wrong_fix' },
];

const OPT_IDS = ['a', 'b', 'c', 'd'];

function expand(d) {
  const pub = {
    id: d.id, template_id: d.tpl, topic: d.topic, type: d.type, tier: d.tier, prompt: d.prompt,
    code: null, expected_output: d.out ?? null, lines: null, options: null,
  };
  const priv = { solution: d.solution, explain: d.explain, group: d.group, hints: d.hints };
  if (d.type === 'fill_blank' || d.type === 'predict_output') {
    pub.code = d.code;
    pub.options = d.options.map((t, i) => ({ id: OPT_IDS[i], text: t }));
    if (d.type === 'predict_output') pub.expected_output = null;
    priv.answer = OPT_IDS[d.answer];
  } else if (d.type === 'parsons') {
    const lines = d.sol.map(([text], i) => ({ id: 'l' + (i + 1), text }));
    priv.order = d.sol.map(([, indent], i) => ({ line_id: 'l' + (i + 1), indent }));
    const shuffled = lines.slice().reverse();
    if (shuffled.length > 2) shuffled.push(shuffled.shift());
    pub.lines = shuffled;
  } else {
    pub.lines = d.src.map(([text, indent], i) => ({ id: 'l' + (i + 1), text, indent }));
    // find_bug v2: options are whole-line edits spanning >= 2 lines: [wrong edit of another line, correct, ...wrong edits of the buggy line]
    const other = d.src.findIndex((_, i) => i !== d.bug && /\d/.test(d.src[i][0]));
    const oi = other >= 0 ? other : d.bug === 0 ? 1 : 0;
    const mutated = d.src[oi][0].replace(/\d+/, (n) => String(+n + 1));
    const edits = [[oi, mutated === d.src[oi][0] ? d.src[oi][0] + ' + 1' : mutated], ...d.options.map((t) => [d.bug, t])];
    pub.options = edits.map(([li, t], i) => ({ id: OPT_IDS[i], line_id: 'l' + (li + 1), text: t }));
    priv.lineId = 'l' + (d.bug + 1);
    priv.answer = OPT_IDS[1 + d.answer];
  }
  return { pub, priv };
}

const BANK = DEFS.map(expand);
const byId = (id) => BANK.find((b) => b.pub.id === id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const pick = (arr) => arr[Math.floor(Math.random() * arr.length)];
let firstCall = true;

export async function health() {
  await sleep(40);
  return { ok: true, puzzles: BANK.length };
}

function publicCopy(entry, level) {
  const p = JSON.parse(JSON.stringify(entry.pub));
  if (p.options && level === 'beginner') p.options = p.options.slice(0, 3);
  return p;
}

export async function nextPuzzle(req) {
  await sleep(150);
  const ex = new Set(req.exclude_ids || []);
  const exT = new Set(req.exclude_templates || []);
  let pool;

  const demo = new URLSearchParams(location.search).get('demo') || '';
  if (firstCall && demo.startsWith('puzzle-')) {
    const type = demo.slice(7).replace(/-/g, '_');
    const c = BANK.filter((b) => b.pub.type === type && b.pub.topic === req.topic);
    firstCall = false;
    if (c.length) return publicCopy(pick(c), req.level);
  }
  firstCall = false;

  if (req.kind === 'debug') {
    const topic = (BANK.find((b) => b.pub.template_id === req.template_id) || {}).pub?.topic || req.topic;
    pool = BANK.filter((b) => b.pub.template_id === req.template_id && b.pub.type === 'find_bug' && !ex.has(b.pub.id));
    if (!pool.length) pool = BANK.filter((b) => b.pub.topic === topic && b.pub.type === 'find_bug' && !ex.has(b.pub.id));
    if (!pool.length) pool = BANK.filter((b) => b.pub.template_id === req.template_id && b.pub.type === 'find_bug');
    if (!pool.length) pool = BANK.filter((b) => b.pub.type === 'find_bug');
  } else {
    pool = BANK.filter((b) => b.pub.topic === req.topic && !ex.has(b.pub.id));
    if (!pool.length) pool = BANK.filter((b) => b.pub.topic === req.topic); // mock bank is small: allow repeats
    const soft = pool.filter((b) => !exT.has(b.pub.template_id));
    if (soft.length) pool = soft;
    const tiered = pool.filter((b) => b.pub.tier === req.tier);
    if (tiered.length) pool = tiered;
    if (req.level === 'advanced') {
      const hard = pool.filter((b) => b.pub.type === 'find_bug' || b.pub.type === 'predict_output');
      if (hard.length) pool = hard;
    }
  }
  if (!pool.length) throw new Error('Không có câu đố phù hợp');
  return publicCopy(pick(pool), req.level);
}

function check(entry, body) {
  const { pub, priv } = entry;
  if (pub.type === 'fill_blank' || pub.type === 'predict_output') {
    return body.option_id === priv.answer
      ? { ok: true }
      : { ok: false, group: pub.type === 'fill_blank' ? 'output_mismatch' : 'wrong_choice', message: 'Đáp án chưa đúng: đầu ra không khớp với yêu cầu.' };
  }
  if (pub.type === 'parsons') {
    const got = body.order || [];
    const orderOk = got.length === priv.order.length && got.every((g, i) => g.line_id === priv.order[i].line_id);
    if (!orderOk) return { ok: false, group: 'wrong_order', message: 'Thứ tự các dòng chưa đúng.' };
    const indentOk = got.every((g, i) => g.indent === priv.order[i].indent);
    return indentOk ? { ok: true } : { ok: false, group: 'bad_indent', message: 'Thứ tự đúng nhưng thụt lề chưa đúng.' };
  }
  if (body.option_id === priv.answer) return { ok: true };
  const picked = pub.options.find((o) => o.id === body.option_id);
  return picked && picked.line_id !== priv.lineId
    ? { ok: false, group: 'wrong_line', message: 'Cách sửa này nằm ở dòng không chứa lỗi.' }
    : { ok: false, group: 'wrong_fix', message: 'Đúng dòng lỗi, nhưng cách sửa chưa đúng.' };
}

export async function submitAnswer(id, body) {
  await sleep(200);
  const entry = byId(id);
  if (!entry) throw new Error('Không tìm thấy câu đố');
  const r = check(entry, body);
  if (r.ok) {
    return { correct: true, error_group: null, message: 'Chính xác!', actual_output: null, solution_code: null, explanation: null };
  }
  return {
    correct: false,
    error_group: r.group,
    message: r.message,
    actual_output: null,
    solution_code: body.reveal ? entry.priv.solution : null,
    explanation: body.reveal ? entry.priv.explain : null,
  };
}

export async function getHint(id, level) {
  await sleep(100);
  const entry = byId(id);
  if (!entry) throw new Error('Không tìm thấy câu đố');
  return { level: Number(level), text: entry.priv.hints[Number(level) - 1], source: 'canned' };
}

export async function rematch(id, level) {
  const entry = byId(id);
  if (!entry) throw new Error('Không tìm thấy câu đố');
  const { topic, tier } = entry.pub;
  const puzzle = await nextPuzzle({ topic, tier, level, exclude_ids: [id] });
  return { puzzle, text: 'Thử áp dụng lại quy tắc vừa gặp vào câu đố mới này.', source: 'canned' };
}

export async function explainPrediction(prediction, actual) {
  await sleep(300);
  const show = (t) => (t && t.trim() ? t.trim().replaceAll('\n', ' · ') : '(không có đầu ra)');
  return {
    text: `Bạn đoán: ${show(prediction)}. Chương trình thật sự in: ${show(actual)}. Thử đi từng dòng theo thứ tự chạy và ghi lại giá trị của biến sau mỗi bước.`,
    source: 'canned',
  };
}

const MOCK_TOPIC_NAMES = { variables: 'Biến', conditions: 'Điều kiện', loops: 'Vòng lặp', functions: 'Hàm' };

export async function debrief(body) {
  await sleep(300);
  const counts = {};
  for (const w of body.wrong || []) {
    const topic = byId(w.puzzle_id)?.pub.topic;
    if (topic) counts[topic] = (counts[topic] || 0) + 1;
  }
  const top = Object.entries(counts).sort((a, b) => b[1] - a[1])[0];
  const focus = top ? top[0] : null;
  return {
    text: `Ván này bạn sai ${(body.wrong || []).length} câu${focus ? `, nhiều nhất ở chủ đề ${MOCK_TOPIC_NAMES[focus] || focus}` : ''}. Hãy đọc lại phần giải thích của từng câu rồi luyện thêm một lượt ngắn.`,
    source: 'canned',
    focus_topic: focus,
  };
}

// ---- custom sets (canned: built from the loops puzzles of the bank) ----
const mockFail = (status, detail) => Object.assign(new Error(detail), { status });

function mockSet(id, code, level) {
  const puzzles = [];
  const skipped = [];
  for (const type of ['fill_blank', 'predict_output', 'parsons', 'find_bug']) {
    const entry = BANK.find((b) => b.pub.topic === 'loops' && b.pub.type === type);
    if (entry) puzzles.push(publicCopy(entry, level));
    else skipped.push({ type, reason: 'chương trình này không có đủ chỗ để tạo dạng câu đố này' });
  }
  const out = BANK.find((b) => b.pub.topic === 'loops' && b.pub.expected_output)?.pub.expected_output ?? '';
  return { id, topic: 'loops', code, expected_output: out, puzzles, skipped };
}

export async function createCustomSet(body) {
  await sleep(500);
  const code = String(body?.code ?? '').trim();
  if (!code) throw mockFail(422, 'Chương trình đang trống. Hãy dán một đoạn mã Python ngắn.');
  return mockSet('mock-set', code, body.level);
}

export async function getCustomSet(id, level) {
  await sleep(250);
  if (id !== 'mock-set' && id !== 'demo') throw mockFail(404, 'Không tìm thấy bộ câu đố.');
  return mockSet(id, ['total = 0', 'for i in range(1, 4):', '    total = total + i', 'print(total)'].join('\n'), level);
}

// Syntax Rows mock lives in mock-rows.js
export { rowsLevels, rowsLevel, rowsRun, rowsHint } from './mock-rows.js';
