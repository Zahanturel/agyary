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
  convertDate, fromParsi,
  bookingDetail,
} from "../api.js";
import { state, primarySystem } from "../state.js";
import { renderCalendar } from "../calendar.js";
import { renderAddBehdin } from "../behdin_add.js";
import { loadDraft, saveDraft, clearDraft, offerDraft, restoredDate } from "../drafts.js";
import { chrome, mainEl, showFab, showError, showInfo, refreshHeader, loading } from "../ui.js";
import { esc, istYmd, istHm, todayIst, gregLabel } from "../util.js";
import { navigate, back, navGuard } from "../router.js";

function system() {
  return primarySystem();
}

function blankDraft(prefill = {}) {
  return {
    kind: "booking",
    // null = "whatever the behdin has saved", resolved by the review step; an
    // array once the mobed has seen and possibly changed them.
    names: null,
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
    // A new event is asked one question at a time; which one is kept here.
    step: 1,
  };
}

// ---------------------------------------------------------------------------
// Entry points
// ---------------------------------------------------------------------------
// The unfinished event the mobed left, kept by drafts.js and offered back (not
// silently applied) the next time they open a new one.
const DRAFT_KEY = "event";

/** Only the content is kept. Roj, Mah and the Parsi label are worked out again
 *  from the date - carrying them is how a stale Roj ends up on a new booking. */
function keep(draft) {
  if (draft.edit) return;
  if (!draft.behdin) return clearDraft(DRAFT_KEY);
  saveDraft(DRAFT_KEY, {
    behdin: draft.behdin, names: draft.names, service_id: draft.service_id,
    service_name: draft.service_name, gregorian: draft.gregorian, time: draft.time,
  });
}

async function open(draft) {
  state.draft = draft;
  await syncFromGregorian(draft);
  await render(draft);
}

export async function renderNewEvent() {
  chrome(true);
  refreshHeader();
  showFab(false);

  // Already part-way through right here - back from the review step, or from
  // adding a behdin: carry on, nothing to ask.
  const held = state.draft;
  if (held && held.kind === "booking" && !held.edit && !held.prefill) return open(held);

  // Otherwise this is a new event, started from the +. If an unfinished one
  // was left, ask before doing anything with it.
  const prefill = (held && held.prefill) || {};
  const stored = loadDraft(DRAFT_KEY);
  if (!stored || !stored.behdin) return open(blankDraft(prefill));

  offerDraft({
    title: "Unfinished event",
    summary: [
      stored.behdin.name,
      stored.service_name || "No service chosen yet",
      `${gregLabel(stored.gregorian)}${stored.time ? " · " + stored.time : ""}`,
    ],
    onStartNew: () => { clearDraft(DRAFT_KEY); open(blankDraft(prefill)); },
    onContinue: async () => {
      const draft = blankDraft(prefill);
      draft.behdin = stored.behdin;
      draft.names = stored.names || null;
      draft.service_id = stored.service_id || null;
      draft.service_name = stored.service_name || "";
      draft.time = stored.time || draft.time;
      // A date that has gone by is not carried into a new booking.
      const [date, replaced] = restoredDate(stored.gregorian, prefill.gregorian);
      draft.gregorian = date;
      await open(draft);
      if (replaced) showInfo(`The date you had chosen has passed, so this is for ${gregLabel(date)}.`);
    },
  });
}

