"use strict";

/**
 * New Event, rebuilt as a six-step wizard.
 *
 * The screen it replaces put behdin creation, service, date, time, purpose
 * and the whole names editor on one page, and created the behdin as a side
 * effect of saving. Here the behdin is chosen or created up front, against
 * the real endpoint, and each decision gets its own step.
 *
 * The date step is the point of the whole exercise: Gregorian and Roj/Mah
 * are two views of one value, either is editable, and neither is ever
 * derived in the browser. Editing Gregorian asks the server for the Parsi
 * reading; editing Roj/Mah asks the server which date that is. The old
 * build guessed the Yazdegerdi year as `year - 630` and could file a
 * ceremony a whole Parsi year off.
 */

import {
  listServices, createService, getSavedNames, putSavedNames,
  listBehdins, convertDate, fromParsi, addMachi, addBooking,
  machiDetail, bookingDetail, editMachi, editBooking,
} from "../api.js";
import {
  state, currentAgyary, GEHS, GEH_NAME_BY_NUM,
  MACHI_PURPOSE_DISPLAY, SERVICE_PURPOSE_DISPLAY,
} from "../state.js";
import { renderCalendar } from "../calendar.js";
import { renderAddBehdin } from "../behdin_add.js";
import { renderNamesEditor, collectNames, validateNames } from "../names.js";
import { chrome, mainEl, showFab, showError, showInfo, markActiveTab, refreshHeader, loading } from "../ui.js";
import { esc, istYmd, istTime, todayIst, gregLabel } from "../util.js";
import { navigate } from "../router.js";

const STEPS = ["Behdin", "Service", "Date", "Time", "Names", "Confirm"];

function system() {
  const agyary = currentAgyary();
  return (agyary && agyary.calendar_system) || "shenshai";
}

function blankDraft(prefill = {}) {
  return {
    type: prefill.geh ? "machi" : "service",
    step: 0,
    edit: null,                 // {kind, id} when editing
    behdin: null,               // {id, name, phone}
    service_id: null,
    service_name: "",
    offsite_capable: false,
    gregorian: prefill.gregorian || todayIst(),
    roj: prefill.roj || null,
    mah: prefill.mah || null,
    year: prefill.year || null,
    geh: prefill.geh || 1,
    time: "10:00",
    purpose: prefill.geh ? "patet" : "gujrela_nu",
    location: null,
    is_offsite: false,
    names: [],
    savedNamesTouched: false,
    conflict: null,
  };
}

// ---------------------------------------------------------------------------
// Entry points
// ---------------------------------------------------------------------------
export async function renderNewEvent() {
  chrome(true);
  refreshHeader();
  markActiveTab("");
  showFab(false);

  if (!state.draft || state.draft.edit) {
    const prefill = (state.draft && state.draft.prefill) || {};
    state.draft = blankDraft(prefill);
    if (prefill.roj) await syncFromParsiFields(state.draft);   // slot tap already knows the day
  }
  await renderStep();
}

export async function renderEditEvent({ kind, id }) {
  chrome(true);
  refreshHeader();
  markActiveTab("");
  showFab(false);
  loading();

  const aid = state.currentAgyaryId;
  const isMachi = kind === "machi";
  let detail;
  try {
    detail = isMachi ? await machiDetail(aid, Number(id)) : await bookingDetail(aid, Number(id));
  } catch (e) {
    return showError(e.message);
  }

  const draft = blankDraft();
  draft.type = isMachi ? "machi" : "service";
  draft.edit = { kind, id: Number(id) };
  draft.behdin = { id: null, name: detail.behdin_name, phone: detail.behdin_phone };
  draft.purpose = detail.purpose;
  draft.names = detail.names || [];
  if (isMachi) {
    draft.roj = detail.roj; draft.mah = detail.mah; draft.year = detail.year;
    draft.geh = detail.geh; draft.gregorian = detail.gregorian;
  } else {
    draft.service_id = detail.service_id;
    draft.gregorian = istYmd(detail.ceremony_datetime);
    draft.time = istTime(detail.ceremony_datetime).replace(/\s?[AP]M/i, "");
    // Carried through, not reset. Sending a flat null/false here is exactly
    // what used to wipe an offsite booking's location on an unrelated edit.
    draft.location = detail.location;
    draft.is_offsite = !!detail.is_offsite;
    await syncFromGregorian(draft);
  }
  state.draft = draft;
  await renderStep();
}

