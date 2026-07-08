/* ═══════════════════════════════════════════════
   Markets Overview — SmartTrade AI
   ═══════════════════════════════════════════════ */
let _filter = (typeof MARKET !== 'undefined' && MARKET) ? MARKET : '';
let _apChart = null, _consensusChart = null, _liveSignals = [];
const mset = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = (v ?? '—'); };
const mfmt = (n, d = 2) => (n == null || isNaN(n)) ? '—' : (+n).toFixed(d);
const _cv = (n, f) => (getComputedStyle(document.documentElement).getPropertyValue(n) || f).trim();
const mktLabel = m => m === 'indian_stock' ? 'Indian Stocks' : m === 'index' ? 'Indices' : m ? m.charAt(0).toUpperCase() + m.slice(1) : 'All';

/* ── KPIs + sentiment + volatility from heatmap/signals ── */
async function loadKPIs() {
  const [summary, perf, pnl, heat] = await Promise.all([
    API.get('/signals/summary'), API.get('/signals/performance'),
    API.get('/signals/open-pnl'), API.get('/market-data/heatmap'),
  ]);
  const ov = perf?.overall || {};
  const buy = summary?.buy_today ?? 0, sell = summary?.sell_today ?? 0, hold = summary?.hold_today ?? 0, exit = summary?.exit_today ?? 0;
  mset('kpiGen', buy + sell + hold + exit);
  mset('kpiActive', summary?.open_alerts ?? (buy + sell + hold + exit));
  mset('kpiWin', ov.win_rate != null ? ov.win_rate.toFixed(1) + '%' : '—');
  mset('kpiWinSub', 'n = ' + (ov.total ?? 0));
  if (Array.isArray(pnl) && pnl.length) {
    const avg = pnl.reduce((s, r) => s + (r.pnl_pct || 0), 0) / pnl.length;
    const el = document.getElementById('kpiPnl'); if (el) { el.textContent = (avg >= 0 ? '+' : '') + avg.toFixed(2) + '%'; el.className = 'kpi-value ' + (avg >= 0 ? 'text-green' : 'text-red'); }
    mset('kpiPnlSub', pnl.length + ' open');
  } else mset('kpiPnl', '—');

  // sentiment + volatility from heatmap — scoped to the selected market tab
  // (All Markets -> whole market; a specific tab -> that market only)
  const rows = (heat?.heatmap || []).filter(r => !_filter || r.market === _filter);
  if (rows.length) {
    const ch = rows.map(r => r.change_pct || 0);
    const avg = ch.reduce((a, b) => a + b, 0) / ch.length;
    const std = Math.sqrt(ch.reduce((a, b) => a + (b - avg) ** 2, 0) / ch.length);
    const score = Math.round(Math.max(0, Math.min(100, 50 + avg * 12)));
    const slbl = score >= 65 ? 'Bullish' : score >= 55 ? 'Slightly Bullish' : score >= 45 ? 'Neutral' : score >= 35 ? 'Slightly Bearish' : 'Bearish';
    const se = document.getElementById('kpiSent'); if (se) { se.textContent = `${slbl} (${score})`; se.className = 'kpi-value ' + (score >= 55 ? 'text-green' : score >= 45 ? 'text-yellow' : 'text-red'); }
    const vlbl = std > 2 ? 'High' : std > 1 ? 'Moderate' : 'Low';
    const ve = document.getElementById('kpiVol'); if (ve) { ve.textContent = vlbl; ve.className = 'kpi-value ' + (std > 2 ? 'text-red' : std > 1 ? 'text-yellow' : 'text-green'); }
    loadSentimentPanel(rows, score, slbl);
  }
}

