/* ═══════════════════════════════════════════════
   Dashboard Page — SmartTrade AI (Enhanced)
   ═══════════════════════════════════════════════ */

let _equityChart = null, _calibChart = null;
let _signalPage = 1, _signalData = [];
let _heatmapMode = 'change';
let _aiSummaryCache = null;
let _dashboardLoadPromise = null;
let _dashboardBooted = false;
let _signalsRequestId = 0;
let _heatmapRequestId = 0;

const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = (v ?? '—'); };
const numberOr = (value, fallback = null) => {
  if (value === null || value === undefined || value === '') return fallback;
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
};
const clamp = (value, min, max, fallback = min) => {
  const number = numberOr(value, fallback);
  return Math.min(max, Math.max(min, number));
};
const countOr = value => Math.max(0, Math.floor(numberOr(value, 0)));
const percentOr = value => {
  const number = numberOr(value);
  return number == null ? null : Math.min(100, Math.max(0, number));
};
const fmt = (n, d = 2) => {
  const number = numberOr(n);
  return number == null ? '—' : number.toFixed(d);
};
const safePrice = (value, market) => {
  const number = numberOr(value);
  return number == null || number < 0 ? '—' : formatPrice(number, market);
};

function setDashboardState(kind, message) {
  const status = document.getElementById('dashboardDataStatus');
  const state = document.getElementById('dashboardDataState');
  if (status) status.className = 'dashboard-context is-' + kind;
  if (state) state.textContent = message;
  const live = document.getElementById('dashboardLiveStatus');
  const updated = document.getElementById('dashboardLastUpdated');
  if (kind === 'ready') {
    const time = new Date().toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
    if (updated) updated.textContent = 'Last updated ' + time;
    if (live) live.textContent = 'Live data updated ' + time;
  } else if (live) {
    live.textContent = kind === 'error' ? 'Dashboard data unavailable' : 'Dashboard partially updated';
  }
}

function setDashboardBusy(isBusy) {
  const content = document.getElementById('dashboardContent');
  const refresh = document.getElementById('refreshAll');
  if (content) content.setAttribute('aria-busy', String(isBusy));
  if (refresh) {
    refresh.setAttribute('aria-busy', String(isBusy));
    refresh.disabled = isBusy;
  }
}

function stateRow(container, message, icon = 'bi-exclamation-circle') {
  if (!container) return;
  const state = `<div class="ui-state ui-state--${icon === 'bi-hourglass-split' ? 'loading' : 'error'}"><i class="bi ${icon}" aria-hidden="true"></i><span>${STSafe.html(message)}</span></div>`;
  if (container.tagName === 'TBODY') {
    const colspan = container.closest('table')?.querySelectorAll('thead th').length || 1;
    container.innerHTML = `<tr><td colspan="${colspan}" class="text-center py-4">${state}</td></tr>`;
  } else {
    container.innerHTML = state;
  }
}

function chartState(canvas, message) {
  const wrapper = canvas?.parentElement;
  if (!wrapper) return;
  if (canvas) canvas.style.display = 'none';
  let state = wrapper.querySelector('.dashboard-chart-state');
  if (!state) {
    state = document.createElement('div');
    state.className = 'dashboard-chart-state text-center text-muted py-4 fs-sm';
    wrapper.appendChild(state);
  }
  state.textContent = message;
}

