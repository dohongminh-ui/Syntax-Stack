// Editor-window building blocks shared by the Code Rescue puzzle panel and the Syntax Rows editor.
import { el } from './ui.js';
import { icon } from './icons.js';
import { misakiAvatar } from './misaki.js';
import { highlightPy } from './highlight.js';

export const FILE_NAMES = { variables: 'bien.py', conditions: 'dieu_kien.py', loops: 'vong_lap.py', functions: 'ham.py' };

/** Title bar with a file tab (3px top border in the accent colour) and a mono meta label on the right. */
export function titleBar({ file, meta, check = false }) {
  return el('div', { class: 'ed-bar' },
    el('div', { class: 'ed-tab' },
      icon('file', { size: 14 }),
      el('span', { class: 'ed-file', text: file }),
      check ? icon('check', { size: 14, cls: 'ed-check' }) : null),
    el('span', { class: 'ed-meta', text: meta || '' }));
}

/**
 * Code with a line-number gutter and highlight.
 * lines: array of strings | { text, n, cls }. opts.slot: { text } renders an inline dashed socket for `___`.
 */
export function codeBlock(lines, { slot = null, label = 'Đoạn mã', raw = null } = {}) {
  const wrap = el('div', { class: 'code', role: 'region', 'aria-label': label });
  const list = Array.isArray(lines) ? lines : String(lines).split('\n');
  list.forEach((item, i) => {
    const text = typeof item === 'string' ? item : item.text;
    const n = typeof item === 'string' ? i + 1 : item.n ?? i + 1;
    const cls = typeof item === 'string' ? '' : item.cls || '';
    const row = el('div', { class: 'code-line ' + cls }, el('span', { class: 'ln', 'aria-hidden': 'true', text: n }));
    const lt = el('span', { class: 'lt' });
    if (slot && text.includes('___')) {
      const [a, b] = text.split('___');
      lt.append(highlightPy(a), el('span', { class: 'blank' + (slot.text ? ' filled' : ''), 'aria-label': slot.text ? 'Đã điền: ' + slot.text : 'Chỗ trống' }, slot.text ? highlightPy(slot.text) : ''), highlightPy(b));
    } else if (text) lt.append(highlightPy(text));
    else lt.textContent = ' ';
    row.append(lt);
    wrap.append(row);
  });
  return wrap;
}

/** Mini terminal: faint `$ python main.py` prompt, then the output lines. */
export function terminal(output, { label = '', cls = '' } = {}) {
  const t = el('div', { class: 'term ' + cls });
  if (label) t.append(el('div', { class: 'term-l', text: label }));
  t.append(el('div', { class: 'term-ps', text: '$ python main.py' }));
  const out = el('pre', { class: 'term-out' });
  out.textContent = output ?? '';
  t.append(out);
  return t;
}

/** Line diff (LCS) between the player's lines and the solution. `-` red, `+` Matcha, context muted. */
export function diffView(playerText, solutionText) {
  const clean = (t) => t.replace(/\r/g, '').split('\n').map((x) => x.replace(/[ \t]+$/, ''));
  const trimEnd = (arr) => {
    while (arr.length > 1 && arr[arr.length - 1] === '') arr.pop();
    return arr;
  };
  const a = trimEnd(clean(playerText));
  const b = trimEnd(clean(solutionText));
  const dp = Array.from({ length: a.length + 1 }, () => Array(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i--)
    for (let j = b.length - 1; j >= 0; j--) dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const ops = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) { ops.push([' ', a[i]]); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) ops.push(['-', a[i++]]);
    else ops.push(['+', b[j++]]);
  }
  while (i < a.length) ops.push(['-', a[i++]]);
  while (j < b.length) ops.push(['+', b[j++]]);
  // group removals before additions inside a changed hunk so it reads as -/+ pairs
  const out = [];
  for (let k = 0; k < ops.length; ) {
    if (ops[k][0] === ' ') { out.push(ops[k++]); continue; }
    const minus = [];
    const plus = [];
    while (k < ops.length && ops[k][0] !== ' ') (ops[k][0] === '-' ? minus : plus).push(ops[k++]);
    out.push(...minus, ...plus);
  }
  const wrap = el('div', { class: 'diff', role: 'region', 'aria-label': 'So sánh với đáp án' });
  for (const [sign, text] of out) {
    const lt = el('span', { class: 'lt' });
    if (text) lt.append(highlightPy(text));
    else lt.textContent = ' ';
    wrap.append(el('div', { class: 'diff-line ' + (sign === '-' ? 'del' : sign === '+' ? 'add' : 'ctx') },
      el('span', { class: 'sign', 'aria-hidden': 'true', text: sign === ' ' ? '' : sign }), lt));
  }
  return wrap;
}

/** `# comment` line in muted italic mono. */
export function comment(text, cls = '') {
  return el('p', { class: 'cm ' + cls, text: '# ' + text });
}

/** Text with `inline code` spans; everything is inserted as text nodes (never innerHTML). */
export function richText(text) {
  const frag = document.createDocumentFragment();
  String(text ?? '').split(/(`[^`\n]+`)/g).forEach((part) => {
    if (part.length > 2 && part.startsWith('`') && part.endsWith('`')) frag.append(el('code', { text: part.slice(1, -1) }));
    else if (part) frag.append(document.createTextNode(part));
  });
  return frag;
}

/**
 * Tutor text. source 'ai' -> a labelled .tutor block; 'canned' -> the `# context: text` comment.
 * `{ loading: true }` renders the AI shell with a "reading" state.
 */
export function tutorNote({ text = '', source = 'canned', context = '', loading = false, cls = '' } = {}) {
  if (!loading && source !== 'ai') {
    const label = context ? `${context}: ` : '';
    return comment(label + text, cls);
  }
  const body = loading
    ? el('p', { class: 'tutor-body tutor-loading' }, 'Misaki đang đọc',
        el('span', { class: 'tutor-dots', 'aria-hidden': 'true' }, el('i'), el('i'), el('i')))
    : el('p', { class: 'tutor-body' }, richText(text));
  return el('div', { class: 'tutor ' + cls, role: 'group', 'aria-label': 'Misaki, gia sư AI' },
    el('div', { class: 'tutor-head' },
      misakiAvatar({ cls: 'tutor-badge' }),
      el('span', { class: 'tutor-label', text: 'MISAKI · GIA SƯ AI' }),
      context ? el('span', { class: 'tutor-ctx', text: context }) : null),
    body,
    loading ? null : el('p', { class: 'tutor-foot', text: 'Do AI tạo, có thể chưa chính xác. Hãy tự kiểm tra bằng Chạy kiểm tra.' }));
}
