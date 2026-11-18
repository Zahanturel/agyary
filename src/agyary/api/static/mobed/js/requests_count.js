"use strict";

/**
 * The red count on the Requests tab (DECISIONS D10): how many requests for
 * prayers wait for this mobed's answer. Read when the app opens, when it comes
 * back to the front, after signing in or being approved, on the Requests
 * screens, and after an answer. Only a mobed's account that is on has one; a
 * manager has no Requests tab. (No import of session.js, which calls this.)
 */

import { myRequestCount } from "./api.js";
import { state } from "./state.js";

let shown = 0;

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
