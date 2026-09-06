/* Shared public market context for the login, registration and recovery
   screens. Keeping this read-only widget in one controller prevents the auth
   pages from drifting into different data validation and timeout behavior. */
(function () {
  const safeNumber = (value, fallback = null) => {
    const number = Number(value);
    return Number.isFinite(number) ? number : fallback;
  };

  function formatPrice(value) {
    const price = safeNumber(value);
    if (price == null || price < 0) return '—';
    return price >= 1000
      ? price.toLocaleString('en-IN', { maximumFractionDigits: 2 })
      : price.toFixed(price < 10 ? 4 : 2);
  }

  async function getJson(path) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 8000);
    try {
      const response = await fetch(path, { signal: controller.signal });
      if (!response.ok) return null;
      return await response.json();
    } catch (_) {
      return null;
    } finally {
      clearTimeout(timeout);
    }
  }

  function renderUnavailable(container) {
    container.replaceChildren();
    const row = document.createElement('div');
    row.className = 'auth-ticker-row';
    const text = document.createElement('span');
    text.className = 'auth-ticker-sym text-muted';
    text.textContent = 'Live prices unavailable';
    row.appendChild(text);
    container.appendChild(row);
  }

  async function loadTicker(container) {
    const payload = await getJson('/api/v1/signals/public-ticker');
    const items = (Array.isArray(payload?.items) ? payload.items : [])
      .map(item => ({
        symbol: String(item?.symbol || 'Market').slice(0, 32),
        price: safeNumber(item?.price),
        change: safeNumber(item?.change_pct, 0),
      }))
      .filter(item => item.price != null && item.price >= 0)
      .slice(0, 3);

    if (!items.length) {
      renderUnavailable(container);
      return;
    }

    container.replaceChildren(...items.map(item => {
      const row = document.createElement('div');
      row.className = 'auth-ticker-row';
      const symbol = document.createElement('span');
      symbol.className = 'auth-ticker-sym';
      symbol.textContent = item.symbol;
      const price = document.createElement('span');
      price.className = 'auth-ticker-price';
      price.textContent = formatPrice(item.price);
      const direction = item.change > 0.05 ? 'BUY' : item.change < -0.05 ? 'SELL' : 'HOLD';
      const chip = document.createElement('span');
      chip.className = 'auth-ticker-chip ' + direction.toLowerCase();
      chip.textContent = direction;
      row.append(symbol, price, chip);
      return row;
    }));
  }

  async function loadStats() {
    const assetsEl = document.getElementById('authStatAssets');
    const timeframesEl = document.getElementById('authStatTimeframes');
    if (!assetsEl && !timeframesEl) return;
    const payload = await getJson('/api/v1/signals/public-stats');
    const formatCount = value => {
      const count = safeNumber(value);
      return count == null || count < 0 ? '—' : Math.floor(count).toLocaleString('en-IN');
    };
    if (assetsEl) assetsEl.textContent = formatCount(payload?.assets_covered);
    if (timeframesEl) timeframesEl.textContent = formatCount(payload?.timeframes_covered);
  }

  document.addEventListener('DOMContentLoaded', () => {
    const ticker = document.getElementById('authTicker');
    if (ticker) loadTicker(ticker);
    loadStats();
  });
})();
