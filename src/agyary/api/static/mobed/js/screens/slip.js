"use strict";

/**
 * The printable slip - what actually goes to the thermal printer and then
 * to the fire. Five fields only: fire temple, behdin and contact, the
 * ceremony, when, and the names. No prices anywhere.
 */

import { machiSlip, bookingSlip, deleteMachi, deleteBooking } from "../api.js";
import { chrome, mainEl, showFab, showError, refreshHeader, loading, flashInfo } from "../ui.js";
import { esc } from "../util.js";
import { navigate } from "../router.js";

export async function renderSlip({ kind, aid, id }) {
  chrome(true);
  refreshHeader();
  showFab(false);
  loading();

  const agyaryId = Number(aid);
  const numId = Number(id);
  let slip;
  try {
    slip = kind === "machi" ? await machiSlip(agyaryId, numId) : await bookingSlip(agyaryId, numId);
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
    </div>
    <div class="card no-print">
      <button class="ghost small" id="slipDeleteOpen">Delete</button>
      <div id="slipDeleteConfirm" style="margin-top:12px"></div>
    </div>`;

  document.getElementById("slipBack").onclick = () => navigate("#/calendar");
  document.getElementById("slipPrint").onclick = () => window.print();
  // A machi's edit screen is its own route (Geh/slot picker, not the
  // generic event form) - #/event/machi/:id/edit is not a real page in
  // either app and used to silently bounce back to the calendar.
  document.getElementById("slipEdit").onclick = () => {
    navigate(kind === "machi" ? `#/machi/${id}/edit` : `#/event/${kind}/${id}/edit`);
  };

  const doDelete = async (future) => {
    const panel = document.getElementById("slipDeleteConfirm");
    panel.innerHTML = "";
    try {
      if (kind === "machi") await deleteMachi(agyaryId, numId, future);
      else await deleteBooking(agyaryId, numId);
    } catch (e) {
      return showError("Couldn't delete: " + e.message);
    }
    flashInfo("Deleted.");
    navigate("#/calendar");
  };

  document.getElementById("slipDeleteOpen").onclick = () => {
    const panel = document.getElementById("slipDeleteConfirm");
    // Only a machi can be part of a recurring series - a booking never
    // repeats, so there is nothing to choose between there.
    panel.innerHTML = slip.is_recurring
      ? `<p class="meta">This is part of a recurring arrangement.</p>
         <div class="row tight">
           <button class="danger small" id="delOne">Just this one</button>
           <button class="danger small" id="delFuture">This and every future one</button>
           <button class="ghost small" id="delCancel">Cancel</button>
         </div>`
      : `<p class="meta">Delete this? This can't be undone.</p>
         <div class="row tight">
           <button class="danger small" id="delOne">Delete</button>
           <button class="ghost small" id="delCancel">Cancel</button>
         </div>`;
    document.getElementById("delOne").onclick = () => doDelete(false);
    document.getElementById("delCancel").onclick = () => { panel.innerHTML = ""; };
    const delFuture = document.getElementById("delFuture");
    if (delFuture) delFuture.onclick = () => doDelete(true);
  };
}
