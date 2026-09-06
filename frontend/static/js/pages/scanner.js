/* ═══════════════════════════════════════════════
   Market Scanner — SmartTrade AI
   ═══════════════════════════════════════════════ */
let _active = new Set();
let _results = [];
let _scannedCount = 0;
let _symbolIds = Object.create(null);
let _scanInFlight = false;
let _scanBooted = false;
const sset = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = (v ?? '—'); };
const sfmt = (n, d = 2) => (n == null || isNaN(n)) ? '—' : (+n).toFixed(d);
const _num = (value, fallback = 0) => {
  if (value === null || value === undefined || value === '') return fallback;
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
};
const _scv = (n, f) => (getComputedStyle(document.documentElement).getPropertyValue(n) || f).trim();
const _notify = (message, type = 'info') => {
  if (typeof Toast !== 'undefined') Toast.show(message, type);
  else if (typeof toast === 'function') toast(message, type);
};

const FILTER_META = {
  strong_buy: { label: 'Strong Buy', sig: 'Strong Buy', clr: 'var(--green)', icon: 'graph-up-arrow' },
  buy: { label: 'Buy', sig: 'Buy', clr: 'var(--green)', icon: 'arrow-up' },
  strong_sell: { label: 'Strong Sell', sig: 'Strong Sell', clr: 'var(--red)', icon: 'graph-down-arrow' },
  sell: { label: 'Sell', sig: 'Sell', clr: 'var(--red)', icon: 'arrow-down' },
  breakout: { label: 'Breakout', sig: 'Breakout', clr: 'var(--yellow)', icon: 'box-arrow-up' },
  breakdown: { label: 'Breakdown', sig: 'Breakdown', clr: 'var(--red)', icon: 'box-arrow-down' },
  volume_spike: { label: 'Volume Spike', sig: 'Vol Spike', clr: 'var(--accent-light)', icon: 'bar-chart-fill' },
  rsi_oversold: { label: 'RSI Oversold', sig: 'Oversold', clr: 'var(--green)', icon: 'activity' },
  rsi_overbought: { label: 'RSI Overbought', sig: 'Overbought', clr: 'var(--red)', icon: 'activity' },
  gap_up: { label: 'Gap Up', sig: 'Gap Up', clr: 'var(--green)', icon: 'chevron-double-up' },
  gap_down: { label: 'Gap Down', sig: 'Gap Down', clr: 'var(--red)', icon: 'chevron-double-down' },
  '52w_high': { label: '52W High', sig: '52W High', clr: 'var(--yellow)', icon: 'trophy' },
  '52w_low': { label: '52W Low', sig: '52W Low', clr: 'var(--red)', icon: 'graph-down' },
};
// Map convenience chips to backend-supported checks
const ALIAS = { buy: 'strong_buy', sell: 'strong_sell' };

/* ── KPI strip (perf + heatmap) ── */
async function loadScanKPIs() {
  const results = await Promise.allSettled([API.get('/signals/performance'), API.get('/signals/open-pnl'), API.get('/market-data/heatmap')]);
  const [perfResult, pnlResult, heatResult] = results;
  const perf = perfResult.status === 'fulfilled' ? perfResult.value : null;
  const pnl = pnlResult.status === 'fulfilled' ? pnlResult.value : null;
  const heat = heatResult.status === 'fulfilled' ? heatResult.value : null;
  const ov = perf?.overall || {};
  const winRate = _num(ov.win_rate, NaN);
  sset('kpiWin', Number.isFinite(winRate) ? winRate.toFixed(1) + '%' : '—');
  sset('kpiWinSub', 'n = ' + (ov.total_closed ?? 0));
  if (Array.isArray(pnl) && pnl.length) {
    const avg = pnl.reduce((s, r) => s + _num(r.pnl_pct), 0) / pnl.length;
    const el = document.getElementById('kpiPnl'); if (el) { el.textContent = (avg >= 0 ? '+' : '') + avg.toFixed(2) + '%'; el.className = 'kpi-value ' + (avg >= 0 ? 'text-green' : 'text-red'); }
    sset('kpiPnlSub', pnl.length + ' open');
  } else { sset('kpiPnl', '—'); sset('kpiPnlSub', 'unavailable'); }
  const rows = Array.isArray(heat?.heatmap) ? heat.heatmap : [];
  if (rows.length) {
    const ch = rows.map(r => _num(r.change_pct)); const avg = ch.reduce((a, b) => a + b, 0) / ch.length;
    const std = Math.sqrt(ch.reduce((a, b) => a + (b - avg) ** 2, 0) / ch.length);
    const score = Math.round(Math.max(0, Math.min(100, 50 + avg * 12)));
    const slbl = score >= 55 ? 'Bullish' : score >= 45 ? 'Neutral' : 'Bearish';
    const bull = rows.filter(r => _num(r.change_pct) > 0.1).length; const bear = rows.filter(r => _num(r.change_pct) < -0.1).length;
    const se = document.getElementById('kpiSent'); if (se) { se.textContent = `${slbl} (${score})`; se.className = 'kpi-value ' + (score >= 55 ? 'text-green' : score >= 45 ? 'text-yellow' : 'text-red'); }
    sset('kpiSentSub', `Bull ${Math.round(bull / rows.length * 100)}% · Bear ${Math.round(bear / rows.length * 100)}%`);
    const vlbl = std > 2 ? 'High' : std > 1 ? 'Moderate' : 'Low';
    const ve = document.getElementById('kpiVol'); if (ve) { ve.textContent = vlbl; ve.className = 'kpi-value ' + (std > 2 ? 'text-red' : std > 1 ? 'text-yellow' : 'text-green'); }
    sset('kpiVolSub', 'σ ' + std.toFixed(2) + '%');
  } else { sset('kpiSent', '—'); sset('kpiSentSub', 'unavailable'); sset('kpiVol', '—'); sset('kpiVolSub', 'unavailable'); }
  return results.some(result => result.status === 'fulfilled');
}

