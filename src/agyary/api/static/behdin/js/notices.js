"use strict";

/**
 * The bell in the header: a dot when there is a notice the person has not read, and a list of them
 * in a sheet. Asked again whenever the app comes back to the front and once a minute while it is open.
 * Tapping a notice goes to the ask it is about. A failure here is never shown: the bell is a help,
 * and the answer is always on "My asks".
 */

import { getNotifications, markNoticesSeen } from "./api.js";
import { state } from "./state.js";
import { signedIn } from "./session.js";
import { openSheet, closeSheet } from "/mobed-app/js/ui.js";
import { navigate } from "/mobed-app/js/router.js";
import { esc } from "./util.js";

const EVERY_MS = 60000;
let timer = null;
let unread = 0;
let bell = null;

/** Called after every screen: shows the bell to a signed-in person and keeps it up to date. */
export function syncBell() {
  bell = bell || document.getElementById("bellBtn");
  if (!bell) return;
  const show = signedIn() && !state.offline && !/^#\/(login|off)/.test(location.hash);
  bell.classList.toggle("hidden", !show);
  if (!show) { stop(); return; }
  bell.onclick = openNotices;
  start();
}

function paintDot() {
  if (!bell) return;
  const dot = bell.querySelector(".bell-dot");
  if (dot) dot.classList.toggle("hidden", unread === 0);
  bell.setAttribute("aria-label", unread ? `Notices, ${unread} new` : "Notices");
}

/** Ask for the notices and light or clear the dot. Returns them, or null when it could not be read. */
export async function refreshNotices() {
  if (!signedIn() || state.offline) return null;
  try {
    const list = (await getNotifications()).notifications;
    unread = list.filter((n) => !n.seen).length;
    paintDot();
    return list;
  } catch (e) {
    return null;
  }
}

function tick() {
  if (document.visibilityState === "visible") refreshNotices();
}

function start() {
  if (timer) return;
  timer = setInterval(tick, EVERY_MS);
  tick();
}

function stop() {
  if (timer) clearInterval(timer);
  timer = null;
  unread = 0;
  paintDot();
}

document.addEventListener("visibilitychange", tick);
window.addEventListener("focus", tick);

function when(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Kolkata", day: "2-digit", month: "2-digit", year: "numeric", hour: "numeric", minute: "2-digit",
  }).format(d);
}

function itemHtml(n) {
  return `<button type="button" class="notice${n.seen ? "" : " unread"}" data-notice="${n.id}" data-link="${esc(n.link || "")}">
    <span class="notice-title">${n.seen ? "" : `<i class="notice-new" aria-hidden="true"></i>`}<b>${esc(n.title)}</b>${n.seen ? "" : `<span class="visually-hidden"> (new)</span>`}</span>
    <span>${esc(n.body)}</span>
    <span class="meta">${esc(when(n.created_at))}</span>
  </button>`;
}

/** The list of notices in a sheet; what was new is marked read as it opens. */
export async function openNotices() {
  const list = await refreshNotices();
  const { body } = openSheet({
    title: "Notices",
    html: list === null
      ? `<p>Your notices could not be read just now. Please try again in a moment.</p>`
      : list.length ? list.map(itemHtml).join("")
        : `<p>No notices yet. When an agyari answers one of your asks, you will see it here.</p>`,
  });
  if (list === null) return;
  const fresh = list.filter((n) => !n.seen).map((n) => n.id);
  if (fresh.length) {
    markNoticesSeen(fresh).then(() => { unread = 0; paintDot(); }).catch(() => { /* it shows as new next time */ });
  }
  body.querySelectorAll("[data-notice]").forEach((b) => {
    b.onclick = () => {
      closeSheet();
      if (b.dataset.link) navigate(b.dataset.link);
    };
  });
}
