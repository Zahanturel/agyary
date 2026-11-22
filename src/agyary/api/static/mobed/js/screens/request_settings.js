"use strict";

/**
 * Settings -> Prayer requests (DECISIONS D10, changed 21 Nov 2026; R3.1): how a
 * request from a Doongerwadi or prayer hall reaches the panthaky's fire temple.
 *
 *  - Everyone at once (what every fire temple starts with): every mobed on the
 *    list is asked on WhatsApp as soon as a request comes.
 *  - Come to me first: only the panthaky is told. Under it, the safety net:
 *    if they have done nothing in 15 minutes, 30 minutes or 1 hour, Mobed
 *    Diary asks all their mobeds by itself. Never is the default.
 *
 * The safety net shows only while Come to me first is chosen; what is picked
 * in it is saved either way, so switching back keeps it. Only that fire
 * temple's confirmed panthakys (and the admin) reach this; the server checks.
 */

import { getRequestSettings, putRequestSettings } from "../api.js";
import { currentAgyary } from "../state.js";
import { chrome, mainEl, showFab, showError, showInfo, refreshHeader, loading, screenFailed } from "../ui.js";
import { esc } from "../util.js";
import { navGuard } from "../router.js";
import { flagProblems, clearProblems } from "../fielderrors.js";

const PANTHAKY_FIRST = "panthaky_first";
const MODES = [
  ["everyone", "Everyone at once",
    "As soon as a request comes, every mobed on your list is asked, in the app and on WhatsApp. The first "
    + "to say yes fill the places. You only step in if it is short."],
  [PANTHAKY_FIRST, "Come to me first",
    "Only you are told. Then you choose: ask everyone on WhatsApp, call a mobed, or pray yourself."],
];
// The safety net's choices; "" is Never.
const WAITS = [["", "Never"], ["15", "15 minutes"], ["30", "30 minutes"], ["60", "1 hour"]];

export async function renderRequestSettings() {
  chrome(true);
  refreshHeader();
  showFab(false);
  loading();
  const alive = navGuard();
  const agyary = currentAgyary();
  if (!agyary) return screenFailed("You are not at a fire temple yet.");
  let got;
  try {
    got = await getRequestSettings(agyary.id);
  } catch (e) {
    if (!alive()) return;
    if (e.status === 404) return screenFailed("Only the panthaky of the fire temple can choose how prayer requests reach it.");
    return screenFailed("Couldn't load how prayer requests reach you: " + e.message, renderRequestSettings);
  }
  if (!alive()) return;
  draw(agyary, got, alive);
}

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

function draw(agyary, got, alive) {
  const minutes = got.escalate_minutes == null ? "" : String(got.escalate_minutes);
  mainEl.innerHTML = `
    <h2 style="margin:0 0 4px">Prayer requests</h2>
    <p class="meta" style="margin:0 0 12px">How a request from a Doongerwadi or prayer hall reaches ${esc(agyary.name)}.</p>
    <div class="card">
      <div class="choice-group" id="prMode">${MODES.map(m => modeHtml(m, got.mode)).join("")}</div>
      <div id="prWaitBox" style="${got.mode === PANTHAKY_FIRST ? "" : "display:none"}">
        <label>If I haven't done anything in</label>
        <div class="choice-group" id="prWait">${WAITS.map(w => waitHtml(w, minutes)).join("")}</div>
        <p class="meta" style="margin:6px 0 0">Mobed Diary then asks all your mobeds on WhatsApp by itself.</p>
      </div>
      <div class="action-bar"><button type="button" id="prSave">Save</button></div>
    </div>`;

  const card = mainEl.querySelector(".card");
  const box = document.getElementById("prWaitBox");
  const chosen = (name) => (mainEl.querySelector(`input[name="${name}"]:checked`) || {}).value;
  mainEl.querySelectorAll('input[name="prMode"]').forEach(r => {
    r.onchange = () => {
      clearProblems(card);
      box.style.display = chosen("prMode") === PANTHAKY_FIRST ? "" : "none";
    };
  });

  document.getElementById("prSave").onclick = async (ev) => {
    const btn = ev.currentTarget;
    if (btn.disabled) return;
    const mode = chosen("prMode");
    if (!mode) return flagProblems(card, [{ target: "#prMode", message: "Please choose how requests reach you." }]);
    const wait = chosen("prWait") || "";
    clearProblems(card);
    btn.disabled = true;   // one save per tap
    try {
      await putRequestSettings(agyary.id, mode, wait === "" ? null : Number(wait));
    } catch (e) {
      btn.disabled = false;
      if (!alive()) return;
      const target = { mode: "#prMode", escalate_minutes: "#prWait" }[e.field];
      if (target) return flagProblems(card, [{ target, message: e.message }]);
      return showError("Not saved: " + e.message);
    }
    btn.disabled = false;
    if (alive()) showInfo("Saved.");
  };
}
