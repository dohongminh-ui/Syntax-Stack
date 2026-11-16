// Code Rescue board + tray + items: rendering, input (pointer drag, tap-to-place, keyboard) and the motion table.
import { SIZE, canPlace, fitsAnywhere } from './game.js';
import { TOPIC_NAMES, TOPIC_GLYPH } from './pieces.js';
import { el, wait, anim, EASE, floatText, reducedMotion } from './ui.js';
import { icon } from './icons.js';
import { keycap, setLegend } from './keycap.js';

const ITEM_DEFS = [
  { key: 'bomb', icon: 'bomb', label: 'Bom', tip: 'Xóa vùng 3×3 (trừ ô bug)', active: true },
  { key: 'shuffle', icon: 'shuffle', label: 'Xáo khối', tip: 'Đổi 3 khối trong khay', active: true },
  { key: 'undo', icon: 'undo', label: 'Hoàn tác', tip: 'Dùng khi hàng bị khóa', active: false },
  { key: 'debugger', icon: 'search', label: 'Debugger', tip: 'Câu đố tiếp theo: Gợi ý 2 miễn phí', active: false },
];
const rand = (a, b) => a + Math.random() * (b - a);

export class Board {
  constructor({ boardEl, trayEl, itemsEl, handlers }) {
    this.boardEl = boardEl;
    this.trayEl = trayEl;
    this.itemsEl = itemsEl;
    this.h = handlers; // {onPlace, onBomb, onBugTap, onSelect, onItem, getState, getUi}
    this.cells = [];
    this.keys = [];
    this.kb = { r: 3, c: 3 };
    this.drag = null;
    this.ghost = null;
    this.hover = null;
    this.fx = [];
    this.lockKey = '';
    this.lockEls = [];
    this.lastPlaced = null;
    this.build();
  }

  build() {
    const b = this.boardEl;
    b.textContent = '';
    for (let r = 0; r < SIZE; r++)
      for (let c = 0; c < SIZE; c++) {
        const key = keycap({ topic: 'neutral', legend: '' });
        const d = el('div', { class: 'cell empty', role: 'gridcell', dataset: { r, c } }, key);
        d.style.gridRow = String(r + 1);
        d.style.gridColumn = String(c + 1);
        this.cells.push(d);
        this.keys.push(key);
        b.append(d);
      }
    b.addEventListener('click', (e) => {
      const cell = e.target.closest('.cell');
      if (cell) this.activate(+cell.dataset.r, +cell.dataset.c);
    });
    b.addEventListener('pointermove', (e) => {
      if (e.pointerType !== 'mouse' || this.drag) return;
      const cell = e.target.closest('.cell');
      if (cell) this.setHover(+cell.dataset.r, +cell.dataset.c);
    });
    b.addEventListener('pointerleave', () => {
      if (!this.drag) this.clearPreview();
    });
    b.addEventListener('focus', () => {
      b.classList.add('kbd');
      this.paintKb();
      this.setHover(this.kb.r, this.kb.c);
    });
    b.addEventListener('blur', () => {
      b.classList.remove('kbd');
      this.paintKb();
      this.clearPreview();
    });
    b.addEventListener('keydown', (e) => this.onKey(e));
  }

  cell(r, c) {
    return this.cells[r * SIZE + c];
  }

  cancelFx() {
    for (const a of this.fx) a.cancel();
    this.fx = [];
  }

  // ---- rendering -----------------------------------------------------------------------------
  render(s, ui = {}) {
    this.cancelFx();
    const locked = new Set((s.lock ? s.lock.cells : []).map(([r, c]) => r * SIZE + c));
    for (let r = 0; r < SIZE; r++)
      for (let c = 0; c < SIZE; c++) {
        const k = r * SIZE + c;
        const g = s.grid[r][c];
        const cls = ['cell'];
        const key = this.keys[k];
        key.style.opacity = '';
        if (!g) {
          cls.push('empty');
        } else {
          key.className = 'key t-' + (g.bug ? 'bug' : g.topic);
          setLegend(key, g.bug ? 'ERR' : TOPIC_GLYPH[g.topic]);
          if (g.bug && s.phase === 'play') cls.push('tappable');
        }
        if (locked.has(k)) cls.push('locked');
        this.cells[k].className = cls.join(' ');
        this.cells[k].setAttribute('aria-label', this.label(g, r, c));
      }
    this.boardEl.dataset.mode = ui.bomb ? 'bomb' : '';
    this.syncLock(s);
    this.renderTray(s, ui);
    this.renderItems(s, ui);
    this.paintKb();
    if (ui.dropped && ui.dropped.length) {
      this.lastPlaced = ui.dropped;
      this.animatePlace(ui.dropped);
    }
  }

