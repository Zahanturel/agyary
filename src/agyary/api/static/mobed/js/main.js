"use strict";

/**
 * Wiring: the route table, the guard, and boot.
 *
 * The mobed app is five screens. Anything not listed here does not exist
 * as far as this app is concerned - notably service-catalog
 * editing and fire-temple editing, whose screens remain in the tree but
 * have no route into them. They belong to the agyari management system,
 * which will be designed after talking to panthakies rather than guessed
 * at now.
 */

import { route, setGuard, setNotFound, start, navigate } from "./router.js";
import { state, saveSession, restoreSession, clearSession } from "./state.js";
import { tryRefresh, getMe, REFRESH_OFFLINE } from "./api.js";
import { chrome, refreshHeader, menuBtn, setDefaultFabAction } from "./ui.js";
import { loadSessionExtras, signedIn } from "./session.js";
import { renderLogin } from "./screens/login.js";
import { renderOnboarding } from "./screens/onboarding.js";
import { renderCalendarScreen } from "./screens/calendar.js";
import { renderNewEvent, renderEditEvent } from "./screens/event.js";
import { renderBehdinList, renderBehdinNew, renderBehdinDetail } from "./screens/behdins.js";
import { renderMenu } from "./screens/menu.js";
import { renderSlip } from "./screens/slip.js";

// --- Routes -----------------------------------------------------------------
// `open: true` needs no session.
route("#/login", renderLogin, { open: true });
route("#/onboarding", renderOnboarding);

route("#/calendar", renderCalendarScreen);
route("#/menu", renderMenu);

route("#/event/new", renderNewEvent);
route("#/event/:kind/:id/edit", renderEditEvent);
route("#/machi/:aid/:id", (p) => renderSlip({ kind: "machi", ...p }));
route("#/booking/:aid/:id", (p) => renderSlip({ kind: "booking", ...p }));

route("#/behdins", renderBehdinList);
// Before :id - the router matches in registration order, and "new"
// would otherwise be read as a behdin id and looked up as NaN.
route("#/behdins/new", renderBehdinNew);
route("#/behdins/:id", renderBehdinDetail);

// The calendar is home; anything unrecognised lands there.
setNotFound(() => navigate("#/calendar", { replace: true }));

// --- Guard ------------------------------------------------------------------
setGuard(async (matched) => {
  if (matched.open) {
    // Already signed in? The login screen has nothing to offer.
    return signedIn() ? "#/calendar" : null;
  }
  if (!signedIn()) return "#/login";

  // Signed in but not yet at a fire temple: every screen is scoped to one.
  const hasAgyary = (state.user.agyaries || []).length > 0;
  if (!hasAgyary && matched.pattern !== "#/onboarding") return "#/onboarding";
  return null;
});

// --- Chrome -----------------------------------------------------------------
menuBtn.onclick = () => navigate("#/menu");

// What the add button does unless a screen overrides it (see ui.showFab).
setDefaultFabAction(() => {
  // A fresh event, not whatever half-finished draft is lying around.
  state.draft = null;
  navigate("#/event/new");
});

// Swipe left/right to move the calendar a day/week/month. Triggers whichever
// prev/next control is currently on screen rather than duplicating the
// navigation logic, so swipe and tap can never drift apart.
(function setupSwipeNav() {
  const main = document.getElementById("main");
  let startX = 0, startY = 0, tracking = false;
  main.addEventListener("touchstart", (e) => {
    if (e.touches.length !== 1) return;
    startX = e.touches[0].clientX; startY = e.touches[0].clientY; tracking = true;
  }, { passive: true });
  main.addEventListener("touchend", (e) => {
    if (!tracking) return;
    tracking = false;
    const dx = e.changedTouches[0].clientX - startX;
    const dy = e.changedTouches[0].clientY - startY;
    // Require a clearly horizontal, deliberate swipe so a vertical scroll
    // (or a tap on a day cell) is never mistaken for one.
    if (Math.abs(dx) < 60 || Math.abs(dx) < Math.abs(dy) * 1.5) return;
    const btn = main.querySelector(dx < 0 ? "[data-cal-next]" : "[data-cal-prev]");
    if (btn) btn.click();
  }, { passive: true });
})();

// --- Boot -------------------------------------------------------------------
async function boot() {
  chrome(false);
  // The refresh cookie is httpOnly and sliding, so a returning mobed is
  // signed in again without touching the login screen.
  const refreshed = await tryRefresh();
  if (refreshed === true) {
    try {
      state.user = await getMe();
      state.currentAgyaryId = state.user.agyaries[0] ? state.user.agyaries[0].id : null;
      await loadSessionExtras();
      saveSession();
      chrome(true);
      refreshHeader();
    } catch (e) {
      state.accessToken = null;
      state.user = null;
    }
  } else if (refreshed === REFRESH_OFFLINE) {
    // No network - which says nothing about whether the session is good.
    // Come up from the remembered one rather than demanding a fresh
    // WhatsApp sign-in for what is almost always a passing dead spot.
    if (restoreSession()) {
      state.offline = true;
      chrome(true);
      refreshHeader();
    }
  } else {
    // The server refused the cookie. This is the one case that really is
    // a logout, so forget the device.
    clearSession();
  }
  if (!signedIn() && !location.hash.startsWith("#/login")) {
    location.replace("#/login");
  }
  await start();
}

// Signal came back after an offline boot. Take the session live and
// re-render whatever is on screen, so the app heals itself instead of
// sitting there signed-in-but-empty until the mobed thinks to reload.
window.addEventListener("online", async () => {
  if (!state.offline) return;
  if (await tryRefresh() !== true) return;
  try {
    state.user = await getMe();
    state.currentAgyaryId = state.user.agyaries[0] ? state.user.agyaries[0].id : null;
    await loadSessionExtras();
    state.offline = false;
    saveSession();
    refreshHeader();
    navigate(location.hash || "#/calendar");
  } catch (e) { /* still not really back; the next online event retries */ }
});

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/mobed-sw.js").catch(() => {});
}
boot();
