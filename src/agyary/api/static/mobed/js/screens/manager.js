"use strict";

/**
 * The Doongerwadi side (DECISIONS D10): a Doongerwadi, prayer hall or aramgah's
 * manager.
 *
 *  - Signing up: a brand-new account that said "I work at a Doongerwadi or
 *    prayer hall" picks its place from the ones the admin has added, and then
 *    waits for the admin's approval like a new mobed (D9).
 *  - Home, once approved: their place, "Record a death", the book of behdins
 *    (manager_behdins.js), and the deaths recorded with where each request
 *    stands (manager_record.js has the rest).
 *  - Settings: name, text size, sign out, delete the account.
 *
 * A manager has none of the mobed app (no Machi, Calendar or Behdins tabs);
 * the guard in main.js keeps them to these screens and the server refuses
 * them every mobed route anyway.
 *
 * The same home and record screens serve the admin acting for one place
 * (#/admin/act/<placeId>, acting.js): every address goes through managerHash.
 */

import {
  searchFuneralPlaces, joinFuneralPlace, managerPlace, managerRecords, updateMyName, signOutOtherDevices,
  deleteMyAccount,
} from "../api.js";
import { recordState } from "./manager_record.js";
import { state, saveSession, clearSession, forgetLastPhone } from "../state.js";
import {
  chrome, mainEl, showFab, showError, showInfo, refreshHeader, loading, screenFailed, toTop, openSheet,
  getTextSize, setTextSize,
} from "../ui.js";
import { esc, gregLabel } from "../util.js";
import { navigate, navGuard } from "../router.js";
import { signOut } from "../session.js";
import { clearAllDrafts } from "../drafts.js";
import { shellVersion } from "../update.js";
import { flagProblems } from "../fielderrors.js";
import { paintPushCard } from "../push_card.js";
import * as push from "../push.js";
import { managerHash, paintActBanner } from "../acting.js";

/** A way to reach the person who runs Mobed Diary, in words and (if the
 *  server has SUPPORT_PHONE) a WhatsApp button. */
function contactHtml() {
  const digits = ((state.user && state.user.support_phone) || "").replace(/\D/g, "");
  return digits
    ? `<a class="button secondary" href="https://wa.me/${esc(digits)}" target="_blank" rel="noopener">Message us on WhatsApp</a>`
    : `<p class="meta" style="margin:0">Please ask the person who gave you Mobed Diary.</p>`;
}

function placeLine(p) {
  return [p.kind_label, p.city].filter(Boolean).join(" - ");
}

// --- Signing up -------------------------------------------------------------

/** Which Doongerwadi or prayer hall do you work at? `back` returns to the
 *  "mobed or Doongerwadi" question. */
export function renderPlacePick(back) {
  chrome(false);
  mainEl.innerHTML = `
    <div class="card">
      <h2>Which Doongerwadi or prayer hall do you work at?</h2>
      <p class="meta">Tap yours. The admin checks with you before you can start.</p>
      <input type="text" id="fpSearch" placeholder="Search by name or town" autocomplete="off">
      <div id="fpResults" style="margin-top:8px"><p class="meta">Loading...</p></div>
    </div>
    <div style="margin-bottom:14px"><button class="ghost" id="fpBack">Back</button></div>`;
  toTop();
  document.getElementById("fpBack").onclick = () => back();

  const input = document.getElementById("fpSearch");
  const results = document.getElementById("fpResults");
  let timer, token = 0;

  const run = async () => {
    const q = input.value.trim();
    const mine = ++token;
    let places;
    try {
      places = (await searchFuneralPlaces(q)).places;
    } catch (e) {
      if (mine !== token) return;
      results.innerHTML = `<div class="load-failed" role="alert"><p><b></b></p>
        <button class="small" type="button" data-retry>Try again</button></div>`;
      results.querySelector("b").textContent = e.message;
      results.querySelector("[data-retry]").onclick = run;
      return;
    }
    if (mine !== token) return;
    if (!places.length) {
      // Never a dead end: say so, and how to get in touch.
      results.innerHTML = `
        <p>${q ? `Nothing found for “${esc(q)}”.` : "No Doongerwadi or prayer hall is in Mobed Diary yet."}</p>
        <p class="meta">Only the person who runs Mobed Diary can add one. Please get in touch, and we will add
          yours.</p>
        <div class="action-bar">${contactHtml()}</div>`;
      return;
    }
    results.innerHTML = places.map((p, i) => `
      <div class="search-result" data-i="${i}">
        <div><strong>${esc(p.name)}</strong></div>
        <div class="addr">${esc(placeLine(p))}${p.run_by ? ` - ${esc(p.run_by)}` : ""}</div>
      </div>`).join("") + (q ? "" : `<p class="meta" style="margin-top:8px">Not here? Please get in touch, and we
        will add it.</p><div class="action-bar">${contactHtml()}</div>`);
    results.querySelectorAll("[data-i]").forEach(row => {
      row.onclick = () => confirmPlace(places[+row.dataset.i]);
    });
  };
  input.oninput = () => { clearTimeout(timer); timer = setTimeout(run, 200); };
  run();
}