/* ── derive signal + confidence from matched filters ── */
function _deriveSignal(matched) {
  matched = Array.isArray(matched) ? matched : [];
  const order = ['strong_buy', 'strong_sell', 'breakout', 'breakdown', 'rsi_oversold', 'rsi_overbought', 'volume_spike', 'gap_up', 'gap_down', '52w_high', '52w_low'];
  const first = order.find(f => matched.includes(f)) || matched[0];
  return FILTER_META[first]?.sig || 'Match';
}
function _deriveConfidence(r) {
  const m = Array.isArray(r.matched_filters) ? r.matched_filters : [];
  let base = 50 + m.length * 8;
  if (m.includes('strong_buy') || m.includes('strong_sell')) base += 18;
  if (m.includes('breakout') || m.includes('volume_spike')) base += 8;
  return Math.min(96, Math.round(base));
}
function _signalBadge(sig) {
  const up = /buy|oversold|gap up|breakout|52w high/i.test(sig) && !/sell/i.test(sig);
  const down = /sell|overbought|gap down|breakdown|52w low/i.test(sig);
  const clr = up ? 'var(--green)' : down ? 'var(--red)' : 'var(--yellow)';
  const bg = up ? 'rgba(16,185,129,.14)' : down ? 'rgba(239,68,68,.14)' : 'rgba(245,158,11,.14)';
  return `<span class="scan-sig" style="color:${clr};background:${bg};border-color:${clr}55">${STSafe.html(sig)}</span>`;
}

/* ── Save/load a scan preset (per-browser, like Auto-Generate's AG_KEY) ── */
const SCAN_PRESET_KEY = 'scanner_preset_v1';

function saveScanPreset() {
  try {
    localStorage.setItem(SCAN_PRESET_KEY, JSON.stringify({
      market: document.getElementById('scanMarket').value,
      timeframe: document.getElementById('scanTf').value,
      minConf: document.getElementById('scanConf').value,
      filters: [..._active],
    }));
    _notify('Scan preset saved', 'success');
  } catch (e) {
    _notify('Could not save preset', 'error');
  }
}

function loadScanPreset() {
  try {
    const p = JSON.parse(localStorage.getItem(SCAN_PRESET_KEY) || 'null');
    if (!p) return;
    const marketEl = document.getElementById('scanMarket');
    const timeframeEl = document.getElementById('scanTf');
    if (p.market && [...marketEl.options].some(option => option.value === p.market)) marketEl.value = p.market;
    if (p.timeframe && [...timeframeEl.options].some(option => option.value === p.timeframe)) timeframeEl.value = p.timeframe;
    if (p.minConf !== undefined) {
      const minConf = _num(p.minConf, NaN);
      if (Number.isInteger(minConf) && minConf >= 0 && minConf <= 100) {
        document.getElementById('scanConf').value = minConf;
        document.getElementById('scanConfVal').textContent = minConf + '%';
      }
    }
    (Array.isArray(p.filters) ? p.filters : []).filter(f => Object.prototype.hasOwnProperty.call(FILTER_META, f)).forEach(f => {
      _active.add(f);
      document.querySelector(`.scan-chip[data-f="${f}"]`)?.classList.add('active');
    });
  } catch (e) {}
}

