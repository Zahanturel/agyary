"use strict";

/**
 * Behdins. One screen, two depths of access:
 *   - a plain mobed sees the people they have personally booked for, and
 *     their history with each (unchanged behaviour);
 *   - a panthaky/caretaker can also register someone new and correct any
 *     of the fire temple's behdin records.
 *
 * The saved-names editor here is the same component the New Event wizard
 * uses, pointed at the same rows the WhatsApp flows read and write.
 */

import {
  searchCustomers, listBehdins, customerHistory, getBehdin, createBehdin,
  updateBehdin, getSavedNames, putSavedNames,
} from "../api.js";
import { state, isManager } from "../state.js";
import { renderNamesEditor, collectNames, validateNames } from "../names.js";
import {
  chrome, mainEl, showFab, showError, showInfo, markActiveTab, refreshHeader,
  loading, backBar, wireAll,
} from "../ui.js";
import { esc, phoneField, readPhone } from "../util.js";
import { navigate } from "../router.js";

export async function renderBehdinList() {
  chrome(true);
  refreshHeader();
  markActiveTab("#/behdins");
  showFab(false);
  loading();

  // Two different questions, and which one you get depends on your role:
  // management sees the temple's whole register (including people who have
  // never booked); a mobed sees the people they have personally booked for.
  const load = (q) => isManager()
    ? listBehdins(state.currentAgyaryId, q).then(rows =>
        rows.map(r => ({ customer_id: r.id, name: r.name, phone: r.phone })))
    : searchCustomers(q);

  let rows = [];
  try { rows = await load(""); }
  catch (e) { mainEl.innerHTML = ""; return showError(e.message); }

  mainEl.innerHTML = `
    <div class="card">
      <div class="row tight" style="justify-content:space-between;align-items:center">
        <h2 style="margin:0">Behdins</h2>
        ${isManager() ? '<button class="small" id="bhAdd">+ Add</button>' : ""}
      </div>
      <p class="meta">${isManager()
        ? "Everyone on file at this fire temple."
        : "The behdins you have personally booked for, most recent first."}</p>
      <input type="text" id="bhFilter" placeholder="Search by name or phone" autocomplete="off">
      <div id="bhAddPanel"></div>
      <div id="bhRows" style="margin-top:8px"></div>
    </div>`;

  const rowsEl = document.getElementById("bhRows");
  const paint = (list) => {
    rowsEl.innerHTML = list.length
      ? list.map(c => `<div class="search-result" data-cid="${c.customer_id}">
          <div>${esc(c.name)}</div><div class="addr">${esc(c.phone)}</div></div>`).join("")
      : `<p class="meta">No behdins yet - they'll appear here once you book for someone.</p>`;
    rowsEl.querySelectorAll("[data-cid]").forEach(el => {
      el.onclick = () => navigate(`#/behdins/${el.dataset.cid}`);
    });
  };
  paint(rows);

  let timer, token = 0;
  document.getElementById("bhFilter").oninput = (e) => {
    clearTimeout(timer);
    const q = e.target.value.trim();
    timer = setTimeout(async () => {
      const mine = ++token;
      try {
        const found = await load(q);
        if (mine === token) paint(found);
      } catch (err) { /* keep the last good list */ }
    }, 220);
  };

  const add = document.getElementById("bhAdd");
  if (add) add.onclick = () => renderAddPanel();
}

function renderAddPanel() {
  const panel = document.getElementById("bhAddPanel");
  panel.innerHTML = `
    <div class="card" style="margin-top:12px">
      <label>Name</label><input type="text" id="nbName" placeholder="e.g. Behdin Jaidev Mistry">
      <label>WhatsApp number</label>${phoneField("nbPhone")}
      <div class="row tight" style="margin-top:12px">
        <button class="small" id="nbSave">Add behdin</button>
        <button class="ghost small" id="nbCancel">Cancel</button>
      </div>
    </div>`;
  document.getElementById("nbCancel").onclick = () => { panel.innerHTML = ""; };
  document.getElementById("nbSave").onclick = async () => {
    const name = document.getElementById("nbName").value.trim();
    const phone = readPhone("nbPhone");
    if (!name) return showError("Please enter the behdin's name.");
    if (!phone) return showError("Please enter a valid phone number.");
    try {
      const created = await createBehdin(state.currentAgyaryId, name, phone);
      navigate(`#/behdins/${created.id}`);
    } catch (e) {
      showError(e.message);
    }
  };
}

