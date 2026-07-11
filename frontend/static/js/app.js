/* ═══════════════════════════════════════════════
   SmartTrade AI Platform — Core App JS
   ═══════════════════════════════════════════════ */

const PUBLIC_ROUTES = ['/login', '/register', '/forgot-password', '/reset-password', '/verify-email', '/terms', '/privacy'];
const IS_PUBLIC = PUBLIC_ROUTES.includes(window.location.pathname);

// Expose global confidence threshold early — updated properly after Auth.init()
window.MIN_CONFIDENCE = parseInt(localStorage.getItem('min_confidence'), 10) || 60;

// ─── API Client ───────────────────────────────
const API = {
  base: '/api/v1',
  token: () => localStorage.getItem('access_token'),

  headers() {
    const t = this.token();
    const h = { 'Content-Type': 'application/json' };
    if (t) h['Authorization'] = `Bearer ${t}`;
    return h;
  },

  async get(path, params = {}) {
    try {
      const url = new URL(this.base + path, window.location.origin);
      Object.entries(params).filter(([,v]) => v !== '' && v !== null && v !== undefined)
        .forEach(([k, v]) => url.searchParams.set(k, v));
      const res = await fetch(url, { headers: this.headers() });
      if (res.status === 401 && !IS_PUBLIC) {
        localStorage.removeItem('access_token');
        window.location.replace('/login');
        return null;
      }
      return res.ok ? res.json() : null;
    } catch (e) {
      console.error('API GET error:', path, e);
      return null;
    }
  },

  async post(path, data = {}) {
    try {
      const res = await fetch(this.base + path, {
        method: 'POST',
        headers: this.headers(),
        body: JSON.stringify(data),
      });
      return res.json();
    } catch (e) {
      console.error('API POST error:', path, e);
      return null;
    }
  },

  async put(path, data = {}) {
    try {
      const res = await fetch(this.base + path, {
        method: 'PUT',
        headers: this.headers(),
        body: JSON.stringify(data),
      });
      return res.json();
    } catch (e) {
      return null;
    }
  },

  async delete(path) {
    try {
      const res = await fetch(this.base + path, {
        method: 'DELETE',
        headers: this.headers(),
      });
      return res.ok;
    } catch (e) {
      return false;
    }
  },
};

// ─── Auth ─────────────────────────────────────
const Auth = {
  user: null,

  async init() {
    // On public pages (login/register) — skip auth check entirely
    if (IS_PUBLIC) return true;

    const token = localStorage.getItem('access_token');
    if (!token) {
      window.location.replace('/login');
      return false;
    }

    const data = await API.get('/auth/me');
    if (!data) return false;  // API.get already redirected on 401

    this.user = data;
    this.updateUI();
    this.applyTheme(data.theme);
    if (data.push_enabled) _initPushSubscription();
    return true;
  },

  applyTheme(theme) {
    // localStorage wins if the user has already toggled manually; server value is used as fallback
    const t = localStorage.getItem('theme') || theme || 'dark';
    document.documentElement.setAttribute('data-theme', t);
    localStorage.setItem('theme', t);
    const btn = document.getElementById('themeToggle');
    if (btn) btn.innerHTML = t === 'dark' ? '<i class="bi bi-sun-fill"></i>' : '<i class="bi bi-moon-fill"></i>';
  },

  updateUI() {
    const u = this.user;
    if (!u) return;

    const banner = document.getElementById('approvalBanner');
    if (banner) {
      if (u.approval_status === 'pending') {
        banner.style.display = '';
        banner.innerHTML = '<i class="bi bi-hourglass-split me-2"></i>Your account is pending admin approval. ' +
          'You can explore the interface, but signals, trading, portfolio, and other data features stay locked until approved.';
        banner.className = 'approval-banner approval-banner-pending';
      } else if (u.approval_status === 'rejected') {
        banner.style.display = '';
        banner.innerHTML = '<i class="bi bi-x-octagon me-2"></i>Your account access request was not approved. Contact support if you believe this is a mistake.';
        banner.className = 'approval-banner approval-banner-rejected';
      } else {
        banner.style.display = 'none';
      }
    }

    const initial = (u.username || 'U').charAt(0).toUpperCase();
    document.querySelectorAll('#userAvatar, #navUserAvatar').forEach(el => el.textContent = initial);
    document.querySelectorAll('#sidebarUserName, #navUserName').forEach(el => el.textContent = u.full_name || u.username);
    const roleEl = document.getElementById('sidebarUserRole');
    if (roleEl) {
      roleEl.textContent = u.role;
      roleEl.className = `user-role badge bg-${u.role === 'admin' ? 'danger' : u.role === 'premium' ? 'warning text-dark' : 'secondary'}`;
    }
    if (u.role === 'admin') {
      const adminNav = document.getElementById('adminNav');
      if (adminNav) {
        adminNav.style.display = 'block';
        // If admin is the saved/active group, open it now (it was hidden when sidebar init ran)
        const savedGroup = localStorage.getItem('sidebar_open_group');
        if (savedGroup === 'admin') {
          const items   = adminNav.querySelector('.nav-group-items');
          const btn     = adminNav.querySelector('.nav-group-toggle');
          const chevron = btn && btn.querySelector('.nav-chevron');
          if (items) { items.style.transition = 'none'; items.style.maxHeight = items.scrollHeight + 'px'; requestAnimationFrame(() => { items.style.transition = ''; }); }
          if (btn) btn.setAttribute('aria-expanded', 'true');
          if (chevron) chevron.style.transform = 'rotate(90deg)';
          adminNav.classList.add('active-group');
        }
      }
    }
  },

  async logout() {
    try { await API.post('/auth/logout'); } catch(e) {}
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    window.location.replace('/login');
  },
};

