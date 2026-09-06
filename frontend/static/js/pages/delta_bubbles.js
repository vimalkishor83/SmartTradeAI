/* ═══════════════════════════════════════════════
   Delta Bubbles — market bubble map by coin group
   ═══════════════════════════════════════════════ */
let dbGroup = 'major';
let dbData = null;
let dbTableView = false;
let dbLoadInFlight = false;
const DB_GROUPS = new Set(['major', 'defi', 'meme', 'options']);

const dbSet = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = (v ?? '—'); };

function dbRadiusFor(value, minV, maxV) {
  const MIN_R = 26, MAX_R = 100;
  if (maxV <= minV) return (MIN_R + MAX_R) / 2;
  const sMin = Math.sqrt(minV), sMax = Math.sqrt(maxV), s = Math.sqrt(value);
  const t = (s - sMin) / (sMax - sMin);
  return MIN_R + t * (MAX_R - MIN_R);
}

function dbAbbr(n) {
  if (n == null || isNaN(n)) return '—';
  const abs = Math.abs(n);
  if (abs >= 1e9) return (n / 1e9).toFixed(2) + 'B';
  if (abs >= 1e6) return (n / 1e6).toFixed(2) + 'M';
  if (abs >= 1e3) return (n / 1e3).toFixed(2) + 'K';
  return (+n).toFixed(2);
}

// Deterministic hash -> hue, so the same symbol always gets the same
// monogram-avatar color across reloads instead of a random one.
function dbAvatarColor(symbol) {
  symbol = String(symbol || '');
  let hash = 0;
  for (let i = 0; i < symbol.length; i++) hash = (hash * 31 + symbol.charCodeAt(i)) >>> 0;
  const hue = hash % 360;
  return `hsl(${hue}, 62%, 46%)`;
}

function dbTickerRoot(symbol) {
  return String(symbol || '').replace(/_OPTIONS$/, '').replace(/USD$/, '');
}

/* ── Circle packing ────────────────────────────────────────────
   No charting/physics library in this app, so this is a small
   self-contained collision-relaxation pack: seed circles along a
   golden-angle spiral (close to their converged spacing already, so fewer
   iterations are needed), then repeatedly (a) pull everything gently
   toward the shared centroid and (b) push overlapping pairs apart along
   their center line, split by relative size so bigger bubbles move less.
   Runs once per group load/switch, not per animation frame. */
function dbPackLayout(items) {
  const n = items.length;
  if (!n) return { nodes: [], width: 0, height: 0 };

  const nodes = items.map((it, i) => {
    const angle = i * 2.399963; // golden angle — spreads seed points evenly
    const radius = 6 * Math.sqrt(i);
    return { ...it, x: radius * Math.cos(angle), y: radius * Math.sin(angle) };
  });

  const iterations = n > 120 ? 160 : n > 40 ? 260 : 340;
  const centerStrength = 0.02;
  for (let iter = 0; iter < iterations; iter++) {
    for (const a of nodes) {
      a.x -= a.x * centerStrength;
      a.y -= a.y * centerStrength;
    }
    for (let i = 0; i < n; i++) {
      const a = nodes[i];
      for (let j = i + 1; j < n; j++) {
        const b = nodes[j];
        const dx = b.x - a.x, dy = b.y - a.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
        const minDist = a.r + b.r + 3;
        if (dist < minDist) {
          const overlap = (minDist - dist) / dist;
          const totalR = a.r + b.r;
          const aShare = b.r / totalR;
          const bShare = a.r / totalR;
          const mx = dx * overlap * 0.5, my = dy * overlap * 0.5;
          a.x -= mx * aShare; a.y -= my * aShare;
          b.x += mx * bShare; b.y += my * bShare;
        }
      }
    }
  }

  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const nd of nodes) {
    minX = Math.min(minX, nd.x - nd.r);
    minY = Math.min(minY, nd.y - nd.r);
    maxX = Math.max(maxX, nd.x + nd.r);
    maxY = Math.max(maxY, nd.y + nd.r);
  }
  const pad = 14;
  const width = (maxX - minX) + pad * 2;
  const height = (maxY - minY) + pad * 2;
  for (const nd of nodes) {
    nd.x = nd.x - minX + pad;
    nd.y = nd.y - minY + pad;
  }
  return { nodes, width, height };
}

