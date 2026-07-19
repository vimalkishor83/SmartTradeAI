/* ═══════════════════════════════════════════════
   Market Scanner — SmartTrade AI
   ═══════════════════════════════════════════════ */
let _active = new Set();
let _results = [];
let _symbolIds = {};
const sset = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = (v ?? '—'); };
const sfmt = (n, d = 2) => (n == null || isNaN(n)) ? '—' : (+n).toFixed(d);
const _scv = (n, f) => (getComputedStyle(document.documentElement).getPropertyValue(n) || f).trim();

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
  const [perf, pnl, heat] = await Promise.all([API.get('/signals/performance'), API.get('/signals/open-pnl'), API.get('/market-data/heatmap')]);
  const ov = perf?.overall || {};
  sset('kpiWin', ov.win_rate != null ? ov.win_rate.toFixed(1) + '%' : '—');
  sset('kpiWinSub', 'n = ' + (ov.total_closed ?? 0));
  if (Array.isArray(pnl) && pnl.length) {
    const avg = pnl.reduce((s, r) => s + (r.pnl_pct || 0), 0) / pnl.length;
    const el = document.getElementById('kpiPnl'); if (el) { el.textContent = (avg >= 0 ? '+' : '') + avg.toFixed(2) + '%'; el.className = 'kpi-value ' + (avg >= 0 ? 'text-green' : 'text-red'); }
    sset('kpiPnlSub', pnl.length + ' open');
  } else sset('kpiPnl', '—');
  const rows = heat?.heatmap || [];
  if (rows.length) {
    const ch = rows.map(r => r.change_pct || 0); const avg = ch.reduce((a, b) => a + b, 0) / ch.length;
    const std = Math.sqrt(ch.reduce((a, b) => a + (b - avg) ** 2, 0) / ch.length);
    const score = Math.round(Math.max(0, Math.min(100, 50 + avg * 12)));
    const slbl = score >= 55 ? 'Bullish' : score >= 45 ? 'Neutral' : 'Bearish';
    const bull = rows.filter(r => (r.change_pct || 0) > 0.1).length; const bear = rows.filter(r => (r.change_pct || 0) < -0.1).length;
    const se = document.getElementById('kpiSent'); if (se) { se.textContent = `${slbl} (${score})`; se.className = 'kpi-value ' + (score >= 55 ? 'text-green' : score >= 45 ? 'text-yellow' : 'text-red'); }
    sset('kpiSentSub', `Bull ${Math.round(bull / rows.length * 100)}% · Bear ${Math.round(bear / rows.length * 100)}%`);
    const vlbl = std > 2 ? 'High' : std > 1 ? 'Moderate' : 'Low';
    const ve = document.getElementById('kpiVol'); if (ve) { ve.textContent = vlbl; ve.className = 'kpi-value ' + (std > 2 ? 'text-red' : std > 1 ? 'text-yellow' : 'text-green'); }
    sset('kpiVolSub', 'σ ' + std.toFixed(2) + '%');
  }
}

/* ── derive signal + confidence from matched filters ── */
function _deriveSignal(matched) {
  const order = ['strong_buy', 'strong_sell', 'breakout', 'breakdown', 'rsi_oversold', 'rsi_overbought', 'volume_spike', 'gap_up', 'gap_down', '52w_high', '52w_low'];
  const first = order.find(f => matched.includes(f)) || matched[0];
  return FILTER_META[first]?.sig || 'Match';
}
function _deriveConfidence(r) {
  const m = r.matched_filters || [];
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
  return `<span class="scan-sig" style="color:${clr};background:${bg};border-color:${clr}55">${sig}</span>`;
}

/* ── Run scan ── */
async function runScan() {
  const btn = document.getElementById('runScan');
  const filters = [...new Set([..._active].map(f => ALIAS[f] || f))];
  if (!filters.length) filters.push('strong_buy', 'strong_sell', 'breakout', 'volume_spike');
  const market = document.getElementById('scanMarket').value;
  const timeframe = document.getElementById('scanTf').value;
  if (btn) { btn.disabled = true; btn.innerHTML = '<i class="bi bi-hourglass-split me-1"></i>Scanning…'; }
  const tb = document.getElementById('scanBody');
  tb.innerHTML = '<tr><td colspan="11" class="text-center text-muted py-5"><i class="bi bi-hourglass-split d-block mb-2" style="font-size:24px"></i>Scanning markets…</td></tr>';
  const data = await API.post('/scanner/run', { filters, market, timeframe }).catch(() => null);
  if (btn) { btn.disabled = false; btn.innerHTML = '<i class="bi bi-play-fill me-1"></i>Run Scan'; }
  _results = (data?.results || []).map(r => ({ ...r, signal: _deriveSignal(r.matched_filters || []), confidence: _deriveConfidence(r) }));
  renderResults();
  loadScanKPIs();
}

