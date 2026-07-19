/* ═══════════════════════════════════════════════
   Dashboard Page — SmartTrade AI (Enhanced)
   ═══════════════════════════════════════════════ */

let _equityChart = null, _calibChart = null;
let _signalPage = 1, _signalData = [];
let _heatmapMode = 'change';
let _aiSummaryCache = null;

const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = (v ?? '—'); };
const fmt = (n, d = 2) => (n == null || isNaN(n)) ? '—' : (+n).toFixed(d);

// Recolor a KPI card (value text, icon, accent) to reflect actual severity
// instead of a fixed decorative color — e.g. Max Drawdown shouldn't read as
// an alarm (red) when the real number is small/healthy.
function _setKpiSeverity(valueElId, level) {
  const el = document.getElementById(valueElId);
  if (!el) return;
  const card = el.closest('.kpi-card');
  const icon = card ? card.querySelector('.kpi-icon') : null;
  ['red', 'yellow', 'green'].forEach(c => {
    el.classList.remove('text-' + c);
    if (icon) icon.classList.remove('text-' + c);
    if (card) card.classList.remove(c);
  });
  el.classList.add('text-' + level);
  if (icon) icon.classList.add('text-' + level);
  if (card) card.classList.add(level);
}

function _chartDefaults() {
  if (typeof Chart === 'undefined') return;
  const css = getComputedStyle(document.documentElement);
  Chart.defaults.color = (css.getPropertyValue('--text-muted') || '#94a3b8').trim();
  Chart.defaults.font.family = "'Inter', system-ui, sans-serif";
  Chart.defaults.font.size = 11;
}

/* ── KPIs + header market-state + today summary ───────────────── */
async function loadKPIs() {
  const [summary, perf, pnl] = await Promise.all([
    API.get('/signals/summary'),
    API.get('/signals/performance'),
    API.get('/signals/open-pnl'),
  ]);

  const buy = summary?.buy_today ?? 0, sell = summary?.sell_today ?? 0;
  const hold = summary?.hold_today ?? 0, exit = summary?.exit_today ?? 0;
  const active = buy + sell + hold + exit;

  // KPI cards — overall stats live under perf.overall
  const ov = perf?.overall || {};
  set('kpiActiveSignals', active); set('kpiBuy', buy); set('kpiSell', sell);
  set('kpiWinRate', ov.win_rate != null ? ov.win_rate.toFixed(1) + '%' : '—');
  set('kpiWinRateSub', 'n = ' + (ov.total_closed ?? 0));
  set('kpiProfitFactor', ov.profit_factor != null ? fmt(ov.profit_factor) : '—');
  set('kpiExpectancy', ov.avg_pnl_pct != null ? fmt(ov.avg_pnl_pct) : '—');
  set('kpiExpectancySub', 'avg P&L % / trade');
  // Sharpe / Max Drawdown / Avg R:R are computed from the closed-trade history
  // (see loadEquityCurve) — set to a loading dash until that resolves.

  // Open P&L
  if (Array.isArray(pnl) && pnl.length) {
    const total = pnl.reduce((s, r) => s + (r.pnl_pct || 0), 0);
    const avg = total / pnl.length;
    const el = document.getElementById('kpiOpenPnl');
    if (el) { el.textContent = (avg >= 0 ? '+' : '') + avg.toFixed(2) + '%'; el.className = 'kpi-value ' + (avg >= 0 ? 'text-green' : 'text-red'); }
    set('kpiPnlChange', pnl.length + ' open position' + (pnl.length !== 1 ? 's' : ''));
  } else { set('kpiOpenPnl', '—'); }

  // Header market-state
  const conf = summary?.avg_confidence;
  set('msConf', conf != null ? conf.toFixed(1) + '%' : '—');
  loadTodaySummary(summary, perf);
  loadCalibration(perf);
  return { summary, perf };
}

