// Basic service worker for PWA
const CACHE_NAME = 'smarttrade-v1';
const STATIC_ASSETS = ['/dashboard', '/static/css/main.css', '/static/js/app.js'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE_NAME).then(c => c.addAll(STATIC_ASSETS)));
});

self.addEventListener('fetch', e => {
  // Network first, fall back to cache for navigation requests
  if (e.request.mode === 'navigate') {
    e.respondWith(fetch(e.request).catch(() => caches.match('/dashboard')));
  }
});
