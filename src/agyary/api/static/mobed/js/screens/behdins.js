"use strict";

/**
 * Behdins - the fire temple's register of the people it prays for.
 *
 * Adding, viewing and correcting a behdin are open to any member. That
 * matches the API (all three ask only for membership) and matches who
 * actually does the work: the mobed taking a walk-in at the counter is
 * usually the one holding the phone number. The management-only parts of
 * this app are invites, the temple's own details, and its service catalog
 * - not this.
 *
 * The saved-names editor here is the same component the New Event wizard
 * uses, pointed at the same rows the WhatsApp flows read and write.
 */

import {
  listBehdins, customerHistory, getBehdin, updateBehdin,
  getSavedNames, putSavedNames,
} from "../api.js";
import { state } from "../state.js";
import { renderAddBehdin } from "../behdin_add.js";
import { renderNamesEditor, collectNames, validateNames } from "../names.js";
import {
  chrome, mainEl, showFab, showError, showInfo, markActiveTab,
  refreshHeader, loading, backBar, wireAll,
} from "../ui.js";
import { esc, phoneField, readPhone } from "../util.js";
import { navigate } from "../router.js";

export async function renderBehdinList() {
  chrome(true);
  refreshHeader();
  markActiveTab("#/behdins");
  // The FAB is the add affordance on this screen, the same way it is on
  // the calendar - so "add someone" is reachable without reading the page.
  showFab(true, "Add a behdin", () => openAddPanel());
  loading();

  let rows = [];
  try {
    rows = await listBehdins(state.currentAgyaryId, "");
  } catch (e) {
    mainEl.innerHTML = "";
    return showError(e.message);
  }

  mainEl.innerHTML = `
    <div class="card">
      <div class="row tight" style="justify-content:space-between;align-items:center">
        <h2 style="margin:0">Behdins</h2>
        <button class="small" id="bhAdd">+ Add behdin</button>
      </div>
      <p class="meta">Everyone on file at this fire temple.</p>
      <input type="text" id="bhFilter" placeholder="Search by name or phone" autocomplete="off">
      <div id="bhAddPanel"></div>
      <div id="bhRows" style="margin-top:8px"></div>
    </div>`;

  const rowsEl = document.getElementById("bhRows");
  const paint = (list) => {
    rowsEl.innerHTML = list.length
      ? list.map(c => `<div class="search-result" data-cid="${c.id}">
          <div>${esc(c.name)}</div><div class="addr">${esc(c.phone)}</div></div>`).join("")
      : `<p class="meta">Nobody here yet - add the first behdin above.</p>`;
    rowsEl.querySelectorAll("[data-cid]").forEach(el => {
      el.onclick = () => navigate(`#/behdins/${el.dataset.cid}`);
    });
  };
  paint(rows);

  let timer, token = 0;
  const filterEl = document.getElementById("bhFilter");
  filterEl.oninput = () => {
    clearTimeout(timer);
    const q = filterEl.value.trim();
    timer = setTimeout(async () => {
      const mine = ++token;
      try {
        const found = await listBehdins(state.currentAgyaryId, q);
        if (mine === token) paint(found);
      } catch (err) { /* keep the last good list */ }
    }, 220);
  };

  document.getElementById("bhAdd").onclick = () => openAddPanel();
}

function openAddPanel() {
  const panel = document.getElementById("bhAddPanel");
  // Reachable from the FAB too, which can be tapped from anywhere on the
  // page - so scroll the form into view rather than opening it off-screen.
  if (!panel) return navigate("#/behdins");
  renderAddBehdin(panel, {
    onCreated: (behdin) => navigate(`#/behdins/${behdin.id}`),
  });
  panel.scrollIntoView({ block: "nearest" });
}

export async function renderBehdinDetail({ id }) {
  chrome(true);
  refreshHeader();
  markActiveTab("#/behdins");
  showFab(false);
  loading();

  const aid = state.currentAgyaryId;
  const cid = Number(id);

  let record = null, history = null, saved = [];
  try {
    [record, history, saved] = await Promise.all([
      getBehdin(aid, cid).catch(() => null),
      // History is scoped to what THIS mobed entered, so it can legitimately
      // be empty for a behdin someone else booked for.
      customerHistory(cid).catch(() => null),
      getSavedNames(aid, cid).catch(() => []),
    ]);
  } catch (e) {
    mainEl.innerHTML = "";
    return showError(e.message);
  }
  if (!record) {
    mainEl.innerHTML = "";
    return showError("That behdin isn't on file at this fire temple.");
  }

  mainEl.innerHTML = `
    <div class="card">
      ${backBar(esc(record.name), "#/behdins")}
      <label>Name</label><input type="text" id="bdName" value="${esc(record.name)}">
      <label>WhatsApp number</label>${phoneField("bdPhone", record.phone)}
      <div style="margin-top:12px"><button class="small" id="bdSave">Save details</button></div>
    </div>

    <div class="card">
      <h2>Saved names</h2>
      <p class="meta">Reused whenever this behdin books - here or over WhatsApp.</p>
      <div id="savedRegion"></div>
      <div style="margin-top:14px"><button class="small" id="bdSaveNames">Save names</button></div>
    </div>

    <div class="card">
      <h2>History</h2>
      ${history && history.history.length ? history.history.map(h => `
        <div class="list-row"><div class="lr-main"><b>${esc(h.event)}</b><span>${esc(h.when)}</span></div></div>
      `).join("") : '<p class="meta">Nothing you have booked for this behdin yet.</p>'}
    </div>`;

  wireAll("[data-back]", (el) => navigate(el.dataset.back));

  document.getElementById("bdSave").onclick = async () => {
    const name = document.getElementById("bdName").value.trim();
    const phone = readPhone("bdPhone");
    if (!name) return showError("Name cannot be blank.");
    if (!phone) return showError("Please enter a valid phone number.");
    try {
      await updateBehdin(aid, cid, { name, phone });
      showInfo("Saved.");
    } catch (e) {
      showError(e.message);
    }
  };

  // The same editor the New Event wizard uses. Rendered in "service" shape
  // because the pool holds both pairs and farmayeshne singles, whatever any
  // one ceremony ends up using them for.
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
