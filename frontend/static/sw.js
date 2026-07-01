// SmartTradeAI Service Worker — PWA cache + Web Push
const CACHE_NAME = 'smarttrade-v1';
const STATIC_ASSETS = ['/dashboard', '/static/css/main.css', '/static/js/app.js'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE_NAME).then(c => c.addAll(STATIC_ASSETS)));
  self.skipWaiting();
});

self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));

self.addEventListener('fetch', e => {
  if (e.request.mode === 'navigate') {
    e.respondWith(fetch(e.request).catch(() => caches.match('/dashboard')));
  }
});

// ── Web Push ──────────────────────────────────────────────────────────────────
self.addEventListener('push', e => {
  if (!e.data) return;
  let payload = {};
  try { payload = e.data.json(); } catch { payload = { title: 'SmartTradeAI', body: e.data.text() }; }

  const title   = payload.title || 'SmartTradeAI';
  const options = {
    body:    payload.body  || '',
    icon:    payload.icon  || '/static/icons/icon-192.png',
    badge:   '/static/icons/badge-72.png',
    data:    { url: payload.url || '/dashboard' },
    vibrate: [200, 100, 200],
  };

  e.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || '/dashboard';
  e.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(clients => {
      for (const c of clients) {
        if (c.url.includes(url) && 'focus' in c) return c.focus();
      }
      return self.clients.openWindow(url);
    })
  );
});
