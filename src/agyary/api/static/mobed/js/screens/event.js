"use strict";

/**
 * Add / edit an event — one screen, not a wizard.
 *
 * Behdin, service, date, time. Names are auto-pulled from the behdin's
 * saved pool at save time (server-side). Machi is selectable here like any
 * other service - doing so skips the dedicated Machi board's slot/Geh
 * logic entirely, since this path only ever creates a plain Booking.
 */

import {
  listServices, createService, listBehdins,
  convertDate, fromParsi, addBooking,
  bookingDetail, editBooking,
} from "../api.js";
import { state, primarySystem } from "../state.js";
import { renderCalendar } from "../calendar.js";
import { renderAddBehdin } from "../behdin_add.js";
import { chrome, mainEl, showFab, showError, refreshHeader, loading } from "../ui.js";
import { esc, istYmd, istTime, todayIst, gregLabel } from "../util.js";
import { navigate } from "../router.js";

function system() {
  return primarySystem();
}

function blankDraft(prefill = {}) {
  return {
    edit: null,
    behdin: null,
    service_id: null,
    service_name: "",
    gregorian: prefill.gregorian || todayIst(),
    roj: prefill.roj || null,
    mah: prefill.mah || null,
    year: prefill.year || null,
    time: "10:00",
    parsiLabel: "",
    isGatha: false,
  };
}

// ---------------------------------------------------------------------------
// Entry points
// ---------------------------------------------------------------------------
export async function renderNewEvent() {
  chrome(true);
  refreshHeader();
  showFab(false);

  if (!state.draft || state.draft.edit) {
    const prefill = (state.draft && state.draft.prefill) || {};
    state.draft = blankDraft(prefill);
  }
  await syncFromGregorian(state.draft);
  render(state.draft);
}

export async function renderEditEvent({ kind, id }) {
  chrome(true);
  refreshHeader();
  showFab(false);
  loading();

  if (kind === "machi") {
    showError("Machi editing is not available in this view.");
    return navigate("#/calendar");
  }

  const aid = state.currentAgyaryId;
  let detail;
  try {
    detail = await bookingDetail(aid, Number(id));
  } catch (e) {
    return showError(e.message);
  }

  const draft = blankDraft();
  draft.edit = { kind, id: Number(id) };
  draft.behdin = { id: null, name: detail.behdin_name, phone: detail.behdin_phone };
  draft.service_id = detail.service_id;
  draft.gregorian = istYmd(detail.ceremony_datetime);
  draft.time = istTime(detail.ceremony_datetime).replace(/\s?[AP]M/i, "");
  await syncFromGregorian(draft);
  state.draft = draft;
  render(draft);
}

// ---------------------------------------------------------------------------
// Date <-> Roj/Mah, always via the server
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

// ---------------------------------------------------------------------------
// Service list (cached per agyary)
// ---------------------------------------------------------------------------
async function servicesFor(aid) {
  if (!state.formOptionsCache[aid]) {
    try {
      const all = await listServices(aid);
      state.formOptionsCache[aid] = { services: all.filter(s => s.is_active) };
    } catch (e) {
      showError(e.message);
      return null;
    }
  }
  return state.formOptionsCache[aid];
}

