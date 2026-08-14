export function comingSoonHtml(mod) {
  return `
    <div class="card soon-card">
      <div class="icon-badge">${mod.icon}</div>
      <h2>${mod.label} — coming soon</h2>
      <p>${mod.desc} This module isn't wired to a live data source yet — we'll enable it once its backend is built out. No placeholder numbers are shown here on purpose.</p>
    </div>
  `;
}
