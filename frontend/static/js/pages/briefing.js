/* ═══════════════════════════════════════════════
   Morning Briefing — SmartTrade AI (Enhanced)
   ═══════════════════════════════════════════════ */

let _breadthChart = null;
let _levelAssets = [];
let _levelActive = null;
const bset = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = (v ?? '—'); };
const bcolor = (id, cls) => { const el = document.getElementById(id); if (el) el.className = cls; };

function _cssv(n, f) { return (getComputedStyle(document.documentElement).getPropertyValue(n) || f).trim(); }

/* ── Header subtitle ──────────────────────────────────────────── */
function renderHeader() {
  const now = new Date();
  const d = now.toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' });
  const t = now.toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hour12: false });
  bset('briefSubtitle', `Your daily trading snapshot — updated on ${d}, ${t} IST`);
}

/* ── Master heatmap-driven sections ───────────────────────────── */
async function loadMarketState() {
  const data = await API.get('/market-data/heatmap');
  const rows = data?.heatmap || [];
  if (!rows.length) return;
  const ch = rows.map(r => r.change_pct || 0);
  const avg = ch.reduce((a, b) => a + b, 0) / ch.length;
  const std = Math.sqrt(ch.reduce((a, b) => a + (b - avg) ** 2, 0) / ch.length);

  // State cards
  const r = document.getElementById('bsRegime');
  if (r) {
    const up = avg > 0.4, dn = avg < -0.4;
    r.innerHTML = `<i class="bi bi-${up ? 'graph-up-arrow' : dn ? 'graph-down-arrow' : 'arrow-left-right'}"></i> ${up ? 'Trending Up' : dn ? 'Trending Down' : 'Ranging'}`;
    r.className = 'bs-value ' + (up ? 'text-green' : dn ? 'text-red' : 'text-yellow');
  }
  const v = document.getElementById('bsVol');
  if (v) {
    const hi = std > 2, mid = std > 1; v.innerHTML = `<i class="bi bi-activity"></i> ${hi ? 'High' : mid ? 'Moderate' : 'Low'}`;
    v.className = 'bs-value ' + (hi ? 'text-red' : mid ? 'text-yellow' : 'text-green');
  }
  const s = document.getElementById('bsSentiment');
  const sScore = Math.max(0, Math.min(100, 50 + avg * 12));
  if (s) {
    const lbl = sScore >= 65 ? 'Bullish' : sScore >= 55 ? 'Slightly Bullish' : sScore >= 45 ? 'Neutral' : sScore >= 35 ? 'Slightly Bearish' : 'Bearish';
    s.innerHTML = `<i class="bi bi-emoji-smile"></i> ${lbl}`; s.className = 'bs-value ' + (sScore >= 55 ? 'text-green' : sScore >= 45 ? 'text-yellow' : 'text-red');
  }
  const k = document.getElementById('bsRisk');
  if (k) {
    const hi = std > 2, mid = std > 1; k.innerHTML = `<i class="bi bi-shield-exclamation"></i> ${hi ? 'Elevated' : mid ? 'Moderate' : 'Low'}`;
    k.className = 'bs-value ' + (hi ? 'text-red' : mid ? 'text-yellow' : 'text-green');
  }
  const c = document.getElementById('bsClarity');
  if (c) {
    const good = std < 1.2 && Math.abs(avg) > 0.2; const poor = std > 2.2;
    c.innerHTML = `<i class="bi bi-check-circle"></i> ${good ? 'Good' : poor ? 'Poor' : 'Fair'}`;
    c.className = 'bs-value ' + (good ? 'text-green' : poor ? 'text-red' : 'text-yellow');
  }

  loadMarketSummary(rows);
  loadMovers(rows);
  loadSentiment(rows, sScore);
  loadCrypto(rows);
  loadLevels(rows);
  loadInsights(rows, avg, std);
}

