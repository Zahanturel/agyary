// Minimal app-shell cache for the mobed PWA - installability (offline
// launch works), not offline data sync (the calendar always hits the API
// fresh; caching that would show stale bookings, worse than a loading
// spinner). Network-first, not cache-first: a cache-first shell would keep
// serving stale code indefinitely after every deploy, since the browser
// only re-installs this worker when THIS file's bytes change, not when the
// cached shell's contents do.
//
// The shell is now a page plus its ES modules rather than one inlined HTML
// file. Every module has to be listed: a module missing from the cache
// means the app launches offline to a blank screen and a module-resolution
// error, which is worse than not launching at all.
//
// Routing lives in the client (hash-based), so every route is served by
// "/mobed" itself - no per-route entries are needed or possible here.
const CACHE_NAME = "mobed-shell-v10";
const SHELL_FILES = [
  "/mobed",
  "/mobed-manifest.json",
  "/mobed-icon.svg",
  "/mobed-fonts/geist-sans.woff2",
  "/mobed-fonts/geist-mono.woff2",
  "/mobed-app/app.css",
  "/mobed-app/js/main.js",
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
  "/mobed-app/js/screens/calendar.js",
  "/mobed-app/js/screens/event.js",
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
