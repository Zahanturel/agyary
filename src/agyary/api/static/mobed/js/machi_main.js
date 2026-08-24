"use strict";

/**
 * Machi app entry point — machi.gotiadarian.com.
 *
 * Same backend and shared modules as the mobed app, different route table:
 * machi calendar (not booking calendar), machi add/edit (not event),
 * and shared screens (behdins, menu, login, onboarding, slip).
 */

import { route, setGuard, setNotFound, start, navigate } from "./router.js";
import { state } from "./state.js";
import { tryRefresh, getMe } from "./api.js";
import { chrome, refreshHeader, menuBtn, setDefaultFabAction } from "./ui.js";
import { loadSessionExtras, signedIn } from "./session.js";
import { renderLogin } from "./screens/login.js";
import { renderOnboarding } from "./screens/onboarding.js";
import { renderMachiCalendarScreen } from "./screens/machi_calendar.js";
import { renderNewMachi, renderEditMachi } from "./screens/machi_event.js";
import { renderBehdinList, renderBehdinDetail } from "./screens/behdins.js";
import { renderMenu } from "./screens/menu.js";
import { renderSlip } from "./screens/slip.js";

// --- Routes -----------------------------------------------------------------
route("#/login", renderLogin, { open: true });
route("#/onboarding", renderOnboarding);

route("#/calendar", renderMachiCalendarScreen);
route("#/menu", renderMenu);

route("#/machi/new", renderNewMachi);
route("#/machi/:id/edit", renderEditMachi);
route("#/machi/:aid/:id", (p) => renderSlip({ kind: "machi", ...p }));

route("#/behdins", renderBehdinList);
route("#/behdins/:id", renderBehdinDetail);

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
  state.draft = null;
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
boot();
