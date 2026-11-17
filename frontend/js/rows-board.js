// Syntax Rows board + token tray: rendering, pointer drag (tray <-> board, board <-> board), tap, keyboard, motion.
import * as R from './rows-game.js';
import { el, anim, EASE, wait, reducedMotion } from './ui.js';
import { keycap } from './keycap.js';
import { sfx } from './sound.js';

const rand = (a, b) => a + Math.random() * (b - a);
const capVar = (topic) => (topic === 'syntax' || !topic ? '#e6e0d2' : `var(--cap-${topic})`);

export class RowsBoard {
  /** handlers: { getState, onPlace(id,row,col), onRemove(id), onHint(text) } */
  constructor({ boardEl, trayEl, trayWrapEl, countEl, handlers }) {
    this.boardEl = boardEl;
    this.trayEl = trayEl;
    this.trayWrapEl = trayWrapEl;
    this.countEl = countEl;
    this.h = handlers;
    this.els = {};
    this.sig = {};
    this.socks = [];
    this.gut = [];
    this.hl = [];
    this.fx = [];
    this.selected = null;
    this.kb = { r: 0, c: 0 };
    this.drag = null;
    this.ghost = null;
    this.settling = false;
    this.settled = false;
    boardEl.addEventListener('click', (e) => this.onSockClick(e));
    boardEl.addEventListener('focus', () => { boardEl.classList.add('kbd'); this.paintKb(); });
    boardEl.addEventListener('blur', () => { boardEl.classList.remove('kbd'); this.paintKb(); });
    boardEl.addEventListener('keydown', (e) => this.onKey(e));
  }

  cancelFx() {
    for (const a of this.fx) a.cancel();
    this.fx = [];
  }

  /** Build sockets, gutter and one keycap element per token for a fresh level. */
  setLevel(state) {
    this.cancelFx();
    const { rows, cols, tokens } = state.level;
    this.selected = null;
    this.sig = {};
    this.boardEl.textContent = '';
    this.trayEl.textContent = '';
    this.boardEl.style.setProperty('--rows', rows);
    this.boardEl.setAttribute('aria-label', `Bàn Syntax Rows, ${rows} hàng, ${cols} cột`);
    this.socks = [];
    this.gut = [];
    this.hl = [];
    const ic = state.level.indent_cols ?? 2;
    if (ic > 0) {
      const cap = el('span', { class: 'indent-cap', 'aria-hidden': 'true', text: 'thụt lề' });
      cap.style.gridRow = '1';
      cap.style.gridColumn = `2 / span ${ic}`;
      this.boardEl.append(cap);
    }
    for (let r = 0; r < rows; r++) {
      const hl = el('i', { class: 'row-hl', 'aria-hidden': 'true' });
      hl.style.gridRow = String(r + 1);
      this.hl.push(hl);
      const rn = el('span', { class: 'rn', text: r + 1, 'aria-hidden': 'true' });
      rn.style.gridRow = String(r + 1);
      this.gut.push(rn);
      this.boardEl.append(hl, rn);
      const row = [];
      for (let c = 0; c < cols; c++) {
        const s = el('div', { class: 'sock' + (c < ic ? ' indent' : ''), role: 'gridcell', dataset: { r, c }, 'aria-label': `Hàng ${r + 1}, cột ${c + 1}${c < ic ? ', cột thụt lề' : ''}` });
        s.style.gridRow = String(r + 1);
        s.style.gridColumn = String(c + 2);
        row.push(s);
        this.boardEl.append(s);
      }
      this.socks.push(row);
    }
    this.els = {};
    for (const t of tokens) {
      const k = keycap({ tag: 'button', topic: t.topic === 'syntax' ? 'neutral' : t.topic, legend: t.text, legendClass: 'legend legend-c', cls: 'rk' });
      k.type = 'button';
      k.dataset.id = t.id;
      k.style.setProperty('--w', t.w);
      k.style.setProperty('--ch', [...t.text].length);
      k.firstElementChild.append(el('i', { class: 'flash', 'aria-hidden': 'true' }));
      k.addEventListener('pointerdown', (e) => this.onDown(e, t.id));
      k.addEventListener('click', (e) => { if (e.detail === 0) this.onKeyboardActivate(t.id); });
      this.els[t.id] = k;
    }
    this.render(state, { animate: false });
  }

