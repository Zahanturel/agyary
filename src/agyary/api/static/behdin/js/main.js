"use strict";

/**
 * Wiring: the route table, the guard, and boot. The router, the page helpers and the form-error
 * marks are shared modules (/mobed-app/js/); everything that knows about a person,
 * the sign-in or the API is this app's.
 */

import { route, setGuard, setNotFound, start, navigate, onNavigated } from "/mobed-app/js/router.js";
import { watchForUpdates } from "/mobed-app/js/update.js";
import { chrome, menuBtn, onTab, flashError, setDefaultFabAction, showFab } from "/mobed-app/js/ui.js";
import { calendarHash } from "/mobed-app/js/calendar.js";
import { setupSwipeNav } from "/mobed-app/js/swipe.js";
import { state, saveSession, restoreSession, clearSession } from "./state.js";
import { tryRefresh, getMe, REFRESH_OFFLINE } from "./api.js";
import { signedIn } from "./session.js";
import { APP_NAME } from "./brand.js";
import { renderLogin } from "./screens/login.js";
import { renderHome } from "./screens/home.js";
import { renderCalendarScreen } from "./screens/calendar.js";
import { renderMenu } from "./screens/menu.js";
import { renderOff } from "./screens/off.js";
import { renderEvent } from "./screens/event.js";
import { renderDeparted } from "./screens/departed.js";
import { renderDepartedForm } from "./screens/departed_form.js";
import { renderAgyari } from "./screens/agyari.js";
import { renderAsk } from "./screens/ask.js";
import { renderAsks, renderAskView, renderAskAnother } from "./screens/asks.js";
import { syncBell } from "./notices.js";

// --- Routes -----------------------------------------------------------------
// `open: true` needs no session. `tab` puts a screen under a bottom tab; `parent` is where Back goes.
route("#/login", renderLogin, { open: true });
route("#/off", renderOff);
route("#/home", renderHome, { tab: "home" });
route("#/calendar", renderCalendarScreen, { tab: "calendar" });
// The view is part of the address, as in the other app: #/calendar/day/2026-09-25.
route("#/calendar/:mode/:date", renderCalendarScreen, { tab: "calendar" });
route("#/menu", renderMenu, { parent: "#/home" });
route("#/agyari", renderAgyari, { parent: "#/home" });
route("#/ask", renderAsk, { parent: "#/home" });
route("#/asks", renderAsks, { parent: "#/home" });
// "another" comes before the bare number, which would otherwise take it.
route("#/asks/:id/another", renderAskAnother, { parent: (p) => `#/asks/${p.id}` });
route("#/asks/:id", renderAskView, { parent: "#/asks" });
// "new" comes before the numbered one, which would otherwise take it.
route("#/event/new", renderEvent, { parent: "#/calendar", tab: "calendar" });
route("#/event/:id", renderEvent, { parent: "#/calendar", tab: "calendar" });
route("#/departed/new", renderDepartedForm, { parent: "#/event/new", tab: "calendar" });
route("#/departed/:id/edit", renderDepartedForm, { parent: (p) => `#/departed/${p.id}` });
route("#/departed/:id", renderDeparted, { parent: "#/calendar", tab: "calendar" });

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
onTab((tab) => navigate(tab === "calendar" ? calendarHash(state.calendar) : "#/home"));
// What the add button does on the calendar: a new event, on the day that is open.
setDefaultFabAction(() => {
  state.draftDate = state.calendar.mode === "day" && state.calendar.focus ? state.calendar.focus : null;
  navigate("#/event/new");
});
setupSwipeNav();

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
// A half-made ask is not worth losing to an update; everything else can wait for the next screen.
const applyUpdate = watchForUpdates({ busy: () => !!state.ask && location.hash === "#/ask" });
onNavigated((...args) => {
  syncBell();
  // The add button belongs to the calendar alone.
  if (!location.hash.startsWith("#/calendar")) showFab(false);
  return applyUpdate(...args);
});
document.title = APP_NAME;
boot();