// ---------------------------------------------------------------------------
// Date <-> Roj/Mah, always via the server
// ---------------------------------------------------------------------------
async function syncFromGregorian(draft) {
  const p = await convertDate(draft.gregorian, system());
  draft.isGatha = p.is_gatha;
  draft.roj = p.is_gatha ? p.gatha_index : p.roj;
  draft.mah = p.is_gatha ? 13 : p.mah;
  draft.year = p.year;
  draft.parsiLabel = p.display;
}

async function syncFromParsiFields(draft) {
  // No year is sent: the server resolves the nearest occurrence. Computing
  // it here is the bug this endpoint exists to prevent.
  const p = await fromParsi(draft.roj, draft.mah, system());
  draft.gregorian = p.gregorian_date;
  draft.year = p.year;
  draft.isGatha = p.is_gatha;
  draft.parsiLabel = p.display;
}

// ---------------------------------------------------------------------------
// Shell
// ---------------------------------------------------------------------------
function stepsBar(step) {
  return `<div class="steps">${STEPS.map((_, i) =>
    `<div class="step ${i < step ? "done" : i === step ? "current" : ""}"></div>`).join("")}</div>
    <div class="step-title">Step ${step + 1} of ${STEPS.length} · ${STEPS[step]}</div>`;
}

function navButtons(draft, { nextLabel = "Next", canNext = true } = {}) {
  return `<div class="wizard-nav">
    ${draft.step > 0 ? '<button class="ghost" data-wiz-back>Back</button>' : '<button class="ghost" data-wiz-cancel>Cancel</button>'}
    <button data-wiz-next ${canNext ? "" : "disabled"}>${esc(nextLabel)}</button>
  </div>`;
}

async function renderStep() {
  const draft = state.draft;
  const renderers = [stepBehdin, stepService, stepDate, stepTime, stepNames, stepConfirm];
  await renderers[draft.step](draft);

  const back = mainEl.querySelector("[data-wiz-back]");
  if (back) back.onclick = () => { draft.step--; renderStep(); };
  const cancel = mainEl.querySelector("[data-wiz-cancel]");
  if (cancel) cancel.onclick = () => { state.draft = null; navigate("#/my-day"); };
}

function goNext() { state.draft.step++; return renderStep(); }

