// Player identity for ranked runs and races: no account, just a random device id and a nickname kept in this browser.
// The server stores only a hash of the device id. The nickname is never typed: it always comes from GET /api/nickname
// (random, friendly names), shown on a name card the player can re-roll.
import { el, anim, EASE } from './ui.js';
import { icon } from './icons.js';
import { keycap } from './keycap.js';
import * as api from './api.js';

const DEVICE_KEY = 'syntaxstack.device';
const NICK_KEY = 'syntaxstack.nickname';
let memoryDevice = null; // used when localStorage is blocked, so one tab still has a stable id

function randomHex32() {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return [...bytes].map((b) => b.toString(16).padStart(2, '0')).join('');
}

export function getDeviceId() {
  try {
    const v = localStorage.getItem(DEVICE_KEY);
    if (v && /^[0-9a-f]{32}$/.test(v)) return v;
    const id = randomHex32();
    localStorage.setItem(DEVICE_KEY, id);
    return id;
  } catch {
    return (memoryDevice ||= randomHex32());
  }
}

export function getNickname() {
  try {
    const v = (localStorage.getItem(NICK_KEY) || '').trim();
    return checkNickname(v) ? v : '';
  } catch {
    return '';
  }
}

export function clearNickname() {
  try {
    localStorage.removeItem(NICK_KEY);
  } catch {
    /* ignore */
  }
}

export function setNickname(name) {
  try {
    localStorage.setItem(NICK_KEY, name);
  } catch {
    /* storage blocked: the name lives for this page only via the caller */
  }
}

/** Returns the cleaned nickname, or '' when it is not allowed. */
export function checkNickname(raw) {
  const v = String(raw ?? '').trim();
  if (!v || [...v].length > 20) return '';
  if (/[\p{Cc}\p{Cf}]/u.test(v)) return '';
  return v;
}

/** Error text for a failed GET /api/nickname. */
function nameError(e) {
  return e?.status === 429 ? 'Bạn đổi tên hơi nhanh. Đợi một lát rồi thử lại.' : 'Chưa lấy được tên. Kiểm tra kết nối rồi thử lại.';
}

/**
 * The name card: a generated name on a wide keycap, "Đổi tên khác" re-rolls it, "Dùng tên này" saves it.
 * Resolves with the saved nickname, or null when dismissed.
 * opts: { title, text, confirmLabel }
 */
export function askNickname({ title = 'Tên của bạn', text = 'Tên được tạo ngẫu nhiên để bảng xếp hạng luôn thân thiện.', confirmLabel = 'Dùng tên này' } = {}) {
  const root = document.getElementById('dialog-root');
  const app = document.getElementById('app');
  return new Promise((resolve) => {
    const uid = Math.random().toString(36).slice(2, 7);
    const titleId = 'nick-title-' + uid;
    let name = getNickname();
    let busy = false;
    const nameKey = keycap({ topic: 'variables', legend: name || '…', legendClass: 'kb-label name-legend', cls: 'name-key' });
    const live = el('div', { class: 'name-live', role: 'status', 'aria-live': 'polite' }, nameKey);
    const err = el('p', { class: 'rs-error', role: 'alert', hidden: true });
    const save = keycap({ tag: 'button', topic: 'neutral', legend: confirmLabel, legendClass: 'kb-label', variant: 'btn', enter: true });
    save.type = 'button';
    save.disabled = !name;
    const dice = el('button', { class: 'btn name-reroll', type: 'button' }, el('span', { class: 'name-dice', 'aria-hidden': 'true', text: '🎲' }), el('span', { text: 'Đổi tên khác' }));
    const later = el('button', { class: 'btn', type: 'button', text: 'Để sau' });
    const legendEl = nameKey.querySelector('.name-legend');
    const face = nameKey.querySelector('.cap-top');

    async function roll() {
      if (busy) return;
      busy = true;
      dice.disabled = true;
      save.disabled = true;
      err.hidden = true;
      anim(face, [{ transform: 'translateY(0)' }, { transform: 'translateY(3px)' }, { transform: 'translateY(0)' }], { duration: 200, easing: EASE.out });
      try {
        const r = await api.fetchNickname();
        name = checkNickname(r?.nickname);
        if (!name) throw new Error('bad');
        legendEl.textContent = name;
        nameKey.classList.remove('is-empty');
        anim(legendEl, [{ opacity: 0, transform: 'translateY(6px)' }, { opacity: 1, transform: 'none' }], { duration: 220, easing: EASE.out });
        save.disabled = false;
      } catch (e) {
        err.replaceChildren(icon('alert', { size: 16 }), el('span', { text: nameError(e) }));
        err.hidden = false;
        save.disabled = !name;
      } finally {
        busy = false;
        dice.disabled = false;
      }
    }

    const card = el('div', { class: 'dialog-card', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': titleId, tabindex: '-1' },
      el('div', { class: 'dlg-bar' }, icon('terminal', { size: 16 }), el('span', { class: 'dlg-file', text: 'name.py' })),
      el('div', { class: 'dlg-body' }, el('h2', { id: titleId, text: title }), el('p', { text }),
        el('div', { class: 'dlg-form' }, live, err,
          el('div', { class: 'dialog-actions name-actions' }, dice, later, save))));
    const wrap = el('div', { class: 'dialog-backdrop' }, card);

    function close(v) {
      anim(wrap, [{ opacity: 1 }, { opacity: 0 }], { duration: 120, easing: EASE.out }).finished.then(() => {
        wrap.remove();
        app.inert = false;
        resolve(v);
      });
    }
    save.addEventListener('click', () => {
      if (busy || !name) return;
      setNickname(name);
      close(name);
    });
    dice.addEventListener('click', roll);
    later.addEventListener('click', () => close(null));
    wrap.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        close(null);
      }
    });
    root.append(wrap);
    app.inert = true;
    anim(card, [{ transform: 'translateY(8px) scale(.97)', opacity: 0 }, { transform: 'none', opacity: 1 }], { duration: 200, easing: EASE.out });
    if (name) save.focus();
    else {
      nameKey.classList.add('is-empty');
      roll().then(() => (name ? save : dice).focus());
    }
  });
}

/** The saved nickname, showing the name card once if there is none yet. Resolves '' when the player dismisses it. */
export async function ensureNickname(opts) {
  const have = getNickname();
  if (have) return have;
  return (await askNickname(opts)) || '';
}

/** The server refused the stored name (old free-text one): forget it and show the card again. '' when dismissed. */
export async function renewNickname(opts) {
  clearNickname();
  return (await askNickname(opts)) || '';
}
