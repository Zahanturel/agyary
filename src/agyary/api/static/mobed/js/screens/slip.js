"use strict";

/**
 * The printable slip - what actually goes to the thermal printer and then
 * to the fire. Five fields only: fire temple, behdin and contact, the
 * ceremony, when, and the names. No prices anywhere.
 */

import { machiSlip, bookingSlip } from "../api.js";
import { chrome, mainEl, showFab, showError, markActiveTab, refreshHeader, loading } from "../ui.js";
import { esc } from "../util.js";
import { navigate } from "../router.js";

export async function renderSlip({ kind, aid, id }) {
  chrome(true);
  refreshHeader();
  markActiveTab("#/calendar");
  showFab(false);
  loading();

  const agyaryId = Number(aid);
  let slip;
  try {
    slip = kind === "machi" ? await machiSlip(agyaryId, Number(id)) : await bookingSlip(agyaryId, Number(id));
  } catch (e) {
    mainEl.innerHTML = "";
    return showError("Couldn't load the slip: " + e.message);
  }

  mainEl.innerHTML = `
    <div class="card no-print row tight" style="justify-content:space-between">
      <button class="ghost small" id="slipBack">&lsaquo; Back</button>
      <div class="row tight">
        <button class="secondary small" id="slipEdit">Edit</button>
        <button class="small" id="slipPrint">Print</button>
      </div>
    </div>
    <div class="slip">
      <div class="slip-agyary">${esc(slip.agyary_name)}</div>
      <hr class="slip-rule">
      <div>${esc(slip.event)}</div>
      <div>${esc(slip.when)}</div>
      <div class="slip-behdin">${esc(slip.behdin_name)} (${esc(slip.behdin_phone)})</div>
      <hr class="slip-rule">
      <pre>${esc(slip.names_text)}</pre>
      <hr class="slip-rule">
    </div>`;

  document.getElementById("slipBack").onclick = () => navigate("#/calendar");
  document.getElementById("slipPrint").onclick = () => window.print();
  document.getElementById("slipEdit").onclick = () => navigate(`#/event/${kind}/${id}/edit`);
}