/* ── Run scan ── */
async function runScan() {
  if (_scanInFlight) return;
  _scanInFlight = true;
  const btn = document.getElementById('runScan');
  const filters = [...new Set([..._active].map(f => ALIAS[f] || f))];
  if (!filters.length) filters.push('strong_buy', 'strong_sell', 'breakout', 'volume_spike');
  const market = document.getElementById('scanMarket').value;
  const timeframe = document.getElementById('scanTf').value;
  if (btn) { btn.disabled = true; btn.setAttribute('aria-busy', 'true'); btn.innerHTML = '<i class="bi bi-hourglass-split me-1"></i>Scanning...'; }
  sset('scanStatus', 'Scanning markets...');
  const tb = document.getElementById('scanBody');
  tb.innerHTML = '<tr><td colspan="11" class="text-center text-muted py-5"><i class="bi bi-hourglass-split d-block mb-2" style="font-size:24px"></i>Scanning markets…</td></tr>';
  let data = null;
  try {
    data = await API.post('/scanner/run', { filters, market, timeframe });
    if (!data || data.error || !Array.isArray(data.results)) throw new Error('Scanner unavailable');
  } catch (error) {
    _results = [];
    _scannedCount = 0;
    const failedBody = document.getElementById('scanBody');
    if (failedBody) failedBody.innerHTML = '<tr><td colspan="11" class="text-center text-muted py-5"><i class="bi bi-exclamation-triangle d-block mb-2" style="font-size:24px"></i>Scanner data is temporarily unavailable. Try again.</td></tr>';
    sset('scanStatus', 'Unable to run scan');
    _notify('Scanner is temporarily unavailable', 'error');
    return;
  } finally {
    _scanInFlight = false;
    if (btn) { btn.disabled = false; btn.removeAttribute('aria-busy'); btn.innerHTML = '<i class="bi bi-play-fill me-1"></i>Run Scan'; }
  }
  _results = (data?.results || []).map(r => ({ ...r, signal: _deriveSignal(r.matched_filters || []), confidence: _deriveConfidence(r) }));
  _scannedCount = data?.scanned ?? _results.length;
  renderResults();
  sset('scanStatus', `${_results.length} matches found`);
  const updated = new Date().toLocaleTimeString('en-IN', {timeZone:'Asia/Kolkata', hour:'2-digit', minute:'2-digit'});
  sset('scanUpdatedAt', 'Updated ' + updated);
  loadScanKPIs().then(ok => { if (!ok) sset('scanStatus', 'Results loaded; summary data unavailable'); });
}

function renderResults() {
  const minConf = parseInt(document.getElementById('scanConf').value, 10) || 0;
  const rows = _results.filter(r => _num(r.confidence) >= minConf).sort((a, b) => _num(b.confidence) - _num(a.confidence));
  sset('kpiResults', rows.length);
  sset('kpiResultsSub', 'of ' + _scannedCount + ' scanned');
  sset('kpiStrong', rows.filter(r => (r.matched_filters || []).some(f => f.startsWith('strong'))).length);
  sset('resultCount', rows.length + ' results');
  const tb = document.getElementById('scanBody');
  if (!rows.length) { tb.innerHTML = '<tr><td colspan="11" class="text-center text-muted py-5"><i class="bi bi-inbox d-block mb-2" style="font-size:24px"></i>No matches — loosen your filters or lower Min Confidence</td></tr>'; return; }
  tb.innerHTML = rows.map(r => {
    const changePct = _num(r.change_pct);
    const up = changePct >= 0; const conf = Math.min(100, Math.max(0, _num(r.confidence)));
    const confClr = conf >= 80 ? 'var(--green)' : conf >= 65 ? 'var(--accent-light)' : conf >= 50 ? 'var(--yellow)' : 'var(--red)';
    const aid = STSafe.assetId(_symbolIds[r.symbol]);
    const icons = (Array.isArray(r.matched_filters) ? r.matched_filters : []).slice(0, 4).map(f => { const m = FILTER_META[f]; return m ? `<i class="bi bi-${m.icon} mf-ico" style="color:${m.clr}" title="${STSafe.html(m.label)}"></i>` : ''; }).join('');
    return `<tr>
      <td><i class="bi bi-star scan-star" data-sym="${STSafe.html(r.symbol)}" style="cursor:pointer;color:var(--text-muted)"></i></td>
      <td>${aid ? `<a href="${STSafe.assetHref(aid)}" class="asset-cell-name" style="text-decoration:none">${STSafe.html(r.symbol)}</a>` : `<span class="asset-cell-name">${STSafe.html(r.symbol)}</span>`}</td>
      <td><span class="badge-tag">${STSafe.html(String(r.market || '').replace('_', ' '))}</span></td>
      <td class="num">${formatPrice(r.price, r.market)}</td>
      <td class="num" style="color:${up ? 'var(--green)' : 'var(--red)'};font-weight:700">${up ? '▲' : '▼'} ${Math.abs(changePct).toFixed(2)}%</td>
      <td class="num">${r.rsi != null && Number.isFinite(_num(r.rsi, NaN)) ? _num(r.rsi).toFixed(1) : '—'}</td>
      <td class="num">${r.volume ? _abbr(_num(r.volume)) : '—'}</td>
      <td>${_signalBadge(r.signal)}</td>
      <td style="min-width:120px"><div style="font-weight:700;color:${confClr};font-size:12px">${conf}%</div><div class="confidence-bar"><div class="confidence-fill" style="width:${conf}%;background:${confClr}"></div></div></td>
      <td><div class="mf-icons">${icons || '<span class="text-muted">—</span>'}</div></td>
      <td><div class="scan-actions">${aid ? `<a href="${STSafe.assetHref(aid)}" class="scan-act" title="View"><i class="bi bi-eye"></i></a>` : ''}<span class="scan-act scan-add" data-sym="${STSafe.html(r.symbol)}" title="Add to watchlist"><i class="bi bi-plus-lg"></i></span></div></td>
    </tr>`;
  }).join('');
  tb.querySelectorAll('.scan-star').forEach(s => s.addEventListener('click', function () { this.classList.toggle('bi-star'); this.classList.toggle('bi-star-fill'); this.style.color = this.classList.contains('bi-star-fill') ? 'var(--yellow)' : 'var(--text-muted)'; }));
  tb.querySelectorAll('.scan-add').forEach(a => a.addEventListener('click', () => _addWatch(a.dataset.sym)));
}

