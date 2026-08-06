// Minimal app-shell cache for the mobed PWA - installability (offline
// launch works), not offline data sync (My Day/Machi Board always hit the
// API fresh; caching those would show stale bookings, worse than a
// loading spinner). Network-first, not cache-first: a cache-first shell
// would keep serving a stale mobed.html indefinitely after every deploy,
// since the browser only re-installs this worker when THIS file's bytes
// change, not when the cached shell's contents do.
const CACHE_NAME = "mobed-shell-v5";
const SHELL_FILES = [
  "/mobed", "/mobed-manifest.json", "/mobed-icon.svg",
  "/mobed-fonts/geist-sans.woff2", "/mobed-fonts/geist-mono.woff2",
];

self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(SHELL_FILES))
  );
  self.skipWaiting();
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);
  if (event.request.method === "GET" && SHELL_FILES.includes(url.pathname)) {
    event.respondWith(
      fetch(event.request)
        .then(response => {
          const copy = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, copy));
          return response;
        })
        .catch(() => caches.match(event.request))
    );
  }
});
