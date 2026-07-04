/* ═══════════════════════════════════════════════
   Dashboard Page — SmartTrade AI v2
   ═══════════════════════════════════════════════ */

function shortTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  const now = new Date();
  if ((now - d) / 36e5 < 24)
    return d.toLocaleTimeString('en-IN', {hour:'2-digit', minute:'2-digit', hour12:false});
  return d.toLocaleDateString('en-IN', {day:'2-digit', month:'short'}) + ' ' +
         d.toLocaleTimeString('en-IN', {hour:'2-digit', minute:'2-digit', hour12:false});
}

let _distChart  = null;
let _winChart   = null;
let _signalPage = 1;
let _signalData = [];

/* ── Chart.js global defaults ─────────────────── */
function _chartDefaults() {
  if (typeof Chart === 'undefined') return;
  Chart.defaults.color       = '#64748b';
  Chart.defaults.font.family = "'Inter', system-ui, sans-serif";
  Chart.defaults.font.size   = 12;
  Chart.defaults.plugins.legend.labels.boxWidth = 12;
  Chart.defaults.plugins.legend.labels.padding  = 14;
}

/* ── KPI Cards ────────────────────────────────── */
async function loadKPIs() {
  const data = await API.get('/signals/summary');
  if (!data) return;

  const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val ?? '—'; };

  // New 4-KPI layout
  set('kpiWinRate',     data.win_rate != null ? data.win_rate.toFixed(1) + '%' : '—');
  const buy  = data.buy_today  ?? 0;
  const sell = data.sell_today ?? 0;
  const hold = data.hold_today ?? 0;
  const exit = data.exit_today ?? 0;
  const total = buy + sell + hold + exit;
  set('kpiBuy',  buy);
  set('kpiSell', sell);
  set('kpiHold', hold);
  set('kpiExit', exit);
  set('kpiActiveSignals', total);

  const avgConf = data.avg_confidence;
  if (avgConf != null) {
    set('kpiAvgConf', avgConf.toFixed(1) + '%');
    set('qsAvgConf',  avgConf.toFixed(1) + '%');
  }

  set('qsTotalToday', total);

  // Open P&L card — load separately
  _loadOpenPnlKpi();

  _buildDistChart(data);
  _buildTopSignalCard(data.top_signal);
}

async function _loadOpenPnlKpi() {
  const data = await API.get('/signals/open-pnl');
  const el   = document.getElementById('kpiOpenPnl');
  const chEl = document.getElementById('kpiPnlChange');
  if (!el) return;
  if (!data || !Array.isArray(data) || !data.length) {
    el.textContent = '—';
    return;
  }
  const totalPnl = data.reduce((sum, r) => sum + (r.pnl_pct || 0), 0);
  const avg = totalPnl / data.length;
  el.textContent = (avg >= 0 ? '+' : '') + avg.toFixed(2) + '%';
  el.className = 'kpi-value ' + (avg >= 0 ? 'text-green' : 'text-red');
  if (chEl) chEl.innerHTML = `<i class="bi bi-circle-fill me-1" style="font-size:6px;color:${avg>=0?'var(--green)':'var(--red)'}"></i>${data.length} open position${data.length !== 1 ? 's' : ''}`;
}

function _buildDistChart(data) {
  const ctx = document.getElementById('signalDistChart');
  if (!ctx) return;
  if (_distChart) { _distChart.destroy(); _distChart = null; }

  const buy = data.buy_today||0, sell = data.sell_today||0,
        hold = data.hold_today||0, exit = data.exit_today||0;

  if (buy + sell + hold + exit === 0) {
    ctx.parentElement.innerHTML = '<div class="text-center text-muted py-4 fs-sm">No signals today yet</div>';
    return;
  }

  _distChart = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: ['BUY','SELL','HOLD','EXIT'],
      datasets: [{
        data: [buy, sell, hold, exit],
        backgroundColor: ['rgba(16,185,129,0.85)','rgba(239,68,68,0.85)','rgba(245,158,11,0.85)','rgba(139,92,246,0.85)'],
        borderColor:     ['#10b981','#ef4444','#f59e0b','#8b5cf6'],
        borderWidth: 2, hoverOffset: 6,
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false, cutout: '68%',
      plugins: {
        legend: { position: 'bottom' },
        tooltip: { callbacks: { label: c => ` ${c.label}: ${c.raw}` } },
      },
    },
  });
}

