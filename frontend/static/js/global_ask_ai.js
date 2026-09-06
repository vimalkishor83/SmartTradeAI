/* ═══════════════════════════════════════════════
   Ask AI — global floating widget, every logged-in page.

   Grounds answers in whatever asset context the current page actually
   has: asset/detail.html defines window.ASSET_ID/ASSET_NAME, so when
   those exist the popup targets that asset via the same
   POST /assets/ask -> _gather_asset_context() path the in-page "Ask AI
   about {symbol}" panel uses. Everywhere else (Dashboard, Terminal,
   Settings, ...) there's no single asset to ground on, so it falls back
   to a platform-wide snapshot on the backend (_gather_general_context()).
   ═══════════════════════════════════════════════ */
(function () {
  const hasAssetContext = () => typeof window.ASSET_ID !== 'undefined' && typeof window.ASSET_NAME !== 'undefined';

  function suggestionsFor() {
    if (hasAssetContext()) {
      const sym = window.ASSET_NAME;
      return [
        `What's driving ${sym} today?`,
        `Is ${sym}'s current trend bullish or bearish?`,
        `What's the latest signal for ${sym}?`,
      ];
    }
    return [
      "What's the overall market sentiment right now?",
      'How many active signals are there right now?',
      "What's the platform's win rate?",
    ];
  }

  function renderContextLine(el) {
    el.textContent = hasAssetContext()
      ? `Asking about ${window.ASSET_NAME}`
      : 'General market & platform question';
  }

  function renderSuggestions(container, onPick) {
    container.innerHTML = suggestionsFor().map((q, i) =>
      `<button type="button" class="ask-ai-suggestion-chip" data-q="${i}">${q}</button>`
    ).join('');
    const qs = suggestionsFor();
    container.querySelectorAll('.ask-ai-suggestion-chip').forEach((btn) => {
      btn.addEventListener('click', () => onPick(qs[+btn.dataset.q]));
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    const fab = document.getElementById('askAiFab');
    const fabIcon = document.getElementById('askAiFabIcon');
    const popup = document.getElementById('askAiPopup');
    const closeBtn = document.getElementById('askAiPopupClose');
    const contextLine = document.getElementById('askAiPopupContext');
    const suggestions = document.getElementById('askAiSuggestions');
    const answerBox = document.getElementById('askAiPopupAnswer');
    const input = document.getElementById('askAiFabInput');
    const sendBtn = document.getElementById('askAiFabSend');
    if (!fab || !popup) return;
    let lastFocus = null;

    function open() {
      lastFocus = document.activeElement;
      renderContextLine(contextLine);
      suggestions.style.display = '';
      renderSuggestions(suggestions, (q) => { input.value = q; submit(); });
      answerBox.style.display = 'none';
      answerBox.innerHTML = '';
      popup.classList.add('open');
      popup.setAttribute('aria-hidden', 'false');
      fab.setAttribute('aria-expanded', 'true');
      fab.setAttribute('aria-label', 'Close Ask AI');
      fabIcon.className = 'bi bi-x-lg';
      input.focus();
    }
    function close() {
      popup.classList.remove('open');
      popup.setAttribute('aria-hidden', 'true');
      fab.setAttribute('aria-expanded', 'false');
      fab.setAttribute('aria-label', 'Open Ask AI');
      fabIcon.className = 'bi bi-chat-left-text-fill';
      if (lastFocus && typeof lastFocus.focus === 'function') lastFocus.focus();
      lastFocus = null;
    }
    function toggle() { popup.classList.contains('open') ? close() : open(); }

    async function submit() {
      const question = input.value.trim();
      if (!question) return;
      input.disabled = true; sendBtn.disabled = true;
      suggestions.style.display = 'none';
      answerBox.style.display = '';
      answerBox.innerHTML = '<i class="bi bi-hourglass-split me-1"></i>Thinking…';

      const payload = { question };
      if (hasAssetContext()) payload.asset_id = window.ASSET_ID;

      const res = await API.post('/assets/ask', payload);
      input.disabled = false; sendBtn.disabled = false;
      input.value = '';

      if (res && res.answer) {
        answerBox.innerHTML = `<div style="color:var(--text-primary);line-height:1.5">${res.answer.replace(/</g, '&lt;')}</div>`;
      } else if (res && res.message) {
        answerBox.innerHTML = `<span class="text-warning">${res.message}</span>`;
      } else {
        answerBox.innerHTML = `<span class="text-danger">${res?.error || 'Could not get an answer — try again.'}</span>`;
      }
    }

    fab.addEventListener('click', toggle);
    closeBtn.addEventListener('click', close);
    sendBtn.addEventListener('click', submit);
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); submit(); }
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && popup.classList.contains('open')) close();
    });
    document.addEventListener('click', (e) => {
      if (popup.classList.contains('open') && !popup.contains(e.target) && !fab.contains(e.target)) close();
    });
  });
})();
