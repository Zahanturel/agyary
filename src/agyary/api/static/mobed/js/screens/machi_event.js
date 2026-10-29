"use strict";

/**
 * Add / edit a machi — one screen.
 *
 * Behdin, purpose (patet/tandarosti), date with Roj/Mah sync, geh picker
 * with live availability. Names are not entered here: the next step (see
 * review.js) shows the slip with the behdin's saved names, keyed on purpose,
 * for the mobed to check and correct before anything is saved.
 */

import {
  listBehdins, convertDate, fromParsi, bookableGehs,
  machiDetail,
} from "../api.js";
import { state, primarySystem, GEHS, GEH_NAME_BY_NUM, MACHI_PURPOSE_DISPLAY } from "../state.js";
import { renderAddBehdin } from "../behdin_add.js";
import { loadDraft, saveDraft, clearDraft, offerDraft, restoredDate } from "../drafts.js";
import { chrome, mainEl, showFab, showError, showInfo, refreshHeader, loading } from "../ui.js";
import { esc, todayIst, gregLabel } from "../util.js";
import { navigate, back, navGuard } from "../router.js";

function system() {
  return primarySystem();
}

function blankDraft(prefill = {}) {
  return {
    kind: "machi",
    names: null,   // see event.js: null = the behdin's saved names, chosen at review
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
    // null (don't repeat), "monthly" or "yearly" - see the picker below.
    recurring: null,
  };
}

// ---------------------------------------------------------------------------
// Entry points
// ---------------------------------------------------------------------------
// The unfinished machi the mobed left, kept by drafts.js and offered back (not
// silently applied) the next time they open a new one.
const DRAFT_KEY = "machi";

/** Only the content is kept. Roj, Mah and the Parsi label are worked out again
 *  from the date, and which gehs are free is asked again - none of that is
 *  worth carrying, and carrying it is how a stale Roj ends up on a new booking. */
function keep(draft) {
  if (draft.edit) return;
  if (!draft.behdin) return clearDraft(DRAFT_KEY);
  saveDraft(DRAFT_KEY, {
    behdin: draft.behdin, names: draft.names, purpose: draft.purpose,
    gregorian: draft.gregorian, geh: draft.geh, recurring: draft.recurring,
  });
}

async function open(draft) {
  state.draft = draft;
  await syncFromGregorian(draft);
  await loadAvailableGehs(draft);
  await render(draft);
}

export async function renderNewMachi() {
  chrome(true);
  refreshHeader();
  showFab(false);

  // Already part-way through right here - back from the review step, or from
  // adding a behdin: carry on, nothing to ask.
  const held = state.draft;
  if (held && held.kind === "machi" && !held.edit && !held.prefill) return open(held);

  // Otherwise this is a new machi, started from the + or from a free geh. If
  // an unfinished one was left, ask before doing anything with it.
  const prefill = (held && held.prefill) || {};
  const stored = loadDraft(DRAFT_KEY);
  if (!stored || !stored.behdin) return open(blankDraft(prefill));

  offerDraft({
    title: "Unfinished machi",
    summary: [
      stored.behdin.name,
      MACHI_PURPOSE_DISPLAY[stored.purpose] || stored.purpose,
      `${gregLabel(stored.gregorian)}${stored.geh ? " · " + (GEH_NAME_BY_NUM[stored.geh] || "") + " Geh" : ""}`,
    ],
    onStartNew: () => { clearDraft(DRAFT_KEY); open(blankDraft(prefill)); },
    onContinue: async () => {
      const draft = blankDraft(prefill);
      draft.behdin = stored.behdin;
      draft.names = stored.names || null;
      draft.purpose = stored.purpose || "patet";
      draft.recurring = stored.recurring || null;
      // A date that has gone by is not carried into a new booking.
      const [date, replaced] = restoredDate(stored.gregorian, prefill.gregorian);
      draft.gregorian = date;
      draft.geh = replaced ? (prefill.geh || null) : stored.geh;
      await open(draft);
      if (replaced) showInfo(`The date you had chosen has passed, so this is for ${gregLabel(date)}.`);
    },
  });
}

