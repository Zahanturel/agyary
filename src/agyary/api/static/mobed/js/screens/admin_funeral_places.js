"use strict";

/**
 * Admin -> Doongerwadis: the Doongerwadis, prayer halls and aramgahs a manager
 * can choose when they sign up (DECISIONS D10). Only an admin adds or changes
 * one; nobody can add one themselves. A place is turned off, never deleted
 * (D8): it is then no longer offered at sign-up, and its managers keep their
 * accounts (their own switch is on Admin -> Mobeds).
 *
 * For the numbers in ADMIN_PHONES only; the server answers anyone else with a
 * 404, so hiding the way here is a courtesy and not the protection.
 */

import {
  adminFuneralPlaces, adminFuneralPlace, adminCreateFuneralPlace, adminUpdateFuneralPlace,
  adminSetFuneralPlaceActive,
} from "../api.js";
import {
  chrome, mainEl, showFab, showError, showInfo, refreshHeader, loading, backBar, screenFailed, flashInfo,
} from "../ui.js";
import { esc } from "../util.js";
import { navGuard, navigate, returnTo } from "../router.js";
import { flagProblems } from "../fielderrors.js";
import { mountLocationPicker } from "../location_picker.js";

const LIST = "#/admin/funeral-places";
const KINDS = [["doongerwadi", "Doongerwadi"], ["prayer_hall", "Prayer hall"], ["aramgah", "Aramgah"]];

function managersText(m) {
  const parts = [];
  if (m.on) parts.push(`${m.on} manager${m.on === 1 ? "" : "s"}`);
  if (m.pending) parts.push(`${m.pending} waiting`);
  if (m.off) parts.push(`${m.off} turned off`);
  return parts.length ? parts.join(", ") : "No managers yet";
}

function placeRow(p) {
  return `
    <div class="section-bar" data-place="${p.id}">
      <div class="sb-text"><b>${esc(p.name)}${p.is_active ? "" : ` <span class="tag grey">Off</span>`}</b>
        <span>${esc(p.kind_label)} - ${esc(p.city)}${p.location ? "" : " - not on the map"}</span>
        <span>${esc(managersText(p.managers))}</span></div>
      <div class="sb-actions"><span class="chev">&rsaquo;</span></div>
    </div>`;
}

export async function renderAdminFuneralPlaces() {
  chrome(true);
  refreshHeader();
  showFab(false);
  loading();
  const alive = navGuard();

  let data;
  try {
    data = await adminFuneralPlaces();
  } catch (e) {
    if (!alive()) return;
    if (e.status === 404) return screenFailed("That page isn't available.");
    return screenFailed(e.message, () => renderAdminFuneralPlaces());
  }
  if (!alive()) return;
  const inUse = data.places.filter(p => p.is_active);
  const off = data.places.filter(p => !p.is_active);

  mainEl.innerHTML = `
    <div class="card">
      ${backBar("Doongerwadis")}
      <p class="meta" style="margin:4px 0 0">The Doongerwadis, prayer halls and aramgahs a manager can choose
        when they sign up. Only you can add them. New managers wait for you on the Mobeds page.</p>
      <div class="action-bar"><button id="fpAdd">Add a place</button></div>
    </div>

    <div class="card">
      <h2>In use (${inUse.length})</h2>
      ${inUse.length ? inUse.map(placeRow).join("") : `<p class="meta">None yet. Add the first one above.</p>`}
    </div>

    ${off.length ? `<div class="card">
      <h2>Turned off (${off.length})</h2>
      <p class="meta" style="margin:4px 0 0">Not offered to new managers. Nothing about them is deleted.</p>
      ${off.map(placeRow).join("")}
    </div>` : ""}`;

  document.getElementById("fpAdd").onclick = () => navigate(LIST + "/new");
  mainEl.querySelectorAll("[data-place]").forEach(row => {
    row.onclick = () => navigate(`${LIST}/${row.dataset.place}`);
  });
}