  // ---- rendering -------------------------------------------------------------------------------
  render(state, { errorRow = null, animate = true } = {}) {
    const { tokens } = state.level;
    const trayList = [];
    for (const t of tokens) {
      const p = state.placed[t.id];
      const k = this.els[t.id];
      const sig = p ? `${p.row},${p.col}` : 'tray';
      const was = this.sig[t.id];
      if (p) {
        k.classList.add('on-board');
        k.style.gridRow = String(p.row + 1);
        k.style.gridColumn = `${p.col + 2} / span ${t.w}`;
        if (k.parentElement !== this.boardEl) this.boardEl.append(k);
        k.setAttribute('aria-label', `Mảnh ${t.text}, hàng ${p.row + 1}, cột ${p.col + 1}. Chạm để trả về khay.`);
      } else {
        k.classList.remove('on-board');
        k.style.gridRow = '';
        k.style.gridColumn = '';
        trayList.push(k);
        k.setAttribute('aria-label', `Mảnh ${t.text}, ${t.w}u. Kéo lên bàn hoặc chọn rồi chạm ô.`);
      }
      k.classList.toggle('sel', this.selected === t.id);
      k.setAttribute('aria-pressed', this.selected === t.id ? 'true' : 'false');
      if (animate && was !== undefined && was !== sig) (p ? this.thock(k) : this.rise(k));
      this.sig[t.id] = sig;
    }
    trayList.forEach((k, i) => {
      if (this.trayEl.children[i] !== k) this.trayEl.insertBefore(k, this.trayEl.children[i] || null);
    });
    while (this.trayEl.children.length > trayList.length) this.trayEl.lastElementChild.remove();
    if (!trayList.length) this.trayEl.append(el('span', { class: 'empty-note', text: '# Đã dùng hết mảnh trên khay.' }));
    this.countEl.textContent = `${trayList.length}/${tokens.length}`;
    this.boardEl.classList.toggle('has-sel', !!this.selected);
    this.setErrorRow(errorRow);
    this.paintKb();
  }

  setErrorRow(row, cls = 'err') {
    this.hl.forEach((h, r) => { h.classList.toggle('err', r === row && cls === 'err'); });
    this.gut.forEach((g, r) => { g.classList.toggle('err', r === row && cls === 'err'); });
  }

  setTraceRow(row) {
    this.hl.forEach((h, r) => h.classList.toggle('trace-active', r === row));
    this.gut.forEach((g, r) => g.classList.toggle('trace-active', r === row));
  }

  select(id) {
    this.selected = id;
    this.render(this.h.getState(), { errorRow: this.h.getErrorRow?.() ?? null, animate: false });
  }

  // ---- placement helpers ---------------------------------------------------------------------------
  tryPlace(id, row, col, maxDist) {
    const s = this.h.getState();
    const c = R.fitCol(s, id, row, col, maxDist);
    if (c == null) {
      this.shake();
      sfx('nope');
      this.h.onHint?.('Không đặt được mảnh ở vị trí này: hàng đã có mảnh, hoặc mảnh đầu tiên phải nằm trong 3 cột đầu.');
      return false;
    }
    this.place(id, row, c);
    return true;
  }

  place(id, row, col) {
    this.selected = null;
    this.h.onPlace(id, row, col);
    this.placeSound(id);
  }

  remove(id) {
    sfx('pickup');
    this.h.onRemove(id);
  }