function _buildTopSignalCard(sig) {
  const el = document.getElementById('topSignalCard');
  if (!el || !sig) return;
  const cls = { BUY:'text-green', SELL:'text-red', HOLD:'text-yellow', EXIT:'text-purple' };
  el.innerHTML = `
    <div class="d-flex justify-content-between align-items-center">
      <div><div class="fw-800 fs-sm">${sig.asset||'—'}</div><div class="text-muted fs-xs">${(sig.market||'').replace('_',' ')} · ${sig.timeframe||''}</div></div>
      <div class="text-end"><div class="${cls[sig.signal_type]||''} fw-800 fs-sm">${sig.signal_type||'—'}</div><div class="text-muted fs-xs">${(sig.confidence_score||0).toFixed(0)}% conf.</div></div>
    </div>`;
}

/* ── Heatmap ──────────────────────────────────── */
async function loadHeatmap() {
  const grid = document.getElementById('heatmapGrid');
  if (!grid) return;

  const market = document.getElementById('heatmapMarket')?.value || '';
  const data   = await API.get('/market-data/heatmap');

  if (!data?.heatmap?.length) {
    grid.innerHTML = '<div class="text-muted small p-3">No data available</div>';
    return;
  }

  let items = data.heatmap;
  if (market) items = items.filter(i => i.market === market);

  _buildWinChart();

  grid.innerHTML = items.map(item => {
    const up    = item.change_pct >= 0;
    const arrow = up ? '▲' : '▼';
    const clr   = up ? 'var(--green)' : 'var(--red)';
    return `<div class="heatmap-cell ${up?'up':'down'}" onclick="location='/markets/${item.market}'">
      <div class="cell-symbol">${item.symbol}</div>
      <div class="cell-change" style="color:${clr}">${arrow}${Math.abs(item.change_pct).toFixed(2)}%</div>
      <div class="cell-price">${formatPrice(item.price)}</div>
    </div>`;
  }).join('');
}

async function _buildWinChart() {
  const ctx = document.getElementById('winRateChart');
  if (!ctx) return;
  if (_winChart) { _winChart.destroy(); _winChart = null; }

  const data = await API.get('/signals/analytics');
  const byMarket = data?.by_market;
  if (!byMarket?.length) return;

  // Only show markets that have historical signal data
  const filtered = byMarket.filter(m => m.total > 0);
  const labels = filtered.map(m =>
    m.market === 'indian_stock' ? 'Stocks' :
    m.market === 'index'        ? 'Indices' :
    m.market.charAt(0).toUpperCase() + m.market.slice(1));
  const values = filtered.map(m => m.win_rate);

  _winChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: 'Win Rate',
        data: values,
        backgroundColor: values.map(v => v >= 50 ? 'rgba(16,185,129,0.7)' : 'rgba(239,68,68,0.7)'),
        borderRadius: 5, borderSkipped: false,
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => c.raw + '%' } } },
      scales: {
        y: { min: 0, max: 100, ticks: { callback: v => v+'%', stepSize: 25 }, grid: { color: 'rgba(255,255,255,0.04)' } },
        x: { grid: { display: false } },
      },
    },
  });
}