/* ── Market Summary + breadth donut ───────────────────────────── */
function loadMarketSummary(rows) {
  const adv = rows.filter(r => (r.change_pct || 0) > 0.05).length;
  const dec = rows.filter(r => (r.change_pct || 0) < -0.05).length;
  const unch = rows.length - adv - dec;
  const tot = rows.length || 1;
  bset('advCount', adv); bset('decCount', dec); bset('unchCount', unch);
  bset('advPct', Math.round(adv / tot * 100) + '%');
  bset('decPct', Math.round(dec / tot * 100) + '%');
  bset('unchPct', Math.round(unch / tot * 100) + '%');
  const breadth = Math.round(adv / tot * 100);
  bset('breadthPct', breadth + '%');
  bset('breadthLbl', breadth >= 55 ? 'Positive' : breadth >= 45 ? 'Neutral' : 'Negative');
  const el = document.getElementById('breadthLbl');
  if (el) el.className = 'breadth-lbl ' + (breadth >= 55 ? 'text-green' : breadth >= 45 ? 'text-yellow' : 'text-red');

  const ctx = document.getElementById('breadthDonut');
  if (ctx && typeof Chart !== 'undefined') {
    if (_breadthChart) _breadthChart.destroy();
    _breadthChart = new Chart(ctx, {
      type: 'doughnut',
      data: { datasets: [{ data: [adv, unch, dec], backgroundColor: [_cssv('--green', '#10b981'), 'rgba(148,163,184,.35)', _cssv('--red', '#ef4444')], borderWidth: 0 }] },
      options: { cutout: '74%', plugins: { legend: { display: false }, tooltip: { enabled: false } }, responsive: false },
    });
  }
}

/* ── Overnight Movers ─────────────────────────────────────────── */
function loadMovers(rows) {
  // With a small tracked universe, naive slice(0,6)/slice(-6) can select
  // the exact same rows from opposite ends (identical lists, just reversed)
  // and can mislabel a barely-positive asset as a "loser" simply because it
  // ranks lowest. Filter by actual sign first, then cap at 6 each — the two
  // lists can never overlap, and "losers" only ever contains real decliners.
  const sorted = [...rows].sort((a, b) => (b.change_pct || 0) - (a.change_pct || 0));
  const gainers = sorted.filter(m => (m.change_pct || 0) > 0).slice(0, 6);
  const losers = sorted.filter(m => (m.change_pct || 0) < 0).slice(-6).reverse();
  const row = (m) => {
    const up = (m.change_pct || 0) >= 0;
    return `<tr><td><div class="mv-sym">${m.symbol}</div><div class="mv-name">${m.name || ''}</div></td>
      <td class="num">${formatPrice(m.price)}</td>
      <td class="num" style="color:${up ? 'var(--green)' : 'var(--red)'};font-weight:700">${up ? '▲' : '▼'} ${Math.abs(m.change_pct || 0).toFixed(2)}%</td></tr>`;
  };
  const emptyRow = (label) => `<tr><td colspan="3" class="text-center text-muted fs-xs py-3">${label}</td></tr>`;
  const g = document.getElementById('gainersBody'), l = document.getElementById('losersBody');
  if (g) g.innerHTML = gainers.length ? gainers.map(row).join('') : emptyRow('No advancers right now');
  if (l) l.innerHTML = losers.length ? losers.map(row).join('') : emptyRow('No decliners right now');
}

/* ── Market Sentiment gauge + by-market bars ──────────────────── */
function loadSentiment(rows, score) {
  bset('sentScore', Math.round(score));
  const lbl = score >= 65 ? 'Bullish' : score >= 55 ? 'Slightly Bullish' : score >= 45 ? 'Neutral' : score >= 35 ? 'Slightly Bearish' : 'Bearish';
  const le = document.getElementById('sentLabel');
  if (le) { le.textContent = lbl; le.className = 'sent-gauge-lbl ' + (score >= 55 ? 'text-green' : score >= 45 ? 'text-yellow' : 'text-red'); }
  _drawGauge('sentGauge', score);

  // by market
  const markets = {};
  rows.forEach(r => { (markets[r.market] = markets[r.market] || []).push(r.change_pct || 0); });
  const label = m => m === 'indian_stock' ? 'Indian Stocks' : m === 'index' ? 'Indices' : m.charAt(0).toUpperCase() + m.slice(1);
  const el = document.getElementById('sentByMarket');
  if (el) el.innerHTML = Object.entries(markets).map(([m, arr]) => {
    const a = arr.reduce((x, y) => x + y, 0) / arr.length;
    const sc = Math.round(Math.max(5, Math.min(95, 50 + a * 12)));
    const clr = sc >= 55 ? 'var(--green)' : sc >= 45 ? 'var(--yellow)' : 'var(--red)';
    return `<div class="sbm-row"><span class="sbm-name">${label(m)}</span><div class="sbm-track"><div class="sbm-fill" style="width:${sc}%;background:${clr}"></div></div><span class="sbm-val">${sc}</span></div>`;
  }).join('');
}