function _abbr(n) { if (n >= 1e9) return (n / 1e9).toFixed(2) + 'B'; if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M'; if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K'; return Math.round(n); }
async function _addWatch(sym) {
  const id = STSafe.assetId(_symbolIds[sym]);
  if (!id) return;
  const res = await API.post('/watchlist/', { asset_id: Number(id) });
  if (res && !res.error) _notify(`${sym} added to watchlist`, 'success');
  else _notify(res?.error || 'Could not add asset to watchlist', 'error');
}

/* ── init ── */
document.addEventListener('app:ready', async () => {
  if (_scanBooted) return;
  _scanBooted = true;
  await populateMarketSelect(document.getElementById('scanMarket'), { includeAll: true });
  sset('scanStatus', 'Ready to scan');
  loadScanKPIs().then(ok => { if (!ok) sset('scanStatus', 'Ready; summary data unavailable'); });
  const assets = await API.get('/assets/').catch(() => null);
  (Array.isArray(assets?.assets) ? assets.assets : []).forEach(a => {
    if (a?.symbol) _symbolIds[a.symbol] = STSafe.assetId(a.id);
  });

  document.querySelectorAll('.scan-chip').forEach(c => c.addEventListener('click', () => {
    const f = c.dataset.f; if (_active.has(f)) { _active.delete(f); c.classList.remove('active'); } else { _active.add(f); c.classList.add('active'); }
  }));
  document.getElementById('runScan').addEventListener('click', runScan);
  document.getElementById('clearFilters').addEventListener('click', () => { _active.clear(); document.querySelectorAll('.scan-chip').forEach(c => c.classList.remove('active')); });
  document.getElementById('scanConf').addEventListener('input', function () { document.getElementById('scanConfVal').textContent = this.value + '%'; if (_results.length) renderResults(); });
  document.getElementById('advToggle').addEventListener('click', function () { const i = this.querySelector('i'); i.classList.toggle('bi-chevron-right'); i.classList.toggle('bi-chevron-down'); _notify('Advanced filters coming soon', 'info'); });
  document.getElementById('savePreset').addEventListener('click', saveScanPreset);
  document.getElementById('dlResults').addEventListener('click', () => {
    if (!_results.length) return;
    const hdr = 'Symbol,Market,Price,Change%,RSI,Volume,Signal,Confidence,Matched\n';
    const csvCell = value => {
      let text = String(value ?? '');
      if (typeof value === 'string' && /^[=+\-@]/.test(text)) text = `'${text}`;
      return `"${text.replace(/"/g, '""')}"`;
    };
    const csv = hdr + _results.map(r => [r.symbol, r.market, r.price, r.change_pct, r.rsi, r.volume, r.signal, r.confidence, (Array.isArray(r.matched_filters) ? r.matched_filters : []).join('|')].map(csvCell).join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv' }); const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'scan_results.csv'; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 0);
  });
  loadScanPreset();
  // auto-run once with the loaded preset, or defaults if none was saved
  runScan();
});
