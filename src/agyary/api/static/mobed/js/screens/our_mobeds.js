"use strict";

/**
 * Mobeds (DECISIONS D10, changed 21 Nov 2026; R3.1 step 3; "Our mobeds"
 * before): the mobeds a confirmed panthaky works with, to call, message, or ask
 * on WhatsApp whether they can pray. The panthaky's fifth tab (owner, 24 Nov
 * 2026), and reached from a request's board while nobody is on the list, at
 * #/mobeds (the old #/our-mobeds leads here too).
 *
 * One list, drawn like Behdins (owner, 24 Nov 2026): a round letter, the name and
 * number, Call and WhatsApp (not on the panthaky's own row), and on the right a
 * pen (edit) and a cross (take off the list):
 *  - mobeds added by hand: pen and cross. Adding is the Add button at the top,
 *    with Import from contacts where the phone allows it (as on the Add behdin
 *    form) and the required tick that they agreed to get WhatsApp messages from
 *    Mobed Diary about prayers. The pen changes the name; a new number is a
 *    different person's, so it needs the tick again.
 *  - the fire temple's mobeds in the app: a cross only (their name and number are
 *    their own), shown when the panthaky may take them off.
 *  - Who replied STOP, or is switched off or waiting, says so: they are never
 *    asked by Mobed Diary, but Call and WhatsApp stay, since those are the
 *    panthaky's own phone and WhatsApp (a plain chat, nothing typed for them).
 *    For a mobed added by hand it says only "Cannot be asked on WhatsApp now",
 *    never whether their number has a Mobed Diary account, or its state.
 *
 * Joining needs the panthaky's confirmation (D10, owner 22 Nov 2026):
 *  - Joined, waiting for you: mobeds who chose this fire temple in Mobed Diary and
 *    get none of its prayer requests until confirmed, by name only (no number until
 *    then), with Confirm and Not one of ours.
 *  - Off the list, by name only, with Put back. They stay at the fire temple in Mobed Diary.
 *
 * Only that fire temple's confirmed panthakys (and the admin) see any of it.
 */

import { ourMobeds, addOurMobed, editOurMobed, removeOurMobed, startOurMobed, memberRequests } from "../api.js";
import { currentAgyary } from "../state.js";
import { chrome, mainEl, showFab, showError, showInfo, refreshHeader, loading, screenFailed, openSheet } from "../ui.js";
import { esc, phoneField, readPhone } from "../util.js";
import { navGuard } from "../router.js";
import { flagProblems } from "../fielderrors.js";
import { canPickContacts, pickContacts, fillFromContact } from "../behdin_add.js";

/** The server's words as a sentence: "cannot be ..." -> "Cannot be ...". */
const sentence = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : "");

const PEN = `<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false" width="22" height="22" fill="none"
  stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16v4z"/><path d="M13.5 6.5l4 4"/></svg>`;

/** Call and WhatsApp from the panthaky's own phone, as on a request
 *  (requests.js): the WhatsApp one opens a plain chat. Not on their own row. */
function reachHtml(m) {
  if (m.is_me || !m.phone) return "";
  const digits = String(m.phone).replace(/\D/g, "");
  // The row's overflow-wrap is for long names; a button's own word never breaks ("WhatsAp/p" at 375 px).
  return `<div class="row" style="margin-top:8px;overflow-wrap:normal">
      <a class="button secondary" href="tel:${esc(m.phone)}" aria-label="Call ${esc(m.name)}" style="white-space:nowrap">Call</a>
      <a class="button secondary" href="https://wa.me/${esc(digits)}" target="_blank" rel="noopener"
        aria-label="WhatsApp ${esc(m.name)}" style="white-space:nowrap">WhatsApp</a>
    </div>`;
}

