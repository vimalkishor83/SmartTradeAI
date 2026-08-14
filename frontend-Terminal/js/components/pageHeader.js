export function pageHeaderHtml(title, desc) {
  return `
    <div class="page-header">
      <div class="page-title">${title}</div>
    </div>
    ${desc ? `<p class="page-desc">${desc}</p>` : ""}
  `;
}