/* ── Sentiment ────────────────────────────────── */
async function loadSentiment() {
  const data = await API.get('/assets/', { market: 'crypto' });
  if (!data?.assets?.length) return;

  const asset = data.assets[0];
  const sentEl = document.getElementById('sentimentAsset');
  if (sentEl) sentEl.textContent = asset.symbol;

  const sent = await API.get(`/market-data/${asset.id}/sentiment`, { timeframe: '1h' });
  if (!sent?.sentiment) return;

  const s = sent.sentiment;
  const score = s.score ?? 50;
  const label = s.label || 'Neutral';

  const scoreEl = document.getElementById('sentimentScore');
  const labelEl = document.getElementById('sentimentLabel');
  const barEl   = document.getElementById('sentimentBar');

  if (scoreEl) {
    scoreEl.textContent = score;
    scoreEl.style.color = score >= 65 ? 'var(--green)' : score <= 35 ? 'var(--red)' : 'var(--yellow)';
  }
  if (labelEl) labelEl.textContent = label;
  if (barEl) {
    // Gradient Fear/Neutral/Greed track: position the marker via --pos.
    barEl.style.setProperty('--pos', Math.max(0, Math.min(100, score)) + '%');
  }

  const statsEl = document.getElementById('sentimentStats');
  if (statsEl && s.indicators) {
    const rsi = s.indicators.rsi;
    const rsiColor = rsi > 70 ? 'text-red' : rsi < 30 ? 'text-green' : 'text-yellow';
    const macdLabel = s.indicators.macd_signal || '—';
    statsEl.innerHTML = `
      <div class="col-6"><div class="quick-stat"><div class="qs-label">RSI</div><div class="qs-value ${rsiColor}" style="font-size:16px">${rsi?.toFixed(1)||'—'}</div></div></div>
      <div class="col-6"><div class="quick-stat"><div class="qs-label">MACD</div><div class="qs-value ${macdLabel==='bullish'?'text-green':'text-red'}" style="font-size:13px;text-transform:capitalize">${macdLabel}</div></div></div>`;
  }
}

/* ── Live Signals ─────────────────────────────── */
async function loadSignals(page) {
  page = page || 1;
  _signalPage = page;

  const market = document.getElementById('signalMarketFilter')?.value || '';
  const type   = document.getElementById('signalTypeFilter')?.value   || '';
  const tf     = document.getElementById('globalTimeframe')?.value    || '1h';

  const params = { page, per_page: 15, timeframe: tf };
  if (market) params.market      = market;
  if (type)   params.signal_type = type;

  const data = await API.get('/signals/', params);
  if (!data) return;

  _signalData = data.signals || [];
  _renderSignals(_signalData);

  const countEl = document.getElementById('signalCount');
  if (countEl) countEl.textContent = `${data.total||0} signals · page ${data.page||1}/${data.pages||1}`;

  // Pagination
  const pag   = document.getElementById('signalPagination');
  const pages = Math.min(data.pages||1, 7);
  pag.innerHTML = '';
  if (pages > 1) {
    for (let i = 1; i <= pages; i++) {
      const li = document.createElement('li');
      li.className = 'page-item' + (i === page ? ' active' : '');
      li.innerHTML = `<a class="page-link" href="#">${i}</a>`;
      li.querySelector('a').addEventListener('click', e => { e.preventDefault(); loadSignals(i); });
      pag.appendChild(li);
    }
  }

  // Quick best signal
  if (_signalData.length) {
    const best = [..._signalData].sort((a,b) => (b.confidence_score||0) - (a.confidence_score||0))[0];
    const bestEl = document.getElementById('qsBest');
    if (bestEl) bestEl.textContent = best?.asset || '—';
  }
}

