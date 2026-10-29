"use strict";

/**
 * Settings, behind the header icon: who you are, and which calendar you read in.
 * Your behdins are a tab of their own, not here. This is the one place the
 * tab bar is not shown.
 *
 * Everything management-shaped - the fire temple's own details,
 * the service catalog - is deliberately absent. Those belong to the agyari
 * management system, which does not exist yet and will be designed after
 * talking to actual panthakies.
 */

import { updateMyName, getPreferences, putPreferences, putDailyReport, logout, signOutOtherDevices, deleteMyAccount } from "../api.js";
import { state, currentAgyary, primarySystem, clearSession } from "../state.js";
import { clearAllDrafts } from "../drafts.js";
import {
  chrome, mainEl, showFab, showError, showInfo, refreshHeader, loading, getTextSize, setTextSize,
} from "../ui.js";
import { esc } from "../util.js";
import { shellVersion } from "../update.js";
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
      <h2>Text size</h2>
      <p class="meta">Makes the words in the app bigger on this phone.</p>
      <div id="mTextSize">
        <label class="choice"><input type="radio" name="mText" value="large" ${getTextSize() === "large" ? "checked" : ""}><span>Large</span></label>
        <label class="choice"><input type="radio" name="mText" value="xl" ${getTextSize() === "xl" ? "checked" : ""}><span>Extra large</span></label>
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
        <span>shown on each day</span></div>
      ${PARSI_SYSTEMS.map(([key, label]) => `
        <div class="check-row">
          <input type="checkbox" id="cs_${key}" data-sys="${key}" ${visible.includes(key) ? "checked" : ""}>
          <label for="cs_${key}">${label}</label>
        </div>`).join("")}
      <div style="margin-top:14px"><button class="small" id="mSavePrefs">Save calendar</button></div>
    </div>

    <div class="card">
      <h2>Daily report</h2>
      <p class="meta">Every evening at about 8 pm, a list of what is on your day tomorrow - your services,
        machis and memorial prayers, with the behdins' names - so you can prepare the day before.
        It appears in the app${state.user.daily_report_whatsapp ? ` and is sent to your WhatsApp (${esc(state.user.phone)})` : ""}.
        Nothing is sent when tomorrow is empty.</p>
      <div class="check-row">
        <input type="checkbox" id="mDaily" ${state.user.daily_report ? "checked" : ""}>
        <label for="mDaily">Send me tomorrow's list every evening</label>
      </div>
    </div>

    <div class="card">
      <div class="section-bar" id="mRemindersBar">
        <div class="sb-text"><b>Reminders</b>
          <span>Families to remind about memorial prayers</span></div>
        <div class="sb-actions"><span class="chev">&rsaquo;</span></div>
      </div>
    </div>
    ${state.user.is_admin ? `<div class="card">
      <div class="section-bar" id="mAdminBar">
        <div class="sb-text"><b>Admin</b>
          <span>Sending limits, cost and the pause switch</span></div>
        <div class="sb-actions"><span class="chev">&rsaquo;</span></div>
      </div>
    </div>` : ""}

    <div class="card">
      <button class="ghost" id="mSignOut">Sign out</button>
      <div style="margin-top:12px"><button class="ghost small" id="mSignOutOthers">Sign out of my other devices</button></div>
      <p class="meta" style="margin:8px 0 0">For a phone that was lost or lent, or a sign-in you do not recognise.
        This phone stays signed in.</p>
      <p class="meta" style="margin:10px 0 0" id="mVersion"></p>
    </div>

    <div class="card">
      <button class="ghost small" id="mDelete">Delete my account</button>
      <div id="mDeleteConfirm"></div>
    </div>`;
  shellVersion().then((v) => {
    const el = document.getElementById("mVersion");
    if (el && v) el.textContent = "App version " + v;
  });

  mainEl.querySelectorAll('input[name="mText"]').forEach(r => {
    r.onchange = () => setTextSize(r.value);
  });

  document.getElementById("mSaveName").onclick = async () => {
    const name = document.getElementById("mName").value.trim();
    if (!name) return showError("Please enter your name.");
    try {
      state.user = await updateMyName(name);
      refreshHeader();
      showInfo("Saved.");
    } catch (e) { showError(e.message); }
  };

  // One switch, saved as it is flipped; put back if the save fails.
  document.getElementById("mDaily").onchange = async (e) => {
    const box = e.target;
    box.disabled = true;
    try {
      const r = await putDailyReport(box.checked);
      state.user.daily_report = r.daily_report;
      showInfo(r.daily_report ? "Daily report on. You will get tomorrow's list each evening." : "Daily report off.");
    } catch (err) {
      box.checked = !box.checked;
      showError(err.message);
    } finally {
      box.disabled = false;
    }
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

  document.getElementById("mRemindersBar").onclick = () => navigate("#/reminders");
  const adminBar = document.getElementById("mAdminBar");
  if (adminBar) adminBar.onclick = () => navigate("#/admin");

  document.getElementById("mSignOutOthers").onclick = async () => {
    try {
      const r = await signOutOtherDevices();
      showInfo(r.signed_out
        ? `Signed out of ${r.signed_out} other device${r.signed_out === 1 ? "" : "s"}.`
        : "You were not signed in anywhere else.");
    } catch (e) { showError(e.message); }
  };

  // Two steps, in plain words: what goes, and that it cannot be undone.
  document.getElementById("mDelete").onclick = () => {
    const box = document.getElementById("mDeleteConfirm");
    box.innerHTML = `
      <p style="margin:12px 0 8px"><b>Delete your account?</b></p>
      <p class="meta" style="margin:0 0 12px">This removes your account and everything in it: your behdins and
        their saved names, your memorials and reminders, and the machis and bookings you made. It cannot be
        undone. You can always sign up again later.</p>
      <div class="row tight">
        <button class="danger small" id="mDeleteYes">Delete everything</button>
        <button class="ghost small" id="mDeleteNo">Keep my account</button>
      </div>`;
    document.getElementById("mDeleteNo").onclick = () => { box.innerHTML = ""; };
    document.getElementById("mDeleteYes").onclick = async (e) => {
      e.target.disabled = true;
      try {
        await deleteMyAccount();
      } catch (err) {
        e.target.disabled = false;
        return showError(err.message);
      }
      clearSession();
      clearAllDrafts();
      state.accessToken = null;
      state.user = null;
      state.preferences = null;
      location.hash = "#/login";
      location.reload();
    };
  };

  document.getElementById("mSignOut").onclick = async () => {
    // The server has to clear the refresh cookie - it's httpOnly, so
    // dropping the in-memory token alone would sign you back in on the
    // next load.
    try { await logout(); } catch (e) { /* clear locally regardless */ }
    clearSession();
    clearAllDrafts();
    state.accessToken = null;
    state.user = null;
    state.offline = false;
    state.preferences = null;
    location.hash = "#/login";
    location.reload();
  };
}