function restoreChart(canvas) {
  const wrapper = canvas?.parentElement;
  if (!wrapper) return;
  canvas.style.display = '';
  wrapper.querySelector('.dashboard-chart-state')?.remove();
}

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

  const buy = countOr(summary?.buy_today), sell = countOr(summary?.sell_today);
  const hold = countOr(summary?.hold_today), exit = countOr(summary?.exit_today);
  const active = buy + sell + hold + exit;

  // KPI cards — overall stats live under perf.overall
  const ov = perf?.overall || {};
  set('kpiActiveSignals', active); set('kpiBuy', buy); set('kpiSell', sell);
  const winRate = percentOr(ov.win_rate);
  set('kpiWinRate', winRate == null ? '—' : winRate.toFixed(1) + '%');
  set('kpiWinRateSub', 'n = ' + countOr(ov.total_closed));
  set('kpiProfitFactor', fmt(ov.profit_factor));
  set('kpiExpectancy', fmt(ov.avg_pnl_pct));
  set('kpiExpectancySub', 'avg P&L % / trade');
  // Sharpe / Max Drawdown / Avg R:R are computed from the closed-trade history
  // (see loadEquityCurve) — set to a loading dash until that resolves.

  // Open P&L
  const openRows = Array.isArray(pnl) ? pnl : [];
  const openPnls = openRows.map(row => numberOr(row?.pnl_pct)).filter(value => value != null);
  if (openPnls.length) {
    const total = openPnls.reduce((s, value) => s + value, 0);
    const avg = total / openPnls.length;
    const el = document.getElementById('kpiOpenPnl');
    if (el) { el.textContent = (avg >= 0 ? '+' : '') + avg.toFixed(2) + '%'; el.className = 'kpi-value ' + (avg >= 0 ? 'text-green' : 'text-red'); }
    set('kpiPnlChange', openPnls.length + ' open position' + (openPnls.length !== 1 ? 's' : ''));
  } else { set('kpiOpenPnl', '—'); }

  // Header market-state
  const conf = percentOr(summary?.avg_confidence);
  set('msConf', conf == null ? '—' : conf.toFixed(1) + '%');
  loadTodaySummary(summary, perf);
  loadCalibration(perf);
  return { summary, perf, hasData: Boolean(summary || perf || openRows.length) };
}

function loadTodaySummary(summary, perf) {
  const buy = countOr(summary?.buy_today), sell = countOr(summary?.sell_today);
  const hold = countOr(summary?.hold_today), exit = countOr(summary?.exit_today);
  set('tsGenerated', buy + sell + hold + exit);
  set('tsNew', countOr(summary?.new_today ?? (buy + sell)));
  // These are all genuinely "today" figures from /signals/summary now (it
  // didn't return any of them before — every cell here silently fell
  // through to '—' regardless of real activity). win_rate_today is null
  // (not 0) when nothing closed today, rendered as '—' rather than a
  // misleading "0%".
  const closed = summary?.closed_today == null ? null : countOr(summary.closed_today);
  set('tsClosed', closed == null ? '—' : closed);
  set('tsWin', summary?.wins_today == null ? '—' : countOr(summary.wins_today));
  set('tsLoss', summary?.losses_today == null ? '—' : countOr(summary.losses_today));
  const winRate = percentOr(summary?.win_rate_today);
  set('tsWinRate', winRate == null ? '—' : winRate.toFixed(1) + '%');
  const el = document.getElementById('tsPnl');
  const tp = summary?.total_pnl_today;
  if (el) {
    const totalPnl = numberOr(tp);
    if (totalPnl != null && closed) {
      el.textContent = (totalPnl >= 0 ? '+' : '') + fmt(totalPnl) + '%';
      el.className = 'ts-value ' + (totalPnl >= 0 ? 'text-green' : 'text-red');
    } else {
      el.textContent = '—';
      el.className = 'ts-value';
    }
  }
}

/* ── Market-state (regime / volatility / risk) from heatmap ───── */
function loadHeaderStats(heatmap) {
  const rows = Array.isArray(heatmap?.heatmap) ? heatmap.heatmap : [];
  if (!rows.length) return;
  const changes = rows.map(r => numberOr(r?.change_pct, 0));
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
  const top = (Array.isArray(signals) ? signals : [])
    .filter(s => { if (!s?.asset_id || seen.has(s.asset_id)) return false; seen.add(s.asset_id); return true; })
    .sort((a, b) => numberOr(b?.confidence_score, 0) - numberOr(a?.confidence_score, 0))
    .slice(0, 5);
  if (!top.length) { wrap.innerHTML = '<div class="text-muted small p-3">No opportunities right now.</div>'; return; }

  wrap.innerHTML = top.map(s => {
    const conf = clamp(s.confidence_score, 0, 100, 0);
    const tag = _oppTag(conf, s.signal_type === 'SELL' ? 'SELL' : 'BUY');
    const rr = numberOr(s.risk_reward, 0);
    const note = String(s.reasoning || '').split(/[.,]/)[0].slice(0, 28) || String(s.confidence_label || '');
    return `<a class="opp-card" href="${STSafe.assetHref(s.asset_id)}" style="text-decoration:none;color:inherit">
      <div class="opp-top">
        <div class="opp-name">${STSafe.html(s.asset)}</div>
        <span class="opp-badge" style="color:${tag.c};border-color:${tag.c}">${tag.t}</span>
      </div>
      <div class="opp-conf" style="color:${tag.c}">${conf.toFixed(0)}%</div>
      <div id="${STSafe.domId('oppspk_', s.id)}" class="opp-spark"></div>
      <div class="opp-foot"><span>R:R ${rr > 0 ? '1:' + rr.toFixed(1) : '—'}</span><span class="text-muted">${STSafe.html(note)}</span></div>
    </a>`;
  }).join('');

  top.forEach(s => {
    const el = document.getElementById(STSafe.domId('oppspk_', s.id));
    if (el && typeof Sparkline !== 'undefined') Sparkline.load(el, s.asset_id, s.timeframe || '1h');
  });
}

