// Machi app shell cache — same strategy as the mobed SW (network-first,
// cache-fallback for offline launch). Shares CSS, fonts, and most JS
// modules with the mobed app; only the entry points differ.
const CACHE_NAME = "machi-shell-v1";
const SHELL_FILES = [
  "/machi",
  "/machi-manifest.json",
  "/mobed-icon.svg",
  "/mobed-fonts/geist-sans.woff2",
  "/mobed-fonts/geist-mono.woff2",
  "/mobed-app/app.css",
  "/mobed-app/js/machi_main.js",
  "/mobed-app/js/api.js",
  "/mobed-app/js/router.js",
  "/mobed-app/js/state.js",
  "/mobed-app/js/session.js",
  "/mobed-app/js/ui.js",
  "/mobed-app/js/util.js",
  "/mobed-app/js/calendar.js",
  "/mobed-app/js/names.js",
  "/mobed-app/js/behdin_add.js",
  "/mobed-app/js/screens/login.js",
  "/mobed-app/js/screens/onboarding.js",
  "/mobed-app/js/screens/machi_calendar.js",
  "/mobed-app/js/screens/machi_event.js",
  "/mobed-app/js/screens/behdins.js",
  "/mobed-app/js/screens/menu.js",
  "/mobed-app/js/screens/slip.js",
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
