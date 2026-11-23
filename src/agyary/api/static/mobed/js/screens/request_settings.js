"use strict";

/**
 * Prayer requests, a card in Settings (DECISIONS D10, changed 21 Nov 2026; R3.1;
 * the card, not a page of its own, since 24 Nov 2026 at the owner's word): how a
 * request from a Doongerwadi or prayer hall reaches the panthaky's fire temple.
 *
 *  - Everyone at once (what every fire temple starts with): every mobed on the
 *    list is asked as soon as a request comes.
 *  - Come to me first: only the panthaky is told. Under it, the safety net:
 *    if they have done nothing in 15 minutes, 30 minutes or 1 hour, Mobed
 *    Diary asks all their mobeds by itself. Never is the default.
 *
 * A choice is saved the moment it is made (no Save button): the radio that is on
 * is what the system follows. The safety net shows only while Come to me first
 * is chosen; what is picked in it is kept either way. Only that fire temple's
 * confirmed panthakys (and the admin) reach this; the server checks.
 */

import { getRequestSettings, putRequestSettings } from "../api.js";
import { showError, showInfo } from "../ui.js";
import { esc } from "../util.js";
import { flagProblems, clearProblems } from "../fielderrors.js";

const PANTHAKY_FIRST = "panthaky_first";
const MODES = [
  ["everyone", "Everyone at once", "Every mobed on your list is asked as soon as a request comes."],
  [PANTHAKY_FIRST, "Come to me first", "Only you are told, then you choose who to ask."],
];
// The safety net's choices; "" is Never.
const WAITS = [["", "Never"], ["15", "15 minutes"], ["30", "30 minutes"], ["60", "1 hour"]];

function modeHtml([value, title, words], chosen) {
  return `<label class="choice"><input type="radio" name="prMode" value="${value}" ${chosen === value ? "checked" : ""}>
    <span><b>${title}</b><span class="meta" style="display:block;font-weight:400;margin-top:4px">${words}</span></span>
  </label>`;
}

function waitHtml([value, text], chosen) {
  const id = `prWait${value || "Never"}`;
  return `<div class="check-row"><input type="radio" name="prWait" id="${id}" value="${value}" ${chosen === value ? "checked" : ""}>
    <label for="${id}">${text}</label></div>`;
}

/** Fill `box` (a card in Settings) for this fire temple's panthaky. A failure says so in the card
 *  and the rest of Settings still works. `alive()` is false once the person has left Settings. */
export async function paintPrayerRequests(box, agyary, alive) {
  let got;
  try {
    got = await getRequestSettings(agyary.id);
  } catch (e) {
    if (!alive()) return;
    // Not the panthaky of a fire temple the server knows: nothing to show.
    if (e.status === 404) { box.remove(); return; }
    box.innerHTML = `<h2>Prayer requests</h2><p class="meta">Couldn't load this: ${esc(e.message)}</p>`;
    return;
  }
  if (!alive()) return;
  const minutes = got.escalate_minutes == null ? "" : String(got.escalate_minutes);
  box.innerHTML = `
    <h2>Prayer requests</h2>
    <p class="meta" style="margin:0 0 8px">How a request from a Doongerwadi reaches ${esc(agyary.name)}.</p>
    <div class="choice-group" id="prMode">${MODES.map(m => modeHtml(m, got.mode)).join("")}</div>
    <div id="prWaitBox" style="${got.mode === PANTHAKY_FIRST ? "" : "display:none"}">
      <label>If I haven't done anything in</label>
      <div class="choice-group" id="prWait">${WAITS.map(w => waitHtml(w, minutes)).join("")}</div>
      <p class="meta" style="margin:6px 0 0">Then Mobed Diary asks all your mobeds by itself.</p>
    </div>`;

  const waitBox = box.querySelector("#prWaitBox");
  const chosen = (name) => (box.querySelector(`input[name="${name}"]:checked`) || {}).value;
  let saving = false, again = false;
  /** Save what is on now; a change made while one is going is saved right after it. */
  const save = async () => {
    if (saving) { again = true; return; }
    saving = true;
    clearProblems(box);
    waitBox.style.display = chosen("prMode") === PANTHAKY_FIRST ? "" : "none";
    const wait = chosen("prWait") || "";
    try {
      await putRequestSettings(agyary.id, chosen("prMode"), wait === "" ? null : Number(wait));
      if (alive()) showInfo("Saved.");
    } catch (e) {
      if (alive()) {
        const target = { mode: "#prMode", escalate_minutes: "#prWait" }[e.field];
        if (target) flagProblems(box, [{ target, message: e.message }]);
        else showError("Not saved: " + e.message);
      }
    }
    saving = false;
    if (again) { again = false; save(); }
  };
  box.querySelectorAll('input[name="prMode"], input[name="prWait"]').forEach(r => { r.onchange = save; });
}
