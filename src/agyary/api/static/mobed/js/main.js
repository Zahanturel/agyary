"use strict";

/**
 * Wiring: the route table, the guard, and boot.
 *
 * The guard is the point worth reading. Roles are real now - panthaky and
 * caretaker are actually assignable, via invites - so management screens
 * are gated at the route, not merely left out of the nav. Hiding a button
 * has never stopped anyone typing a URL, and these URLs are shareable by
 * design.
 */

import { route, setGuard, setNotFound, start, navigate, resolve } from "./router.js";
import { state, isManager } from "./state.js";
import { tryRefresh, getMe } from "./api.js";
import { chrome, markActiveTab, refreshHeader, tabsEl, profileBtn, flashError, setDefaultFabAction } from "./ui.js";
import { loadSessionExtras, signedIn } from "./session.js";
import { renderLogin } from "./screens/login.js";
import { renderOnboarding } from "./screens/onboarding.js";
import { renderMyDay, renderCalendarScreen } from "./screens/calendar.js";
import { renderNewEvent, renderEditEvent } from "./screens/event.js";
import { renderBehdinList, renderBehdinDetail } from "./screens/behdins.js";
import { renderSettings } from "./screens/settings.js";
import { renderInvites } from "./screens/invites.js";
import { renderSlip } from "./screens/slip.js";

// --- Routes -----------------------------------------------------------------
// `open: true` needs no session; `manage: true` needs an admin role.
route("#/login", renderLogin, { open: true });
route("#/onboarding", renderOnboarding);

route("#/my-day", renderMyDay);
route("#/calendar", renderCalendarScreen);

route("#/event/new", renderNewEvent);
route("#/event/:kind/:id/edit", renderEditEvent);
route("#/machi/:aid/:id", (p) => renderSlip({ kind: "machi", ...p }));
route("#/booking/:aid/:id", (p) => renderSlip({ kind: "booking", ...p }));

route("#/behdins", renderBehdinList);
route("#/behdins/:id", renderBehdinDetail);

route("#/settings", renderSettings);
route("#/manage/invites", renderInvites, { manage: true });

setNotFound(() => navigate("#/my-day", { replace: true }));

// --- Guard ------------------------------------------------------------------
setGuard(async (matched) => {
  if (matched.open) {
    // Already signed in? The login screen has nothing to offer.
    return signedIn() ? "#/my-day" : null;
  }
  if (!signedIn()) return "#/login";

  // Signed in but not yet at a fire temple: everything except onboarding
  // needs one, since every screen is scoped to it.
  const hasAgyary = (state.user.agyaries || []).length > 0;
  if (!hasAgyary && matched.pattern !== "#/onboarding") return "#/onboarding";

  if (matched.manage && !isManager()) {
    // Real gating, not a hidden nav item. Bounce and say why - flashed, so
    // the message survives the redirect's re-render instead of being wiped
    // by it.
    flashError("That section is for the panthaky or caretaker of this fire temple.");
    return "#/settings";
  }
  return null;
});

// --- Chrome -----------------------------------------------------------------
tabsEl.onclick = (e) => {
  const btn = e.target.closest("button");
  if (btn) navigate(btn.dataset.route);
};
profileBtn.onclick = () => navigate("#/settings");
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
  // The refresh cookie is httpOnly and sliding, so a returning user is
  // signed in again without touching the login screen.
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
  markActiveTab(location.hash);
}

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/mobed-sw.js").catch(() => {});
}
boot();

// Keep the tab highlight honest for back/forward navigation too.
window.addEventListener("hashchange", () => markActiveTab(location.hash));