function _drawGauge(id, score) {
  const cv = document.getElementById(id); if (!cv) return;
  const ctx = cv.getContext('2d'); const w = cv.width, h = cv.height;
  ctx.clearRect(0, 0, w, h);
  const cx = w / 2, cy = h - 6, rad = Math.min(w / 2, h) - 10;
  ctx.lineWidth = 11; ctx.lineCap = 'round';
  ctx.beginPath(); ctx.arc(cx, cy, rad, Math.PI, 2 * Math.PI); ctx.strokeStyle = 'rgba(148,163,184,.22)'; ctx.stroke();
  const frac = Math.max(0, Math.min(1, score / 100));
  const col = score >= 55 ? _cssv('--green', '#10b981') : score >= 45 ? _cssv('--yellow', '#f59e0b') : _cssv('--red', '#ef4444');
  ctx.beginPath(); ctx.arc(cx, cy, rad, Math.PI, Math.PI + Math.PI * frac); ctx.strokeStyle = col; ctx.stroke();
}

/* ── Crypto Market Snapshot ───────────────────────────────────── */
function loadCrypto(rows) {
  const crypto = rows.filter(r => r.market === 'crypto').slice(0, 6);
  const tb = document.getElementById('cryptoBody');
  if (!tb) return;
  if (!crypto.length) { tb.innerHTML = '<tr><td colspan="5" class="text-center text-muted py-4">No crypto data</td></tr>'; return; }
  tb.innerHTML = crypto.map(c => {
    const up = (c.change_pct || 0) >= 0;
    return `<tr>
      <td class="mv-sym">${c.symbol}</td>
      <td class="num">${formatPrice(c.price)}</td>
      <td class="num" style="color:${up ? 'var(--green)' : 'var(--red)'};font-weight:700">${up ? '▲' : '▼'}${Math.abs(c.change_pct || 0).toFixed(2)}%</td>
      <td><div id="cspk_${c.asset_id}" style="line-height:0"></div></td>
    </tr>`;
  }).join('');
  crypto.forEach(c => { const el = document.getElementById(`cspk_${c.asset_id}`); if (el && typeof Sparkline !== 'undefined' && c.asset_id) Sparkline.load(el, c.asset_id, '1h'); });
}
function _abbrev(n) { if (n >= 1e9) return (n / 1e9).toFixed(2) + 'B'; if (n >= 1e6) return (n / 1e6).toFixed(2) + 'M'; if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K'; return Math.round(n); }

/* ── Key Levels to Watch ──────────────────────────────────────── */
const KL_KEY = 'briefing_key_levels';   // localStorage: user's chosen assets
let _allLevelRows = [];

function _klSaved() {
  try { const v = JSON.parse(localStorage.getItem(KL_KEY)); return (Array.isArray(v) && v.length) ? v : null; }
  catch (_) { return null; }
}

function loadLevels(rows) {
  _allLevelRows = rows;
  const wanted = _klSaved() || ['BTCUSDT', 'ETHUSDT', 'XAUUSD', 'NIFTY50'];
  _levelAssets = wanted.map(sym => rows.find(r => r.symbol === sym)).filter(Boolean);
  if (!_levelAssets.length) _levelAssets = rows.slice(0, 4);
  _renderLevelTabs();
  if (_levelAssets[0]) _renderLevels(_levelAssets[0].symbol);
}

function _renderLevelTabs() {
  const tabs = document.getElementById('levelTabs');
  if (!tabs) return;
  tabs.innerHTML = _levelAssets.map((a, i) => `<button class="level-tab ${i === 0 ? 'active' : ''}" data-sym="${a.symbol}">${a.symbol}</button>`).join('');
  tabs.querySelectorAll('.level-tab').forEach(t => t.addEventListener('click', () => {
    tabs.querySelectorAll('.level-tab').forEach(x => x.classList.remove('active'));
    t.classList.add('active'); _renderLevels(t.dataset.sym);
  }));
}

function _openKlConfig() {
  const panel = document.getElementById('klConfigPanel');
  if (!panel) return;
  if (panel.style.display !== 'none') { panel.style.display = 'none'; return; }   // toggle off
  const selected = new Set(_levelAssets.map(a => a.symbol));
  const syms = _allLevelRows.map(r => r.symbol);
  panel.innerHTML = `
    <div class="kl-config-title">Choose assets to show <span class="text-muted">(up to 6)</span></div>
    <div class="kl-config-grid">${syms.map(s =>
    `<label class="kl-chk"><input type="checkbox" value="${s}" ${selected.has(s) ? 'checked' : ''}>${s}</label>`).join('')}</div>
    <div class="kl-config-actions">
      <button class="btn btn-sm btn-primary" id="klSave"><i class="bi bi-check2 me-1"></i>Save</button>
      <button class="btn btn-sm btn-outline-secondary" id="klCancel">Cancel</button>
    </div>`;
  panel.style.display = 'block';
  document.getElementById('klCancel').addEventListener('click', () => { panel.style.display = 'none'; });
  document.getElementById('klSave').addEventListener('click', () => {
    const picked = [...panel.querySelectorAll('input:checked')].map(i => i.value).slice(0, 6);
    if (!picked.length) { if (typeof toast === 'function') toast('Pick at least one asset', 'info'); return; }
    localStorage.setItem(KL_KEY, JSON.stringify(picked));
    _levelAssets = picked.map(sym => _allLevelRows.find(r => r.symbol === sym)).filter(Boolean);
    _renderLevelTabs();
    if (_levelAssets[0]) _renderLevels(_levelAssets[0].symbol);
    panel.style.display = 'none';
    if (typeof toast === 'function') toast('Key Levels assets updated', 'success');
  });
}

async function _renderLevels(sym) {
  const asset = _levelAssets.find(a => a.symbol === sym);
  if (!asset) return;
  _levelActive = sym;
  const list = document.getElementById('levelsList');
  const chart = document.getElementById('levelChart');
  const price = asset.price || 0;
  // Try real OHLCV for classic pivots; fall back to % bands off current price.
  let H = price * 1.01, L = price * 0.99, C = price, candles = [];
  const oh = await API.get(`/market-data/${asset.asset_id}/ohlcv`, { timeframe: '1h', limit: 40 }).catch(() => null);
  candles = oh?.data || oh?.ohlcv || oh?.candles || [];
  if (candles.length) {
    const last = candles[candles.length - 1];
    H = last.h ?? last.high ?? H; L = last.l ?? last.low ?? L; C = last.c ?? last.close ?? C;
  }
  const P = (H + L + C) / 3;
  const levels = [
    ['Resistance 2', P + (H - L), 'var(--red)'],
    ['Resistance 1', 2 * P - L, 'var(--red)'],
    ['Pivot', P, 'var(--text-primary)'],
    ['Support 1', 2 * P - H, 'var(--green)'],
    ['Support 2', P - (H - L), 'var(--green)'],
  ];
  if (list) list.innerHTML = levels.map(([n, val, clr]) =>
    `<div class="lv-row"><span class="lv-name">${n}</span><span class="lv-val" style="color:${clr}">${formatPrice(val, asset.market)}</span></div>`).join('') +
    `<div class="lv-row" style="border-top:1px dashed var(--border);margin-top:4px;padding-top:6px"><span class="lv-name">Price</span><span class="lv-val" style="color:var(--accent-light)">${formatPrice(price, asset.market)}</span></div>`;
  if (chart) chart.innerHTML = candles.length ? _candlesSvg(candles.slice(-30), price) : `<div class="text-muted fs-xs text-center py-4">Live chart unavailable — showing levels only</div>`;
}

function _candlesSvg(candles, price) {
  const W = 240, Hh = 150, pad = 4;
  const highs = candles.map(c => c.h ?? c.high), lows = candles.map(c => c.l ?? c.low);
  const hi = Math.max(...highs), lo = Math.min(...lows), rng = (hi - lo) || 1;
  const y = v => pad + (hi - v) / rng * (Hh - 2 * pad);
  const cw = (W - 2 * pad) / candles.length;
  const g = _cssv('--green', '#10b981'), r = _cssv('--red', '#ef4444');
  let s = `<svg viewBox="0 0 ${W} ${Hh}" width="100%" preserveAspectRatio="none" style="max-height:150px">`;
  candles.forEach((c, i) => {
    const o = c.o ?? c.open, cl = c.c ?? c.close, h = c.h ?? c.high, l = c.l ?? c.low;
    const x = pad + i * cw + cw / 2; const up = cl >= o; const col = up ? g : r;
    s += `<line x1="${x}" y1="${y(h)}" x2="${x}" y2="${y(l)}" stroke="${col}" stroke-width="1"/>`;
    s += `<rect x="${x - cw * 0.32}" y="${y(Math.max(o, cl))}" width="${cw * 0.64}" height="${Math.max(1, Math.abs(y(o) - y(cl)))}" fill="${col}"/>`;
  });
  s += `</svg>`;
  return s;
}

/* ── Key Headlines ────────────────────────────────────────────── */
async function loadHeadlines() {
  const data = await API.get('/news/', { per_page: 6 });
  const rows = data?.news || data?.articles || [];
  const el = document.getElementById('headlinesBody');
  if (!el) return;
  if (!rows.length) { el.innerHTML = '<div class="text-muted fs-sm">No headlines available</div>'; return; }
  el.innerHTML = rows.slice(0, 6).map(n => {
    const t = n.published_at ? new Date(n.published_at + 'Z').toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hour12: false }) : '';
    const dot = n.sentiment === 'positive' ? 'var(--green)' : n.sentiment === 'negative' ? 'var(--red)' : 'var(--text-muted)';
    return `<a class="headline-row" href="${n.url || '#'}" target="_blank" rel="noopener">
      <span class="headline-time">${t}</span>
      <span class="headline-dot" style="background:${dot}"></span>
      <span class="headline-text">${n.title || ''}</span></a>`;
  }).join('');
}

