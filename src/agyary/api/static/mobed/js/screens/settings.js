"use strict";

/**
 * Settings: your own profile, how you want dates shown, your fire temple's
 * details and service catalog, and - for management - the way into invites.
 */

import {
  updateMyName, getPreferences, putPreferences, listServices, createService,
  setServiceActive, activateAgyary, logout,
} from "../api.js";
import { state, currentAgyary, isManager, currentRole } from "../state.js";
import {
  chrome, mainEl, showFab, showError, showInfo, markActiveTab, refreshHeader,
  loading, keepScroll,
} from "../ui.js";
import { esc, phoneField, readOptionalPhone } from "../util.js";
import { navigate } from "../router.js";

const CALENDAR_SYSTEMS = [
  ["gregorian", "Gregorian"],
  ["shenshai", "Shenshai"],
  ["kadmi", "Kadmi"],
  ["fasli", "Fasli"],
];
const PARSI_SYSTEMS = CALENDAR_SYSTEMS.filter(([k]) => k !== "gregorian");

export async function renderSettings() {
  chrome(true);
  refreshHeader();
  markActiveTab("#/settings");
  showFab(false);
  loading();

  const agyary = currentAgyary();
  const manage = isManager();
  let services = [];
  if (agyary) { try { services = await listServices(agyary.id); } catch (e) { /* non-fatal */ } }
  if (!state.preferences) {
    try { state.preferences = await getPreferences(); } catch (e) { /* defaults already set */ }
  }
  const prefs = state.preferences;
  const visible = prefs.visible_calendar_systems || ["gregorian", "shenshai"];

  mainEl.innerHTML = `
    <div class="card">
      <h2>You</h2>
      <label>Your name</label>
      <input type="text" id="stName" value="${esc(state.user.name)}">
      <label>Your phone</label>
      <input type="text" value="${esc(state.user.phone)}" disabled>
      <p class="meta">Your number is how you sign in${currentRole() ? ` · you are a ${esc(currentRole())} here` : ""}.</p>
      <div style="margin-top:14px"><button id="stSaveName">Save name</button></div>
    </div>

    <div class="card">
      <h2>Calendars</h2>
      <p class="meta">Dates always show the Gregorian day first. Choose which Parsi
        reckonings you want available, and which one sits under every date.</p>
      <div class="names-group-label"><b>Show these</b></div>
      ${CALENDAR_SYSTEMS.map(([key, label]) => `
        <div class="check-row">
          <input type="checkbox" id="cs_${key}" data-sys="${key}"
                 ${visible.includes(key) ? "checked" : ""} ${key === "gregorian" ? "disabled" : ""}>
          <label for="cs_${key}">${label}${key === "gregorian" ? " (always shown)" : ""}</label>
        </div>`).join("")}
      <label>Shown under every date</label>
      <select id="stSecondary">
        ${PARSI_SYSTEMS.map(([key, label]) =>
          `<option value="${key}" ${prefs.default_secondary_system === key ? "selected" : ""}>${label}</option>`).join("")}
      </select>
      <p class="meta">The others are one tap away on any day in the calendar.</p>
      <div style="margin-top:14px"><button id="stSavePrefs">Save calendar settings</button></div>
    </div>

    <div class="card">
      <div class="row tight" style="justify-content:space-between;align-items:center">
        <h2 style="margin:0">Behdins</h2>
        <button class="ghost small" id="stBehdins">Open</button>
      </div>
      <p class="meta">${manage
        ? "Register a behdin, correct their details, and manage their saved names."
        : "The behdins you have booked for, and your history with each."}</p>
    </div>

    ${manage ? `
    <div class="card">
      <div class="row tight" style="justify-content:space-between;align-items:center">
        <h2 style="margin:0">People</h2>
        <button class="ghost small" id="stInvites">Open</button>
      </div>
      <p class="meta">Invite a mobed, panthaky or caretaker to this fire temple.</p>
    </div>` : ""}

    ${agyary ? `
    <div class="card">
      <h2>${esc(agyary.name)}</h2>
      ${manage ? `
        <label>Name</label><input type="text" id="stTempleName" value="${esc(agyary.name)}">
        <label>City</label><input type="text" id="stTempleCity" value="${esc(agyary.city || "")}">
        <label>Address</label><input type="text" id="stTempleAddr" value="${esc(agyary.address || "")}">
        <label>Contact phone (optional)</label>${phoneField("stTemplePhone", agyary.contact_phone || "")}
        <div style="margin-top:14px"><button id="stSaveTemple">Save fire temple details</button></div>
      ` : `<p class="meta">${esc([agyary.address, agyary.city].filter(Boolean).join(", "))}</p>`}
    </div>

    ${manage ? `
    <div class="card">
      <h2>Services</h2>
      <p class="meta">What this fire temple offers when booking. Machi has its own path and isn't listed.</p>
      <div id="stServices">${services.length
        ? services.map(s => `<div class="list-row">
            <div class="lr-main"><b>${esc(s.name)}</b>
              <span>${s.offsite_capable ? "Can be performed offsite" : "At the fire temple"}${
                s.is_active ? "" : " · inactive"}</span></div>
            <button class="ghost small" data-svc="${s.id}" data-active="${s.is_active}">
              ${s.is_active ? "Deactivate" : "Activate"}</button>
          </div>`).join("")
        : '<p class="meta">No services yet.</p>'}</div>
      <div style="margin-top:10px"><button class="secondary small" id="stAddSvc">+ Add a service</button></div>
      <div id="stSvcPanel"></div>
    </div>` : ""}` : ""}

    <div class="card">
      <button class="ghost" id="stSignOut">Sign out</button>
    </div>`;

  document.getElementById("stSaveName").onclick = async () => {
    const name = document.getElementById("stName").value.trim();
    if (!name) return showError("Please enter your name.");
    try {
      state.user = await updateMyName(name);
      refreshHeader();
      showInfo("Saved.");
    } catch (e) { showError(e.message); }
  };

  document.getElementById("stSavePrefs").onclick = async () => {
    const chosen = Array.from(mainEl.querySelectorAll("[data-sys]"))
      .filter(cb => cb.checked || cb.dataset.sys === "gregorian")
      .map(cb => cb.dataset.sys);
    const secondary = document.getElementById("stSecondary").value;
    if (!chosen.includes(secondary)) {
      return showError("The calendar shown under every date has to be one you've ticked.");
    }
    try {
      state.preferences = await putPreferences({
        visible_calendar_systems: chosen,
        default_secondary_system: secondary,
        // Infrastructure only for now - carried through untouched so a value
        // set elsewhere isn't clobbered by saving this form.
        display_language: state.preferences.display_language || "en",
      });
      showInfo("Calendar settings saved.");
    } catch (e) { showError(e.message); }
  };

  document.getElementById("stBehdins").onclick = () => navigate("#/behdins");
  const invites = document.getElementById("stInvites");
  if (invites) invites.onclick = () => navigate("#/manage/invites");

  const saveTemple = document.getElementById("stSaveTemple");
  if (saveTemple) {
    saveTemple.onclick = async () => {
      const phoneRes = readOptionalPhone("stTemplePhone");
      if (!phoneRes.ok) return showError("Please enter a valid phone number, or leave it blank.");
      const body = {
        name: document.getElementById("stTempleName").value.trim(),
        city: document.getElementById("stTempleCity").value.trim(),
        address: document.getElementById("stTempleAddr").value.trim() || null,
        contact_phone: phoneRes.value,
      };
      if (!body.name || !body.city) return showError("Name and city are required.");
      try {
        const res = await activateAgyary(agyary.id, body);
        state.user = res.user;
        refreshHeader();
        showInfo("Saved.");
      } catch (e) { showError(e.message); }
    };
  }

  mainEl.querySelectorAll("[data-svc]").forEach(btn => {
    btn.onclick = async () => {
      try {
        await setServiceActive(agyary.id, btn.dataset.svc, btn.dataset.active !== "true");
        delete state.formOptionsCache[agyary.id];
        keepScroll(renderSettings);
      } catch (e) { showError(e.message); }
    };
  });

  const addSvc = document.getElementById("stAddSvc");
  if (addSvc) {
    addSvc.onclick = () => {
      const panel = document.getElementById("stSvcPanel");
      panel.innerHTML = `
        <div class="card" style="margin-top:12px">
          <label>Service name</label><input type="text" id="svcName" placeholder="e.g. Afringan">
          <div class="check-row">
            <input type="checkbox" id="svcOffsite">
            <label for="svcOffsite">Can be performed away from the fire temple</label>
          </div>
          <div class="row tight" style="margin-top:12px">
            <button class="small" id="svcSave">Add</button>
            <button class="ghost small" id="svcCancel">Cancel</button>
          </div>
        </div>`;
      document.getElementById("svcCancel").onclick = () => { panel.innerHTML = ""; };
      document.getElementById("svcSave").onclick = async () => {
        const name = document.getElementById("svcName").value.trim();
        if (!name) return showError("Please enter a service name.");
        try {
          await createService(agyary.id, name, document.getElementById("svcOffsite").checked);
          delete state.formOptionsCache[agyary.id];
          renderSettings();
        } catch (e) { showError(e.message); }
      };
    };
  }

  document.getElementById("stSignOut").onclick = async () => {
    // The server has to clear the refresh cookie - it's httpOnly, so
    // dropping the in-memory token alone would leave the next page load
    // signing straight back in.
    try { await logout(); } catch (e) { /* clear locally regardless */ }
    state.accessToken = null;
    state.user = null;
    state.preferences = null;
    location.hash = "#/login";
    location.reload();
  };
}
