"use strict";

/**
 * Settings -> Requests (R4.2 redesign, 27 Nov 2026): the panthaky's page for requests from people.
 *
 *  - "Take requests" is the one switch. While it is off nothing else is shown.
 *  - "What people can ask you for" is empty until the panthaky lists something: pick from the suggestions
 *    (one tap each) or write their own. A price is optional, and can be set or cleared at any time.
 *  - Listing is only for people: the mobed's own diary list is not touched (the server keeps them apart).
 * Only the confirmed panthaky (and the admin) reach this; the server checks.
 */

import { getAsksSetting, putAsksSetting, getServicePrices, putServiceAsk, addRequestService } from "../api.js";
import { chrome, mainEl, showFab, showError, showInfo, refreshHeader, loading, backBar, screenFailed } from "../ui.js";
import { esc } from "../util.js";
import { navGuard } from "../router.js";
import { currentAgyary } from "../state.js";
import { flagProblems, clearProblems } from "../fielderrors.js";

/** Prayers a fire temple is commonly asked for. Tapped to list; anything else is written in. */
export const SUGGESTED = [
  "Jashan", "Tandarosti", "Satum", "Afringan", "Farokshi", "Baaj", "Sarosh Baj", "Machi",
  "Navjote", "Lagan", "Vendidad", "Yazeshni", "Patet",
];

const same = (a, b) => a.trim().toLowerCase() === b.trim().toLowerCase();
const priceText = (p) => (p == null ? "" : String(Number(p)));

/** What to suggest: the common prayers and the fire temple's own catalog, minus what is already listed. */
export function suggestionsFor(services) {
  const listed = services.filter((s) => s.offered).map((s) => s.name);
  const out = [];
  for (const name of [...SUGGESTED, ...services.map((s) => s.name)]) {
    if (listed.some((l) => same(l, name)) || out.some((o) => same(o, name))) continue;
    out.push(name);
  }
  return out;
}

function listedRow(s) {
  return `<div class="svc-price-row" data-svc="${s.id}" style="padding:10px 0;border-top:1px solid var(--border)">
    <div style="font-weight:600;overflow-wrap:anywhere">${esc(s.name)}</div>
    <label for="rsPrice${s.id}" style="margin-top:4px">Price (₹, optional)</label>
    <input type="text" inputmode="decimal" id="rsPrice${s.id}" data-price value="${esc(priceText(s.default_price))}"
      autocomplete="off">
    <button class="ghost small" data-remove style="margin-top:8px">Remove from my list</button>
  </div>`;
}

