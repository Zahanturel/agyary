"use strict";

/**
 * "Our mobeds" (DECISIONS D10, Phase 2 Step 5c): the fire temple's own list of
 * mobeds that a confirmed panthaky can ask on WhatsApp whether they can pray.
 * Reached from Settings and from the call-out screen.
 *
 *  - The fire temple's mobeds in the app are on it already (their number is not
 *    shown). Mobeds added by hand show their number, who added them and when.
 *  - Adding one: name and number (with Import from contacts, as on the Add
 *    behdin form, where the phone allows it) and the required tick that they
 *    agreed to get WhatsApp messages from Mobed Diary about prayers.
 *  - Who replied STOP, or is switched off, says so: they are never asked.
 *  - Remove takes a hand-added mobed off the list.
 *
 * Only that fire temple's confirmed panthakys (and the admin) see any of it.
 */

import { ourMobeds, addOurMobed, removeOurMobed } from "../api.js";
import { currentAgyary } from "../state.js";
import { chrome, mainEl, showFab, showError, showInfo, refreshHeader, loading, screenFailed, openSheet } from "../ui.js";
import { esc, phoneField, readPhone } from "../util.js";
import { navGuard } from "../router.js";
import { flagProblems } from "../fielderrors.js";
import { canPickContacts, pickContacts, fillFromContact } from "../behdin_add.js";

function personHtml(m) {
  const lines = [];
  if (m.kind === "app") lines.push(m.is_me ? "You" : "Uses Mobed Diary");
  else {
    lines.push(esc(m.phone));
    if (m.added_by) lines.push(`Added by ${esc(m.added_by)}`);
  }
  const state = m.stopped ? "Replied STOP: not asked on WhatsApp"
    : !m.can_message && !m.is_me ? `Not asked: ${m.why_not}` : "";
  return `<div class="search-result" data-key="${esc(m.key)}" style="overflow-wrap:anywhere">
      <strong>${esc(m.name)}</strong>
      ${lines.map(l => `<div class="addr">${l}</div>`).join("")}
      ${state ? `<div class="meta"><b>${esc(state)}</b></div>` : ""}
      ${m.kind === "contact" ? `<button type="button" class="ghost small" data-remove="${m.id}"
        style="margin-top:6px">Remove</button>` : ""}
    </div>`;
}

export async function renderOurMobeds() {
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
    if (e.status === 404) return screenFailed("Only the panthaky of the fire temple can see its list of mobeds.");
    return screenFailed("Couldn't load your mobeds: " + e.message, renderOurMobeds);
  }
  if (!alive()) return;
  draw(agyary, got);
}

function draw(agyary, got) {
  const app = got.mobeds.filter(m => m.kind === "app");
  const added = got.mobeds.filter(m => m.kind === "contact");
  mainEl.innerHTML = `
    <h2 style="margin:0 0 4px">Our mobeds</h2>
    <p class="meta" style="margin:0 0 12px">The mobeds of ${esc(got.agyari.name)} you can ask on WhatsApp whether
      they can pray, when a Doongerwadi's request is accepted. Only the panthaky sees this list.</p>
    ${got.whatsapp.on ? "" : `<div class="card"><p class="meta" style="margin:0">${esc(got.whatsapp.why_not)}
      You can build the list now.</p></div>`}
    <div class="card">
      <h2>In Mobed Diary</h2>
      ${app.length ? app.map(personHtml).join("") : `<p class="meta" style="margin:0">Nobody else here uses Mobed Diary yet.</p>`}
    </div>
    <div class="card">
      <h2>Added by hand</h2>
      ${added.length ? added.map(personHtml).join("") : `<p class="meta" style="margin:0">Nobody yet.</p>`}
      <div class="action-bar"><button type="button" id="omAdd">Add a mobed</button></div>
    </div>`;
  document.getElementById("omAdd").onclick = () => openAdd(agyary, got);
  mainEl.querySelectorAll("[data-remove]").forEach(btn => {
    btn.onclick = () => confirmRemove(agyary, got.mobeds.find(m => m.kind === "contact" && String(m.id) === btn.dataset.remove));
  });
}

function openAdd(agyary, got) {
  const sheet = openSheet({
    title: "Add a mobed",
    html: `
      ${canPickContacts() ? `<button type="button" class="secondary" id="omImport" style="margin-bottom:12px">
        Import from contacts</button>` : ""}
      <label for="omName">Name</label>
      <input type="text" id="omName" maxlength="60" autocomplete="off" placeholder="e.g. Er. Rustom Dastur">
      <label for="omPhone">WhatsApp number</label>
      ${phoneField("omPhone", "")}
      <div class="check-row" id="omTickRow"><input type="checkbox" id="omTick">
        <label for="omTick">${esc(got.consent_words)}</label></div>
      <p class="meta" data-msg role="alert" style="margin:6px 0 0"></p>
      <div class="stack" style="margin-top:12px">
        <button type="button" data-yes>Add</button>
        <button type="button" class="ghost" data-no>Cancel</button>
      </div>`,
  });
  const body = sheet.body;
  body.querySelector("[data-no]").onclick = sheet.close;
  const imp = body.querySelector("#omImport");
  if (imp) {
    imp.onclick = async () => {
      const [contact] = await pickContacts({ multiple: false });
      if (contact) fillFromContact(contact, { nameId: "omName", phoneId: "omPhone" });
    };
  }
  body.querySelector("[data-yes]").onclick = async (ev) => {
    const btn = ev.currentTarget;
    if (btn.disabled) return;
    body.querySelector("[data-msg]").textContent = "";
    const name = body.querySelector("#omName").value.trim();
    const phone = readPhone("omPhone");
    const agreed = body.querySelector("#omTick").checked;
    const problems = [];
    if (!name) problems.push({ target: "#omName", message: "Please enter the mobed's name." });
    if (!phone) problems.push({ target: ".phone-field", message: "Please enter a valid WhatsApp number." });
    if (!agreed) problems.push({ target: "#omTickRow", message: "Please tick this first: they must have agreed." });
    if (problems.length) return flagProblems(body, problems);
    btn.disabled = true;
    let res;
    try {
      res = await addOurMobed(agyary.id, name, phone, true);
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
    showInfo(`${name} is on your list.`);
  };
}

function confirmRemove(agyary, m) {
  if (!m) return;
  const sheet = openSheet({
    title: `Take ${m.name} off the list?`,
    html: `<p class="meta" style="margin-top:0">They will not be asked on WhatsApp any more. You can add them again later.</p>
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
    showInfo(`${m.name} is off the list.`);
  };
}