/* ── Economic Calendar + Upcoming ─────────────────────────────── */
async function loadEcon() {
  const data = await API.get('/news/economic-calendar');
  const events = (data?.events || []).filter(e => e.event_time);
  const impRank = { high: 0, medium: 1, low: 2 };
  events.sort((a, b) => new Date(a.event_time) - new Date(b.event_time));
  const tb = document.getElementById('econBody');
  const upcoming = document.getElementById('upcomingBody');
  if (tb) {
    if (!events.length) { tb.innerHTML = '<tr><td colspan="5" class="text-center text-muted py-4">No scheduled events</td></tr>'; }
    else tb.innerHTML = events.slice(0, 6).map(e => {
      const imp = (e.impact || 'low').toLowerCase();
      const t = new Date(e.event_time + 'Z').toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hour12: false });
      const impClr = imp === 'high' ? 'var(--red)' : imp === 'medium' ? 'var(--yellow)' : 'var(--text-muted)';
      return `<tr><td class="num">${t}</td><td>${e.title || ''}</td>
        <td><span style="color:${impClr};font-weight:700"><i class="bi bi-bar-chart-fill" style="font-size:9px"></i> ${imp.charAt(0).toUpperCase() + imp.slice(1)}</span></td>
        <td class="num">${e.previous ?? '—'}</td><td class="num">${e.forecast ?? '—'}</td></tr>`;
    }).join('');
  }
  if (upcoming) {
    const next = events.filter(e => new Date(e.event_time + 'Z') >= new Date()).sort((a, b) => (impRank[(a.impact || 'low').toLowerCase()] ?? 2) - (impRank[(b.impact || 'low').toLowerCase()] ?? 2))[0];
    const link = '<a href="/economic-calendar" class="btn btn-sm btn-outline-secondary" style="white-space:nowrap">View Full Calendar</a>';
    if (next) {
      const t = new Date(next.event_time + 'Z').toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hour12: false });
      const imp = (next.impact || 'low').toLowerCase();
      upcoming.innerHTML = `<div class="d-flex align-items-center gap-2"><i class="bi bi-calendar2-event text-accent"></i><div><div style="font-weight:700;font-size:13px">${t} &nbsp;${next.title}</div><div class="fs-xs" style="color:${imp === 'high' ? 'var(--red)' : 'var(--yellow)'}">${imp.charAt(0).toUpperCase() + imp.slice(1)} Impact</div></div></div>${link}`;
    } else {
      upcoming.innerHTML = `<div class="text-muted fs-sm"><i class="bi bi-check-circle text-green me-1"></i>No high-impact events scheduled</div>${link}`;
    }
  }
}

