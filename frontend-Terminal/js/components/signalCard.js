function directionBadge(direction) {
  const d = (direction || "WAIT").toUpperCase();
  if (d === "LONG" || d === "BUY") return `<span class="badge badge-up">LONG</span>`;
  if (d === "SHORT" || d === "SELL") return `<span class="badge badge-down">SHORT</span>`;
  return `<span class="badge badge-neutral">WAIT</span>`;
}

function fmt(n) {
  if (n === null || n === undefined || n === "") return "—";
  const num = Number(n);
  if (Number.isNaN(num)) return String(n);
  return num.toLocaleString(undefined, { maximumFractionDigits: num < 10 ? 4 : 2 });
}

export function signalCardHtml(signal) {
  // Field names confirmed against the live GET /api/v1/signals response —
  // the API returns `asset` (e.g. "XAUTUSDT") and `signal_type` ("BUY"/
  // "SELL"), not "symbol"/"direction" as originally guessed, which left
  // every card showing a blank symbol.
  const symbol = signal.asset || signal.symbol || signal.asset_symbol || signal.pair || "—";
  const name = signal.name || signal.asset_name || "";
  const direction = signal.signal_type || signal.direction || signal.side || "WAIT";
  const confidence = signal.confidence_score ?? signal.confidence;
  const entry = signal.entry_price ?? signal.entry;
  const stop = signal.stop_loss ?? signal.stop;
  const t1 = signal.target1 ?? signal.target_1 ?? signal.take_profit_1;
  const price = signal.current_price ?? signal.last_price;
  const rawStrategy = signal.reasoning || signal.strategy || signal.strategy_name || signal.rationale_summary;
  // `reasoning` is a long pipe-separated technical breakdown — show just
  // the first couple of factors on the compact card, not the full string.
  const strategy = rawStrategy && rawStrategy.includes("|")
    ? rawStrategy.split("|").slice(0, 2).join(" · ").trim()
    : rawStrategy;

  return `
    <div class="card signal-card">
      <div style="display:flex; justify-content:space-between; align-items:flex-start;">
        <div>
          <div style="font-weight:700; font-size:14px;">${symbol}</div>
          <div class="text-3" style="font-size:11px;">${name}</div>
        </div>
        ${directionBadge(direction)}
      </div>
      <div style="display:flex; align-items:baseline; gap:8px; margin:10px 0;">
        <span class="mono" style="font-size:18px; font-weight:700;">${fmt(price)}</span>
      </div>
      ${strategy ? `<div class="text-2" style="font-size:12px; margin-bottom:8px;">${strategy}</div>` : ""}
      ${confidence !== undefined ? `
        <div class="text-3" style="font-size:11px; margin-bottom:2px;">Confidence</div>
        <div style="font-weight:700; margin-bottom:8px;">${Math.round(Number(confidence) <= 1 ? confidence * 100 : confidence)}%</div>
      ` : ""}
      ${entry !== undefined ? `
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px; font-size:12px;">
          <div><span class="text-3">Entry</span><br/><span class="mono">${fmt(entry)}</span></div>
          <div><span class="text-3">Stop</span><br/><span class="mono">${fmt(stop)}</span></div>
          <div><span class="text-3">Target 1</span><br/><span class="mono">${fmt(t1)}</span></div>
        </div>
      ` : ""}
    </div>
  `;
}