// ---------------------------------------------------------------------------
// Step 1 - Behdin
// ---------------------------------------------------------------------------
async function stepBehdin(draft) {
  const chosen = draft.behdin;
  mainEl.innerHTML = `
    ${stepsBar(0)}
    <div class="card">
      <h2>Who is this for?</h2>
      ${chosen ? `
        <div class="chosen">
          <div class="who"><b>${esc(chosen.name)}</b><span>${esc(chosen.phone)}</span></div>
          <button class="ghost small" id="bhChange">Change</button>
        </div>` : `
        <label>Search behdins</label>
        <input type="text" id="bhSearch" placeholder="Name or phone number" autocomplete="off">
        <div id="bhResults" style="margin-top:8px"></div>
        <div style="margin-top:12px">
          <button class="secondary small" id="bhNew">+ Add a new behdin</button>
        </div>
        <div id="bhNewPanel"></div>`}
      ${navButtons(draft, { canNext: !!chosen })}
    </div>`;

  if (chosen) {
    document.getElementById("bhChange").onclick = () => { draft.behdin = null; renderStep(); };
    mainEl.querySelector("[data-wiz-next]").onclick = goNext;
    return;
  }

  const input = document.getElementById("bhSearch");
  const results = document.getElementById("bhResults");
  let timer, token = 0;
  input.oninput = () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const mine = ++token;
      let matches = [];
      // The temple's register, not the booking-derived personal list: a
      // behdin registered moments ago has no bookings yet and would be
      // invisible in the latter - which is precisely who you're looking
      // for when you just added them.
      try { matches = await listBehdins(state.currentAgyaryId, input.value.trim()); }
      catch (e) { return; }
      if (mine !== token) return;
      results.innerHTML = matches.length
        ? matches.map((m, i) => `
            <div class="search-result" data-i="${i}">
              <div>${esc(m.name)}</div><div class="addr">${esc(m.phone)}</div>
            </div>`).join("")
        : '<p class="meta">Nobody matching. Add them below.</p>';
      results.querySelectorAll(".search-result").forEach(el => {
        el.onclick = () => choose(draft, matches[Number(el.dataset.i)]);
      });
    }, 220);
  };
  input.focus();

  document.getElementById("bhNew").onclick = () => {
    // Same form as the Behdins screen - one add-behdin UI, not two.
    renderAddBehdin(document.getElementById("bhNewPanel"), {
      onCreated: (created) => choose(draft, created),
    });
  };
}

async function choose(draft, match) {
  // Both shapes reach here: the register returns `id`, the newly-created
  // behdin response also returns `id`.
  const id = match.id != null ? match.id : match.customer_id;
  draft.behdin = { id, name: match.name, phone: match.phone };
  // Prefill names from the behdin's saved pool - the shared rows the
  // WhatsApp flow reads and writes, not a replay of their last booking.
  if (id) {
    try {
      draft.names = await getSavedNames(state.currentAgyaryId, id);
    } catch (e) {
      draft.names = [];
    }
  }
  renderStep();
}

/**
 * The bookable service list, WITH offsite_capable on each row.
 *
 * Not /form-options: that returns only {id, name} (plus priests), and
 * whether a service can be performed away from the fire temple is the
 * thing step 4 needs in order to decide whether to offer an offsite
 * toggle at all. The catalog endpoint carries it, so use that and filter
 * out the deactivated ones - which is the only thing form-options was
 * doing for us here.
 */
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
// Step 2 - what kind of ceremony
// ---------------------------------------------------------------------------
async function stepService(draft) {
  const aid = state.currentAgyaryId;
  const opts = await servicesFor(aid);
  if (!opts) return;
  const isMachi = draft.type === "machi";

  mainEl.innerHTML = `
    ${stepsBar(1)}
    <div class="card">
      <h2>What is being performed?</h2>
      <div class="toggle" style="margin-bottom:12px">
        <button data-type="service" class="${!isMachi ? "active" : ""}">Service</button>
        <button data-type="machi" class="${isMachi ? "active" : ""}">Machi</button>
      </div>
      ${isMachi ? `
        <p class="meta">Machi is booked into one of the five Gehs for a day.</p>
      ` : `
        <label>Service</label>
        <select id="evService">
          <option value="" ${!draft.service_id ? "selected" : ""} disabled>Select a service...</option>
          ${opts.services.map(s =>
            `<option value="${s.id}" ${s.id === draft.service_id ? "selected" : ""}>${esc(s.name)}</option>`).join("")}
          <option value="__new__">+ Add a new service</option>
        </select>
        <div id="newServicePanel"></div>`}
      ${navButtons(draft, { canNext: isMachi || !!draft.service_id })}
    </div>`;

  mainEl.querySelectorAll("[data-type]").forEach(b => {
    b.onclick = () => {
      draft.type = b.dataset.type;
      draft.purpose = draft.type === "machi" ? "patet" : "gujrela_nu";
      // Machi is never offsite - it happens at the fire.
      if (draft.type === "machi") { draft.is_offsite = false; draft.location = null; }
      renderStep();
    };
  });

  if (!isMachi) {
    const sel = document.getElementById("evService");
    sel.onchange = () => {
      if (sel.value === "__new__") return renderNewServicePanel(sel, draft);
      const svc = opts.services.find(s => String(s.id) === sel.value);
      draft.service_id = svc ? svc.id : null;
      draft.service_name = svc ? svc.name : "";
      renderStep();
    };
  }
  mainEl.querySelector("[data-wiz-next]").onclick = goNext;
}

