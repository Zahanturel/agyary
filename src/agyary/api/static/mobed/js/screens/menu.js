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

import {
  updateMyName, getPreferences, putPreferences, putDailyReport, signOutOtherDevices, deleteMyAccount,
  claimPanthaky, withdrawPanthakyClaim,
} from "../api.js";
import { signOut } from "../session.js";
import { state, currentAgyary, primarySystem, clearSession, forgetLastPhone, saveSession } from "../state.js";
import { clearAllDrafts } from "../drafts.js";
import {
  chrome, mainEl, showFab, showError, showInfo, refreshHeader, loading, getTextSize, setTextSize, screenFailed,
  keepScroll, openSheet,
} from "../ui.js";
import { esc } from "../util.js";
import { shellVersion } from "../update.js";
import { navigate, navGuard } from "../router.js";
import { flagProblems } from "../fielderrors.js";
import { paintPushCard } from "../push_card.js";

const PARSI_SYSTEMS = [
  ["shenshai", "Shenshai"],
  ["kadmi", "Kadmi"],
];

/** Where the fire temple is, in a few words (D10). */
function locationText(location) {
  if (!location) return "Not on the map yet";
  return location.source === "pin" ? "Pinned on the map" : "Only the town so far - please move the pin";
}

const ROLE_NAMES = { panthaky: "Panthaky", caretaker: "Caretaker", mobed: "Mobed" };

/** "Are you the panthaky?" for a mobed who never answered it (D10), or the
 *  claim they made and can take back while the admin has not decided. */
function claimHtml(agyary) {
  if (agyary.panthaky_claim_waiting) {
    return `<p class="meta" style="margin:12px 0 6px">You told us you are the panthaky here. The admin will
        check it; until then you use the app as a mobed.</p>
      <button class="ghost small" id="mWithdrawClaim">Take it back</button>`;
  }
  if (agyary.may_claim_panthaky) {
    return `<p class="meta" style="margin:12px 0 6px">Are you the panthaky of ${esc(agyary.name)}?</p>
      <button class="ghost small" id="mClaim">Tell us</button>`;
  }
  return "";
}

