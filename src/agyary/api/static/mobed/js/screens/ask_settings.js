"use strict";

/**
 * Requests from people, a card in Settings for the panthaky (R4.2 redesign, 25 Nov 2026).
 *
 *  - "Services and prices" comes first: every service in the diary's catalog with its price in rupees
 *    and whether it is offered. Saved per row, as soon as the price is left or the box is ticked.
 *  - "Take requests" comes after it and stays off-limits ("Enter a price for every service.") until every
 *    offered service has a price. Saved at once; the server's reason is shown on the control.
 * Only the confirmed panthaky (and the admin) reach this; the server checks.
 */

import { getAsksSetting, putAsksSetting, getServicePrices, putServiceAsk, createService } from "../api.js";
import { showError } from "../ui.js";
import { esc } from "../util.js";
import { flagProblems, clearProblems } from "../fielderrors.js";

const NEEDS_PRICES = "Enter a price for every service.";

function priceText(p) {
  return p == null ? "" : String(Number(p));
}

function rowHtml(s) {
  return `<div class="svc-price-row" data-svc="${s.id}" style="padding:10px 0;border-top:1px solid var(--border)">
    <div style="font-weight:600;overflow-wrap:anywhere">${esc(s.name)}</div>
    <label for="spPrice${s.id}" style="margin-top:4px">Price (₹)</label>
    <input type="text" inputmode="decimal" id="spPrice${s.id}" data-price value="${esc(priceText(s.default_price))}"
      autocomplete="off">
    <div class="check-row" style="padding:2px 0">
      <input type="checkbox" id="spOn${s.id}" data-on ${s.is_active ? "checked" : ""}>
      <label for="spOn${s.id}">Offered</label>
    </div>
  </div>`;
}

/** Fill `box` (a card in Settings) for this fire temple's panthaky. `alive()` is false once Settings is left. */
export async function paintAskSettings(box, agyary, alive) {
  let setting, prices;
  try {
    [setting, prices] = await Promise.all([getAsksSetting(agyary.id), getServicePrices(agyary.id)]);
  } catch (e) {
    if (!alive()) return;
    // Not the panthaky of a fire temple the server knows: nothing to show.
    if (e.status === 404 || e.status === 403) { box.remove(); return; }
    box.innerHTML = `<h2>Requests from people</h2><p class="meta">Couldn't load this: ${esc(e.message)}</p>`;
    return;
  }
  if (!alive()) return;
  box.innerHTML = `
    <h2>Requests from people</h2>
    <div class="check-row">
      <input type="checkbox" id="askTake">
      <label for="askTake"><b>Take requests</b></label>
    </div>
    <p class="meta" id="askTakeMsg" style="margin:0"></p>
    <h3 style="margin:12px 0 0">Services and prices</h3>
    <div id="askSvcs">${prices.services.length ? prices.services.map(rowHtml).join("")
      : `<p class="meta">No services yet.</p>`}</div>
    <div style="border-top:1px solid var(--border);padding-top:10px">
      <label for="askNewSvc">Add your own service</label>
      <div class="row tight">
        <input type="text" id="askNewSvc" maxlength="60" autocomplete="off" placeholder="Name of the service">
        <button class="small" id="askNewSvcAdd">Add</button>
      </div>
      <p class="meta" id="askNewSvcMsg" style="margin:4px 0 0"></p>
    </div>`;

  const newName = box.querySelector("#askNewSvc");
  const newBtn = box.querySelector("#askNewSvcAdd");
  const newMsg = box.querySelector("#askNewSvcMsg");
  newBtn.onclick = async () => {
    const name = newName.value.trim();
    if (!name) { newMsg.textContent = "Please enter the service's name."; return; }
    newBtn.disabled = true;
    newMsg.textContent = "";
    try {
      const made = await createService(agyary.id, name, false);
      // While requests are on, a service with no price cannot be offered: it starts off.
      if (setting.takes_asks) await putServiceAsk(agyary.id, made.id, { is_active: false });
    } catch (e) {
      if (alive()) { newMsg.textContent = e.message; newBtn.disabled = false; }
      return;
    }
    if (alive()) paintAskSettings(box, agyary, alive);
  };

  const take = box.querySelector("#askTake");
  const takeMsg = box.querySelector("#askTakeMsg");
  const paintSwitch = (st) => {
    take.checked = !!st.takes_asks;
    // Off is always allowed; on only when every offered service has a price.
    take.disabled = !st.takes_asks && !st.ready;
    takeMsg.textContent = take.disabled ? NEEDS_PRICES : "";
  };
  paintSwitch(setting);
  /** The switch follows the prices: read it again after a row is saved. */
  const reread = async () => {
    try {
      const st = await getAsksSetting(agyary.id);
      if (alive()) paintSwitch(st);
    } catch (e) { /* the switch keeps what it shows; the server checks it anyway */ }
  };

  take.onchange = async () => {
    const want = take.checked;
    take.disabled = true;
    takeMsg.textContent = "";
    try {
      paintSwitch(await putAsksSetting(agyary.id, want));
    } catch (e) {
      take.checked = !want;
      if (alive()) { takeMsg.textContent = e.message; take.disabled = false; }
    }
  };

  box.querySelectorAll(".svc-price-row").forEach(row => {
    const id = Number(row.dataset.svc);
    const on = row.querySelector("[data-on]");
    const price = row.querySelector("[data-price]");
    let kept = price.value.trim();      // what the server has, to save only a real change
    const save = async (body, target, undo) => {
      clearProblems(row);
      try {
        const saved = await putServiceAsk(agyary.id, id, body);
        if (!alive()) return;
        if ("default_price" in body) { price.value = priceText(saved.default_price); kept = price.value; }
        reread();
      } catch (e) {
        undo();
        if (!alive()) return;
        if (e.status === 400 || e.status === 409) flagProblems(row, [{ target, message: e.message }]);
        else showError("Not saved: " + e.message);
      }
    };
    on.onchange = () => {
      const want = on.checked;
      save({ is_active: want }, on.closest(".check-row"), () => { on.checked = !want; });
    };
    price.onchange = () => {
      const v = price.value.trim().replace(/^(rs\.?|₹)\s*/i, "").replace(/,/g, "");
      if (v === kept) return;
      // A refused price that is a valid number (clearing one while requests are on) goes back to what is saved.
      save({ default_price: v === "" ? null : v }, price, () => { if (v === "") price.value = kept; });
    };
  });
}