// ─── Toast ────────────────────────────────────
const Toast = {
  show(message, type = 'info', duration = 4000) {
    const container = document.getElementById('toastContainer');
    if (!container) return;
    const icons   = { success: 'check-circle-fill', error: 'x-circle-fill', warning: 'exclamation-triangle-fill', info: 'info-circle-fill' };
    const colors  = { success: 'var(--green)', error: 'var(--red)', warning: 'var(--yellow)', info: 'var(--accent)' };
    const el = document.createElement('div');
    el.className = 'toast smart-toast show';
    el.innerHTML = `<div class="toast-body d-flex align-items-center gap-2">
      <i class="bi bi-${icons[type]}" style="color:${colors[type]}"></i>
      <span>${message}</span>
      <button type="button" class="btn-close btn-close-white ms-auto" onclick="this.closest('.toast').remove()"></button>
    </div>`;
    container.appendChild(el);
    setTimeout(() => el.remove(), duration);
  },
};

// ─── Notifications ────────────────────────────
const Notifications = {
  async load() {
    // Fetches ALL notifications (read + unread), not just unread — the
    // dropdown previously called with unread:'true', so any notification
    // instantly vanished the moment it was marked read (individually, or
    // via "Mark all read"), with no way to see history afterward.
    const data = await API.get('/notifications/', {});
    if (!data) return;
    const countEl = document.getElementById('notifCount');
    const listEl  = document.getElementById('notifList');
    if (countEl) {
      countEl.textContent  = data.unread_count;
      countEl.style.display = data.unread_count > 0 ? 'flex' : 'none';
    }
    if (listEl) {
      if (!data.notifications?.length) {
        listEl.innerHTML = '<p class="p-3 text-muted fs-sm mb-0">No notifications</p>';
        return;
      }
      // Theme-aware text color (was hardcoded #fff — invisible on white
      // cards in light theme, the same bug class fixed elsewhere for
      // tables/badges but missed in this widget).
      listEl.innerHTML = data.notifications.map(n => `
        <div class="notif-item ${n.is_read ? '' : 'unread'}" data-id="${n.id}" onclick="Notifications.markRead(${n.id})" style="cursor:pointer">
          <div class="fw-semibold" style="font-size:13px;color:var(--text-primary)">${n.title}</div>
          <div style="font-size:12px;color:var(--text-secondary)">${n.message}</div>
          <div class="mt-1" style="font-size:11px;color:var(--text-muted)">${formatTime(n.created_at)}</div>
        </div>`).join('');
    }
  },
  async markRead(id) {
    await API.put(`/notifications/${id}/read`, {});
    this.load();
  },
  async markAllRead() {
    await API.put('/notifications/read-all');
    this.load();
  },
};