/* ── AI Insight Summary ───────────────────────────────────────── */
function loadInsights(rows, avg, std) {
  const el = document.getElementById('insightsBody'); if (!el) return;
  const sorted = [...rows].sort((a, b) => (b.change_pct || 0) - (a.change_pct || 0));
  const top = sorted[0], bottom = sorted[sorted.length - 1];
  const insights = [];
  if (avg > 0.2) insights.push(['arrow-up-right-circle', 'var(--green)', 'Trend alignment across majors is positive, favouring long setups.']);
  else if (avg < -0.2) insights.push(['arrow-down-right-circle', 'var(--red)', 'Broad weakness across markets — favour caution and short setups.']);
  else insights.push(['dash-circle', 'var(--yellow)', 'Markets are mixed with no clear directional bias — be selective.']);
  if (std > 2) insights.push(['exclamation-triangle', 'var(--yellow)', 'High volatility expected — reduce position size and widen stops.']);
  if (top) insights.push(['graph-up-arrow', 'var(--green)', `${top.symbol} leads gainers (+${(top.change_pct || 0).toFixed(2)}%) — momentum building.`]);
  if (bottom && (bottom.change_pct || 0) < 0) insights.push(['graph-down-arrow', 'var(--red)', `${bottom.symbol} weakest (${(bottom.change_pct || 0).toFixed(2)}%) — bearish bias intact.`]);
  const cryptoAvg = rows.filter(r => r.market === 'crypto').reduce((a, b, _, arr) => a + (b.change_pct || 0) / arr.length, 0);
  insights.push(['currency-bitcoin', cryptoAvg >= 0 ? 'var(--green)' : 'var(--red)', `Crypto market structure ${cryptoAvg >= 0 ? 'bullish above key breakouts' : 'soft below key supports'}.`]);
  el.innerHTML = insights.slice(0, 5).map(([ic, clr, txt]) =>
    `<div class="insight-row"><i class="bi bi-${ic}" style="color:${clr}"></i><span>${txt}</span></div>`).join('');
}

