"use strict";

/**
 * Add / edit a machi — one screen.
 *
 * Behdin, purpose (patet/tandarosti), date with Roj/Mah sync, geh picker
 * with live availability, names inline (one pair for patet, multiple
 * singles for tandarosti).
 */

import {
  listBehdins, convertDate, fromParsi, bookableGehs,
  addMachi, machiDetail, editMachi,
} from "../api.js";
import { state, primarySystem, GEHS, GEH_NAME_BY_NUM, NAME_TITLES, TITLE_DISPLAY } from "../state.js";
import { renderAddBehdin } from "../behdin_add.js";
import { chrome, mainEl, showFab, showError, refreshHeader, loading } from "../ui.js";
import { esc, todayIst } from "../util.js";
import { navigate } from "../router.js";

function system() {
  return primarySystem();
}

function blankDraft(prefill = {}) {
  return {
    edit: null,
    behdin: null,
    purpose: "patet",
    gregorian: prefill.gregorian || todayIst(),
    roj: prefill.roj || null,
    mah: prefill.mah || null,
    year: prefill.year || null,
    geh: prefill.geh || null,
    parsiLabel: "",
    isGatha: false,
    availableGehs: [],
    names: null,
    recurring: false,
  };
}

function defaultNames(purpose) {
  if (purpose === "patet") {
    return [
      { section: "pair", title: "ervad", name: "", status: "departed", pair_group: 1 },
      { section: "pair", title: "ervad", name: "", status: "departed", pair_group: 1 },
    ];
  }
  return [
    { section: "farmayeshne", title: "ervad", name: "", status: "living" },
  ];
}

// ---------------------------------------------------------------------------
// Entry points
// ---------------------------------------------------------------------------
export async function renderNewMachi() {
  chrome(true);
  refreshHeader();
  showFab(false);

  if (!state.draft || state.draft.edit || state.draft.prefill) {
    const prefill = (state.draft && state.draft.prefill) || {};
    state.draft = blankDraft(prefill);
    state.draft.names = defaultNames(state.draft.purpose);
  }
  await syncFromGregorian(state.draft);
  await loadAvailableGehs(state.draft);
  render(state.draft);
}

export async function renderEditMachi({ id }) {
  chrome(true);
  refreshHeader();
  showFab(false);
  loading();

  const aid = state.currentAgyaryId;
  let detail;
  try {
    detail = await machiDetail(aid, Number(id));
  } catch (e) {
    return showError(e.message);
  }

  const draft = blankDraft();
  draft.edit = { id: Number(id) };
  draft.behdin = { id: null, name: detail.behdin_name, phone: detail.behdin_phone };
  draft.purpose = detail.purpose;
  draft.geh = detail.geh;
  draft.gregorian = detail.gregorian;
  draft.roj = detail.roj;
  draft.mah = detail.mah;
  draft.year = detail.year;
  draft.names = detail.names && detail.names.length ? detail.names : defaultNames(detail.purpose);
  await syncFromGregorian(draft);
  await loadAvailableGehs(draft);
  state.draft = draft;
  render(draft);
}

// ---------------------------------------------------------------------------
// Date <-> Roj/Mah sync
// ---------------------------------------------------------------------------
async function syncFromGregorian(draft) {
  try {
    const p = await convertDate(draft.gregorian, system());
    draft.isGatha = p.is_gatha;
    draft.roj = p.is_gatha ? p.gatha_index : p.roj;
    draft.mah = p.is_gatha ? 13 : p.mah;
    draft.year = p.year;
    draft.parsiLabel = p.display;
  } catch (e) { /* keep whatever was there */ }
}

async function syncFromParsiFields(draft) {
  try {
    const p = await fromParsi(draft.roj, draft.mah, system());
    draft.gregorian = p.gregorian_date;
    draft.year = p.year;
    draft.isGatha = p.is_gatha;
    draft.parsiLabel = p.display;
  } catch (e) { /* keep whatever was there */ }
}

async function loadAvailableGehs(draft) {
  if (!draft.gregorian) return;
  try {
    const res = await bookableGehs(state.currentAgyaryId, draft.gregorian);
    draft.availableGehs = res.bookable || res;
  } catch (e) {
    draft.availableGehs = [1, 2, 3, 4, 5];
  }
}