  label(g, r, c) {
    const pos = `Hàng ${r + 1}, cột ${c + 1}`;
    if (!g) return pos + ': trống';
    return pos + ': ' + (g.bug ? 'bug' : TOPIC_NAMES[g.topic]);
  }

  renderTray(s, ui) {
    const t = this.trayEl;
    while (t.children.length < 3) t.append(el('div', { class: 'slot' }));
    s.tray.forEach((p, i) => {
      const slot = t.children[i];
      const pid = p ? p.id : '';
      if (slot.dataset.pid !== pid) {
        slot.textContent = '';
        slot.dataset.pid = pid;
        if (p) {
          const piece = this.pieceEl(p, i);
          slot.append(piece);
          anim(piece, [{ transform: 'translateY(8px)', opacity: 0 }, { transform: 'none', opacity: 1 }], { duration: 220, delay: [0, 40, 90][i], easing: EASE.out, fill: 'backwards' });
        }
      }
      const btn = slot.firstElementChild;
      if (btn) {
        btn.classList.toggle('selected', ui.selected === i);
        btn.classList.toggle('nofit', !fitsAnywhere(s.grid, p));
        btn.setAttribute('aria-pressed', ui.selected === i ? 'true' : 'false');
        btn.disabled = s.phase !== 'play';
      }
      slot.classList.toggle('empty', !p);
    });
  }

  pieceEl(p, i) {
    const btn = el('button', {
      class: 'piece',
      type: 'button',
      'aria-label': `Khối ${i + 1}, ${TOPIC_NAMES[p.topic]}, ${p.cells.length} ô`,
      style: { '--w': p.w, '--h': p.h, '--m': Math.max(p.w, p.h) },
    });
    for (const [r, c] of p.cells) {
      const k = keycap({ topic: p.topic, legend: TOPIC_GLYPH[p.topic] });
      k.style.gridRow = String(r + 1);
      k.style.gridColumn = String(c + 1);
      btn.append(k);
    }
    btn.addEventListener('pointerdown', (e) => this.onDown(e, i, btn));
    btn.addEventListener('click', (e) => {
      if (e.detail === 0) this.h.onSelect(i, true); // keyboard activation
    });
    return btn;
  }

  renderItems(s, ui) {
    const it = this.itemsEl;
    it.textContent = '';
    for (const d of ITEM_DEFS) {
      const n = s.items[d.key];
      const usable = d.active && n > 0 && s.phase === 'play';
      const k = keycap({
        tag: d.active ? 'button' : 'span',
        topic: 'neutral',
        legend: icon(d.icon, { size: 22 }),
        legendClass: 'legend legend-c',
        cls: 'item' + (ui.bomb && d.key === 'bomb' ? ' on' : '') + (n > 0 ? '' : ' is-off'),
      });
      if (d.active) {
        k.type = 'button';
        k.disabled = !usable;
        k.addEventListener('click', () => this.h.onItem(d.key));
        if (d.key === 'bomb') k.setAttribute('aria-pressed', ui.bomb ? 'true' : 'false');
      }
      k.title = d.tip;
      k.setAttribute('aria-label', `${d.label}: ${n}. ${d.tip}`);
      k.append(el('span', { class: 'item-n', text: '×' + n, 'aria-hidden': 'true' }));
      it.append(el('div', { class: 'item-cell' }, k, el('span', { class: 'item-name', text: d.label })));
    }
  }