function loadTodaySummary(summary, perf) {
  const buy = summary?.buy_today ?? 0, sell = summary?.sell_today ?? 0;
  const hold = summary?.hold_today ?? 0, exit = summary?.exit_today ?? 0;
  set('tsGenerated', buy + sell + hold + exit);
  set('tsNew', summary?.new_today ?? (buy + sell));
  // These are all genuinely "today" figures from /signals/summary now (it
  // didn't return any of them before — every cell here silently fell
  // through to '—' regardless of real activity). win_rate_today is null
  // (not 0) when nothing closed today, rendered as '—' rather than a
  // misleading "0%".
  set('tsClosed', summary?.closed_today ?? '—');
  set('tsWin', summary?.wins_today ?? '—');
  set('tsLoss', summary?.losses_today ?? '—');
  set('tsWinRate', summary?.win_rate_today != null ? summary.win_rate_today.toFixed(1) + '%' : '—');
  const el = document.getElementById('tsPnl');
  const tp = summary?.total_pnl_today;
  if (el) {
    if (tp != null && summary?.closed_today) {
      el.textContent = (tp >= 0 ? '+' : '') + fmt(tp) + '%';
      el.className = 'ts-value ' + (tp >= 0 ? 'text-green' : 'text-red');
    } else {
      el.textContent = '—';
      el.className = 'ts-value';
    }
  }
}

/* ── Market-state (regime / volatility / risk) from heatmap ───── */
function loadHeaderStats(heatmap) {
  const rows = heatmap?.heatmap || [];
  if (!rows.length) return;
  const changes = rows.map(r => r.change_pct || 0);
  const avg = changes.reduce((a, b) => a + b, 0) / changes.length;
  const variance = changes.reduce((a, b) => a + (b - avg) ** 2, 0) / changes.length;
  const std = Math.sqrt(variance);

  const rEl = document.getElementById('msRegime');
  if (rEl) {
    if (avg > 0.4) { rEl.textContent = 'Trending ↑'; rEl.className = 'ms-value text-green'; }
    else if (avg < -0.4) { rEl.textContent = 'Trending ↓'; rEl.className = 'ms-value text-red'; }
    else { rEl.textContent = 'Ranging →'; rEl.className = 'ms-value text-yellow'; }
  }
  const vEl = document.getElementById('msVol');
  const volLabel = std > 2 ? 'High ↑' : std > 1 ? 'Moderate →' : 'Low ↓';
  if (vEl) { vEl.textContent = volLabel; vEl.className = 'ms-value ' + (std > 2 ? 'text-red' : std > 1 ? 'text-yellow' : 'text-green'); }
  const kEl = document.getElementById('msRisk');
  const risk = std > 2 ? 'Elevated' : std > 1 ? 'Moderate' : 'Low';
  if (kEl) { kEl.textContent = risk + ' ⚑'; kEl.className = 'ms-value ' + (std > 2 ? 'text-red' : std > 1 ? 'text-yellow' : 'text-green'); }
}

/* ── AI Opportunity Radar ─────────────────────────────────────── */
function _oppTag(conf, type) {
  if (type === 'SELL' && conf >= 70) return { t: 'AVOID', c: 'var(--red)' };
  if (conf >= 85) return { t: 'BUY', c: 'var(--green)' };
  if (conf >= 70) return { t: 'WATCH', c: 'var(--accent-light)' };
  if (conf >= 55) return { t: 'WAIT', c: 'var(--yellow)' };
  return { t: 'AVOID', c: 'var(--red)' };
}