// ─── Live Price Cache (populated by WebSocket) ───────────────
const LivePrices = {
  _cache: {},   // { symbol: { price, change_pct, change, high, low, volume } }
  _listeners: [],  // callbacks registered by page components

  update(tick) {
    this._cache[tick.symbol] = tick;
    this._listeners.forEach(fn => { try { fn(tick); } catch(e) {} });
  },

  get(symbol) { return this._cache[symbol] || null; },

  onUpdate(fn) { this._listeners.push(fn); },

  // Seed from REST endpoint (fast initial paint before WS connects)
  async seed() {
    const data = await API.get('/market-data/live-prices');
    if (data?.prices) {
      Object.values(data.prices).forEach(t => { this._cache[t.symbol] = t; });
    }
  },
};

// ─── Ticker Ribbon ────────────────────────────
const Ticker = {
  _items: {},

  _renderHtml() {
    const items = Object.values(this._items);
    if (!items.length) return null;
    return items.map(item => {
      const cls   = item.change_pct >= 0 ? 'up' : 'down';
      const arrow = item.change_pct >= 0 ? '▲' : '▼';
      return `<span class="ticker-item" data-symbol="${item.symbol}">
        <span class="ticker-symbol">${item.symbol}</span>
        <span class="ticker-price"> ${formatPrice(item.price)}</span>
        <span class="ticker-change ${cls}"> ${arrow}${Math.abs(item.change_pct).toFixed(2)}%</span>
      </span>`;
    }).join('');
  },

  async load() {
    const track = document.getElementById('tickerTrack');
    if (!track) return;
    const data = await API.get('/market-data/heatmap');
    if (!data?.heatmap?.length) {
      track.textContent = 'Market data loading...';
      return;
    }
    data.heatmap.forEach(item => { this._items[item.symbol] = item; });
    const html = this._renderHtml();
    if (html) track.innerHTML = html + html;
  },

  // Called by WebSocket on each live price update
  patchItem(tick) {
    if (!this._items[tick.symbol]) return;  // only update symbols already in ribbon
    this._items[tick.symbol] = { ...this._items[tick.symbol], ...tick };
    const track = document.getElementById('tickerTrack');
    if (!track) return;
    // Update the specific ticker item DOM (no full re-render — avoids scroll reset)
    track.querySelectorAll(`[data-symbol="${tick.symbol}"]`).forEach(el => {
      const cls   = tick.change_pct >= 0 ? 'up' : 'down';
      const arrow = tick.change_pct >= 0 ? '▲' : '▼';
      el.querySelector('.ticker-price').textContent  = ' ' + formatPrice(tick.price);
      const chgEl = el.querySelector('.ticker-change');
      chgEl.textContent = ` ${arrow}${Math.abs(tick.change_pct).toFixed(2)}%`;
      chgEl.className   = `ticker-change ${cls}`;
    });
  },
};

// ─── Formatters ───────────────────────────────
function formatPrice(price, market) {
  if (!price && price !== 0) return '—';
  const p = parseFloat(price);
  // Explicit market hint
  if (market === 'forex')        return p.toFixed(4);
  if (market === 'crypto') {
    if (p >= 1000)  return p.toLocaleString('en-IN', { maximumFractionDigits: 2 });
    if (p >= 1)     return p.toFixed(4);
    return p.toFixed(6);
  }
  // commodity / indian_stock / index — always 2 dp
  if (market)                    return p.toFixed(2);
  // Auto-detect by magnitude (fallback when no market passed)
  if (p >= 10000) return p.toLocaleString('en-IN', { maximumFractionDigits: 2 });
  if (p >= 100)   return p.toFixed(2);
  if (p >= 1)     return p.toFixed(4);
  return p.toFixed(6);
}

function formatTime(iso) {
  if (!iso) return '—';
  // Ensure UTC interpretation — append Z if no timezone offset present
  const str = /[Zz]|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : iso + 'Z';
  return new Date(str).toLocaleString('en-IN', {
    timeZone: 'Asia/Kolkata',
    dateStyle: 'short',
    timeStyle: 'short',
  });
}

