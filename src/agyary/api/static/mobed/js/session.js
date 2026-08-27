"use strict";

/**
 * What has to be true before any signed-in screen renders: we know who the
 * user is, which fire temple they belong to, what they're allowed to do,
 * and how they want dates displayed.
 */

import { getPreferences, calendarOptions } from "./api.js";
import { state, saveSession } from "./state.js";
import { refreshHeader, chrome } from "./ui.js";
import { navigate } from "./router.js";

export async function loadSessionExtras() {
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
  state.currentAgyaryId = state.user.agyaries[0] ? state.user.agyaries[0].id : null;
  await loadSessionExtras();
  chrome(true);
  refreshHeader();
  saveSession();
  navigate(state.user.agyaries.length ? "#/calendar" : "#/onboarding");
}

/** Signed in, which is not the same as "holding a live access token".
 *  An offline boot has a known user and no token; sending them to the
 *  sign-in screen would be wrong, because their session is fine - the
 *  network isn't. */
export function signedIn() {
  return !!(state.user && (state.accessToken || state.offline));
}