/* ── Live Signals (enhanced) ──────────────────────────────────── */
async function loadSignals(page) {
  page = page || 1; _signalPage = page;
  const requestId = ++_signalsRequestId;
  const market = document.getElementById('signalMarketFilter')?.value || '';
  const type = document.getElementById('signalTypeFilter')?.value || '';
  const tf = document.getElementById('globalTimeframe')?.value || '1h';
  const params = { page, per_page: 12, timeframe: tf };
  if (market) params.market = market;
  if (type) params.signal_type = type;

  const data = await API.get('/signals/', params);
  if (requestId !== _signalsRequestId || !data) {
    if (!data && requestId === _signalsRequestId) {
      stateRow(document.getElementById('signalsBody'), 'Signals are temporarily unavailable. Try refreshing.');
      return null;
    }
    return undefined;
  }
  _signalData = Array.isArray(data.signals) ? data.signals : [];
  _renderSignals(_signalData);
  loadOpportunityRadar(_signalData);
  if (_signalData.length) loadInspector([..._signalData].sort((a, b) => (b.confidence_score || 0) - (a.confidence_score || 0))[0]);

  set('signalCount', countOr(data.total) + ' active');
  const pag = document.getElementById('signalPagination');
  const pages = Math.min(Math.max(1, countOr(data.pages) || 1), 7);
  if (pag) {
      pag.innerHTML = ''; if (pages > 1) for (let i = 1; i <= pages; i++) {
      const li = document.createElement('li'); li.className = 'page-item' + (i === page ? ' active' : '');
      li.innerHTML = `<a class="page-link" href="#">${i}</a>`;
      li.querySelector('a').addEventListener('click', e => { e.preventDefault(); loadSignals(i); });
      pag.appendChild(li);
    }
  }
  return data;
}

function _renderSignals(signals) {
  const tbody = document.getElementById('signalsBody');
  if (!tbody) return;
  const minConf = clamp(window.MIN_CONFIDENCE, 0, 100, 0);
  const filtered = (Array.isArray(signals) ? signals : []).filter(s => numberOr(s?.confidence_score, 0) >= minConf);
  if (!filtered.length) {
    tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted py-4"><i class="bi bi-inbox d-block mb-2" style="font-size:22px;opacity:.4"></i>No signals yet — generate one from a market page.</td></tr>`;
    return;
  }
  tbody.innerHTML = filtered.map(s => {
    const conf = clamp(s.confidence_score, 0, 100, 0);
    const confClr = conf >= 85 ? 'var(--green)' : conf >= 70 ? 'var(--accent-light)' : conf >= 55 ? 'var(--yellow)' : 'var(--red)';
    const rr = Math.max(0, numberOr(s.risk_reward, 0));
    const rrClr = rr >= 2 ? 'var(--green)' : rr >= 1.5 ? 'var(--yellow)' : 'var(--text-primary)';
    const cur = numberOr(s.current_price, numberOr(s.entry_price));
    const mkt = String(s.market || '').replace('_', ' ');
    // Row itself navigates to the asset's AI Position Analysis (SL/targets/
    // age/regime/model-agreement/status all live there now) — only the
    // trash-icon-style affordance differs, so make the whole row clickable
    // rather than just the asset name.
    return `<tr style="cursor:pointer" tabindex="0" data-asset-href="${STSafe.assetHref(s.asset_id)}">
      <td><span class="asset-cell-name">${STSafe.html(s.asset)}</span><div class="asset-cell-sub"><span class="badge-tag">${STSafe.html(mkt)}</span></div></td>
      <td><span class="badge-tag">${STSafe.html(s.timeframe)}</span></td>
      <td>${signalBadge(s.signal_type)}</td>
      <td class="num">${safePrice(s.entry_price, s.market)}</td>
      <td class="num">${safePrice(cur, s.market)}</td>
      <td style="min-width:110px"><div style="font-weight:700;color:${confClr};font-size:12px">${conf.toFixed(0)}%</div><div class="confidence-bar"><div class="confidence-fill" style="width:${conf}%;background:${confClr}"></div></div></td>
      <td class="num" style="color:${rrClr};font-weight:700">${rr > 0 ? '1:' + rr.toFixed(1) : '—'}</td>
    </tr>`;
  }).join('');
  tbody.querySelectorAll('tr[data-asset-href]').forEach(row => {
    const go = () => { if (row.dataset.assetHref && row.dataset.assetHref !== '#') location.href = row.dataset.assetHref; };
    row.addEventListener('click', go);
    row.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); go(); }
    });
  });
}

