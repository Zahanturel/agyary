"use strict";

import { state, currentAgyary } from "./state.js";

export const mainEl = document.getElementById("main");
export const fabEl = document.getElementById("fab");
export const headerTitle = document.getElementById("headerTitle");
export const menuBtn = document.getElementById("menuBtn");
export const backEl = document.getElementById("backBtn");

export function setMain(html) { mainEl.innerHTML = html; }
export function loading() { mainEl.innerHTML = `<div class="empty-state">Loading...</div>`; }

/** Show the app chrome (menu icon, add button) or hide it for the
 *  full-screen login and onboarding flows. */
export function chrome(show) {
  menuBtn.classList.toggle("hidden", !show);
  const bellBtn = document.getElementById("bellBtn");
  if (bellBtn) bellBtn.classList.toggle("hidden", !show);
  if (!show) { fabEl.classList.add("hidden"); showBack(null); showTabs(null); }
}

/** The bottom tab bar. `active` is the tab to highlight, or null to hide the bar.
 *  The router calls this on every screen from the route's `tab` option, so a
 *  screen never has to remember to turn it off. */
const tabsEl = document.getElementById("tabs");
export function showTabs(active) {
  if (!tabsEl) return;
  tabsEl.classList.toggle("hidden", !active);
  document.body.classList.toggle("has-tabs", !!active);
  // Machi is a view inside the Calendar tab (cal_switch.js), so its screens light that tab.
  const lit = active === "machi" ? "calendar" : active;
  tabsEl.querySelectorAll("[data-tab]").forEach(b => {
    const on = b.dataset.tab === lit;
    b.classList.toggle("active", on);
    b.setAttribute("aria-current", on ? "page" : "false");
  });
}
// The tab bar's own height (it grows with the text size and the phone's bottom edge) is kept in
// --tabs-h, so the Events | Machi bar can sit exactly on top of it (cal_switch.js).
if (tabsEl && typeof ResizeObserver !== "undefined") {
  new ResizeObserver(() => {
    if (tabsEl.offsetHeight) document.documentElement.style.setProperty("--tabs-h", tabsEl.offsetHeight + "px");
  }).observe(tabsEl);
}
export function onTab(handler) {
  if (tabsEl) tabsEl.querySelectorAll("[data-tab]").forEach(b => { b.onclick = () => handler(b.dataset.tab); });
}

/**
 * Show/hide the floating add button, and say what it adds HERE.
 *
 * The handler is reassigned on every call, never left over from the last
 * screen - the Behdins screen points it at "add a behdin" and the calendar
 * at "add an event", and a stale handler would silently do the wrong
 * thing. Callers that pass no handler get the default set in main.js.
 */
let defaultFabAction = () => {};
export function setDefaultFabAction(fn) { defaultFabAction = fn; }

const TEXT_KEY = "mobed.textsize";

/** The name of whichever app this page is: the other app (Parsi) shares this file and says its own name in an
 *  application-name line; Mobed Diary has none, so it is "Mobed Diary". */
function appName() {
  const tag = document.querySelector('meta[name="application-name"]');
  return (tag && tag.content) || "Mobed Diary";
}
/** "regular", "large" (the default) or "xl". Kept on this device only, like a draft. */
export function getTextSize() {
  try {
    const v = localStorage.getItem(TEXT_KEY);
    return v === "xl" || v === "regular" ? v : "large";
  } catch (e) { return "large"; }
}
export function setTextSize(v) {
  try { localStorage.setItem(TEXT_KEY, v); } catch (e) { /* only this visit then */ }
  applyTextSize();
}
export function applyTextSize() {
  const size = getTextSize();
  if (size !== "large") document.documentElement.dataset.text = size;
  else delete document.documentElement.dataset.text;
}
applyTextSize();

export function showFab(show, title = "Add", handler = null) {
  fabEl.classList.toggle("hidden", !show);
  document.body.classList.toggle("has-fab", show);
  fabEl.title = title;
  fabEl.onclick = handler || defaultFabAction;
}

export function setHeader(text) { headerTitle.textContent = text; }

/** The header Back control. The router owns it: it is shown on every screen
 *  that has somewhere to go back to - including a screen that failed to load,
 *  which is exactly where a mobed with no browser Back button used to be
 *  stranded. Pass null to hide it. */
export function showBack(handler) {
  if (!backEl) return;
  backEl.classList.toggle("hidden", !handler);
  backEl.onclick = handler;
}

// --- Messages -----------------------------------------------------------------
// A message is shown where the mobed is looking, not where the page begins: it
// floats over the bottom of the screen whatever the scroll position. It used to
// be a strip at the top of <main>, which someone at the foot of a long page
// never saw. What is wrong with ONE field is still said on that field
// (fielderrors.js); this is for everything else.
let toastTimer = null;

