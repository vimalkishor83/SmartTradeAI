export function statCardHtml({ label, value, sub, tone }) {
  const toneClass = tone === "up" ? "text-up" : tone === "down" ? "text-down" : tone === "warn" ? "text-warn" : "";
  return `
    <div class="card">
      <div class="text-3" style="font-size:11px; text-transform:uppercase; letter-spacing:.03em;">${label}</div>
      <div class="mono ${toneClass}" style="font-size:22px; font-weight:700; margin-top:4px;">${value}</div>
      ${sub ? `<div class="text-3" style="font-size:11px; margin-top:2px;">${sub}</div>` : ""}
    </div>
  `;
}
