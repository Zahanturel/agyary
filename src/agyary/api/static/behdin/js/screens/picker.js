"use strict";

/**
 * A list of agyaries to pick one from, with "Near me" and a search. Used by "Ask for a prayer" (which
 * agyari to ask) and by "Ask another agyari". Only agyaries that take asks can be picked: the ones that
 * plainly cannot are greyed with a plain line, and the rest are checked the moment one is tapped.
 * The phone's position is used once to sort, sent in the body of one request and kept nowhere.
 */

import { agyariesNearby, getAsking } from "../api.js";
import { loadFailedHtml, wireRetry, showError } from "/mobed-app/js/ui.js";
import { esc, KIND_LABELS } from "../util.js";

const kindLabel = (k) => KIND_LABELS[k] || "";

export const NOT_TAKING = "Not taking asks in the app yet";

function cardHtml(a, currentId, pickLabel) {
  const grey = !a.answers_in_app;
  return `<div class="card agy-card${grey ? " agy-grey" : ""}" data-card="${a.id}">
    <h2>${esc(a.name)}</h2>
    <p class="meta" style="margin:0">${esc([a.city, kindLabel(a.kind)].filter(Boolean).join(" · "))}</p>
    ${a.distance_km != null ? `<p class="meta" style="margin:2px 0 0">${a.distance_km} km away</p>` : ""}
    ${grey ? `<p class="meta" style="margin:var(--space-2) 0 0">${NOT_TAKING}.</p>` : `
    <div style="margin-top:var(--space-3)">
      <button type="button" class="small" data-pick="${a.id}">${a.id === currentId ? "Keep this one" : esc(pickLabel)}</button>
      <p class="meta pick-note" style="margin:var(--space-2) 0 0" hidden></p>
    </div>`}
  </div>`;
}

/**
 * Draw the picker into `host`. `onPick(agyari, asking)` runs with an agyari that takes asks, and the
 * plain facts about what it offers. `alive()` says whether the screen is still the one on show.
 */
export function mountPicker(host, { onPick, alive, currentId = null, pickLabel = "Ask this fire temple" }) {
  host.innerHTML = `
    <div class="card">
      <h2>Find a fire temple</h2>
      <button type="button" class="secondary" id="pkNear" style="width:100%">Near me</button>
      <label for="pkSearch">Name or town</label>
      <input type="search" id="pkSearch" autocomplete="off" maxlength="100">
    </div>
    <div id="pkList"><div class="empty-state">Loading...</div></div>`;

  let here = null;
  let asked = 0;
  const list = host.querySelector("#pkList");

  const load = async () => {
    const mine = ++asked;
    const q = host.querySelector("#pkSearch").value.trim();
    let found;
    try {
      found = (await agyariesNearby(q, here)).agyaries;
    } catch (e) {
      if (mine !== asked || !alive()) return;
      list.innerHTML = loadFailedHtml("the list of fire temples");
      wireRetry(list, load);
      return;
    }
    if (mine !== asked || !alive()) return;
    if (!found.length) {
      list.innerHTML = `<div class="empty-state">${q ? "No fire temple found." : ""}</div>`;
      return;
    }
    list.innerHTML = found.map((a) => cardHtml(a, currentId, pickLabel)).join("");
    list.querySelectorAll("[data-pick]").forEach((b) => {
      b.onclick = async () => {
        const a = found.find((x) => x.id === Number(b.dataset.pick));
        const note = b.parentElement.querySelector(".pick-note");
        b.disabled = true;
        let asking;
        try {
          asking = await getAsking(a.id);
        } catch (err) {
          b.disabled = false;
          return showError(err.message);
        }
        if (!alive()) return;
        if (!asking.takes_asks) {
          b.disabled = false;
          b.closest(".agy-card").classList.add("agy-grey");
          note.textContent = `${asking.message || NOT_TAKING}.`;
          note.hidden = false;
          return;
        }
        onPick({ id: a.id, name: a.name, city: a.city }, asking);
      };
    });
  };

  let typing = null;
  host.querySelector("#pkSearch").oninput = () => { clearTimeout(typing); typing = setTimeout(load, 300); };

  host.querySelector("#pkNear").onclick = (e) => {
    const btn = e.currentTarget;
    const note = host.querySelector("#pkNearNote");
    if (!("geolocation" in navigator)) {
      note.textContent = "Could not get your position.";
      return;
    }
    btn.disabled = true;
    note.textContent = "Asking your phone...";
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        here = { lat: pos.coords.latitude, lng: pos.coords.longitude };
        btn.disabled = false;
        note.textContent = "Nearest first.";
        load();
      },
      () => {
        btn.disabled = false;
        note.textContent = "Could not get your position.";
      },
      { enableHighAccuracy: false, timeout: 15000, maximumAge: 300000 },
    );
  };

  load();
}