/* ── Today at a Glance ────────────────────────────────────────── */
async function loadGlance() {
  // /signals/summary now returns real today-scoped closed/win/loss/pnl
  // fields — this used to read all-time figures from perf.overall (and one
  // field, ov.wins, that doesn't exist there at all) under a "Today at a
  // Glance" header, which is a contradiction of a different kind than a
  // blank cell: a confidently-displayed number that's simply the wrong scope.
  const summary = await API.get('/signals/summary');
  const buy = summary?.buy_today ?? 0, sell = summary?.sell_today ?? 0, hold = summary?.hold_today ?? 0, exit = summary?.exit_today ?? 0;
  bset('glGenerated', buy + sell + hold + exit);
  bset('glNew', buy + sell);
  bset('glClosed', summary?.closed_today ?? '—');
  bset('glWin', summary?.wins_today ?? '—');
  bset('glWinRate', summary?.win_rate_today != null ? summary.win_rate_today.toFixed(1) + '%' : '—');
  const el = document.getElementById('glPnl');
  if (el) {
    if (summary?.total_pnl_today != null && summary?.closed_today) {
      const v = summary.total_pnl_today;
      el.textContent = (v >= 0 ? '+' : '') + v.toFixed(1) + '%';
      el.className = 'ts-value ' + (v >= 0 ? 'text-green' : 'text-red');
    } else {
      el.textContent = '—';
      el.className = 'ts-value';
    }
  }
}

/* ── Share ────────────────────────────────────────────────────── */
function shareBriefing() {
  const txt = `SmartTrade AI — Morning Briefing (${new Date().toLocaleDateString()})\n` +
    `Regime: ${document.getElementById('bsRegime')?.textContent?.trim()} | Sentiment: ${document.getElementById('bsSentiment')?.textContent?.trim()} | Breadth: ${document.getElementById('breadthPct')?.textContent}`;
  if (navigator.share) navigator.share({ title: 'Morning Briefing', text: txt }).catch(() => { });
  else if (navigator.clipboard) navigator.clipboard.writeText(txt).then(() => { if (typeof toast === 'function') toast('Briefing copied to clipboard', 'success'); });
}

/* ── Load all ─────────────────────────────────────────────────── */
function loadAll() { renderHeader(); loadMarketState(); loadHeadlines(); loadEcon(); loadGlance(); }

document.addEventListener('app:ready', () => {
  if (typeof Chart !== 'undefined') Chart.defaults.color = _cssv('--text-muted', '#94a3b8');
  loadAll();
  document.getElementById('briefRefresh')?.addEventListener('click', loadAll);
  document.getElementById('briefShare')?.addEventListener('click', shareBriefing);
  document.getElementById('klConfigBtn')?.addEventListener('click', _openKlConfig);
  setInterval(loadAll, 120000);
});
