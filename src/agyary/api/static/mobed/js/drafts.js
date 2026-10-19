"use strict";

/**
 * Forms that are filled in over more than one screen keep what was typed
 * until it is saved or the mobed cancels. The draft lives in memory, and in
 * sessionStorage so a reload of the page does not lose it either. Storage can
 * be unavailable (private windows) - then memory alone does the job.
 */

const held = new Map();

export function loadDraft(key) {
  if (held.has(key)) return held.get(key);
  try {
    const raw = sessionStorage.getItem("draft:" + key);
    if (raw) { const v = JSON.parse(raw); held.set(key, v); return v; }
  } catch (e) { /* unavailable: memory only */ }
  return null;
}

export function saveDraft(key, value) {
  held.set(key, value);
  try { sessionStorage.setItem("draft:" + key, JSON.stringify(value)); } catch (e) { /* ignore */ }
}

export function clearDraft(key) {
  held.delete(key);
  try { sessionStorage.removeItem("draft:" + key); } catch (e) { /* ignore */ }
}