function personHtml(m) {
  const lines = [];
  if (m.is_me) lines.push("You");
  else if (m.phone) lines.push(esc(m.phone));
  // For a mobed added by hand the server's words are whole ("cannot be asked on WhatsApp now"):
  // they never say whether the number has a Mobed Diary account, or its state.
  const state = m.stopped ? "Replied STOP: not asked on WhatsApp"
    : !m.can_message && !m.is_me ? (m.kind === "contact" ? sentence(m.why_not) : `Not asked: ${m.why_not}`) : "";
  const pen = m.kind === "contact" ? `<button type="button" class="row-edit" data-edit="${m.id}"
      aria-label="Edit ${esc(m.name)}" title="Edit">${PEN}</button>` : "";
  const cross = m.kind === "contact"
    ? `<button type="button" class="row-x" data-remove="${m.id}" aria-label="Take ${esc(m.name)} off the list"
      title="Take off the list">&times;</button>`
    : m.kind === "app" && m.may_take_off
      ? `<button type="button" class="row-x" data-takeoff="${m.id}" aria-label="Take ${esc(m.name)} off the list"
        title="Take off the list">&times;</button>` : "";
  return `<div class="search-result bh-row mb-row" data-key="${esc(m.key)}" style="overflow-wrap:anywhere;cursor:default">
      <div class="bh-av" aria-hidden="true">${esc((m.name || "?").trim().charAt(0).toUpperCase())}</div>
      <div class="bh-main"><div>${esc(m.name)}</div>
        ${lines.map(l => `<div class="addr">${l}</div>`).join("")}
        ${state ? `<div class="meta"><b>${esc(state)}</b></div>` : ""}
        ${m.stopped ? `<button type="button" class="secondary small" data-start="${esc(m.key)}"
          style="margin-top:8px">Turn WhatsApp back on</button>` : ""}
        ${reachHtml(m)}
      </div>
      ${pen}${cross}
    </div>`;
}

/** Someone not on the list for prayer requests (D10, 22 Nov 2026): a name, no number. */
function joinedHtml(p, buttons) {
  return `<div class="search-result bh-row" style="overflow-wrap:anywhere;cursor:default">
      <div class="bh-av" aria-hidden="true">${esc((p.name || "?").trim().charAt(0).toUpperCase())}</div>
      <div class="bh-main"><div>${esc(p.name)}</div>
        <div class="row" style="margin-top:8px">${buttons}</div></div>
    </div>`;
}

export async function renderMobeds() {
  chrome(true);
  refreshHeader();
  showFab(false);
  loading();
  const alive = navGuard();
  const agyary = currentAgyary();
  if (!agyary) return screenFailed("You are not at a fire temple yet.");
  let got;
  try {
    got = await ourMobeds(agyary.id);
  } catch (e) {
    if (!alive()) return;
    if (e.status === 404) return screenFailed("Only the panthaky of the fire temple can see its mobeds.");
    return screenFailed("Couldn't load your mobeds: " + e.message, renderMobeds);
  }
  if (!alive()) return;
  draw(agyary, got);
}

function draw(agyary, got) {
  const joined = got.joined || { waiting: [], off: [] };
  const temple = esc(got.agyari.name);
  // The fire temple's mobeds in the app first, then those added by hand.
  const all = [...got.mobeds.filter(m => m.kind === "app"), ...got.mobeds.filter(m => m.kind === "contact")];
  mainEl.innerHTML = `
    ${joined.waiting.length ? `<div class="card">
      <h2>Joined, waiting for you</h2>
      <p class="meta" style="margin:0 0 8px">Confirm the ones who are your mobeds. Only then do they get prayer
        requests from ${temple}.</p>
      ${joined.waiting.map(p => joinedHtml(p, `<button type="button" class="small" data-member="confirm"
          data-id="${p.id}">Confirm</button>
        <button type="button" class="ghost small" data-member="off" data-id="${p.id}">Not one of ours</button>`)).join("")}
    </div>` : ""}
    <div class="card">
      <div class="row tight" style="justify-content:space-between;align-items:center">
        <h2 style="margin:0">Mobeds</h2>
        <button class="icon-add" id="omAdd" title="Add a mobed" aria-label="Add a mobed">+</button>
      </div>
      <div style="margin-top:8px">
        ${all.length ? all.map(personHtml).join("") : `<p class="meta">No mobeds yet. Tap Add.</p>`}
      </div>
    </div>
    ${joined.off.length ? `<div class="card">
      <h2>Off the list</h2>
      ${joined.off.map(p => joinedHtml(p, `<button type="button" class="secondary small" data-member="on"
          data-id="${p.id}">Put back</button>`)).join("")}
    </div>` : ""}`;
  document.getElementById("omAdd").onclick = () => openForm(agyary, got, null);
  mainEl.querySelectorAll("[data-edit]").forEach(btn => {
    btn.onclick = () => openForm(agyary, got, got.mobeds.find(m => m.kind === "contact" && String(m.id) === btn.dataset.edit));
  });
  mainEl.querySelectorAll("[data-start]").forEach(btn => {
    btn.onclick = () => confirmStart(agyary, got.mobeds.find(m => m.key === btn.dataset.start));
  });
  mainEl.querySelectorAll("[data-remove]").forEach(btn => {
    btn.onclick = () => confirmRemove(agyary, got.mobeds.find(m => m.kind === "contact" && String(m.id) === btn.dataset.remove));
  });
  mainEl.querySelectorAll("[data-takeoff]").forEach(btn => {
    btn.onclick = () => confirmTakeOff(agyary, got, got.mobeds.find(m => m.kind === "app" && String(m.id) === btn.dataset.takeoff));
  });
  // Confirm, Not one of ours and Put back go at once: each can be undone on this page.
  mainEl.querySelectorAll("[data-member]").forEach(btn => {
    btn.onclick = () => member(agyary, Number(btn.dataset.id), btn.dataset.member, btn);
  });
}