/* ── Market Sentiment panel ── */
function loadSentimentPanel(rows, score, label) {
  mset('mktSentScore', score);
  const le = document.getElementById('mktSentLabel'); if (le) { le.textContent = label; le.className = 'sent-gauge-lbl ' + (score >= 55 ? 'text-green' : score >= 45 ? 'text-yellow' : 'text-red'); }
  _gauge('mktGauge', score);
  const bull = rows.filter(r => (r.change_pct || 0) > 0.1).length;
  const bear = rows.filter(r => (r.change_pct || 0) < -0.1).length;
  const neu = rows.length - bull - bear;
  const cEl = document.getElementById('sentCounts');
  if (cEl) cEl.innerHTML = `
    <div class="sc-item sc-bull"><div class="sc-lbl">Bullish</div><div class="sc-val">${bull}</div></div>
    <div class="sc-item sc-neu"><div class="sc-lbl">Neutral</div><div class="sc-val">${neu}</div></div>
    <div class="sc-item sc-bear"><div class="sc-lbl">Bearish</div><div class="sc-val">${bear}</div></div>`;
  // "By Market" breakdown only makes sense on the All-Markets view; hide it
  // (and its label) when a single market tab is selected.
  const bm = document.getElementById('mktByMarket');
  const bmLabel = bm ? bm.previousElementSibling : null;
  const showByMarket = !_filter;
  if (bm) bm.style.display = showByMarket ? '' : 'none';
  if (bmLabel && bmLabel.textContent.trim().toLowerCase() === 'by market') bmLabel.style.display = showByMarket ? '' : 'none';
  const markets = {}; rows.forEach(r => { (markets[r.market] = markets[r.market] || []).push(r.change_pct || 0); });
  if (bm && showByMarket) bm.innerHTML = Object.entries(markets).map(([m, arr]) => {
    const a = arr.reduce((x, y) => x + y, 0) / arr.length; const sc = Math.round(Math.max(5, Math.min(95, 50 + a * 12)));
    const clr = sc >= 55 ? 'var(--green)' : sc >= 45 ? 'var(--yellow)' : 'var(--red)';
    return `<div class="sbm-row"><span class="sbm-name">${mktLabel(m)}</span><div class="sbm-track"><div class="sbm-fill" style="width:${sc}%;background:${clr}"></div></div><span class="sbm-val">${sc}</span></div>`;
  }).join('');
}

function _gauge(id, score) {
  const cv = document.getElementById(id); if (!cv) return; const ctx = cv.getContext('2d'); const w = cv.width, h = cv.height;
  ctx.clearRect(0, 0, w, h); const cx = w / 2, cy = h - 6, rad = Math.min(w / 2, h) - 12; ctx.lineWidth = 12; ctx.lineCap = 'round';
  ctx.beginPath(); ctx.arc(cx, cy, rad, Math.PI, 2 * Math.PI); ctx.strokeStyle = 'rgba(148,163,184,.22)'; ctx.stroke();
  const f = Math.max(0, Math.min(1, score / 100)); const col = score >= 55 ? _cv('--green', '#10b981') : score >= 45 ? _cv('--yellow', '#f59e0b') : _cv('--red', '#ef4444');
  ctx.beginPath(); ctx.arc(cx, cy, rad, Math.PI, Math.PI + Math.PI * f); ctx.strokeStyle = col; ctx.stroke();
}