export async function renderEditEvent({ kind, id }) {
  chrome(true);
  refreshHeader();
  showFab(false);
  loading();
  const alive = navGuard();

  if (kind === "machi") {
    showError("Machi editing is not available in this view.");
    return navigate("#/calendar", { replace: true });
  }

  // Coming back from the review step ("Edit details"): the mobed's unsaved
  // changes are in the draft. Rebuilding it from the server here threw them
  // away - the time went back to what was saved.
  const held = state.draft;
  if (held && held.edit && held.edit.id === Number(id) && held.returning) {
    held.returning = false;
    return render(held);
  }

  const aid = state.currentAgyaryId;
  let detail;
  try {
    detail = await bookingDetail(aid, Number(id));
  } catch (e) {
    if (!alive()) return;
    return showError(e.message);
  }
  if (!alive()) return;

  const draft = blankDraft();
  draft.edit = { kind, id: Number(id) };
  draft.behdin = { id: null, name: detail.behdin_name, phone: detail.behdin_phone };
  draft.names = detail.names;   // the event's own, as saved
  draft.service_id = detail.service_id;
  draft.gregorian = istYmd(detail.ceremony_datetime);
  draft.time = istHm(detail.ceremony_datetime);
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
  keep(draft);
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

  // A new event is asked one question at a time. Editing one is a single page:
  // everything is already there and only a detail changes.
  const stepped = !draft.edit;
  const total = 4;
  const step = stepped ? Math.min(Math.max(draft.step || 1, 1), total) : 0;
  const lbl = (text, style = "") => stepped ? "" : `<label ${style ? `style="${style}"` : ""}>${text}</label>`;
  const sec = (n, question, body) => stepped
    ? `<div class="step-sec${step === n ? "" : " hidden"}"><h2 class="step-q">${question}</h2>${body}</div>`
    : `<div>${body}</div>`;

  mainEl.innerHTML = `
    <div class="card${stepped ? " stepped" : ""}">
      ${stepped ? `<div class="step-count">Step ${step} of ${total}</div>
        <div class="step-bar">${[1, 2, 3, 4].map(n => `<i class="${n <= step ? "on" : ""}"></i>`).join("")}</div>`
        : `<h2>Edit event</h2>`}

      ${sec(1, "Who is the event for?", `
        ${lbl("Behdin")}
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
        <div id="bhNewPanel"></div>`}`)}

      ${sec(2, "Which service?", `
        ${lbl("Service", "margin-top:16px")}
        <select id="evService">
          <option value="" ${!draft.service_id ? "selected" : ""} disabled>Select a service...</option>
          ${opts.services.map(s =>
            `<option value="${s.id}" ${s.id === draft.service_id ? "selected" : ""}>${esc(s.name)}</option>`).join("")}
          <option value="__new__">+ Add a new service</option>
        </select>
        <div id="newServicePanel"></div>`)}

      ${sec(3, "Which day?", `
        ${lbl("Date", "margin-top:16px")}
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
        <div id="evPickPanel"></div>`)}

      ${sec(4, "What time?", `
        ${lbl("Time", "margin-top:16px")}
        <input type="time" id="evTime" value="${esc(draft.time)}">`)}

      <!-- Actions -->
      <div class="wizard-nav" style="margin-top:20px">
        ${stepped
          ? `<button class="secondary" id="evBack">${step === 1 ? "Cancel" : "Back"}</button>
             <button id="evNext">${step === total ? "Review" : "Next"}</button>`
          : `<button class="ghost" id="evCancel">Cancel</button>
             <button id="evSave">Review</button>`}
      </div>
    </div>`;

  // --- Behdin wiring ---
  if (chosen) {
    document.getElementById("bhChange").onclick = () => { draft.behdin = null; draft.names = null; render(draft); };
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
    draft.names = null;   // the default names depend on the service
    keep(draft);
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
  document.getElementById("evTime").onchange = (e) => { draft.time = e.target.value; keep(draft); };

  // --- Cancel / Back / Next / Save ---
  const cancel = () => {
    state.draft = null;
    if (!draft.edit) clearDraft(DRAFT_KEY);
    back(draft.edit ? `#/booking/${aid}/${draft.edit.id}` : "#/calendar");
  };
  if (stepped) {
    const go = (n) => { draft.step = n; keep(draft); render(draft); window.scrollTo(0, 0); };
    document.getElementById("evBack").onclick = () => (step === 1 ? cancel() : go(step - 1));
    document.getElementById("evNext").onclick = () => {
      if (step === 1 && !draft.behdin) return showError("Please choose who the event is for.");
      if (step === 2 && !draft.service_id) return showError("Please choose a service.");
      if (step === 3 && !draft.gregorian) return showError("Please choose a day.");
      if (step === 4 && !draft.time) return showError("Please choose a time.");
      if (step === total) return save(draft);
      go(step + 1);
    };
  } else {
    document.getElementById("evCancel").onclick = cancel;
    document.getElementById("evSave").onclick = () => save(draft);
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
  draft.names = null;   // a different behdin has different saved names
  if (!draft.edit) draft.step = 2;
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
// Next: review. Saving happens there, after the mobed has seen the slip.
// ---------------------------------------------------------------------------
function save(draft) {
  if (!draft.behdin) return showError("Please select a behdin.");
  if (!draft.service_id) return showError("Please select a service.");
  if (!draft.gregorian) return showError("Please select a date.");
  if (!draft.time) return showError("Please select a time.");
  // Replace, so the form and the review are two steps of one screen: Back
  // from the finished slip goes to the calendar, not back through them.
  navigate("#/event/review", { replace: true });
}