export async function renderRequestSetup() {
  chrome(true);
  refreshHeader();
  showFab(false);
  loading();
  const alive = navGuard();
  const agyary = currentAgyary();
  if (!agyary) return screenFailed("You are not at a fire temple yet.");

  let setting, prices;
  try {
    [setting, prices] = await Promise.all([getAsksSetting(agyary.id), getServicePrices(agyary.id)]);
  } catch (e) {
    if (!alive()) return;
    if (e.status === 404 || e.status === 403) return screenFailed("Only the panthaky of this fire temple can use this page.");
    return screenFailed(e.message, () => renderRequestSetup());
  }
  if (!alive()) return;

  const services = prices.services;
  const listed = services.filter((s) => s.offered);
  const suggestions = suggestionsFor(services);

  mainEl.innerHTML = `
    <div class="card">
      ${backBar("Requests")}
      <p class="meta" style="margin:4px 0 0">Let people ask you for prayers.</p>
      <div class="check-row">
        <input type="checkbox" id="rsTake" ${setting.takes_asks ? "checked" : ""}>
        <label for="rsTake"><b>Take requests</b></label>
      </div>
      <p class="meta" id="rsTakeMsg" style="margin:0"></p>
    </div>
    ${setting.takes_asks ? `
    <div class="card" id="rsListed">
      <h2>What people can ask you for</h2>
      ${listed.length ? listed.map(listedRow).join("")
        : `<p class="meta">Nothing yet. Pick from the suggestions below, or write your own. People can send a
            request only for what is listed here.</p>`}
    </div>
    <div class="card">
      <h2>Suggestions</h2>
      <p class="meta" style="margin:0 0 8px">Tap one to list it.</p>
      <div class="chip-row" id="rsSuggest">${suggestions.map((n) =>
        `<button class="chip" data-suggest="${esc(n)}">+ ${esc(n)}</button>`).join("")}</div>
      <label for="rsNew" style="margin-top:16px">Write your own</label>
      <input type="text" id="rsNew" maxlength="40" autocomplete="off" placeholder="Name of the prayer">
      <button class="small" id="rsNewAdd" style="margin-top:8px">Add to my list</button>
      <p class="meta" id="rsNewMsg" style="margin:4px 0 0"></p>
    </div>` : `<p class="meta" style="padding:0 var(--space-3)">Turn this on to choose what people can ask you for.</p>`}`;

  /** Draw again from the server, in the same place on the page. */
  const redraw = async () => {
    const y = window.scrollY;
    await renderRequestSetup();
    if (alive()) window.scrollTo(0, y);
  };

  const take = document.getElementById("rsTake");
  const takeMsg = document.getElementById("rsTakeMsg");
  take.onchange = async () => {
    const want = take.checked;
    take.disabled = true;
    try {
      await putAsksSetting(agyary.id, want);
    } catch (e) {
      take.checked = !want;
      take.disabled = false;
      takeMsg.textContent = e.message;
      return;
    }
    if (alive()) redraw();
  };
  if (!setting.takes_asks) return;

  const add = async (name, msgEl, btn) => {
    if (btn) btn.disabled = true;
    try {
      await addRequestService(agyary.id, name);
    } catch (e) {
      if (btn) btn.disabled = false;
      if (msgEl) msgEl.textContent = e.message; else showError(e.message);
      return;
    }
    if (!alive()) return;
    await redraw();
    if (alive()) showInfo(`${name} is on your list.`);
  };

  mainEl.querySelectorAll("[data-suggest]").forEach((b) => {
    b.onclick = () => add(b.dataset.suggest, null, b);
  });
  const newName = document.getElementById("rsNew");
  const newMsg = document.getElementById("rsNewMsg");
  const newBtn = document.getElementById("rsNewAdd");
  newBtn.onclick = () => {
    const name = newName.value.trim();
    if (!name) { newMsg.textContent = "Please enter the prayer's name."; return; }
    newMsg.textContent = "";
    add(name, newMsg, newBtn);
  };
  newName.onkeydown = (ev) => { if (ev.key === "Enter") { ev.preventDefault(); newBtn.click(); } };

  mainEl.querySelectorAll(".svc-price-row").forEach((row) => {
    const id = Number(row.dataset.svc);
    const price = row.querySelector("[data-price]");
    const remove = row.querySelector("[data-remove]");
    const name = services.find((s) => s.id === id).name;
    let kept = price.value.trim();
    price.onchange = async () => {
      const v = price.value.trim().replace(/^(rs\.?|₹)\s*/i, "").replace(/,/g, "");
      if (v === kept) return;
      clearProblems(row);
      try {
        const saved = await putServiceAsk(agyary.id, id, { default_price: v === "" ? null : v });
        price.value = priceText(saved.default_price);
        kept = price.value;
      } catch (e) {
        price.value = kept;
        if (e.status === 400) flagProblems(row, [{ target: price, message: e.message }]);
        else showError("Not saved: " + e.message);
      }
    };
    remove.onclick = async () => {
      remove.disabled = true;
      try {
        await putServiceAsk(agyary.id, id, { offered: false });
      } catch (e) {
        remove.disabled = false;
        return showError("Not removed: " + e.message);
      }
      if (!alive()) return;
      await redraw();
      if (alive()) showInfo(`${name} is off your list.`);
    };
  });
}
