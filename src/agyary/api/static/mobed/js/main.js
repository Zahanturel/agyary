"use strict";

/**
 * Wiring: the route table, the guard, and boot.
 *
 * The mobed app is four tabs (Machi, Calendar, Behdins, Requests) and the
 * screens behind them. Anything not listed here does not exist
 * as far as this app is concerned - notably service-catalog
 * editing and fire-temple editing, whose screens remain in the tree but
 * have no route into them. They belong to the agyari management system,
 * which will be designed after talking to panthakies rather than guessed
 * at now.
 */

import { route, setGuard, setNotFound, start, navigate, onNavigated } from "./router.js";
import { watchForUpdates } from "./update.js";
import { state, saveSession, restoreSession, clearSession, homeHash } from "./state.js";
import { clearAllDrafts } from "./drafts.js";
import { calendarHash, boardHash } from "./calendar.js";
import { tryRefresh, getMe, managerPlace, REFRESH_OFFLINE } from "./api.js";
import {
  chrome, refreshHeader, menuBtn, setDefaultFabAction, onTab, paintOffline, flashError, flashInfo,
} from "./ui.js";
import { loadSessionExtras, signedIn, hasAccess, isFuneralManager, homeFor } from "./session.js";
import { renderLogin } from "./screens/login.js";
import { renderOnboarding } from "./screens/onboarding.js";
import { renderCalendarScreen } from "./screens/calendar.js";
import { renderNewEvent, renderEditEvent } from "./screens/event.js";
import { renderNewMachi, renderEditMachi } from "./screens/machi_event.js";
import { renderMachiCalendarScreen } from "./screens/machi_calendar.js";
import { renderBehdinList, renderBehdinNew, renderBehdinDetail } from "./screens/behdins.js";
import { renderMemorialNew } from "./screens/memorial_new.js";
import { renderMemorial } from "./screens/memorial.js";
import { renderMemorialEdit } from "./screens/memorial_edit.js";
import { renderReminders } from "./screens/reminders.js";
import { renderAdmin } from "./screens/admin.js";
import { renderAdminMobeds } from "./screens/admin_mobeds.js";
import { renderAdminFuneralPlaces, renderAdminFuneralPlace } from "./screens/admin_funeral_places.js";
import { renderWaiting } from "./screens/waiting.js";
import { renderMenu } from "./screens/menu.js";
import { renderAgyariLocation } from "./screens/agyari_location.js";
import { renderManagerHome, renderManagerSettings } from "./screens/manager.js";
import { renderRecordNew, renderRecordView, renderRecordEdit, renderRecordSend } from "./screens/manager_record.js";
import { renderSlip } from "./screens/slip.js";
import { renderReview, formFor } from "./screens/review.js";
import { refreshNotifications, setupNotifications } from "./notifications.js";
import { renderRequests, renderRequest } from "./screens/requests.js";
import { renderCallout } from "./screens/callout.js";
import { renderOurMobeds } from "./screens/our_mobeds.js";
import { refreshRequestCount, setupRequestCount } from "./requests_count.js";
import { paintActBanner } from "./acting.js";

// --- Routes -----------------------------------------------------------------
// `open: true` needs no session.
route("#/login", renderLogin, { open: true });
route("#/onboarding", renderOnboarding);
// A mobed an admin has not let in yet, or has switched off (DECISIONS D9).
route("#/waiting", renderWaiting);

// A Doongerwadi or prayer hall manager's own screens (D10): no bottom tabs, and
// none of the mobed app. The guard keeps a manager here and a mobed out.
route("#/manager", renderManagerHome);
route("#/manager/settings", renderManagerSettings, { parent: "#/manager" });
// Recording a death and asking a fire temple (Step 4). "new" before :id.
route("#/manager/record/new", renderRecordNew, { parent: "#/manager" });
route("#/manager/record/:id", renderRecordView, { parent: "#/manager" });
route("#/manager/record/:id/edit", renderRecordEdit, { parent: (p) => `#/manager/record/${p.id}` });
route("#/manager/record/:id/send", renderRecordSend, { parent: (p) => `#/manager/record/${p.id}` });

