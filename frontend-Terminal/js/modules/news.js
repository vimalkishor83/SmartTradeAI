import { api } from "../api.js";
import { pageHeaderHtml } from "../components/pageHeader.js";
import { renderAsync } from "../components/asyncSection.js";
import { emptyStateHtml } from "../components/emptyState.js";

export function renderNews(main, mod) {
  main.innerHTML = `
    ${pageHeaderHtml(mod.label, mod.desc)}
    <div id="news-list" class="grid" style="grid-template-columns:1fr;"></div>
  `;

  renderAsync(
    main.querySelector("#news-list"),
    () => api.get("/news"),
    (data) => {
      const items = data.news || data.items || data || [];
      if (!items.length) return `<div class="card">${emptyStateHtml("No news items yet.", "\u{1F4F0}")}</div>`;
      return items.map((n) => `
        <div class="card card-hover">
          <div style="font-weight:600;">${n.title || n.headline || "—"}</div>
          <div class="text-3" style="font-size:11px; margin-top:4px;">${n.source || ""} ${n.published_at ? "· " + n.published_at : ""}</div>
          ${n.summary ? `<div class="text-2" style="font-size:12px; margin-top:6px;">${n.summary}</div>` : ""}
        </div>
      `).join("");
    },
  );
}
