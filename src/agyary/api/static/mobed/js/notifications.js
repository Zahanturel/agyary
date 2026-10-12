"use strict";

/**
 * The mobed's notifications: a bell in the header and a popup on open.
 *
 * These are what a mobed must not miss - a family replying STOP, a reminder
 * that could not be sent - so anything new is put in front of them the moment
 * they open the app, not left in a list to be found. The popup shows only
 * what they have not seen; the bell keeps everything for the day (the server
 * lets them lapse after 24 hours) so it can be read again.
 */

import { getNotifications, markNotificationsSeen } from "./api.js";
import { state } from "./state.js";
import { esc } from "./util.js";
import { navigate } from "./router.js";

const bell = document.getElementById("bellBtn");
const badge = document.getElementById("bellBadge");

let items = [];
let overlay = null;

function ago(iso) {
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  return `${hours} hour${hours === 1 ? "" : "s"} ago`;
}

function paintBadge() {
  if (!badge) return;
  const unseen = items.filter(n => !n.seen).length;
  badge.textContent = unseen > 9 ? "9+" : String(unseen);
  badge.classList.toggle("hidden", unseen === 0);
}

function close() {
  if (!overlay) return;
  overlay.remove();
  overlay = null;
  document.removeEventListener("keydown", onKey);
}
function onKey(e) { if (e.key === "Escape") close(); }

/** Show `list` in a dialog. If `markSeen`, the popup has now shown them, so
 *  tell the server and they are not shown again on the next open. */
function show(list, { markSeen, title }) {
  close();
  overlay = document.createElement("div");
  overlay.className = "modal-backdrop";
  overlay.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true" aria-label="${esc(title)}">
      <h2 style="margin:0 0 var(--space-2)">${esc(title)}</h2>
      ${list.length ? list.map(n => `
        <div class="note ${n.link ? "tap" : ""}" data-nid="${n.id}">
          <b>${esc(n.title)}</b>
          <span>${esc(n.body)}</span>
          <span class="when">${esc(ago(n.created_at))}</span>
        </div>`).join("")
        : `<p class="meta">Nothing new. Notifications stay here for a day.</p>`}
      <div style="margin-top:var(--space-4)"><button class="small" id="noteClose">OK</button></div>
    </div>`;
  document.body.appendChild(overlay);
  document.addEventListener("keydown", onKey);

  overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });
  overlay.querySelector("#noteClose").onclick = close;
  overlay.querySelectorAll("[data-nid]").forEach(el => {
    const n = list.find(x => x.id === Number(el.dataset.nid));
    if (n && n.link) el.onclick = () => { close(); navigate(n.link); };
  });

  if (markSeen && list.length) {
    const ids = list.map(n => n.id);
    items = items.map(n => (ids.includes(n.id) ? { ...n, seen: true } : n));
    paintBadge();
    markNotificationsSeen(ids).catch(() => { /* they will simply show once more */ });
  }
}

/** Fetch the notifications; with `popup`, put anything unseen in front of the
 *  mobed. A failure is silent - a missing notification must never break the app. */
export async function refreshNotifications({ popup = false } = {}) {
  if (!state.user || !bell) return;
  try {
    items = await getNotifications();
  } catch (e) {
    return;
  }
  paintBadge();
  const fresh = items.filter(n => !n.seen);
  if (popup && fresh.length && !overlay) show(fresh, { markSeen: true, title: "New for you" });
}

export function setupNotifications() {
  if (!bell) return;
  bell.onclick = () => show(items, { markSeen: true, title: "Notifications" });
  // Opening the app again (a PWA resumed from the background) counts as opening it.
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refreshNotifications({ popup: true });
  });
}
