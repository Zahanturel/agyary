"use strict";

/**
 * Behdins - THIS mobed's own book, not the fire temple's register.
 *
 * A behdin's name and phone number are their own. A colleague at the same
 * fire temple has no business reading them, so every read here is scoped
 * server-side to the signed-in mobed; this screen could not show someone
 * else's behdins even if it tried.
 *
 * Adding, viewing and correcting are open to any member - the mobed taking
 * a walk-in at the counter is the one holding the phone number.
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
  chrome, mainEl, showFab, showError, showInfo,
  refreshHeader, loading, backBar, wireAll,
} from "../ui.js";
import { esc, phoneField, readPhone } from "../util.js";
import { navigate } from "../router.js";

export async function renderBehdinList() {
  chrome(true);
  refreshHeader();
  // Exactly one add control on this screen: the icon in the header below.
  // No floating button as well.
  showFab(false);
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
        <button class="icon-add" id="bhAdd" title="Add a behdin" aria-label="Add a behdin">+</button>
      </div>
      <p class="meta">The behdins you look after.</p>
      <input type="text" id="bhFilter" placeholder="Search by name or phone" autocomplete="off">
      <div id="bhAddPanel"></div>
      <div id="bhRows" style="margin-top:8px"></div>
    </div>`;

  const rowsEl = document.getElementById("bhRows");
  const paint = (list) => {
    rowsEl.innerHTML = list.length
      ? list.map(c => `<div class="search-result" data-cid="${c.id}">
          <div>${esc(c.name)}</div><div class="addr">${esc(c.phone)}</div></div>`).join("")
      : `<p class="meta">No behdins yet - add one above, or they appear here when you book for them.</p>`;
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
  const typed = (document.getElementById("bhFilter") || {}).value || "";
  renderAddBehdin(panel, {
    prefill: { name: typed.trim() },
    onCreated: (behdin) => navigate(`#/behdins/${behdin.id}`),
  });
  panel.scrollIntoView({ block: "nearest" });
}

export async function renderBehdinDetail({ id }) {
  chrome(true);
  refreshHeader();
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
      <p class="meta" style="margin-top:6px">
        <a class="tel" href="tel:${esc(record.phone)}">Call ${esc(record.phone)}</a></p>
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