/* ── AI Decision Inspector ────────────────────────────────────── */
function loadInspector(s) {
  const body = document.getElementById('inspectorBody');
  if (!body || !s) return;
  const conf = clamp(s.confidence_score, 0, 100, 0);
  document.getElementById('inspHeader').textContent = `${s.asset} · ${s.signal_type} · ${conf.toFixed(0)}%`;
  const entry = numberOr(s.entry_price);
  const stop = numberOr(s.stop_loss);
  const cur = numberOr(s.current_price, entry);
  const riskPct = entry && stop != null ? Math.abs((entry - stop) / entry * 100) : null;
  const quality = s.data_quality && typeof s.data_quality === 'object' ? s.data_quality : {};
  const qualityStatus = ['GREEN', 'YELLOW', 'RED'].includes(quality.status) ? quality.status : 'UNKNOWN';
  const qualityClass = qualityStatus.toLowerCase();
  const qualityAge = Number.isFinite(Number(quality.last_candle_age_seconds))
    ? `${Math.max(0, Math.round(Number(quality.last_candle_age_seconds) / 60))} min ago`
    : 'timestamp unavailable';
  const qualityProvider = STSafe.html(quality.provider || 'provider unavailable');
  const provenance = s.reproducibility && typeof s.reproducibility === 'object' ? s.reproducibility : {};
  const provenanceText = value => STSafe.html(value || 'unavailable');
  const sourceLabel = provenance.generation_source === 'manual' ? 'Manual' :
    provenance.generation_source === 'automatic' ? 'Automatic' : 'Legacy / unknown';
  const modelLabel = provenance.model_version === 'not_applicable' ? 'Rule-based scoring' :
    provenanceText(provenance.model_version);
  const fingerprint = String(provenance.data_fingerprint || '');
  const fingerprintLabel = fingerprint
    ? STSafe.html(`${fingerprint.slice(0, 12)}...`)
    : 'unavailable';
  const decisionTitle = provenance.model_version && provenance.model_version !== 'not_applicable'
    ? 'Why This Signal Qualified (AI-assisted)' : 'Why This Signal Qualified';
  // "AI Model Agreement" removed from this checklist: ai_score is a
  // hardcoded placeholder (10) for every automatically-generated signal --
  // the real ML ensemble is never invoked for these -- and even for the
  // rare admin-generated signal where it IS real (see /signals/generate's
  // "AI boost", app/api/v1/signals.py), it's deliberately scaled to a
  // 0-20 range (prediction.confidence * 0.2) while this check compared it
  // against >= 55, a threshold sized for the OTHER checks' 0-100 scale.
  // The check could not pass for any signal in the system, in either case.
  const checks = [
    ['EMA Trend Alignment', numberOr(s.trend_score, 0) >= 55],
    ['RSI / Momentum Recovery', numberOr(s.momentum_score, 0) >= 55],
    ['Volume Confirmation', numberOr(s.volume_score, 0) >= 50],
    ['Pattern Support', numberOr(s.pattern_score, 0) >= 50],
  ];
  const warnings = [];
  if (riskPct != null && riskPct > 3) warnings.push(`Wide stop (${riskPct.toFixed(1)}% risk)`);
  if (numberOr(s.volume_score, 0) < 40) warnings.push('Low volume confirmation');
  if (conf < 65) warnings.push('Confidence below 65%');
  const dir = s.signal_type === 'SELL' ? 'var(--red)' : 'var(--green)';
  // Honest breakdown of the real components behind confidence_score (see
  // SignalEngine._compute_confidence) -- this used to be labeled "Model
  // Agreement" and show ['XGBoost', s.ai_score], ['LightGBM', (trend+
  // momentum)/2], ['LSTM', (momentum+volume)/2], implying three distinct
  // real ML models had independently voted on this signal. They hadn't:
  // "XGBoost" was the same always-10 placeholder described above,
  // "LightGBM"/"LSTM" were ad-hoc averages of these SAME four numbers
  // relabeled with ML brand names, and LSTM isn't a model that exists
  // anywhere in this codebase. This is what the checklist above is
  // actually built from -- no fabricated per-model attribution.
  const factors = [
    ['Trend', clamp(s.trend_score, 0, 100, 0)], ['Momentum', clamp(s.momentum_score, 0, 100, 0)],
    ['Volume', clamp(s.volume_score, 0, 100, 0)], ['Pattern', clamp(s.pattern_score, 0, 100, 0)],
  ];
  // Evidence / Counter-Evidence — SignalEngine already computes this per
  // factor (reasoning_detail's `aligned` flag, see
  // SignalEngine._labeled_reasons) but until now nothing in the UI
  // surfaced it: the checklist above only shows four fixed score-vs-
  // threshold checks, never the actual reasons, and counter-evidence
  // (a factor that pointed the other way but was outweighed -- e.g. a
  // strong reversal pattern beating a still-bullish EMA trend) was
  // computed and persisted but never shown anywhere. Splitting on the
  // same `aligned` flag `_build_retrospective_note` already uses server-
  // side keeps this consistent with the plain-language summary on
  // /signal-journal.
  const detail = Array.isArray(s.reasoning_detail) ? s.reasoning_detail.filter(r => r && typeof r === 'object') : [];
  const evidence = detail.filter(r => r.aligned);
  const counterEvidence = detail.filter(r => !r.aligned);
  const history = s.historical_context && typeof s.historical_context === 'object' ? s.historical_context : {};
  const historyAccuracy = percentOr(history.accuracy);
  const historySample = countOr(history.sample_size);
  const historyDecisive = countOr(history.decisive_sample_size);
  const historyPnl = numberOr(history.avg_pnl_pct);
  const historyWins = countOr(history.wins);
  const historyLosses = countOr(history.losses);
  const historyNeutral = countOr(history.neutral);
  const historySummary = historyDecisive
    ? `${historyWins} wins · ${historyLosses} losses${historyNeutral ? ` · ${historyNeutral} neutral` : ''}`
    : 'No decisive closed sample yet';

  body.innerHTML = `
    <div class="insp-grid">
      <div><div class="insp-k">Entry</div><div class="insp-v">${safePrice(entry, s.market)}</div></div>
      <div><div class="insp-k">Current</div><div class="insp-v">${safePrice(cur, s.market)}</div></div>
      <div><div class="insp-k">Stop Loss</div><div class="insp-v" style="color:var(--red)">${safePrice(stop, s.market)}</div></div>
      <div><div class="insp-k">Take Profit 1</div><div class="insp-v" style="color:var(--green)">${safePrice(s.target1, s.market)}</div></div>
      <div><div class="insp-k">Take Profit 2</div><div class="insp-v" style="color:var(--green)">${safePrice(s.target2, s.market)}</div></div>
      <div><div class="insp-k">R:R</div><div class="insp-v">${numberOr(s.risk_reward, 0) > 0 ? '1:' + fmt(s.risk_reward, 1) : '—'}</div></div>
      <div><div class="insp-k">Risk</div><div class="insp-v">${riskPct != null ? riskPct.toFixed(2) + '%' : '—'}</div></div>
    </div>
    <div class="insp-context insp-quality-${qualityClass}" role="status">
      <div class="insp-context-main"><i class="bi bi-database-check"></i><strong>Data ${qualityStatus}</strong><span>${qualityAge}</span></div>
      <div class="insp-context-meta">${qualityProvider} · ${quality.candle_count == null ? '—' : countOr(quality.candle_count)} candles</div>
    </div>
    <div class="insp-context insp-regime" role="status">
      <div class="insp-context-main"><i class="bi bi-activity"></i><strong>Market regime</strong><span>${STSafe.html(s.regime || 'Not classified')}</span></div>
      <div class="insp-context-meta">This describes the observed environment, not a profit prediction.</div>
    </div>
    <div class="insp-context insp-provenance" role="status">
      <div class="insp-context-main"><i class="bi bi-fingerprint"></i><strong>Signal provenance</strong><span>${STSafe.html(sourceLabel)}</span></div>
      <div class="insp-context-meta">${modelLabel} · ${provenance.data_candles == null ? '—' : countOr(provenance.data_candles)} candles · data ${fingerprintLabel}</div>
    </div>
    <div class="insp-context insp-history" role="status">
      <div class="insp-context-main"><i class="bi bi-bar-chart-line"></i><strong>Historical context</strong><span>${historyAccuracy == null ? '—' : historyAccuracy.toFixed(1) + '% accuracy'}</span></div>
      <div class="insp-context-meta">${STSafe.html(historySummary)} · ${historySample} total resolved records${historyPnl == null ? '' : ` · avg P&L ${historyPnl >= 0 ? '+' : ''}${historyPnl.toFixed(2)}%`}</div>
      <div class="insp-context-meta">Same asset and timeframe; accuracy excludes neutral expiries and is not a forecast.</div>
    </div>
    <div class="insp-section-title">${decisionTitle}</div>
    <div class="insp-checks">${checks.map(([l, ok]) => `<div class="insp-check"><i class="bi ${ok ? 'bi-check-circle-fill text-green' : 'bi-dash-circle text-muted'}"></i>${l}</div>`).join('')}</div>
    ${warnings.length ? `<div class="insp-section-title text-yellow">Warnings</div><div class="insp-warns">${warnings.map(w => `<div class="insp-warn"><i class="bi bi-exclamation-triangle-fill text-yellow"></i>${w}</div>`).join('')}</div>` : ''}
    ${evidence.length ? `<div class="insp-section-title">Evidence Supporting ${STSafe.html(s.signal_type)}</div><div class="insp-checks">${evidence.map(r => `<div class="insp-check"><i class="bi bi-check-circle-fill text-green"></i>${STSafe.html(r.text)}</div>`).join('')}</div>` : ''}
    ${counterEvidence.length ? `<div class="insp-section-title text-yellow">Counter-Evidence (outweighed)</div><div class="insp-warns">${counterEvidence.map(r => `<div class="insp-warn"><i class="bi bi-arrow-left-right text-yellow"></i>${STSafe.html(r.text)}</div>`).join('')}</div>` : ''}
    <div class="insp-section-title">Confidence Factors</div>
    ${factors.map(([n, v]) => `<div class="insp-model"><span class="insp-model-n">${n}</span><div class="insp-model-track"><div class="insp-model-fill" style="width:${Math.max(0, Math.min(100, v || 0))}%;background:${dir}"></div></div><span class="insp-model-p">${Math.round(v || 0)}%</span></div>`).join('')}
  `;
}

