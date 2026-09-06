/* ═══════════════════════════════════════════════
   Delta Scanner — multi-timeframe EMA + Supertrend
   ═══════════════════════════════════════════════ */
const dsSet = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = (v ?? '—'); };

/* ── Generic click-to-sort for smart-table headers ───────────
   Every table on this page is server-ordered (volume, RSI, etc.) with no
   way to look at it any other way — e.g. the BUY/SELL scan tables always
   show highest-to-lowest volume, so scanning for the best Score or tightest
   EMA Dist% meant reading the whole table by eye. This wires click-to-sort
   onto a table's <thead>, with a 3-state cycle per column (asc → desc →
   back to the server's original order) plus an explicit Reset control,
   without touching how any table's data is fetched or normally rendered. */
const dsSortRegistry = Object.create(null); // tableId -> { original, current, state: {col, dir}|null, render }

function dsInitSortable(tableId, theadSelector, tbodyId, columns, render) {
  const thead = document.querySelector(theadSelector);
  if (!thead) return;
  const headerRow = thead.querySelector('tr');
  const ths = Array.from(headerRow.children);

  dsSortRegistry[tableId] = { original: [], current: [], state: null, render, tbodyId, thead };

  ths.forEach((th, i) => {
    const col = columns[i];
    if (!col) return; // not sortable (rank #, free-text "Why", etc.)
    th.classList.add('sortable-th');
    th.setAttribute('role', 'button');
    th.setAttribute('tabindex', '0');
    const label = th.textContent;
    th.innerHTML = `<span>${label}</span><i class="bi bi-arrow-down-up sort-th-icon"></i>`;
    const activate = () => dsSortBy(tableId, i, col);
    th.addEventListener('click', activate);
    th.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); activate(); } });
  });
}

function dsSetSortData(tableId, rows) {
  const reg = dsSortRegistry[tableId];
  if (!reg) return;
  reg.original = rows;
  // A fresh fetch (new scan / rescan) should show newest data in the
  // server's own order, not silently keep re-applying a stale sort.
  reg.state = null;
  reg.current = rows;
  dsUpdateSortIcons(tableId);
  reg.render(reg.current);
}

function dsSortBy(tableId, colIndex, accessor) {
  const reg = dsSortRegistry[tableId];
  if (!reg) return;
  let dir = 'asc';
  if (reg.state && reg.state.col === colIndex) {
    dir = reg.state.dir === 'asc' ? 'desc' : (reg.state.dir === 'desc' ? null : 'asc');
  }

  if (dir === null) {
    reg.state = null;
    reg.current = reg.original;
  } else {
    reg.state = { col: colIndex, dir };
    reg.current = [...reg.original].sort((a, b) => {
      let va = accessor(a), vb = accessor(b);
      const aNull = va == null, bNull = vb == null;
      if (aNull && bNull) return 0;
      if (aNull) return 1;   // missing values always sort last, regardless of direction
      if (bNull) return -1;
      if (typeof va === 'string') { va = va.toLowerCase(); vb = vb.toLowerCase(); }
      if (va < vb) return dir === 'asc' ? -1 : 1;
      if (va > vb) return dir === 'asc' ? 1 : -1;
      return 0;
    });
  }
  dsUpdateSortIcons(tableId);
  reg.render(reg.current);
}

function dsResetSort(tableId) {
  const reg = dsSortRegistry[tableId];
  if (!reg) return;
  reg.state = null;
  reg.current = reg.original;
  dsUpdateSortIcons(tableId);
  reg.render(reg.current);
}

function dsUpdateSortIcons(tableId) {
  const reg = dsSortRegistry[tableId];
  if (!reg || !reg.thead) return;
  reg.thead.querySelectorAll('th').forEach((th, i) => {
    if (!th.classList.contains('sortable-th')) return;
    th.classList.toggle('sort-active', !!reg.state && reg.state.col === i);
    const icon = th.querySelector('.sort-th-icon');
    if (!icon) return;
    icon.className = 'bi sort-th-icon ' + (
      reg.state && reg.state.col === i
        ? (reg.state.dir === 'asc' ? 'bi-arrow-up' : 'bi-arrow-down')
        : 'bi-arrow-down-up'
    );
  });
}

function dsAbbr(n) {
  if (n == null || isNaN(n)) return '—';
  const abs = Math.abs(n);
  if (abs >= 1e9) return (n / 1e9).toFixed(2) + 'B';
  if (abs >= 1e6) return (n / 1e6).toFixed(2) + 'M';
  if (abs >= 1e3) return (n / 1e3).toFixed(2) + 'K';
  return (+n).toFixed(2);
}

