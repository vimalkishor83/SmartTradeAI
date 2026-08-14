export function emptyStateHtml(message, icon = "\u{1F4ED}") {
  return `<div class="state-block"><span class="state-icon">${icon}</span><span class="text-3">${message}</span></div>`;
}