function dbRenderCanvas(data) {
  const canvas = document.getElementById('bubbleCanvas');
  if (!canvas) return;
  const bubbles = Array.isArray(data?.bubbles) ? data.bubbles.filter(b => b && typeof b === 'object') : [];
  if (!bubbles.length) {
    canvas.style.height = '';
    canvas.innerHTML = '<div class="text-center text-muted py-5 w-100"><i class="bi bi-inbox d-block mb-2" style="font-size:24px;opacity:.4"></i>No data for this group</div>';
    return;
  }
  const values = bubbles.map((b) => Math.max(0, Number(b.size_metric) || 0));
  const minV = Math.min(...values);
  const maxV = Math.max(...values);
  const withRadius = bubbles.map((b, i) => ({ ...b, size_metric: values[i], r: dbRadiusFor(values[i], minV, maxV) }));
  // Biggest first so the dominant bubble seeds near the spiral's (and
  // therefore the pack's) center, matching how these market maps read.
  withRadius.sort((a, b) => b.r - a.r);

  const { nodes, width, height } = dbPackLayout(withRadius);
  canvas.style.height = Math.max(height, 320) + 'px';

  const bubblesHtml = nodes.map((b, i) => {
    const d = b.r * 2;
    const change = Number(b.change_pct);
    const up = Number.isFinite(change) && change >= 0;
    const sign = up ? '+' : '';
    const avatarD = Math.max(16, Math.min(d * 0.28, 40));
    const ticker = dbTickerRoot(b.symbol);
    const title = `${b.label || b.symbol || ''}\n${data.color_label || 'Change'}: ${sign}${Number.isFinite(change) ? change.toFixed(2) : '—'}%\n${data.metric_label || 'Metric'}: ${dbAbbr(b.turnover_usd ?? b.size_metric)}${b.price != null ? `\nPrice: ${b.price}` : ''}`;
    const delay = (i % 12) * 0.35;
    const popDelay = Math.min(i * 0.012, 0.6);

    const showAvatar = d >= 44;
    const showName = d >= 70;
    const showPct = d >= 48;

    return `<div class="mkt-bubble ${up ? 'dir-up' : 'dir-down'}" title="${STSafe.html(title)}"
        style="width:${d}px;height:${d}px;left:${b.x - b.r}px;top:${b.y - b.r}px;animation-delay:${delay}s,${popDelay}s">
      <span class="mkt-bubble-ticker" style="font-size:${Math.max(9, Math.min(d * 0.14, 12))}px">${STSafe.html(ticker)}</span>
      ${showAvatar ? `<span class="mkt-bubble-avatar" style="width:${avatarD}px;height:${avatarD}px;background:${dbAvatarColor(b.symbol)};font-size:${avatarD * 0.42}px">${STSafe.html(ticker.slice(0, 2))}</span>` : ''}
      ${showName ? `<span class="mkt-bubble-name" style="font-size:${Math.max(10, Math.min(d * 0.12, 14))}px">${STSafe.html(b.label || b.symbol || '')}</span>` : ''}
      ${showPct ? `<span class="mkt-bubble-pct" style="color:${up ? 'var(--green)' : 'var(--red)'};font-size:${Math.max(9, Math.min(d * 0.13, 13))}px">${sign}${Number.isFinite(change) ? change.toFixed(1) : '—'}%</span>` : ''}
    </div>`;
  }).join('');

  canvas.innerHTML = `<div class="bubble-canvas-inner" style="width:${width}px;height:${height}px">${bubblesHtml}</div>`;
}