function renderNewServicePanel(selectEl, draft) {
  const panel = document.getElementById("newServicePanel");
  panel.innerHTML = `
    <div class="card" style="margin-top:12px">
      <label>New service name</label>
      <input type="text" id="nsName" placeholder="e.g. Afringan">
      <div class="check-row">
        <input type="checkbox" id="nsOffsite">
        <label for="nsOffsite">Can be performed away from the fire temple</label>
      </div>
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
      const svc = await createService(state.currentAgyaryId, name, document.getElementById("nsOffsite").checked);
      delete state.formOptionsCache[state.currentAgyaryId];
      draft.service_id = svc.id;
      draft.service_name = svc.name;
      renderStep();
    } catch (e) {
      showError(e.message);
    }
  };
}

// ---------------------------------------------------------------------------
// Step 3 - Date and Roj/Mah, two views of one value
// ---------------------------------------------------------------------------
async function stepDate(draft) {
  if (!draft.roj) {
    try { await syncFromGregorian(draft); } catch (e) { /* shown below */ }
  }
  const opts = state.calendarOptions;
  const rojOptions = opts.roj.map(o => {
    const v = Number(o.id.replace("roj_", ""));
    return `<option value="${v}" ${v === draft.roj && draft.mah !== 13 ? "selected" : ""}>${esc(o.title)}</option>`;
  }).join("");
  const mahOptions = opts.mah.map(o => {
    const v = Number(o.id.replace("mah_", ""));
    return `<option value="${v}" ${v === draft.mah ? "selected" : ""}>${esc(o.title)}</option>`;
  }).join("");

  mainEl.innerHTML = `
    ${stepsBar(2)}
    <div class="card">
      <h2>When?</h2>
      <div class="synced" id="syncBox">
        <label>Date</label>
        <input type="date" id="evDate" value="${esc(draft.gregorian)}">
        <div class="row" style="margin-top:8px">
          <div><label>Roj</label><select id="evRoj">${rojOptions}</select></div>
          <div><label>Mah</label><select id="evMah">${mahOptions}</select></div>
        </div>
        <div class="sync-note" id="syncNote">${esc(draft.parsiLabel || "")}</div>
      </div>
      ${draft.isGatha && draft.type === "machi"
        ? '<div class="error-banner" style="margin-top:12px">Machi cannot be booked on a Gatha day. Pick another date.</div>'
        : ""}
      <div style="margin-top:12px">
        <button class="ghost small" id="evPick">Pick from the calendar</button>
      </div>
      <div id="evPickPanel"></div>
      ${navButtons(draft, { canNext: !(draft.isGatha && draft.type === "machi") })}
    </div>`;

  const box = document.getElementById("syncBox");
  const note = document.getElementById("syncNote");
  const busy = (on) => box.classList.toggle("syncing", on);

  document.getElementById("evDate").onchange = async (e) => {
    draft.gregorian = e.target.value;
    if (!draft.gregorian) return;
    busy(true);
    try { await syncFromGregorian(draft); } catch (err) { showError(err.message); }
    busy(false);
    renderStep();
  };

  const onParsiChange = async () => {
    draft.roj = Number(document.getElementById("evRoj").value);
    draft.mah = Number(document.getElementById("evMah").value);
    busy(true);
    note.textContent = "Finding that day...";
    try { await syncFromParsiFields(draft); } catch (err) { showError(err.message); }
    busy(false);
    renderStep();
  };
  document.getElementById("evRoj").onchange = onParsiChange;
  document.getElementById("evMah").onchange = onParsiChange;

  document.getElementById("evPick").onclick = async () => {
    const panel = document.getElementById("evPickPanel");
    if (panel.innerHTML) { panel.innerHTML = ""; return; }
    const view = { mode: "month", focus: draft.gregorian, parsiMonth: null, selectedDay: draft.gregorian };
    const draw = () => renderCalendar(panel, {
      view,
      loadItems: async () => [],          // a picker shows days, not events
      onDayPick: async (day) => {
        draft.gregorian = day;
        try { await syncFromGregorian(draft); } catch (e) { showError(e.message); }
        renderStep();
      },
      rerender: draw,
    });
    await draw();
  };

  mainEl.querySelector("[data-wiz-next]").onclick = goNext;
}

// ---------------------------------------------------------------------------
// Step 4 - Time or Geh, purpose, and (services only) offsite
// ---------------------------------------------------------------------------
async function stepTime(draft) {
  const isMachi = draft.type === "machi";
  const aid = state.currentAgyaryId;
  const opts = (await servicesFor(aid)) || { services: [] };
  const service = opts.services.find(s => s.id === draft.service_id);
  const offsiteCapable = !!(service && service.offsite_capable);

  const purposes = isMachi ? MACHI_PURPOSE_DISPLAY : SERVICE_PURPOSE_DISPLAY;

  mainEl.innerHTML = `
    ${stepsBar(3)}
    <div class="card">
      <h2>${isMachi ? "Which Geh?" : "What time?"}</h2>
      ${isMachi ? `
        <label>Geh</label>
        <select id="evGeh">${GEHS.map(([g, n]) =>
          `<option value="${g}" ${g === draft.geh ? "selected" : ""}>${n}</option>`).join("")}</select>
      ` : `
        <label>Time</label>
        <input type="time" id="evTime" value="${esc(draft.time)}">
      `}
      <label>Purpose</label>
      <select id="evPurpose">${Object.entries(purposes).map(([k, v]) =>
        `<option value="${k}" ${k === draft.purpose ? "selected" : ""}>${esc(v)}</option>`).join("")}</select>
      ${!isMachi && offsiteCapable ? `
        <div class="check-row" style="margin-top:12px">
          <input type="checkbox" id="evOffsite" ${draft.is_offsite ? "checked" : ""}>
          <label for="evOffsite">Performed away from the fire temple</label>
        </div>
        <div id="evLocationWrap" class="${draft.is_offsite ? "" : "hidden"}">
          <label>Where</label>
          <input type="text" id="evLocation" placeholder="e.g. 14 Cusrow Baug, Colaba"
                 value="${esc(draft.location || "")}">
        </div>` : ""}
      ${navButtons(draft)}
    </div>`;

  if (isMachi) {
    document.getElementById("evGeh").onchange = (e) => { draft.geh = Number(e.target.value); };
  } else {
    document.getElementById("evTime").onchange = (e) => { draft.time = e.target.value; };
  }
  document.getElementById("evPurpose").onchange = (e) => {
    draft.purpose = e.target.value;
    // A machi's name shape follows its purpose, so the names step has to be
    // rebuilt when it changes.
    renderStep();
  };

  const offsite = document.getElementById("evOffsite");
  if (offsite) {
    offsite.onchange = () => {
      draft.is_offsite = offsite.checked;
      document.getElementById("evLocationWrap").classList.toggle("hidden", !offsite.checked);
      if (!offsite.checked) draft.location = null;
    };
    const loc = document.getElementById("evLocation");
    if (loc) loc.oninput = () => { draft.location = loc.value.trim() || null; };
  }

  mainEl.querySelector("[data-wiz-next]").onclick = goNext;
}

// ---------------------------------------------------------------------------
// Step 5 - Names
// ---------------------------------------------------------------------------
async function stepNames(draft) {
  const isMachi = draft.type === "machi";
  mainEl.innerHTML = `
    ${stepsBar(4)}
    <div class="card">
      <h2>Names</h2>
      <p class="meta">Prefilled from ${esc(draft.behdin.name)}'s saved names. Edits here apply to this
        ceremony; tick below to update their saved list too.</p>
      <div id="namesRegion"></div>
      ${draft.behdin.id ? `
        <div class="check-row" style="margin-top:16px">
          <input type="checkbox" id="evSaveNames" ${draft.savedNamesTouched ? "checked" : ""}>
          <label for="evSaveNames">Also update this behdin's saved names</label>
        </div>` : ""}
      ${navButtons(draft)}
    </div>`;

  const region = document.getElementById("namesRegion");
  renderNamesEditor(region, isMachi, draft.purpose, draft.names);

  const save = document.getElementById("evSaveNames");
  if (save) save.onchange = () => { draft.savedNamesTouched = save.checked; };

  mainEl.querySelector("[data-wiz-next]").onclick = () => {
    const rows = collectNames(region, isMachi, draft.purpose);
    const problem = validateNames(rows);
    if (problem) return showError(problem);
    if (!rows.length) return showError("Please enter at least one name.");
    draft.names = rows;
    goNext();
  };
}

// ---------------------------------------------------------------------------
// Step 6 - Confirm and save
// ---------------------------------------------------------------------------
async function stepConfirm(draft) {
  const isMachi = draft.type === "machi";
  const when = isMachi
    ? `${gregLabel(draft.gregorian)} · ${GEH_NAME_BY_NUM[draft.geh]} Geh`
    : `${gregLabel(draft.gregorian)} · ${draft.time}`;
  const what = isMachi ? `Machi (${MACHI_PURPOSE_DISPLAY[draft.purpose]})` : draft.service_name || "Service";

  mainEl.innerHTML = `
    ${stepsBar(5)}
    <div class="card">
      <h2>Confirm</h2>
      <div class="list-row"><div class="lr-main"><b>${esc(draft.behdin.name)}</b>
        <span>${esc(draft.behdin.phone)}</span></div></div>
      <div class="list-row"><div class="lr-main"><b>${esc(what)}</b><span>${esc(draft.parsiLabel || "")}</span></div></div>
      <div class="list-row"><div class="lr-main"><b>${esc(when)}</b>
        <span>${draft.is_offsite ? esc(draft.location || "Offsite") : "At the fire temple"}</span></div></div>
      <div class="list-row"><div class="lr-main"><b>${draft.names.length} name${draft.names.length === 1 ? "" : "s"}</b>
        <span>${esc(draft.names.map(n => n.name).join(", "))}</span></div></div>
      <div id="conflictPanel"></div>
      ${navButtons(draft, { nextLabel: draft.edit ? "Save changes" : "Book it" })}
    </div>`;

  mainEl.querySelector("[data-wiz-next]").onclick = () => save(draft);
  if (draft.conflict) renderConflict(draft);
}

async function save(draft) {
  const aid = state.currentAgyaryId;
  const btn = mainEl.querySelector("[data-wiz-next]");
  btn.disabled = true;
  draft.conflict = null;

  try {
    if (draft.type === "machi") {
      const body = {
        behdin_phone: draft.behdin.phone,
        behdin_name: draft.behdin.name,
        roj: draft.roj, mah: draft.mah, year: draft.year,
        geh: draft.geh, gregorian: draft.gregorian,
        purpose: draft.purpose, names: draft.names,
      };
      const res = draft.edit ? await editMachi(aid, draft.edit.id, body) : await addMachi(aid, body);
      if (!res.confirmed) {
        // The server hands back concrete free slots when a geh is taken.
        // The old build threw this away and showed a generic message.
        draft.conflict = res.alternatives;
        btn.disabled = false;
        return renderConflict(draft);
      }
      await persistSavedNames(draft);
      finish(draft, "machi", draft.edit ? draft.edit.id : res.machi_id);
    } else {
      const body = {
        behdin_phone: draft.behdin.phone,
        behdin_name: draft.behdin.name,
        service_id: draft.service_id,
        ceremony_datetime: `${draft.gregorian}T${draft.time}:00`,
        purpose: draft.purpose,
        names: draft.names,
        location: draft.is_offsite ? draft.location : null,
        is_offsite: !!draft.is_offsite,
      };
      const res = draft.edit ? await editBooking(aid, draft.edit.id, body) : await addBooking(aid, body);
      await persistSavedNames(draft);
      if (res.calendar_conflict) {
        showInfo("Saved. Note: this overlaps something else already in your calendar.");
      }
      finish(draft, "booking", draft.edit ? draft.edit.id : res.booking_id);
    }
  } catch (e) {
    btn.disabled = false;
    showError(e.message);
  }
}

/** Section-wholesale, because that is the only shape the API takes - a pair
 *  is two names of one status, which is a property of the set. */
async function persistSavedNames(draft) {
  if (!draft.savedNamesTouched || !draft.behdin.id) return;
  const aid = state.currentAgyaryId;
  const pairs = draft.names.filter(n => n.section === "pair");
  const farm = draft.names.filter(n => n.section === "farmayeshne");
  try {
    await putSavedNames(aid, draft.behdin.id, "pair", pairs);
    await putSavedNames(aid, draft.behdin.id, "farmayeshne", farm);
  } catch (e) {
    // The ceremony is already booked; a failure to also update the saved
    // list is worth saying out loud but must not read as "nothing saved".
    showInfo("Booked, but couldn't update the saved names: " + e.message);
  }
}

function renderConflict(draft) {
  const panel = document.getElementById("conflictPanel");
  const alt = draft.conflict || {};
  const sameDay = alt.same_day_gehs || [];
  const nextDays = alt.same_geh_next_days || [];

  panel.innerHTML = `
    <div class="error-banner" style="margin-top:12px">
      ${esc(GEH_NAME_BY_NUM[draft.geh])} Geh is already taken on ${esc(gregLabel(draft.gregorian))}.
    </div>
    ${sameDay.length ? `<div class="names-group-label"><b>Free that same day</b></div>
      ${sameDay.map(g => `<div class="alt-slot" data-alt-geh="${g}">
        <span class="when">${esc(GEH_NAME_BY_NUM[g])} Geh</span><span>Use this</span></div>`).join("")}` : ""}
    ${nextDays.length ? `<div class="names-group-label"><b>Same Geh, next available days</b></div>
      ${nextDays.map((o, i) => `<div class="alt-slot" data-alt-day="${i}">
        <span class="when">${esc(gregLabel(o.gregorian))} · ${esc(GEH_NAME_BY_NUM[o.geh])} Geh</span>
        <span>Use this</span></div>`).join("")}` : ""}
    ${!sameDay.length && !nextDays.length
      ? '<p class="meta">Nothing else is free nearby - try a different date.</p>' : ""}`;

  panel.querySelectorAll("[data-alt-geh]").forEach(el => {
    el.onclick = () => { draft.geh = Number(el.dataset.altGeh); draft.conflict = null; renderStep(); };
  });
  panel.querySelectorAll("[data-alt-day]").forEach(el => {
    el.onclick = async () => {
      const o = nextDays[Number(el.dataset.altDay)];
      draft.roj = o.roj; draft.mah = o.mah; draft.year = o.year;
      draft.geh = o.geh; draft.gregorian = o.gregorian;
      draft.conflict = null;
      try { await syncFromGregorian(draft); } catch (e) { /* label only */ }
      renderStep();
    };
  });
  panel.scrollIntoView({ block: "nearest" });
}

function finish(draft, kind, id) {
  const aid = state.currentAgyaryId;
  state.calendar.focus = draft.gregorian;
  state.calendar.mode = "day";
  state.draft = null;
  navigate(kind === "machi" ? `#/machi/${aid}/${id}` : `#/booking/${aid}/${id}`);
}
