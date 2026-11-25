"use strict";

/**
 * What has to be true before any signed-in screen renders: we know who the
 * user is, which fire temple they belong to, what they're allowed to do,
 * and how they want dates displayed.
 */

import { getPreferences, calendarOptions, logout } from "./api.js";
import { state, saveSession, clearSession, forgetLastPhone } from "./state.js";
import { refreshHeader, chrome, showError } from "./ui.js";
import { navigate } from "./router.js";
import { clearAllDrafts } from "./drafts.js";
import { refreshRequestCount } from "./requests_count.js";
import * as push from "./push.js";
import { askNotificationsOnce } from "./notify_prompt.js";

/** Sign this phone out, from Settings or the waiting screen. `btn` is the
 *  button pressed: off while it runs, back on if it could not be done.
 *  This phone's notifications stop too (the server forgets its push
 *  subscription, and the browser drops it), so a phone handed over shows
 *  nothing more of this account; that is best effort and never holds it up. */
export async function signOut(btn) {
  btn.disabled = true;   // one sign-out per tap; the page reloads when it is done
  const sub = await push.thisPhone();
  // The server has to clear the refresh cookie - it's httpOnly, so
  // dropping the in-memory token alone would sign you back in on the
  // next load.
  try {
    await logout(sub ? sub.endpoint : null);
  } catch (e) {
    // Only the server can clear that cookie, so with no answer the next
    // launch would sign this phone straight back in. Say so (FE-04).
    if (e.status === 0 || e.status >= 500) {
      btn.disabled = false;
      return showError("Could not sign out, because Mobed Diary can't be reached. "
        + "Please try again when you have signal.");
    }
  }
  await push.forget(sub);
  clearSession();
  clearAllDrafts();
  forgetLastPhone();
  state.accessToken = null;
  state.user = null;
  state.offline = false;
  state.preferences = null;
  location.hash = "#/login";
  location.reload();
}

/** Whether this is a Doongerwadi or prayer hall manager's account (D10): none
 *  of the mobed app, only the manager's own screens. */
export function isFuneralManager() {
  return !!(state.user && state.user.account_kind === "funeral_manager");
}

/** A behdin's account (the Parsi app's): none of the mobed app, only the page that offers to make it a mobed's. */
export function isBehdin() {
  return !!(state.user && state.user.account_kind === "behdin");
}

/** Where this account's app opens. */
export function homeFor() {
  if (isBehdin()) return "#/become";
  return isFuneralManager() ? "#/manager" : "#/calendar";
}

/** Whether an admin has let this mobed use the app (DECISIONS D9). A session
 *  saved before access existed has none, and the server is the judge anyway. */
export function hasAccess() {
  return !state.user || !state.user.access || state.user.access === "on";
}

export async function loadSessionExtras() {
  // A behdin has no calendar here: nothing to load, and the server would refuse it.
  if (isBehdin()) return;
  // A manager has no calendar: nothing to load, and the server would refuse it.
  if (isFuneralManager()) return;
  // Preferences drive every calendar label, so a failure here must not take
  // the app down - fall back to the defaults the server would have sent.
  if (!state.preferences) {
    try {
      state.preferences = await getPreferences();
    } catch (e) {
      state.preferences = {
        visible_calendar_systems: ["gregorian", "shenshai"],
        default_secondary_system: "shenshai",
        display_language: "en",
      };
    }
  }
  if (!state.calendarOptions) {
    try {
      state.calendarOptions = await calendarOptions();
    } catch (e) {
      state.calendarOptions = { roj: [], mah: [], geh: [] };
    }
  }
}

/** Called once a sign-in has produced a session. A returning mobed
 *  already has a membership, so this lands them straight in the app; a
 *  first-time one goes to fire-temple search. */
export async function afterSignIn() {
  if (isBehdin()) {
    saveSession();
    chrome(false);
    return navigate("#/become", { replace: true });
  }
  state.currentAgyaryId = state.user.agyaries[0] ? state.user.agyaries[0].id : null;
  await loadSessionExtras();
  chrome(true);
  refreshHeader();
  saveSession();
  // Replace, not push: the login screen must not be a step Back can return to
  // (it would bounce straight forward again and look like Back did nothing).
  navigate(isFuneralManager() ? homeFor() : state.user.agyaries.length ? "#/calendar" : "#/onboarding",
    { replace: true });
  refreshRequestCount();
  setTimeout(askNotificationsOnce, 1500);
}

/** Signed in, which is not the same as "holding a live access token".
 *  An offline boot has a known user and no token; sending them to the
 *  sign-in screen would be wrong, because their session is fine - the
 *  network isn't. */
export function signedIn() {
  return !!(state.user && (state.accessToken || state.offline));
}
