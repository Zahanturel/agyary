"use strict";

/**
 * My agyari: the one the person has chosen, and a list to choose another from. "Near me" asks the
 * phone where it is once, uses the answer only to sort and measure, and keeps it nowhere: it goes
 * in the body of one request, never in an address, never stored, never written to a log.
 */

import { agyariesNearby, getMyAgyari, chooseAgyari, forgetAgyari } from "../api.js";
import { chrome, mainEl, setHeader, loading, wireRetry, loadFailedHtml, showError, showInfo } from "/mobed-app/js/ui.js";
import { navGuard } from "/mobed-app/js/router.js";
import { esc, KIND_LABELS } from "../util.js";

const NOT_CHOSEN = "You have not chosen one yet.";

export function kindLabel(kind) { return KIND_LABELS[kind] || ""; }

function cardHtml(a, mineId) {
  const mine = a.id === mineId;
  return `<div class="card agy-card${mine ? " agy-mine" : ""}">
    <h2>${esc(a.name)}</h2>
    <p class="meta" style="margin:0">${esc([a.city, kindLabel(a.kind)].filter(Boolean).join(" · "))}</p>
    ${a.distance_km != null ? `<p class="meta" style="margin:2px 0 0">${a.distance_km} km away</p>` : ""}
    ${a.answers_in_app ? `<p style="margin:var(--space-2) 0 0"><span class="tag">Answers in the app</span></p>` : ""}
    <div style="margin-top:var(--space-3)">
      ${mine ? `<span class="tag role">Your agyari</span>`
        : `<button type="button" class="small" data-choose="${a.id}">Choose as my agyari</button>`}
    </div>
  </div>`;
}

export async function renderAgyari() {
  chrome(true);
  setHeader("My agyari");
  loading();
  const alive = navGuard();

  let mine = null;
  try {
    mine = (await getMyAgyari()).agyari;
  } catch (e) {
    if (!alive()) return;
    mainEl.innerHTML = loadFailedHtml("your agyari");
    wireRetry(mainEl, () => renderAgyari());
    return;
  }
  if (!alive()) return;

  mainEl.innerHTML = `
    <div class="card" id="agyMine"></div>
    <div class="card">
      <h2>Find an agyari</h2>
      <button type="button" class="secondary" id="agyNear" style="width:100%">Near me</button>
      <p class="meta" id="agyNearNote" style="margin:6px 0 0">Your position is used once to put the nearest first. It is not kept.</p>
      <label for="agySearch">Or search by name or town</label>
      <input type="search" id="agySearch" autocomplete="off" maxlength="100" placeholder="For example: Udvada">
    </div>
    <div id="agyList"><div class="empty-state">Loading...</div></div>`;

  // Where the phone is, for the life of this screen only: a variable, nothing else.
  let here = null;
  let asked = 0;

  const paintMine = () => {
    const box = document.getElementById("agyMine");
    if (!box) return;
    if (!mine) {
      box.innerHTML = `<h2>Your agyari</h2><p class="meta" style="margin:0">${NOT_CHOSEN}</p>`;
      return;
    }
    box.innerHTML = `<h2>Your agyari</h2>
      <p style="margin:0"><b>${esc(mine.name)}</b></p>
      <p class="meta" style="margin:0">${esc([mine.city, kindLabel(mine.kind)].filter(Boolean).join(" · "))}</p>
      ${mine.closed ? `<p class="meta" style="margin:6px 0 0">This agyari is no longer listed. You can choose another below.</p>` : ""}
      ${mine.answers_in_app ? `<p style="margin:var(--space-2) 0 0"><span class="tag">Answers in the app</span></p>` : ""}
      <div style="margin-top:var(--space-3)"><button type="button" class="ghost small" id="agyRemove">Remove my choice</button></div>`;
    document.getElementById("agyRemove").onclick = async (e) => {
      const btn = e.currentTarget;
      btn.disabled = true;
      try {
        await forgetAgyari();
      } catch (err) {
        btn.disabled = false;
        return showError(err.message);
      }
      mine = null;
      paintMine();
      load();
      showInfo("Your choice was removed.");
    };
  };

  const load = async () => {
    const mineRun = ++asked;
    const q = document.getElementById("agySearch").value.trim();
    const list = document.getElementById("agyList");
    let found;
    try {
      found = (await agyariesNearby(q, here)).agyaries;
    } catch (e) {
      if (mineRun !== asked || !alive()) return;
      list.innerHTML = loadFailedHtml("the list of agyaries");
      wireRetry(list, load);
      return;
    }
    if (mineRun !== asked || !alive()) return;
    if (!found.length) {
      list.innerHTML = `<div class="empty-state">${q ? "No agyari found. Try another name or town." : "No agyaries are listed yet."}</div>`;
      return;
    }
    list.innerHTML = found.map((a) => cardHtml(a, mine && mine.id)).join("");
    list.querySelectorAll("[data-choose]").forEach((b) => {
      b.onclick = async () => {
        b.disabled = true;
        try {
          mine = (await chooseAgyari(Number(b.dataset.choose))).agyari;
        } catch (err) {
          b.disabled = false;
          return showError(err.message);
        }
        paintMine();
        load();
        showInfo(`${mine.name} is now your agyari.`);
      };
    });
  };

  let typing = null;
  document.getElementById("agySearch").oninput = () => { clearTimeout(typing); typing = setTimeout(load, 300); };

  document.getElementById("agyNear").onclick = (e) => {
    const btn = e.currentTarget;
    const note = document.getElementById("agyNearNote");
    if (!("geolocation" in navigator)) {
      note.textContent = "This phone cannot tell us where it is. That is fine: please use the search below.";
      return;
    }
    btn.disabled = true;
    note.textContent = "Asking your phone where you are...";
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        here = { lat: pos.coords.latitude, lng: pos.coords.longitude };
        btn.disabled = false;
        note.textContent = "Nearest first. Your position is not kept.";
        load();
      },
      () => {
        btn.disabled = false;
        note.textContent = "That is fine. You can find your agyari with the search below.";
      },
      { enableHighAccuracy: false, timeout: 15000, maximumAge: 300000 },
    );
  };

  paintMine();
  load();
}