// Relative "time ago" for live-feed scanning (e.g. "3m ago", "2h ago").
// Falls back to an absolute IST date for anything older than ~7 days.
function relativeTime(iso) {
  if (!iso) return '—';
  const str = /[Zz]|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : iso + 'Z';
  const then = new Date(str), now = new Date();
  const secs = Math.max(0, Math.floor((now - then) / 1000));
  if (secs < 45)   return 'just now';
  if (secs < 90)   return '1m ago';
  const mins = Math.floor(secs / 60);
  if (mins < 60)   return mins + 'm ago';
  const hrs = Math.floor(mins / 60);
  if (hrs < 24)    return hrs + 'h ago';
  const days = Math.floor(hrs / 24);
  if (days < 7)    return days + 'd ago';
  return then.toLocaleDateString('en-IN', { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short' });
}

function formatChange(val) {
  if (val === null || val === undefined) return '<span class="text-muted">—</span>';
  const cls  = val >= 0 ? 'text-green' : 'text-red';
  const sign = val >= 0 ? '+' : '';
  return `<span class="${cls}">${sign}${parseFloat(val).toFixed(2)}%</span>`;
}

function signalBadge(type) {
  const map = { BUY: 'signal-buy', SELL: 'signal-sell', HOLD: 'signal-hold', EXIT: 'signal-exit' };
  return `<span class="signal-badge ${map[type] || ''}">${type || '—'}</span>`;
}

function confidenceBar(score) {
  if (!score && score !== 0) return '<span class="text-muted">—</span>';
  const s = parseFloat(score);
  const color = s >= 90 ? 'var(--green)' : s >= 75 ? 'var(--accent)' : s >= 60 ? 'var(--yellow)' : 'var(--red)';
  return `<div class="confidence-bar">
    <div class="confidence-fill" style="width:${s}%;background:${color}"></div>
  </div><small class="text-muted">${s.toFixed(1)}%</small>`;
}

// ─── Boot ─────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {

  // Apply saved theme immediately
  const savedTheme = localStorage.getItem('theme') || 'dark';
  document.documentElement.setAttribute('data-theme', savedTheme);

  // Theme toggle button — persists to server + localStorage
  const themeToggle = document.getElementById('themeToggle');
  if (themeToggle) {
    themeToggle.innerHTML = savedTheme === 'dark' ? '<i class="bi bi-sun-fill"></i>' : '<i class="bi bi-moon-fill"></i>';
    themeToggle.addEventListener('click', () => {
      const cur  = document.documentElement.getAttribute('data-theme');
      const next = cur === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      localStorage.setItem('theme', next);
      themeToggle.innerHTML = next === 'dark' ? '<i class="bi bi-sun-fill"></i>' : '<i class="bi bi-moon-fill"></i>';
      // Persist to server (best-effort, fire-and-forget)
      API.put('/auth/me', { theme: next }).catch(() => {});
    });
  }

  // Sidebar collapse/expand is wired in partials/base.html's inline script
  // (handles desktop collapse + mobile drawer + localStorage persistence + icon swap).
  // Do not attach duplicate listeners here — two listeners on the same button
  // toggle the class on then off, making the button appear to do nothing.

  // Notification bell
  const notifBell     = document.getElementById('notifBell');
  const notifDropdown = document.getElementById('notifDropdown');
  if (notifBell && notifDropdown) {
    notifBell.addEventListener('click', e => {
      e.stopPropagation();
      const open = notifDropdown.style.display !== 'none';
      notifDropdown.style.display = open ? 'none' : 'block';
      if (!open) Notifications.load();
    });
    document.addEventListener('click', () => { notifDropdown.style.display = 'none'; });
  }
  document.getElementById('markAllRead')?.addEventListener('click', e => {
    e.preventDefault(); Notifications.markAllRead();
  });

  // Logout
  document.getElementById('logoutBtn')?.addEventListener('click', e => {
    e.preventDefault(); Auth.logout();
  });

  // ── Auth check ──
  const authed = await Auth.init();
  if (!authed) return;  // redirected to login

  // ── Global confidence filter ──────────────────────────────────────────────
  (function initConfFilter() {
    const slider = document.getElementById('globalConfFilter');
    const valEl  = document.getElementById('globalConfVal');
    if (!slider || !valEl) return;

    // Seed from server preference, then localStorage override
    const serverVal = Auth.user?.min_confidence_filter ?? 60;
    const stored    = parseInt(localStorage.getItem('min_confidence'), 10);
    const initial   = !isNaN(stored) ? stored : serverVal;

    window.MIN_CONFIDENCE = initial;
    slider.value    = initial;
    valEl.textContent = initial + '%';

    let _saveTimer;
    slider.addEventListener('input', function () {
      const val = parseInt(this.value, 10);
      valEl.textContent     = val + '%';
      window.MIN_CONFIDENCE = val;
      localStorage.setItem('min_confidence', val);
      clearTimeout(_saveTimer);
      _saveTimer = setTimeout(() => {
        API.put('/auth/me', { min_confidence_filter: val });
      }, 500);
    });
  })();

  // Load shared navbar data
  Notifications.load();
  Ticker.load();
  LivePrices.seed();  // bootstrap price cache before WS connects
  setInterval(() => Notifications.load(), 60000);

  // Fire ready event for page-specific scripts
  document.dispatchEvent(new Event('app:ready'));

  // ── WebSocket ──────────────────────────────────────────────────
  const token = localStorage.getItem('access_token');
  if (token && typeof io !== 'undefined') {
    try {
      const socket = io({ query: { token }, transports: ['websocket', 'polling'],
                          reconnection: true, reconnectionDelay: 2000,
                          reconnectionDelayMax: 30000, reconnectionAttempts: Infinity });

      // WebSocket status indicator
      const _wsDot   = document.getElementById('wsDot');
      const _wsLabel = document.getElementById('wsStatusLabel');
      let _wsStaleSince = null;
      let _wsStaleTimer = null;

      function _wsSetStatus(state) {
        if (!_wsDot) return;
        _wsDot.className = 'ws-dot ' + state;
        _wsLabel.textContent = state === 'live' ? 'Live' : state === 'delayed' ? 'Delayed' : 'Offline';
      }

      socket.on('connect', () => {
        _wsSetStatus('live');
        _wsStaleSince = null;
        clearTimeout(_wsStaleTimer);
        socket.emit('subscribe_all_tickers');
        socket.emit('subscribe_signals', { market: 'all' });
        socket.emit('subscribe_notifications');
      });

      socket.on('disconnect', () => {
        _wsSetStatus('offline');
        _wsStaleSince = Date.now();
      });

      socket.on('connect_error', () => {
        _wsSetStatus('offline');
      });

      socket.on('reconnect_attempt', () => {
        _wsSetStatus('delayed');
      });

      // Live price → update ribbon + notify page listeners
      socket.on('ticker_update', tick => {
        if (!tick?.symbol) return;
        LivePrices.update(tick);
        Ticker.patchItem(tick);
        // Dispatch DOM event so page components can react
        document.dispatchEvent(new CustomEvent('price:update', { detail: tick }));
      });

      socket.on('new_signal', signal => {
        Toast.show(
          `${signal.signal_type} signal: ${signal.asset} — ${signal.confidence_score?.toFixed(0)}% confidence`,
          'info', 6000
        );
        Notifications.load();
      });

      socket.on('notification', n => {
        Toast.show(n.title + ': ' + n.message, 'info', 7000);
        Notifications.load();
      });

      window._socket = socket;
    } catch (e) { /* websocket optional */ }
  }
});

