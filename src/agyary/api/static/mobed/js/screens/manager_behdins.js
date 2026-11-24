"use strict";

/**
 * The funeral place's book of behdins (DECISIONS D10, changed 19 Nov 2026): the
 * families it deals with - a name, a number, and the fire temple they usually
 * go to. Private to that place: its managers, and the admin acting for it.
 *
 *  - The book: search by name or number, Add a family, tap one to change it or
 *    take it out (it is kept, turned off).
 *  - The form (a sheet): name and WhatsApp number, typed or "Import from
 *    contacts" (the phone's own contact list, as on Add behdin: contact import
 *    lives only inside a name-and-number form), and their usual fire temple,
 *    chosen from the fire temple search. Recording a death opens the same sheet
 *    to add a family on the spot (manager_record.js).
 */

import { managerBook, managerAddToBook, managerChangeInBook, managerRemoveFromBook, managerSearchAgyaries } from "../api.js";
import {
  chrome, mainEl, showFab, showError, showInfo, refreshHeader, loading, screenFailed, toTop, openSheet,
} from "../ui.js";
import { esc, phoneField, readPhone } from "../util.js";
import { navGuard } from "../router.js";
import { flagProblems } from "../fielderrors.js";
import { canPickContacts, pickContacts, fillFromContact } from "../behdin_add.js";
import { managerPlaces } from "../acting.js";

/** One family as a line: name, number, and their usual fire temple. */
export function familyLineHtml(b) {
  return `<div><strong>${esc(b.name)}</strong></div>
    <div class="addr">${esc(b.phone)}${b.usual_agyari ? ` · ${esc(b.usual_agyari.name)}` : ""}</div>`;
}

/** The usual fire temple: chosen (with "Not this one"), or a search. */
function paintAgyari(box, form, placeId) {
  if (form.place) {
    box.innerHTML = `<div class="search-result" style="cursor:default;min-height:0">
        <div><strong>${esc(form.place.name)}</strong></div><div class="addr">${esc(form.place.city || "")}</div></div>
      <button type="button" class="ghost small" data-clear>Not this one</button>`;
    box.querySelector("[data-clear]").onclick = () => { form.place = null; paintAgyari(box, form, placeId); };
    return;
  }
  box.innerHTML = `<input type="text" id="fbAgyari" placeholder="Search by name or town" autocomplete="off">
    <div data-results style="margin-top:8px"></div>`;
  const input = box.querySelector("#fbAgyari");
  const results = box.querySelector("[data-results]");
  let timer, token = 0;
  input.oninput = () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const q = input.value.trim();
      const mine = ++token;
      if (!q) { results.innerHTML = ""; return; }
      let found;
      try {
        found = (await managerSearchAgyaries(q, placeId)).agyaries;
      } catch (e) {
        if (mine === token) results.innerHTML = `<p class="meta" role="alert">${esc(e.message)}</p>`;
        return;
      }
      if (mine !== token || !box.isConnected) return;
      if (!found.length) { results.innerHTML = `<p class="meta">No fire temple found for “${esc(q)}”.</p>`; return; }
      results.innerHTML = found.map((a, i) => `<div class="search-result" data-i="${i}">
          <div><strong>${esc(a.name)}</strong></div><div class="addr">${esc(a.city || "")}</div></div>`).join("");
      results.querySelectorAll("[data-i]").forEach(row => {
        row.onclick = () => {
          const a = found[+row.dataset.i];
          form.place = { id: a.id, name: a.name, city: a.city };
          paintAgyari(box, form, placeId);
        };
      });
    }, 250);
  };
}

/**
 * Add a family to the book, or change one (`behdin`). `onSaved(behdin)` is
 * called with what the server kept; `onRemoved()` after "Take out of the book".
 */