/* ── Live Signals table ── */
async function loadLiveSignals() {
  const tf = document.getElementById('tfFilter')?.value || '';
  const type = document.getElementById('typeFilter')?.value || '';
  const params = { per_page: 12 }; if (_filter) params.market = _filter; if (tf) params.timeframe = tf; if (type) params.signal_type = type;
  const data = await API.get('/signals/', params);
  _liveSignals = data?.signals || [];
  mset('liveCount', (data?.total || 0) + ' active');
  loadTopOpps(_liveSignals);
  // consensus is computed from the full scored universe in loadAiHeat()
  const tb = document.getElementById('liveBody');
  if (!tb) return;
  const search = (document.getElementById('assetSearch')?.value || '').toLowerCase();
  const rows = _liveSignals.filter(s => !search || (s.asset || '').toLowerCase().includes(search));
  if (!rows.length) { tb.innerHTML = '<tr><td colspan="12" class="text-center text-muted py-5">No signals for this filter</td></tr>'; return; }
  tb.innerHTML = rows.map(s => {
    const conf = s.confidence_score || 0; const confClr = conf >= 85 ? 'var(--green)' : conf >= 70 ? 'var(--accent-light)' : conf >= 55 ? 'var(--yellow)' : 'var(--red)';
    const rr = parseFloat(s.risk_reward) || 0; const st = _statusOf(s);
    return `<tr>
      <td><a href="/asset/${s.asset_id}" class="asset-cell-name" style="text-decoration:none">${s.asset}</a></td>
      <td><span class="badge-tag">${mktLabel(s.market)}</span></td>
      <td>${signalBadge(s.signal_type)}</td>
      <td><span class="badge-tag">${s.timeframe}</span></td>
      <td class="num">${formatPrice(s.entry_price, s.market)}</td>
      <td class="num" style="color:var(--red)">${formatPrice(s.stop_loss, s.market)}</td>
      <td class="num" style="color:var(--green)">${formatPrice(s.target1, s.market)}</td>
      <td class="num" style="color:var(--green)">${s.target2 ? formatPrice(s.target2, s.market) : '—'}</td>
      <td style="min-width:100px"><div style="font-weight:700;color:${confClr};font-size:12px">${conf.toFixed(0)}%</div><div class="confidence-bar"><div class="confidence-fill" style="width:${conf}%;background:${confClr}"></div></div></td>
      <td class="num" style="font-weight:700">${rr > 0 ? '1:' + rr.toFixed(1) : '—'}</td>
      <td class="num">${typeof relativeTime === 'function' ? relativeTime(s.generated_at) : ''}</td>
      <td><span class="status-chip" style="color:${st.c};border-color:${st.c}">${st.t}</span></td>
    </tr>`;
  }).join('');
}
function _statusOf(s) { const age = s.generated_at ? (Date.now() - new Date(s.generated_at)) / 60000 : 999; const cur = s.current_price, e = s.entry_price;
  if (cur && e && ((s.signal_type === 'BUY' && cur >= e) || (s.signal_type === 'SELL' && cur <= e))) return { t: 'ENTRY HIT', c: 'var(--green)' };
  return age < 30 ? { t: 'ACTIVE', c: 'var(--accent-light)' } : { t: 'ACTIVE', c: 'var(--green)' }; }

/* ── Top Opportunities ── */
function loadTopOpps(signals) {
  const el = document.getElementById('topOpps'); if (!el) return;
  const seen = new Set();
  const top = signals.filter(s => { if (!s.asset_id || seen.has(s.asset_id)) return false; seen.add(s.asset_id); return true; })
    .sort((a, b) => (b.confidence_score || 0) - (a.confidence_score || 0)).slice(0, 5);
  if (!top.length) { el.innerHTML = '<div class="text-muted fs-sm">No opportunities</div>'; return; }
  el.innerHTML = top.map((s, i) => {
    const conf = s.confidence_score || 0; const rr = parseFloat(s.risk_reward);
    return `<div class="opp-list-row" onclick="location='/asset/${s.asset_id}'">
      <span class="opp-rank">${i + 1}</span>
      <span class="opp-list-name">${s.asset}</span>
      ${signalBadge(s.signal_type)}
      <span class="opp-list-conf" style="color:${conf >= 70 ? 'var(--green)' : 'var(--yellow)'}">${conf.toFixed(0)}%</span>
      <span class="opp-list-rr">${rr > 0 ? '1:' + rr.toFixed(1) : '—'}</span>
      <span id="oppspk_${s.id}" class="opp-list-spark"></span>
    </div>`;
  }).join('');
  top.forEach(s => { const e = document.getElementById(`oppspk_${s.id}`); if (e && typeof Sparkline !== 'undefined') Sparkline.load(e, s.asset_id, s.timeframe || '1h'); });
}

/* ── AI Score Heatmap ──
   Shows EVERY asset in the selected market, each with a score. Score source,
   in priority order: (1) live signal conviction (BUY→conf, SELL→100-conf,
   HOLD→50), (2) AI model prediction from ai-summary, (3) price-change fallback
   so no asset is ever missing a score. */