function toastHost() {
  let host = document.getElementById("toasts");
  if (host) return host;
  host = document.createElement("div");
  host.id = "toasts";
  host.className = "toasts no-print";
  document.body.appendChild(host);
  // An open keyboard covers the bottom of the page without shrinking it, so the
  // message is lifted above whatever part of the page is hidden.
  const vv = window.visualViewport;
  if (vv) {
    const place = () => {
      const hidden = Math.max(0, window.innerHeight - vv.height - vv.offsetTop);
      host.style.setProperty("--kb", `${Math.round(hidden)}px`);
    };
    vv.addEventListener("resize", place);
    vv.addEventListener("scroll", place);
    place();
  }
  return host;
}

/** Take the message off the screen (the router does on every new screen). */
export function clearToasts() {
  clearTimeout(toastTimer);
  const host = document.getElementById("toasts");
  if (host) host.replaceChildren();
}

function banner(cls, msg) {
  const error = cls === "error-banner";
  const el = document.createElement("div");
  el.className = `toast ${error ? "error" : "info"}`;
  el.setAttribute("role", error ? "alert" : "status");
  const text = document.createElement("span");
  text.className = "toast-text";
  text.textContent = msg;
  const x = document.createElement("button");
  x.type = "button";
  x.className = "toast-x";
  x.setAttribute("aria-label", "Dismiss");
  x.textContent = "×";
  el.append(text, x);
  el.onclick = clearToasts;
  // Only one at a time - a second failed attempt replaces the old message
  // rather than stacking on it.
  clearToasts();
  toastHost().replaceChildren(el);
  // Long enough to read at an unhurried pace; an error stays longer.
  const ms = Math.max(error ? 9000 : 4500, String(msg).length * 90);
  toastTimer = setTimeout(clearToasts, ms);
}

/** A screen that could not be loaded at all: say so in the page itself, with a
 *  way to try again, instead of a blank page under a passing message. Going
 *  back is the header's job. */
export function screenFailed(msg, retry = null) {
  mainEl.innerHTML = `<div class="load-failed" role="alert">
    <p><b data-msg></b></p>
    ${retry ? `<button class="small" type="button" data-retry>Try again</button>` : ""}
  </div>`;
  mainEl.querySelector("[data-msg]").textContent = msg;
  if (retry) mainEl.querySelector("[data-retry]").onclick = retry;
  window.scrollTo(0, 0);
}

/** The top of the page: for a new step of a form, which is a new page to the
 *  person filling it in even though the address has not changed. */
export function toTop() { window.scrollTo(0, 0); }

// --- Sheet ----------------------------------------------------------------------
// One dialog at a time, over the page: up from the bottom on a phone, in the
// middle on a wide screen. For a choice that belongs to the moment (where to go
// in the calendar, what to do with a memorial just made) rather than to a page.
let sheet = null;

export function closeSheet() {
  if (!sheet) return;
  const s = sheet;
  sheet = null;
  s.el.remove();
  document.removeEventListener("keydown", s.onKey);
  document.body.classList.remove("sheet-open");
  if (s.opener && s.opener.isConnected) s.opener.focus({ preventScroll: true });
  if (s.onClose) s.onClose();
}

/**
 * Open a sheet. Returns { body, close } - `body` is the element to wire.
 * opts.dismissable (default true): the cross, a tap outside and Escape close
 * it. Pass false for a question that has to be answered with its own buttons.
 * opts.onClose runs however it closes, including a navigation.
 */
export function openSheet({ title, html, dismissable = true, onClose = null }) {
  closeSheet();
  const el = document.createElement("div");
  el.className = "sheet-backdrop no-print";
  el.innerHTML = `<div class="sheet" role="dialog" aria-modal="true" aria-labelledby="sheetTitle">
    <div class="sheet-head"><h2 id="sheetTitle"></h2>
      ${dismissable ? `<button type="button" class="sheet-x" aria-label="Close">×</button>` : ""}</div>
    <div class="sheet-body"></div></div>`;
  el.querySelector("#sheetTitle").textContent = title;
  const body = el.querySelector(".sheet-body");
  body.innerHTML = html;
  const onKey = (e) => { if (e.key === "Escape" && dismissable) closeSheet(); };
  sheet = { el, onKey, onClose, opener: document.activeElement };
  document.body.appendChild(el);
  document.body.classList.add("sheet-open");
  document.addEventListener("keydown", onKey);
  if (dismissable) {
    el.addEventListener("click", (e) => { if (e.target === el) closeSheet(); });
    el.querySelector(".sheet-x").onclick = closeSheet;
  }
  el.querySelector(".sheet").tabIndex = -1;
  el.querySelector(".sheet").focus({ preventScroll: true });
  return { body, close: closeSheet };
}
// Rows that open something are divs with their own click handlers, so neither a
// keyboard nor a screen reader could reach them (UX-04). This gives every such row
// what a real button has: a place in the tab order, the role, Enter and Space.
const TAPPABLE = ".search-result, .section-bar, .event, .geh-slot.booked, .geh-slot.open, "
  + ".note.tap, .obs-head, [data-oid]";