// ---------------------------------------------------------------------------
// The single screen
// ---------------------------------------------------------------------------
async function render(draft) {
  const calOpts = state.calendarOptions;
  const rojOptions = calOpts.roj.map(o => {
    const v = Number(o.id.replace("roj_", ""));
    return `<option value="${v}" ${v === draft.roj && draft.mah !== 13 ? "selected" : ""}>${esc(o.title)}</option>`;
  }).join("");
  const mahOptions = calOpts.mah.map(o => {
    const v = Number(o.id.replace("mah_", ""));
    return `<option value="${v}" ${v === draft.mah ? "selected" : ""}>${esc(o.title)}</option>`;
  }).join("");

  const chosen = draft.behdin;

  mainEl.innerHTML = `
    <div class="card">
      <h2>${draft.edit ? "Edit machi" : "New machi"}</h2>

      <!-- Behdin -->
      <label>Behdin</label>
      ${chosen ? `
        <div class="chosen">
          <div class="who"><b>${esc(chosen.name)}</b><span>${esc(chosen.phone)}</span></div>
          <button class="ghost small" id="bhChange">Change</button>
        </div>` : `
        <input type="text" id="bhSearch" placeholder="Search by name or phone" autocomplete="off">
        <div id="bhResults" style="margin-top:4px"></div>
        <div style="margin-top:8px">
          <button class="secondary small" id="bhNew">+ Add a new behdin</button>
        </div>
        <div id="bhNewPanel"></div>`}

      <!-- Purpose -->
      <label style="margin-top:16px">Purpose</label>
      <select id="mcPurpose">
        <option value="patet" ${draft.purpose === "patet" ? "selected" : ""}>Patet (for the departed)</option>
        <option value="tandarosti" ${draft.purpose === "tandarosti" ? "selected" : ""}>Tandarosti (for the living)</option>
      </select>

      <!-- Date + Roj/Mah -->
      <label style="margin-top:16px">Date</label>
      <div class="synced" id="syncBox">
        <input type="date" id="mcDate" value="${esc(draft.gregorian)}">
        <div class="row" style="margin-top:8px">
          <div><label>Roj</label><select id="mcRoj">${rojOptions}</select></div>
          <div><label>Mah</label><select id="mcMah">${mahOptions}</select></div>
        </div>
        <div class="sync-note" id="syncNote">${esc(draft.parsiLabel || "")}</div>
      </div>

      <!-- Geh -->
      <label style="margin-top:16px">Geh</label>
      <div class="geh-grid" id="gehGrid">
        ${GEHS.map(([num, name]) => {
          const avail = draft.availableGehs.includes(num);
          const sel = draft.geh === num;
          return `<button class="geh-btn${sel ? " selected" : ""}${!avail && !sel ? " taken" : ""}"
            data-geh="${num}" ${!avail && !sel ? "disabled" : ""}>${esc(name)}</button>`;
        }).join("")}
      </div>

      <!-- Names -->
      <label style="margin-top:16px">Names</label>
      <div id="namesRegion">${renderNames(draft)}</div>

      ${!draft.edit ? `<!-- Recurring -->
      <label class="check-row" style="margin-top:16px">
        <input type="checkbox" id="mcRecur" ${draft.recurring ? "checked" : ""}>
        Repeat every month on this Roj
      </label>` : ""}

      <!-- Actions -->
      <div class="wizard-nav" style="margin-top:20px">
        <button class="ghost" id="mcCancel">Cancel</button>
        <button id="mcSave">${draft.edit ? "Save changes" : "Book it"}</button>
      </div>
    </div>`;

  // --- Behdin wiring ---
  if (chosen) {
    document.getElementById("bhChange").onclick = () => { draft.behdin = null; render(draft); };
  } else {
    wireSearch(draft);
    document.getElementById("bhNew").onclick = () => {
      const typed = (document.getElementById("bhSearch") || {}).value || "";
      renderAddBehdin(document.getElementById("bhNewPanel"), {
        prefill: { name: typed.trim() },
        onCreated: (created) => choose(draft, created),
      });
    };
  }

  // --- Purpose wiring ---
  document.getElementById("mcPurpose").onchange = (e) => {
    draft.purpose = e.target.value;
    draft.names = defaultNames(draft.purpose);
    document.getElementById("namesRegion").innerHTML = renderNames(draft);
    wireNames(draft);
  };

  // --- Date wiring ---
  const box = document.getElementById("syncBox");
  const note = document.getElementById("syncNote");
  const busy = (on) => box.classList.toggle("syncing", on);

  document.getElementById("mcDate").onchange = async (e) => {
    draft.gregorian = e.target.value;
    if (!draft.gregorian) return;
    busy(true);
    await syncFromGregorian(draft);
    await loadAvailableGehs(draft);
    busy(false);
    render(draft);
  };

  const onParsiChange = async () => {
    draft.roj = Number(document.getElementById("mcRoj").value);
    draft.mah = Number(document.getElementById("mcMah").value);
    busy(true);
    note.textContent = "Finding that day...";
    await syncFromParsiFields(draft);
    await loadAvailableGehs(draft);
    busy(false);
    render(draft);
  };
  document.getElementById("mcRoj").onchange = onParsiChange;
  document.getElementById("mcMah").onchange = onParsiChange;

  // --- Geh wiring ---
  document.getElementById("gehGrid").querySelectorAll(".geh-btn:not([disabled])").forEach(btn => {
    btn.onclick = () => {
      draft.geh = Number(btn.dataset.geh);
      document.querySelectorAll(".geh-btn").forEach(b => b.classList.remove("selected"));
      btn.classList.add("selected");
    };
  });

  // --- Names wiring ---
  wireNames(draft);

  // --- Recurring wiring ---
  const recurEl = document.getElementById("mcRecur");
  if (recurEl) recurEl.onchange = () => { draft.recurring = recurEl.checked; };

  // --- Cancel / Save ---
  document.getElementById("mcCancel").onclick = () => { state.draft = null; navigate("#/calendar"); };
  document.getElementById("mcSave").onclick = () => save(draft);
}