let joining = false;

/** "Do you work here?" asked once more, then they are its manager and wait. */
function confirmPlace(p) {
  if (joining) return;
  const sheet = openSheet({
    title: `Do you work at ${p.name}?`,
    html: `
      <p class="meta" style="margin-top:0">${esc(placeLine(p))}</p>
      <p>You will be its manager in Mobed Diary. The admin checks this before you can start.</p>
      <p class="meta">This account is then for ${esc(p.name)} only. If you are also a mobed, please use another
        number for that.</p>
      <div class="stack">
        <button type="button" id="fpYes">Yes, I work here</button>
        <button type="button" class="ghost" id="fpNo">Cancel</button>
      </div>`,
  });
  sheet.body.querySelector("#fpNo").onclick = sheet.close;
  sheet.body.querySelector("#fpYes").onclick = async (ev) => {
    if (joining) return;
    joining = true;
    const btn = ev.currentTarget;
    btn.disabled = true;   // one join per tap
    try {
      const res = await joinFuneralPlace(p.id);
      state.user = res.user;
      saveSession();
      sheet.close();
      refreshHeader();
      navigate("#/waiting", { replace: true });
    } catch (e) {
      btn.disabled = false;
      showError(e.message);
    } finally {
      joining = false;
    }
  };
}

// --- Home -------------------------------------------------------------------

export async function renderManagerHome() {
  chrome(true);
  refreshHeader();
  showFab(false);
  loading();
  const alive = navGuard();

  let places;
  try {
    places = (await managerPlace()).places;
  } catch (e) {
    if (!alive()) return;
    return screenFailed(e.message, () => renderManagerHome());
  }
  if (!alive()) return;
  if (state.actFor) {
    // The admin acting for this place: their own account keeps no places.
    state.actPlace = places[0] || null;
    paintActBanner();
  } else {
    // What the app keeps follows what the server has now.
    state.user.funeral_places = places;
    saveSession();
    refreshHeader();
  }

  if (!places.length) {
    mainEl.innerHTML = `
      <div class="card" role="status">
        <h2>No place yet</h2>
        <p>Your account is not linked to a Doongerwadi or prayer hall at the moment. Please get in touch.</p>
        <div class="action-bar">${contactHtml()}</div>
      </div>`;
    return;
  }
  const anyOn = places.some(p => p.is_active);
  mainEl.innerHTML = places.map(p => `
    <div class="card">
      <h2>${esc(p.name)}</h2>
      <p class="meta" style="margin:0">${esc(placeLine(p))}${p.run_by ? ` - ${esc(p.run_by)}` : ""}</p>
      ${p.is_active ? "" : `<p class="meta" style="margin:10px 0 0">This place is turned off in Mobed Diary at the
        moment. Please get in touch if that is not right.</p>`}
    </div>`).join("") + `
    <div class="action-bar" style="margin:0 0 14px">
      <button type="button" class="secondary" id="mhBook">Book of behdins</button>
      ${anyOn ? `<button type="button" id="mhRecord">Record a death</button>` : ""}
    </div>
    <div class="card">
      <h2>Deaths recorded</h2>
      <div id="mhRecords"><p class="meta">Loading...</p></div>
    </div>`;
  const rec = document.getElementById("mhRecord");
  if (rec) rec.onclick = () => navigate(managerHash("/record/new"));
  document.getElementById("mhBook").onclick = () => navigate(managerHash("/behdins"));
  paintRecords(document.getElementById("mhRecords"), alive);
}

/** The records, newest first, each with where its request stands; "Show
 *  older" adds the next page. */
async function paintRecords(box, alive, before = null) {
  let page;
  try {
    page = await managerRecords(before);
  } catch (e) {
    if (!alive()) return;
    const failed = document.createElement("div");
    failed.className = "load-failed";
    failed.setAttribute("role", "alert");
    failed.innerHTML = `<p><b></b></p><button class="small" type="button">Try again</button>`;
    failed.querySelector("b").textContent = e.message;
    failed.querySelector("button").onclick = () => { failed.remove(); paintRecords(box, alive, before); };
    if (!before) box.replaceChildren(failed); else box.appendChild(failed);
    return;
  }
  if (!alive()) return;
  if (!before) box.innerHTML = "";
  if (!page.records.length && !before) {
    box.innerHTML = `<p class="meta" style="margin:0">None yet. Tap Record a death to ask a fire temple for the
      prayers.</p>`;
    return;
  }
  const older = box.querySelector("[data-older]");
  if (older) older.remove();
  box.insertAdjacentHTML("beforeend", page.records.map(r => `
    <div class="search-result" data-rec="${r.id}">
      <div><strong>${esc(r.prayed_name)}</strong></div>
      <div class="addr">Died ${esc(gregLabel(r.death.date))}${r.geh_saarnu
        ? ` · Geh-saarnu ${esc(gregLabel(r.geh_saarnu.date))}, ${esc(r.geh_saarnu.geh_name)}` : ""}</div>
      <div style="margin-top:4px;font-size:var(--text-sm)">${esc(recordState(r))}</div>
    </div>`).join("") + (page.more ? `<div data-older style="margin-top:4px">
      <button type="button" class="ghost small">Show older</button></div>` : ""));
  box.querySelectorAll("[data-rec]").forEach(row => {
    row.onclick = () => navigate(managerHash(`/record/${row.dataset.rec}`));
  });
  const more = box.querySelector("[data-older] button");
  if (more) {
    more.onclick = () => {
      more.disabled = true;
      paintRecords(box, alive, page.records[page.records.length - 1].id);
    };
  }
}