export function openBehdinSheet({ behdin = null, prefill = null, placeId = null, onSaved, onRemoved = null } = {}) {
  placeId = behdin ? behdin.funeral_place_id : (placeId || (managerPlaces()[0] || {}).id || null);
  const start = behdin || prefill || {};
  const form = { place: behdin ? behdin.usual_agyari : null };
  const sheet = openSheet({
    title: behdin ? "Change the behdin" : "Add a behdin",
    html: `
      ${canPickContacts() ? `<button type="button" class="secondary" id="fbImport" style="margin-bottom:12px">
        Import from contacts</button>` : ""}
      <label for="fbName">Name</label>
      <input type="text" id="fbName" maxlength="100" autocomplete="off" placeholder="e.g. Zubin Mistry"
        value="${esc(start.name || "")}">
      <label for="fbPhone">WhatsApp number</label>
      ${phoneField("fbPhone", start.phone || "")}
      <label for="fbAgyari">Their usual fire temple <span class="meta">(optional)</span></label>
      <div id="fbAgyariBox"></div>
      <p class="meta" data-msg role="alert" style="margin:6px 0 0"></p>
      <div class="stack" style="margin-top:12px">
        <button type="button" data-yes>${behdin ? "Save" : "Add to the book"}</button>
        ${behdin ? `<button type="button" class="ghost" data-remove>Take out of the book</button>` : ""}
        <button type="button" class="ghost" data-no>Cancel</button>
      </div>`,
  });
  const body = sheet.body;
  paintAgyari(body.querySelector("#fbAgyariBox"), form, placeId);
  body.querySelector("[data-no]").onclick = sheet.close;
  const imp = body.querySelector("#fbImport");
  if (imp) {
    imp.onclick = async () => {
      const [contact] = await pickContacts({ multiple: false });
      if (contact) fillFromContact(contact, { nameId: "fbName", phoneId: "fbPhone" });
    };
  }
  const msg = body.querySelector("[data-msg]");
  body.querySelector("[data-yes]").onclick = async (ev) => {
    const btn = ev.currentTarget;
    if (btn.disabled) return;
    msg.textContent = "";
    const name = body.querySelector("#fbName").value.trim();
    const phone = readPhone("fbPhone");
    const problems = [];
    if (!name) problems.push({ target: "#fbName", message: "Please enter the behdin's name." });
    if (!phone) problems.push({ target: ".phone-field", message: "Please enter a valid WhatsApp number." });
    if (problems.length) return flagProblems(body, problems);
    btn.disabled = true;
    const payload = { name, phone, usual_agyary_id: form.place ? form.place.id : null };
    let res;
    try {
      res = behdin ? await managerChangeInBook(behdin.id, payload)
        : await managerAddToBook({ ...payload, funeral_place_id: placeId });
    } catch (e) {
      btn.disabled = false;
      const target = { name: "#fbName", phone: ".phone-field", usual_agyary_id: "#fbAgyariBox" }[e.field];
      if (target) return flagProblems(body, [{ target, message: e.message }]);
      msg.textContent = e.status === 422 ? "Please check the WhatsApp number." : e.message;
      return;
    }
    sheet.close();
    if (onSaved) onSaved(res.behdin);
  };
  const remove = body.querySelector("[data-remove]");
  if (remove) {
    remove.onclick = async () => {
      if (remove.dataset.sure !== "1") {
        remove.dataset.sure = "1";
        remove.textContent = "Yes, take them out";
        remove.classList.add("danger");
        msg.textContent = "Deaths already recorded keep their family contact.";
        return;
      }
      remove.disabled = true;
      try {
        await managerRemoveFromBook(behdin.id);
      } catch (e) {
        remove.disabled = false;
        msg.textContent = e.message;
        return;
      }
      sheet.close();
      if (onRemoved) onRemoved();
    };
  }
}

export async function renderManagerBehdins() {
  chrome(true);
  refreshHeader();
  showFab(false);
  loading();
  const alive = navGuard();
  let first;
  try {
    first = await managerBook("");
  } catch (e) {
    if (!alive()) return;
    return screenFailed("Couldn't open the book: " + e.message, renderManagerBehdins);
  }
  if (!alive()) return;
  mainEl.innerHTML = `
    <div class="card">
      <h2>Book of behdins</h2>
      <p class="meta" style="margin:0 0 10px">The behdins you deal with, and the fire temple each usually goes to.
        Only your place sees this book. When you record a death, choose the behdin from here.</p>
      <input type="text" id="mbSearch" placeholder="Search by name or number" autocomplete="off">
      <div id="mbList" style="margin-top:8px"></div>
      <div class="action-bar"><button type="button" id="mbAdd">Add a behdin</button></div>
    </div>`;
  toTop();
  const list = document.getElementById("mbList");
  const input = document.getElementById("mbSearch");
  const paint = (got, q) => {
    if (!got.behdins.length) {
      list.innerHTML = `<p class="meta" style="margin:0">${q ? `Nobody found for “${esc(q)}”.`
        : "Nobody yet. Tap Add a behdin."}</p>`;
      return;
    }
    list.innerHTML = got.behdins.map((b, i) => `<div class="search-result" data-i="${i}">${familyLineHtml(b)}</div>`).join("")
      + (got.more ? `<p class="meta" style="margin:6px 0 0">Search to find others.</p>` : "");
    list.querySelectorAll("[data-i]").forEach(row => {
      row.onclick = () => openBehdinSheet({
        behdin: got.behdins[+row.dataset.i],
        onSaved: (b) => { showInfo(`Saved ${b.name}.`); reload(); },
        onRemoved: () => { showInfo("Taken out of the book."); reload(); },
      });
    });
  };
  let timer, token = 0;
  const reload = async () => {
    const q = input.value.trim();
    const mine = ++token;
    let got;
    try {
      got = await managerBook(q);
    } catch (e) {
      if (mine === token) showError(e.message);
      return;
    }
    if (mine === token && alive()) paint(got, q);
  };
  paint(first, "");
  input.oninput = () => { clearTimeout(timer); timer = setTimeout(reload, 250); };
  document.getElementById("mbAdd").onclick = () => openBehdinSheet({
    onSaved: (b) => { showInfo(`${b.name} is in the book.`); input.value = ""; reload(); },
  });
}
