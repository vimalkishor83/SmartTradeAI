/* Reporting Center - bounded, read-only historical performance view. */

let _reportChart = null;
let _reportSequence = 0;
let _reportInFlight = false;
let _reportBooted = false;

const reportNumber = (value, fallback = null) => {
  if (value === null || value === undefined || value === '') return fallback;
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
};
const reportCount = value => Math.max(0, Math.floor(reportNumber(value, 0)));
const reportRate = value => {
  const number = reportNumber(value);
  return number == null ? null : Math.min(100, Math.max(0, number));
};
const reportPnl = value => {
  const number = reportNumber(value);
  return number == null ? '-' : (number >= 0 ? '+' : '') + number.toFixed(2) + '%';
};
const reportEsc = value => STSafe.html(String(value ?? ''));

function utcDateOffset(daysAgo) {
  const now = new Date();
  const date = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()));
  date.setUTCDate(date.getUTCDate() - daysAgo);
  return date.toISOString().slice(0, 10);
}

function setReportState(kind, message) {
  const status = document.getElementById('reportStatus');
  const state = document.getElementById('reportState');
  if (status) status.className = 'dashboard-context report-context is-' + kind;
  if (state) state.textContent = message;
  if (kind === 'ready') {
    const updated = document.getElementById('reportLastUpdated');
    if (updated) updated.textContent = 'Last updated ' + new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
  }
}

function setReportBusy(isBusy) {
  const content = document.getElementById('reportContent');
  const run = document.getElementById('runReport');
  const exportButton = document.getElementById('reportExport');
  if (content) content.setAttribute('aria-busy', String(isBusy));
  if (run) {
    run.disabled = isBusy;
    run.setAttribute('aria-busy', String(isBusy));
  }
  if (exportButton) exportButton.disabled = isBusy;
}