function _renderSignals(signals) {
  const tbody   = document.getElementById('signalsBody');
  if (!tbody) return;
  const search  = (document.getElementById('signalSearch')?.value || '').toLowerCase();
  const minConf = window.MIN_CONFIDENCE || 0;

  let filtered = signals.filter(s => (s.confidence_score || 0) >= minConf);
  if (search) {
    filtered = filtered.filter(s =>
      (s.asset||'').toLowerCase().includes(search) || (s.market||'').toLowerCase().includes(search));
  }

  if (!filtered.length) {
    tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted py-5">
      <i class="bi bi-inbox d-block mb-2" style="font-size:28px"></i>
      No signals found yet. Go to a market page and click "Generate Signal" to create one.
    </td></tr>`;
    return;
  }

  tbody.innerHTML = filtered.map(s => {
    const rr = parseFloat(s.risk_reward) || 0;
    const rrColor = rr >= 2 ? 'var(--green)' : rr >= 1.5 ? 'var(--yellow)' : rr > 0 ? 'var(--text-secondary)' : 'var(--text-muted)';
    const rrText  = rr > 0 ? `${rr.toFixed(1)}x` : '—';
    const conf    = s.confidence_score || 0;
    const confClr = conf >= 85 ? 'var(--green)' : conf >= 70 ? 'var(--accent-light)' : conf >= 55 ? 'var(--yellow)' : 'var(--red)';
    const mktLabel = (s.market || '').replace('_', ' ');
    return `<tr>
      <td>
        <div class="asset-cell">
          <a href="/asset/${s.asset_id}" class="asset-cell-name" style="text-decoration:none" onmouseover="this.style.color='var(--accent)'" onmouseout="this.style.color=''">${s.asset}</a>
          <span class="asset-cell-sub"><span class="badge-tag">${mktLabel}</span></span>
        </div>
      </td>
      <td><span class="badge-tag">${s.timeframe}</span></td>
      <td>${signalBadge(s.signal_type)}</td>
      <td class="fw-700">${formatPrice(s.entry_price, s.market)}</td>
      <td style="min-width:160px">
        <div class="confidence-wrap">
          <div style="font-size:12px;font-weight:700;color:${confClr}">${conf.toFixed(0)}% <span style="color:var(--text-muted);font-weight:400;font-size:11px">${s.confidence_label || ''}</span></div>
          <div class="confidence-bar"><div class="confidence-fill" style="width:${conf}%;background:${confClr}"></div></div>
          <div class="signal-levels">
            <span class="sl">SL ${formatPrice(s.stop_loss, s.market)}</span>
            <span class="tgt">T1 ${formatPrice(s.target1, s.market)}</span>
            ${s.target2 ? `<span class="tgt">T2 ${formatPrice(s.target2, s.market)}</span>` : ''}
          </div>
          <div id="dsbd_${s.id}"></div>
          <div id="dsprog_${s.id}"></div>
        </div>
      </td>
      <td style="font-weight:700;color:${rrColor}">${rrText}</td>
      <td>
        <div class="text-muted fs-xs" style="white-space:nowrap" title="${shortTime(s.generated_at)}">${typeof relativeTime==='function'?relativeTime(s.generated_at):shortTime(s.generated_at)}</div>
        <div id="dspk_${s.id}" style="line-height:0;margin-top:4px"></div>
        <div id="conf_${s.id}" style="font-size:10px;color:var(--text-muted);margin-top:3px"></div>
      </td>
    </tr>`;
  }).join('');

  // Lazy-load sparklines, score breakdowns, and P&L progress bars (non-blocking)
  filtered.forEach(s => {
    if (s.asset_id) {
      const el = document.getElementById(`dspk_${s.id}`);
      if (el && typeof Sparkline !== 'undefined') Sparkline.load(el, s.asset_id, s.timeframe || '1h');
    }
    if (typeof ScoreBreakdown !== 'undefined') {
      const sbdEl = document.getElementById(`dsbd_${s.id}`);
      if (sbdEl) ScoreBreakdown.render(sbdEl, s);
    }
    if (typeof SignalProgress !== 'undefined') {
      const progEl = document.getElementById(`dsprog_${s.id}`);
      if (progEl) SignalProgress.render(progEl, s);
    }
  });
  _loadConfluenceCells(filtered);
  _loadConfluenceWidget(filtered);
}

/* ── Confluence cell lazy-loader ──────────────── */
async function _loadConfluenceCells(signals) {
  // Deduplicate by asset_id so we don't call the same endpoint multiple times
  const seen = new Set();
  for (const s of signals) {
    if (!s.asset_id || seen.has(s.asset_id)) continue;
    seen.add(s.asset_id);
    // Fire and forget — update cells for all signals sharing this asset_id
    (async () => {
      try {
        const data = await API.get(`/signals/confluence/${s.asset_id}`);
        if (!data) return;
        const label = _confluenceLabel(data);
        // Update all cells on this page for this asset
        signals
          .filter(x => x.asset_id === s.asset_id)
          .forEach(x => {
            const cell = document.getElementById(`conf_${x.id}`);
            if (cell) cell.innerHTML = label;
          });
      } catch (_) {}
    })();
  }
}

function _confluenceLabel(data) {
  if (!data) return '—';
  const buy  = data.buy_tfs  || 0;
  const sell = data.sell_tfs || 0;
  const total = data.total   || 7;
  const dominant = buy >= sell ? 'BUY' : 'SELL';
  const count    = Math.max(buy, sell);
  const clr = dominant === 'BUY' ? 'var(--green)' : 'var(--red)';
  return `<span style="font-weight:700;color:${clr}">${count}/${total}</span>
    <span style="color:var(--text-muted)"> ${dominant}</span>`;
}

/* ── Confluence Score Widget ──────────────────── */
async function _loadConfluenceWidget(signals) {
  const widget = document.getElementById('confluenceWidget');
  const barsEl = document.getElementById('confluenceBars');
  if (!widget || !barsEl) return;

  // Take top 5 unique assets from current signals list
  const seen = new Set();
  const topAssets = signals.filter(s => {
    if (!s.asset_id || seen.has(s.asset_id)) return false;
    seen.add(s.asset_id);
    return true;
  }).slice(0, 5);

  if (!topAssets.length) return;

  widget.style.display = '';
  barsEl.innerHTML = '<div class="text-muted fs-sm">Computing confluence...</div>';

  const results = await Promise.all(
    topAssets.map(s => API.get(`/signals/confluence/${s.asset_id}`).catch(() => null))
  );

  const valid = results.filter(Boolean);
  if (!valid.length) {
    barsEl.innerHTML = '<div class="text-muted fs-sm">No confluence data available</div>';
    return;
  }

  // Sort by dominant TF count descending
  valid.sort((a, b) => Math.max(b.buy_tfs, b.sell_tfs) - Math.max(a.buy_tfs, a.sell_tfs));

  barsEl.innerHTML = valid.map(d => {
    const total  = d.total || 7;
    const buyPct  = Math.round((d.buy_tfs  / total) * 100);
    const sellPct = Math.round((d.sell_tfs / total) * 100);
    const neuPct  = 100 - buyPct - sellPct;
    return `<div class="d-flex align-items-center gap-3 mb-2">
      <div style="width:80px;font-weight:700;font-size:12px;color:var(--text-primary);flex-shrink:0">${d.symbol}</div>
      <div style="flex:1;height:14px;border-radius:7px;overflow:hidden;background:var(--bg-input);display:flex">
        <div style="width:${buyPct}%;background:var(--green);height:100%" title="BUY ${d.buy_tfs}/${total}"></div>
        <div style="width:${neuPct}%;background:rgba(100,116,139,0.4);height:100%" title="Neutral ${d.neutral_tfs}/${total}"></div>
        <div style="width:${sellPct}%;background:var(--red);height:100%" title="SELL ${d.sell_tfs}/${total}"></div>
      </div>
      <div style="font-size:11px;color:var(--text-muted);flex-shrink:0;min-width:90px">
        <span style="color:var(--green)">${d.buy_tfs}B</span> /
        <span style="color:var(--red)">${d.sell_tfs}S</span> /
        <span>${d.neutral_tfs}N</span> of ${total}
      </div>
    </div>`;
  }).join('');
}

/* ── Live P&L Ticker Strip ────────────────────── */
let _openPositions = [];    // [{signal_id, asset, asset_id, timeframe, signal_type, entry_price}]

async function loadLivePnlStrip() {
  try {
    const data = await API.get('/signals/open-pnl');
    if (!data || !Array.isArray(data) || !data.length) {
      document.getElementById('livePnlStrip').style.display = 'none';
      return;
    }
    _openPositions = data;
    document.getElementById('livePnlStrip').style.display = 'block';
    _renderPnlStrip(data);
  } catch (e) {
    document.getElementById('livePnlStrip').style.display = 'none';
  }
}

function _renderPnlStrip(positions) {
  const wrap = document.getElementById('pnlTickerItems');
  if (!wrap) return;
  wrap.innerHTML = positions.map(p => {
    const pnl    = p.pnl_pct;
    const pnlStr = pnl != null
      ? `<span style="font-weight:800;color:${pnl >= 0 ? 'var(--green)' : 'var(--red)'}">
           ${pnl >= 0 ? '▲' : '▼'}${Math.abs(pnl).toFixed(2)}%</span>`
      : '<span style="color:var(--text-muted)">—</span>';
    return `<div id="pnlstrip_${p.signal_id || p.asset_id}" style="display:flex;align-items:center;gap:5px;white-space:nowrap;flex-shrink:0">
      <span style="font-size:12px;font-weight:700">${p.asset}</span>
      <span class="badge-tag" style="font-size:9px">${p.timeframe}</span>
      ${pnlStr}
    </div>`;
  }).join('');
}

function _patchPnlStrip(tick) {
  // Update P&L for any open position matching this symbol
  _openPositions.forEach(p => {
    if (p.asset !== tick.symbol) return;
    const price = tick.price;
    let pnl = null;
    if (p.entry_price && price) {
      pnl = p.signal_type === 'SELL' || p.signal_type === 'EXIT'
        ? (p.entry_price - price) / p.entry_price * 100
        : (price - p.entry_price) / p.entry_price * 100;
      p.pnl_pct = parseFloat(pnl.toFixed(2));
    }
    const itemEl = document.getElementById(`pnlstrip_${p.signal_id || p.asset_id}`);
    if (itemEl) {
      const span = itemEl.querySelector('span[style*="font-weight:800"]') || itemEl.lastElementChild;
      if (pnl !== null && span) {
        span.style.color = pnl >= 0 ? 'var(--green)' : 'var(--red)';
        span.textContent = `${pnl >= 0 ? '▲' : '▼'}${Math.abs(pnl).toFixed(2)}%`;
      }
    }
  });
}

/* ── Load Everything ──────────────────────────── */
function loadAll() {
  Promise.all([loadKPIs(), loadHeatmap(), loadSentiment(), loadSignals(1)]);
}

/* ── Init ─────────────────────────────────────── */
document.addEventListener('app:ready', () => {
  _chartDefaults();
  loadAll();
  loadLivePnlStrip();

  document.getElementById('refreshAll')?.addEventListener('click', () => { loadAll(); loadLivePnlStrip(); });
  document.getElementById('globalTimeframe')?.addEventListener('change', () => loadSignals(1));
  document.getElementById('signalMarketFilter')?.addEventListener('change', () => loadSignals(1));
  document.getElementById('signalTypeFilter')?.addEventListener('change', () => loadSignals(1));
  document.getElementById('heatmapMarket')?.addEventListener('change', loadHeatmap);
  document.getElementById('signalSearch')?.addEventListener('input', () => _renderSignals(_signalData));

  // React to live WebSocket price updates — patch the P&L strip in-place
  document.addEventListener('price:update', e => { if (e.detail) _patchPnlStrip(e.detail); });

  setInterval(loadAll, 90000);
  setInterval(loadLivePnlStrip, 60000);
});
