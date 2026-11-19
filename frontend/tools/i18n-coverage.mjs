#!/usr/bin/env node
// i18n coverage check. Run from anywhere:  node frontend/tools/i18n-coverage.mjs
//
// Extracts every Vietnamese (diacritic-bearing) string literal / template literal from js/*.js and every
// Vietnamese text node / translatable attribute from index.html, then reports the ones that neither
// EN (js/i18n-en.js) nor an EN_PATTERNS regex covers. Exit code 1 if anything is uncovered.
//
// Template literals are tested with the placeholders replaced by sample values (numbers, a name, a time...);
// a template passes if ANY sample combination is covered. Comments are ignored.
//
// Use --list to print every extracted string, --stats for counts.
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const JS_DIR = join(ROOT, 'js');

// Strings that contain Vietnamese but are intentionally NOT translated. Each entry needs a reason.
// `file` (optional) limits the entry to one file; `re` is tested against the extracted string.
const WHITELIST = [
  { re: /^syntax_stack$/, reason: 'brand wordmark' },
  { file: 'index.html', re: /^(Syntax Stack: tiêu đề bằng phím|Nhóm Le Rouge|Web \(trình duyệt\)|Lập trình Python cơ bản)/, reason: 'JSON-LD / social-card metadata for crawlers (not rendered UI)' },
  { file: 'index.html', re: /^Language \/ Ngôn ngữ$/, reason: 'the language toggle label is bilingual on purpose, so it reads right in either language' },
  { file: 'i18n.js', re: /./, reason: 'i18n runtime (contains Vietnamese character classes only)' },
  { file: 'i18n-core.js', re: /./, reason: 'i18n core (contains Vietnamese character classes only)' },
  { file: 'index.html', re: /^Syntax Stack cần JavaScript để chạy/, reason: '<noscript> text: only shown when JavaScript is off, so no script can translate it' },
  { file: 'mock-ranked.js', re: /^(Hải|Thảo|Quân|Bảo|Phúc|Ngọc|Tùng|Hà|Khánh|Sơn|Yến|Đạt|Kiên)$/, reason: 'Vietnamese given names in the fake leaderboard (personal names are not translated)' },
  { file: 'custom.js', re: /^score = 75\n/, reason: 'Python example code shown in the editor (code is never translated)' },
  { file: 'mock-api.js', re: /\bprint\(|^return "|^score = 7\n|^def greet\(|^(Đậu|Người lớn|lớn|chẵn|Xin chào, An)$/, reason: 'Python code and program output inside the offline demo puzzles (code is never translated)' },
  { file: 'mock-rows.js', re: /\bprint\(|^(Đậu|Trượt)$/, reason: 'Python code and program output inside the offline Syntax Rows levels' },
];

// ASCII-only Vietnamese UI strings (no diacritics, so the detector cannot see them). They must exist in EN.
const ASCII_REQUIRED = ['Bom', 'Xanh', 'Cam', 'bien.py', 'dieu_kien.py', 'vong_lap.py', 'ham.py'];

// Calls whose string arguments are developer-only (console output, thrown internal errors) are skipped by the
// lexer pass below when the literal is the direct argument of one of these.
const DEV_CALLS = /(console\.(log|warn|error|info|debug)|\bassert)\s*\($/;

const TRANSLATABLE_ATTRS = ['aria-label', 'placeholder', 'title', 'alt', 'value', 'content'];

const VI = /[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]/i;

// ---------------------------------------------------------------------------------------------------------
// JS lexer: yields string and template literals, skipping comments and regex literals.
// ---------------------------------------------------------------------------------------------------------
function lexJs(src) {
  const out = [];
  let i = 0;
  const line = (pos) => src.slice(0, pos).split('\n').length;

  function unescape(s) {
    return s.replace(/\\(u\{([0-9a-fA-F]+)\}|u([0-9a-fA-F]{4})|x([0-9a-fA-F]{2})|[\s\S])/g, (m, a, b, c, d) => {
      if (b) return String.fromCodePoint(parseInt(b, 16));
      if (c) return String.fromCharCode(parseInt(c, 16));
      if (d) return String.fromCharCode(parseInt(d, 16));
      const ch = m[1];
      return ch === 'n' ? '\n' : ch === 't' ? '\t' : ch === 'r' ? '\r' : ch === '\n' ? '' : ch;
    });
  }

  // Scan code. If `inTemplate`, stop at the matching "}" of a ${ } expression.
  function scan(inTemplate) {
    let depth = 0;
    let prev = ''; // last significant char
    let prevWord = '';
    while (i < src.length) {
      const c = src[i];
      const n = src[i + 1];
      if (c === '/' && n === '/') { while (i < src.length && src[i] !== '\n') i++; continue; }
      if (c === '/' && n === '*') { i = src.indexOf('*/', i + 2); i = i < 0 ? src.length : i + 2; continue; }
      if (c === '"' || c === "'") {
        const start = i;
        i++;
        let s = '';
        while (i < src.length && src[i] !== c) {
          if (src[i] === '\\') { s += src[i] + src[i + 1]; i += 2; } else { s += src[i]; i++; }
        }
        i++;
        const before = src.slice(Math.max(0, start - 40), start);
        out.push({ text: unescape(s), line: line(start), kind: 'str', dev: DEV_CALLS.test(before.replace(/\s+$/, '')) });
        prev = c; prevWord = '';
        continue;
      }
      if (c === '`') { const t = readTemplate(); out.push(t); prev = '`'; prevWord = ''; continue; }
      if (c === '/') {
        const regexOk = prev === '' || '(,=:[!&|?{};+-*%<>~^'.includes(prev) || ['return', 'typeof', 'case', 'in', 'of'].includes(prevWord);
        if (regexOk) {
          i++;
          let inClass = false;
          while (i < src.length) {
            if (src[i] === '\\') { i += 2; continue; }
            if (src[i] === '[') inClass = true;
            else if (src[i] === ']') inClass = false;
            else if (src[i] === '/' && !inClass) break;
            else if (src[i] === '\n') break;
            i++;
          }
          i++;
          while (/[a-z]/i.test(src[i] || '')) i++;
          prev = ')'; prevWord = '';
          continue;
        }
      }
      if (c === '{') depth++;
      if (c === '}') {
        if (inTemplate && depth === 0) { i++; return; }
        depth--;
      }
      if (/\s/.test(c)) { i++; continue; }
      if (/[A-Za-z_$]/.test(c)) {
        let w = '';
        while (i < src.length && /[\w$]/.test(src[i])) w += src[i++];
        prev = 'a'; prevWord = w;
        continue;
      }
      prev = c; prevWord = '';
      i++;
    }
  }

  function readTemplate() {
    const start = i;
    i++; // opening backtick
    const parts = [];
    let cur = '';
    while (i < src.length && src[i] !== '`') {
      if (src[i] === '\\') { cur += src[i] + src[i + 1]; i += 2; continue; }
      if (src[i] === '$' && src[i + 1] === '{') {
        i += 2;
        parts.push(unescape(cur)); cur = '';
        scan(true);
        continue;
      }
      cur += src[i++];
    }
    i++;
    parts.push(unescape(cur));
    return { parts, text: parts.join('\u0000'), line: line(start), kind: 'tpl', dev: false };
  }

  scan(false);
  return out;
}

// ---------------------------------------------------------------------------------------------------------
// HTML extraction
// ---------------------------------------------------------------------------------------------------------
function decodeEntities(s) {
  return s
    .replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&middot;/g, '·').replace(/&mdash;/g, '—')
    .replace(/&hellip;/g, '…').replace(/&#(\d+);/g, (m, d) => String.fromCodePoint(+d));
}

function extractHtml(src) {
  const out = [];
  const lineAt = (pos) => src.slice(0, pos).split('\n').length;
  // Blank out comments / scripts / styles but keep offsets for line numbers.
  const blank = (m) => m.replace(/[^\n]/g, ' ');
  const clean = src.replace(/<!--[\s\S]*?-->/g, blank).replace(/<script[\s\S]*?<\/script>/gi, blank).replace(/<style[\s\S]*?<\/style>/gi, blank);
  // JSON-LD lives in a script tag; it is whitelisted but still extracted so that the whitelist is explicit.
  for (const m of src.matchAll(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/g)) {
    for (const s of m[1].matchAll(/"([^"]*)"/g)) if (VI.test(s[1])) out.push({ text: s[1], line: lineAt(m.index + m[0].indexOf(s[0])), kind: 'html' });
  }
  // Tags + text
  const re = /<\/?([a-zA-Z][^\s>/]*)((?:[^>"']|"[^"]*"|'[^']*')*)>|([^<]+)/g;
  let m;
  while ((m = re.exec(clean))) {
    if (m[3] !== undefined) {
      const t = decodeEntities(m[3]).replace(/\s+/g, ' ').trim();
      if (t && VI.test(t)) out.push({ text: t, line: lineAt(m.index), kind: 'html' });
    } else {
      const attrs = m[2];
      for (const a of attrs.matchAll(/([a-zA-Z:-]+)\s*=\s*("([^"]*)"|'([^']*)')/g)) {
        if (!TRANSLATABLE_ATTRS.includes(a[1])) continue;
        const v = decodeEntities(a[3] ?? a[4]);
        if (VI.test(v)) out.push({ text: v.trim(), line: lineAt(m.index), kind: 'html' });
      }
    }
  }
  return out;
}

// ---------------------------------------------------------------------------------------------------------
async function loadModule(name) {
  const code = readFileSync(join(ROOT, 'js', name), 'utf8');
  return import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'));
}
const { EN, EN_PATTERNS } = await loadModule('i18n-en.js');
const { makeTranslator, HAS_VI } = await loadModule('i18n-core.js');
const translate = makeTranslator(EN, EN_PATTERNS);

// Sample values for ${} placeholders in template literals (and {n}/{topic} in coach templates).
const SAMPLES = [
  ['3', ''], ['Tên', ''], ['in 7', '7'], ['không in gì', '7'], ['Mức 2', '3', ''], ['Mức 2', '3', ' · dùng Debugger: Gợi ý 2 miễn phí'], ['Tên', ' · 3 người đang chơi'], ['Beginner', '3'],
  ['3', '3'], ['Tên', 'Tên'], ['3', 'Tên'], ['Tên', '3'], ['12', '5'], ['2:05', '3'], ['3', '2:05'], ['12.5', '3'],
  ['x', '3'], ['3', 'x'], ['5', '2', '7'], ['Tên', '3', '5'], ['3', 'Tên', '5'], ['3', '5', 'Tên'], ['Tên', 'Tên', '3'],
  ['Tên', '3', 'Tên'], ['3', 'Tên', 'Tên'], ['x', 'y', 'z', 'w'], ['Biến', '3'], ['3', 'Biến'], ['Biến', 'Điền chỗ trống'],
  ['Hôm nay', '3'], ['3', 'Hôm nay'], ['Biến', 'Điền chỗ trống', 'đang học'], ['Biến', 'Điền chỗ trống', 'đang học', '3'],
];

// Strings that only ever appear in the MIDDLE or END of a longer concatenated text (they start with punctuation).
// Each maps to a full sample that must be covered, so the fragment is verified through the pattern that handles it.
const FRAGMENTS = new Map([
  [', gửi ${} dòng lỗi sang đối thủ', 'Hủy 3 dòng đang chờ của bạn, gửi 2 dòng lỗi sang đối thủ'],
  ['. Cảnh báo: khối ở vùng đỏ sẽ bị mất', 'Dòng lỗi đang chờ: 3. Cảnh báo: khối ở vùng đỏ sẽ bị mất'],
  [' (đã dùng gợi ý)', '+5 điểm (đã dùng gợi ý)'],
  [' (bước ${})', 'Gợi ý 2 (bước 3)'],
  [': trống', 'Hàng 1, cột 2: trống'],
  [', cột thụt lề', 'Hàng 1, cột 2, cột thụt lề'],
  ['Lỗi máy chủ (', 'Lỗi máy chủ (500)'],
  [', nhiều nhất ở chủ đề ${}', 'Ván này bạn sai 3 câu, nhiều nhất ở chủ đề Biến. Hãy đọc lại phần giải thích của từng câu rồi luyện thêm một lượt ngắn.'],
  ['Hàng ${} · ', 'Hàng 3 · Thiếu dấu hai chấm ở cuối dòng.'],
]);
const FRAG_BY_TRIM = new Map([...FRAGMENTS].map(([k, v]) => [k.trim(), v]));

// Words that legitimately stay Vietnamese inside an English result: Python string literals / program output.
// "Tên" is the sample value used for placeholders.
const ALLOWED_LEFTOVER = /Đậu|Người lớn|lớn|chẵn|Xin chào|Tên/g;

function fillings(text) {
  const t = text.replace(/\{n\}/g, '\u0000').replace(/\{topic\}/g, '\u0000');
  if (!t.includes('\u0000')) return [text];
  const n = t.split('\u0000').length - 1;
  const out = [];
  for (const set of SAMPLES) {
    if (n > 1 && set.length < 2) continue;
    let idx = 0;
    out.push(t.replace(/\u0000/g, () => set[idx++ % set.length]));
  }
  return out;
}

function candidates(text) {
  const frag = FRAG_BY_TRIM.get(text.replace(/ /g, "${}").trim());
  if (frag) return [frag];
  const out = [];
  for (const f of fillings(text)) {
    out.push(f);
    // A text that ends in ":" / "·" / "(" / whitespace is a prefix; something dynamic is appended at runtime.
    if (/[:·(]\s*$/.test(f) || /\s$/.test(f)) for (const s of ['Tên', '3', 'ABCDE']) out.push(f + s);
  }
  return out;
}

function ok(src) {
  const r = translate(src);
  if (r === src) return false;
  return !HAS_VI.test(r.replace(/"[^"]*"/g, '').replace(ALLOWED_LEFTOVER, ''));
}

function covered(text) {
  if (candidates(text).some(ok)) return true;
  if (/\n/.test(text)) {
    const lines = text.split('\n').map((l) => l.trim()).filter(Boolean);
    if (lines.length > 1 && lines.every(covered)) return true;
  }
  return false;
}

const args = process.argv.slice(2);
const files = [
  { name: 'index.html', items: extractHtml(readFileSync(join(ROOT, 'index.html'), 'utf8')) },
  ...readdirSync(JS_DIR).filter((f) => f.endsWith('.js') && f !== 'i18n-en.js').sort().map((f) => ({
    name: f,
    items: lexJs(readFileSync(join(JS_DIR, f), 'utf8')),
  })),
];

let total = 0;
let skipped = 0;
let uncovered = 0;
const lines = [];
for (const f of files) {
  for (const it of f.items) {
    if (!VI.test(it.text)) continue;
    total++;
    if (it.dev) { skipped++; continue; }
    const wl = WHITELIST.find((w) => (!w.file || w.file === f.name) && w.re.test(it.text));
    if (wl) { skipped++; continue; }
    const shown = `${f.name}:${it.line}  ${JSON.stringify(it.text.replace(/\u0000/g, '${}'))}`;
    if (args.includes('--list')) lines.push(shown);
    if (!covered(it.text)) {
      uncovered++;
      if (!args.includes('--list')) lines.push(shown);
    }
  }
}
// ASCII-only Vietnamese UI words have no diacritics to detect, so they are listed here and must be in EN.
for (const w of ASCII_REQUIRED) {
  if (!EN.has(w)) { uncovered++; lines.push(`ASCII_REQUIRED missing from EN: ${JSON.stringify(w)}`); }
}
if (lines.length) console.log(lines.join('\n'));
console.log(`\nVietnamese strings: ${total}  (whitelisted/dev: ${skipped})  dictionary: ${EN.size} exact + ${EN_PATTERNS.length} patterns`);
console.log(uncovered ? `UNCOVERED: ${uncovered}` : 'All covered.');
process.exit(uncovered ? 1 : 0);