function setReportTableState(tbody, colspan, message) {
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="${colspan}" class="text-center text-muted py-4">${reportEsc(message)}</td></tr>`;
}

function validateReportRange() {
  const from = document.getElementById('reportFrom')?.value || '';
  const to = document.getElementById('reportTo')?.value || '';
  const error = document.getElementById('reportValidation');
  let message = '';
  if (!/^\d{4}-\d{2}-\d{2}$/.test(from) || !/^\d{4}-\d{2}-\d{2}$/.test(to)) {
    message = 'Choose both a start and end date.';
  } else if (from > to) {
    message = 'The start date must be on or before the end date.';
  } else {
    const start = new Date(from + 'T00:00:00Z');
    const end = new Date(to + 'T00:00:00Z');
    const days = Math.round((end - start) / 86400000) + 1;
    if (!Number.isFinite(days) || days > 367) message = 'Choose a range of 367 days or fewer.';
  }
  if (error) {
    error.textContent = message;
    error.hidden = !message;
  }
  return message ? null : { from, to };
}

function updateRangeLabel(range) {
  const label = document.getElementById('reportRangeLabel');
  if (!label || !range) return;
  const preset = document.getElementById('reportPreset')?.value;
  label.textContent = preset !== 'custom' ? `Last ${preset} days` : `${range.from} to ${range.to} UTC`;
}

function renderSummary(overall) {
  const total = reportCount(overall?.total);
  const wins = Math.min(total, reportCount(overall?.wins));
  const losses = Math.min(total - wins, reportCount(overall?.losses));
  const neutral = Math.max(0, total - wins - losses);
  const rate = reportRate(overall?.win_rate);
  const set = (id, value) => { const element = document.getElementById(id); if (element) element.textContent = value; };
  set('reportTotal', total.toLocaleString());
  set('reportOutcomeMix', `${wins} wins / ${losses} losses / ${neutral} neutral`);
  set('reportWinRate', rate == null ? '-' : rate.toFixed(1) + '%');
  set('reportNetPnl', reportPnl(overall?.net_pnl_pct));
  set('reportProfitFactor', reportNumber(overall?.profit_factor) == null ? '-' : reportNumber(overall.profit_factor).toFixed(2));
  set('reportAvgPnl', reportPnl(overall?.avg_pnl_pct));
  const duration = reportNumber(overall?.avg_duration_minutes);
  set('reportAvgDuration', duration == null ? '-' : duration.toFixed(1));
  set('reportWins', wins.toLocaleString());
  set('reportLosses', losses.toLocaleString());
  set('reportNeutral', neutral.toLocaleString());
  const denominator = total || 1;
  document.getElementById('reportWinsBar')?.style.setProperty('width', `${Math.min(100, wins / denominator * 100)}%`);
  document.getElementById('reportLossesBar')?.style.setProperty('width', `${Math.min(100, losses / denominator * 100)}%`);
  document.getElementById('reportNeutralBar')?.style.setProperty('width', `${Math.min(100, neutral / denominator * 100)}%`);
}

function marketLabel(value) {
  const labels = { indian_stock: 'Indian Stocks', index: 'Indices', crypto: 'Crypto', forex: 'Forex', commodity: 'Commodities' };
  return labels[value] || String(value || 'Unknown').replace('_', ' ').replace(/^\w/, character => character.toUpperCase());
}

function renderMarketTable(rows) {
  const tbody = document.getElementById('reportMarketBody');
  const items = (Array.isArray(rows) ? rows : []).slice(0, 20);
  if (!items.length) { setReportTableState(tbody, 6, 'No closed trades in this range.'); return; }
  tbody.innerHTML = items.map(row => {
    const total = reportCount(row?.total);
    const wins = Math.min(total, reportCount(row?.wins));
    const losses = Math.min(total - wins, reportCount(row?.losses));
    const rate = reportRate(row?.win_rate);
    const pnl = reportNumber(row?.pnl_pct);
    return `<tr><td>${reportEsc(marketLabel(row?.name))}</td><td class="num">${total}</td><td class="num text-green">${wins}</td><td class="num text-red">${losses}</td><td class="num" style="font-weight:700">${rate == null ? '-' : rate.toFixed(1) + '%'}</td><td class="num ${pnl != null && pnl < 0 ? 'text-red' : 'text-green'}">${reportPnl(pnl)}</td></tr>`;
  }).join('');
}

function renderTimeframeTable(rows) {
  const tbody = document.getElementById('reportTfBody');
  const items = (Array.isArray(rows) ? rows : []).slice(0, 20);
  if (!items.length) { setReportTableState(tbody, 4, 'No closed trades in this range.'); return; }
  tbody.innerHTML = items.map(row => {
    const total = reportCount(row?.total);
    const rate = reportRate(row?.win_rate);
    const pnl = reportNumber(row?.pnl_pct);
    return `<tr><td><span class="ui-chip ui-chip--neutral">${reportEsc(row?.name || 'Unknown')}</span></td><td class="num">${total}</td><td class="num" style="font-weight:700">${rate == null ? '-' : rate.toFixed(1) + '%'}</td><td class="num ${pnl != null && pnl < 0 ? 'text-red' : 'text-green'}">${reportPnl(pnl)}</td></tr>`;
  }).join('');
}

function renderDailyChart(rows) {
  const canvas = document.getElementById('reportDailyChart');
  const empty = document.getElementById('reportDailyEmpty');
  const items = (Array.isArray(rows) ? rows : []).slice(-367);
  if (_reportChart) { _reportChart.destroy(); _reportChart = null; }
  if (!items.length || typeof Chart !== 'function') {
    if (canvas) canvas.style.display = 'none';
    if (empty) { empty.hidden = false; empty.textContent = typeof Chart !== 'function' ? 'Chart library unavailable. Use the tables above for the report.' : 'No closed trades in this range.'; }
    return;
  }
  if (canvas) canvas.style.display = '';
  if (empty) empty.hidden = true;
  const css = getComputedStyle(document.documentElement);
  _reportChart = new Chart(canvas, {
    type: 'bar',
    data: {
      labels: items.map(row => reportEsc(String(row?.date || 'Unknown')).slice(0, 10)),
      datasets: [{ label: 'P&L %', data: items.map(row => reportNumber(row?.pnl_pct, 0)), backgroundColor: items.map(row => reportNumber(row?.pnl_pct, 0) >= 0 ? 'rgba(16,185,129,.72)' : 'rgba(239,68,68,.72)'), borderRadius: 4 }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: { y: { ticks: { callback: value => value + '%' }, grid: { color: (css.getPropertyValue('--border') || 'rgba(148,163,184,.1)').trim() } }, x: { grid: { display: false }, ticks: { maxTicksLimit: 12 } } },
    },
  });
}

async function loadReport() {
  if (_reportInFlight) return;
  const range = validateReportRange();
  if (!range) return;
  _reportInFlight = true;
  const sequence = ++_reportSequence;
  setReportBusy(true);
  setReportState('loading', 'Loading historical report');
  updateRangeLabel(range);
  try {
    const data = await API.get('/signals/report', range);
    if (sequence !== _reportSequence) return;
    if (!data) {
      setReportState('error', 'Report data unavailable');
      setReportTableState(document.getElementById('reportMarketBody'), 6, 'Report data is temporarily unavailable. Try again.');
      setReportTableState(document.getElementById('reportTfBody'), 4, 'Report data is temporarily unavailable. Try again.');
      renderDailyChart([]);
      return;
    }
    renderSummary(data.overall || {});
    renderMarketTable(data.by_market);
    renderTimeframeTable(data.by_timeframe);
    renderDailyChart(data.daily);
    setReportState('ready', 'Report ready');
  } catch (_) {
    setReportState('error', 'Report data unavailable');
  } finally {
    if (sequence === _reportSequence) {
      _reportInFlight = false;
      setReportBusy(false);
    }
  }
}

async function exportReport() {
  const range = validateReportRange();
  if (!range) return;
  const button = document.getElementById('reportExport');
  if (button) button.disabled = true;
  try {
    const query = new URLSearchParams(range).toString();
    const response = await fetch('/api/v1/signals/history/export/csv?' + query, { headers: API.headers() });
    if (!response.ok) throw new Error('export failed');
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `signal_history_${range.from}_${range.to}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  } catch (_) {
    setReportState('error', 'Export failed. Try again.');
  } finally {
    if (button) button.disabled = false;
  }
}

function applyPreset() {
  const preset = document.getElementById('reportPreset')?.value;
  if (preset === 'custom') return;
  const days = Math.max(1, reportCount(preset));
  const from = document.getElementById('reportFrom');
  const to = document.getElementById('reportTo');
  if (from) from.value = utcDateOffset(days - 1);
  if (to) to.value = utcDateOffset(0);
  loadReport();
}

document.addEventListener('app:ready', () => {
  if (_reportBooted) return;
  _reportBooted = true;
  document.getElementById('reportFrom').value = utcDateOffset(29);
  document.getElementById('reportTo').value = utcDateOffset(0);
  document.getElementById('reportPreset').addEventListener('change', applyPreset);
  ['reportFrom', 'reportTo'].forEach(id => document.getElementById(id).addEventListener('change', () => {
    document.getElementById('reportPreset').value = 'custom';
  }));
  document.getElementById('runReport').addEventListener('click', loadReport);
  document.getElementById('reportExport').addEventListener('click', exportReport);
  loadReport();
});
