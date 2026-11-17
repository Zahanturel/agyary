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
import { setRepeat, repeatCountHtml, wireRepeatCount, repeatCountProblem } from "../repeat.js";
import {
  chrome, mainEl, showFab, showError, showInfo, refreshHeader, loading, screenFailed, toTop,
} from "../ui.js";
import { flagProblems } from "../fielderrors.js";
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
    recurringCount: null,
    // A new machi is asked one question at a time; which one is kept here.
    step: 1,
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
    recurringCount: draft.recurringCount,
  });
}

async function open(draft) {
  const alive = navGuard();
  state.draft = draft;
  // The screen being left comes off at once. Until the form was ready it used
  // to stay on the page, still tappable, under this form's address.
  loading();
  const failed = await syncFromGregorian(draft);
  if (!alive()) return;
  // A machi is saved with its Roj and Mah, so a form with none to fall back
  // on cannot be filled in rightly.
  if (failed && draft.roj == null) return screenFailed(failed, () => open(draft));
  await loadAvailableGehs(draft);
  if (!alive()) return;
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
    onStartNew: () => { clearDraft(DRAFT_KEY); return open(blankDraft(prefill)); },
    onContinue: async () => {
      const draft = blankDraft(prefill);
      draft.behdin = stored.behdin;
      draft.names = stored.names || null;
      draft.purpose = stored.purpose || "patet";
      draft.recurring = stored.recurring || null;
      draft.recurringCount = stored.recurringCount || null;
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
    // In the page, not a passing message over "Loading...". A machi that is
    // not on file will not be there on a second try either.
    return screenFailed(e.message, e.status === 404 ? null : () => renderEditMachi({ id }));
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
  // If this cannot be reached the machi's own saved Roj and Mah stand, and
  // they are right for its date - so that is quiet.
  await syncFromGregorian(draft);
  await loadAvailableGehs(draft);
  if (!alive()) return;
  state.draft = draft;
  render(draft);
}

// ---------------------------------------------------------------------------
// Date <-> Roj/Mah sync
// ---------------------------------------------------------------------------
// Both answer "" when the day was worked out, and otherwise say why not, with
// the draft's Roj, Mah and label left as they were. The caller decides what
// that means: it used to be swallowed here, which left a new date on the form
// beside the old date's Roj - and a machi is saved with both.
async function syncFromGregorian(draft) {
  try {
    const p = await convertDate(draft.gregorian, system());
    draft.isGatha = p.is_gatha;
    draft.roj = p.is_gatha ? p.gatha_index : p.roj;
    draft.mah = p.is_gatha ? 13 : p.mah;
    draft.year = p.year;
    draft.parsiLabel = p.display;
    return "";
  } catch (e) {
    return e.message || "Please try again.";
  }
}

async function syncFromParsiFields(draft) {
  try {
    const p = await fromParsi(draft.roj, draft.mah, system());
    draft.gregorian = p.gregorian_date;
    draft.year = p.year;
    draft.isGatha = p.is_gatha;
    draft.parsiLabel = p.display;
    return "";
  } catch (e) {
    return e.message || "Please try again.";
  }
}

async function loadAvailableGehs(draft) {
  if (!draft.gregorian) return;
  try {
    const res = await bookableGehs(state.currentAgyaryId, draft.gregorian);
    draft.availableGehs = res.bookable || res;
  } catch (e) {
    // Quiet on purpose: every geh is offered rather than none. One that is
    // already taken is refused by the review step, which asks the server
    // again before anything is saved.
    draft.availableGehs = [1, 2, 3, 4, 5];
  }
}

// ---------------------------------------------------------------------------
// The single screen
// ---------------------------------------------------------------------------
async function render(draft) {
  // For what is wired below that waits on the server before redrawing.
  const alive = navGuard();
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

  // A new machi is asked one question at a time. Editing one is a single page:
  // everything is already there and only a detail changes.
  const stepped = !draft.edit;
  const total = 4;
  const step = stepped ? Math.min(Math.max(draft.step || 1, 1), total) : 0;
  const lbl = (text, style = "") => stepped ? "" : `<label ${style ? `style="${style}"` : ""}>${text}</label>`;
  const sec = (n, question, body) => stepped
    ? `<div class="step-sec${step === n ? "" : " hidden"}"><h2 class="step-q">${question}</h2>${body}</div>`
    : `<div>${body}</div>`;
  const choice = (name, value, text, on) => `<label class="choice${on ? " on" : ""}">
      <input type="radio" name="${name}" value="${value}" ${on ? "checked" : ""}><span>${text}</span></label>`;

  mainEl.innerHTML = `
    <div class="card${stepped ? " stepped" : ""}">
      ${stepped ? `<div class="step-count">Step ${step} of ${total}</div>
        <div class="step-bar">${[1, 2, 3, 4].map(n => `<i class="${n <= step ? "on" : ""}"></i>`).join("")}</div>`
        : `<h2>Edit machi</h2>`}

      ${sec(1, "Who is the machi for?", `
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

      ${sec(2, "What is it for?", `
        ${lbl("Purpose", "margin-top:16px")}
        <div id="mcPurpose">
          ${choice("mcPurpose", "patet", "Patet, for the departed", draft.purpose === "patet")}
          ${choice("mcPurpose", "tandarosti", "Tandarosti, for the living", draft.purpose === "tandarosti")}
        </div>`)}

      ${sec(3, "When is it?", `
        ${lbl("Date", "margin-top:16px")}
        <div class="synced" id="syncBox">
          <input type="date" id="mcDate" value="${esc(draft.gregorian)}">
          <div class="row" style="margin-top:8px">
            <div><label>Roj</label><select id="mcRoj">${rojOptions}</select></div>
            <div><label>Mah</label><select id="mcMah">${mahOptions}</select></div>
          </div>
          <div class="sync-note" id="syncNote">${esc(draft.parsiLabel || "")}</div>
        </div>

        ${lbl("Geh", "margin-top:16px")}
        ${stepped ? '<p class="meta" style="margin:12px 0 4px">Choose the time of day</p>' : ""}
        <div class="geh-grid" id="gehGrid">
          ${GEHS.map(([num, name]) => {
            const avail = draft.availableGehs.includes(num);
            const sel = draft.geh === num;
            return `<button class="geh-btn${sel ? " selected" : ""}${!avail && !sel ? " taken" : ""}"
              data-geh="${num}" ${!avail && !sel ? "disabled" : ""}>${esc(name)}${!avail && !sel ? " · taken" : ""}</button>`;
          }).join("")}
        </div>`)}

      ${!draft.edit ? sec(4, "Does it repeat?", `
        <div id="mcRecur">
          ${choice("mcRecur", "", "Don't repeat", !draft.recurring)}
          ${choice("mcRecur", "monthly", "Every month, on the same Roj", draft.recurring === "monthly")}
          ${choice("mcRecur", "yearly", "Every year, on the same Roj and Mah (a birthday or anniversary)", draft.recurring === "yearly")}
        </div>
        ${repeatCountHtml(draft, "mcCount")}`) : ""}

      <!-- Actions -->
      <div class="wizard-nav" style="margin-top:20px">
        ${stepped
          ? `<button class="secondary" id="mcBack">${step === 1 ? "Cancel" : "Back"}</button>
             <button id="mcNext">${step === total ? "Review" : "Next"}</button>`
          : `<button class="ghost" id="mcCancel">Cancel</button>
             <button id="mcSave">Review</button>`}
      </div>
    </div>`;

  // --- Behdin wiring ---
  if (chosen) {
    document.getElementById("bhChange").onclick = () => { draft.behdin = null; draft.names = null; render(draft); };
  } else {
    wireSearch(draft, alive);
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
  document.querySelectorAll('input[name="mcPurpose"]').forEach(r => {
    r.onchange = () => {
      draft.purpose = r.value;
      draft.names = null;   // patet and tandarosti take different names
      keep(draft);
      render(draft);
    };
  });

  // --- Date wiring ---
  const box = document.getElementById("syncBox");
  const note = document.getElementById("syncNote");
  const busy = (on) => box.classList.toggle("syncing", on);

  // If the Roj and Mah of a new date cannot be worked out, the date goes back
  // to what it was - never a new date beside the old date's Roj, since a machi
  // is saved with both - and the mobed is told. The free gehs are asked for
  // only when the day really changed.
  document.getElementById("mcDate").onchange = async (e) => {
    const was = draft.gregorian;
    draft.gregorian = e.target.value;
    if (!draft.gregorian) return;
    busy(true);
    const failed = await syncFromGregorian(draft);
    if (failed) draft.gregorian = was;
    else await loadAvailableGehs(draft);
    if (!alive()) return;   // gone to another screen meanwhile: nothing here to redraw
    await render(draft);
    if (failed) showError("The date was not changed. " + failed);
  };

  const onParsiChange = async () => {
    const was = { roj: draft.roj, mah: draft.mah };
    draft.roj = Number(document.getElementById("mcRoj").value);
    draft.mah = Number(document.getElementById("mcMah").value);
    busy(true);
    note.textContent = "Finding that day...";
    const failed = await syncFromParsiFields(draft);
    // No such day could be found: back to the Roj and Mah of the date shown.
    if (failed) Object.assign(draft, was);
    else await loadAvailableGehs(draft);
    if (!alive()) return;
    await render(draft);
    if (failed) showError("The Roj and Mah were not changed. " + failed);
  };
  document.getElementById("mcRoj").onchange = onParsiChange;
  document.getElementById("mcMah").onchange = onParsiChange;

  // --- Geh wiring ---
  const gehGrid = document.getElementById("gehGrid");
  gehGrid.querySelectorAll(".geh-btn:not([disabled])").forEach(btn => {
    btn.onclick = () => {
      draft.geh = Number(btn.dataset.geh);
      document.querySelectorAll(".geh-btn").forEach(b => b.classList.remove("selected"));
      btn.classList.add("selected");
      keep(draft);
      // A tap on a button is not a "change" as a typed-in field has one, so
      // say it for the grid: that is what takes a "choose the time of day"
      // mark off it (fielderrors.js clears a mark when its target changes).
      gehGrid.dispatchEvent(new Event("change"));
    };
  });

  // --- Recurring wiring ---
  document.querySelectorAll('input[name="mcRecur"]').forEach(r => {
    r.onchange = () => { setRepeat(draft, r.value); keep(draft); render(draft); };
  });
  wireRepeatCount(draft, "mcCount", keep);

  // --- Cancel / Back / Next / Save ---
  const cancel = () => {
    state.draft = null;
    if (!draft.edit) clearDraft(DRAFT_KEY);
    back(draft.edit ? `#/machi/${state.currentAgyaryId}/${draft.edit.id}` : "#/board");
  };
  if (stepped) {
    // Another step is another page to the person filling it in: it opens at
    // its top, once it has been drawn.
    const go = async (n) => { draft.step = n; keep(draft); await render(draft); if (alive()) toTop(); };
    // What this step still needs is said on the control itself, which is on screen.
    const missing = (target, message) => void flagProblems(mainEl, [{ target, message }]);
    document.getElementById("mcBack").onclick = () => (step === 1 ? cancel() : go(step - 1));
    document.getElementById("mcNext").onclick = () => {
      if (step === 1 && !draft.behdin) return missing("#bhSearch", "Please choose who the machi is for.");
      if (step === 3 && !draft.gregorian) return missing("#mcDate", "Please choose a date.");
      if (step === 3 && !draft.geh) return missing("#gehGrid", "Please choose the time of day.");
      if (step === total) {
        const problem = repeatCountProblem(draft);
        if (problem) return missing("#mcCount", problem);
        return save(draft);
      }
      go(step + 1);
    };
  } else {
    document.getElementById("mcCancel").onclick = cancel;
    document.getElementById("mcSave").onclick = () => save(draft);
  }
}

