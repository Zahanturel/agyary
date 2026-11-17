"use strict";

/**
 * The one screen for a mobed who may not use the app yet (DECISIONS D9):
 * signed up and waiting for an admin's approval, or switched off by one.
 * Nothing they saved is touched. It checks again by itself whenever the app
 * is opened, and moves on to the calendar the moment they are approved.
 */

import { getMe } from "../api.js";
import { state, saveSession, currentAgyary } from "../state.js";
import { chrome, mainEl, showFab, showError, showInfo } from "../ui.js";
import { esc } from "../util.js";
import { navigate } from "../router.js";
import { signOut, loadSessionExtras } from "../session.js";
import { refreshNotifications } from "../notifications.js";

const onScreen = () => location.hash.startsWith("#/waiting");

/** Ask the server again. `quiet`: said nothing when it has not changed (the
 *  check made on opening the app, as opposed to a tap on Check again). */
async function checkAgain({ quiet = false, btn = null } = {}) {
  if (btn) btn.disabled = true;
  let me;
  try {
    me = await getMe();
  } catch (e) {
    if (btn) btn.disabled = false;
    if (!quiet) showError(e.message);
    return;
  }
  const before = state.user && state.user.access;
  state.user = me;
  if (!state.currentAgyaryId && me.agyaries[0]) state.currentAgyaryId = me.agyaries[0].id;
  saveSession();
  if (!onScreen()) return;
  if (me.access === "on") {
    // Settings and calendar names may have fallen back to defaults while
    // the server was saying no: load them properly now.
    state.preferences = null;
    await loadSessionExtras();
    navigate("#/calendar", { replace: true });
    refreshNotifications({ popup: true });
    return;
  }
  if (me.access !== before) return renderWaiting();
  if (btn) btn.disabled = false;
  if (!quiet) showInfo(me.access === "pending" ? "Still waiting for approval." : "Your access is still switched off.");
}

let watching = false;

export function renderWaiting() {
  chrome(false);
  showFab(false);
  const user = state.user || {};
  const pending = user.access === "pending";
  const temple = currentAgyary();
  const digits = (user.support_phone || "").replace(/\D/g, "");
  const contact = digits
    ? `<a class="button secondary" href="https://wa.me/${esc(digits)}" target="_blank" rel="noopener">Message us on WhatsApp</a>`
    : "";

  mainEl.innerHTML = `
    <div class="card" role="status">
      <h2>${pending ? "Waiting for approval" : "Your access is switched off"}</h2>
      ${pending
        ? `<p>Thank you, ${esc(user.name || "")}. Your request to use Mobed Diary${temple
            ? ` at <b>${esc(temple.name)}</b>` : ""} has been sent.</p>
           ${temple && temple.panthaky_claim_waiting
             ? `<p class="meta">You said you are the panthaky here. The admin checks that too.</p>` : ""}
           <p class="meta">You can start as soon as it is approved. This screen moves on by
             itself when you open the app after that.</p>`
        : `<p>Your access to Mobed Diary is switched off at the moment.</p>
           <p class="meta">Everything you saved is kept, just as you left it. Nothing is sent to your
             families while access is off. To turn it back on, please get in touch${digits ? "" : " with the person who gave you Mobed Diary"}.</p>`}
      <div class="action-bar" style="margin-top:14px">
        <button id="wtCheck">Check again</button>
        ${contact}
      </div>
      <div style="margin-top:18px"><button class="ghost small" id="wtSignOut">Sign out</button></div>
    </div>`;

  document.getElementById("wtCheck").onclick = (ev) => checkAgain({ btn: ev.currentTarget });
  document.getElementById("wtSignOut").onclick = (ev) => signOut(ev.currentTarget);

  // Opening the app again (a PWA resumed from the background) asks again.
  if (!watching) {
    watching = true;
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden && onScreen()) checkAgain({ quiet: true });
    });
  }
}
