"use strict";

/**
 * Fire temples to choose from: a town, and the list of the listed fire temples in it (only those that take
 * requests are ever returned). A distance is shown only when the server sends one.
 */

import { findAgyaries, getTowns } from "../api.js";
import { loadFailedHtml, wireRetry } from "/mobed-app/js/ui.js";
import { esc, KIND_LABELS } from "../util.js";

const kindLabel = (k) => KIND_LABELS[k] || "";

function cardHtml(a, currentId, pickLabel) {
  return `<div class="card">
    <h2>${esc(a.name)}</h2>
    <p class="meta" style="margin:0">${esc([a.city, kindLabel(a.kind)].filter(Boolean).join(" · "))}</p>
    ${a.distance_km != null ? `<p class="meta" style="margin:2px 0 0">${a.distance_km} km</p>` : ""}
    <div style="margin-top:var(--space-3)">${a.id === currentId
      ? `<span class="tag role">Selected</span>`
      : `<button type="button" class="small" data-pick="${a.id}">${esc(pickLabel)}</button>`}</div>
  </div>`;
}

/** Draw the picker into `host`. `onPick(fireTemple)` runs with the one chosen; `alive()` says whether the screen is still on show. */
export async function mountPicker(host, { onPick, alive, currentId = null, town = "", pickLabel = "Choose" }) {
  host.innerHTML = `<div class="card">
      <label for="pkTown">Town</label>
      <select id="pkTown"><option value="">All towns</option></select>
    </div>
    <div id="pkList"><div class="empty-state">Loading...</div></div>`;
  const list = host.querySelector("#pkList");
  const select = host.querySelector("#pkTown");
  let asked = 0;

  const load = async () => {
    const mine = ++asked;
    let found;
    try {
      found = (await findAgyaries(select.value, "")).agyaries;
    } catch (e) {
      if (mine !== asked || !alive()) return;
      list.innerHTML = loadFailedHtml("the fire temples");
      wireRetry(list, load);
      return;
    }
    if (mine !== asked || !alive()) return;
    const shown = select.value ? found.filter((a) => (a.city || "").trim().toLowerCase() === select.value.toLowerCase()) : found;
    list.innerHTML = shown.length ? shown.map((a) => cardHtml(a, currentId, pickLabel)).join("")
      : `<div class="empty-state">No fire temple listed.</div>`;
    list.querySelectorAll("[data-pick]").forEach((b) => {
      b.onclick = () => {
        const a = shown.find((x) => x.id === Number(b.dataset.pick));
        b.disabled = true;
        onPick({ id: a.id, name: a.name, city: a.city, kind: a.kind });
      };
    });
  };

  try {
    const towns = (await getTowns()).towns;
    if (!alive()) return;
    select.insertAdjacentHTML("beforeend", towns.map((t) => `<option value="${esc(t)}">${esc(t)}</option>`).join(""));
    if (town && towns.some((t) => t.toLowerCase() === town.toLowerCase())) select.value = towns.find((t) => t.toLowerCase() === town.toLowerCase());
  } catch (e) { /* the list below still shows every town */ }
  select.onchange = load;
  load();
}