// `tab` puts the screen under a bottom tab and shows the tab bar. Every screen
// has one except Settings (the menu and what opens from it), sign-in and
// onboarding. "inherit" lights whichever tab the mobed came from.
route("#/calendar", renderCalendarScreen, { tab: "calendar" });
// The view is part of the address: #/calendar/day/2026-09-25. The Machi tab
// ("board") shares the one view object, so the day never moves between tabs.
route("#/calendar/:mode/:date", renderCalendarScreen, { tab: "calendar" });
route("#/board", renderMachiCalendarScreen, { tab: "machi" });
route("#/board/:mode/:date", renderMachiCalendarScreen, { tab: "machi" });
route("#/menu", renderMenu, { parent: homeHash });
// Where the mobed's fire temple is on the map (D10), from Settings.
route("#/fire-temple/location", renderAgyariLocation, { parent: "#/menu" });
// For the numbers in ADMIN_PHONES only (the server enforces it; the menu entry just hides).
route("#/admin", renderAdmin, { parent: "#/menu" });
route("#/admin/mobeds", renderAdminMobeds, { parent: "#/admin" });
// The Doongerwadis, prayer halls and aramgahs (D10). "new" before :id.
route("#/admin/funeral-places", renderAdminFuneralPlaces, { parent: "#/admin" });
route("#/admin/funeral-places/new", () => renderAdminFuneralPlace(), { parent: "#/admin/funeral-places" });
route("#/admin/funeral-places/:id", renderAdminFuneralPlace, { parent: "#/admin/funeral-places" });
// The admin acting for one of them (acting.js): the manager's own screens for that
// place. The guard lets only an admin in; the server checks again on every call.
const actHome = (p) => `#/admin/act/${p.placeId}`;
route("#/admin/act/:placeId", renderManagerHome, { parent: "#/admin/funeral-places" });
route("#/admin/act/:placeId/record/new", renderRecordNew, { parent: actHome });
route("#/admin/act/:placeId/record/:id", renderRecordView, { parent: actHome });
route("#/admin/act/:placeId/record/:id/edit", renderRecordEdit, { parent: (p) => `${actHome(p)}/record/${p.id}` });
route("#/admin/act/:placeId/record/:id/send", renderRecordSend, { parent: (p) => `${actHome(p)}/record/${p.id}` });

// `parent` is where Back goes when there is nothing behind the screen (a
// reload, a shared link) - see router.back(). Screens with a parent get the
// header Back control.
const slipOf = (kind) => (p) => `#/${kind}/${state.currentAgyaryId}/${p.id}`;
route("#/event/new", renderNewEvent, { parent: "#/calendar", tab: "calendar" });
route("#/machi/new", renderNewMachi, { parent: "#/board", tab: "machi" });
// Review is the step after the form: its Back is that form, swapped in place.
route("#/event/review", renderReview("booking"), { parent: () => formFor("booking"), stepBack: true, tab: "calendar" });
route("#/machi/review", renderReview("machi"), { parent: () => formFor("machi"), stepBack: true, tab: "machi" });
route("#/event/:kind/:id/edit", renderEditEvent, { parent: slipOf("booking"), tab: "inherit" });
// Before :aid/:id below - the router matches in registration order, and
// that pattern would otherwise read "edit" as an id. A machi needs its own
// Geh/slot-picker editor; the generic event form can't touch those fields.
route("#/machi/:id/edit", renderEditMachi, { parent: slipOf("machi"), tab: "inherit" });
route("#/machi/:aid/:id", (p) => renderSlip({ kind: "machi", ...p }), { parent: homeHash, tab: "inherit" });
route("#/booking/:aid/:id", (p) => renderSlip({ kind: "booking", ...p }), { parent: homeHash, tab: "inherit" });