function dbRenderTable(data) {
  const tb = document.getElementById('bubbleTableBody');
  if (!tb) return;
  // Sort/display the real turnover_usd where it exists, not size_metric --
  // that's now a blended (turnover x move-magnitude) visualization value
  // for bubble sizing, and this table's column is explicitly labeled
  // "24h Turnover (USD)" (metric_label), so showing the blended number
  // here would just be mislabeled data. Options bubbles have no
  // turnover_usd (they're sized by open interest, which IS what
  // metric_label says for that group), hence the fallback.
  const metricOf = (b) => b.turnover_usd ?? b.size_metric;
  const bubbles = [...(Array.isArray(data?.bubbles) ? data.bubbles : [])].sort((a, b) => metricOf(b) - metricOf(a));
  dbSet('thColor', data.color_label || 'Change');
  dbSet('thSize', data.metric_label || 'Metric');
  if (!bubbles.length) {
    tb.innerHTML = '<tr><td colspan="4" class="text-center text-muted py-4">No data for this group</td></tr>';
    return;
  }
  tb.innerHTML = bubbles.map((b) => {
    const change = Number(b.change_pct);
    return `
    <tr>
      <td><span class="asset-cell-name">${STSafe.html(b.label || b.symbol || '')}</span></td>
      <td class="num">${Number.isFinite(Number(b.price)) ? Number(b.price).toLocaleString() : '—'}</td>
      <td class="num" style="color:${change >= 0 ? 'var(--green)' : 'var(--red)'};font-weight:700">${change >= 0 ? '+' : ''}${Number.isFinite(change) ? change.toFixed(2) : '—'}%</td>
      <td class="num">${dbAbbr(metricOf(b))}</td>
    </tr>
  `;
  }).join('');
}

async function dbLoad() {
  if (dbLoadInFlight) return;
  dbLoadInFlight = true;
  document.getElementById('bubbleCanvas').innerHTML = '<div class="text-center text-muted py-5 w-100"><i class="bi bi-hourglass-split d-block mb-2" style="font-size:24px"></i>Loading…</div>';
  let data = null;
  try {
    data = await API.get('/scanner/delta-bubbles?group=' + encodeURIComponent(DB_GROUPS.has(dbGroup) ? dbGroup : 'major')).catch(() => null);
  } finally {
    dbLoadInFlight = false;
  }
  if (!data) {
    dbSet('bubbleMeta', 'Failed to load');
    return;
  }
  dbData = data;
  const bubbles = Array.isArray(data.bubbles) ? data.bubbles : [];
  dbSet('bubbleMeta', `${bubbles.length} · generated ${data.generated_at ? new Date(data.generated_at * 1000).toLocaleTimeString() : '—'}`);
  document.getElementById('bubbleLegend').style.display = '';
  // The API call above already has a network-failure fallback ("Failed to
  // load"); this catches the separate case of a real response whose shape
  // trips up rendering (canvas or table) -- previously an uncaught
  // exception here would leave the "Loading…" placeholder frozen with no
  // indication anything went wrong, which reads as "blank"/stuck rather
  // than a visible, honest error.
  try {
    dbRenderCanvas(data);
    dbRenderTable(data);
  } catch (e) {
    console.error('Delta Bubbles render failed:', e);
    document.getElementById('bubbleCanvas').innerHTML =
      '<div class="text-center text-muted py-5 w-100"><i class="bi bi-exclamation-triangle d-block mb-2" style="font-size:24px"></i>Could not render this group — try Refresh.</div>';
  }
}

function dbSetTableView(on) {
  dbTableView = on;
  document.getElementById('bubbleCanvas').style.display = on ? 'none' : '';
  document.getElementById('bubbleTableWrap').style.display = on ? '' : 'none';
  document.getElementById('tableViewBtn').innerHTML = on
    ? '<i class="bi bi-circle me-1"></i>Bubble View'
    : '<i class="bi bi-table me-1"></i>Table View';
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
  dbLoad();
  document.getElementById('refreshBubblesBtn')?.addEventListener('click', dbLoad);
  document.getElementById('tableViewBtn')?.addEventListener('click', () => dbSetTableView(!dbTableView));
  document.querySelectorAll('#bubbleTypeTabs .scan-chip').forEach((btn) => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('#bubbleTypeTabs .scan-chip').forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      dbGroup = DB_GROUPS.has(btn.dataset.group) ? btn.dataset.group : 'major';
      const titleEl = document.getElementById('bubbleSectionTitle');
      if (titleEl) titleEl.innerHTML = `<i class="bi bi-circle-fill text-accent me-1"></i>${STSafe.html(btn.textContent.trim())}`;
      dbLoad();
    });
  });
});