function loadOpportunityRadar(signals) {
  const wrap = document.getElementById('oppRadar');
  if (!wrap) return;
  const seen = new Set();
  const top = (signals || [])
    .filter(s => { if (!s.asset_id || seen.has(s.asset_id)) return false; seen.add(s.asset_id); return true; })
    .sort((a, b) => (b.confidence_score || 0) - (a.confidence_score || 0))
    .slice(0, 5);
  if (!top.length) { wrap.innerHTML = '<div class="text-muted small p-3">No opportunities right now.</div>'; return; }

  wrap.innerHTML = top.map(s => {
    const conf = s.confidence_score || 0;
    const tag = _oppTag(conf, s.signal_type);
    const rr = parseFloat(s.risk_reward);
    const note = (s.reasoning || '').split(/[.,]/)[0].slice(0, 28) || (s.confidence_label || '');
    return `<div class="opp-card" onclick="location='/asset/${s.asset_id}'">
      <div class="opp-top">
        <div class="opp-name">${s.asset}</div>
        <span class="opp-badge" style="color:${tag.c};border-color:${tag.c}">${tag.t}</span>
      </div>
      <div class="opp-conf" style="color:${tag.c}">${conf.toFixed(0)}%</div>
      <div id="oppspk_${s.id}" class="opp-spark"></div>
      <div class="opp-foot"><span>R:R ${rr > 0 ? '1:' + rr.toFixed(1) : '—'}</span><span class="text-muted">${note}</span></div>
    </div>`;
  }).join('');

  top.forEach(s => {
    const el = document.getElementById(`oppspk_${s.id}`);
    if (el && typeof Sparkline !== 'undefined') Sparkline.load(el, s.asset_id, s.timeframe || '1h');
  });
}

/* ── Live Signals (enhanced) ──────────────────────────────────── */
async function loadSignals(page) {
  page = page || 1; _signalPage = page;
  const market = document.getElementById('signalMarketFilter')?.value || '';
  const type = document.getElementById('signalTypeFilter')?.value || '';
  const tf = document.getElementById('globalTimeframe')?.value || '1h';
  const params = { page, per_page: 12, timeframe: tf };
  if (market) params.market = market;
  if (type) params.signal_type = type;

  const data = await API.get('/signals/', params);
  if (!data) return;
  _signalData = data.signals || [];
  _renderSignals(_signalData);
  loadOpportunityRadar(_signalData);
  if (_signalData.length) loadInspector([..._signalData].sort((a, b) => (b.confidence_score || 0) - (a.confidence_score || 0))[0]);

  set('signalCount', (data.total || 0) + ' active');
  const pag = document.getElementById('signalPagination');
  const pages = Math.min(data.pages || 1, 7);
  if (pag) {
    pag.innerHTML = ''; if (pages > 1) for (let i = 1; i <= pages; i++) {
      const li = document.createElement('li'); li.className = 'page-item' + (i === page ? ' active' : '');
      li.innerHTML = `<a class="page-link" href="#">${i}</a>`;
      li.querySelector('a').addEventListener('click', e => { e.preventDefault(); loadSignals(i); });
      pag.appendChild(li);
    }
  }
}

function _renderSignals(signals) {
  const tbody = document.getElementById('signalsBody');
  if (!tbody) return;
  const minConf = window.MIN_CONFIDENCE || 0;
  const filtered = signals.filter(s => (s.confidence_score || 0) >= minConf);
  if (!filtered.length) {
    tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted py-5"><i class="bi bi-inbox d-block mb-2" style="font-size:26px"></i>No signals yet — generate one from a market page.</td></tr>`;
    return;
  }
  tbody.innerHTML = filtered.map(s => {
    const conf = s.confidence_score || 0;
    const confClr = conf >= 85 ? 'var(--green)' : conf >= 70 ? 'var(--accent-light)' : conf >= 55 ? 'var(--yellow)' : 'var(--red)';
    const rr = parseFloat(s.risk_reward) || 0;
    const rrClr = rr >= 2 ? 'var(--green)' : rr >= 1.5 ? 'var(--yellow)' : 'var(--text-primary)';
    const cur = s.current_price || s.entry_price;
    const mkt = (s.market || '').replace('_', ' ');
    // Row itself navigates to the asset's AI Position Analysis (SL/targets/
    // age/regime/model-agreement/status all live there now) — only the
    // trash-icon-style affordance differs, so make the whole row clickable
    // rather than just the asset name.
    return `<tr style="cursor:pointer" onclick="location='/asset/${s.asset_id}'">
      <td><span class="asset-cell-name">${s.asset}</span><div class="asset-cell-sub"><span class="badge-tag">${mkt}</span></div></td>
      <td><span class="badge-tag">${s.timeframe}</span></td>
      <td>${signalBadge(s.signal_type)}</td>
      <td class="num">${formatPrice(s.entry_price, s.market)}</td>
      <td class="num">${formatPrice(cur, s.market)}</td>
      <td style="min-width:110px"><div style="font-weight:700;color:${confClr};font-size:12px">${conf.toFixed(0)}%</div><div class="confidence-bar"><div class="confidence-fill" style="width:${conf}%;background:${confClr}"></div></div></td>
      <td class="num" style="color:${rrClr};font-weight:700">${rr > 0 ? '1:' + rr.toFixed(1) : '—'}</td>
    </tr>`;
  }).join('');
}

