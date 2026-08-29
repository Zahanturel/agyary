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
  listBehdins, customerHistory, getBehdin, updateBehdin, createBehdin,
  getSavedNames, putSavedNames,
} from "../api.js";
import { state } from "../state.js";
import { canPickContacts, pickContacts } from "../behdin_add.js";
import { renderNamesEditor, collectNames, validateNames } from "../names.js";
import {
  chrome, mainEl, showFab, showError, showInfo,
  refreshHeader, loading, backBar, wireAll,
} from "../ui.js";
import { esc, phoneField, readPhone, setPhoneField } from "../util.js";
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

  document.getElementById("bhAdd").onclick = () => navigate("#/behdins/new");
}

/**
 * Adding a behdin is the same page as looking at one, minus the history
 * nobody has yet. It used to be a cramped name-and-number panel that, once
 * saved, threw you onto this very layout to do the saved names - two
 * screens and two saves for one person. Now it is one screen and one save,
 * and importing from the phone's own contacts sits where you would look
 * for it rather than one step earlier.
 */
export function renderBehdinNew() {
  chrome(true);
  refreshHeader();
  showFab(false);

  // Read once, up front - a fresh visit to this same URL later (Settings)
  // must not accidentally inherit a stale flag from an earlier detour.
  const returnToEvent = state.behdinReturnTo === "event";
  const prefillName = state.behdinPrefillName || "";
  state.behdinReturnTo = null;
  state.behdinPrefillName = null;
  const backTarget = returnToEvent ? "#/event/new" : "#/behdins";

  mainEl.innerHTML = `
    <div class="card">
      ${backBar("New behdin", backTarget)}
      ${canPickContacts() ? `
        <button class="secondary" id="bnImport" style="margin-bottom:12px">
          Import from contacts
        </button>` : ""}
      <label>Name</label>
      <input type="text" id="bnName" placeholder="e.g. Behdin Jaidev Mistry"
             autocomplete="off" value="${esc(prefillName)}">
      <label>WhatsApp number</label>${phoneField("bnPhone")}
    </div>

    <div class="card">
      <h2>Saved names</h2>
      <p class="meta">Reused whenever this behdin books - here or over
        WhatsApp. Leave it for later if you don't have them to hand.</p>
      <div id="savedRegion"></div>
    </div>

    <div class="wizard-nav" style="margin-top:4px">
      <button class="ghost" id="bnCancel">Cancel</button>
      <button id="bnSave">Add behdin</button>
    </div>`;

  wireAll("[data-back]", (el) => navigate(el.dataset.back));
  document.getElementById("bnCancel").onclick = () => navigate(backTarget);
  document.getElementById("bnName").focus();

  const region = document.getElementById("savedRegion");
  renderNamesEditor(region, false, "gujrela_nu", []);

  if (canPickContacts()) {
    document.getElementById("bnImport").onclick = async () => {
      const btn = document.getElementById("bnImport");
      const picked = await pickContacts();
      if (!picked.length) return;

      // One contact fills the form so the saved names below can be added in
      // the same pass. Several is a different intent - a bulk import - and
      // saved names make no sense per-person there.
      if (picked.length === 1) {
        document.getElementById("bnName").value = picked[0].name;
        setPhoneField("bnPhone", picked[0].phone);
        return;
      }
      btn.disabled = true;
      btn.textContent = "Importing...";
      let added = 0, skipped = 0;
      for (const c of picked) {
        try {
          const r = await createBehdin(state.currentAgyaryId, c.name, c.phone);
          r.created ? added++ : skipped++;
        } catch (e) { skipped++; }
      }
      showInfo(added
        ? `${added} behdin${added > 1 ? "s" : ""} added` + (skipped ? `, ${skipped} already on file` : "")
        : "All of those were already on file");
      // A batch has no single behdin to hand back to the event - land on
      // the same place either way, and the event flow's search will find
      // whichever of these he needs.
      navigate(backTarget);
    };
  }

  document.getElementById("bnSave").onclick = async () => {
    const name = document.getElementById("bnName").value.trim();
    const phone = readPhone("bnPhone");
    if (!name) return showError("Please enter the behdin's name.");
    if (!phone) return showError("Please enter a valid phone number.");

    const rows = collectNames(region, false, "gujrela_nu");
    // Check the names BEFORE creating anybody, or a bad pair leaves a
    // half-made behdin behind and the mobed retypes the lot.
    if (rows.length) {
      const problem = validateNames(rows);
      if (problem) return showError(problem);
    }

    const btn = document.getElementById("bnSave");
    btn.disabled = true;
    let created;
    try {
      created = await createBehdin(state.currentAgyaryId, name, phone);
    } catch (e) {
      btn.disabled = false;
      return showError(e.message);
    }
    if (!created.created && !returnToEvent) {
      showInfo(`${created.name} was already on file - opening their record.`);
    }

    // Back to the event with this behdin chosen, rather than their own
    // record - that record has nothing to do with the ceremony being booked.
    const landing = () => {
      if (returnToEvent && state.draft) {
        state.draft.behdin = { id: created.id, name: created.name, phone: created.phone };
        navigate("#/event/new");
      } else {
        navigate(`#/behdins/${created.id}`);
      }
    };

    if (rows.length) {
      try {
        await putSavedNames(state.currentAgyaryId, created.id, "pair",
                            rows.filter(n => n.section === "pair"));
        await putSavedNames(state.currentAgyaryId, created.id, "farmayeshne",
                            rows.filter(n => n.section === "farmayeshne"));
      } catch (e) {
        // The behdin exists either way - say so rather than losing them.
        landing();
        return showError(`${created.name} was added, but the names didn't save: ${e.message}`);
      }
    }
    landing();
  };
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
