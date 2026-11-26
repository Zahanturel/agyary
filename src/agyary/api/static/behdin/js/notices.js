"use strict";

/**
 * The bell in the header, as in the other app: a count on the bell and a list that opens on a tap. Asked
 * again whenever the app comes back to the front and once a minute while it is open. A tap on a notice goes to
 * the ask it is about. A failure here is never shown: the answer is always on "My asks".
 */

import { getNotifications, markNoticesSeen } from "./api.js";
import { state } from "./state.js";
import { signedIn } from "./session.js";
import { navigate } from "/mobed-app/js/router.js";
import { esc } from "./util.js";
import { offerPush } from "./push.js";

const EVERY_MS = 60000;
let timer = null;
let items = [];
let overlay = null;

function ago(iso) {
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.round(hours / 24);
  return `${days} days ago`;
}

function paintBadge() {
  const badge = document.getElementById("bellBadge");
  if (!badge) return;
  const unseen = items.filter((n) => !n.seen).length;
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

function show() {
  close();
  const list = items;
  overlay = document.createElement("div");
  overlay.className = "modal-backdrop";
  overlay.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true" aria-label="Notifications">
      <h2 style="margin:0 0 var(--space-2)">Notifications</h2>
      ${list.length ? list.map((n) => `
        <div class="note ${n.link ? "tap" : ""}" data-nid="${n.id}">
          <b>${esc(n.title)}</b>
          <span>${esc(n.body)}</span>
          <span class="when">${esc(ago(n.created_at))}</span>
        </div>`).join("") : `<p class="meta">Nothing new.</p>`}
      <div style="margin-top:var(--space-4)"><button class="small" id="noteClose">OK</button></div>
    </div>`;
  document.body.appendChild(overlay);
  document.addEventListener("keydown", onKey);
  overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });
  overlay.querySelector("#noteClose").onclick = close;
  overlay.querySelectorAll("[data-nid]").forEach((el) => {
    const n = list.find((x) => x.id === Number(el.dataset.nid));
    if (n && n.link) el.onclick = () => { close(); navigate(n.link); };
  });
  const fresh = list.filter((n) => !n.seen).map((n) => n.id);
  if (fresh.length) {
    items = items.map((n) => (fresh.includes(n.id) ? { ...n, seen: true } : n));
    paintBadge();
    markNoticesSeen(fresh).catch(() => { /* they show as new once more */ });
  }
}

/** Ask for the notices and show the count. A failure is silent. */
export async function refreshNotices() {
  if (!signedIn() || state.offline) return;
  try {
    items = (await getNotifications()).notifications;
  } catch (e) {
    return;
  }
  paintBadge();
}

function tick() {
  if (document.visibilityState === "visible") refreshNotices();
}

/** Called after every screen: keeps the bell up to date for a signed-in person. */
export function syncBell() {
  offerPush();
  const bell = document.getElementById("bellBtn");
  if (!bell) return;
  bell.onclick = async () => { await refreshNotices(); show(); };
  if (signedIn() && !state.offline && !timer) {
    timer = setInterval(tick, EVERY_MS);
    tick();
  } else if (!signedIn() && timer) {
    clearInterval(timer);
    timer = null;
    items = [];
    paintBadge();
  }
}

document.addEventListener("visibilitychange", tick);
window.addEventListener("focus", tick);
