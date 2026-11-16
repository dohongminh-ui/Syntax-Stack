// Small DOM helpers: element builder, WAAPI helper, toast, confirm dialog, wait.
import { icon } from './icons.js';
import { keycap } from './keycap.js';

export const reducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

export function wait(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

export const EASE = {
  out: 'cubic-bezier(0.23, 1, 0.32, 1)',
  inOut: 'cubic-bezier(0.77, 0, 0.175, 1)',
  drawer: 'cubic-bezier(0.32, 0.72, 0, 1)',
};

const NOOP = { finished: Promise.resolve(), cancel() {}, finish() {} };

/**
 * One-off WAAPI sequence. Under prefers-reduced-motion every transform keyframe is dropped and
 * only opacity / filter changes survive, capped at 150ms. Returns the Animation (or a no-op).
 */
export function anim(node, frames, opts = {}) {
  if (!node) return NOOP;
  if (reducedMotion()) {
    const keep = frames.map((f) => {
      const o = {};
      for (const k of Object.keys(f)) if (k === 'opacity' || k === 'filter' || k === 'offset') o[k] = f[k];
      return o;
    });
    if (!keep.some((f) => 'opacity' in f || 'filter' in f)) return NOOP;
    const a = node.animate(keep, { ...opts, duration: Math.min(opts.duration || 150, 150), delay: 0, iterations: opts.iterations === Infinity ? 1 : opts.iterations });
    a.finished.catch(() => {});
    return a;
  }
  const a = node.animate(frames, opts);
  a.finished.catch(() => {});
  return a;
}

export function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === false || v === null || v === undefined) continue;
    if (k === 'class') node.className = v;
    else if (k === 'text') node.textContent = v;
    else if (k.startsWith('on') && typeof v === 'function') node.addEventListener(k.slice(2), v);
    else if (k === 'style' && typeof v === 'object') {
      for (const [sk, sv] of Object.entries(v)) {
        if (sk.startsWith('--')) node.style.setProperty(sk, sv);
        else node.style[sk] = sv;
      }
    } else if (k === 'dataset') Object.assign(node.dataset, v);
    else node.setAttribute(k, v === true ? '' : v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return node;
}

/** Rolls a tabular-digit number from its current value to `to`. */
export function rollNumber(node, to, ms = 400) {
  const from = Number(node.dataset.v ?? node.textContent) || 0;
  node.dataset.v = String(to);
  if (node._roll) cancelAnimationFrame(node._roll);
  if (from === to || reducedMotion()) {
    node.textContent = to;
    return;
  }
  const t0 = performance.now();
  const tick = (t) => {
    const p = Math.min(1, (t - t0) / ms);
    const e = 1 - Math.pow(1 - p, 3);
    node.textContent = Math.round(from + (to - from) * e);
    if (p < 1) node._roll = requestAnimationFrame(tick);
  };
  node._roll = requestAnimationFrame(tick);
}

/** Floating "+375" that rises 24px from a point and fades (700ms). */
export function floatText(text, x, y, color = 'var(--matcha)') {
  const n = el('div', { class: 'float-pts', text, 'aria-hidden': 'true', style: { left: x + 'px', top: y + 'px', color } });
  document.body.append(n);
  const a = anim(n, [
    { transform: 'translate(-50%, 0)', opacity: 0 },
    { transform: 'translate(-50%, -8px)', opacity: 1, offset: 0.2 },
    { transform: 'translate(-50%, -24px)', opacity: 1, offset: 0.65 },
    { transform: 'translate(-50%, -24px)', opacity: 0 },
  ], { duration: 700, easing: EASE.out, fill: 'forwards' });
  a.finished.then(() => n.remove());
}

export function toast(text, ms = 2600) {
  const root = document.getElementById('toast-root');
  if (!root) return;
  const t = el('div', { class: 'toast' }, icon('terminal', { size: 16 }), el('span', { text }));
  root.append(t);
  anim(t, [{ transform: 'translateY(8px)', opacity: 0 }, { transform: 'translateY(0)', opacity: 1 }], { duration: 200, easing: EASE.out });
  setTimeout(() => {
    anim(t, [{ opacity: 1 }, { opacity: 0 }], { duration: 140, easing: EASE.out, fill: 'forwards' }).finished.then(() => t.remove());
  }, ms);
}

// buttons: [{label, value, variant}] -> resolves with the clicked value.
export function confirmDialog({ title, text, buttons }) {
  const root = document.getElementById('dialog-root');
  const app = document.getElementById('app');
  return new Promise((resolve) => {
    const titleId = 'dlg-title-' + Math.random().toString(36).slice(2, 7);
    const actions = el('div', { class: 'dialog-actions' });
    for (const b of buttons) {
      if (b.variant === 'ghost') {
        actions.append(el('button', { class: 'btn', type: 'button', text: b.label, onclick: () => close(b.value) }));
      } else {
        const k = keycap({ tag: 'button', legend: b.label, legendClass: 'kb-label', variant: 'btn', topic: b.variant === 'danger' ? 'bug' : 'neutral', enter: true });
        k.type = 'button';
        k.addEventListener('click', () => close(b.value));
        actions.append(k);
      }
    }
    const card = el('div', { class: 'dialog-card', role: 'alertdialog', 'aria-modal': 'true', 'aria-labelledby': titleId, tabindex: '-1' },
      el('div', { class: 'dlg-bar' }, icon('terminal', { size: 16 }), el('span', { class: 'dlg-file', text: 'confirm.py' })),
      el('div', { class: 'dlg-body' },
        el('h2', { id: titleId, text: title }),
        text ? el('p', { text }) : null,
        actions));
    const wrap = el('div', { class: 'dialog-backdrop' }, card);
    function close(v) {
      anim(wrap, [{ opacity: 1 }, { opacity: 0 }], { duration: 120, easing: EASE.out }).finished.then(() => {
        wrap.remove();
        app.inert = false;
        resolve(v);
      });
    }
    root.append(wrap);
    app.inert = true;
    anim(card, [{ transform: 'translateY(8px) scale(.97)', opacity: 0 }, { transform: 'none', opacity: 1 }], { duration: 200, easing: EASE.out });
    (card.querySelector('.key') || card.querySelector('button')).focus();
  });
}
