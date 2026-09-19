(function () {
  'use strict';

  const state = { boardTimer: null, boardInFlight: false };
  const $ = (selector) => document.querySelector(selector);

  function safeNumber(value, fallback = null) {
    const number = Number(value);
    return Number.isFinite(number) ? number : fallback;
  }

  function formatPrice(value) {
    const number = safeNumber(value);
    if (number == null || number < 0) return '--';
    return number >= 1000 ? number.toLocaleString('en-IN', { maximumFractionDigits: 2 }) : number.toFixed(number < 10 ? 4 : 2);
  }

  async function getJson(path, timeoutMs = 8000) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(path, { signal: controller.signal, headers: { Accept: 'application/json' } });
      if (!response.ok) throw new Error(`Request failed: ${response.status}`);
      return await response.json();
    } finally {
      window.clearTimeout(timeout);
    }
  }

  function setFreshness(element, label) {
    if (element) element.textContent = label;
  }

  async function loadTicker() {
    const node = $('[data-public-ticker]');
    if (!node) return;
    try {
      const payload = await getJson('/api/v1/signals/public-ticker');
      const items = (Array.isArray(payload?.items) ? payload.items : []).slice(0, 5);
      node.replaceChildren(...(items.length ? items.map((item) => {
        const span = document.createElement('span');
        const change = safeNumber(item.change_pct, 0);
        span.textContent = `${String(item.symbol || 'Market').slice(0, 18)} ${formatPrice(item.price)} ${change > 0.05 ? '+' : ''}${change.toFixed(2)}%`;
        span.className = change >= 0 ? 'positive' : 'negative';
        return span;
      }) : [Object.assign(document.createElement('span'), { textContent: 'Live prices unavailable right now' })]));
      setFreshness($('[data-public-clock]'), payload?.as_of ? `Updated ${new Date(payload.as_of).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : 'Updated just now');
    } catch (_) {
      node.replaceChildren(Object.assign(document.createElement('span'), { textContent: 'Market data temporarily unavailable' }));
      setFreshness($('[data-public-clock]'), 'Data unavailable');
    }
  }

  function renderBoard(rows) {
    const body = $('#publicSignalRows');
    if (!body) return;
    const actionable = rows.filter((row) => ['BUY', 'SELL'].includes(String(row?.signal_type || '').toUpperCase()) && safeNumber(row?.entry_price) != null);
    if (!actionable.length) {
      body.innerHTML = '<tr><td colspan="9" class="public-table-state">No actionable setup is available right now. The engine is waiting for cleaner confirmation.</td></tr>';
      return;
    }
    body.replaceChildren(...actionable.slice(0, 8).map((row) => {
      const signal = String(row.signal_type).toUpperCase();
      const tr = document.createElement('tr');
      const values = [row.asset || 'Unknown', row.market || 'Market', signal, row.timeframe || '--', `${Math.round(safeNumber(row.confidence_score, 0))}%`, formatPrice(row.entry_price), formatPrice(row.stop_loss), formatPrice(row.target1), 'Fresh snapshot'];
      values.forEach((value, index) => {
        const td = document.createElement('td');
        if (index === 2) {
          const badge = document.createElement('span');
          badge.className = `public-signal-badge ${signal === 'BUY' ? 'buy' : 'sell'}`;
          badge.textContent = signal;
          td.appendChild(badge);
        } else if (index === 0) {
          const strong = document.createElement('strong');
          strong.textContent = String(value);
          td.appendChild(strong);
        } else {
          td.textContent = String(value);
        }
        tr.appendChild(td);
      });
      return tr;
    }));
  }

  async function loadBoard() {
    if (state.boardInFlight || document.visibilityState === 'hidden') return;
    const status = $('#publicSignalStatus');
    const updated = $('#publicSignalUpdated');
    state.boardInFlight = true;
    try {
      const payload = await getJson('/api/v1/signals/public-board');
      renderBoard(Array.isArray(payload?.rows) ? payload.rows : []);
      if (status) status.textContent = 'Public setups are read-only and intentionally limited.';
      setFreshness(updated, payload?.as_of ? `Updated ${new Date(payload.as_of).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : 'Updated just now');
    } catch (_) {
      if (status) status.textContent = 'Public signal preview is temporarily unavailable.';
      if (updated) updated.textContent = 'Retrying when available';
      renderBoard([]);
    } finally {
      state.boardInFlight = false;
    }
  }

  async function loadPerformance() {
    const node = $('[data-public-performance]');
    if (!node) return;
    try {
      const data = await getJson('/api/v1/signals/public-performance');
      const resultValues = data?.available ? [`${safeNumber(data.win_rate, 0).toFixed(1)}%`, safeNumber(data.profit_factor, 0).toFixed(2), `${safeNumber(data.avg_pnl_pct, 0) >= 0 ? '+' : ''}${safeNumber(data.avg_pnl_pct, 0).toFixed(3)}%`, String(data.closed_trades || 0)] : ['--', '--', '--', String(data?.closed_trades || 0)];
      const values = node.hasAttribute('data-public-results') ? resultValues : (data?.available ? [resultValues[0], resultValues[1], resultValues[3], data.period || 'All available closed records'] : ['--', '--', String(data?.closed_trades || 0), `Sample building; minimum ${data?.minimum_sample || 30}`]);
      const valueNodes = node.querySelectorAll('b, strong');
      valueNodes.forEach((item, index) => { item.textContent = values[index]; });
      if (node.hasAttribute('data-public-results')) {
        node.querySelectorAll('[data-result-value]').forEach((item) => { item.textContent = resultValues[['win-rate', 'profit-factor', 'avg-pnl', 'closed-trades'].indexOf(item.dataset.resultValue)] || '--'; });
        node.querySelectorAll('[data-result-note]').forEach((item) => { item.textContent = data?.available ? `Closed-signal sample · ${data.period || 'all available records'}` : `Sample building · minimum ${data?.minimum_sample || 30} decisive records`; });
        const period = node.querySelector('[data-result-period]');
        const updated = node.querySelector('[data-result-updated]');
        if (period) period.textContent = data?.period || 'all available closed records';
        if (updated) updated.textContent = data?.as_of ? new Date(data.as_of).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : 'unavailable';
      }
    } catch (_) {
      node.querySelectorAll('b, strong').forEach((item) => { item.textContent = '--'; });
      node.querySelectorAll('[data-result-note]').forEach((item) => { item.textContent = 'Performance data temporarily unavailable'; });
    }
  }

  async function loadSocialLinks() {
    const node = $('[data-public-social]');
    if (!node) return;
    try {
      const payload = await getJson('/api/v1/public/site-config');
      const labels = { facebook: 'Facebook', instagram: 'Instagram', x: 'X', linkedin: 'LinkedIn', youtube: 'YouTube', telegram: 'Telegram', discord: 'Discord' };
      const links = Object.entries(payload?.social_links || {}).filter(([key, value]) => labels[key] && typeof value === 'string' && value);
      node.replaceChildren(...links.map(([key, value]) => {
        const link = document.createElement('a');
        link.href = value;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.textContent = labels[key];
        return link;
      }));
      node.hidden = !links.length;
    } catch (_) {
      node.hidden = true;
    }
  }

  function startSignalBoard() {
    loadTicker();
    loadBoard();
    state.boardTimer = window.setInterval(() => { loadTicker(); loadBoard(); }, 30000);
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') { loadTicker(); loadBoard(); }
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    const menuToggle = $('.public-menu-toggle');
    const menu = $('#publicMenu');
    const currentPath = window.location.pathname.replace(/\/$/, '') || '/home';
    document.querySelectorAll('#publicMenu a[href^="/"]').forEach((link) => {
      const linkPath = new URL(link.href, window.location.origin).pathname.replace(/\/$/, '') || '/home';
      if (linkPath === currentPath) link.setAttribute('aria-current', 'page');
    });
    if (menuToggle && menu) {
      menuToggle.addEventListener('click', () => {
        const open = menu.classList.toggle('open');
        menuToggle.setAttribute('aria-expanded', String(open));
        menuToggle.textContent = open ? 'Close' : 'Menu';
      });
      menu.addEventListener('click', (event) => {
        if (!event.target.closest('a')) return;
        menu.classList.remove('open');
        menuToggle.setAttribute('aria-expanded', 'false');
        menuToggle.textContent = 'Menu';
      });
    }
    loadTicker();
    loadPerformance();
    loadSocialLinks();
  });

  window.PublicPages = { startSignalBoard };
})();