// ---------------------------------------------------------------------------
// Behdin search
// ---------------------------------------------------------------------------
function wireSearch(draft, alive) {
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
      onCreated: (created) => choose(draft, created, alive),
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
      catch (e) {
        if (mine !== token) return;
        // Said under the box being typed in. A search that could not run
        // used to look exactly like one that found nobody.
        results.innerHTML = `<div class="field-msg" role="alert">Couldn't search: ${esc(e.message)}</div>`;
        // An add form already open takes its name from this box (its own name
        // row is hidden), so it must not be left holding an earlier spelling.
        const open = document.getElementById("abName");
        if (open && q.length >= 2) open.value = q;
        return;
      }
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
          el.onclick = () => choose(draft, matches[Number(el.dataset.i)], alive);
        });
        return;
      }

      results.innerHTML = "";
      // Two characters, so a single stray keystroke doesn't throw a form up.
      if (q.length >= 2) openAdd(q); else closeAdd();
    }, 220);
  };
  // Ready to type in, without the page being moved to it: the step has just
  // opened at its top and the box is there.
  input.focus({ preventScroll: true });
}

/** Awaited by the add form, so its note follows the redraw. */
async function choose(draft, match, alive) {
  const id = match.id != null ? match.id : match.customer_id;
  draft.behdin = { id, name: match.name, phone: match.phone };
  draft.names = null;   // a different behdin has different saved names
  if (!draft.edit) draft.step = 2;
  // The add form asks the server first. If the mobed has gone to another
  // screen by the time it answers, the choice is kept on the draft for when
  // they come back, and nothing is drawn over the screen they are on.
  if (!alive()) return;
  await render(draft);
  // In a new machi that was the answer to the first question, and the next
  // one opens at its top - not wherever the list of matches had been scrolled
  // to. Editing redraws the one page it already is, so that stays put.
  if (!draft.edit && alive()) toTop();
}

// ---------------------------------------------------------------------------
// Next: review. Saving happens there, after the mobed has seen the slip.
// ---------------------------------------------------------------------------
function save(draft) {
  const problems = [];
  if (!draft.behdin) problems.push({ target: "#bhSearch", message: "Please select a behdin." });
  if (!draft.purpose) problems.push({ target: "#mcPurpose", message: "Please select a purpose." });
  if (!draft.gregorian) problems.push({ target: "#mcDate", message: "Please select a date." });
  if (!draft.geh) problems.push({ target: "#gehGrid", message: "Please select a geh." });
  if (problems.length) {
    // The edit form is one page, so each is marked on its own control. A new
    // machi has already checked every step as it was passed; should one still
    // be missing its control is on a hidden step, so it is said in words.
    if (draft.edit) flagProblems(mainEl, problems);
    else showError(problems[0].message);
    return;
  }
  navigate("#/machi/review", { replace: true });
}