async function loadAiHeat() {
  const grid = document.getElementById('aiHeatGrid'); if (!grid) return;
  const params = { per_page: 40 }; if (_filter) params.market = _filter;
  const [sig, ai, heat] = await Promise.all([
    API.get('/signals/', params), API.get('/market-data/ai-summary'), API.get('/market-data/heatmap'),
  ]);
  // best (highest-confidence) active signal per symbol
  const bySym = {};
  (sig?.signals || []).forEach(s => { const k = s.asset; if (!bySym[k] || (s.confidence_score || 0) > bySym[k].confidence_score) bySym[k] = s; });
  // AI-model prediction per symbol
  const aiMap = {}; (ai?.assets || []).forEach(a => { aiMap[a.symbol] = a; });
  // universe = every asset in the market (from the live heatmap feed)
  const universe = (heat?.heatmap || []).filter(r => !_filter || r.market === _filter);
  let items = universe.map(r => {
    let score;
    const s = bySym[r.symbol];
    if (s) {                                                  // 1) live signal
      const c = s.confidence_score || 0;
      score = s.signal_type === 'BUY' ? c : s.signal_type === 'SELL' ? 100 - c : 50;
    } else {                                                  // 2) AI prediction
      const a = aiMap[r.symbol];
      const tf = a && (a.tf?.['1h'] || Object.values(a.tf || {})[0]);
      if (tf && tf.confidence != null) {
        score = tf.direction === 'bullish' ? tf.confidence : tf.direction === 'bearish' ? 100 - tf.confidence : 50;
      } else {                                                // 3) price-change fallback
        score = 50 + (r.change_pct || 0) * 8;
      }
    }
    return { symbol: r.symbol, id: r.asset_id, score: Math.round(Math.max(1, Math.min(99, score))) };
  });
  if (!items.length) { // last-resort fallback to ai-summary universe
    let assets = ai?.assets || []; if (_filter) assets = assets.filter(a => a.market === _filter);
    items = assets.map(a => { const tf = a.tf?.['1h'] || Object.values(a.tf || {})[0] || {}; return { symbol: a.symbol, id: a.id, score: Math.round(tf.confidence ?? 50) }; });
  }
  items = items.sort((a, b) => b.score - a.score);
  loadConsensus(items);                 // consensus from every scored asset
  items = items.slice(0, 24);
  if (!items.length) { grid.innerHTML = '<div class="text-muted small p-3">No AI data</div>'; return; }
  grid.innerHTML = items.map(it => {
    const score = it.score;
    const label = score >= 80 ? 'STRONG BUY' : score >= 60 ? 'BUY' : score >= 40 ? 'HOLD' : score >= 20 ? 'SELL' : 'STRONG SELL';
    const bg = score >= 80 ? 'rgba(16,185,129,.22)' : score >= 60 ? 'rgba(74,222,128,.16)' : score >= 40 ? 'rgba(245,158,11,.16)' : score >= 20 ? 'rgba(248,113,113,.16)' : 'rgba(239,68,68,.22)';
    const bd = score >= 60 ? 'var(--green)' : score >= 40 ? 'var(--yellow)' : 'var(--red)';
    return `<div class="ai-heat-cell" style="background:${bg};border-color:${bd}33" onclick="location='/asset/${it.id}'">
      <div class="ahc-sym">${it.symbol}</div><div class="ahc-score" style="color:${bd}">${score}</div><div class="ahc-lbl">${label}</div></div>`;
  }).join('');
}

