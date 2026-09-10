(() => {
  let inFlight = false;

  const count = v => Number.isFinite(Number(v)) ? Number(v).toLocaleString() : '-';
  const rate = v => v === null || v === undefined ? '-' : `${Number(v).toFixed(1)}%`;
  const set = (id, text) => {
    const element = document.getElementById(id);
    if (element) element.textContent = text;
  };
  const esc = text => typeof STSafe !== 'undefined' ? STSafe.html(String(text)) : String(text);

  function render(data) {
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
      set('tpStatus', 'Terminal asset performance loaded. Open and resolved reads are shown separately in the table.');
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