export async function renderMenu() {
  chrome(true);
  refreshHeader();
  showFab(false);
  loading();
  const alive = navGuard();

  // Normally loaded at sign-in (session.js), so this is the rare case. The
  // page below is drawn from the preferences, so without them it says so and
  // offers to try again; it used to stay on "Loading..." for good.
  if (!state.preferences) {
    try {
      state.preferences = await getPreferences();
    } catch (e) {
      if (!alive()) return;
      return screenFailed(e.message, () => renderMenu());
    }
    if (!alive()) return;
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
          <div class="fact"><div class="fl">Location</div>
            <div class="fv">${locationText(agyary.location)}</div></div>
          <div class="fact"><div class="fl">You are</div>
            <div class="fv">${ROLE_NAMES[agyary.role] || "Mobed"}</div></div>
        ` : ""}
      </div>
      ${agyary ? `<div style="margin-top:10px"><button class="secondary small" id="mEditLocation">Edit location</button></div>
        ${agyary.role === "panthaky" ? `<div style="margin-top:10px"><button class="secondary small" id="mOurMobeds">Our mobeds</button>
          <p class="meta" style="margin:4px 0 0">The mobeds you can ask on WhatsApp whether they can pray.</p></div>
          <div style="margin-top:10px"><button class="secondary small" id="mPrayerRequests">Prayer requests</button>
          <p class="meta" style="margin:4px 0 0">How a request from a Doongerwadi or prayer hall reaches you.</p></div>` : ""}
        <div id="mClaimBox">${claimHtml(agyary)}</div>` : ""}
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
      <h2>Notifications on this phone</h2>
      <div id="mPush"><p class="meta">Checking...</p></div>
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
  paintPushCard(document.getElementById("mPush"), alive, { what: "a Doongerwadi asks your fire temple for prayers" });
  shellVersion().then((v) => {
    const el = document.getElementById("mVersion");
    if (el && v) el.textContent = "App version " + v;
  });

  mainEl.querySelectorAll('input[name="mText"]').forEach(r => {
    r.onchange = () => setTextSize(r.value);
  });

  document.getElementById("mSaveName").onclick = async (ev) => {
    const btn = ev.currentTarget;
    const nameEl = document.getElementById("mName");
    const name = nameEl.value.trim();
    // Said on the name box itself.
    if (!name) return flagProblems(nameEl.closest(".card"), [{ target: "#mName", message: "Please enter your name." }]);
    btn.disabled = true;   // one save per tap
    try {
      state.user = await updateMyName(name);
      refreshHeader();
      showInfo("Saved.");
    } catch (e) {
      showError(e.message);
    } finally {
      btn.disabled = false;
    }
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

  document.getElementById("mSavePrefs").onclick = async (ev) => {
    const btn = ev.currentTarget;
    const primary = document.getElementById("mPrimary").value;
    const checked = Array.from(mainEl.querySelectorAll("[data-sys]"))
      .filter(cb => cb.checked).map(cb => cb.dataset.sys);
    // Gregorian is always shown, and the primary is by definition available -
    // so it goes in whether or not its box happens to be ticked.
    const systems = ["gregorian", primary, ...checked.filter(s => s !== primary)];
    btn.disabled = true;   // one save per tap; the redraw below brings a fresh button
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
      // The same screen drawn again (the primary's own box is now ticked):
      // it stays where it was, at the Calendar card.
      keepScroll(() => renderMenu());
    } catch (e) {
      btn.disabled = false;
      showError(e.message);
    }
  };

  // The same screen drawn again with what the server now says.
  const redrawWith = (user) => {
    state.user = user;
    saveSession();
    return keepScroll(() => renderMenu());
  };
  const claimBtn = document.getElementById("mClaim");
  if (claimBtn) claimBtn.onclick = () => {
    const sheet = openSheet({
      title: `Are you the panthaky of ${agyary.name}?`,
      html: `
        <p>We will tell the admin. Nothing changes for you until the admin confirms it.</p>
        <div class="stack">
          <button type="button" id="clYes">Yes, I am the panthaky</button>
          <button type="button" class="ghost" id="clNo">Cancel</button>
        </div>`,
    });
    sheet.body.querySelector("#clNo").onclick = sheet.close;
    sheet.body.querySelector("#clYes").onclick = async (ev) => {
      const btn = ev.currentTarget;
      btn.disabled = true;   // one claim per tap
      let user;
      try {
        user = await claimPanthaky(agyary.id);
      } catch (e) {
        btn.disabled = false;
        return showError(e.message);
      }
      sheet.close();
      showInfo("Thank you. The admin will check it.");
      if (alive()) redrawWith(user);
    };
  };
  const withdrawBtn = document.getElementById("mWithdrawClaim");
  if (withdrawBtn) withdrawBtn.onclick = async () => {
    withdrawBtn.disabled = true;
    let user;
    try {
      user = await withdrawPanthakyClaim(agyary.id);
    } catch (e) {
      withdrawBtn.disabled = false;
      return showError(e.message);
    }
    showInfo("Taken back. You are a mobed here, as before.");
    if (alive()) redrawWith(user);
  };

  const editLocation = document.getElementById("mEditLocation");
  if (editLocation) editLocation.onclick = () => navigate("#/fire-temple/location");
  const ourMobedsBtn = document.getElementById("mOurMobeds");
  if (ourMobedsBtn) ourMobedsBtn.onclick = () => navigate("#/our-mobeds");
  const prayerRequestsBtn = document.getElementById("mPrayerRequests");
  if (prayerRequestsBtn) prayerRequestsBtn.onclick = () => navigate("#/prayer-requests");
  document.getElementById("mRemindersBar").onclick = () => navigate("#/reminders");
  const adminBar = document.getElementById("mAdminBar");
  if (adminBar) adminBar.onclick = () => navigate("#/admin");

  document.getElementById("mSignOutOthers").onclick = async (ev) => {
    const btn = ev.currentTarget;
    btn.disabled = true;   // one request per tap
    try {
      const r = await signOutOtherDevices();
      showInfo(r.signed_out
        ? `Signed out of ${r.signed_out} other device${r.signed_out === 1 ? "" : "s"}.`
        : "You were not signed in anywhere else.");
    } catch (e) {
      showError(e.message);
    } finally {
      btn.disabled = false;
    }
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
      forgetLastPhone();
      state.accessToken = null;
      state.user = null;
      state.preferences = null;
      location.hash = "#/login";
      location.reload();
    };
  };

  document.getElementById("mSignOut").onclick = (ev) => signOut(ev.currentTarget);
}
