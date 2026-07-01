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

  set('kpiBuy',     data.buy_today  ?? 0);
  set('kpiSell',    data.sell_today ?? 0);
  set('kpiHold',    data.hold_today ?? 0);
  set('kpiExit',    data.exit_today ?? 0);
  set('kpiAlerts',  data.open_alerts ?? 0);
  set('kpiWinRate', data.win_rate != null ? data.win_rate.toFixed(1) + '%' : '—');

  const total = (data.buy_today||0)+(data.sell_today||0)+(data.hold_today||0)+(data.exit_today||0);
  set('qsTotalToday', total);
  if (data.avg_confidence != null) set('qsAvgConf', data.avg_confidence.toFixed(1) + '%');

  _buildDistChart(data);
  _buildTopSignalCard(data.top_signal);
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

  _buildWinChart(items);

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

function _buildWinChart(items) {
  const ctx = document.getElementById('winRateChart');
  if (!ctx) return;
  if (_winChart) { _winChart.destroy(); _winChart = null; }

  const markets = {};
  items.forEach(i => {
    if (!markets[i.market]) markets[i.market] = [];
    markets[i.market].push(i.change_pct);
  });

  const labels = Object.keys(markets).map(m =>
    m === 'indian_stock' ? 'Stocks' : m === 'index' ? 'Indices' :
    m.charAt(0).toUpperCase() + m.slice(1));
  const values = Object.values(markets).map(arr => {
    const pos = arr.filter(v => v > 0).length;
    return Math.round((pos / arr.length) * 100);
  });

  _winChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: '% Up',
        data: values,
        backgroundColor: values.map(v => v >= 50 ? 'rgba(16,185,129,0.7)' : 'rgba(239,68,68,0.7)'),
        borderRadius: 5, borderSkipped: false,
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
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
    barEl.style.width      = score + '%';
    barEl.style.background = score >= 65 ? 'var(--green)' : score <= 35 ? 'var(--red)' : 'var(--yellow)';
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
    tbody.innerHTML = `<tr><td colspan="12" class="text-center text-muted py-5">
      <i class="bi bi-inbox d-block mb-2" style="font-size:28px"></i>
      No signals found yet. Go to a market page and click "Generate Signal" to create one.
    </td></tr>`;
    return;
  }

  tbody.innerHTML = filtered.map(s => {
    const rr = parseFloat(s.risk_reward) || 0;
    const rrColor = rr >= 2 ? 'var(--green)' : rr >= 1.5 ? 'var(--yellow)' : rr > 0 ? 'var(--text-secondary)' : 'var(--text-muted)';
    const rrText  = rr > 0 ? `${rr.toFixed(1)}x` : '—';
    const conf = s.confidence_score || 0;
    const confClr = conf >= 85 ? 'var(--green)' : conf >= 70 ? 'var(--accent-light)' : conf >= 55 ? 'var(--yellow)' : 'var(--red)';
    return `<tr>
      <td><a href="/asset/${s.asset_id}" style="color:var(--text-primary);text-decoration:none;font-weight:700" onmouseover="this.style.color='var(--accent)'" onmouseout="this.style.color='var(--text-primary)'">${s.asset}</a></td>
      <td><span class="badge-tag">${(s.market||'').replace('_',' ')}</span></td>
      <td><span class="badge-tag">${s.timeframe}</span></td>
      <td>${signalBadge(s.signal_type)}</td>
      <td class="fw-700" style="color:var(--text-primary)">${formatPrice(s.entry_price, s.market)}</td>
      <td class="text-red">${formatPrice(s.stop_loss, s.market)}</td>
      <td class="text-green">${formatPrice(s.target1, s.market)}</td>
      <td class="text-green">${formatPrice(s.target2, s.market)}</td>
      <td><span style="font-weight:700;color:${rrColor}">${rrText}</span></td>
      <td>
        <div style="min-width:90px">
          <div class="confidence-bar"><div class="confidence-fill" style="width:${conf}%;background:${confClr}"></div></div>
          <div style="color:#94a3b8;font-size:11px;margin-top:3px">${conf.toFixed(0)}% · ${s.confidence_label||''}</div>
        </div>
      </td>
      <td id="conf_${s.id}" style="font-size:11px;color:var(--text-muted);white-space:nowrap">…</td>
      <td style="color:#7a8fa8;font-size:11px;white-space:nowrap">${shortTime(s.generated_at)}</td>
    </tr>`;
  }).join('');

  // Lazy-load confluence for each signal (non-blocking)
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

/* ── Load Everything ──────────────────────────── */
function loadAll() {
  Promise.all([loadKPIs(), loadHeatmap(), loadSentiment(), loadSignals(1)]);
}

/* ── Init ─────────────────────────────────────── */
document.addEventListener('app:ready', () => {
  _chartDefaults();
  loadAll();

  document.getElementById('refreshAll')?.addEventListener('click', loadAll);
  document.getElementById('globalTimeframe')?.addEventListener('change', () => loadSignals(1));
  document.getElementById('signalMarketFilter')?.addEventListener('change', () => loadSignals(1));
  document.getElementById('signalTypeFilter')?.addEventListener('change', () => loadSignals(1));
  document.getElementById('heatmapMarket')?.addEventListener('change', loadHeatmap);
  document.getElementById('signalSearch')?.addEventListener('input', () => _renderSignals(_signalData));

  setInterval(loadAll, 90000);
});
