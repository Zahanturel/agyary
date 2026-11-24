// Minimal app-shell cache for the behdin app's PWA (see mobed-sw.js, which this follows):
// installability and an offline launch, never offline data. Network-first, not cache-first, so a
// deploy is never hidden behind a stale shell.
//
// Every file of the app is listed, and so is every file it takes from Mobed Diary's own folder
// (/mobed-app/): a module missing from the cache means a blank screen offline. tests/test_behdin_shell.py
// checks both lists against what the app really imports.
//
// Routing lives in the client (hash-based), so every route is served by the one page: /behdin, or the root on the
// app's own hostname.
const CACHE_NAME = "behdin-shell-v2";
// How long the network gets before the cached shell is shown. The fetch carries on behind it.
const SHELL_WAIT_MS = 4000;
const SHELL_FILES = [
  "/behdin",
  // The page itself on the app's own hostname (BEHDIN_HOST), where the app is at the root, with no /behdin.
  "/",
  "/behdin-manifest.json",
  "/behdin-icon.svg",
  "/mobed-fonts/figtree.woff2",
  "/mobed-fonts/geist-mono.woff2",
  "/mobed-app/app.css",
  "/behdin-app/behdin.css",
  // Taken from Mobed Diary's own folder (the shared router, page helpers and form marks):
  "/mobed-app/js/router.js",
  "/mobed-app/js/ui.js",
  "/mobed-app/js/state.js",
  "/mobed-app/js/fielderrors.js",
  "/mobed-app/js/install.js",
  "/mobed-app/js/update.js",
  // The behdin app's own:
  "/behdin-app/js/main.js",
  "/behdin-app/js/api.js",
  "/behdin-app/js/brand.js",
  "/behdin-app/js/install.js",
  "/behdin-app/js/session.js",
  "/behdin-app/js/state.js",
  "/behdin-app/js/util.js",
  "/behdin-app/js/screens/become_mobed.js",
  "/behdin-app/js/screens/calendar.js",
  "/behdin-app/js/screens/home.js",
  "/behdin-app/js/screens/login.js",
  "/behdin-app/js/screens/menu.js",
  "/behdin-app/js/screens/off.js",
];

self.addEventListener("install", event => {
  event.waitUntil(
    // Fresh from the network, not the browser's HTTP cache, or old and new
    // modules can end up mixed in here and run together offline (FE-06).
    caches.open(CACHE_NAME).then(cache => cache.addAll(SHELL_FILES.map(u => new Request(u, { cache: "reload" }))))
  );
  self.skipWaiting();
});

self.addEventListener("activate", event => {
  event.waitUntil(
    caches.keys().then(keys =>
      // Only this app's own old shells: Mobed Diary's cache may live on the same origin and is not ours to delete.
      Promise.all(keys.filter(k => k.startsWith("behdin-shell-") && k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);
  if (event.request.method === "GET" && SHELL_FILES.includes(url.pathname)) {
    // `cache: "no-cache"` forces a revalidation against the origin instead
    // of letting the browser answer from its own HTTP cache. Necessary
    // because Cloudflare rewrites our "Cache-Control: no-cache" into a
    // 4-hour max-age on the way out (its Browser Cache TTL setting), so
    // without this a phone can keep serving a pre-deploy module for hours
    // and no amount of reloading shifts it. The revalidation is cheap: the
    // ETag is unchanged for anything we didn't just ship, so it is a 304.
    const fresh = new Request(event.request.url, {
      cache: "no-cache",
      credentials: "same-origin",
    });
    const network = fetch(fresh).then(response => {
      // An error page - Cloudflare's 502 or 530 while the app restarts, a
      // 404 - is never cached, and the shell we already have is shown in
      // its place. Caching it overwrote a working app with the error (FE-03).
      if (!response.ok) return caches.match(event.request).then(cached => cached || response);
      const copy = response.clone();
      return caches.open(CACHE_NAME).then(cache => cache.put(event.request, copy)).then(() => response);
    });
    const tooSlow = new Promise((_, giveUp) => setTimeout(giveUp, SHELL_WAIT_MS));
    event.waitUntil(network.catch(() => {}));
    event.respondWith(
      Promise.race([network, tooSlow])
        // Offline or crawling: whatever we cached last is exactly what should
        // show. With nothing cached, the network is all there is to wait for.
        .catch(() => caches.match(event.request).then(cached => cached || network))
    );
  }
});

// --- Phone notifications ----------------------------------------------------
// R4.4 adds the "push" and "notificationclick" handlers here (see mobed-sw.js for the shape).