function renderResults() {
  const minConf = parseInt(document.getElementById('scanConf').value, 10) || 0;
  const rows = _results.filter(r => r.confidence >= minConf).sort((a, b) => b.confidence - a.confidence);
  sset('kpiResults', rows.length);
  sset('kpiResultsSub', 'of ' + _results.length + ' scanned');
  sset('kpiStrong', rows.filter(r => (r.matched_filters || []).some(f => f.startsWith('strong'))).length);
  sset('resultCount', rows.length + ' results');
  const tb = document.getElementById('scanBody');
  if (!rows.length) { tb.innerHTML = '<tr><td colspan="11" class="text-center text-muted py-5"><i class="bi bi-inbox d-block mb-2" style="font-size:24px"></i>No matches — loosen your filters or lower Min Confidence</td></tr>'; return; }
  tb.innerHTML = rows.map(r => {
    const up = (r.change_pct || 0) >= 0; const conf = r.confidence;
    const confClr = conf >= 80 ? 'var(--green)' : conf >= 65 ? 'var(--accent-light)' : conf >= 50 ? 'var(--yellow)' : 'var(--red)';
    const aid = _symbolIds[r.symbol];
    const icons = (r.matched_filters || []).slice(0, 4).map(f => { const m = FILTER_META[f]; return m ? `<i class="bi bi-${m.icon} mf-ico" style="color:${m.clr}" title="${m.label}"></i>` : ''; }).join('');
    return `<tr>
      <td><i class="bi bi-star scan-star" data-sym="${r.symbol}" style="cursor:pointer;color:var(--text-muted)"></i></td>
      <td>${aid ? `<a href="/asset/${aid}" class="asset-cell-name" style="text-decoration:none">${r.symbol}</a>` : `<span class="asset-cell-name">${r.symbol}</span>`}</td>
      <td><span class="badge-tag">${(r.market || '').replace('_', ' ')}</span></td>
      <td class="num">${formatPrice(r.price, r.market)}</td>
      <td class="num" style="color:${up ? 'var(--green)' : 'var(--red)'};font-weight:700">${up ? '▲' : '▼'} ${Math.abs(r.change_pct || 0).toFixed(2)}%</td>
      <td class="num">${r.rsi != null ? r.rsi.toFixed(1) : '—'}</td>
      <td class="num">${r.volume ? _abbr(r.volume) : '—'}</td>
      <td>${_signalBadge(r.signal)}</td>
      <td style="min-width:120px"><div style="font-weight:700;color:${confClr};font-size:12px">${conf}%</div><div class="confidence-bar"><div class="confidence-fill" style="width:${conf}%;background:${confClr}"></div></div></td>
      <td><div class="mf-icons">${icons || '<span class="text-muted">—</span>'}</div></td>
      <td><div class="scan-actions">${aid ? `<a href="/asset/${aid}" class="scan-act" title="View"><i class="bi bi-eye"></i></a>` : ''}<span class="scan-act scan-add" data-sym="${r.symbol}" title="Add to watchlist"><i class="bi bi-plus-lg"></i></span></div></td>
    </tr>`;
  }).join('');
  tb.querySelectorAll('.scan-star').forEach(s => s.addEventListener('click', function () { this.classList.toggle('bi-star'); this.classList.toggle('bi-star-fill'); this.style.color = this.classList.contains('bi-star-fill') ? 'var(--yellow)' : 'var(--text-muted)'; }));
  tb.querySelectorAll('.scan-add').forEach(a => a.addEventListener('click', () => _addWatch(a.dataset.sym)));
}

function _abbr(n) { if (n >= 1e9) return (n / 1e9).toFixed(2) + 'B'; if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M'; if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K'; return Math.round(n); }
async function _addWatch(sym) { const id = _symbolIds[sym]; if (!id) return; await API.post('/watchlist/', { asset_id: id }).catch(() => { }); if (typeof toast === 'function') toast(sym + ' added to watchlist', 'success'); }

/* ── init ── */
document.addEventListener('app:ready', async () => {
  loadScanKPIs();
  const assets = await API.get('/assets/').catch(() => null);
  (assets?.assets || []).forEach(a => { _symbolIds[a.symbol] = a.id; });

  document.querySelectorAll('.scan-chip').forEach(c => c.addEventListener('click', () => {
    const f = c.dataset.f; if (_active.has(f)) { _active.delete(f); c.classList.remove('active'); } else { _active.add(f); c.classList.add('active'); }
  }));
  document.getElementById('runScan').addEventListener('click', runScan);
  document.getElementById('clearFilters').addEventListener('click', () => { _active.clear(); document.querySelectorAll('.scan-chip').forEach(c => c.classList.remove('active')); });
  document.getElementById('scanConf').addEventListener('input', function () { document.getElementById('scanConfVal').textContent = this.value + '%'; if (_results.length) renderResults(); });
  document.getElementById('advToggle').addEventListener('click', function () { const i = this.querySelector('i'); i.classList.toggle('bi-chevron-right'); i.classList.toggle('bi-chevron-down'); if (typeof toast === 'function') toast('Advanced filters coming soon', 'info'); });
  document.getElementById('savePreset').addEventListener('click', () => { if (typeof toast === 'function') toast('Scan preset saved', 'success'); });
  document.getElementById('dlResults').addEventListener('click', () => {
    if (!_results.length) return;
    const hdr = 'Symbol,Market,Price,Change%,RSI,Volume,Signal,Confidence,Matched\n';
    const csv = hdr + _results.map(r => [r.symbol, r.market, r.price, r.change_pct, r.rsi, r.volume, r.signal, r.confidence, (r.matched_filters || []).join('|')].join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv' }); const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'scan_results.csv'; a.click();
  });
  // auto-run once with defaults
  runScan();
});