export async function renderBehdinDetail({ id }) {
  chrome(true);
  refreshHeader();
  markActiveTab("#/behdins");
  showFab(false);
  loading();

  const aid = state.currentAgyaryId;
  const cid = Number(id);
  const manage = isManager();

  let record = null, history = null, saved = [];
  try {
    // History is the mobed-scoped view and exists for everyone; the record
    // and saved names are agyari-scoped and are what management edits.
    [record, history, saved] = await Promise.all([
      getBehdin(aid, cid).catch(() => null),
      customerHistory(cid).catch(() => null),
      getSavedNames(aid, cid).catch(() => []),
    ]);
  } catch (e) {
    mainEl.innerHTML = "";
    return showError(e.message);
  }
  if (!record && !history) {
    mainEl.innerHTML = "";
    return showError("That behdin isn't on file at this fire temple.");
  }

  const name = (record && record.name) || (history && history.name) || "";
  const phone = (record && record.phone) || (history && history.phone) || "";

  mainEl.innerHTML = `
    <div class="card">
      ${backBar(esc(name), "#/behdins")}
      ${manage && record ? `
        <label>Name</label><input type="text" id="bdName" value="${esc(name)}">
        <label>WhatsApp number</label>${phoneField("bdPhone", phone)}
        <div style="margin-top:12px"><button class="small" id="bdSave">Save details</button></div>
      ` : `<p class="meta">${esc(phone)}</p>`}
    </div>

    ${record ? `
    <div class="card">
      <h2>Saved names</h2>
      <p class="meta">Reused whenever this behdin books - here or over WhatsApp.</p>
      <div id="savedRegion"></div>
      <div style="margin-top:14px"><button class="small" id="bdSaveNames">Save names</button></div>
    </div>` : ""}

    <div class="card">
      <h2>History</h2>
      ${history && history.history.length ? history.history.map(h => `
        <div class="list-row"><div class="lr-main"><b>${esc(h.event)}</b><span>${esc(h.when)}</span></div></div>
      `).join("") : '<p class="meta">Nothing booked for this behdin yet.</p>'}
    </div>`;

  wireAll("[data-back]", (el) => navigate(el.dataset.back));

  if (manage && record) {
    document.getElementById("bdSave").onclick = async () => {
      const newName = document.getElementById("bdName").value.trim();
      const newPhone = readPhone("bdPhone");
      if (!newName) return showError("Name cannot be blank.");
      if (!newPhone) return showError("Please enter a valid phone number.");
      try {
        await updateBehdin(aid, cid, { name: newName, phone: newPhone });
        showInfo("Saved.");
        refreshHeader();
      } catch (e) {
        showError(e.message);
      }
    };
  }

  if (record) {
    // The same editor the New Event wizard uses. "Service" shape, because
    // the pool holds both pairs and farmayeshne singles regardless of what
    // any one ceremony will use them for.
    const region = document.getElementById("savedRegion");
    renderNamesEditor(region, false, "gujrela_nu", saved);
    document.getElementById("bdSaveNames").onclick = async () => {
      const rows = collectNames(region, false, "gujrela_nu");
      const problem = validateNames(rows);
      if (problem) return showError(problem);
      try {
        // Section-wholesale: the API replaces a section at a time, which is
        // also the level the "a pair is two names" rule lives at.
        await putSavedNames(aid, cid, "pair", rows.filter(n => n.section === "pair"));
        await putSavedNames(aid, cid, "farmayeshne", rows.filter(n => n.section === "farmayeshne"));
        showInfo("Saved names updated.");
      } catch (e) {
        showError(e.message);
      }
    };
  }
}
