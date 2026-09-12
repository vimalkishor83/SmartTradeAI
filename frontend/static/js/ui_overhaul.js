/* Small presentation-layer interactions shared by authenticated pages.
   No data requests or application state are changed here. */
(function () {
  'use strict';

  const sidebar = document.getElementById('sidebar');
  const mobileToggle = document.getElementById('mobileSidebarToggle');
  if (!sidebar || !mobileToggle) return;

  let restoreFocus = null;

  function focusableInSidebar() {
    return Array.from(sidebar.querySelectorAll(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled])'
    )).filter((node) => node.offsetParent !== null);
  }

  function onSidebarStateChange() {
    const open = sidebar.classList.contains('mobile-open');
    if (open) {
      restoreFocus = document.activeElement;
      setTimeout(() => focusableInSidebar()[0]?.focus(), 0);
    } else if (restoreFocus && typeof restoreFocus.focus === 'function') {
      restoreFocus.focus();
      restoreFocus = null;
    }
  }

  new MutationObserver(onSidebarStateChange).observe(sidebar, {
    attributes: true,
    attributeFilter: ['class'],
  });

  document.addEventListener('keydown', (event) => {
    if (!sidebar.classList.contains('mobile-open')) return;

    if (event.key === 'Escape') {
      event.preventDefault();
      mobileToggle.click();
      return;
    }

    if (event.key !== 'Tab') return;
    const focusable = focusableInSidebar();
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
})();
