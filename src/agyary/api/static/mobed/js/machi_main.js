"use strict";

/**
 * Machi app entry point — machi.gotiadarian.com.
 *
 * Same backend and shared modules as the mobed app, different route table:
 * machi calendar (not booking calendar), machi add/edit (not event),
 * and shared screens (behdins, menu, login, onboarding, slip).
 */

import { route, setGuard, setNotFound, start, navigate, onNavigated } from "./router.js";
import { watchForUpdates } from "./update.js";
import { state } from "./state.js";
import { tryRefresh, getMe } from "./api.js";
import { chrome, refreshHeader, menuBtn, setDefaultFabAction } from "./ui.js";
import { loadSessionExtras, signedIn } from "./session.js";
import { renderLogin } from "./screens/login.js";
import { renderOnboarding } from "./screens/onboarding.js";
import { renderMachiCalendarScreen } from "./screens/machi_calendar.js";
import { renderNewMachi, renderEditMachi } from "./screens/machi_event.js";
import { renderBehdinList, renderBehdinNew, renderBehdinDetail } from "./screens/behdins.js";
import { renderMenu } from "./screens/menu.js";
import { renderSlip } from "./screens/slip.js";
import { renderReview, formFor } from "./screens/review.js";

// --- Routes -----------------------------------------------------------------
route("#/login", renderLogin, { open: true });
route("#/onboarding", renderOnboarding);

route("#/calendar", renderMachiCalendarScreen);
route("#/calendar/:mode/:date", renderMachiCalendarScreen);
route("#/menu", renderMenu, { parent: "#/calendar" });

route("#/machi/new", renderNewMachi, { parent: "#/calendar" });
route("#/machi/review", renderReview("machi"), { parent: () => formFor("machi"), stepBack: true });
route("#/machi/:id/edit", renderEditMachi, { parent: (p) => `#/machi/${state.currentAgyaryId}/${p.id}` });
route("#/machi/:aid/:id", (p) => renderSlip({ kind: "machi", ...p }), { parent: "#/calendar" });

route("#/behdins", renderBehdinList, { parent: "#/menu" });
// Before :id - the router matches in registration order, and "new"
// would otherwise be read as a behdin id and looked up as NaN.
route("#/behdins/new", renderBehdinNew, { parent: "#/behdins" });
route("#/behdins/:id", renderBehdinDetail, { parent: "#/behdins" });

setNotFound(() => navigate("#/calendar", { replace: true }));

// --- Guard ------------------------------------------------------------------
setGuard(async (matched) => {
  if (matched.open) {
    return signedIn() ? "#/calendar" : null;
  }
  if (!signedIn()) return "#/login";
  const hasAgyary = (state.user.agyaries || []).length > 0;
  if (!hasAgyary && matched.pattern !== "#/onboarding") return "#/onboarding";
  return null;
});

// --- Chrome -----------------------------------------------------------------
menuBtn.onclick = () => navigate("#/menu");

setDefaultFabAction(() => {
  // A fresh event, not whatever half-finished draft is lying around - but on
  // the day the mobed is looking at. It used to open on today whatever day
  // was on screen, so events added from another day's page landed on today.
  state.draft = state.calendar.mode === "day" && state.calendar.focus
    ? { prefill: { gregorian: state.calendar.focus } }
    : null;
  navigate("#/machi/new");
});

// Swipe navigation
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
    if (Math.abs(dx) < 60 || Math.abs(dx) < Math.abs(dy) * 1.5) return;
    const btn = main.querySelector(dx < 0 ? "[data-cal-next]" : "[data-cal-prev]");
    if (btn) btn.click();
  }, { passive: true });
})();

// --- Boot -------------------------------------------------------------------
async function boot() {
  chrome(false);
  if (await tryRefresh()) {
    try {
      state.user = await getMe();
      state.currentAgyaryId = state.user.agyaries[0] ? state.user.agyaries[0].id : null;
      await loadSessionExtras();
      chrome(true);
      refreshHeader();
    } catch (e) {
      state.accessToken = null;
      state.user = null;
    }
  }
  if (!signedIn() && !location.hash.startsWith("#/login")) {
    location.replace("#/login");
  }
  await start();
}

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/machi-sw.js").catch(() => {});
}
// Pick up a deployed update without waiting for someone to reload by hand,
// but never while a form is half filled in.
onNavigated(watchForUpdates({ busy: () => !!state.draft }));
boot();
