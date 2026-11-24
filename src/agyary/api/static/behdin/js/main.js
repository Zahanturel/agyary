"use strict";

/**
 * Wiring: the route table, the guard, and boot. The router, the page helpers and the form-error
 * marks are shared modules (/mobed-app/js/); everything that knows about a person,
 * the sign-in or the API is this app's.
 */

import { route, setGuard, setNotFound, start, navigate, onNavigated } from "/mobed-app/js/router.js";
import { watchForUpdates } from "/mobed-app/js/update.js";
import { chrome, menuBtn, onTab, flashError } from "/mobed-app/js/ui.js";
import { state, saveSession, restoreSession, clearSession } from "./state.js";
import { tryRefresh, getMe, REFRESH_OFFLINE } from "./api.js";
import { signedIn } from "./session.js";
import { APP_NAME } from "./brand.js";
import { renderLogin } from "./screens/login.js";
import { renderHome } from "./screens/home.js";
import { renderCalendar } from "./screens/calendar.js";
import { renderMenu } from "./screens/menu.js";
import { renderOff } from "./screens/off.js";

// --- Routes -----------------------------------------------------------------
// `open: true` needs no session. `tab` puts a screen under a bottom tab; `parent` is where Back goes.
route("#/login", renderLogin, { open: true });
route("#/off", renderOff);
route("#/home", renderHome, { tab: "home" });
route("#/calendar", renderCalendar, { tab: "calendar" });
route("#/menu", renderMenu, { parent: "#/home" });

setNotFound(() => navigate("#/home", { replace: true }));

// --- Guard ------------------------------------------------------------------
setGuard(async (matched) => {
  if (matched.open) return signedIn() ? "#/home" : null;   // nothing for a signed-in person to do at sign-in
  if (!signedIn()) return "#/login";
  return null;
});

// --- Chrome -----------------------------------------------------------------
menuBtn.onclick = () => navigate("#/menu");
// The name in the header goes home.
{
  const title = document.getElementById("headerTitle");
  const home = () => { if (signedIn()) navigate("#/home"); };
  title.setAttribute("role", "link");
  title.setAttribute("tabindex", "0");
  title.onclick = home;
  title.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); home(); } };
}
onTab((tab) => navigate({ home: "#/home", calendar: "#/calendar" }[tab]));

// --- Boot -------------------------------------------------------------------
async function boot() {
  chrome(false);
  // The refresh cookie is httpOnly and sliding, so a returning person is signed in again without
  // touching the sign-in screen.
  const refreshed = await tryRefresh();
  if (refreshed === true) {
    try {
      state.user = await getMe();
      saveSession();
      chrome(true);
    } catch (e) {
      state.accessToken = null;
      state.user = null;
    }
  } else if (refreshed === REFRESH_OFFLINE) {
    // No network says nothing about whether the session is good: come up from the remembered one
    // rather than demanding a fresh sign-in for what is almost always a passing dead spot.
    if (restoreSession()) {
      state.offline = true;
      chrome(true);
    }
  } else {
    // The server refused the cookie: the one case that really is a logout.
    clearSession();
  }
  // The first screen is Home, not the router's own default.
  if (!location.hash) history.replaceState({ depth: 0 }, "", signedIn() ? "#/home" : "#/login");
  else if (!signedIn() && !location.hash.startsWith("#/login")) location.replace("#/login");
  await start();
}

// The server refused the session mid-use: to sign-in.
window.addEventListener("behdin:signed-out", () => {
  if (!state.user) return;
  clearSession();
  state.accessToken = null;
  state.user = null;
  state.offline = false;
  flashError("You have been signed out. Please sign in again.");
  location.hash = "#/login";
});

// An admin has switched this account off while the app was open.
window.addEventListener("behdin:access", (e) => {
  if (state.user && e.detail === "off") navigate("#/off", { replace: true });
});

// Signal came back after an offline launch: take the session live and redraw what is on screen.
window.addEventListener("online", async () => {
  if (!state.offline) return;
  if (await tryRefresh() !== true) return;
  try {
    state.user = await getMe();
    state.offline = false;
    saveSession();
    navigate(location.hash || "#/home");
  } catch (e) { /* still not really back; the next online event retries */ }
});

if ("serviceWorker" in navigator) {
  // The worker is served from the root, so its scope is given: on the app's own hostname the page is
  // "/" and the scope "/"; anywhere else it is /behdin, which covers nothing else.
  const scope = location.pathname === "/" ? "/" : "/behdin";
  navigator.serviceWorker.register("/behdin-sw.js", { scope }).catch(() => {});
}
// Pick up a deployed update without waiting for someone to reload by hand.
onNavigated(watchForUpdates({ busy: () => false }));
document.title = APP_NAME;
boot();