/* ── AI Model Consensus donut ── */
// items: scored asset universe [{score}] from the AI heatmap (buy>=60, hold 40-59, sell<40)
function loadConsensus(items) {
  const scored = (items || []).filter(x => typeof x.score === 'number');
  const buy = scored.filter(x => x.score >= 60).length;
  const hold = scored.filter(x => x.score >= 40 && x.score < 60).length;
  const sell = scored.filter(x => x.score < 40).length;
  const tot = buy + sell + hold || 1;
  const pct = Math.round(buy / tot * 100);
  mset('consensusPct', pct + '%');
  const lbl = pct >= 66 ? 'Strong Buy' : pct >= 50 ? 'Buy Bias' : pct >= 34 ? 'Mixed' : 'Sell Bias';
  const le = document.getElementById('consensusLbl'); if (le) { le.textContent = lbl; le.className = 'fs-xs ' + (pct >= 50 ? 'text-green' : 'text-red'); }
  const ctx = document.getElementById('consensusDonut');
  if (ctx && typeof Chart !== 'undefined') {
    if (_consensusChart) _consensusChart.destroy();
    _consensusChart = new Chart(ctx, { type: 'doughnut', data: { datasets: [{ data: [buy, hold, sell], backgroundColor: [_cv('--green', '#10b981'), _cv('--yellow', '#f59e0b'), _cv('--red', '#ef4444')], borderWidth: 0 }] }, options: { cutout: '72%', plugins: { legend: { display: false }, tooltip: { enabled: false } }, responsive: false } });
  }
  const leg = document.getElementById('consensusLegend');
  if (leg) leg.innerHTML = `
    <div class="cons-leg"><span><span class="dot" style="background:var(--green)"></span>Buy</span><span>${Math.round(buy / tot * 100)}%</span></div>
    <div class="cons-leg"><span><span class="dot" style="background:var(--yellow)"></span>Hold</span><span>${Math.round(hold / tot * 100)}%</span></div>
    <div class="cons-leg"><span><span class="dot" style="background:var(--red)"></span>Sell</span><span>${Math.round(sell / tot * 100)}%</span></div>`;
}

/* ── AI Performance chart ── */
async function loadAiPerf() {
  const [perf, hist] = await Promise.all([API.get('/signals/performance'), API.get('/signals/history', { per_page: 100 })]);
  const ov = perf?.overall || {};
  mset('apWin', ov.win_rate != null ? ov.win_rate.toFixed(1) + '%' : '—');
  mset('apPF', ov.profit_factor != null ? mfmt(ov.profit_factor) : '—');
  mset('apTrades', ov.total ?? '—');
  const rows = (hist?.history || []).slice().reverse();
  if (!rows.length) return;
  // daily buckets: win rate + avg realized RR
  const byDay = {};
  rows.forEach(r => { const d = (r.closed_at || '').slice(0, 10); if (!d) return; (byDay[d] = byDay[d] || []).push(r); });
  const days = Object.keys(byDay).sort().slice(-7);
  const winRates = days.map(d => { const arr = byDay[d]; const w = arr.filter(x => (x.pnl_pct || 0) > 0).length; return Math.round(w / arr.length * 100); });
  const rrs = days.map(d => { const arr = byDay[d]; const wins = arr.filter(x => (x.pnl_pct || 0) > 0).map(x => x.pnl_pct); const losses = arr.filter(x => (x.pnl_pct || 0) < 0).map(x => Math.abs(x.pnl_pct)); const aw = wins.length ? wins.reduce((a, b) => a + b, 0) / wins.length : 0; const al = losses.length ? losses.reduce((a, b) => a + b, 0) / losses.length : 1; return +(aw / al).toFixed(2); });
  const ctx = document.getElementById('apChart'); if (!ctx || typeof Chart === 'undefined') return;
  if (_apChart) _apChart.destroy();
  _apChart = new Chart(ctx, { type: 'line',
    data: { labels: days.map(d => d.slice(5)), datasets: [
      { label: 'Win Rate', data: winRates, borderColor: _cv('--green', '#10b981'), yAxisID: 'y', tension: .3, pointRadius: 2, borderWidth: 2 },
      { label: 'Avg R:R', data: rrs, borderColor: _cv('--accent', '#6366f1'), yAxisID: 'y1', tension: .3, pointRadius: 2, borderWidth: 2 } ] },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { labels: { boxWidth: 10 } } },
      scales: { y: { min: 0, max: 100, ticks: { callback: v => v + '%' }, grid: { color: 'rgba(148,163,184,.1)' } }, y1: { position: 'right', min: 0, grid: { display: false } } } } });
}

