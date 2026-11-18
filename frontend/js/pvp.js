// PvpClient: owns the WebSocket of a 1v1 match ("Đối kháng", docs/pvp.md).
// Transport only: connect, JSON in/out, keep-alive ping, automatic reconnect with backoff, dispatch.
// The server is authoritative. Nothing here knows about rules, boards or screens.
import * as api from './api.js';

const BACKOFF_MS = [500, 1000, 2000, 4000]; // then 4 s again until MAX_TRIES
const MAX_TRIES = 8;                          // ~ 27 s of trying: longer than the server's 20 s grace
const PING_MS = 8000;
const SILENCE_MS = 22000;                     // no frame at all for this long: the link is dead, reconnect
const FATAL_CODES = new Set([1008, 4400, 4401, 4403, 4404, 4409, 4410]); // refused / unknown ticket / ended: never retry

/**
 * opts: {
 *   ticket,
 *   onMessage(msg)            every server frame (parsed JSON with `t`)
 *   onStatus(status, info)    'connecting' | 'open' | 'reconnecting' | 'failed' | 'closed'
 * }
 * `status` 'open' fires on the first open and after every reconnect (info.reconnected).
 */
export class PvpClient {
  constructor({ ticket, onMessage = () => {}, onStatus = () => {} }) {
    this.ticket = ticket;
    this.onMessage = onMessage;
    this.onStatus = onStatus;
    this.ws = null;
    this.tries = 0;
    this.everOpen = false;
    this.closedByUs = false;
    this.finished = false; // the match ended: a closing socket is expected, do not reconnect
    this.pingN = 0;
    this.pingTimer = null;
    this.retryTimer = null;
    this.silenceTimer = null;
    this.lastFrame = 0;
    this.latency = null;
    this.pingSent = new Map();
    this.status = 'connecting';
  }

  setStatus(status, info = {}) {
    this.status = status;
    this.onStatus(status, info);
  }

  async connect() {
    if (this.closedByUs) return;
    let ws;
    try {
      ws = await api.openPvpSocket(this.ticket);
    } catch {
      return this.scheduleRetry();
    }
    if (this.closedByUs) {
      try { ws.close(); } catch { /* already closed */ }
      return;
    }
    this.ws = ws;
    let opened = false;
    ws.onopen = () => {
      if (this.ws !== ws) return;
      opened = true;
      const reconnected = this.everOpen;
      this.everOpen = true;
      this.tries = 0;
      this.lastFrame = Date.now();
      this.setStatus('open', { reconnected });
      this.startTimers();
    };
    ws.onmessage = (ev) => {
      if (this.ws !== ws) return;
      this.lastFrame = Date.now();
      let msg;
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (!msg || typeof msg.t !== 'string') return;
      if (msg.t === 'pong') {
        const sent = this.pingSent.get(msg.n);
        if (sent != null) this.latency = Date.now() - sent;
        this.pingSent.clear();
      }
      this.onMessage(msg);
    };
    ws.onerror = () => { /* the close event follows and does the work */ };
    ws.onclose = (ev) => {
      if (this.ws !== ws) return;
      this.ws = null;
      this.stopTimers();
      if (this.closedByUs || this.finished) {
        this.setStatus('closed');
        return;
      }
      if (ev && FATAL_CODES.has(ev.code)) {
        this.setStatus('failed', { code: ev.code });
        return;
      }
      if (!opened && !this.everOpen && this.tries >= 2) {
        // never connected at all (bad ticket, server down): do not keep a lobby spinning
        this.setStatus('failed', { code: ev && ev.code });
        return;
      }
      this.scheduleRetry();
    };
  }

  scheduleRetry() {
    if (this.closedByUs || this.finished) return;
    if (this.tries >= MAX_TRIES) {
      this.setStatus('failed', { exhausted: true });
      return;
    }
    const wait = BACKOFF_MS[Math.min(this.tries, BACKOFF_MS.length - 1)];
    this.tries++;
    this.setStatus('reconnecting', { attempt: this.tries, in: wait });
    clearTimeout(this.retryTimer);
    this.retryTimer = setTimeout(() => this.connect(), wait);
  }

  startTimers() {
    this.stopTimers();
    this.pingTimer = setInterval(() => this.ping(), PING_MS);
    this.silenceTimer = setInterval(() => {
      if (this.ws && Date.now() - this.lastFrame > SILENCE_MS) {
        try { this.ws.close(); } catch { /* ignore */ }
      }
    }, 2000);
  }

  stopTimers() {
    clearInterval(this.pingTimer);
    clearInterval(this.silenceTimer);
    this.pingTimer = null;
    this.silenceTimer = null;
  }

  ping() {
    const n = ++this.pingN;
    this.pingSent.set(n, Date.now());
    this.send({ t: 'ping', n });
  }

  get open() {
    return !!this.ws && this.ws.readyState === 1;
  }

  /** Sends one JSON frame. Returns false (and drops it) when the link is down: actions are never queued. */
  send(obj) {
    if (!this.open) return false;
    try {
      this.ws.send(JSON.stringify(obj));
      return true;
    } catch {
      return false;
    }
  }

  /** The match is over: the socket may close without a reconnect. */
  markFinished() {
    this.finished = true;
  }

  /** A rematch started on this same socket: reconnects are wanted again. */
  resume() {
    this.finished = false;
  }

  close() {
    this.closedByUs = true;
    this.stopTimers();
    clearTimeout(this.retryTimer);
    const ws = this.ws;
    this.ws = null;
    if (ws) {
      try { ws.close(1000); } catch { /* ignore */ }
    }
    if (this.status !== 'closed') this.setStatus('closed');
  }
}

// ---- last known PvP rating (shown on the entry screen; the server's number from the last `end` message) ----
const RATING_KEY = 'syntaxstack.pvp.rating';

export function getRating() {
  try {
    const n = Number(localStorage.getItem(RATING_KEY));
    return Number.isFinite(n) && n > 0 ? Math.round(n) : null;
  } catch {
    return null;
  }
}

export function setRating(n) {
  try {
    if (Number.isFinite(n) && n > 0) localStorage.setItem(RATING_KEY, String(Math.round(n)));
  } catch {
    /* storage blocked */
  }
}

// ---- live-match ticket (sessionStorage): a page reload inside the 20 s grace reconnects with it ----
const TICKET_KEY = 'syntaxstack.pvp.ticket';

/** t: { ticket, kind, level, nickname } */
export function storeTicket(t) {
  try {
    sessionStorage.setItem(TICKET_KEY, JSON.stringify(t));
  } catch {
    /* storage blocked: no resume after a reload */
  }
}

export function loadTicket() {
  try {
    const v = JSON.parse(sessionStorage.getItem(TICKET_KEY));
    return v && typeof v.ticket === 'string' ? v : null;
  } catch {
    return null;
  }
}

export function clearTicket() {
  try {
    sessionStorage.removeItem(TICKET_KEY);
  } catch {
    /* ignore */
  }
}
