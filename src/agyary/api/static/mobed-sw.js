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
//
// Leaflet (/mobed-app/vendor/leaflet/) is not in the shell: it is loaded only
// when a screen shows a map, and a map needs the network for its tiles anyway.
// Offline, the picker says the map could not load.
const CACHE_NAME = "mobed-shell-v94";
// How long the network gets before the cached shell is shown (FE-05). The
// fetch carries on behind it, so the next launch has the new one.
const SHELL_WAIT_MS = 4000;
const SHELL_FILES = [
  "/mobed",
  "/mobed-manifest.json",
  "/mobed-icon.svg",
  "/mobed-fonts/figtree.woff2",
  "/mobed-fonts/geist-mono.woff2",
  "/mobed-app/app.css",
  "/mobed-app/js/main.js",
  "/mobed-app/js/api.js",
  "/mobed-app/js/router.js",
  "/mobed-app/js/state.js",
  "/mobed-app/js/session.js",
  "/mobed-app/js/ui.js",
  "/mobed-app/js/util.js",
  "/mobed-app/js/update.js",
  "/mobed-app/js/calendar.js",
  "/mobed-app/js/names.js",
  "/mobed-app/js/behdin_add.js",
  "/mobed-app/js/notifications.js",
  "/mobed-app/js/memorial_form.js",
  "/mobed-app/js/fielderrors.js",
  "/mobed-app/js/drafts.js",
  "/mobed-app/js/repeat.js",
  "/mobed-app/js/behdin_delete.js",
  "/mobed-app/js/memorial_share.js",
  "/mobed-app/js/paid_chip.js",
  "/mobed-app/js/service_toggle.js",
  "/mobed-app/js/install.js",
  "/mobed-app/js/push.js",
  "/mobed-app/js/push_card.js",
  "/mobed-app/js/location_picker.js",
  "/mobed-app/js/requests_count.js",
  "/mobed-app/js/acting.js",
  "/mobed-app/js/screens/login.js",
  "/mobed-app/js/screens/onboarding.js",
  "/mobed-app/js/screens/calendar.js",
  "/mobed-app/js/screens/event.js",
  "/mobed-app/js/screens/machi_calendar.js",
  "/mobed-app/js/screens/machi_event.js",
  "/mobed-app/js/screens/behdins.js",
  "/mobed-app/js/screens/memorial.js",
  "/mobed-app/js/screens/memorial_edit.js",
  "/mobed-app/js/screens/memorial_new.js",
  "/mobed-app/js/screens/reminders.js",
  "/mobed-app/js/screens/admin.js",
  "/mobed-app/js/screens/admin_mobeds.js",
  "/mobed-app/js/screens/admin_funeral_places.js",
  "/mobed-app/js/screens/waiting.js",
  "/mobed-app/js/screens/manager.js",
  "/mobed-app/js/screens/manager_record.js",
  "/mobed-app/js/screens/manager_record_flow.js",
  "/mobed-app/js/screens/manager_behdins.js",
  "/mobed-app/js/screens/requests.js",
  "/mobed-app/js/screens/our_mobeds.js",
  "/mobed-app/js/screens/request_settings.js",
  "/mobed-app/js/cal_switch.js",
  "/mobed-app/js/screens/menu.js",
  "/mobed-app/js/screens/agyari_location.js",
  "/mobed-app/js/screens/slip.js",
  "/mobed-app/js/screens/review.js",
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
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
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

// --- Phone notifications (web push, services/web_push.py) ---------------------
// For every account that is on (an admin's "a new mobed is waiting", a mobed's
// "a Doongerwadi asks for prayers"). The server sends a title,
// a body, the page to open and a tag; one of each tag shows at a time.
self.addEventListener("push", event => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = { body: event.data ? event.data.text() : "" }; }
  event.waitUntil(self.registration.showNotification(data.title || "Mobed Diary", {
    body: data.body || "",
    icon: "/mobed-icon-192.png",
    badge: "/mobed-icon-192.png",
    tag: data.tag || "mobed-diary",
    renotify: true,
    data: { url: data.url || "/mobed" },
  }));
});

// A tap opens that page: in the app if it is already open, else in a new window.
self.addEventListener("notificationclick", event => {
  event.notification.close();
  const target = new URL((event.notification.data && event.notification.data.url) || "/mobed", self.location.origin);
  // Only our own pages.
  if (target.origin !== self.location.origin) return;
  event.waitUntil((async () => {
    const open = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    const app = open.find(c => new URL(c.url).pathname === "/mobed");
    if (app) {
      await app.focus();
      return app.navigate(target.href).catch(() => {});
    }
    return self.clients.openWindow(target.href);
  })());
});