// ---------------------------------------------------------------------------
// Names rendering (inline, not the full names.js editor)
// ---------------------------------------------------------------------------
function renderNames(draft) {
  const names = draft.names || [];
  if (draft.purpose === "patet") {
    return `
      <div class="names-inline">
        <p class="meta">One pair of names for patet</p>
        ${names.map((n, i) => nameRow(n, i, false)).join("")}
      </div>`;
  }
  return `
    <div class="names-inline">
      <p class="meta">Names for tandarosti (living only)</p>
      ${names.map((n, i) => nameRow(n, i, true)).join("")}
      <button class="ghost small" id="nameAdd" type="button" style="margin-top:8px">+ Add name</button>
    </div>`;
}

function nameRow(n, idx, removable) {
  const titleOpts = NAME_TITLES.map(t =>
    `<option value="${t}" ${n.title === t ? "selected" : ""}>${TITLE_DISPLAY[t]}</option>`
  ).join("");
  return `
    <div class="name-row" data-idx="${idx}">
      <select class="t" data-idx="${idx}">${titleOpts}</select>
      <input type="text" data-idx="${idx}" placeholder="Name" value="${esc(n.name)}">
      ${removable ? `<button class="rm" data-idx="${idx}" type="button">&times;</button>` : ""}
    </div>`;
}

function wireNames(draft) {
  const region = document.getElementById("namesRegion");
  if (!region) return;

  region.querySelectorAll(".name-row select.t").forEach(el => {
    el.onchange = () => { draft.names[Number(el.dataset.idx)].title = el.value; };
  });
  region.querySelectorAll(".name-row input").forEach(el => {
    el.oninput = () => { draft.names[Number(el.dataset.idx)].name = el.value.trim(); };
  });
  region.querySelectorAll(".name-row button.rm").forEach(el => {
    el.onclick = () => {
      draft.names.splice(Number(el.dataset.idx), 1);
      region.innerHTML = renderNames(draft);
      wireNames(draft);
    };
  });

  const addBtn = document.getElementById("nameAdd");
  if (addBtn) {
    addBtn.onclick = () => {
      draft.names.push({ section: "farmayeshne", title: "ervad", name: "", status: "living" });
      region.innerHTML = renderNames(draft);
      wireNames(draft);
    };
  }
}