/** Add a place (no `id`) or change one. */
export async function renderAdminFuneralPlace({ id } = {}) {
  chrome(true);
  refreshHeader();
  showFab(false);
  loading();
  const alive = navGuard();

  let place = null;
  if (id) {
    try {
      place = await adminFuneralPlace(id);
    } catch (e) {
      if (!alive()) return;
      if (e.status === 404) return screenFailed("That place could not be found.");
      return screenFailed(e.message, () => renderAdminFuneralPlace({ id }));
    }
    if (!alive()) return;
  }
  const v = place || { name: "", kind: "", city: "", address: "", run_by: "", location: null, is_active: true };

  mainEl.innerHTML = `
    <div class="card">
      ${backBar(place ? esc(place.name) : "Add a place")}
      <label for="fpName">Name</label>
      <input type="text" id="fpName" value="${esc(v.name)}" autocomplete="off" placeholder="e.g. Doongerwadi">
      <label>What kind of place</label>
      <div class="choice-group" id="fpKind">
        ${KINDS.map(([k, label]) => `<label class="choice"><input type="radio" name="fpKind" value="${k}"
          ${v.kind === k ? "checked" : ""}><span>${label}</span></label>`).join("")}
      </div>
      <label for="fpCity">Town</label>
      <input type="text" id="fpCity" value="${esc(v.city)}" autocomplete="off">
      <label for="fpAddr">Address (optional)</label>
      <input type="text" id="fpAddr" value="${esc(v.address || "")}" autocomplete="off">
      <label for="fpRunBy">Run by (optional)</label>
      <input type="text" id="fpRunBy" value="${esc(v.run_by || "")}" autocomplete="off"
        placeholder="e.g. the Punchayet or trust">
    </div>

    <div class="card">
      <h2>Where is it? (optional)</h2>
      <p class="meta">Put the pin on the place itself. Later, fire temples will be suggested nearest first.</p>
      <div id="fpPicker"></div>
      <div class="action-bar"><button type="button" id="fpSave">${place ? "Save changes" : "Add it"}</button></div>
    </div>

    ${place ? `<div class="card">
      <h2>${place.is_active ? "Turn this place off" : "This place is turned off"}</h2>
      <p class="meta">${place.is_active
        ? "New managers will no longer see it when they sign up. Nothing is deleted, and its managers keep their accounts."
        : "New managers do not see it when they sign up. Turn it on to offer it again."}</p>
      <div style="margin-top:10px"><button type="button" class="${place.is_active ? "ghost" : "secondary"} small"
        id="fpActive">${place.is_active ? "Turn off" : "Turn on again"}</button></div>
      <div id="fpAsk"></div>
    </div>` : ""}`;

  const picker = mountLocationPicker(document.getElementById("fpPicker"), {
    initial: v.location ? { ...v.location, source: "pin" } : null,
    suggest: () => [document.getElementById("fpName").value.trim(), document.getElementById("fpCity").value.trim()]
      .filter(Boolean).join(", "),
    noun: "the place",
    hereLabel: "I'm there now",
  });

  document.getElementById("fpSave").onclick = async (ev) => {
    const btn = ev.currentTarget;
    const el = (x) => document.getElementById(x);
    const kind = mainEl.querySelector('input[name="fpKind"]:checked');
    const body = {
      name: el("fpName").value.trim(),
      kind: kind ? kind.value : "",
      city: el("fpCity").value.trim(),
      address: el("fpAddr").value.trim() || null,
      run_by: el("fpRunBy").value.trim() || null,
      location: picker.get(),
    };
    const problems = [];
    if (!body.name) problems.push({ target: el("fpName"), message: "Please enter the place's name." });
    if (!body.kind) problems.push({ target: el("fpKind"), message: "Please choose what kind of place it is." });
    if (!body.city) problems.push({ target: el("fpCity"), message: "Please enter the town." });
    if (problems.length) return flagProblems(mainEl, problems);
    btn.disabled = true;   // one save per tap
    let saved;
    try {
      saved = place ? await adminUpdateFuneralPlace(place.id, body) : await adminCreateFuneralPlace(body);
    } catch (e) {
      btn.disabled = false;
      return showError(e.message);
    }
    picker.destroy();
    flashInfo(place ? `${saved.name} is saved.` : `${saved.name} is added. Managers can choose it when they sign up.`);
    if (alive()) returnTo(LIST);
  };

  const activeBtn = document.getElementById("fpActive");
  if (activeBtn) activeBtn.onclick = () => {
    const turnOn = !place.is_active;
    const go = async (btn) => {
      btn.disabled = true;
      try {
        await adminSetFuneralPlaceActive(place.id, turnOn);
      } catch (e) {
        btn.disabled = false;
        return showError(e.message);
      }
      showInfo(turnOn ? `${place.name} is on again.` : `${place.name} is turned off.`);
      if (!alive()) return;
      const y = window.scrollY;
      await renderAdminFuneralPlace({ id: place.id });
      if (alive()) window.scrollTo(0, y);
    };
    if (turnOn) return go(activeBtn);
    // Turning off is asked first.
    const ask = document.getElementById("fpAsk");
    ask.innerHTML = `
      <p class="meta" style="margin:10px 0 8px">Turn ${esc(place.name)} off? New managers will not see it.</p>
      <div class="row tight">
        <button type="button" class="danger small" data-go>Turn off</button>
        <button type="button" class="ghost small" data-no>Cancel</button>
      </div>`;
    ask.querySelector("[data-no]").onclick = () => { ask.innerHTML = ""; };
    ask.querySelector("[data-go]").onclick = (e) => go(e.currentTarget);
  };
}