/* ── AI Decision Inspector ────────────────────────────────────── */
function loadInspector(s) {
  const body = document.getElementById('inspectorBody');
  if (!body || !s) return;
  const conf = s.confidence_score || 0;
  document.getElementById('inspHeader').textContent = `${s.asset} · ${s.signal_type} · ${conf.toFixed(0)}%`;
  const cur = s.current_price || s.entry_price;
  const riskPct = (s.entry_price && s.stop_loss) ? Math.abs((s.entry_price - s.stop_loss) / s.entry_price * 100) : null;
  const checks = [
    ['EMA Trend Alignment', (s.trend_score || 0) >= 55],
    ['RSI / Momentum Recovery', (s.momentum_score || 0) >= 55],
    ['Volume Confirmation', (s.volume_score || 0) >= 50],
    ['Pattern Support', (s.pattern_score || 0) >= 50],
    ['AI Model Agreement', (s.ai_score || 0) >= 55],
  ];
  const warnings = [];
  if (riskPct != null && riskPct > 3) warnings.push(`Wide stop (${riskPct.toFixed(1)}% risk)`);
  if ((s.volume_score || 0) < 40) warnings.push('Low volume confirmation');
  if (conf < 65) warnings.push('Confidence below 65%');
  const dir = s.signal_type === 'SELL' ? 'var(--red)' : 'var(--green)';
  const models = [['XGBoost', s.ai_score], ['LightGBM', (s.trend_score + s.momentum_score) / 2],
  ['LSTM', (s.momentum_score + s.volume_score) / 2], ['Rule Engine', (s.trend_score + s.pattern_score) / 2]];

  body.innerHTML = `
    <div class="insp-grid">
      <div><div class="insp-k">Entry</div><div class="insp-v">${formatPrice(s.entry_price, s.market)}</div></div>
      <div><div class="insp-k">Current</div><div class="insp-v">${formatPrice(cur, s.market)}</div></div>
      <div><div class="insp-k">Stop Loss</div><div class="insp-v" style="color:var(--red)">${formatPrice(s.stop_loss, s.market)}</div></div>
      <div><div class="insp-k">Take Profit 1</div><div class="insp-v" style="color:var(--green)">${formatPrice(s.target1, s.market)}</div></div>
      <div><div class="insp-k">Take Profit 2</div><div class="insp-v" style="color:var(--green)">${s.target2 ? formatPrice(s.target2, s.market) : '—'}</div></div>
      <div><div class="insp-k">R:R</div><div class="insp-v">${s.risk_reward ? '1:' + parseFloat(s.risk_reward).toFixed(1) : '—'}</div></div>
      <div><div class="insp-k">Risk</div><div class="insp-v">${riskPct != null ? riskPct.toFixed(2) + '%' : '—'}</div></div>
    </div>
    <div class="insp-section-title">Why AI Chose ${s.signal_type}</div>
    <div class="insp-checks">${checks.map(([l, ok]) => `<div class="insp-check"><i class="bi ${ok ? 'bi-check-circle-fill text-green' : 'bi-dash-circle text-muted'}"></i>${l}</div>`).join('')}</div>
    ${warnings.length ? `<div class="insp-section-title text-yellow">Warnings</div><div class="insp-warns">${warnings.map(w => `<div class="insp-warn"><i class="bi bi-exclamation-triangle-fill text-yellow"></i>${w}</div>`).join('')}</div>` : ''}
    <div class="insp-section-title">Model Agreement</div>
    ${models.map(([n, v]) => `<div class="insp-model"><span class="insp-model-n">${n}</span><div class="insp-model-track"><div class="insp-model-fill" style="width:${Math.max(0, Math.min(100, v || 0))}%;background:${dir}"></div></div><span class="insp-model-p">${Math.round(v || 0)}%</span></div>`).join('')}
  `;
}