function markTappable() {
  document.querySelectorAll(TAPPABLE).forEach(el => {
    if (el.hasAttribute("tabindex")) return;
    el.tabIndex = 0;
    el.setAttribute("role", "button");
  });
}
new MutationObserver(markTappable).observe(document.body, { childList: true, subtree: true });
document.addEventListener("keydown", (e) => {
  if ((e.key !== "Enter" && e.key !== " ") || !e.target.matches?.('[role="button"]')) return;
  if (e.target.tagName === "BUTTON") return;
  e.preventDefault();
  e.target.click();
});

export function showError(msg) { banner("error-banner", msg); }
export function showInfo(msg) { banner("info-banner", msg); }

/** In place of what would otherwise look like an empty day or a missing person
 *  (UX-01). `whole` says the failure is the whole of `what`; otherwise part of
 *  it did load. Wire the button with wireRetry. */
export function loadFailedHtml(what, { whole = true } = {}) {
  return `<div class="load-failed" role="alert">
    <p><b>${whole ? `Couldn't load ${what}.` : `Part of ${what} couldn't load.`}</b></p>
    <p class="meta">${whole ? "This does not mean it is empty." : "There may be more than you see here."}
      Check your signal and try again.</p>
    <button class="small" type="button" data-retry>Try again</button>
  </div>`;
}

export function wireRetry(root, retry) {
  const btn = root.querySelector("[data-retry]");
  if (btn) btn.onclick = retry;
}

/** A strip above the page while the app cannot reach the server, so what is on
 *  screen is not taken for the latest: nothing else said so (UX-01). */
export function paintOffline() {
  const bar = document.getElementById("offlineBar");
  if (!(state.offline || navigator.onLine === false)) {
    if (bar) bar.remove();
    return;
  }
  if (bar) return;
  const strip = document.createElement("div");
  strip.id = "offlineBar";
  strip.className = "offline-bar no-print";
  strip.setAttribute("role", "status");
  strip.textContent = `Can't reach ${appName()}. What you see may be out of date.`;
  mainEl.parentNode.insertBefore(strip, mainEl);
}

// A message that has to outlive a navigation. Showing one the normal way
// just before redirecting doesn't work: a new screen starts with no message
// on it - so a guard that bounces you somewhere would do it with no
// explanation at all.
let pendingFlash = null;
export function flashError(msg) { pendingFlash = { cls: "error-banner", msg }; }
export function flashInfo(msg) { pendingFlash = { cls: "info-banner", msg }; }
export function drainFlash() {
  if (!pendingFlash) return;
  const { cls, msg } = pendingFlash;
  pendingFlash = null;
  banner(cls, msg);
}

/** A refresh that redraws the SAME logical screen (a save, a toggle, an
 *  accept/decline) shouldn't yank the user to the top of a long list. */
export async function keepScroll(fn) {
  const y = window.scrollY;
  await fn();
  window.scrollTo(0, y);
}

export function wire(sel, fn) {
  const el = mainEl.querySelector(sel);
  if (el) el.onclick = fn;
  return el;
}
export function wireAll(sel, fn) {
  mainEl.querySelectorAll(sel).forEach(el => { el.onclick = () => fn(el); });
}

/** A screen's title row. Going back is the header's job (see showBack), so
 *  there is no second Back button here. */
export function backBar(title, extraHtml = "") {
  return `<div class="row tight" style="justify-content:space-between;align-items:center">
    <h2 style="margin:0">${title}</h2>
    <div class="row tight">${extraHtml}</div>
  </div>`;
}

/** A short way to address someone, given names like "Er. Hormuz
 *  Dadachanji": an honorific on its own ("Er.") is not a name, so keep the
 *  word after it. */
export function shortName(full) {
  const parts = (full || "").trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "";
  if (parts.length > 1 && parts[0].endsWith(".")) return `${parts[0]} ${parts[1]}`;
  return parts[0];
}

/** Header line every signed-in screen shares: who you are and where. */
export function refreshHeader() {
  if (!state.user) return setHeader(appName());
  const agyary = currentAgyary();
  // A Doongerwadi manager has no fire temple; their place is where they are (D10).
  const place = (state.user.funeral_places || [])[0];
  const where = agyary ? agyary.name : place ? place.name : "";
  const first = shortName(state.user.name);
  setHeader(where ? `${first} · ${where}` : first);
}