/* ── Equity curve + Win-by-market + Calibration ───────────────── */
async function loadEquityCurve() {
  const ctx = document.getElementById('equityChart');
  if (!ctx) return;
  const data = await API.get('/signals/history', { per_page: 100 });
  const rawRows = Array.isArray(data?.history) ? data.history : (Array.isArray(data?.signals) ? data.signals : []);
  const rows = rawRows.map(row => ({ ...row, pnl_pct: numberOr(row?.pnl_pct) }))
    .filter(row => row.pnl_pct != null).slice().reverse();
  if (!rows.length) { chartState(ctx, data ? 'No closed trades yet' : 'Historical performance is temporarily unavailable'); return null; }
  restoreChart(ctx);
  let eq = 0; const eqPts = [], ddPts = []; let peak = 0, maxDD = 0;
  const pnls = [];
  rows.forEach(r => {
    const p = r.pnl_pct; pnls.push(p);
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
  if (typeof Chart === 'undefined') { chartState(ctx, 'Chart library unavailable. Use Signal Analytics for the table view.'); return data; }
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
  return data;
}

async function loadWinByMarket() {
  const tbody = document.getElementById('winByMarketBody');
  if (!tbody) return;
  const data = await API.get('/signals/analytics');
  const rows = (Array.isArray(data?.by_market) ? data.by_market : [])
    .filter(m => countOr(m?.total) > 0);
  if (!rows.length) {
    stateRow(tbody, data ? 'No market history yet' : 'Market performance is temporarily unavailable');
    return null;
  }
  const label = m => m === 'indian_stock' ? 'Stocks' : m === 'index' ? 'Indices' : String(m || 'Unknown').replace('_', ' ').replace(/^\w/, c => c.toUpperCase());
  tbody.innerHTML = rows.map(m => {
    const wr = percentOr(m.win_rate) ?? 0;
    const exp = numberOr(m.avg_pnl_pct, numberOr(m.expectancy));
    const total = countOr(m.total);
    return `<tr>
      <td>${STSafe.html(label(m.market))}</td>
      <td class="num" style="color:${wr >= 50 ? 'var(--green)' : 'var(--red)'};font-weight:700">${wr.toFixed(0)}%</td>
      <td class="num">${numberOr(m.avg_rr) != null ? '1:' + fmt(m.avg_rr) : '—'}</td>
      <td class="num" style="color:${(exp || 0) >= 0 ? 'var(--green)' : 'var(--red)'}">${exp != null ? (exp >= 0 ? '+' : '') + fmt(exp) : '—'}</td>
      <td class="num">${total}</td>
    </tr>`;
  }).join('');
  return data;
}

function loadCalibration(perf) {
  const ctx = document.getElementById('calibrationChart');
  if (!ctx) return;
  const bands = Array.isArray(perf?.calibration) ? perf.calibration : (Array.isArray(perf?.confidence_calibration) ? perf.confidence_calibration : []);
  if (!bands.length) { chartState(ctx, 'Not enough closed-trade data yet'); return; }
  restoreChart(ctx);
  const labels = bands.map(b => String(b?.range || b?.band || 'Unknown').slice(0, 24));
  const expected = bands.map(b => percentOr(b?.expected_win_rate));
  const actual = bands.map(b => percentOr(b?.actual_win_rate));
  if (typeof Chart === 'undefined') { chartState(ctx, 'Chart library unavailable. Use Model Performance for details.'); return; }
  if (_calibChart) _calibChart.destroy();
  const css = getComputedStyle(document.documentElement);
  _calibChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels, datasets: [
        { label: 'Expected', data: expected, borderColor: (css.getPropertyValue('--accent') || '#f5a623').trim(), borderDash: [4, 3], pointRadius: 2, borderWidth: 1.5 },
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
  const requestId = ++_heatmapRequestId;
  const data = await API.get('/market-data/heatmap');
  if (requestId !== _heatmapRequestId) return undefined;
  const items = Array.isArray(data?.heatmap) ? data.heatmap.filter(item => item && typeof item === 'object') : [];
  if (!items.length) {
    stateRow(grid, data ? 'Market data is not available yet' : 'Market data is temporarily unavailable');
    return null;
  }
  loadHeaderStats(data);
  if (!_aiSummaryCache && (_heatmapMode === 'ai' || _heatmapMode === 'confidence')) {
    _aiSummaryCache = await API.get('/market-data/ai-summary').catch(() => null);
  }
  if (requestId !== _heatmapRequestId) return undefined;
  _renderHeatmap(items);
  return data;
}

function _renderHeatmap(items) {
  const grid = document.getElementById('heatmapGrid');
  const aiMap = {};
  (Array.isArray(_aiSummaryCache?.assets) ? _aiSummaryCache.assets : []).forEach(a => { aiMap[String(a?.symbol || '')] = a; });
  grid.innerHTML = (Array.isArray(items) ? items : []).map(item => {
    let main, sub, clr;
    const change = numberOr(item?.change_pct, 0);
    const up = change >= 0;
    const ai = aiMap[item.symbol];
    const tfMap = ai?.tf && typeof ai.tf === 'object' ? ai.tf : {};
    const tf = tfMap['1h'] || Object.values(tfMap)[0] || {};
    const aiConfidence = clamp(tf.confidence, 0, 100, 50);
    const direction = ['bullish', 'bearish', 'neutral'].includes(tf.direction) ? tf.direction : 'neutral';
    if (_heatmapMode === 'change') { main = (up ? '▲' : '▼') + Math.abs(change).toFixed(2) + '%'; clr = up ? 'var(--green)' : 'var(--red)'; sub = safePrice(item.price); }
    else if (_heatmapMode === 'ai') { main = 'AI ' + Math.round(aiConfidence); clr = direction === 'bullish' ? 'var(--green)' : direction === 'bearish' ? 'var(--red)' : 'var(--yellow)'; sub = direction.toUpperCase(); }
    else if (_heatmapMode === 'confidence') { main = Math.round(aiConfidence) + '%'; clr = aiConfidence >= 70 ? 'var(--green)' : aiConfidence >= 55 ? 'var(--yellow)' : 'var(--red)'; sub = 'confidence'; }
    else if (_heatmapMode === 'volatility') { const volatility = Math.abs(change); main = volatility.toFixed(2) + '%'; clr = volatility > 3 ? 'var(--red)' : volatility > 1.5 ? 'var(--yellow)' : 'var(--green)'; sub = volatility > 3 ? 'high' : volatility > 1.5 ? 'med' : 'low'; }
    else { const strength = Math.min(100, Math.abs(change) * 25 + 30); main = Math.round(strength); clr = up ? 'var(--green)' : 'var(--red)'; sub = up ? 'bullish' : 'bearish'; }
    return `<a class="heatmap-cell ${up ? 'up' : 'down'}" href="${STSafe.marketHref(item.market)}" style="text-decoration:none;color:inherit">
      <div class="cell-symbol">${STSafe.html(item.symbol)}</div>
      <div class="cell-change" style="color:${clr}">${main}</div>
      <div class="cell-price">${sub}</div>
    </a>`;
  }).join('');
}

/* ── Generate Signal button ───────────────────────────────────── */
async function _generateSignal() {
  const btn = document.getElementById('generateSignalBtn');
  const top = _signalData[0];
  // Both the /auto-generate page and this fallback route to it are
  // admin-only now (see app.js generateSignalBtn visibility gate) — this
  // handler only runs for admins in the first place since the button
  // itself is hidden for everyone else.
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
  if (_dashboardLoadPromise) return _dashboardLoadPromise;
  setDashboardBusy(true);
  setDashboardState('loading', 'Refreshing dashboard data');
  _dashboardLoadPromise = Promise.allSettled([
    loadKPIs(),
    loadSignals(1),
    loadHeatmap(),
    loadEquityCurve(),
    loadWinByMarket(),
  ]).then(results => {
    const rejected = results.filter(result => result.status === 'rejected').length;
    const empty = results.filter(result => result.status === 'fulfilled' && (
      result.value === null || result.value?.hasData === false
    )).length;
    if (rejected === results.length || empty === results.length) {
      setDashboardState('error', 'Dashboard data unavailable');
    } else if (rejected || empty) {
      setDashboardState('degraded', 'Dashboard partially updated');
    } else {
      setDashboardState('ready', 'Dashboard data current');
    }
    return results;
  }).catch(() => {
    setDashboardState('error', 'Dashboard data unavailable');
    return [];
  }).finally(() => {
    setDashboardBusy(false);
    _dashboardLoadPromise = null;
  });
  return _dashboardLoadPromise;
}

document.addEventListener('app:ready', () => {
  if (_dashboardBooted) return;
  _dashboardBooted = true;
  _chartDefaults();
  populateMarketSelect(document.getElementById('signalMarketFilter'), { includeAll: true });
  loadAll();

  document.getElementById('refreshAll')?.addEventListener('click', () => { _aiSummaryCache = null; loadAll(); });
  document.getElementById('generateSignalBtn')?.addEventListener('click', _generateSignal);
  document.getElementById('globalTimeframe')?.addEventListener('change', () => loadSignals(1));
  document.getElementById('signalMarketFilter')?.addEventListener('change', () => loadSignals(1));
  document.getElementById('signalTypeFilter')?.addEventListener('change', () => loadSignals(1));
  document.querySelectorAll('.hm-tab').forEach(tab => tab.addEventListener('click', () => {
    document.querySelectorAll('.hm-tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.hm-tab').forEach(t => t.setAttribute('aria-selected', String(t === tab)));
    tab.classList.add('active');
    document.getElementById('heatmapGrid')?.setAttribute('aria-labelledby', tab.id);
    _heatmapMode = tab.dataset.mode; _aiSummaryCache = null; loadHeatmap();
  }));

  setInterval(loadAll, 90000);
});