  // ---- lock frame, sweep and breathing glow ---------------------------------------------------
  syncLock(s) {
    const L = s.lock && (s.phase === 'locked' || s.phase === 'puzzle') ? s.lock : null;
    const sig = L ? JSON.stringify([L.rows, L.cols, L.topic]) : '';
    if (sig === this.lockKey) return;
    this.lockKey = sig;
    for (const n of this.lockEls) n.remove();
    this.lockEls = [];
    if (!L) return;
    const mk = (cls, row, col, vert) => {
      const n = el('i', { class: cls + ' t-' + L.topic + (vert ? ' vert' : ''), 'aria-hidden': 'true' });
      n.style.gridRow = row;
      n.style.gridColumn = col;
      this.boardEl.append(n);
      this.lockEls.push(n);
      return n;
    };
    const sweeps = [];
    for (const r of L.rows) {
      mk('lock-frame breathe', `${r + 1}`, '1 / -1');
      sweeps.push([mk('lock-sweep', `${r + 1}`, '1 / -1'), 'inset(0 100% 0 0)', 'inset(0 0 0 0)']);
    }
    for (const c of L.cols) {
      mk('lock-frame breathe', '1 / -1', `${c + 1}`);
      sweeps.push([mk('lock-sweep', '1 / -1', `${c + 1}`, true), 'inset(0 0 100% 0)', 'inset(0 0 0 0)']);
    }
    for (const [n, from, to] of sweeps) {
      const a = anim(n, [{ clipPath: from, opacity: 1 }, { clipPath: to, opacity: 1, offset: 0.85 }, { clipPath: to, opacity: 0 }], { duration: 380, easing: EASE.inOut, fill: 'backwards' });
      a.finished.then(() => {
        n.remove();
        this.lockEls = this.lockEls.filter((x) => x !== n);
      });
    }
  }

  // ---- previews ------------------------------------------------------------------------------
  clearPreview() {
    for (const c of this.cells) c.classList.remove('pv-ok', 'pv-bomb');
    this.hover = null;
  }

  showPreview(piece, r0, c0) {
    for (const c of this.cells) c.classList.remove('pv-ok', 'pv-bomb');
    const ok = canPlace(this.h.getState().grid, piece, r0, c0);
    if (!ok) return false; // invalid: no ghost (the dragged piece tints red instead)
    for (const [dr, dc] of piece.cells) {
      const r = r0 + dr;
      const c = c0 + dc;
      if (r < 0 || r >= SIZE || c < 0 || c >= SIZE) continue;
      const cell = this.cell(r, c);
      cell.classList.add('pv-ok');
      cell.style.setProperty('--pv', `var(--cap-${piece.topic})`);
    }
    return true;
  }

  setHover(r, c) {
    const s = this.h.getState();
    const ui = this.h.getUi();
    if (s.phase !== 'play') return;
    if (ui.bomb) {
      this.clearPreview();
      for (let dr = -1; dr <= 1; dr++)
        for (let dc = -1; dc <= 1; dc++) {
          const rr = r + dr;
          const cc = c + dc;
          if (rr >= 0 && rr < SIZE && cc >= 0 && cc < SIZE) this.cell(rr, cc).classList.add('pv-bomb');
        }
      return;
    }
    const p = ui.selected != null ? s.tray[ui.selected] : null;
    if (!p) return this.clearPreview();
    this.hover = [r, c];
    this.showPreview(p, r - Math.floor(p.h / 2), c - Math.floor(p.w / 2));
  }

  // ---- tap / keyboard ------------------------------------------------------------------------
  activate(r, c) {
    const s = this.h.getState();
    const ui = this.h.getUi();
    if (s.phase !== 'play') return;
    if (ui.bomb) return this.h.onBomb(r, c);
    const g = s.grid[r][c];
    if (g && g.bug) return this.h.onBugTap(g.bugId);
    const p = ui.selected != null ? s.tray[ui.selected] : null;
    if (!p) return this.h.onHint('Chọn một khối ở khay trước, rồi chạm vào ô trên lưới.');
    const r0 = r - Math.floor(p.h / 2);
    const c0 = c - Math.floor(p.w / 2);
    if (!canPlace(s.grid, p, r0, c0)) {
      this.shake();
      return this.h.onHint('Không đặt được khối ở vị trí này.');
    }
    this.clearPreview();
    this.h.onPlace(ui.selected, r0, c0);
  }

