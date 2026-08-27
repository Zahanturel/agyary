"use strict";

/**
 * The menu, behind the header icon. Three sections and nothing else:
 * who you are, which calendar you read in, and your behdins.
 *
 * Everything management-shaped - the fire temple's own details,
 * the service catalog - is deliberately absent. Those belong to the agyari
 * management system, which does not exist yet and will be designed after
 * talking to actual panthakies.
 */

import { updateMyName, getPreferences, putPreferences, logout } from "../api.js";
import { state, currentAgyary, primarySystem, clearSession } from "../state.js";
import {
  chrome, mainEl, showFab, showError, showInfo, refreshHeader, loading,
} from "../ui.js";
import { esc } from "../util.js";
import { navigate } from "../router.js";

const PARSI_SYSTEMS = [
  ["shenshai", "Shenshai"],
  ["kadmi", "Kadmi"],
  ["fasli", "Fasli"],
];

export async function renderMenu() {
  chrome(true);
  refreshHeader();
  showFab(false);
  loading();

  if (!state.preferences) {
    try { state.preferences = await getPreferences(); } catch (e) { /* defaults stand */ }
  }
  const prefs = state.preferences;
  const visible = prefs.visible_calendar_systems || ["gregorian", "shenshai"];
  const agyary = currentAgyary();

  mainEl.innerHTML = `
    <div class="card">
      <h2>You</h2>
      <label>Name</label>
      <input type="text" id="mName" value="${esc(state.user.name)}">
      <div style="margin-top:10px"><button class="small" id="mSaveName">Save name</button></div>
      <div style="margin-top:14px">
        <div class="fact"><div class="fl">Phone</div>
          <div class="fv">${esc(state.user.phone)}</div></div>
        ${agyary ? `
          <div class="fact"><div class="fl">Fire temple</div>
            <div class="fv">${esc(agyary.name)}</div></div>
          <div class="fact"><div class="fl">Address</div>
            <div class="fv">${esc([agyary.address, agyary.city].filter(Boolean).join(", ") || "-")}</div></div>
        ` : ""}
      </div>
    </div>

    <div class="card">
      <h2>Calendar</h2>
      <p class="meta">Dates always show the Gregorian day. Your primary calendar is
        what appears beneath it, and what you enter Roj and Mah in.</p>
      <label>Primary calendar</label>
      <select id="mPrimary">
        ${PARSI_SYSTEMS.map(([key, label]) =>
          `<option value="${key}" ${primarySystem() === key ? "selected" : ""}>${label}</option>`).join("")}
      </select>
      <div class="names-group-label" style="margin-top:16px"><b>Also available</b>
        <span>shown when you tap a day</span></div>
      ${PARSI_SYSTEMS.map(([key, label]) => `
        <div class="check-row">
          <input type="checkbox" id="cs_${key}" data-sys="${key}" ${visible.includes(key) ? "checked" : ""}>
          <label for="cs_${key}">${label}</label>
        </div>`).join("")}
      <div style="margin-top:14px"><button class="small" id="mSavePrefs">Save calendar</button></div>
    </div>

    <div class="card">
      <div class="section-bar" id="mBehdinBar">
        <div class="sb-text"><b>Manage your behdins</b>
          <span>Names, numbers and their saved name lists</span></div>
        <div class="sb-actions">
          <button class="icon-add" id="mAddBehdin" title="Add a behdin" aria-label="Add a behdin">+</button>
          <span class="chev">&rsaquo;</span>
        </div>
      </div>
    </div>

    <div class="card">
      <button class="ghost" id="mSignOut">Sign out</button>
    </div>`;

  document.getElementById("mSaveName").onclick = async () => {
    const name = document.getElementById("mName").value.trim();
    if (!name) return showError("Please enter your name.");
    try {
      state.user = await updateMyName(name);
      refreshHeader();
      showInfo("Saved.");
    } catch (e) { showError(e.message); }
  };

  document.getElementById("mSavePrefs").onclick = async () => {
    const primary = document.getElementById("mPrimary").value;
    const checked = Array.from(mainEl.querySelectorAll("[data-sys]"))
      .filter(cb => cb.checked).map(cb => cb.dataset.sys);
    // Gregorian is always shown, and the primary is by definition available -
    // so it goes in whether or not its box happens to be ticked.
    const systems = ["gregorian", primary, ...checked.filter(s => s !== primary)];
    try {
      state.preferences = await putPreferences({
        visible_calendar_systems: [...new Set(systems)],
        default_secondary_system: primary,
        display_language: state.preferences.display_language || "en",
      });
      // Every rendered Parsi date derives from this, and cached readings
      // were computed under the old primary.
      state.parsiCache = {};
      state.parsiMonthCache = {};
      state.calendar.parsiMonth = null;
      showInfo("Calendar saved.");
      renderMenu();
    } catch (e) { showError(e.message); }
  };

  // The whole bar opens the list; the + is a shortcut straight to adding.
  document.getElementById("mBehdinBar").onclick = (e) => {
    if (e.target.closest("#mAddBehdin")) return;
    navigate("#/behdins");
  };
  // Straight to the one-page add screen - name, number, import-from-contacts
  // and the saved names all in one place. It used to unfold a second panel
  // here that could only do name and number, so adding saved names meant
  // saving, opening the behdin, and editing them in: three steps for one
  // job, and the reason this shortcut existed at all was to avoid steps.
  document.getElementById("mAddBehdin").onclick = (e) => {
    e.stopPropagation();
    navigate("#/behdins/new");
  };

  document.getElementById("mSignOut").onclick = async () => {
    // The server has to clear the refresh cookie - it's httpOnly, so
    // dropping the in-memory token alone would sign you back in on the
    // next load.
    try { await logout(); } catch (e) { /* clear locally regardless */ }
    clearSession();
    state.accessToken = null;
    state.user = null;
    state.offline = false;
    state.preferences = null;
    location.hash = "#/login";
    location.reload();
  };
}
