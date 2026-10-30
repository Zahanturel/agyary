"use strict";

/**
 * Forms that are filled in over more than one sitting keep what was typed
 * until it is saved, discarded, or the mobed signs out. There is no expiry:
 * instead, opening the form again asks whether to continue from last time or
 * start a new one (see offerDraft), so an old draft is never applied unseen.
 *
 * A draft belongs to the signed-in user and lives in localStorage, so it
 * survives closing the app. Storage can be unavailable (private windows) -
 * then memory alone does the job. Signing out or deleting the account wipes
 * every draft (clearAllDrafts), so a lent phone never shows someone else's
 * half-finished form.
 *
 * Dates are the one thing a draft must not carry blindly. Callers restore
 * the content (behdin, purpose, names) and treat a date that has already
 * passed as no date at all - see restoredDate().
 */

import { state } from "./state.js";
import { mainEl } from "./ui.js";
import { esc, todayIst } from "./util.js";

const PREFIX = "draft:v2:";
const held = new Map();

function slot(key) {
  const who = (state.user && state.user.id) || "anon";
  return `${PREFIX}${who}:${key}`;
}

export function loadDraft(key) {
  const k = slot(key);
  if (held.has(k)) return held.get(k);
  try {
    const raw = localStorage.getItem(k);
    if (raw) { const v = JSON.parse(raw).value; held.set(k, v); return v; }
  } catch (e) { /* unavailable: memory only */ }
  return null;
}

export function saveDraft(key, value) {
  const k = slot(key);
  held.set(k, value);
  try { localStorage.setItem(k, JSON.stringify({ savedAt: Date.now(), value })); } catch (e) { /* ignore */ }
}

export function clearDraft(key) {
  const k = slot(key);
  held.delete(k);
  try { localStorage.removeItem(k); } catch (e) { /* ignore */ }
}

/** Every draft of every user on this phone, including the older
 *  sessionStorage ones. For sign-out and account deletion. */
export function clearAllDrafts() {
  held.clear();
  for (const name of ["localStorage", "sessionStorage"]) {
    try {
      const store = globalThis[name];
      for (const k of Object.keys(store)) if (k.startsWith("draft:")) store.removeItem(k);
    } catch (e) { /* blocked, or nothing to clear */ }
  }
}

/** A saved date is only worth restoring if it has not passed. Anything else
 *  gets `fallback` (the day on screen), and the second value says it was
 *  replaced, so the form can tell the mobed. */
export function restoredDate(saved, fallback) {
  if (saved && saved >= todayIst()) return [saved, false];
  return [fallback || todayIst(), !!saved];
}

/**
 * Ask what to do with a saved draft, in place of the form.
 * `summary` is a few plain lines (already text, not HTML) describing it, with
 * its date, so the choice is made on what is actually there.
 */
export function offerDraft({ title, summary, onContinue, onStartNew }) {
  mainEl.innerHTML = `
    <div class="card">
      <h2>${esc(title)}</h2>
      <p class="meta">You started this and did not finish it.</p>
      <div class="chosen" style="margin:12px 0">
        <div class="who">${summary.map((line, i) => (i ? `<span>${esc(line)}</span>` : `<b>${esc(line)}</b>`)).join("")}</div>
      </div>
      <div class="wizard-nav">
        <button class="ghost" id="dfNew">Start a new one</button>
        <button id="dfContinue">Continue from last time</button>
      </div>
    </div>`;
  document.getElementById("dfContinue").onclick = onContinue;
  document.getElementById("dfNew").onclick = onStartNew;
}
