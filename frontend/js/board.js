// Code Rescue board + tray + items: rendering, input (pointer drag, tap-to-place, keyboard) and the motion table.
import { SIZE, canPlace, fitsAnywhere, completedLines } from './game.js';
import { sfx } from './sound.js';
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
    this.pvEls = [];
    this.pvCells = [];
    this.pvKey = '';
    this.settled = false;
    this.settling = false;
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
    this.clearLines(); // the cell classes below are rewritten; the next showPreview rebuilds the frames
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
      this.animatePlace(ui.dropped, { settled: this.settled, lock: !!ui.lock });
    }
  }

  label(g, r, c) {
    const pos = `Hàng ${r + 1}, cột ${c + 1}`;
    if (!g) return pos + ': trống';
    return pos + ': ' + (g.bug ? 'bug' : TOPIC_NAMES[g.topic]);
  }

  renderTray(s, ui) {
    const t = this.trayEl;
    while (t.children.length < 3) {
      const slot = el('div', { class: 'slot', dataset: { idx: t.children.length } });
      // The whole slot is the drag handle: on phones a small piece leaves most of the slot empty,
      // and a touch there used to scroll the page instead of picking the piece up.
      slot.addEventListener('pointerdown', (e) => {
        const btn = slot.querySelector('.piece');
        if (btn && !btn.disabled) this.onDown(e, +slot.dataset.idx, btn);
      });
      t.append(slot);
    }
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
        const nofit = !fitsAnywhere(s.grid, p);
        const prev = btn.dataset.fit;
        btn.classList.toggle('nofit', nofit);
        btn.dataset.fit = nofit ? '0' : '1';
        if (prev === '1' && nofit) anim(btn, [{ rotate: '0deg' }, { rotate: '-3deg' }, { rotate: '3deg' }, { rotate: '-2deg' }, { rotate: '0deg' }], { duration: 300, delay: 150, easing: EASE.out });
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
    // pointerdown is handled by the whole slot (renderTray), so a touch beside a small piece still drags it
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
    this.clearLines();
    this.hover = null;
  }

  clearLines() {
    for (const n of this.pvEls) n.remove();
    for (const c of this.pvCells) c.classList.remove('pv-line');
    this.pvEls = [];
    this.pvCells = [];
    this.pvKey = '';
  }

  /** Frames + brightened caps for rows/cols this placement would complete. Rebuilt only when the target changes. */
  syncLines(piece, r0, c0) {
    const grid = this.h.getState().grid;
    const { rows, cols } = completedLines(grid, piece, r0, c0);
    const key = JSON.stringify([rows, cols, piece.topic]);
    if (key === this.pvKey) return;
    this.clearLines();
    this.pvKey = key;
    const mk = (row, col) => {
      const n = el('i', { class: 'pv-frame', 'aria-hidden': 'true' });
      n.style.gridRow = row;
      n.style.gridColumn = col;
      n.style.color = `var(--cap-${piece.topic})`;
      n.style.borderColor = "currentColor";
      this.boardEl.append(n);
      this.pvEls.push(n);
    };
    const lit = new Set();
    for (const r of rows) {
      mk(`${r + 1}`, '1 / -1');
      for (let c = 0; c < SIZE; c++) lit.add(r * SIZE + c);
    }
    for (const c of cols) {
      mk('1 / -1', `${c + 1}`);
      for (let r = 0; r < SIZE; r++) lit.add(r * SIZE + c);
    }
    for (const k of lit) {
      const r = Math.floor(k / SIZE);
      const c = k % SIZE;
      if (!grid[r][c]) continue; // only already-filled cells; the piece's own cells keep the socket glow
      this.cells[k].classList.add('pv-line');
      this.pvCells.push(this.cells[k]);
    }
  }

  showPreview(piece, r0, c0) {
    for (const c of this.cells) c.classList.remove('pv-ok', 'pv-bomb');
    const ok = canPlace(this.h.getState().grid, piece, r0, c0);
    if (!ok) {
      this.clearLines();
      return false; // invalid: no ghost (the dragged piece tints red instead)
    }
    this.syncLines(piece, r0, c0);
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
    const t = this.resolveTarget(p, r - Math.floor(p.h / 2), c - Math.floor(p.w / 2));
    if (!t) {
      this.shake();
      return this.h.onHint('Không đặt được khối ở vị trí này.');
    }
    this.clearPreview();
    sfx('drop', { cells: p.cells.length });
    this.h.onPlace(ui.selected, t[0], t[1]);
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
    sfx('nope');
    anim(this.boardEl, [{ transform: 'translateX(0)' }, { transform: 'translateX(-5px)' }, { transform: 'translateX(5px)' }, { transform: 'translateX(-4px)' }, { transform: 'translateX(4px)' }, { transform: 'translateX(0)' }], { duration: 260, easing: EASE.out });
  }

  // ---- drag ----------------------------------------------------------------------------------
  onDown(e, idx, btn) {
    if (e.button > 0 || this.settling || this.h.getState().phase !== 'play') return;
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
    const gap = m.sx - m.size;
    const gw = p.w * m.size + (p.w - 1) * gap;
    const gh = p.h * m.size + (p.h - 1) * gap;
    // Touch lift eases in over the pickup (120ms) so the piece does not jump away from the finger.
    const liftMax = d.touch ? Math.max(64, gh / 2 + 28) : 0;
    const k = reducedMotion() ? 1 : Math.min(1, (performance.now() - d.t0) / 120);
    const lift = liftMax * (1 - Math.pow(1 - k, 3));
    const left = e.clientX - gw / 2;
    const top = e.clientY - gh / 2 - lift;
    this.ghost.style.transform = `translate(${left}px, ${top}px)`;
    const fc = (left - m.left) / m.sx;
    const fr = (top - m.top) / m.sy;
    const t = this.resolveTarget(p, fr, fc);
    d.target = t || [Math.round(fr), Math.round(fc)];
    d.ok = this.showPreview(p, d.target[0], d.target[1]);
    this.ghost.classList.toggle('bad', !d.ok);
  }

  /** Rounded cell if valid, else the valid neighbour nearest the fractional position (max distance 1.0). */
  resolveTarget(p, fr, fc) {
    const grid = this.h.getState().grid;
    const r0 = Math.round(fr);
    const c0 = Math.round(fc);
    if (canPlace(grid, p, r0, c0)) return [r0, c0];
    let best = null;
    let bestD = Infinity;
    for (let dr = -1; dr <= 1; dr++)
      for (let dc = -1; dc <= 1; dc++) {
        if (!dr && !dc) continue;
        if (!canPlace(grid, p, r0 + dr, c0 + dc)) continue;
        const dist = Math.hypot(r0 + dr - fr, c0 + dc - fc);
        if (dist < bestD) {
          bestD = dist;
          best = [r0 + dr, c0 + dc];
        }
      }
    return best && bestD <= 1 ? best : null;
  }

  startGhost() {
    const d = this.drag;
    const p = this.h.getState().tray[d.idx];
    this.m = this.metrics();
    d.t0 = performance.now();
    sfx('pickup');
    const gap = this.m.sx - this.m.size;
    const g = el('div', { class: 'ghost', 'aria-hidden': 'true' });
    g.style.setProperty('--u', this.m.size + 'px');
    const inner = el('div', { class: 'ghost-in' });
    inner.style.gap = gap + 'px';
    inner.style.gridTemplateColumns = `repeat(${p.w}, ${this.m.size}px)`;
    inner.style.gridTemplateRows = `repeat(${p.h}, ${this.m.size}px)`;
    for (const [r, c] of p.cells) {
      const k = keycap({ topic: p.topic, legend: TOPIC_GLYPH[p.topic] });
      k.style.gridRow = String(r + 1);
      k.style.gridColumn = String(c + 1);
      inner.append(k);
    }
    g.append(inner);
    document.body.append(g);
    this.ghost = g;
    if (!reducedMotion()) {
      const tray = d.btn.firstElementChild?.getBoundingClientRect().width || this.m.size;
      inner.style.transform = 'scale(1.04)';
      inner.animate([{ transform: `scale(${tray / this.m.size})` }, { transform: 'scale(1.04)' }], { duration: 120, easing: EASE.out });
    }
    d.btn.classList.add('dragging');
    this.h.onSelect(d.idx, false, true);
  }

  /** Animates the ghost (outer translate/scale + inner pickup scale) to `to`; resolves when done. */
  flyGhost(g, to, ms) {
    const from = g.style.transform || 'translate(0px, 0px)';
    const a = g.animate([{ transform: from }, { transform: to }], { duration: ms, easing: EASE.out, fill: 'forwards' });
    const inner = g.firstElementChild;
    inner?.animate([{ transform: 'scale(1.04)' }, { transform: 'scale(1)' }], { duration: ms, easing: EASE.out, fill: 'forwards' });
    return a.finished.catch(() => {});
  }

  onUp(e, cancelled) {
    const d = this.drag;
    this.drag = null;
    document.documentElement.classList.remove('is-dragging');
    if (!d) return;
    if (!d.started) {
      d.btn.classList.remove('dragging');
      if (!cancelled) this.h.onSelect(d.idx, false);
      return;
    }
    const ghost = this.ghost;
    this.ghost = null;
    if (!ghost) {
      d.btn.classList.remove('dragging');
      this.clearPreview();
      return;
    }
    if (!cancelled && d.ok) {
      const place = () => {
        this.clearPreview();
        this.settled = true;
        sfx('drop', { cells: this.h.getState().tray[d.idx]?.cells.length || 1 });
        try {
          this.h.onPlace(d.idx, d.target[0], d.target[1]);
        } finally {
          this.settled = false;
          ghost.remove();
          d.btn.classList.remove('dragging');
          this.settling = false;
        }
      };
      this.settling = true;
      if (reducedMotion()) return place();
      const m = this.metrics();
      this.flyGhost(ghost, `translate(${m.left + d.target[1] * m.sx}px, ${m.top + d.target[0] * m.sy}px) scale(1)`, 90).then(place);
      return;
    }
    // Failed drop / cancel: the piece flies back to its tray slot.
    this.clearPreview();
    const overTray = !cancelled && !!document.elementFromPoint(e.clientX, e.clientY)?.closest('#tray-zone');
    if (!cancelled && !overTray) sfx('nope');
    const done = () => {
      ghost.remove();
      d.btn.classList.remove('dragging');
    };
    const k = d.btn.isConnected ? d.btn.firstElementChild : null;
    if (reducedMotion() || !k) return done();
    const r = k.getBoundingClientRect();
    this.flyGhost(ghost, `translate(${r.left}px, ${r.top}px) scale(${r.width / this.m.size})`, overTray ? 160 : 220).then(done);
  }

  // ---- animations (WAAPI one-offs) -------------------------------------------------------------
  keyOf(r, c) {
    return this.keys[r * SIZE + c];
  }

  /** Caps drop in 120ms then "thock" (2px press and release), 12ms stagger across the cells. */
  animatePlace(cells, { settled = false, lock = false } = {}) {
    const depth = cells.length <= 2 ? 2 : cells.length <= 5 ? 3 : 4;
    const base = settled ? 0 : 100; // a settled drag already landed: skip the drop-in, thock straight away
    cells.forEach(([r, c], i) => {
      const key = this.keyOf(r, c);
      const delay = i * 12;
      if (!settled) anim(key, [{ transform: 'translateY(-6px) scale(1.03)', opacity: 0.5 }, { transform: 'none', opacity: 1 }], { duration: 120, delay, easing: EASE.out, fill: 'backwards' });
      const top = key.firstElementChild;
      anim(top, [{ transform: 'translateY(0)' }, { transform: `translateY(${depth}px)`, offset: 0.4 }, { transform: 'translateY(0)' }], { duration: 90, delay: delay + base, easing: EASE.out });
      if (lock) anim(key, [{ transform: 'scale(1.04, .94)' }, { transform: 'none' }], { duration: 160, delay: delay + base, easing: EASE.out });
    });
    if (lock) anim(this.boardEl, [{ transform: 'translateY(0)' }, { transform: 'translateY(2px)', offset: 0.4 }, { transform: 'translateY(0)' }], { duration: 140, delay: base, easing: EASE.out });
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
    // Lift the board above the tray and every filled cell above the empty sockets, so caps fall in front.
    const col = this.boardEl.closest('.board-col');
    col?.classList.add('crashing');
    this.boardEl.classList.add('crashing');
    for (let r = 0; r < SIZE; r++)
      for (let c = 0; c < SIZE; c++) {
        if (this.cells[r * SIZE + c].classList.contains('empty')) continue;
        this.cells[r * SIZE + c].style.zIndex = String(6 + SIZE - r); // higher rows over lower sockets
        this.fx.push(anim(this.keyOf(r, c), [
          { transform: 'translateY(0) rotate(0deg)' },
          { transform: `translateY(110vh) rotate(${rand(-25, 25)}deg)` },
        ], { duration: 700, delay: (SIZE - 1 - r) * 30 + rand(0, 18), easing: 'cubic-bezier(.5, 0, .75, 0)', fill: 'forwards' }));
      }
    await wait(700 + (SIZE - 1) * 30 + 60);
    root.style.overflow = '';
    col?.classList.remove('crashing');
    this.boardEl.classList.remove('crashing');
    for (const c of this.cells) c.style.zIndex = '';
  }
}
