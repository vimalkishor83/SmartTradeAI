/* ═══════════════════════════════════════════════
   SmartTrade AI Platform — Core App JS
   ═══════════════════════════════════════════════ */

const PUBLIC_ROUTES = ['/login', '/register'];
const IS_PUBLIC = PUBLIC_ROUTES.includes(window.location.pathname);

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
    return true;
  },

  updateUI() {
    const u = this.user;
    if (!u) return;
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
      if (adminNav) adminNav.style.display = 'block';
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
    const data = await API.get('/notifications/', { unread: 'true' });
    if (!data) return;
    const countEl = document.getElementById('notifCount');
    const listEl  = document.getElementById('notifList');
    if (countEl) {
      countEl.textContent  = data.unread_count;
      countEl.style.display = data.unread_count > 0 ? 'flex' : 'none';
    }
    if (listEl && data.notifications?.length) {
      listEl.innerHTML = data.notifications.map(n => `
        <div class="notif-item ${n.is_read ? '' : 'unread'}">
          <div class="fw-semibold" style="font-size:13px">${n.title}</div>
          <div class="text-muted" style="font-size:12px">${n.message}</div>
          <div class="text-muted mt-1" style="font-size:11px">${formatTime(n.created_at)}</div>
        </div>`).join('');
    }
  },
  async markAllRead() {
    await API.put('/notifications/read-all');
    this.load();
  },
};

// ─── Ticker Ribbon ────────────────────────────
const Ticker = {
  async load() {
    const track = document.getElementById('tickerTrack');
    if (!track) return;
    const data = await API.get('/market-data/heatmap');
    if (!data?.heatmap?.length) {
      track.textContent = 'Market data loading...';
      return;
    }
    const html = data.heatmap.map(item => {
      const cls   = item.change_pct >= 0 ? 'up' : 'down';
      const arrow = item.change_pct >= 0 ? '▲' : '▼';
      return `<span class="ticker-item">
        <span class="ticker-symbol">${item.symbol}</span>
        <span class="ticker-price"> ${formatPrice(item.price)}</span>
        <span class="ticker-change ${cls}"> ${arrow}${Math.abs(item.change_pct).toFixed(2)}%</span>
      </span>`;
    }).join('');
    track.innerHTML = html + html;
  },
};

// ─── Formatters ───────────────────────────────
function formatPrice(price) {
  if (!price && price !== 0) return '—';
  if (price >= 10000) return price.toLocaleString('en-IN', { maximumFractionDigits: 2 });
  if (price >= 1)     return parseFloat(price).toFixed(4);
  return parseFloat(price).toFixed(6);
}

function formatTime(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('en-IN', { dateStyle: 'short', timeStyle: 'short' });
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

  // Theme toggle button
  const themeToggle = document.getElementById('themeToggle');
  if (themeToggle) {
    themeToggle.innerHTML = savedTheme === 'dark' ? '<i class="bi bi-sun-fill"></i>' : '<i class="bi bi-moon-fill"></i>';
    themeToggle.addEventListener('click', () => {
      const cur  = document.documentElement.getAttribute('data-theme');
      const next = cur === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      localStorage.setItem('theme', next);
      themeToggle.innerHTML = next === 'dark' ? '<i class="bi bi-sun-fill"></i>' : '<i class="bi bi-moon-fill"></i>';
    });
  }

  // Sidebar collapse
  const sidebar      = document.getElementById('sidebar');
  const mainWrapper  = document.getElementById('mainWrapper');
  document.getElementById('sidebarToggle')?.addEventListener('click', () => {
    sidebar?.classList.toggle('collapsed');
    mainWrapper?.classList.toggle('expanded');
  });
  document.getElementById('mobileSidebarToggle')?.addEventListener('click', () => {
    sidebar?.classList.toggle('mobile-open');
  });

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

  // Load shared navbar data
  Notifications.load();
  Ticker.load();

  // Fire ready event for page-specific scripts
  document.dispatchEvent(new Event('app:ready'));

  // WebSocket (optional — won't break if socket.io not connected)
  const token = localStorage.getItem('access_token');
  if (token && typeof io !== 'undefined') {
    try {
      const socket = io({ query: { token }, transports: ['websocket', 'polling'] });
      socket.on('connect_error', () => {});  // suppress console errors
      socket.on('new_signal', signal => {
        Toast.show(`${signal.signal_type} signal: ${signal.asset} — ${signal.confidence_score?.toFixed(0)}% confidence`, 'info');
        Notifications.load();
      });
      window._socket = socket;
    } catch (e) { /* websocket optional */ }
  }
});