// --- Settings ---------------------------------------------------------------

export function renderManagerSettings() {
  chrome(true);
  refreshHeader();
  showFab(false);
  const user = state.user;
  const places = user.funeral_places || [];

  mainEl.innerHTML = `
    <div class="card">
      <h2>You</h2>
      <label for="msName">Name</label>
      <input type="text" id="msName" value="${esc(user.name)}">
      <div style="margin-top:10px"><button class="small" id="msSaveName">Save name</button></div>
      <div style="margin-top:14px">
        <div class="fact"><div class="fl">Phone</div><div class="fv">${esc(user.phone)}</div></div>
        ${places.map(p => `<div class="fact"><div class="fl">Manager at</div>
          <div class="fv">${esc(p.name)}</div></div>`).join("")}
      </div>
    </div>

    <div class="card">
      <h2>Notifications on this phone</h2>
      <div id="msPush"><p class="meta">Checking...</p></div>
    </div>

    <div class="card">
      <h2>Text size</h2>
      <p class="meta">Makes the words in the app bigger on this phone.</p>
      <label class="choice"><input type="radio" name="msText" value="large" ${getTextSize() === "large" ? "checked" : ""}><span>Large</span></label>
      <label class="choice"><input type="radio" name="msText" value="xl" ${getTextSize() === "xl" ? "checked" : ""}><span>Extra large</span></label>
    </div>

    <div class="card">
      <button class="ghost" id="msSignOut">Sign out</button>
      <div style="margin-top:12px"><button class="ghost small" id="msSignOutOthers">Sign out of my other devices</button></div>
      <p class="meta" style="margin:8px 0 0">For a phone that was lost or lent. This phone stays signed in.</p>
      <p class="meta" style="margin:10px 0 0" id="msVersion"></p>
    </div>

    <div class="card">
      <button class="ghost small" id="msDelete">Delete my account</button>
      <div id="msDeleteConfirm"></div>
    </div>`;
  paintPushCard(document.getElementById("msPush"), navGuard(),
    { what: "Mobed Diary has news for you" });
  shellVersion().then((v) => {
    const el = document.getElementById("msVersion");
    if (el && v) el.textContent = "App version " + v;
  });

  mainEl.querySelectorAll('input[name="msText"]').forEach(r => { r.onchange = () => setTextSize(r.value); });

  document.getElementById("msSaveName").onclick = async (ev) => {
    const btn = ev.currentTarget;
    const nameEl = document.getElementById("msName");
    const name = nameEl.value.trim();
    if (!name) return flagProblems(nameEl.closest(".card"), [{ target: "#msName", message: "Please enter your name." }]);
    btn.disabled = true;
    try {
      state.user = await updateMyName(name);
      saveSession();
      refreshHeader();
      showInfo("Saved.");
    } catch (e) {
      showError(e.message);
    } finally {
      btn.disabled = false;
    }
  };

  document.getElementById("msSignOut").onclick = (ev) => signOut(ev.currentTarget);
  document.getElementById("msSignOutOthers").onclick = async (ev) => {
    const btn = ev.currentTarget;
    btn.disabled = true;
    try {
      // This phone keeps its notifications; the others' stop.
      const sub = await push.thisPhone();
      const r = await signOutOtherDevices(sub ? sub.endpoint : null);
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
  document.getElementById("msDelete").onclick = () => {
    const box = document.getElementById("msDeleteConfirm");
    box.innerHTML = `
      <p style="margin:12px 0 8px"><b>Delete your account?</b></p>
      <p class="meta" style="margin:0 0 12px">This removes your account from Mobed Diary. ${places.length
        ? `${esc(places[0].name)} stays in the app.` : ""} It cannot be undone. You can sign up again later.</p>
      <div class="row tight">
        <button class="danger small" id="msDeleteYes">Delete my account</button>
        <button class="ghost small" id="msDeleteNo">Keep my account</button>
      </div>`;
    document.getElementById("msDeleteNo").onclick = () => { box.innerHTML = ""; };
    document.getElementById("msDeleteYes").onclick = async (e) => {
      const btn = e.currentTarget;
      btn.disabled = true;
      try {
        await deleteMyAccount();
      } catch (err) {
        btn.disabled = false;
        return showError(err.message);
      }
      // The server forgot this phone's notifications with the account; the browser drops them too.
      await push.forget(await push.thisPhone());
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
}