// ---------------------------------------------------------------------------
// The single screen
// ---------------------------------------------------------------------------
async function render(draft) {
  const aid = state.currentAgyaryId;
  const opts = await servicesFor(aid);
  if (!opts) return;

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
      <h2>${draft.edit ? "Edit event" : "New event"}</h2>

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

      <!-- Service -->
      <label style="margin-top:16px">Service</label>
      <select id="evService">
        <option value="" ${!draft.service_id ? "selected" : ""} disabled>Select a service...</option>
        ${opts.services.map(s =>
          `<option value="${s.id}" ${s.id === draft.service_id ? "selected" : ""}>${esc(s.name)}</option>`).join("")}
        <option value="__new__">+ Add a new service</option>
      </select>
      <div id="newServicePanel"></div>

      <!-- Date + Roj/Mah -->
      <label style="margin-top:16px">Date</label>
      <div class="synced" id="syncBox">
        <input type="date" id="evDate" value="${esc(draft.gregorian)}">
        <div class="row" style="margin-top:8px">
          <div><label>Roj</label><select id="evRoj">${rojOptions}</select></div>
          <div><label>Mah</label><select id="evMah">${mahOptions}</select></div>
        </div>
        <div class="sync-note" id="syncNote">${esc(draft.parsiLabel || "")}</div>
      </div>
      <div style="margin-top:8px">
        <button class="ghost small" id="evPick">Pick from the calendar</button>
      </div>
      <div id="evPickPanel"></div>

      <!-- Time -->
      <label style="margin-top:16px">Time</label>
      <input type="time" id="evTime" value="${esc(draft.time)}">

      <!-- Actions -->
      <div class="wizard-nav" style="margin-top:20px">
        <button class="ghost" id="evCancel">Cancel</button>
        <button id="evSave">${draft.edit ? "Save changes" : "Add event"}</button>
      </div>
    </div>`;

  // --- Behdin wiring ---
  if (chosen) {
    document.getElementById("bhChange").onclick = () => { draft.behdin = null; render(draft); };
  } else {
    wireSearch(draft);
    // A deliberate tap, not the mid-typing "nobody matched" fallback below -
    // send them to the full behdin page (saved names and all), the same one
    // Settings uses, rather than the compact inline form.
    document.getElementById("bhNew").onclick = () => {
      const typed = (document.getElementById("bhSearch") || {}).value || "";
      state.behdinReturnTo = "event";
      state.behdinPrefillName = typed.trim();
      navigate("#/behdins/new");
    };
  }

  // --- Service wiring ---
  const sel = document.getElementById("evService");
  sel.onchange = () => {
    if (sel.value === "__new__") return renderNewServicePanel(sel, draft);
    const svc = opts.services.find(s => String(s.id) === sel.value);
    draft.service_id = svc ? svc.id : null;
    draft.service_name = svc ? svc.name : "";
  };

  // --- Date wiring ---
  const box = document.getElementById("syncBox");
  const note = document.getElementById("syncNote");
  const busy = (on) => box.classList.toggle("syncing", on);

  document.getElementById("evDate").onchange = async (e) => {
    draft.gregorian = e.target.value;
    if (!draft.gregorian) return;
    busy(true);
    await syncFromGregorian(draft);
    busy(false);
    render(draft);
  };

  const onParsiChange = async () => {
    draft.roj = Number(document.getElementById("evRoj").value);
    draft.mah = Number(document.getElementById("evMah").value);
    busy(true);
    note.textContent = "Finding that day...";
    await syncFromParsiFields(draft);
    busy(false);
    render(draft);
  };
  document.getElementById("evRoj").onchange = onParsiChange;
  document.getElementById("evMah").onchange = onParsiChange;

  document.getElementById("evPick").onclick = async () => {
    const panel = document.getElementById("evPickPanel");
    if (panel.innerHTML) { panel.innerHTML = ""; return; }
    const view = { mode: "month", focus: draft.gregorian, parsiMonth: null, selectedDay: draft.gregorian };
    const draw = () => renderCalendar(panel, {
      view,
      loadItems: async () => [],
      onDayPick: async (day) => {
        draft.gregorian = day;
        await syncFromGregorian(draft);
        render(draft);
      },
      rerender: draw,
    });
    await draw();
  };

  // --- Time wiring ---
  document.getElementById("evTime").onchange = (e) => { draft.time = e.target.value; };

  // --- Cancel / Save ---
  document.getElementById("evCancel").onclick = () => { state.draft = null; navigate("#/calendar"); };
  document.getElementById("evSave").onclick = () => save(draft);
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
// Inline new-service
// ---------------------------------------------------------------------------
function renderNewServicePanel(selectEl, draft) {
  const panel = document.getElementById("newServicePanel");
  panel.innerHTML = `
    <div class="card" style="margin-top:12px">
      <label>New service name</label>
      <input type="text" id="nsName" placeholder="e.g. Afringan">
      <div class="row tight" style="margin-top:12px">
        <button class="small" id="nsSave">Add service</button>
        <button class="ghost small" id="nsCancel">Cancel</button>
      </div>
    </div>`;
  document.getElementById("nsCancel").onclick = () => { panel.innerHTML = ""; selectEl.value = ""; };
  document.getElementById("nsSave").onclick = async () => {
    const name = document.getElementById("nsName").value.trim();
    if (!name) return showError("Please enter a service name.");
    try {
      const svc = await createService(state.currentAgyaryId, name, false);
      delete state.formOptionsCache[state.currentAgyaryId];
      draft.service_id = svc.id;
      draft.service_name = svc.name;
      render(draft);
    } catch (e) {
      showError(e.message);
    }
  };
}

// ---------------------------------------------------------------------------
// Save
// ---------------------------------------------------------------------------
async function save(draft) {
  if (!draft.behdin) return showError("Please select a behdin.");
  if (!draft.service_id) return showError("Please select a service.");
  if (!draft.gregorian) return showError("Please select a date.");
  if (!draft.time) return showError("Please select a time.");

  const btn = document.getElementById("evSave");
  btn.disabled = true;

  try {
    const aid = state.currentAgyaryId;
    const body = {
      behdin_phone: draft.behdin.phone,
      behdin_name: draft.behdin.name,
      service_id: draft.service_id,
      ceremony_datetime: `${draft.gregorian}T${draft.time}:00`,
    };

    let res;
    if (draft.edit) {
      res = await editBooking(aid, draft.edit.id, body);
    } else {
      res = await addBooking(aid, body);
    }

    state.calendar.focus = draft.gregorian;
    state.calendar.mode = "day";
    state.draft = null;
    navigate(`#/booking/${aid}/${draft.edit ? draft.edit.id : res.booking_id}`);
  } catch (e) {
    btn.disabled = false;
    showError(e.message);
  }
}
