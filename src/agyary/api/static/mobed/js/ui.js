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
  if (!show) { fabEl.classList.add("hidden"); showBack(null); }
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

export function showFab(show, title = "Add", handler = null) {
  fabEl.classList.toggle("hidden", !show);
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

function banner(cls, msg) {
  // Only one banner at a time - a second failed attempt on the same screen
  // must replace the old message, not stack under it.
  mainEl.querySelectorAll(".error-banner, .info-banner").forEach(el => el.remove());
  const el = document.createElement("div");
  el.className = cls;
  el.textContent = msg;
  mainEl.prepend(el);
  el.scrollIntoView({ block: "nearest" });
}
export function showError(msg) { banner("error-banner", msg); }
export function showInfo(msg) { banner("info-banner", msg); }

// A message that has to outlive a navigation. Showing one the normal way
// just before redirecting doesn't work: the destination screen replaces
// the whole of <main>, taking the banner with it - so a guard that bounces
// you somewhere would do it with no explanation at all.
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
  if (!state.user) return setHeader("Agyary");
  const agyary = currentAgyary();
  const first = shortName(state.user.name);
  setHeader(agyary ? `${first} · ${agyary.name}` : first);
}
