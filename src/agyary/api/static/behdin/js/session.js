"use strict";

import { logout } from "./api.js";
import { thisPhone, forget } from "./push.js";
import { state, saveSession, clearSession, forgetLastPhone } from "./state.js";
import { chrome, showError } from "/mobed-app/js/ui.js";
import { navigate } from "/mobed-app/js/router.js";
import { APP_NAME } from "./brand.js";


/** Signed in, which is not the same as "holding a live access token": an offline launch has a known
 *  person and no token, and sending them to sign-in would be wrong, because the network is down,
 *  not their session. */
export function signedIn() {
  return !!(state.user && (state.accessToken || state.offline));
}

/** Forget everything of this person on this phone and start again at sign-in. */
export function forgetEverything() {
  clearSession();
  forgetLastPhone();
  state.accessToken = null;
  state.user = null;
  state.offline = false;
  location.hash = "#/login";
  location.reload();
}

/** Sign this phone out. `btn` is the button pressed: off while it runs, back on if it could not be done. */
export async function signOut(btn) {
  btn.disabled = true;   // one sign-out per tap; the page reloads when it is done
  const sub = await thisPhone();
  try {
    await logout(sub ? sub.endpoint : null);
  } catch (e) {
    // Only the server can clear the httpOnly cookie, so with no answer the next launch would sign
    // this phone straight back in. Say so.
    if (e.status === 0 || e.status >= 500) {
      btn.disabled = false;
      return showError(`Could not sign out, because ${APP_NAME} can't be reached. Please try again when you have signal.`);
    }
  }
  await forget(sub);
  forgetEverything();
}

/** Called once a sign-in has produced a session. */
export function afterSignIn() {
  chrome(true);
  saveSession();
  // Replace, not push: the sign-in screen must not be a step Back can return to.
  navigate("#/home", { replace: true });
}