// Before :id - the router matches in registration order, and "new"
// would otherwise be read as a behdin id and looked up as NaN.
route("#/behdins", renderBehdinList, { tab: "behdins" });
route("#/behdins/new", renderBehdinNew, { parent: "#/behdins", tab: "behdins" });
route("#/behdins/:id", renderBehdinDetail, { parent: "#/behdins", tab: "behdins" });
// A memorial is a behdin's: made from their page, and Back returns to it.
route("#/behdins/:id/memorials/new", renderMemorialNew, { parent: (p) => `#/behdins/${p.id}`, tab: "behdins" });
// The mobed's own families to remind, from the Behdins tab.
route("#/reminders", renderReminders, { parent: "#/behdins", tab: "behdins" });
route("#/memorial/:id", renderMemorial, { parent: "#/behdins", tab: "behdins" });
// Before :oid, which would otherwise read "edit" as an observance.
route("#/memorial/:id/edit", renderMemorialEdit, { parent: (p) => `#/memorial/${p.id}`, tab: "behdins" });
// Opened from the calendar on one observance's day, landing on that observance.
route("#/memorial/:id/:oid", renderMemorial, { parent: "#/behdins", tab: "behdins" });
// Requests for prayers from a Doongerwadi or prayer hall (D10), the fourth tab.
route("#/requests", renderRequests, { tab: "requests" });
route("#/requests/:id", renderRequest, { parent: "#/requests", tab: "requests" });
// A confirmed panthaky asks the agyari's mobeds on WhatsApp (D10, Step 5c).
route("#/requests/:id/callout", renderCallout, { parent: (p) => `#/requests/${p.id}`, tab: "requests" });
route("#/our-mobeds", renderOurMobeds, { parent: "#/menu" });

// The calendar is home; anything unrecognised lands there.
setNotFound(() => navigate("#/calendar", { replace: true }));

// --- Guard ------------------------------------------------------------------
setGuard(async (matched, params) => {
  state.actFor = null;   // set again only for an admin acting for a place
  const to = await guardFor(matched, params);
  paintActBanner();
  return to;
});

/** The admin acting for a place: in, with the place known for the banner; or
 *  back to the list, saying why, if the server says no (unknown or turned off). */
async function enterActing(params) {
  if (!state.user.is_admin) return "#/calendar";
  const id = Number(params.placeId);
  if (!Number.isInteger(id) || id <= 0) return "#/admin/funeral-places";
  state.actFor = id;
  if (state.actPlace && state.actPlace.id === id) return null;
  try {
    state.actPlace = (await managerPlace()).places[0] || null;
  } catch (e) {
    if (e.status === 403 || e.status === 404) {
      if (state.actFor === id) state.actFor = null;
      flashError(e.message);
      return "#/admin/funeral-places";
    }
    // No signal or a passing failure: the screen itself says so, with Try again.
  }
  return null;
}

async function guardFor(matched, params) {
  if (matched.open) {
    // Already signed in? The login screen has nothing to offer.
    return signedIn() ? "#/calendar" : null;
  }
  if (!signedIn()) return "#/login";

  // A Doongerwadi manager (D10): the waiting screen until approved (D9), then
  // only their own screens. Settings is theirs too. Anything else typed or
  // linked goes to their home, saying why unless it was only the app's default.
  if (isFuneralManager()) {
    if (!hasAccess()) return matched.pattern === "#/waiting" ? null : "#/waiting";
    if (matched.pattern === "#/menu") return "#/manager/settings";
    if (matched.pattern.startsWith("#/manager")) return null;
    if (!["#/calendar", "#/waiting", "#/onboarding"].includes(matched.pattern)) {
      flashInfo("That part of Mobed Diary is for mobeds. This is your own page.");
    }
    return "#/manager";
  }

  // Signed in but not yet at a fire temple: every screen is scoped to one.
  const hasAgyary = (state.user.agyaries || []).length > 0;
  if (!hasAgyary && matched.pattern !== "#/onboarding") return "#/onboarding";

  // Waiting for an admin's approval, or switched off (D9): this one screen,
  // once a fire temple is chosen. The server refuses everything else anyway.
  if (!hasAccess()) return matched.pattern === "#/waiting" || matched.pattern === "#/onboarding" ? null : "#/waiting";
  if (matched.pattern === "#/waiting") return "#/calendar";
  // The manager's screens are not a mobed's; an admin reaches them only acting for a place.
  if (matched.pattern.startsWith("#/manager")) return "#/calendar";
  if (matched.pattern.startsWith("#/admin/act/")) return enterActing(params);
  return null;
}