/* ── News Impact + Upcoming Events ── */
async function loadNewsImpact() {
  const data = await API.get('/news/', { per_page: 4 });
  const rows = data?.news || [];
  const el = document.getElementById('newsImpact'); if (!el) return;
  if (!rows.length) { el.innerHTML = '<div class="text-muted fs-sm">No news</div>'; return; }
  el.innerHTML = rows.slice(0, 4).map(n => {
    const imp = n.sentiment === 'negative' ? ['High Impact', 'var(--red)'] : n.sentiment === 'positive' ? ['Positive', 'var(--green)'] : ['Neutral', 'var(--text-muted)'];
    const t = n.published_at ? new Date(n.published_at).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false }) : '';
    return `<a class="ni-row" href="${n.url || '#'}" target="_blank" rel="noopener"><span class="ni-imp" style="color:${imp[1]}">${imp[0]}</span><span class="ni-text">${(n.title || '').slice(0, 70)}</span><span class="ni-time">${t}</span></a>`;
  }).join('');
}
async function loadUpcoming() {
  const data = await API.get('/news/economic-calendar');
  const events = (data?.events || []).filter(e => e.event_time && new Date(e.event_time + 'Z') >= new Date())
    .sort((a, b) => new Date(a.event_time) - new Date(b.event_time)).slice(0, 4);
  const el = document.getElementById('upcomingEvents'); if (!el) return;
  if (!events.length) { el.innerHTML = '<div class="text-muted fs-sm"><i class="bi bi-check-circle text-green me-1"></i>No high-impact events scheduled</div>'; return; }
  el.innerHTML = events.map(e => { const t = new Date(e.event_time + 'Z').toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hour12: false });
    const imp = (e.impact || 'low').toLowerCase(); const clr = imp === 'high' ? 'var(--red)' : imp === 'medium' ? 'var(--yellow)' : 'var(--text-muted)';
    return `<div class="ue-row"><span class="ue-time">${t}</span><span class="ue-name">${e.title}</span><span class="ue-imp" style="color:${clr}">${imp.charAt(0).toUpperCase() + imp.slice(1)}</span></div>`; }).join('');
}

/* ── Generate All ── */
async function generateAll() {
  const btn = document.getElementById('generateAll') || document.getElementById('qaGenerate');
  const symbols = [...new Set(_liveSignals.map(s => s.asset))].slice(0, 6);
  if (typeof toast === 'function') toast('Generating signals…', 'info');
  const tf = document.getElementById('tfFilter')?.value || '1h';
  for (const sym of symbols) { await API.post('/signals/generate', { symbol: sym, timeframe: tf }).catch(() => {}); }
  loadLiveSignals();
  if (typeof toast === 'function') toast('Signals refreshed', 'success');
}

/* ── Tabs ── */
function _setActiveTab() {
  document.querySelectorAll('.mkt-tab').forEach(t => t.classList.toggle('active', (t.dataset.market || '') === _filter));
}

/* ── Init ── */
function loadAll() { loadKPIs(); loadLiveSignals(); loadAiHeat(); loadAiPerf(); loadNewsImpact(); loadUpcoming(); }

document.addEventListener('app:ready', () => {
  if (typeof Chart !== 'undefined') Chart.defaults.color = _cv('--text-muted', '#94a3b8');
  _setActiveTab();
  loadAll();
  document.querySelectorAll('.mkt-tab').forEach(t => t.addEventListener('click', () => { _filter = t.dataset.market || ''; _setActiveTab(); loadKPIs(); loadLiveSignals(); loadAiHeat(); }));
  document.getElementById('tfFilter')?.addEventListener('change', loadLiveSignals);
  document.getElementById('typeFilter')?.addEventListener('change', loadLiveSignals);
  document.getElementById('assetSearch')?.addEventListener('input', () => loadLiveSignals());
  document.getElementById('generateAll')?.addEventListener('click', generateAll);
  document.getElementById('qaGenerate')?.addEventListener('click', generateAll);
  setInterval(loadAll, 90000);
});
