/* Standalone Terminal presentation helpers.
   This augments the existing markup without changing API requests, routing,
   permissions, or market data behavior. */
(function () {
  'use strict';

  function focusable(root) {
    return Array.from(root.querySelectorAll(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled])'
    )).filter((node) => node.offsetParent !== null);
  }

  function mount(root) {
    const header = root.querySelector('.header');
    const shell = root.querySelector('.body-shell');
    const nav = root.querySelector('.sidenav');
    if (!header || !shell || !nav) return false;

    const existingMenu = header.querySelector('#mobile-menu-btn');
    let menu = header.querySelector('#terminal-ui-menu, #mobile-menu-btn');
    if (!menu) {
      menu = document.createElement('button');
      menu.type = 'button';
      menu.id = 'terminal-ui-menu';
      menu.className = 'icon-btn terminal-ui-menu';
      menu.textContent = 'Menu';
      menu.setAttribute('aria-label', 'Open navigation');
      menu.setAttribute('aria-expanded', 'false');
      header.querySelector('.header-actions')?.prepend(menu);
    }

    const existingTheme = header.querySelector('#theme-toggle');
    let theme = header.querySelector('#terminal-ui-theme, #theme-toggle');
    if (!theme) {
      theme = document.createElement('button');
      theme.type = 'button';
      theme.id = 'terminal-ui-theme';
      theme.className = 'icon-btn terminal-ui-theme';
      theme.textContent = 'Theme';
      header.querySelector('.header-actions')?.append(theme);
    }

    function syncTheme() {
      const light = document.documentElement.getAttribute('data-theme') === 'light';
      theme.setAttribute('aria-label', light ? 'Switch to dark theme' : 'Switch to light theme');
      theme.title = light ? 'Switch to dark theme' : 'Switch to light theme';
    }

    function close() {
      shell.classList.remove('mobile-nav-open');
      document.documentElement.classList.remove('terminal-mobile-nav-open');
      menu.setAttribute('aria-expanded', 'false');
      menu.setAttribute('aria-label', 'Open navigation');
    }

    function open() {
      shell.classList.add('mobile-nav-open');
      document.documentElement.classList.add('terminal-mobile-nav-open');
      menu.setAttribute('aria-expanded', 'true');
      menu.setAttribute('aria-label', 'Close navigation');
      setTimeout(() => focusable(nav)[0]?.focus(), 0);
    }

    if (!existingMenu && !menu.dataset.bound) {
      menu.addEventListener('click', () => {
        shell.classList.contains('mobile-nav-open') ? close() : open();
      });
      menu.dataset.bound = '1';
    }

    if (!existingTheme && !theme.dataset.bound) {
      theme.addEventListener('click', () => {
        const light = document.documentElement.getAttribute('data-theme') !== 'light';
        document.documentElement.setAttribute('data-theme', light ? 'light' : 'dark');
        try {
          localStorage.setItem('theme', light ? 'light' : 'dark');
          localStorage.setItem('stt_theme', light ? 'light' : 'dark');
        } catch (_) {}
        syncTheme();
      });
      theme.dataset.bound = '1';
    }

    if (!nav.dataset.uiOverhaulBound) {
      nav.addEventListener('click', (event) => {
        if (event.target.closest('.sidenav-item')) close();
      });
      nav.dataset.uiOverhaulBound = '1';
    }
    syncTheme();
    return true;
  }

  function observe() {
    const root = document.getElementById('app');
    if (!root) return;
    const tryMount = () => mount(root);
    tryMount();
    new MutationObserver(tryMount).observe(root, { childList: true, subtree: true });
    document.addEventListener('keydown', (event) => {
      const shell = root.querySelector('.body-shell');
      const nav = root.querySelector('.sidenav');
      const menu = root.querySelector('#terminal-ui-menu, #mobile-menu-btn');
      if (!shell?.classList.contains('mobile-nav-open') || !nav || !menu) return;
      if (event.key === 'Escape') {
        event.preventDefault();
        menu.click();
        return;
      }
      if (event.key !== 'Tab') return;
      const items = focusable(nav);
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', observe);
  else observe();
})();