  onKey(e) {
    const d = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] }[e.key];
    if (d) {
      e.preventDefault();
      this.kb.r = Math.min(SIZE - 1, Math.max(0, this.kb.r + d[0]));
      this.kb.c = Math.min(SIZE - 1, Math.max(0, this.kb.c + d[1]));
      this.paintKb();
      this.setHover(this.kb.r, this.kb.c);
    } else if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      this.activate(this.kb.r, this.kb.c);
    } else if (['1', '2', '3'].includes(e.key)) {
      this.h.onSelect(+e.key - 1, false);
    }
  }

  paintKb() {
    for (const c of this.cells) c.classList.remove('kb');
    if (this.boardEl.classList.contains('kbd')) this.cell(this.kb.r, this.kb.c).classList.add('kb');
  }

  shake() {
    anim(this.boardEl, [{ transform: 'translateX(0)' }, { transform: 'translateX(-5px)' }, { transform: 'translateX(5px)' }, { transform: 'translateX(-4px)' }, { transform: 'translateX(4px)' }, { transform: 'translateX(0)' }], { duration: 260, easing: EASE.out });
  }

  // ---- drag ----------------------------------------------------------------------------------
  onDown(e, idx, btn) {
    if (e.button > 0 || this.h.getState().phase !== 'play') return;
    // A mouse press must not start a text selection: the browser would turn it into a native
    // drag-and-drop, steal the pointer, and leave this drag half-finished.
    if (e.pointerType === 'mouse') e.preventDefault();
    window.getSelection()?.removeAllRanges();
    if (this.drag) this.onUp(e, true); // a previous drag never finished: clean it up first
    this.drag = { idx, btn, x0: e.clientX, y0: e.clientY, started: false, id: e.pointerId, touch: e.pointerType !== 'mouse' };
    try { btn.setPointerCapture(e.pointerId); } catch { /* pointer already released */ }
    document.documentElement.classList.add('is-dragging');
    const move = (ev) => this.onMove(ev);
    let done = false;
    const end = (cancelled) => (ev) => {
      if (done) return;
      done = true;
      btn.removeEventListener('pointermove', move);
      btn.removeEventListener('pointerup', up);
      btn.removeEventListener('pointercancel', cancel);
      btn.removeEventListener('lostpointercapture', cancel);
      this.onUp(ev, cancelled);
    };
    const up = end(false);
    const cancel = end(true);
    btn.addEventListener('pointermove', move);
    btn.addEventListener('pointerup', up);
    btn.addEventListener('pointercancel', cancel);
    btn.addEventListener('lostpointercapture', cancel);
  }

  metrics() {
    const a = this.cells[0].getBoundingClientRect();
    const b = this.cells[1].getBoundingClientRect();
    const c = this.cells[SIZE].getBoundingClientRect();
    return { left: a.left, top: a.top, size: a.width, sx: b.left - a.left, sy: c.top - a.top };
  }

  onMove(e) {
    const d = this.drag;
    if (!d) return;
    if (!d.started) {
      if (Math.hypot(e.clientX - d.x0, e.clientY - d.y0) < 6) return;
      d.started = true;
      this.startGhost();
    }
    const m = this.m;
    const p = this.h.getState().tray[d.idx];
    const lift = d.touch ? 64 : 0;
    const gap = m.sx - m.size;
    const gw = p.w * m.size + (p.w - 1) * gap;
    const gh = p.h * m.size + (p.h - 1) * gap;
    const left = e.clientX - gw / 2;
    const top = e.clientY - gh / 2 - lift;
    this.ghost.style.transform = `translate(${left}px, ${top}px) scale(1.04)`;
    const c0 = Math.round((left - m.left) / m.sx);
    const r0 = Math.round((top - m.top) / m.sy);
    d.target = [r0, c0];
    d.ok = this.showPreview(p, r0, c0);
    this.ghost.classList.toggle('bad', !d.ok);
  }

  startGhost() {
    const d = this.drag;
    const p = this.h.getState().tray[d.idx];
    this.m = this.metrics();
    const gap = this.m.sx - this.m.size;
    const g = el('div', { class: 'ghost', 'aria-hidden': 'true' });
    g.style.setProperty('--u', this.m.size + 'px');
    g.style.gap = gap + 'px';
    g.style.gridTemplateColumns = `repeat(${p.w}, ${this.m.size}px)`;
    g.style.gridTemplateRows = `repeat(${p.h}, ${this.m.size}px)`;
    for (const [r, c] of p.cells) {
      const k = keycap({ topic: p.topic, legend: TOPIC_GLYPH[p.topic] });
      k.style.gridRow = String(r + 1);
      k.style.gridColumn = String(c + 1);
      g.append(k);
    }
    document.body.append(g);
    this.ghost = g;
    d.btn.classList.add('dragging');
    this.h.onSelect(d.idx, false, true);
  }

  onUp(e, cancelled) {
    const d = this.drag;
    this.drag = null;
    document.documentElement.classList.remove('is-dragging');
    if (!d) return;
    d.btn.classList.remove('dragging');
    if (d.started) {
      this.ghost?.remove();
      this.ghost = null;
      this.clearPreview();
      if (!cancelled && d.ok) this.h.onPlace(d.idx, d.target[0], d.target[1]);
      else if (!cancelled) this.shake();
    } else if (!cancelled) {
      this.h.onSelect(d.idx, false);
    }
  }

  // ---- animations (WAAPI one-offs) -------------------------------------------------------------
  keyOf(r, c) {
    return this.keys[r * SIZE + c];
  }

  /** Caps drop in 120ms then "thock" (2px press and release), 12ms stagger across the cells. */
  animatePlace(cells) {
    cells.forEach(([r, c], i) => {
      const key = this.keyOf(r, c);
      const delay = i * 12;
      anim(key, [{ transform: 'translateY(-6px) scale(1.03)', opacity: 0.5 }, { transform: 'none', opacity: 1 }], { duration: 120, delay, easing: EASE.out, fill: 'backwards' });
      const top = key.firstElementChild;
      anim(top, [{ transform: 'translateY(0)' }, { transform: 'translateY(2px)', offset: 0.4 }, { transform: 'translateY(0)' }], { duration: 90, delay: delay + 100, easing: EASE.out });
    });
  }

  /** Correct: caps pop up and away, staggered from the end nearest the last placed piece. */
  async animateClear(cells, { points = 0, color } = {}) {
    if (!cells.length) return;
    const from = this.lastPlaced && this.lastPlaced.length
      ? [this.lastPlaced.reduce((a, [r]) => a + r, 0) / this.lastPlaced.length, this.lastPlaced.reduce((a, [, c]) => a + c, 0) / this.lastPlaced.length]
      : [(SIZE - 1) / 2, (SIZE - 1) / 2];
    const ordered = cells.slice().sort((a, b) => Math.hypot(a[0] - from[0], a[1] - from[1]) - Math.hypot(b[0] - from[0], b[1] - from[1]));
    const step = Math.min(22, 560 / ordered.length);
    const done = ordered.map(([r, c], i) => {
      const a = anim(this.keyOf(r, c), [
        { transform: 'translateY(0) rotate(0deg) scale(1)', opacity: 1 },
        { transform: `translateY(-16px) rotate(${(Math.random() < 0.5 ? -1 : 1) * rand(4, 8)}deg) scale(.92)`, opacity: 0 },
      ], { duration: 260, delay: i * step, easing: EASE.out, fill: 'forwards' });
      this.fx.push(a);
      return a.finished;
    });
    if (points) {
      const rs = cells.map(([r]) => r);
      const cs = cells.map(([, c]) => c);
      const r0 = this.cell(Math.min(...rs), Math.min(...cs)).getBoundingClientRect();
      const r1 = this.cell(Math.max(...rs), Math.max(...cs)).getBoundingClientRect();
      floatText('+' + points, (r0.left + r1.right) / 2, (r0.top + r1.bottom) / 2, color || 'var(--matcha)');
    }
    await Promise.all(done);
    if (reducedMotion()) await wait(150);
  }

  /** Wrong: caps shake (3 cycles, 6px, 300ms), then crossfade to Error caps with a 2px blur masking the swap. */
  async animateBug(cells) {
    const keys = cells.map(([r, c]) => this.keyOf(r, c));
    const sh = keys.map((k) => anim(k, [0, -6, 6, -6, 6, -6, 6, 0].map((x) => ({ transform: `translateX(${x}px)` })), { duration: 300, easing: 'linear' }));
    await Promise.all(sh.map((a) => a.finished));
    const out = keys.map((k) => anim(k, [{ filter: 'blur(0)', opacity: 1 }, { filter: 'blur(2px)', opacity: 0.55 }], { duration: 100, easing: EASE.out, fill: 'forwards' }));
    await Promise.all(out.map((a) => a.finished));
    for (const [r, c] of cells) {
      const key = this.keyOf(r, c);
      key.className = 'key t-bug';
      setLegend(key, 'ERR');
      this.cell(r, c).classList.remove('locked');
    }
    for (const l of this.lockEls) l.remove();
    this.lockEls = [];
    this.lockKey = '';
    const back = keys.map((k) => anim(k, [{ filter: 'blur(2px)', opacity: 0.55 }, { filter: 'blur(0)', opacity: 1 }], { duration: 100, easing: EASE.out }));
    out.forEach((a) => a.cancel());
    await Promise.all(back.map((a) => a.finished));
  }

  /** Debug fixed: each Error cap cracks into two halves that drift apart and fade (320ms). */
  async animateCrack(cells) {
    const jobs = [];
    for (const [r, c] of cells) {
      const key = this.keyOf(r, c);
      const cell = this.cell(r, c);
      const halves = [
        ['polygon(0 0, 100% 0, 0 100%)', [-10, -6]],
        ['polygon(100% 0, 100% 100%, 0 100%)', [10, 6]],
      ].map(([clip, [dx, dy]]) => {
        const h = key.cloneNode(true);
        h.classList.add('half');
        h.style.cssText = `position:absolute;inset:0;clip-path:${clip};pointer-events:none;z-index:2`;
        cell.append(h);
        const a = anim(h, [{ transform: 'translate(0,0) rotate(0)', opacity: 1 }, { transform: `translate(${dx}px,${dy}px) rotate(${dx > 0 ? 4 : -4}deg)`, opacity: 0 }], { duration: 320, easing: EASE.out, fill: 'forwards' });
        a.finished.then(() => h.remove());
        return a.finished;
      });
      key.style.opacity = '0';
      jobs.push(...halves);
    }
    await Promise.all(jobs);
    if (reducedMotion()) await wait(100);
  }

  /** Crash: the board flickers once, then caps fall row by row from the bottom (gravity: ease-in). */
  async animateCrash() {
    await anim(this.boardEl, [{ opacity: 1 }, { opacity: 0.4 }, { opacity: 1 }], { duration: 120 }).finished;
    if (reducedMotion()) return wait(300);
    const root = document.documentElement;
    root.style.overflow = 'hidden';
    for (let r = 0; r < SIZE; r++)
      for (let c = 0; c < SIZE; c++) {
        if (this.cells[r * SIZE + c].classList.contains('empty')) continue;
        this.fx.push(anim(this.keyOf(r, c), [
          { transform: 'translateY(0) rotate(0deg)' },
          { transform: `translateY(110vh) rotate(${rand(-25, 25)}deg)` },
        ], { duration: 700, delay: (SIZE - 1 - r) * 30 + rand(0, 18), easing: 'cubic-bezier(.5, 0, .75, 0)', fill: 'forwards' }));
      }
    await wait(700 + (SIZE - 1) * 30 + 60);
    root.style.overflow = '';
  }
}
