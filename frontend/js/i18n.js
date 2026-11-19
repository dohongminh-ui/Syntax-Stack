// Language switch (Vietnamese default, English on request).
//
// Vietnamese is the language the app is written in, so Vietnamese needs no work at all: this module does nothing
// but set <html lang> and wire the VI | EN toggle. In English mode it translates the page in place:
//   - text nodes (matched on their trimmed text; surrounding whitespace is kept)
//   - attributes aria-label, placeholder, title, alt, and value on button-like inputs
//   - document.title and the meta description
// A MutationObserver translates anything inserted or changed later, so none of the ~900 call sites that build
// Vietnamese strings had to change. The dictionary lives in i18n-en.js, the lookup logic in i18n-core.js.
//
// Cost control: results are memoised per string (i18n-core), text without letters is skipped, patterns only run for
// text that contains Vietnamese letters, and Python code is never touched (see SKIP_CODE below).
//
// Import this module FIRST in the entry module so that the static HTML is already English before the first paint.
import { EN, EN_PATTERNS } from './i18n-en.js';
import { makeTranslator } from './i18n-core.js';

const KEY = 'ss-lang';
const LANGS = ['vi', 'en'];

function readStored() {
  try {
    const v = localStorage.getItem(KEY);
    return LANGS.includes(v) ? v : null;
  } catch {
    return null;
  }
}

function store(l) {
  try {
    localStorage.setItem(KEY, l);
  } catch {
    /* private mode / storage disabled: the choice just lasts for this page load */
  }
}

// ?lang=en / ?lang=vi overrides the stored choice and is saved.
function resolve() {
  let fromUrl = null;
  try {
    fromUrl = new URLSearchParams(location.search).get('lang');
  } catch {
    /* ignore */
  }
  if (LANGS.includes(fromUrl)) {
    store(fromUrl);
    return fromUrl;
  }
  return readStored() || 'vi';
}

const current = resolve();
const isEn = current === 'en';
try {
  document.documentElement.lang = current;
} catch {
  /* ignore */
}

/** Current language: 'vi' or 'en'. */
export const lang = () => current;

/** Save the language and reload (a mid-game switch simply restarts the page). */
export function setLang(l) {
  if (!LANGS.includes(l)) return;
  store(l);
  try {
    const u = new URL(location.href);
    if (u.searchParams.has('lang')) {
      u.searchParams.set('lang', l);
      location.replace(u.toString());
      return;
    }
  } catch {
    /* fall through to a plain reload */
  }
  location.reload();
}

const translate = isEn ? makeTranslator(EN, EN_PATTERNS) : (s) => s;

/** Translate one Vietnamese string for direct use in JS (alert/confirm, canvas text, share text...). */
export const t = (vi) => translate(vi);

// ---------------------------------------------------------------------------------------------------------------
// DOM translation (English only)
// ---------------------------------------------------------------------------------------------------------------
const ATTRS = ['aria-label', 'placeholder', 'title', 'alt', 'value'];
// Python code is never translated. Text inside these is left alone:
//   pre, code, textarea      terminal output, inline code, the "make puzzles" editor
//   .code, .lt               codeBlock() / diff lines (editor.js)
//   .rk                      Syntax Rows piece keycaps (rows-board.js)
//   .opt-text, .opt-code     answer options (puzzle-modal.js)
//   .pl-text                 Parsons line keycaps (puzzle-modal.js)
//   .term-out                program output
const SKIP_CODE = 'pre, code, textarea, .code, .lt, .rk, .opt-text, .opt-code, .pl-text, .term-out, script, style';
const HAS_LETTER = /[A-Za-zÀ-ỹ]/;
const MAX_LEN = 1500;

function inCode(node) {
  const p = node.parentElement;
  return !!p && p.closest(SKIP_CODE) !== null;
}

function translateText(node) {
  const v = node.nodeValue;
  if (!v || v.length > MAX_LEN || !HAS_LETTER.test(v)) return;
  if (inCode(node)) return;
  const out = translate(v);
  if (out !== v) node.nodeValue = out;
}

function valueAttrApplies(el) {
  if (el.tagName === 'BUTTON') return true;
  if (el.tagName !== 'INPUT') return false;
  const type = (el.getAttribute('type') || '').toLowerCase();
  return type === 'button' || type === 'submit' || type === 'reset';
}

function translateAttr(el, name) {
  if (name === 'value' && !valueAttrApplies(el)) return;
  if (el.tagName === 'PRE' || el.tagName === 'CODE') return;
  const v = el.getAttribute(name);
  if (!v || v.length > MAX_LEN || !HAS_LETTER.test(v)) return;
  const out = translate(v);
  if (out !== v) el.setAttribute(name, out);
}

function translateElementAttrs(el) {
  if (!el.hasAttributes()) return;
  for (let i = 0; i < ATTRS.length; i++) if (el.hasAttribute(ATTRS[i])) translateAttr(el, ATTRS[i]);
}

function walk(root) {
  if (root.nodeType === 3) {
    translateText(root);
    return;
  }
  if (root.nodeType !== 1) return;
  translateElementAttrs(root);
  const tw = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
  for (let n = tw.nextNode(); n; n = tw.nextNode()) {
    if (n.nodeType === 3) translateText(n);
    else translateElementAttrs(n);
  }
}

function translateHead() {
  const tt = document.querySelector('head > title');
  if (tt) for (const n of tt.childNodes) if (n.nodeType === 3) translateText(n);
  const sel = 'meta[name="description"], meta[property="og:title"], meta[property="og:description"], meta[name="twitter:title"], meta[name="twitter:description"]';
  for (const m of document.head.querySelectorAll(sel)) {
    const v = m.getAttribute('content');
    if (v) {
      const out = translate(v);
      if (out !== v) m.setAttribute('content', out);
    }
  }
  const loc = document.querySelector('meta[property="og:locale"]');
  if (loc) loc.setAttribute('content', 'en_US');
}

function startTranslating() {
  translateHead();
  walk(document.body);
  const obs = new MutationObserver((records) => {
    for (const r of records) {
      if (r.type === 'childList') {
        for (const n of r.addedNodes) walk(n);
      } else if (r.type === 'characterData') {
        translateText(r.target);
      } else if (r.type === 'attributes') {
        translateAttr(r.target, r.attributeName);
      }
    }
  });
  obs.observe(document.documentElement, {
    childList: true,
    subtree: true,
    characterData: true,
    attributes: true,
    attributeFilter: ATTRS,
  });
}

// ---------------------------------------------------------------------------------------------------------------
// The VI | EN toggle (markup is in index.html: radios named "lang")
// ---------------------------------------------------------------------------------------------------------------
function wireToggle() {
  const radios = document.querySelectorAll('input[name="lang"]');
  radios.forEach((r) => {
    r.checked = r.value === current;
    r.addEventListener('change', () => {
      if (r.checked) setLang(r.value);
    });
  });
}

if (typeof document !== 'undefined' && document.body) {
  wireToggle();
  if (isEn) startTranslating();
}