// --- Chrome -----------------------------------------------------------------
menuBtn.onclick = () => navigate("#/menu");
// A tab opens at the day and view the mobed is on - the Machi and Calendar
// tabs read the same one - rather than resetting to today.
onTab((tab) => navigate({
  machi: boardHash(state.calendar),
  calendar: calendarHash(state.calendar),
  behdins: "#/behdins",
  requests: "#/requests",
}[tab]));

// What the add button does unless a screen overrides it (see ui.showFab).
setDefaultFabAction(() => {
  // A fresh event, not whatever half-finished draft is lying around - but on
  // the day the mobed is looking at. It used to open on today whatever day
  // was on screen, so events added from another day's page landed on today.
  state.draft = state.calendar.mode === "day" && state.calendar.focus
    ? { prefill: { gregorian: state.calendar.focus } }
    : null;
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
      paintOffline();
    }
  } else {
    // The server refused the cookie. This is the one case that really is
    // a logout, so forget the device - and anything half-typed on it.
    clearSession();
    clearAllDrafts();
  }
  if (!signedIn() && !location.hash.startsWith("#/login")) {
    location.replace("#/login");
  }
  await start();
  // What a mobed must not miss goes in front of them as the app opens.
  if (signedIn() && !state.offline && hasAccess()) refreshNotifications({ popup: true });
  refreshRequestCount();
}

// Signal came back after an offline boot. Take the session live and
// re-render whatever is on screen, so the app heals itself instead of
// sitting there signed-in-but-empty until the mobed thinks to reload.
// The server refused the session mid-use: to sign-in, with half-typed forms kept,
// since it is often the same mobed signing straight back in.
window.addEventListener("mobed:signed-out", () => {
  if (!state.user) return;
  clearSession();
  state.accessToken = null;
  state.user = null;
  state.offline = false;
  flashError("You have been signed out. Please sign in again.");
  location.hash = "#/login";
});

// The server says this mobed may not use the app (D9): waiting for approval,
// or switched off while it was open. The one screen that says so.
window.addEventListener("mobed:access", (e) => {
  if (!state.user || state.user.access === e.detail) return;
  state.user.access = e.detail;
  saveSession();
  navigate("#/waiting", { replace: true });
});

// The server says this is a Doongerwadi manager's account (D10) while the app
// was showing part of the mobed app: to their own screen, which is all they have.
window.addEventListener("mobed:account-kind", (e) => {
  if (!state.user) return;
  if (state.user.account_kind === e.detail && location.hash.startsWith("#/manager")) return;
  state.user.account_kind = e.detail;
  saveSession();
  navigate(homeFor(), { replace: true });
});

window.addEventListener("offline", paintOffline);
window.addEventListener("online", async () => {
  paintOffline();
  if (!state.offline) return;
  if (await tryRefresh() !== true) return;
  try {
    state.user = await getMe();
    state.currentAgyaryId = state.user.agyaries[0] ? state.user.agyaries[0].id : null;
    await loadSessionExtras();
    state.offline = false;
    paintOffline();
    saveSession();
    refreshHeader();
    navigate(location.hash || homeFor());
    refreshNotifications({ popup: true });
    refreshRequestCount();
  } catch (e) { /* still not really back; the next online event retries */ }
});

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/mobed-sw.js").catch(() => {});
}
// Pick up a deployed update without waiting for someone to reload by hand,
// but never while a form is half filled in.
onNavigated(watchForUpdates({ busy: () => !!state.draft }));
setupNotifications();
setupRequestCount();
boot();