// ─── ScoreBreakdown ───────────────────────────────────────────────────────────
// Renders a 5-component confidence breakdown inside any container element.
// Usage: ScoreBreakdown.render(containerEl, signalObj)
const ScoreBreakdown = (() => {
  const COMPONENTS = [
    { key: 'trend_score',    label: 'Trend',    color: '#4f8ef7' },
    { key: 'momentum_score', label: 'Momentum', color: '#a78bfa' },
    { key: 'volume_score',   label: 'Volume',   color: '#22d3ee' },
    { key: 'pattern_score',  label: 'Pattern',  color: '#f59e0b' },
    { key: 'ai_score',       label: 'AI',       color: '#22c55e' },
  ];

  function render(el, sig) {
    if (!el || !sig) return;
    const hasBreakdown = COMPONENTS.some(c => sig[c.key] != null && sig[c.key] > 0);
    if (!hasBreakdown) { el.innerHTML = ''; return; }
    el.innerHTML = `<div class="score-breakdown">${
      COMPONENTS.map(c => {
        const val = Math.min(100, Math.max(0, (sig[c.key] || 0)));
        return `<div class="score-breakdown-row">
          <span class="score-breakdown-label">${c.label}</span>
          <div class="score-breakdown-track">
            <div class="score-breakdown-fill" style="width:${val}%;background:${c.color}"></div>
          </div>
          <span class="score-breakdown-val">${val.toFixed(0)}</span>
        </div>`;
      }).join('')
    }</div>`;
  }

  return { render };
})();