export async function renderEditMachi({ id }) {
  chrome(true);
  refreshHeader();
  showFab(false);
  loading();
  const alive = navGuard();

  // Back from the review step: keep the mobed's unsaved changes (see event.js).
  const held = state.draft;
  if (held && held.edit && held.edit.id === Number(id) && held.returning) {
    held.returning = false;
    return render(held);
  }

  const aid = state.currentAgyaryId;
  let detail;
  try {
    detail = await machiDetail(aid, Number(id));
  } catch (e) {
    if (!alive()) return;
    return showError(e.message);
  }
  if (!alive()) return;

  const draft = blankDraft();
  draft.edit = { id: Number(id) };
  draft.behdin = { id: null, name: detail.behdin_name, phone: detail.behdin_phone };
  draft.names = detail.names;   // the machi's own, as saved
  draft.purpose = detail.purpose;
  draft.geh = detail.geh;
  draft.gregorian = detail.gregorian;
  draft.roj = detail.roj;
  draft.mah = detail.mah;
  draft.year = detail.year;
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
  keep(draft);
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

      ${!draft.edit ? `<!-- Recurring -->
      <label style="margin-top:16px">Repeat</label>
      <select id="mcRecur">
        <option value="" ${!draft.recurring ? "selected" : ""}>Don't repeat</option>
        <option value="monthly" ${draft.recurring === "monthly" ? "selected" : ""}>Every month, same Roj</option>
        <option value="yearly" ${draft.recurring === "yearly" ? "selected" : ""}>Every year, same Roj &amp; Mah - for a birthday or anniversary</option>
      </select>` : ""}

      <!-- Actions -->
      <div class="wizard-nav" style="margin-top:20px">
        <button class="ghost" id="mcCancel">Cancel</button>
        <button id="mcSave">Review</button>
      </div>
    </div>`;

  // --- Behdin wiring ---
  if (chosen) {
    document.getElementById("bhChange").onclick = () => { draft.behdin = null; draft.names = null; render(draft); };
  } else {
    wireSearch(draft);
    // A deliberate tap, not the mid-typing "nobody matched" fallback below -
    // send them to the full behdin page (saved names and all), the same one
    // Settings and New Event use, rather than the compact inline form.
    document.getElementById("bhNew").onclick = () => {
      const typed = (document.getElementById("bhSearch") || {}).value || "";
      state.behdinReturnTo = "machi";
      state.behdinPrefillName = typed.trim();
      navigate("#/behdins/new");
    };
  }

  // --- Purpose wiring ---
  document.getElementById("mcPurpose").onchange = (e) => {
    draft.purpose = e.target.value;
    draft.names = null;   // patet and tandarosti take different names
    keep(draft);
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
      keep(draft);
    };
  });

  // --- Recurring wiring ---
  const recurEl = document.getElementById("mcRecur");
  if (recurEl) recurEl.onchange = () => { draft.recurring = recurEl.value || null; keep(draft); };

  // --- Cancel / Save ---
  document.getElementById("mcCancel").onclick = () => {
    state.draft = null;
    if (!draft.edit) clearDraft(DRAFT_KEY);
    back(draft.edit ? `#/machi/${state.currentAgyaryId}/${draft.edit.id}` : "#/board");
  };
  document.getElementById("mcSave").onclick = () => save(draft);
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
  draft.names = null;   // a different behdin has different saved names
  render(draft);
}

// ---------------------------------------------------------------------------
// Next: review. Saving happens there, after the mobed has seen the slip.
// ---------------------------------------------------------------------------
function save(draft) {
  if (!draft.behdin) return showError("Please select a behdin.");
  if (!draft.purpose) return showError("Please select a purpose.");
  if (!draft.gregorian) return showError("Please select a date.");
  if (!draft.geh) return showError("Please select a geh.");
  navigate("#/machi/review", { replace: true });
}