/** Confirm ("confirm"), off the list ("off") or Put back ("on"); the page comes back drawn
 *  again, and the server's words say what happened. `btn` is off while it goes. */
async function member(agyary, userId, what, btn) {
  if (btn.disabled) return;
  btn.disabled = true;
  let res;
  try {
    res = await memberRequests(agyary.id, userId, what);
  } catch (e) {
    btn.disabled = false;
    return showError(e.message);
  }
  draw(agyary, res);
  showInfo(res.done.message);
}

/** Turn WhatsApp back on for someone who replied STOP (owner, 24 Nov 2026): the panthaky's call, since they
 *  asked. The person can reply STOP again any time. */
function confirmStart(agyary, m) {
  if (!m) return;
  const sheet = openSheet({
    title: `Turn WhatsApp back on for ${m.name}?`,
    html: `<p class="meta" style="margin-top:0">They replied STOP before. Turn it back on only if they have asked
        you to. They can reply STOP again any time.</p>
      <div class="stack" style="margin-top:12px">
        <button type="button" data-yes>Yes, turn it on</button>
        <button type="button" class="ghost" data-no>Cancel</button>
      </div>`,
  });
  sheet.body.querySelector("[data-no]").onclick = sheet.close;
  sheet.body.querySelector("[data-yes]").onclick = async (ev) => {
    ev.currentTarget.disabled = true;
    let res;
    try {
      res = await startOurMobed(agyary.id, m.key);
    } catch (e) {
      sheet.close();
      return showError(e.message);
    }
    sheet.close();
    draw(agyary, res);
    showInfo(res.done.message);
  };
}

function confirmTakeOff(agyary, got, m) {
  if (!m) return;
  const sheet = openSheet({
    title: `Take ${m.name} off the list?`,
    html: `<p class="meta" style="margin-top:0">They will not get prayer requests from ${esc(got.agyari.name)}. If they
        hold a place, it opens again and the next on the waiting list is asked. You can put them back later.</p>
      <div class="stack" style="margin-top:12px">
        <button type="button" class="danger" data-yes>Take off</button>
        <button type="button" class="ghost" data-no>Keep them</button>
      </div>`,
  });
  sheet.body.querySelector("[data-no]").onclick = sheet.close;
  sheet.body.querySelector("[data-yes]").onclick = async (ev) => {
    ev.currentTarget.disabled = true;
    let res;
    try {
      res = await memberRequests(agyary.id, m.id, "off");
    } catch (e) {
      sheet.close();
      return showError(e.message);
    }
    sheet.close();
    draw(agyary, res);
    showInfo(res.done.message);
  };
}

/** Add a mobed (`existing` null) or change one added by hand (the pen). Same sheet: Import from
 *  contacts, name, number, and the tick that they agreed, which an edit asks for only when the
 *  number is a new one (a new number is a different person's). */