// ─── SignalProgress ───────────────────────────────────────────────────────────
// Renders a live P&L progress bar (entry → target / entry → SL).
// Usage: SignalProgress.render(containerEl, signalObj)
const SignalProgress = (() => {
  function render(el, sig) {
    if (!el) return;
    const entry   = parseFloat(sig.entry_price);
    const target  = parseFloat(sig.target1);
    const sl      = parseFloat(sig.stop_loss);
    const current = parseFloat(sig.current_price || entry);
    if (!entry || !target || !sl) { el.innerHTML = ''; return; }

    const isBuy   = sig.signal_type === 'BUY';
    const range   = Math.abs(target - entry);
    if (range === 0) { el.innerHTML = ''; return; }

    const progress = isBuy
      ? Math.max(-100, Math.min(150, ((current - entry) / range) * 100))
      : Math.max(-100, Math.min(150, ((entry - current) / range) * 100));

    const isProfit  = progress >= 0;
    const pct       = Math.min(100, Math.max(0, Math.abs(progress)));
    const pnlLabel  = sig.pnl_pct != null ? `${sig.pnl_pct > 0 ? '+' : ''}${sig.pnl_pct.toFixed(2)}%` : '';

    el.innerHTML = `<div class="signal-progress-wrap">
      <div class="signal-progress-track">
        <div class="signal-progress-fill ${isProfit ? 'profit' : 'loss'}" style="width:${pct}%"></div>
      </div>
      <div class="signal-progress-label">
        <span>SL ${_fmt(sl)}</span>
        <span>${pnlLabel}</span>
        <span>T1 ${_fmt(target)}</span>
      </div>
    </div>`;
  }

  function _fmt(n) {
    const v = parseFloat(n);
    return isNaN(v) ? '—' : v >= 1000 ? v.toLocaleString(undefined,{maximumFractionDigits:2})
                         : v >= 1    ? v.toFixed(4)
                         : v.toFixed(6);
  }

  return { render };
})();

// ─── Web Push Subscription ───────────────────────────────────────────────────
async function _initPushSubscription() {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) return;
  try {
    const reg = await navigator.serviceWorker.ready;
    const existing = await reg.pushManager.getSubscription();
    if (existing) return; // already subscribed

    const resp = await fetch('/api/v1/auth/push/vapid-key');
    const { vapid_public_key } = await resp.json();
    if (!vapid_public_key) return;

    const keyBytes = Uint8Array.from(
      atob(vapid_public_key.replace(/-/g, '+').replace(/_/g, '/')),
      c => c.charCodeAt(0)
    );

    const sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: keyBytes,
    });

    await API.post('/auth/push/subscribe', { subscription: sub.toJSON() });
  } catch (err) {
    console.debug('Push subscription skipped:', err.message);
  }
}

// ─── Sparkline ────────────────────────────────────────────────────────────────
// Lightweight SVG sparkline. Use:
//   Sparkline.render(containerEl, closes, isPositive)   — sync, from array
//   Sparkline.load(containerEl, assetId, timeframe)     — async, fetches OHLCV
const Sparkline = (() => {
  const _cache = {};   // assetId+tf → closes array

  function _svg(closes, positive) {
    if (!closes || closes.length < 2) return '<span style="color:var(--text-muted);font-size:10px">—</span>';
    const W = 68, H = 28, pad = 2;
    const min = Math.min(...closes), max = Math.max(...closes);
    const range = max - min || 1;
    const pts = closes.map((v, i) => {
      const x = pad + (i / (closes.length - 1)) * (W - pad * 2);
      const y = H - pad - ((v - min) / range) * (H - pad * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');
    const color = positive ? '#10b981' : '#ef4444';
    return `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" style="display:block;overflow:visible">
      <polyline fill="none" stroke="${color}" stroke-width="1.5" stroke-linejoin="round"
                points="${pts}"/>
    </svg>`;
  }

  function render(el, closes, positive) {
    if (!el) return;
    el.innerHTML = _svg(closes, positive);
  }

  async function load(el, assetId, timeframe) {
    if (!el || !assetId) return;
    const key = `${assetId}_${timeframe}`;
    if (_cache[key]) { render(el, _cache[key].closes, _cache[key].pos); return; }
    el.innerHTML = '<span style="color:var(--text-muted);font-size:8px">···</span>';
    try {
      const data = await API.get(`/market-data/${assetId}/ohlcv`, { timeframe, limit: 24 });
      if (!data?.data?.length) return;
      const closes = data.data.map(c => c.c);
      const pos = closes[closes.length - 1] >= closes[0];
      _cache[key] = { closes, pos };
      render(el, closes, pos);
    } catch (e) { el.innerHTML = ''; }
  }

  return { render, load };
})();
