"use strict";

/**
 * The red count on the Requests tab (DECISIONS D10): how many requests for
 * prayers wait for this mobed's answer. Read when the app opens, when it comes
 * back to the front, after signing in or being approved, on the Requests
 * screens, and after an answer. Only a mobed's account that is on has one; a
 * manager has no Requests tab. (No import of session.js, which calls this.)
 */

import { myRequestCount } from "./api.js";
import { state, currentAgyary } from "./state.js";

let shown = 0;

/** The Mobeds tab is the panthaky's only: a mobed's account that is on, whose
 *  fire temple's role is panthaky (the same rule as the Mobeds button in Settings). */
export function paintMobedsTab() {
  const tab = document.querySelector('#tabs [data-tab="mobeds"]');
  if (!tab) return;
  const u = state.user;
  const a = u && currentAgyary();
  const show = !!(a && a.role === "panthaky" && u.account_kind !== "funeral_manager" && (!u.access || u.access === "on"));
  tab.classList.toggle("hidden", !show);
}

export function paintRequestCount(n) {
  shown = Math.max(0, Number(n) || 0);
  const badge = document.getElementById("reqBadge");
  const tab = document.querySelector('#tabs [data-tab="requests"]');
  if (badge) {
    badge.textContent = shown > 9 ? "9+" : String(shown);
    badge.classList.toggle("hidden", shown === 0);
  }
  if (tab) tab.setAttribute("aria-label", shown ? `Requests, ${shown} waiting` : "Requests");
}

/** Ask the server again. A failure keeps the count already shown: it is a
 *  reminder, and the Requests screen itself says when it cannot load. */
export async function refreshRequestCount() {
  paintMobedsTab();
  const u = state.user;
  if (!u || !state.accessToken || state.offline || u.account_kind === "funeral_manager"
      || (u.access && u.access !== "on") || !(u.agyaries || []).length) {
    return paintRequestCount(0);
  }
  try {
    paintRequestCount((await myRequestCount()).waiting);
  } catch (e) {
    paintRequestCount(shown);
  }
}

export function setupRequestCount() {
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refreshRequestCount();
  });
}