function dsPrice(n) {
  if (n == null || isNaN(n)) return '—';
  const v = +n;
  const decimals = v >= 100 ? 2 : v >= 1 ? 4 : 6;
  return v.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

function dsSupertrendBadge(dir) {
  const up = dir === 'bullish';
  return `<span style="color:${up ? 'var(--green)' : 'var(--red)'};font-weight:700">${up ? '▲' : '▼'} ${STSafe.html(dir)}</span>`;
}

// Shared across the Common Coins status panel AND the All Coins BUY/SELL
// tables (keyed by symbol, not by which table rendered it) so a coin
// appearing in both places tracks one continuous tick history rather than
// two independent ones.
const dsLastPrice = new Map();

function dsPriceTickClass(symbol, price) {
  const prev = dsLastPrice.get(symbol);
  dsLastPrice.set(symbol, price);
  if (prev == null || price == null) return '';
  if (price > prev) return 'mtf-cell-bull';
  if (price < prev) return 'mtf-cell-bear';
  return 'mtf-cell-mixed'; // unchanged since the last refresh -> amber, not a false green/red
}

const dsSupertrendCellClass = (dir) => (dir === 'bullish' ? 'mtf-cell-bull' : 'mtf-cell-bear');

// Background communicates the trend (green = price above the Supertrend
// line = bullish, red = below = bearish); the cell itself shows the actual
// Supertrend line price so the trend can be read/verified, not just trusted.
function dsSupertrendCell(dir, value) {
  return `<td class="num ${dsSupertrendCellClass(dir)}">${dsPrice(value)}</td>`;
}

// Green if price sits above this EMA (bullish for that average), red if
// below, amber on an exact touch.
function dsEmaCellClass(price, emaVal) {
  if (price == null || emaVal == null) return '';
  if (price > emaVal) return 'mtf-cell-bull';
  if (price < emaVal) return 'mtf-cell-bear';
  return 'mtf-cell-mixed';
}

function dsVolTrendBadge(trend) {
  const clr = trend === 'increasing' ? 'var(--green)' : trend === 'declining' ? 'var(--red)' : 'var(--text-muted)';
  return `<span style="color:${clr}">${STSafe.html(trend)}</span>`;
}

function dsTierBadge(tier) {
  const meta = {
    strong: { clr: 'var(--green)', bg: 'rgba(16,185,129,.14)' },
    moderate: { clr: 'var(--yellow)', bg: 'rgba(245,158,11,.14)' },
    weak: { clr: 'var(--text-muted)', bg: 'rgba(148,163,184,.12)' },
  }[tier] || { clr: 'var(--text-muted)', bg: 'transparent' };
  return `<span class="badge-tag" style="color:${meta.clr};background:${meta.bg};border-color:${meta.clr}55;text-transform:capitalize">${STSafe.html(tier)}</span>`;
}

function dsRenderTable(bodyId, results) {
  const tb = document.getElementById(bodyId);
  if (!tb) return;
  if (!results.length) {
    tb.innerHTML = '<tr><td colspan="15" class="text-center text-muted py-4"><i class="bi bi-inbox d-block mb-2" style="font-size:22px;opacity:.4"></i>No qualifying contracts</td></tr>';
    return;
  }
  tb.innerHTML = results.map((r, i) => {
    const ema = r.ema || {};
    const reasons = Array.isArray(r.reasons) ? r.reasons.map(String) : [];
    const priceCls = dsPriceTickClass(r.symbol, r.current_price);
    const zoneDistance = Number(r.ema_zone_distance_pct);
    return `
    <tr>
      <td>${i + 1}</td>
      <td><span class="asset-cell-name">${STSafe.html(r.symbol)}</span></td>
      <td class="text-muted small">${STSafe.html(r.short_name || '')}</td>
      <td class="num ${priceCls}">${dsPrice(r.current_price)}</td>
      <td class="num">${dsAbbr(r.volume_24h)}</td>
      <td class="num ${dsEmaCellClass(r.current_price, ema.ema9)}">${dsPrice(ema.ema9)}</td>
      <td class="num ${dsEmaCellClass(r.current_price, ema.ema21)}">${dsPrice(ema.ema21)}</td>
      <td class="num ${dsEmaCellClass(r.current_price, ema.ema50)}">${dsPrice(ema.ema50)}</td>
      <td class="num">${Number.isFinite(zoneDistance) ? zoneDistance.toFixed(2) : '—'}%</td>
      ${dsSupertrendCell(r.supertrend_15m, r.supertrend_15m_value)}
      ${dsSupertrendCell(r.supertrend_1h, r.supertrend_1h_value)}
      <td>${dsVolTrendBadge(r.volume_trend)}</td>
      <td class="num">${r.score}/${r.max_score}</td>
      <td>${dsTierBadge(r.tier)}</td>
      <td class="text-muted small" style="max-width:260px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="${STSafe.html(reasons.join(' · '))}">${STSafe.html(reasons[0] || '')}</td>
    </tr>
  `;
  }).join('');
}

/* ═══════════════════════════════════════════════
   Common Coins — configurable live status panel
   (unfiltered: shows every configured symbol's
   current bullish/bearish/mixed read, not just
   ones that qualify as a full BUY/SELL scan hit)
   ═══════════════════════════════════════════════ */
const mtfStatusCellClass = (status) =>
  status === 'bullish' ? 'mtf-cell-bull' : status === 'bearish' ? 'mtf-cell-bear' : 'mtf-cell-mixed';

function mtfRenderCommonRows(results) {
  const tb = document.getElementById('commonBody');
  if (!tb) return;
  if (!results.length) {
    tb.innerHTML = `<tr><td colspan="11" class="text-center text-muted py-4"><i class="bi bi-inbox d-block mb-2" style="font-size:22px;opacity:.4"></i>No data</td></tr>`;
    return;
  }
  tb.innerHTML = results.map((r) => {
    const ema = r.ema || {};
    const changePct = Number(r.change_pct);
    const up = Number.isFinite(changePct) && changePct >= 0;
    return `
    <tr>
      <td><span class="asset-cell-name">${STSafe.html(r.symbol)}</span></td>
      <td class="text-muted small">${STSafe.html(r.short_name || '')}</td>
      <td class="num ${dsPriceTickClass(r.symbol, r.current_price)}">${dsPrice(r.current_price)}</td>
      <td class="num" style="color:${up ? 'var(--green)' : 'var(--red)'};font-weight:700">${up ? '+' : ''}${Number.isFinite(changePct) ? changePct.toFixed(2) : '—'}%</td>
      <td class="num ${dsEmaCellClass(r.current_price, ema.ema9)}">${dsPrice(ema.ema9)}</td>
      <td class="num ${dsEmaCellClass(r.current_price, ema.ema21)}">${dsPrice(ema.ema21)}</td>
      <td class="num ${dsEmaCellClass(r.current_price, ema.ema50)}">${dsPrice(ema.ema50)}</td>
      ${dsSupertrendCell(r.supertrend_15m, r.supertrend_15m_value)}
      ${dsSupertrendCell(r.supertrend_1h, r.supertrend_1h_value)}
      <td>${dsVolTrendBadge(r.volume_trend)}</td>
      <td class="${mtfStatusCellClass(r.status)}" style="text-transform:capitalize">${STSafe.html(r.status)}</td>
    </tr>`;
  }).join('');
}

async function mtfLoadCommon() {
  if (mtfCommonInFlight) return;
  mtfCommonInFlight = true;
  let data = null;
  try {
    data = await API.get('/scanner/delta-mtf/status').catch(() => null);
  } finally {
    mtfCommonInFlight = false;
  }
  if (!data) { dsSet('commonMeta', 'Failed to load'); return; }
  const results = Array.isArray(data.results) ? data.results : [];
  dsSet('commonMeta', data.generated_at ? 'refreshed ' + new Date(data.generated_at * 1000).toLocaleTimeString() : '');
  if (!results.length) {
    document.getElementById('commonBody').innerHTML = `<tr><td colspan="11" class="text-center text-muted py-4"><i class="bi bi-inbox d-block mb-2" style="font-size:22px;opacity:.4"></i>${STSafe.html(data.message || 'No data')}</td></tr>`;
    return;
  }
  dsSetSortData('common', results);
}

const MTF_STATUS_RANK = { bullish: 3, mixed: 2, bearish: 1 };
const DS_COMMON_COLUMNS = [
  r => r.symbol,
  r => r.short_name || '',
  r => r.current_price,
  r => r.change_pct,
  r => r.ema?.ema9,
  r => r.ema?.ema21,
  r => r.ema?.ema50,
  r => r.supertrend_15m_value,
  r => r.supertrend_1h_value,
  r => r.volume_trend,
  r => MTF_STATUS_RANK[r.status] ?? 0,
];

let mtfCommonTimer = null;
let mtfCommonInFlight = false;
function mtfStartCommonAutoRefresh() {
  if (mtfCommonTimer) clearInterval(mtfCommonTimer);
  // Cheap call (a handful of symbols, ~8 by default), so this refreshes
  // faster than the 220-symbol All Coins scan (dsStartScanAutoRefresh,
  // 5 min — matched to its backend cache TTL).
  mtfCommonTimer = setInterval(mtfLoadCommon, 30000);
}

/* ── Configure Common Coins — search-and-select modal ──────────── */
let ccAllSymbols = null; // cached {symbol, short_name}[] for the full live universe
let ccSelected = new Set();
const CC_MAX_SYMBOLS = 30; // mirrors the server-side cap in the watchlist POST handler

async function ccEnsureSymbols() {
  if (ccAllSymbols) return ccAllSymbols;
  const data = await API.get('/scanner/delta-mtf/symbols').catch(() => null);
  ccAllSymbols = Array.isArray(data?.symbols)
    ? data.symbols
      .filter(r => r && typeof r.symbol === 'string')
      .map(r => ({ symbol: r.symbol, short_name: typeof r.short_name === 'string' ? r.short_name : r.symbol }))
    : [];
  return ccAllSymbols;
}

function ccRenderChips() {
  const wrap = document.getElementById('ccSelectedChips');
  document.getElementById('ccSelectedCount').textContent = ccSelected.size;
  if (!ccSelected.size) {
    wrap.innerHTML = '<span class="text-muted small">No coins selected yet — search below to add.</span>';
    return;
  }
  wrap.innerHTML = Array.from(ccSelected).map((s) => `
    <span class="badge-tag d-inline-flex align-items-center gap-1" style="cursor:pointer" data-remove="${STSafe.html(s)}" title="Remove">
      ${STSafe.html(s)}<i class="bi bi-x"></i>
    </span>`).join('');
  wrap.querySelectorAll('[data-remove]').forEach((el) => {
    el.addEventListener('click', () => {
      ccSelected.delete(el.dataset.remove);
      ccRenderChips();
      ccRenderResults(document.getElementById('ccSearchInput').value);
    });
  });
}

function ccRenderResults(query) {
  const list = ccAllSymbols || [];
  const q = (query || '').trim().toUpperCase();
  // "old records" — coins already selected are shown pinned at the top of
  // an unfiltered search, so opening the picker always makes the current
  // configuration visible at a glance, not just whatever the query matches.
  const filtered = q
    ? list.filter((r) => r.symbol.includes(q) || r.short_name.toUpperCase().includes(q))
    : [...list].sort((a, b) => (ccSelected.has(b.symbol) ? 1 : 0) - (ccSelected.has(a.symbol) ? 1 : 0));

  const wrap = document.getElementById('ccSearchResults');
  if (!filtered.length) {
    wrap.innerHTML = '<div class="text-muted small py-3 text-center">No matches</div>';
    return;
  }
  wrap.innerHTML = filtered.slice(0, 150).map((r) => {
    const checked = ccSelected.has(r.symbol);
    return `
    <div class="d-flex justify-content-between align-items-center py-2 px-1 cc-row" data-symbol="${STSafe.html(r.symbol)}" style="cursor:pointer;border-bottom:1px solid var(--border)">
      <div><span class="asset-cell-name">${STSafe.html(r.symbol)}</span><span class="text-muted small ms-2">${STSafe.html(r.short_name)}</span></div>
      <i class="bi ${checked ? 'bi-check-circle-fill text-green' : 'bi-circle text-muted'}"></i>
    </div>`;
  }).join('');
  wrap.querySelectorAll('.cc-row').forEach((el) => {
    el.addEventListener('click', () => {
      const sym = el.dataset.symbol;
      if (ccSelected.has(sym)) {
        ccSelected.delete(sym);
      } else {
        if (ccSelected.size >= CC_MAX_SYMBOLS) { Toast.show(`Max ${CC_MAX_SYMBOLS} coins`, 'error'); return; }
        ccSelected.add(sym);
      }
      ccRenderChips();
      ccRenderResults(document.getElementById('ccSearchInput').value);
    });
  });
}

async function mtfConfigure() {
  await ccEnsureSymbols();
  const cfg = await API.get('/scanner/delta-mtf/watchlist').catch(() => null);
  const allowed = new Set(ccAllSymbols.map(r => r.symbol));
  ccSelected = new Set(Array.isArray(cfg?.symbols) ? cfg.symbols.filter(s => allowed.has(s)) : []);
  document.getElementById('ccSearchInput').value = '';
  ccRenderChips();
  ccRenderResults('');
  new bootstrap.Modal(document.getElementById('commonCoinsModal')).show();
}

let ccSaveInFlight = false;
async function ccSave() {
  if (ccSaveInFlight) return;
  ccSaveInFlight = true;
  let res = null;
  try {
    res = await API.post('/scanner/delta-mtf/watchlist', { symbols: Array.from(ccSelected) }).catch(() => null);
  } finally {
    ccSaveInFlight = false;
  }
  if (!res || res.error) { Toast.show(res?.error || 'Failed to save', 'error'); return; }
  bootstrap.Modal.getInstance(document.getElementById('commonCoinsModal'))?.hide();
  Toast.show('Common Coins updated', 'success');
  mtfLoadCommon();
}

function mtfSetSubTab(tab) {
  document.getElementById('mtfCommonPanel').style.display = tab === 'common' ? '' : 'none';
  document.getElementById('mtfAllPanel').style.display = tab === 'all' ? '' : 'none';
  document.querySelectorAll('#mtfSubTabs .scan-chip').forEach((b) => b.classList.toggle('active', b.dataset.subtab === tab));
}

function dsSetDirTab(dir) {
  document.getElementById('buySection').style.display = dir === 'buy' ? '' : 'none';
  document.getElementById('sellSection').style.display = dir === 'sell' ? '' : 'none';
  document.querySelectorAll('#dsDirTabs .scan-chip').forEach((b) => b.classList.toggle('active', b.dataset.dir === dir));
}

let dsScanInFlight = false;
async function dsLoadScan(forceRefresh) {
  if (dsScanInFlight) return;
  dsScanInFlight = true;
  const btn = document.getElementById('rescanBtn');
  if (btn) { btn.disabled = true; btn.innerHTML = '<i class="bi bi-hourglass-split me-1"></i>Scanning…'; }

  const path = '/scanner/delta-mtf' + (forceRefresh ? '?force_refresh=1' : '');
  let data = null;
  try {
    data = await API.get(path).catch(() => null);
  } finally {
    dsScanInFlight = false;
  }
  if (btn) { btn.disabled = false; btn.innerHTML = '<i class="bi bi-arrow-repeat me-1"></i>Rescan'; }

  if (!data) {
    dsSet('scanMeta', 'Failed to load scan');
    return;
  }

  const buy = Array.isArray(data.buy) ? data.buy : [];
  const sell = Array.isArray(data.sell) ? data.sell : [];

  dsSet('kpiScanned', data.contracts_scanned ?? '—');
  dsSet('kpiBuy', buy.length);
  dsSet('kpiBuyStrong', buy.filter(r => r.tier === 'strong').length + ' strong');
  dsSet('kpiSell', sell.length);
  dsSet('kpiSellStrong', sell.filter(r => r.tier === 'strong').length + ' strong');
  dsSet('kpiUpdated', data.generated_at ? new Date(data.generated_at * 1000).toLocaleTimeString() : '—');
  dsSet('scanMeta', data.generated_at ? 'Generated ' + new Date(data.generated_at * 1000).toLocaleTimeString() : '');
  dsSet('buyCount', buy.length);
  dsSet('sellCount', sell.length);

  const msgCard = document.getElementById('scanMessageCard');
  if (data.message && msgCard) {
    document.getElementById('scanMessageText').textContent = data.message;
    msgCard.style.display = '';
  } else if (msgCard) {
    msgCard.style.display = 'none';
  }

  dsSetSortData('buy', buy);
  dsSetSortData('sell', sell);
}

// Column accessors for the BUY/SELL scan tables, in header order — null
// marks a column as not sortable (row rank, and the free-text "Why").
// Supertrend columns sort by the same numeric value shown in the cell;
// Tier sorts by conviction rank, not alphabetically (moderate < strong
// alphabetically, but that's backwards for what the column means).
const DS_TIER_RANK = { strong: 3, moderate: 2, weak: 1 };
const DS_BUY_SELL_COLUMNS = [
  null,                                   // #
  r => r.symbol,                          // Symbol
  r => r.short_name || '',                // Name
  r => r.current_price,                   // Price
  r => r.volume_24h,                      // Vol 24h
  r => r.ema?.ema9,                       // 5m 9EMA
  r => r.ema?.ema21,                      // 5m 21EMA
  r => r.ema?.ema50,                      // 5m 50EMA
  r => +r.ema_zone_distance_pct,          // EMA Dist%
  r => r.supertrend_15m_value,            // 15m ST
  r => r.supertrend_1h_value,             // 1h ST
  r => r.volume_trend,                    // Vol Trend
  r => r.score,                           // Score
  r => DS_TIER_RANK[r.tier] ?? 0,         // Tier
  null,                                   // Why
];

function dsInitScanTableSorting() {
  dsInitSortable('buy', '#buySection thead', 'buyBody', DS_BUY_SELL_COLUMNS, rows => dsRenderTable('buyBody', rows));
  dsInitSortable('sell', '#sellSection thead', 'sellBody', DS_BUY_SELL_COLUMNS, rows => dsRenderTable('sellBody', rows));
  document.getElementById('buyResetSort')?.addEventListener('click', () => dsResetSort('buy'));
  document.getElementById('sellResetSort')?.addEventListener('click', () => dsResetSort('sell'));

  dsInitSortable('common', '#mtfCommonPanel thead', 'commonBody', DS_COMMON_COLUMNS, rows => mtfRenderCommonRows(rows));
  document.getElementById('commonResetSort')?.addEventListener('click', () => dsResetSort('common'));

  dsInitSortable('screener', '#screenerTableWrap thead', 'screenerBody', DS_SCREENER_COLUMNS, rows => scRenderResultsTable(rows));
  document.getElementById('screenerResetSort')?.addEventListener('click', () => dsResetSort('screener'));
}

// Matches the backend's 330s scan cache (see /scanner/delta-mtf) and the
// "auto-refreshes every 5 min" label on the KPI card — without this, the
// BUY/SELL tables only ever render once (on page load), so the price-tick
// background coloring never has a prior price to compare against.
let dsScanTimer = null;
function dsStartScanAutoRefresh() {
  if (dsScanTimer) clearInterval(dsScanTimer);
  dsScanTimer = setInterval(() => dsLoadScan(false), 300000);
}

/* ═══════════════════════════════════════════════
   Market Screener mode — flexible WHERE-condition
   builder over price/24h/volume/RSI/funding/OI
   ═══════════════════════════════════════════════ */
let scAssetType = 'perpetual_futures';
let scCombinator = 'AND';
let scConditions = [];
let scFields = null;   // {field_key: label} — loaded from the API's first response
let scOperators = null;
const SC_ASSET_TYPES = new Set(['perpetual_futures', 'spot', 'move_options']);
const SC_OPERATOR_LABEL = { '>': '>', '<': '<', '>=': '≥', '<=': '≤', '==': '=', between: 'between' };

function scNewCondition() {
  const firstField = scFields ? Object.keys(scFields)[0] : 'rsi_14';
  return { field: firstField, op: '>', value: '', value2: '', abs: false };
}

function scRenderConditions() {
  const wrap = document.getElementById('screenerConditions');
  if (!wrap) return;
  if (!scConditions.length) {
    wrap.innerHTML = '<div class="text-muted small py-2">No conditions yet — every coin matches. Add one or pick a preset above.</div>';
    return;
  }
  const fieldOpts = Object.entries(scFields || {}).map(([k, label]) => `<option value="${STSafe.html(k)}">${STSafe.html(label)}</option>`).join('');
  const opOpts = (scOperators || []).map((op) => `<option value="${STSafe.html(op)}">${STSafe.html(SC_OPERATOR_LABEL[op] || op)}</option>`).join('');

  wrap.innerHTML = scConditions.map((c, i) => `
    <div class="d-flex align-items-center gap-2 mb-2 flex-wrap" data-cond-row="${i}">
      <span class="text-muted small" style="min-width:44px">${i === 0 ? 'where' : scCombinator.toLowerCase()}</span>
      <select class="form-select form-select-sm sc-field" style="width:auto" data-i="${i}">${fieldOpts}</select>
      <select class="form-select form-select-sm sc-op" style="width:auto" data-i="${i}">${opOpts}</select>
      <input type="number" class="form-control form-control-sm sc-value" style="width:110px" placeholder="value" data-i="${i}">
      <input type="number" class="form-control form-control-sm sc-value2" style="width:110px;display:${c.op === 'between' ? '' : 'none'}" placeholder="and…" data-i="${i}">
      ${c.field === 'change_24h_pct' ? `<label class="text-muted small d-flex align-items-center gap-1"><input type="checkbox" class="sc-abs" data-i="${i}"${c.abs ? ' checked' : ''}> |abs|</label>` : ''}
      <button class="btn btn-sm btn-outline-secondary sc-remove" data-i="${i}" title="Remove"><i class="bi bi-x-lg"></i></button>
    </div>
  `).join('');

  // Wire selects/inputs after innerHTML swap (event delegation would also work,
  // but this mirrors the direct-listener style already used elsewhere on this page).
  wrap.querySelectorAll('.sc-field').forEach((el) => {
    el.value = scConditions[+el.dataset.i].field;
    el.addEventListener('change', (e) => { scConditions[+e.target.dataset.i].field = e.target.value; scConditions[+e.target.dataset.i].abs = false; scRenderConditions(); });
  });
  wrap.querySelectorAll('.sc-op').forEach((el) => {
    el.value = scConditions[+el.dataset.i].op;
    el.addEventListener('change', (e) => { scConditions[+e.target.dataset.i].op = e.target.value; scRenderConditions(); });
  });
  wrap.querySelectorAll('.sc-value').forEach((el) => {
    el.value = scConditions[+el.dataset.i].value;
    el.addEventListener('input', (e) => { scConditions[+e.target.dataset.i].value = e.target.value; });
  });
  wrap.querySelectorAll('.sc-value2').forEach((el) => {
    el.value = scConditions[+el.dataset.i].value2;
    el.addEventListener('input', (e) => { scConditions[+e.target.dataset.i].value2 = e.target.value; });
  });
  wrap.querySelectorAll('.sc-abs').forEach((el) => {
    el.addEventListener('change', (e) => { scConditions[+e.target.dataset.i].abs = e.target.checked; });
  });
  wrap.querySelectorAll('.sc-remove').forEach((el) => {
    el.addEventListener('click', (e) => {
      const i = +e.currentTarget.dataset.i;
      scConditions.splice(i, 1);
      scRenderConditions();
    });
  });
}

// Resolved lazily on first star-click and cached for the rest of the page
// session — every "add to watchlist" from the screener goes to this one
// list rather than asking the user to pick a watchlist for every symbol.
let scDefaultWatchlistId = null;

async function scResolveDefaultWatchlist() {
  if (scDefaultWatchlistId != null) return scDefaultWatchlistId;
  const lists = await API.get('/watchlist/').catch(() => null);
  const existing = lists?.watchlists?.[0];
  const existingId = STSafe.assetId(existing?.id);
  if (existingId) { scDefaultWatchlistId = existingId; return scDefaultWatchlistId; }
  const created = await API.post('/watchlist/', { name: 'My Watchlist' }).catch(() => null);
  scDefaultWatchlistId = STSafe.assetId(created?.id) || null;
  return scDefaultWatchlistId;
}

const scNotify = (message, type = 'info') => {
  if (typeof Toast !== 'undefined') Toast.show(message, type);
  else if (typeof toast === 'function') toast(message, type);
};

async function scAddToWatchlist(symbol, description, iconEl) {
  if (!iconEl || iconEl.classList.contains('bi-hourglass-split')) return;
  iconEl.classList.remove('bi-star', 'bi-star-fill');
  iconEl.classList.add('bi-hourglass-split');
  const wlId = await scResolveDefaultWatchlist();
  if (!wlId) {
    iconEl.classList.remove('bi-hourglass-split');
    iconEl.classList.add('bi-star');
    scNotify('Could not create a watchlist', 'error');
    return;
  }
  const res = await API.post(`/watchlist/${Number(wlId)}/items`, { symbol, name: description }).catch(() => null);
  iconEl.classList.remove('bi-hourglass-split');
  if (res && res.id) {
    iconEl.classList.add('bi-star-fill');
    iconEl.style.color = 'var(--yellow)';
    iconEl.title = 'In watchlist';
    scNotify(symbol + ' added to watchlist', 'success');
  } else {
    iconEl.classList.add('bi-star');
    scNotify('Failed to add ' + symbol, 'error');
  }
}

// Trading's order form takes this app's {BASE}USDT convention, not Delta's
// native {BASE}USD symbols the screener works with — mirrors
// from_delta_symbol() server-side (delta_symbol.upper() + "T") so the
// prefilled symbol actually resolves to something /trading recognizes.
const scTradingSymbol = (deltaSymbol) => String(deltaSymbol || '').toUpperCase() + 'T';

function scRsiBadgeColor(rsi) {
  if (rsi == null) return 'var(--text-muted)';
  if (rsi < 30) return 'var(--green)';
  if (rsi > 70) return 'var(--red)';
  return 'var(--text-muted)';
}

let scCardsView = false;
let scLastResults = [];

function scRenderResults(data) {
  dsSet('screenerMatchCount', `${data.matched ?? 0} of ${data.universe_size ?? 0} match`);
  dsSet('screenerMeta', data.generated_at ? 'refreshed ' + new Date(data.generated_at * 1000).toLocaleTimeString() : '');
  scLastResults = Array.isArray(data.results) ? data.results : [];
  dsSetSortData('screener', scLastResults); // drives the table view; cards view is unaffected by column sort
  scRenderResultsCards(scLastResults);
}

const DS_SCREENER_COLUMNS = [
  null, // watchlist star
  r => r.symbol,
  r => r.price,
  r => r.change_24h_pct,
  r => r.volume_24h,
  r => r.rsi_14,
  r => r.funding_pct,
  r => r.open_interest,
];

function scRenderResultsTable(results) {
  const tb = document.getElementById('screenerBody');
  if (!results.length) {
    tb.innerHTML = '<tr><td colspan="8" class="text-center text-muted py-4"><i class="bi bi-inbox d-block mb-2" style="font-size:22px;opacity:.4"></i>No matches</td></tr>';
    return;
  }
  tb.innerHTML = results.map((r) => {
    const change = Number(r.change_24h_pct);
    const rsi = Number(r.rsi_14);
    const funding = Number(r.funding_pct);
    const description = STSafe.html(r.description || r.symbol);
    return `
    <tr>
      <td><i class="bi bi-star sc-watch-star" data-sym="${STSafe.html(r.symbol)}" data-desc="${description}" style="cursor:pointer;color:var(--text-muted)" title="Add to watchlist"></i></td>
      <td><span class="asset-cell-name">${STSafe.html(r.symbol)}</span></td>
      <td class="num">${dsPrice(r.price)}</td>
      <td class="num" style="color:${change >= 0 ? 'var(--green)' : 'var(--red)'};font-weight:700">${change >= 0 ? '+' : ''}${Number.isFinite(change) ? change.toFixed(2) : '—'}%</td>
      <td class="num">${dsAbbr(r.volume_24h)}</td>
      <td class="num">${Number.isFinite(rsi) ? rsi.toFixed(1) : '—'}</td>
      <td class="num">${Number.isFinite(funding) ? (funding >= 0 ? '+' : '') + funding.toFixed(4) + '%' : '—'}</td>
      <td class="num">${dsAbbr(r.open_interest)}</td>
    </tr>
  `;
  }).join('');
  tb.querySelectorAll('.sc-watch-star').forEach((el) => {
    el.addEventListener('click', () => scAddToWatchlist(el.dataset.sym, el.dataset.desc, el));
  });
}

function scRenderResultsCards(results) {
  const wrap = document.getElementById('screenerCardsWrap');
  if (!wrap) return;
  if (!results.length) {
    wrap.innerHTML = '<div class="text-center text-muted py-4 w-100"><i class="bi bi-inbox d-block mb-2" style="font-size:22px;opacity:.4"></i>No matches</div>';
    return;
  }
  wrap.innerHTML = results.map((r) => {
    const change = Number(r.change_24h_pct);
    const up = Number.isFinite(change) && change >= 0;
    const tradeSym = scTradingSymbol(r.symbol);
    const encodedTradeSym = encodeURIComponent(tradeSym);
    const description = STSafe.html(r.description || r.symbol);
    return `
    <div class="scanner-card">
      <div class="scanner-card-head">
        <span class="scanner-card-symbol">${STSafe.html(r.symbol)}</span>
        <i class="bi bi-star sc-watch-star" data-sym="${STSafe.html(r.symbol)}" data-desc="${description}" style="cursor:pointer;color:var(--text-muted)" title="Add to watchlist"></i>
      </div>
      <div class="scanner-card-price">${dsPrice(r.price)}</div>
      <div class="scanner-card-metrics">
        <span>24h <span class="num" style="color:${up ? 'var(--green)' : 'var(--red)'}">${up ? '+' : ''}${Number.isFinite(change) ? change.toFixed(2) : '—'}%</span></span>
        <span>Vol <span class="num">${dsAbbr(r.volume_24h)}</span></span>
        <span>RSI <span class="num" style="color:${scRsiBadgeColor(r.rsi_14)}">${Number.isFinite(Number(r.rsi_14)) ? Number(r.rsi_14).toFixed(1) : '—'}</span></span>
        <span>OI <span class="num">${dsAbbr(r.open_interest)}</span></span>
      </div>
      <div class="scanner-card-actions">
        <a class="btn btn-sm btn-outline-success" href="/trading?symbol=${encodedTradeSym}&side=buy"><i class="bi bi-arrow-up-circle me-1"></i>Buy</a>
        <a class="btn btn-sm btn-outline-danger" href="/trading?symbol=${encodedTradeSym}&side=sell"><i class="bi bi-arrow-down-circle me-1"></i>Sell</a>
      </div>
    </div>`;
  }).join('');
  wrap.querySelectorAll('.sc-watch-star').forEach((el) => {
    el.addEventListener('click', () => scAddToWatchlist(el.dataset.sym, el.dataset.desc, el));
  });
}

function scSetView(view) {
  scCardsView = view === 'cards';
  document.getElementById('screenerTableWrap').style.display = scCardsView ? 'none' : '';
  document.getElementById('screenerCardsWrap').style.display = scCardsView ? '' : 'none';
  document.querySelectorAll('#screenerViewToggle button').forEach((b) => b.classList.toggle('active', b.dataset.view === view));
}

// The last request actually applied — Save Screen and Export both act on
// exactly what's currently shown in the Results table, not whatever is
// mid-edit in the condition builder.
let scLastApplied = { asset_type: 'perpetual_futures', conditions: [], combinator: 'AND' };
let scApplyInFlight = false;

function scUpdateExportLink() {
  const params = new URLSearchParams({
    asset_type: scLastApplied.asset_type,
    conditions: JSON.stringify(scLastApplied.conditions),
    combinator: scLastApplied.combinator,
  });
  const btn = document.getElementById('screenerExportBtn');
  if (btn) btn.href = '/api/v1/scanner/delta-market-screener/export.csv?' + params.toString();
}

async function scApply(presetKey) {
  if (scApplyInFlight) return;
  scApplyInFlight = true;
  const tb = document.getElementById('screenerBody');
  tb.innerHTML = '<tr><td colspan="8" class="text-center text-muted py-4"><i class="bi bi-hourglass-split d-block mb-2" style="font-size:22px"></i>Filtering…</td></tr>';

  const assetType = SC_ASSET_TYPES.has(scAssetType) ? scAssetType : 'perpetual_futures';
  const preset = Object.prototype.hasOwnProperty.call(market_screener_presets_cache, presetKey) ? presetKey : null;
  const params = new URLSearchParams({ asset_type: assetType });
  const effectiveConditions = preset
    ? (market_screener_presets_cache[preset] || [])
    : scConditions.filter((c) => c.value !== '');
  if (preset) {
    params.set('preset', preset);
  } else {
    params.set('conditions', JSON.stringify(effectiveConditions));
    params.set('combinator', scCombinator);
  }
  let data = null;
  try {
    data = await API.get('/scanner/delta-market-screener?' + params.toString()).catch(() => null);
  } finally {
    scApplyInFlight = false;
  }
  if (!data || data.error) { dsSet('screenerMeta', data?.error || 'Failed to load'); return; }

  if (!scFields) {
    scFields = data.fields && typeof data.fields === 'object' ? data.fields : {};
    scOperators = Array.isArray(data.operators) ? data.operators : [];
    if (!scConditions.length && !preset) {
      scRenderConditions();
    }
  }
  scRenderResults(data);

  scLastApplied = { asset_type: assetType, conditions: effectiveConditions, combinator: scCombinator };
  scUpdateExportLink();
}

// Preset conditions mirror app/services/scanner/delta_market_screener.py's
// PRESETS so Save Screen can persist "what preset X actually filters on"
// as ordinary conditions (a saved screen doesn't need the preset key to
// still work correctly after the fact).
const market_screener_presets_cache = {
  oversold: [{ field: 'rsi_14', op: '<', value: 30 }],
  overbought: [{ field: 'rsi_14', op: '>', value: 70 }],
  high_funding: [{ field: 'funding_pct', op: '>=', value: 0.05 }],
  top_volume: [{ field: 'volume_24h', op: '>=', value: 100000000 }],
  big_movers: [{ field: 'change_24h_pct', op: '>=', value: 8, abs: true }],
};

async function scSaveScreen() {
  const name = window.prompt('Name this screen:', '');
  const trimmedName = name?.trim().slice(0, 120);
  if (!trimmedName) return;
  const res = await API.post('/scanner/delta-market-screener/saved', {
    name: trimmedName,
    asset_type: scLastApplied.asset_type,
    conditions: scLastApplied.conditions,
    combinator: scLastApplied.combinator,
  }).catch(() => null);
  if (res && res.id) {
    scNotify('Screen saved', 'success');
    scSavedScreensLoaded = false; // force a re-fetch next time the dropdown opens
  } else {
    scNotify('Failed to save screen', 'error');
  }
}

let scSavedScreensLoaded = false;

async function scLoadSavedScreens() {
  const menu = document.getElementById('screenerSavedMenu');
  if (!menu) return;
  const res = await API.get('/scanner/delta-market-screener/saved').catch(() => null);
  const screens = Array.isArray(res?.screens) ? res.screens : [];
  scSavedScreensLoaded = true;
  if (!screens.length) {
    menu.innerHTML = '<li><span class="dropdown-item-text text-muted small">No saved screens yet</span></li>';
    return;
  }
  menu.innerHTML = screens.map((s) => {
    const id = STSafe.assetId(s.id);
    const assetType = SC_ASSET_TYPES.has(s.asset_type) ? s.asset_type : 'perpetual_futures';
    const conditions = Array.isArray(s.conditions) ? s.conditions : [];
    return `
    <li class="d-flex align-items-center">
      <a class="dropdown-item flex-grow-1 sc-load-screen" href="#" data-id="${STSafe.html(id)}">${STSafe.html(s.name || 'Unnamed screen')}
        <span class="text-muted small d-block">${STSafe.html(assetType.replace('_', ' '))} · ${conditions.length} condition(s)</span>
      </a>
      <button class="btn btn-sm text-danger sc-delete-screen" data-id="${STSafe.html(id)}" title="Delete"><i class="bi bi-trash"></i></button>
    </li>
  `;
  }).join('');
  menu.querySelectorAll('.sc-load-screen').forEach((el) => {
    el.addEventListener('click', (e) => {
      e.preventDefault();
      const s = screens.find((x) => String(x.id) === el.dataset.id);
      if (!s) return;
      scAssetType = SC_ASSET_TYPES.has(s.asset_type) ? s.asset_type : 'perpetual_futures';
      scCombinator = s.combinator === 'OR' ? 'OR' : 'AND';
      scConditions = (Array.isArray(s.conditions) ? s.conditions : []).slice(0, 20).map((c) => ({ value2: '', abs: false, ...c }));
      document.querySelectorAll('#screenerAssetTypeTabs .scan-chip').forEach((x) => x.classList.toggle('active', x.dataset.type === scAssetType));
      document.querySelectorAll('#screenerCombinator button').forEach((x) => x.classList.toggle('active', x.dataset.combinator === scCombinator));
      document.querySelectorAll('#screenerPresets .scan-chip').forEach((x) => x.classList.remove('active'));
      scRenderConditions();
      scApply(null);
    });
  });
  menu.querySelectorAll('.sc-delete-screen').forEach((el) => {
    el.addEventListener('click', async (e) => {
      e.stopPropagation();
      const id = STSafe.assetId(el.dataset.id);
      if (!id) return;
      await API.delete(`/scanner/delta-market-screener/saved/${Number(id)}`).catch(() => null);
      scLoadSavedScreens();
    });
  });
}

const MODE_SUBTITLES = {
  mtf: 'Multi-timeframe BUY/SELL scan of every live Delta Exchange contract — 5m EMA(9/21/50) zone + 15m & 1h Supertrend(10,3) confirmation, ranked by volume',
  screener: 'Screen every live Delta Exchange contract by price, 24h change, volume, RSI, funding, and open interest.',
  indicator: 'Build indicator-crossover conditions (EMA/SMA/RSI/MACD/ADX/ATR/Bollinger) on a chosen candle timeframe — e.g. "EMA 9 crosses above EMA 20".',
};

function scSwitchMode(mode) {
  document.getElementById('mtfModePanel').style.display = mode === 'mtf' ? '' : 'none';
  document.getElementById('screenerModePanel').style.display = mode === 'screener' ? '' : 'none';
  document.getElementById('indicatorModePanel').style.display = mode === 'indicator' ? '' : 'none';
  document.querySelectorAll('#scannerModeTabs .scan-chip').forEach((b) => b.classList.toggle('active', b.dataset.mode === mode));
  const subtitle = document.getElementById('pageSubtitle');
  if (subtitle) subtitle.textContent = MODE_SUBTITLES[mode] || '';

  if (mode === 'screener' && !scFields) {
    scApply(null);
  }
  if (mode === 'indicator' && !icIndicators) {
    icApply();
  }
}

/* ═══════════════════════════════════════════════
   Indicator Screener mode — crossover/threshold
   conditions over EMA/SMA/RSI/MACD/ADX/ATR/Bollinger
   ═══════════════════════════════════════════════ */
let icAssetType = 'perpetual_futures';
let icTimeframe = '15m';
let icCombinator = 'AND';
let icConditions = [];
let icIndicators = null;   // {field_key: label} — loaded from the API's first response
let icComparisons = null;
let icApplyInFlight = false;

const IC_COMPARISON_LABEL = {
  crosses_above: 'crosses above', crosses_below: 'crosses below',
  is_above: 'is above', is_below: 'is below',
  is_at_or_above: 'is at or above', is_at_or_below: 'is at or below',
  is_between: 'is between',
};

function icNewCondition() {
  const firstField = icIndicators ? Object.keys(icIndicators)[0] : 'ema9';
  const secondField = icIndicators ? (Object.keys(icIndicators)[2] || firstField) : 'ema20';
  return { field: firstField, comparison: 'crosses_above', rightMode: 'indicator', rightField: secondField, rightValue: '', low: '', high: '' };
}

function icRenderConditions() {
  const wrap = document.getElementById('indicatorConditions');
  if (!wrap) return;
  if (!icConditions.length) {
    wrap.innerHTML = '<div class="text-muted small py-2">No conditions yet — every coin matches. Add a Condition above.</div>';
    return;
  }
  const fieldOpts = (fields) => Object.entries(icIndicators || {}).map(([k, label]) => `<option value="${STSafe.html(k)}" ${k === fields ? 'selected' : ''}>${STSafe.html(label)}</option>`).join('');
  const compOpts = (comp) => (icComparisons || []).map((c) => `<option value="${STSafe.html(c)}" ${c === comp ? 'selected' : ''}>${STSafe.html(IC_COMPARISON_LABEL[c] || c)}</option>`).join('');

  wrap.innerHTML = icConditions.map((c, i) => {
    const isBetween = c.comparison === 'is_between';
    const rightControl = isBetween
      ? `<input type="number" class="form-control form-control-sm ic-low" style="width:90px" placeholder="low" value="${STSafe.html(c.low)}" data-i="${i}">
         <span class="text-muted small">and</span>
         <input type="number" class="form-control form-control-sm ic-high" style="width:90px" placeholder="high" value="${STSafe.html(c.high)}" data-i="${i}">`
      : `<select class="form-select form-select-sm ic-right-mode" style="width:auto" data-i="${i}">
           <option value="number" ${c.rightMode === 'number' ? 'selected' : ''}>a number…</option>
           ${Object.entries(icIndicators || {}).map(([k, label]) => `<option value="indicator:${STSafe.html(k)}" ${c.rightMode === 'indicator' && c.rightField === k ? 'selected' : ''}>${STSafe.html(label)}</option>`).join('')}
         </select>
         ${c.rightMode === 'number' ? `<input type="number" class="form-control form-control-sm ic-right-value" style="width:110px" placeholder="value" value="${STSafe.html(c.rightValue)}" data-i="${i}">` : ''}`;

    return `
    <div class="d-flex align-items-center gap-2 mb-2 flex-wrap" data-cond-row="${i}">
      <span class="text-muted small" style="min-width:44px">${i === 0 ? 'where' : icCombinator.toLowerCase()}</span>
      <select class="form-select form-select-sm ic-field" style="width:auto" data-i="${i}">${fieldOpts(c.field)}</select>
      <select class="form-select form-select-sm ic-comparison" style="width:auto" data-i="${i}">${compOpts(c.comparison)}</select>
      ${rightControl}
      <button class="btn btn-sm btn-outline-secondary ic-remove" data-i="${i}" title="Remove"><i class="bi bi-x-lg"></i></button>
    </div>`;
  }).join('');

  wrap.querySelectorAll('.ic-field').forEach((el) => {
    el.addEventListener('change', (e) => { icConditions[+e.target.dataset.i].field = e.target.value; });
  });
  wrap.querySelectorAll('.ic-comparison').forEach((el) => {
    el.addEventListener('change', (e) => { icConditions[+e.target.dataset.i].comparison = e.target.value; icRenderConditions(); });
  });
  wrap.querySelectorAll('.ic-right-mode').forEach((el) => {
    el.addEventListener('change', (e) => {
      const cond = icConditions[+e.target.dataset.i];
      const v = e.target.value;
      if (v === 'number') { cond.rightMode = 'number'; }
      else { cond.rightMode = 'indicator'; cond.rightField = v.split(':')[1]; }
      icRenderConditions();
    });
  });
  wrap.querySelectorAll('.ic-right-value').forEach((el) => {
    el.addEventListener('input', (e) => { icConditions[+e.target.dataset.i].rightValue = e.target.value; });
  });
  wrap.querySelectorAll('.ic-low').forEach((el) => {
    el.addEventListener('input', (e) => { icConditions[+e.target.dataset.i].low = e.target.value; });
  });
  wrap.querySelectorAll('.ic-high').forEach((el) => {
    el.addEventListener('input', (e) => { icConditions[+e.target.dataset.i].high = e.target.value; });
  });
  wrap.querySelectorAll('.ic-remove').forEach((el) => {
    el.addEventListener('click', (e) => {
      icConditions.splice(+e.currentTarget.dataset.i, 1);
      icRenderConditions();
    });
  });
}

function icBuildPayloadConditions() {
  return icConditions.map((c) => {
    const cond = { left: { type: 'indicator', field: c.field }, comparison: c.comparison };
    if (c.comparison === 'is_between') {
      cond.low = c.low;
      cond.high = c.high;
    } else if (c.rightMode === 'number') {
      cond.right = { type: 'number', value: c.rightValue };
    } else {
      cond.right = { type: 'indicator', field: c.rightField };
    }
    return cond;
  }).filter((c) => {
    if (c.comparison === 'is_between') return c.low !== '' && c.high !== '';
    if (c.right && c.right.type === 'number') return c.right.value !== '';
    return true;
  });
}

function icReferencedFields() {
  const fields = new Set();
  icConditions.forEach((c) => {
    fields.add(c.field);
    if (c.comparison !== 'is_between' && c.rightMode === 'indicator') fields.add(c.rightField);
  });
  return [...fields];
}

function icRenderResults(data) {
  const referenced = icReferencedFields().filter(f => Object.prototype.hasOwnProperty.call(icIndicators || {}, f));
  const thead = document.getElementById('indicatorTableHead');
  const tbody = document.getElementById('indicatorBody');

  thead.innerHTML = `<tr><th></th><th>Symbol</th><th>Price</th><th>Vol (bar)</th>${referenced.map((f) => `<th>${STSafe.html(icIndicators[f] || f)}</th>`).join('')}</tr>`;

  dsSet('indicatorMatchCount', `${data.matched} of ${data.universe_size} match`);
  dsSet('indicatorMeta', data.generated_at ? 'refreshed ' + new Date(data.generated_at * 1000).toLocaleTimeString() : '');

  const summaryCard = document.getElementById('indicatorSummaryCard');
  if (Array.isArray(data.conditions_summary) && data.conditions_summary.length) {
    document.getElementById('indicatorSummaryText').textContent = data.conditions_summary.join(icCombinator === 'OR' ? '  OR  ' : '  AND  ');
    summaryCard.style.display = '';
  } else {
    summaryCard.style.display = 'none';
  }

  const results = Array.isArray(data.results) ? data.results : [];
  if (!results.length) {
    tbody.innerHTML = `<tr><td colspan="${4 + referenced.length}" class="text-center text-muted py-4"><i class="bi bi-inbox d-block mb-2" style="font-size:22px;opacity:.4"></i>No matches</td></tr>`;
    return;
  }

  tbody.innerHTML = results.map((r) => `
    <tr>
      <td><i class="bi bi-star sc-watch-star" data-sym="${STSafe.html(r.symbol)}" data-desc="${STSafe.html(r.description || r.symbol)}" style="cursor:pointer;color:var(--text-muted)" title="Add to watchlist"></i></td>
      <td><span class="asset-cell-name">${STSafe.html(r.symbol)}</span></td>
      <td class="num">${dsPrice(r.price)}</td>
      <td class="num">${dsAbbr(r.volume_bar)}</td>
      ${referenced.map((f) => { const value = Number(r.indicators?.[f]); return `<td class="num">${Number.isFinite(value) ? value.toFixed(4) : '—'}</td>`; }).join('')}
    </tr>
  `).join('');
  tbody.querySelectorAll('.sc-watch-star').forEach((el) => {
    el.addEventListener('click', () => scAddToWatchlist(el.dataset.sym, el.dataset.desc, el));
  });
}

async function icApply() {
  if (icApplyInFlight) return;
  icApplyInFlight = true;
  const tbody = document.getElementById('indicatorBody');
  tbody.innerHTML = '<tr><td colspan="4" class="text-center text-muted py-4"><i class="bi bi-hourglass-split d-block mb-2" style="font-size:22px"></i>Scanning (fetches candles for every contract — a few seconds)…</td></tr>';

  const conditions = icBuildPayloadConditions();
  const params = new URLSearchParams({
    asset_type: icAssetType,
    timeframe: icTimeframe,
    conditions: JSON.stringify(conditions),
    combinator: icCombinator,
  });
  let data = null;
  try {
    data = await API.get('/scanner/delta-indicator-screener?' + params.toString()).catch(() => null);
  } finally {
    icApplyInFlight = false;
  }
  if (!data || data.error) { dsSet('indicatorMeta', data?.error || 'Failed to load'); return; }

  if (!icIndicators) {
    icIndicators = data.indicators && typeof data.indicators === 'object' ? data.indicators : {};
    icComparisons = Array.isArray(data.comparisons) ? data.comparisons : [];
    if (!icConditions.length) {
      icConditions.push(icNewCondition());
      icRenderConditions();
    }
  }
  icRenderResults(data);
}

// app:ready (fired from app.js), not DOMContentLoaded: this page is
// tier-gated (requires_tier=2 in views.py), and app:ready is deliberately
// skipped on a tier-locked page since showTierLockOverlay() replaces
// #pageContentBody's real elements with an upgrade card -- listening on
// DOMContentLoaded instead ran this unconditionally and raced that swap,
// throwing on the first now-missing element for any account below
// Premium (same bug and fix as journal.html's Trade Journal, this
// session).
document.addEventListener('app:ready', () => {
  dsInitScanTableSorting();
  dsLoadScan(false);
  dsStartScanAutoRefresh();
  scUpdateExportLink();
  mtfLoadCommon();
  mtfStartCommonAutoRefresh();
  const btn = document.getElementById('rescanBtn');
  if (btn) btn.addEventListener('click', () => dsLoadScan(true));

  const configBtn = document.getElementById('mtfConfigureBtn');
  if (configBtn) configBtn.addEventListener('click', mtfConfigure);

  const ccSearch = document.getElementById('ccSearchInput');
  if (ccSearch) ccSearch.addEventListener('input', () => ccRenderResults(ccSearch.value));
  wireSearchClear('ccSearchInput');

  const ccClear = document.getElementById('ccClearBtn');
  if (ccClear) ccClear.addEventListener('click', () => {
    ccSelected.clear();
    ccRenderChips();
    ccRenderResults(document.getElementById('ccSearchInput').value);
  });

  const ccSaveBtnEl = document.getElementById('ccSaveBtn');
  if (ccSaveBtnEl) ccSaveBtnEl.addEventListener('click', ccSave);

  document.querySelectorAll('#mtfSubTabs .scan-chip').forEach((b) => {
    b.addEventListener('click', () => mtfSetSubTab(b.dataset.subtab));
  });

  document.querySelectorAll('#dsDirTabs .scan-chip').forEach((b) => {
    b.addEventListener('click', () => dsSetDirTab(b.dataset.dir));
  });

  document.querySelectorAll('#scannerModeTabs .scan-chip').forEach((b) => {
    b.addEventListener('click', () => scSwitchMode(b.dataset.mode));
  });

  document.querySelectorAll('#screenerAssetTypeTabs .scan-chip').forEach((b) => {
    b.addEventListener('click', () => {
      document.querySelectorAll('#screenerAssetTypeTabs .scan-chip').forEach((x) => x.classList.remove('active'));
      b.classList.add('active');
      scAssetType = b.dataset.type;
      scApply(null);
    });
  });

  document.querySelectorAll('#screenerPresets .scan-chip').forEach((b) => {
    b.addEventListener('click', () => {
      document.querySelectorAll('#screenerPresets .scan-chip').forEach((x) => x.classList.remove('active'));
      b.classList.add('active');
      scConditions = [];
      scApply(b.dataset.preset);
    });
  });

  document.getElementById('screenerAddCondition').addEventListener('click', () => {
    document.querySelectorAll('#screenerPresets .scan-chip').forEach((x) => x.classList.remove('active'));
    scConditions.push(scNewCondition());
    scRenderConditions();
  });

  document.getElementById('screenerReset').addEventListener('click', () => {
    scConditions = [];
    scCombinator = 'AND';
    document.querySelectorAll('#screenerCombinator button').forEach((b) => b.classList.toggle('active', b.dataset.combinator === 'AND'));
    document.querySelectorAll('#screenerPresets .scan-chip').forEach((x) => x.classList.remove('active'));
    scRenderConditions();
    scApply(null);
  });

  document.getElementById('screenerApply').addEventListener('click', () => {
    document.querySelectorAll('#screenerPresets .scan-chip').forEach((x) => x.classList.remove('active'));
    scApply(null);
  });

  document.querySelectorAll('#screenerCombinator button').forEach((b) => {
    b.addEventListener('click', () => {
      scCombinator = b.dataset.combinator;
      document.querySelectorAll('#screenerCombinator button').forEach((x) => x.classList.remove('active'));
      b.classList.add('active');
      scRenderConditions();
    });
  });

  document.getElementById('screenerSaveBtn').addEventListener('click', scSaveScreen);

  const savedDropdownToggle = document.getElementById('screenerSavedBtn');
  if (savedDropdownToggle) {
    savedDropdownToggle.addEventListener('click', () => {
      if (!scSavedScreensLoaded) scLoadSavedScreens();
    });
  }

  document.querySelectorAll('#screenerViewToggle button').forEach((b) => {
    b.addEventListener('click', () => scSetView(b.dataset.view));
  });

  document.querySelectorAll('#indicatorAssetTypeTabs .scan-chip').forEach((b) => {
    b.addEventListener('click', () => {
      document.querySelectorAll('#indicatorAssetTypeTabs .scan-chip').forEach((x) => x.classList.remove('active'));
      b.classList.add('active');
      icAssetType = b.dataset.type;
      icApply();
    });
  });

  document.querySelectorAll('#indicatorTimeframeTabs .scan-chip').forEach((b) => {
    b.addEventListener('click', () => {
      document.querySelectorAll('#indicatorTimeframeTabs .scan-chip').forEach((x) => x.classList.remove('active'));
      b.classList.add('active');
      icTimeframe = b.dataset.tf;
      icApply();
    });
  });

  document.getElementById('indicatorAddCondition').addEventListener('click', () => {
    icConditions.push(icNewCondition());
    icRenderConditions();
  });

  document.getElementById('indicatorReset').addEventListener('click', () => {
    icConditions = [];
    icCombinator = 'AND';
    document.querySelectorAll('#indicatorCombinator button').forEach((b) => b.classList.toggle('active', b.dataset.combinator === 'AND'));
    icRenderConditions();
    icApply();
  });

  document.getElementById('indicatorApply').addEventListener('click', icApply);

  document.querySelectorAll('#indicatorCombinator button').forEach((b) => {
    b.addEventListener('click', () => {
      icCombinator = b.dataset.combinator;
      document.querySelectorAll('#indicatorCombinator button').forEach((x) => x.classList.remove('active'));
      b.classList.add('active');
      icRenderConditions();
    });
  });
});