function openForm(agyary, got, existing) {
  const editing = !!existing;
  const sheet = openSheet({
    title: editing ? "Edit mobed" : "Add a mobed",
    html: `
      ${canPickContacts() ? `<button type="button" class="secondary" id="omImport" style="margin-bottom:12px">
        Import from contacts</button>` : ""}
      <label for="omName">Name</label>
      <input type="text" id="omName" maxlength="60" autocomplete="off" placeholder="e.g. Er. Jehangir Mistry"
        value="${editing ? esc(existing.name) : ""}">
      <label for="omPhone">WhatsApp number</label>
      ${phoneField("omPhone", editing ? existing.phone : "")}
      <div class="check-row ${editing ? "hidden" : ""}" id="omTickRow"><input type="checkbox" id="omTick">
        <label for="omTick">${esc(got.consent_words)}</label></div>
      <p class="meta" data-msg role="alert" style="margin:6px 0 0"></p>
      <div class="stack" style="margin-top:12px">
        <button type="button" data-yes>${editing ? "Save" : "Add"}</button>
        <button type="button" class="ghost" data-no>Cancel</button>
      </div>`,
  });
  const body = sheet.body;
  body.querySelector("[data-no]").onclick = sheet.close;
  const tickRow = body.querySelector("#omTickRow");
  // Editing: the tick shows once the number is not the one on the list.
  const numberChanged = () => editing && readPhone("omPhone") !== existing.phone;
  if (editing) {
    body.addEventListener("input", () => { tickRow.classList.toggle("hidden", !numberChanged()); });
  }
  const imp = body.querySelector("#omImport");
  if (imp) {
    imp.onclick = async () => {
      const [contact] = await pickContacts({ multiple: false });
      if (contact) {
        fillFromContact(contact, { nameId: "omName", phoneId: "omPhone" });
        if (editing) tickRow.classList.toggle("hidden", !numberChanged());
      }
    };
  }
  body.querySelector("[data-yes]").onclick = async (ev) => {
    const btn = ev.currentTarget;
    if (btn.disabled) return;
    body.querySelector("[data-msg]").textContent = "";
    const name = body.querySelector("#omName").value.trim();
    const phone = readPhone("omPhone");
    const needsTick = !editing || numberChanged();
    const agreed = body.querySelector("#omTick").checked;
    const problems = [];
    if (!name) problems.push({ target: "#omName", message: "Please enter the mobed's name." });
    if (!phone) problems.push({ target: ".phone-field", message: "Please enter a valid WhatsApp number." });
    if (needsTick && !agreed) problems.push({ target: "#omTickRow", message: "Please tick this first: they must have agreed." });
    if (problems.length) return flagProblems(body, problems);
    btn.disabled = true;
    let res;
    try {
      res = editing
        ? await editOurMobed(agyary.id, existing.id, name, phone, needsTick && agreed)
        : await addOurMobed(agyary.id, name, phone, true);
    } catch (e) {
      btn.disabled = false;
      const target = { name: "#omName", phone: ".phone-field", agreed: "#omTickRow" }[e.field];
      if (target) return flagProblems(body, [{ target, message: e.message }]);
      body.querySelector("[data-msg]").textContent = e.status === 422
        ? "Please check the WhatsApp number." : e.message;
      return;
    }
    sheet.close();
    draw(agyary, res);
    showInfo(editing ? (res.done ? res.done.message : "Saved.") : `${name} is on your list.`);
  };
}

function confirmRemove(agyary, m) {
  if (!m) return;
  const sheet = openSheet({
    title: `Take ${m.name} off the list?`,
    html: `<p class="meta" style="margin-top:0">They will not be asked on WhatsApp any more. If they hold a place, it
        opens again and the next on the waiting list is asked. You can add them again later.</p>
      <div class="stack" style="margin-top:12px">
        <button type="button" class="danger" data-yes>Remove</button>
        <button type="button" class="ghost" data-no>Keep them</button>
      </div>`,
  });
  sheet.body.querySelector("[data-no]").onclick = sheet.close;
  sheet.body.querySelector("[data-yes]").onclick = async (ev) => {
    ev.currentTarget.disabled = true;
    let res;
    try {
      res = await removeOurMobed(agyary.id, m.id);
    } catch (e) {
      sheet.close();
      return showError(e.message);
    }
    sheet.close();
    draw(agyary, res);
    // With a place they held freed, the server says so (D10, 22 Nov 2026).
    showInfo(res.done ? res.done.message : `${m.name} is off the list.`);
  };
}