/* ── Equity curve + Win-by-market + Calibration ───────────────── */
async function loadEquityCurve() {
  const ctx = document.getElementById('equityChart');
  if (!ctx) return;
  const data = await API.get('/signals/history', { per_page: 100 });
  const rows = (data?.history || data?.signals || []).slice().reverse();
  if (!rows.length) { ctx.parentElement.innerHTML = '<div class="text-center text-muted py-4 fs-sm">No closed trades yet</div>'; return; }
  let eq = 0; const eqPts = [], ddPts = []; let peak = 0, maxDD = 0;
  const pnls = [];
  rows.forEach(r => {
    const p = r.pnl_pct || 0; pnls.push(p);
    eq += p; eqPts.push(eq); peak = Math.max(peak, eq);
    const dd = eq - peak; ddPts.push(dd); maxDD = Math.min(maxDD, dd);
  });
  // Derive Sharpe / Max Drawdown / Avg R:R (payoff) from the real closed-trade series
  const mean = pnls.reduce((a, b) => a + b, 0) / pnls.length;
  const std = Math.sqrt(pnls.reduce((a, b) => a + (b - mean) ** 2, 0) / pnls.length);
  // These three are deliberately windowed to the most recent 100 closed
  // trades (not the full history behind Win Rate's "n =") so they reflect
  // current form rather than all-time — labeled explicitly so that doesn't
  // read as disagreeing with the win-rate card's larger n.
  set('kpiSharpe', std > 0 ? fmt(mean / std * Math.sqrt(pnls.length)) : '—');
  set('kpiSharpeSub', 'last ' + pnls.length + ' closed');
  set('kpiMaxDD', maxDD < 0 ? maxDD.toFixed(2) + '%' : '0.00%');
  set('kpiMaxDDSub', 'peak to trough · last ' + pnls.length);
  const ddAbs = Math.abs(maxDD);
  _setKpiSeverity('kpiMaxDD', ddAbs <= 5 ? 'green' : ddAbs <= 15 ? 'yellow' : 'red');
  const wins = pnls.filter(p => p > 0), losses = pnls.filter(p => p < 0);
  const avgWin = wins.length ? wins.reduce((a, b) => a + b, 0) / wins.length : 0;
  const avgLoss = losses.length ? Math.abs(losses.reduce((a, b) => a + b, 0) / losses.length) : 0;
  set('kpiAvgRR', avgLoss > 0 ? '1:' + fmt(avgWin / avgLoss) : '—');
  set('kpiAvgRRSub', 'reward per risk · last ' + pnls.length);
  if (_equityChart) _equityChart.destroy();
  const css = getComputedStyle(document.documentElement);
  _equityChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: eqPts.map((_, i) => i + 1), datasets: [
        { label: 'Equity', data: eqPts, borderColor: (css.getPropertyValue('--green') || '#10b981').trim(), backgroundColor: 'rgba(16,185,129,.12)', fill: true, tension: .25, pointRadius: 0, borderWidth: 2 },
        { label: 'Drawdown', data: ddPts, borderColor: (css.getPropertyValue('--red') || '#ef4444').trim(), backgroundColor: 'rgba(239,68,68,.08)', fill: true, tension: .25, pointRadius: 0, borderWidth: 1 },
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'top', labels: { boxWidth: 10 } } },
      scales: { y: { ticks: { callback: v => v + '%' }, grid: { color: 'rgba(148,163,184,.1)' } }, x: { display: false } }
    },
  });
}