// ---------------------------------------------------------------------------
// Behdin search
// ---------------------------------------------------------------------------
function wireSearch(draft) {
  const input = document.getElementById("bhSearch");
  const results = document.getElementById("bhResults");
  const panel = document.getElementById("bhNewPanel");
  if (!input) return;
  let timer, token = 0;

  /**
   * Booking for someone new is the common case, not the exception, and the
   * name has already been typed once by the time we know they aren't on
   * file. So the add form opens by itself with that name in it - no
   * "Nobody matching" dead end, no button to find, and nothing typed twice.
   */
  const openAdd = (name) => {
    const open = document.getElementById("abName");
    if (open) {
      // Already showing. Track the search box as he keeps typing, but never
      // clobber a name he has corrected by hand in the form itself.
      open.value = name;
      return;
    }
    renderAddBehdin(panel, {
      prefill: { name },
      onCreated: (created) => choose(draft, created),
      onCancel: () => { showNewBtn(true); input.focus(); },
    });
    // The name is already on screen in the search box directly above, so the
    // form does not ask for it a second time - the box above IS the name
    // field. And the button that opens this form is meaningless while the
    // form is open.
    const row = document.getElementById("abNameRow");
    if (row) row.style.display = "none";
    showNewBtn(false);
  };

  const showNewBtn = (show) => {
    const btn = document.getElementById("bhNew");
    if (btn) btn.style.display = show ? "" : "none";
  };

  const closeAdd = () => { panel.innerHTML = ""; showNewBtn(true); };

  input.oninput = () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const mine = ++token;
      const q = input.value.trim();
      let matches = [];
      try { matches = await listBehdins(state.currentAgyaryId, q); }
      catch (e) { return; }
      if (mine !== token) return;

      if (matches.length) {
        // Somebody matched, so the add form is moot - drop it rather than
        // leaving a half-filled form under a list he is about to tap.
        closeAdd();
        results.innerHTML = matches.map((m, i) => `
            <div class="search-result" data-i="${i}">
              <div>${esc(m.name)}</div><div class="addr">${esc(m.phone)}</div>
            </div>`).join("");
        results.querySelectorAll(".search-result").forEach(el => {
          el.onclick = () => choose(draft, matches[Number(el.dataset.i)]);
        });
        return;
      }

      results.innerHTML = "";
      // Two characters, so a single stray keystroke doesn't throw a form up.
      if (q.length >= 2) openAdd(q); else closeAdd();
    }, 220);
  };
  input.focus();
}

function choose(draft, match) {
  const id = match.id != null ? match.id : match.customer_id;
  draft.behdin = { id, name: match.name, phone: match.phone };
  render(draft);
}

// ---------------------------------------------------------------------------
// Save
// ---------------------------------------------------------------------------
async function save(draft) {
  if (!draft.behdin) return showError("Please select a behdin.");
  if (!draft.purpose) return showError("Please select a purpose.");
  if (!draft.gregorian) return showError("Please select a date.");
  if (!draft.geh) return showError("Please select a geh.");

  const namesList = (draft.names || []).filter(n => n.name.trim());
  if (draft.purpose === "patet" && namesList.length < 2) {
    return showError("Patet requires a pair of names.");
  }

  const btn = document.getElementById("mcSave");
  btn.disabled = true;

  try {
    const aid = state.currentAgyaryId;
    const body = {
      behdin_phone: draft.behdin.phone,
      behdin_name: draft.behdin.name,
      roj: draft.roj,
      mah: draft.mah,
      year: draft.year,
      geh: draft.geh,
      gregorian: draft.gregorian,
      purpose: draft.purpose,
      names: namesList.map(n => ({
        section: draft.purpose === "patet" ? "pair" : "farmayeshne",
        title: n.title,
        name: n.name.trim(),
        status: draft.purpose === "patet" ? "departed" : "living",
        pair_group: draft.purpose === "patet" ? 1 : null,
      })),
    };

    if (draft.recurring && !draft.edit) body.recurring = true;

    let res;
    if (draft.edit) {
      res = await editMachi(aid, draft.edit.id, body);
    } else {
      res = await addMachi(aid, body);
    }

    state.calendar.focus = draft.gregorian;
    state.calendar.mode = "day";
    state.draft = null;
    const mid = draft.edit ? draft.edit.id : (res.machi_id || res.id);
    navigate(`#/machi/${aid}/${mid}`);
  } catch (e) {
    btn.disabled = false;
    showError(e.message);
  }
}
