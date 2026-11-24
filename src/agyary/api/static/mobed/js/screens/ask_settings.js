"use strict";

/**
 * Asks from people, a card in Settings for the panthaky (R4.2; docs/behdin-r4-2-design.md).
 *
 *  - "Take asks from people": one switch, off until the panthaky turns it on. While it is off, people
 *    cannot ask this fire temple for a service in the app. Saved the moment it is changed.
 *  - "Services and prices": each service of the fire temple with its usual price in rupees (blank means
 *    no usual price: the person is told to ask the fire temple) and whether it is offered. Saved per row,
 *    as soon as the price is left or the box is ticked. Only the confirmed panthaky (and the admin) reach
 *    this; the server checks.
 */

import { getAsksSetting, putAsksSetting, getServicePrices, putServiceAsk } from "../api.js";
import { showError, showInfo } from "../ui.js";
import { esc } from "../util.js";
import { flagProblems, clearProblems } from "../fielderrors.js";

function priceText(p) {
  return p == null ? "" : String(Number(p));
}

function rowHtml(s) {
  return `<div class="svc-price-row" data-svc="${s.id}" style="padding:10px 0;border-top:1px solid var(--border)">
    <div style="font-weight:600;overflow-wrap:anywhere">${esc(s.name)}</div>
    <div class="check-row" style="padding:2px 0">
      <input type="checkbox" id="spOn${s.id}" data-on ${s.is_active ? "checked" : ""}>
      <label for="spOn${s.id}">Offered to people</label>
    </div>
    <label for="spPrice${s.id}" style="margin-top:4px">Usual price, Rs <span class="meta">(blank: no usual price)</span></label>
    <input type="text" inputmode="decimal" id="spPrice${s.id}" data-price value="${esc(priceText(s.default_price))}"
      autocomplete="off" placeholder="No usual price">
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
    box.innerHTML = `<h2>Asks from people</h2><p class="meta">Couldn't load this: ${esc(e.message)}</p>`;
    return;
  }
  if (!alive()) return;
  box.innerHTML = `
    <h2>Asks from people</h2>
    <div class="check-row">
      <input type="checkbox" id="askTake" ${setting.takes_asks ? "checked" : ""}>
      <label for="askTake"><b>Take asks from people</b></label>
    </div>
    <p class="meta" style="margin:0 0 10px">When this is on, people can ask ${esc(agyary.name)} for a prayer in their own
      app. You see each ask on the Requests tab and say yes or no. Their name and number reach you only when you
      accept. Off until you turn it on.</p>
    <h3 style="margin:14px 0 4px">Services and prices</h3>
    <p class="meta" style="margin:0 0 6px">The price is only what people are shown, as "usual price, confirm with the
      fire temple". Nothing is charged in the app. Turn a service off to stop people asking for it.</p>
    <div id="askSvcs">${prices.services.length ? prices.services.map(rowHtml).join("")
      : `<p class="meta">No services yet.</p>`}</div>`;

  const take = box.querySelector("#askTake");
  take.onchange = async () => {
    const want = take.checked;
    take.disabled = true;
    try {
      await putAsksSetting(agyary.id, want);
      if (alive()) showInfo(want ? "Saved. People can now ask you." : "Saved. People can no longer ask you.");
    } catch (e) {
      take.checked = !want;
      if (alive()) showError("Not saved: " + e.message);
    }
    take.disabled = false;
  };

  box.querySelectorAll(".svc-price-row").forEach(row => {
    const id = Number(row.dataset.svc);
    const on = row.querySelector("[data-on]");
    const price = row.querySelector("[data-price]");
    let kept = price.value.trim();      // what the server has, to save only a real change
    const save = async (body, undo) => {
      clearProblems(row);
      try {
        const saved = await putServiceAsk(agyary.id, id, body);
        if (!alive()) return;
        if ("default_price" in body) { price.value = priceText(saved.default_price); kept = price.value; }
        showInfo("Saved.");
      } catch (e) {
        undo();
        if (!alive()) return;
        if (e.field === "default_price" || e.status === 400) flagProblems(row, [{ target: price, message: e.message }]);
        else showError("Not saved: " + e.message);
      }
    };
    on.onchange = () => {
      const want = on.checked;
      save({ is_active: want }, () => { on.checked = !want; });
    };
    price.onchange = () => {
      const v = price.value.trim().replace(/^rs\.?\s*/i, "").replace(/,/g, "");
      if (v === kept) return;
      save({ default_price: v === "" ? null : v }, () => { /* the field keeps what was typed, flagged */ });
    };
  });
}