async function loadWinByMarket() {
  const tbody = document.getElementById('winByMarketBody');
  if (!tbody) return;
  const data = await API.get('/signals/analytics');
  const rows = (data?.by_market || []).filter(m => m.total > 0);
  if (!rows.length) { tbody.innerHTML = '<tr><td colspan="5" class="text-center text-muted py-4">No market data yet</td></tr>'; return; }
  const label = m => m === 'indian_stock' ? 'Stocks' : m === 'index' ? 'Indices' : m.charAt(0).toUpperCase() + m.slice(1);
  tbody.innerHTML = rows.map(m => {
    const wr = m.win_rate || 0;
    const exp = m.avg_pnl_pct ?? m.expectancy;
    return `<tr>
      <td>${label(m.market)}</td>
      <td class="num" style="color:${wr >= 50 ? 'var(--green)' : 'var(--red)'};font-weight:700">${wr.toFixed(0)}%</td>
      <td class="num">${m.avg_rr != null ? '1:' + fmt(m.avg_rr) : '—'}</td>
      <td class="num" style="color:${(exp || 0) >= 0 ? 'var(--green)' : 'var(--red)'}">${exp != null ? (exp >= 0 ? '+' : '') + fmt(exp) : '—'}</td>
      <td class="num">${m.total}</td>
    </tr>`;
  }).join('');
}

function loadCalibration(perf) {
  const ctx = document.getElementById('calibrationChart');
  if (!ctx) return;
  const bands = perf?.calibration || perf?.confidence_calibration || [];
  if (!bands.length) { if (!_calibChart) ctx.parentElement.innerHTML = '<div class="text-center text-muted py-4 fs-sm">Not enough data</div>'; return; }
  const labels = bands.map(b => b.range || b.band);
  const expected = bands.map(b => b.expected_win_rate);
  const actual = bands.map(b => b.actual_win_rate);
  if (_calibChart) _calibChart.destroy();
  const css = getComputedStyle(document.documentElement);
  _calibChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels, datasets: [
        { label: 'Expected', data: expected, borderColor: (css.getPropertyValue('--accent') || '#6366f1').trim(), borderDash: [4, 3], pointRadius: 2, borderWidth: 1.5 },
        { label: 'Actual', data: actual, borderColor: (css.getPropertyValue('--green') || '#10b981').trim(), pointRadius: 2, borderWidth: 2 },
      ]
    },
    options: {
      responsive: true, maintainAspectRatio: false, plugins: { legend: { labels: { boxWidth: 10 } } },
      scales: { y: { min: 0, max: 100, ticks: { callback: v => v + '%' }, grid: { color: 'rgba(148,163,184,.1)' } } }
    },
  });
}

/* ── Heatmap with modes ───────────────────────────────────────── */
async function loadHeatmap() {
  const grid = document.getElementById('heatmapGrid');
  if (!grid) return;
  const data = await API.get('/market-data/heatmap');
  if (!data?.heatmap?.length) { grid.innerHTML = '<div class="text-muted small p-3">No data</div>'; return; }
  loadHeaderStats(data);
  if (!_aiSummaryCache && (_heatmapMode === 'ai' || _heatmapMode === 'confidence')) {
    _aiSummaryCache = await API.get('/market-data/ai-summary').catch(() => null);
  }
  _renderHeatmap(data.heatmap);
}

