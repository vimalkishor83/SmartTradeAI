(() => {
  let inFlight = false;

  const value = (v, fallback = '-') => v === null || v === undefined ? fallback : v;
  const count = v => Number.isFinite(Number(v)) ? Number(v).toLocaleString() : '-';
  const rate = v => v === null || v === undefined ? '-' : `${Number(v).toFixed(1)}%`;
  const set = (id, text) => {
    const element = document.getElementById(id);
    if (element) element.textContent = text;
  };
  const esc = text => typeof STSafe !== 'undefined' ? STSafe.html(String(text)) : String(text);

  function render(data) {
    const closed = data?.closed || {};
    const open = data?.open_stats || {};
    set('tpTotal', count(data?.total_logged));
    set('tpOpen', count(data?.open));
    set('tpDecisive', count(data?.decisive));
    set('tpWinsLosses', `${count(closed.wins)} / ${count(closed.losses)}`);
    set('tpWinRate', rate(closed.win_rate));
    set('tpExpired', count(data?.expired));

    const pnl = open.avg_unrealized_pnl_pct;
    const pnlText = pnl === null || pnl === undefined ? 'live P&L unavailable' : `${Number(pnl) >= 0 ? '+' : ''}${Number(pnl).toFixed(2)}% average unrealized P&L`;
    const stages = Array.isArray(open.by_stage) ? open.by_stage.map(stage => `${esc(stage.label)}: ${count(stage.count)}`).join(' | ') : '';
    set('tpOpenMeta', `Open snapshot: ${count(data?.open)} reads | ${pnlText} | ${open.avg_age_minutes == null ? 'age unavailable' : `${Number(open.avg_age_minutes).toFixed(0)}m average age`}${stages ? ` | ${stages}` : ''}`);
    set('tpUpdated', `Updated ${new Date().toLocaleTimeString()}`);

    const timeframeBody = document.getElementById('tpTimeframeBody');
    const timeframeRows = Array.isArray(data?.by_timeframe) ? data.by_timeframe : [];
    timeframeBody.innerHTML = timeframeRows.length ? timeframeRows.map(row => `<tr><td><strong>${esc(row.name)}</strong></td><td>${count(row.total)}</td><td>${count(row.open)}</td><td>${count(row.decisive)}</td><td>${count(row.expired)}</td><td>${rate(row.win_rate)}</td></tr>`).join('') : '<tr><td colspan="6" class="text-center text-muted py-4">No Terminal reads logged yet.</td></tr>';

    const assetBody = document.getElementById('tpAssetBody');
    const assetRows = Array.isArray(data?.by_asset) ? data.by_asset : [];
    assetBody.innerHTML = assetRows.length ? assetRows.map(row => `<tr><td><strong>${esc(row.name)}</strong></td><td>${count(row.total)}</td><td>${count(row.open)}</td><td>${count(row.decisive)}</td><td class="tp-positive">${count(row.wins)}</td><td class="tp-negative">${count(row.losses)}</td><td>${rate(row.win_rate)}</td></tr>`).join('') : '<tr><td colspan="7" class="text-center text-muted py-4">No Terminal reads logged yet.</td></tr>';
  }

  async function load() {
    if (inFlight) return;
    inFlight = true;
    const button = document.getElementById('tpRefresh');
    if (button) { button.disabled = true; button.setAttribute('aria-busy', 'true'); }
    try {
      const data = await API.get('/signals/terminal-performance');
      if (!data || data.error) throw new Error('unavailable');
      render(data);
      set('tpStatus', 'Terminal performance loaded. Open reads are operational only; closed statistics use resolved outcomes.');
    } catch (_) {
      set('tpStatus', 'Terminal performance is temporarily unavailable. Try refreshing.');
    } finally {
      inFlight = false;
      if (button) { button.disabled = false; button.setAttribute('aria-busy', 'false'); }
    }
  }

  document.addEventListener('app:ready', () => {
    document.getElementById('tpRefresh')?.addEventListener('click', load);
    load();
    setInterval(load, 30000);
  });
})();