  /** Neighbour flush against the token on the same row: brighter click, else a weighted drop. */
  placeSound(id) {
    const s = this.h.getState();
    const p = s.placed[id];
    if (!p) return;
    const w = R.tokenOf(s, id).w;
    const adj = R.rowTokens(s, p.row, id).some((o) => o.col + o.w === p.col || o.col === p.col + w);
    sfx(adj ? 'click' : 'drop', { cells: w });
  }

  onSockClick(e) {
    const sock = e.target.closest('.sock');
    if (!sock || !this.selected) return;
    this.tryPlace(this.selected, +sock.dataset.r, +sock.dataset.c);
  }

  onKeyboardActivate(id) {
    const s = this.h.getState();
    if (s.placed[id]) return this.remove(id);
    this.select(this.selected === id ? null : id);
    if (this.selected) this.boardEl.focus();
  }

  onKey(e) {
    const s = this.h.getState();
    const { rows, cols } = s.level;
    const d = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] }[e.key];
    if (d) {
      e.preventDefault();
      this.kb.r = Math.min(rows - 1, Math.max(0, this.kb.r + d[0]));
      this.kb.c = Math.min(cols - 1, Math.max(0, this.kb.c + d[1]));
      this.paintKb();
    } else if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      if (this.selected) return void this.tryPlace(this.selected, this.kb.r, this.kb.c);
      const hit = R.rowTokens(s, this.kb.r).find((t) => this.kb.c >= t.col && this.kb.c < t.col + t.w);
      if (hit) this.remove(hit.id);
    } else if (e.key === 'Escape' && this.selected) {
      this.select(null);
    }
  }

  paintKb() {
    for (const row of this.socks) for (const s of row) s.classList.remove('kb');
    if (this.boardEl.classList.contains('kbd') && this.socks[this.kb.r]) this.socks[this.kb.r][this.kb.c]?.classList.add('kb');
  }

  // ---- pointer drag ----------------------------------------------------------------------------------
  onDown(e, id) {
    if (e.button > 0 || this.settling) return;
    // See board.js: a mouse press must not start a text selection / native drag-and-drop.
    if (e.pointerType === 'mouse') e.preventDefault();
    window.getSelection()?.removeAllRanges();
    if (this.drag) this.onUp(e, true); // a previous drag never finished: clean it up first
    const k = this.els[id];
    const rect = k.getBoundingClientRect();
    this.drag = { id, k, x0: e.clientX, y0: e.clientY, gx: e.clientX - rect.left, gy: e.clientY - rect.top, w: rect.width, h: rect.height, fromBoard: k.classList.contains('on-board'), touch: e.pointerType !== 'mouse', started: false, target: null };
    try { k.setPointerCapture(e.pointerId); } catch { /* pointer already released */ }
    document.documentElement.classList.add('is-dragging');
    const move = (ev) => this.onMove(ev);
    let done = false;
    const finish = (cancelled) => (ev) => {
      if (done) return;
      done = true;
      k.removeEventListener('pointermove', move);
      k.removeEventListener('pointerup', up);
      k.removeEventListener('pointercancel', cancel);
      k.removeEventListener('lostpointercapture', cancel);
      this.onUp(ev, cancelled);
    };
    const up = finish(false);
    const cancel = finish(true);
    k.addEventListener('pointermove', move);
    k.addEventListener('pointerup', up);
    k.addEventListener('pointercancel', cancel);
    k.addEventListener('lostpointercapture', cancel);
  }

  metrics() {
    const a = this.socks[0][0].getBoundingClientRect();
    const b = this.socks[0][1].getBoundingClientRect();
    const c = this.socks.length > 1 ? this.socks[1][0].getBoundingClientRect() : a;
    return { left: a.left, top: a.top, sx: b.left - a.left, sy: this.socks.length > 1 ? c.top - a.top : a.height + 6, h: a.height };
  }

  onMove(e) {
    const d = this.drag;
    if (!d) return;
    if (!d.started) {
      if (Math.hypot(e.clientX - d.x0, e.clientY - d.y0) < 6) return;
      d.started = true;
      this.startGhost();
    }
    // Touch lift eases in over the pickup (120ms) so the piece does not jump away from the finger.
    const liftMax = d.touch ? Math.max(52, d.h / 2 + 28) : 0;
    const k = reducedMotion() ? 1 : Math.min(1, (performance.now() - d.t0) / 120);
    const lift = liftMax * (1 - Math.pow(1 - k, 3));
    const left = e.clientX - d.gx;
    const top = e.clientY - d.gy - lift;
    this.ghost.style.transform = `translate(${left}px, ${top}px)`;
    const m = this.m;
    const s = this.h.getState();
    const cy = top + d.h / 2;
    const row = Math.floor((cy - m.top + (m.sy - m.h) / 2) / m.sy);
    const col = Math.round((left - m.left) / m.sx);
    const tr = this.trayWrapEl.getBoundingClientRect();
    const overTray = e.clientX >= tr.left && e.clientX <= tr.right && e.clientY >= tr.top && e.clientY <= tr.bottom;
    d.target = null;
    this.clearPreview();
    if (!overTray && row >= 0 && row < s.level.rows) {
      const c = R.fitCol(s, d.id, row, col, 2);
      if (c != null) {
        d.target = { row, col: c };
        this.showPreview(d.id, row, c);
      }
    } else if (overTray) d.target = { tray: true };
    this.ghost.classList.toggle('bad', !d.target && !overTray);
  }

  showPreview(id, row, col) {
    const t = R.tokenOf(this.h.getState(), id);
    for (let c = col; c < col + t.w; c++) {
      const s = this.socks[row][c];
      s.classList.add('pv-ok');
      s.style.setProperty('--pv', capVar(t.topic));
    }
  }

  clearPreview() {
    for (const row of this.socks) for (const s of row) s.classList.remove('pv-ok');
  }

  startGhost() {
    const d = this.drag;
    this.m = this.metrics();
    const g = d.k.cloneNode(true);
    g.removeAttribute('data-id');
    g.removeAttribute('aria-label');
    g.removeAttribute('aria-pressed');
    g.className = d.k.className.replace(/\b(sel|dragging|on-board)\b/g, '').trim() + ' rk-ghost';
    g.style.cssText = `width:${d.w}px;height:${d.h}px;--kw:${d.w}px;--w:1;--ch:${d.k.style.getPropertyValue('--ch')};--u:${this.m.sx}px`;
    g.setAttribute('aria-hidden', 'true');
    g.tabIndex = -1;
    document.body.append(g);
    this.ghost = g;
    d.t0 = performance.now();
    // Pickup scale uses the independent `scale` property so it never fights the translate set in onMove.
    g.style.scale = '1.04';
    if (!reducedMotion()) g.animate([{ scale: '1' }, { scale: '1.04' }], { duration: 120, easing: EASE.out });
    sfx('pickup');
    d.k.classList.add('dragging');
  }

  /** Flies the ghost to a viewport top-left point while easing its pickup scale back to 1; resolves when done. */
  flyGhost(g, x, y, ms) {
    const from = g.style.transform || 'translate(0px, 0px)';
    const a = g.animate([{ transform: from, scale: '1.04' }, { transform: `translate(${x}px, ${y}px)`, scale: '1' }], { duration: ms, easing: EASE.out, fill: 'forwards' });
    return a.finished.catch(() => {});
  }

  onUp(e, cancelled) {
    const d = this.drag;
    this.drag = null;
    document.documentElement.classList.remove('is-dragging');
    if (!d) return;
    if (d.started) {
      const ghost = this.ghost;
      this.ghost = null;
      this.clearPreview();
      const finish = () => {
        ghost?.remove();
        // a new drag of the same token may already have started during the fly-back
        if (this.drag?.k !== d.k) d.k.classList.remove('dragging');
      };
      if (!ghost) return finish();
      const instant = reducedMotion();
      if (!cancelled && d.target && !d.target.tray) {
        // Valid drop: settle onto the socket (90ms), then commit.
        const { row, col } = d.target;
        const commit = () => {
          this.settled = true;
          try {
            this.place(d.id, row, col);
          } finally {
            this.settled = false;
            this.settling = false;
            finish();
          }
        };
        this.settling = true;
        if (instant) return commit();
        const r = this.socks[row][col].getBoundingClientRect();
        this.flyGhost(ghost, r.left, r.top, 90).then(commit);
        return;
      }
      const toTray = !cancelled && d.target?.tray;
      if (toTray && d.fromBoard) this.remove(d.id);
      else if (!cancelled && !toTray) sfx('nope');
      if (instant || !d.k.isConnected) return finish();
      const r = d.k.getBoundingClientRect();
      this.flyGhost(ghost, r.left, r.top, toTray ? 160 : 220).then(finish);
    } else {
      d.k.classList.remove('dragging');
      if (cancelled) return;
      // tap: board token returns to the tray, tray token toggles selection
      if (d.fromBoard) this.remove(d.id);
      else this.select(this.selected === d.id ? null : d.id);
    }
  }

  // ---- motion --------------------------------------------------------------------------------------------
  shake() {
    anim(this.boardEl, [0, -5, 5, -4, 4, 0].map((x) => ({ transform: `translateX(${x}px)` })), { duration: 260, easing: EASE.out });
  }

  thock(k) {
    // After a settled drag the piece already landed: skip the drop-in, press only.
    if (!this.settled) anim(k, [{ transform: 'translateY(-6px) scale(1.03)', opacity: 0.5 }, { transform: 'none', opacity: 1 }], { duration: 120, easing: EASE.out, fill: 'backwards' });
    anim(k.firstElementChild, [{ transform: 'translateY(0)' }, { transform: 'translateY(2px)', offset: 0.4 }, { transform: 'translateY(0)' }], { duration: 90, delay: this.settled ? 0 : 100, easing: EASE.out });
  }

  rise(k) {
    anim(k, [{ transform: 'translateY(8px)', opacity: 0 }, { transform: 'none', opacity: 1 }], { duration: 220, easing: EASE.out, fill: 'backwards' });
  }

  /** Fail: the error row's caps shake once (200ms) and the gutter number turns red. */
  flagError(row) {
    this.setErrorRow(row);
    if (row == null) return;
    for (const [id, k] of Object.entries(this.els)) {
      if (this.h.getState().placed[id]?.row === row) anim(k, [0, -6, 6, -4, 0].map((x) => ({ transform: `translateX(${x}px)` })), { duration: 200, easing: EASE.out });
    }
  }

  /** Pass: rows compile top to bottom. Each row flashes Matcha (120ms) then lifts away; 80ms between rows. */
  async animateCompile(lines) {
    const jobs = [];
    lines.forEach((ln, i) => {
      const t0 = i * 200;
      setTimeout(() => {
        sfx('line', { i });
        this.hl[ln.row]?.classList.add('ok');
        this.gut[ln.row]?.classList.add('ok');
      }, t0);
      for (const id of ln.ids) {
        const k = this.els[id];
        this.fx.push(anim(k.querySelector('.flash'), [{ opacity: 0 }, { opacity: 1 }], { duration: 120, delay: t0, easing: EASE.out, fill: 'forwards' }));
        const a = anim(k, [
          { transform: 'translateY(0) rotate(0deg) scale(1)', opacity: 1 },
          { transform: `translateY(-16px) rotate(${(Math.random() < 0.5 ? -1 : 1) * rand(3, 7)}deg) scale(.92)`, opacity: 0 },
        ], { duration: 260, delay: t0 + 120, easing: EASE.out, fill: 'forwards' });
        this.fx.push(a);
        jobs.push(a.finished);
      }
    });
    if (lines.length) setTimeout(() => sfx('compile'), (lines.length - 1) * 200 + 120);
    await Promise.all(jobs);
    await wait(60);
  }
}