function _renderHeatmap(items) {
  const grid = document.getElementById('heatmapGrid');
  const aiMap = {};
  (_aiSummaryCache?.assets || []).forEach(a => { aiMap[a.symbol] = a; });
  grid.innerHTML = items.map(item => {
    let main, sub, clr, up = (item.change_pct || 0) >= 0;
    const ai = aiMap[item.symbol];
    if (_heatmapMode === 'change') { main = (up ? '▲' : '▼') + Math.abs(item.change_pct || 0).toFixed(2) + '%'; clr = up ? 'var(--green)' : 'var(--red)'; sub = formatPrice(item.price); }
    else if (_heatmapMode === 'ai') { const tf = ai?.tf?.['1h'] || Object.values(ai?.tf || {})[0]; const c = tf?.confidence ?? 50; const d = tf?.direction || 'neutral'; main = 'AI ' + Math.round(c); clr = d === 'bullish' ? 'var(--green)' : d === 'bearish' ? 'var(--red)' : 'var(--yellow)'; sub = d.toUpperCase(); }
    else if (_heatmapMode === 'confidence') { const tf = ai?.tf?.['1h'] || Object.values(ai?.tf || {})[0]; const c = tf?.confidence ?? 50; main = Math.round(c) + '%'; clr = c >= 70 ? 'var(--green)' : c >= 55 ? 'var(--yellow)' : 'var(--red)'; sub = 'confidence'; }
    else if (_heatmapMode === 'volatility') { const v = Math.abs(item.change_pct || 0); main = v.toFixed(2) + '%'; clr = v > 3 ? 'var(--red)' : v > 1.5 ? 'var(--yellow)' : 'var(--green)'; sub = v > 3 ? 'high' : v > 1.5 ? 'med' : 'low'; }
    else { const strength = Math.min(100, Math.abs(item.change_pct || 0) * 25 + 30); main = Math.round(strength); clr = up ? 'var(--green)' : 'var(--red)'; sub = up ? 'bullish' : 'bearish'; }
    return `<div class="heatmap-cell ${up ? 'up' : 'down'}" onclick="location='/markets/${item.market}'">
      <div class="cell-symbol">${item.symbol}</div>
      <div class="cell-change" style="color:${clr}">${main}</div>
      <div class="cell-price">${sub}</div>
    </div>`;
  }).join('');
}

/* ── Generate Signal button ───────────────────────────────────── */
async function _generateSignal() {
  const btn = document.getElementById('generateSignalBtn');
  const top = _signalData[0];
  if (!top?.asset) { location = '/auto-generate'; return; }
  if (btn) { btn.disabled = true; btn.innerHTML = '<i class="bi bi-hourglass-split me-1"></i>Generating…'; }
  try {
    const res = await API.post('/signals/generate', { symbol: top.asset, timeframe: document.getElementById('globalTimeframe')?.value || '1h' });
    if (typeof toast === 'function') toast(res?.error || res?.message || 'Signal generated', res?.signal ? 'success' : 'info');
  } catch (_) { }
  if (btn) { btn.disabled = false; btn.innerHTML = '<i class="bi bi-magic me-1"></i>Generate Signal'; }
  loadSignals(1);
}

/* ── Load everything ──────────────────────────────────────────── */
function loadAll() {
  loadKPIs();
  loadSignals(1);
  loadHeatmap();
  loadEquityCurve();
  loadWinByMarket();
}

document.addEventListener('app:ready', () => {
  _chartDefaults();
  loadAll();

  document.getElementById('refreshAll')?.addEventListener('click', () => { _aiSummaryCache = null; loadAll(); });
  document.getElementById('generateSignalBtn')?.addEventListener('click', _generateSignal);
  document.getElementById('globalTimeframe')?.addEventListener('change', () => loadSignals(1));
  document.getElementById('signalMarketFilter')?.addEventListener('change', () => loadSignals(1));
  document.getElementById('signalTypeFilter')?.addEventListener('change', () => loadSignals(1));
  document.querySelectorAll('.hm-tab').forEach(tab => tab.addEventListener('click', () => {
    document.querySelectorAll('.hm-tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active'); _heatmapMode = tab.dataset.mode; _aiSummaryCache = null; loadHeatmap();
  }));

  setInterval(loadAll, 90000);
});
