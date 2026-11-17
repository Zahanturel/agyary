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
  listBehdins, memorialReminders, setBehdinReminders, consentWording, customerHistory, getBehdin, updateBehdin,
  createBehdin,
  getSavedNames, putSavedNames, listMemorials,
} from "../api.js";
import { state } from "../state.js";
import { canPickContacts, pickContacts, fillFromContact } from "../behdin_add.js";
import { renderNamesEditor, collectNames, validateNames } from "../names.js";
import {
  chrome, mainEl, showFab, showError, showInfo, flashInfo, flashError,
  refreshHeader, loading, backBar, loadFailedHtml, wireRetry, screenFailed, toTop,
} from "../ui.js";
import { esc, gregShort, phoneField, readPhone } from "../util.js";
import { navigate, back, navGuard } from "../router.js";
import { flagProblems, clearProblems } from "../fielderrors.js";
import { openDeleteBox, deleteResultText } from "../behdin_delete.js";
import { loadDraft, saveDraft, clearDraft, offerDraft } from "../drafts.js";

export async function renderBehdinList() {
  chrome(true);
  refreshHeader();
  // Exactly one add control on this screen: the icon in the header below.
  // No floating button as well.
  showFab(false);
  loading();
  const alive = navGuard();

  let rows = [];
  try {
    rows = await listBehdins(state.currentAgyaryId, "");
  } catch (e) {
    if (!alive()) return;
    // The whole list did not load: say so in the page, with a way to try
    // again, rather than a blank page under a message that goes away.
    return screenFailed(e.message, () => renderBehdinList());
  }
  if (!alive()) return;

  mainEl.innerHTML = `
    <div class="card" id="bhReminders" hidden>
      <div class="section-bar" id="bhRemindersBar">
        <div class="sb-text"><b>Reminders</b><span id="bhRemindersText"></span></div>
        <div class="sb-actions"><span class="chev">&rsaquo;</span></div>
      </div>
    </div>
    <div class="card">
      <div class="row tight" style="justify-content:space-between;align-items:center">
        <h2 style="margin:0">Behdins</h2>
        <button class="icon-add" id="bhAdd" title="Add a behdin" aria-label="Add a behdin">+</button>
      </div>
      <p class="meta">The behdins you look after.</p>
      <input type="text" id="bhFilter" aria-label="Search by name or phone" placeholder="Search by name or phone" autocomplete="off">
      <div id="bhRows" style="margin-top:8px"></div>
    </div>`;

  // Not worth holding the list for: the bar appears once it knows, and stays
  // away if there is nothing to remind or the call fails.
  memorialReminders(state.currentAgyaryId, 14).then((r) => {
    const bar = document.getElementById("bhReminders");
    if (!alive() || !bar || !r.items.length) return;
    const due = r.items.filter(o => o.due).length;
    document.getElementById("bhRemindersText").textContent =
      due ? `${due} to remind now, ${r.items.length - due} coming up`
          : `${r.items.length} coming up in the next 14 days`;
    bar.hidden = false;
    document.getElementById("bhRemindersBar").onclick = () => navigate("#/reminders");
  }).catch(() => {});

  const rowsEl = document.getElementById("bhRows");
  const paint = (list) => {
    rowsEl.innerHTML = list.length
      ? list.map(c => `<div class="search-result bh-row" data-cid="${c.id}">
          <div class="bh-av" aria-hidden="true">${esc((c.name || "?").trim().charAt(0).toUpperCase())}</div>
          <div class="bh-main"><div>${esc(c.name)}</div><div class="addr">${esc(c.phone)}</div></div>
          <button type="button" class="row-x" data-del aria-label="Delete ${esc(c.name)}" title="Delete this behdin">&times;</button>
        </div>`).join("")
      : `<p class="meta">No behdins yet - add one above, or they appear here when you book for them.</p>`;
    rowsEl.querySelectorAll("[data-cid]").forEach(el => {
      el.onclick = (e) => {
        const row = e.currentTarget;
        const c = list.find(b => String(b.id) === row.dataset.cid);
        if (e.target.closest("[data-del]")) return askDelete(row, c);
        if (e.target.closest(".row-confirm")) return;
        navigate(`#/behdins/${row.dataset.cid}`);
      };
    });
  };

  /** The x on a row: ask in place, then delete. Same call as the Delete button
   *  on the behdin's own page, so the same rules apply (the server says if
   *  something, such as a memorial, stops it). */
  const askDelete = (row, c) => {
    if (row.querySelector(".row-confirm")) return;
    row.classList.add("row-pending");
    row.insertAdjacentHTML("beforeend", `<div class="row-confirm" style="flex-basis:100%;display:block"></div>`);
    const box = row.querySelector(".row-confirm");
    const close = () => { row.classList.remove("row-pending"); box.remove(); };
    openDeleteBox(box, state.currentAgyaryId, c, {
      onCancel: close,
      onError: (m) => { close(); showError(m); },
      onDone: (r) => {
        rows = rows.filter(b => b.id !== c.id);
        row.remove();
        showInfo(deleteResultText(c.name, r));
      },
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
      } catch (err) {
        // The last good list stays on screen, but it is not what was asked
        // for: say so, or a behdin who is on file reads as one who is not.
        if (mine === token) showError("Couldn't search: " + err.message);
      }
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
  // "event" is the mobed app's New Event screen, "machi" is the Machi
  // Board's New Machi screen - both share this page rather than their own
  // cramped inline form.
  const RETURN_TARGETS = { event: "#/event/new", machi: "#/machi/new" };
  const returnTo = RETURN_TARGETS[state.behdinReturnTo] ? state.behdinReturnTo : null;
  const prefillName = state.behdinPrefillName || "";
  state.behdinReturnTo = null;
  state.behdinPrefillName = null;
  const backTarget = returnTo ? RETURN_TARGETS[returnTo] : "#/behdins";

  // A new behdin often comes because someone has died: give the date and the
  // whole schedule is laid out from it. Not when this page is a detour from a form.
  const memorialOk = !returnTo;

  // What was typed stays until the behdin is saved or this is cancelled -
  // going to another tab and coming back asks whether to continue it.
  const draftKey = `behdin-new:${returnTo || ""}`;
  const stored = loadDraft(draftKey);
  const ctx = { returnTo, prefillName, backTarget, memorialOk, draftKey, RETURN_TARGETS };
  if (!stored || !(stored.name || stored.phone || (stored.names || []).length || stored.memOn)) {
    return buildBehdinNew(ctx, {});
  }
  // The form takes the place of the question without the address changing, so
  // the router does not put it at the top: do that here.
  offerDraft({
    title: "Unfinished behdin",
    summary: [stored.name || "No name yet", stored.phone ? `${stored.cc || ""} ${stored.phone}`.trim() : "No number yet"],
    onStartNew: () => { clearDraft(draftKey); buildBehdinNew(ctx, {}); toTop(); },
    onContinue: () => { buildBehdinNew(ctx, stored); toTop(); },
  });
}

function buildBehdinNew({ returnTo, prefillName, backTarget, memorialOk, draftKey, RETURN_TARGETS }, held) {
  // One question at a time: who they are, the names for their prayers, and (unless this
  // page is a detour from a booking) whether they are keeping prayers for someone they
  // have lost - which carries straight on into the memorial's own steps.
  const total = memorialOk ? 3 : 2;
  const QUESTIONS = ["Who is the behdin?", "Names for prayers", "Someone they have lost?"];
  let step = 1;
  mainEl.innerHTML = `
    <div id="bnForm">
    <div class="card stepped">
      <div class="step-count" id="bnCount"></div>
      <div class="step-bar" id="bnBar">${Array.from({ length: total }, () => "<i></i>").join("")}</div>

      <div class="step-sec" data-bstep="1">
        <h2 class="step-q">${QUESTIONS[0]}</h2>
        ${canPickContacts() ? `
        <button class="secondary" id="bnImport" style="margin-bottom:12px">
          Import from contacts
        </button>` : ""}
        <label for="bnName">Name</label>
        <input type="text" id="bnName" placeholder="e.g. Behdin Zubin Mistry"
               autocomplete="off" value="${esc(prefillName)}">
        <label for="bnPhone">WhatsApp number</label>${phoneField("bnPhone")}
      </div>

      <div class="step-sec hidden" data-bstep="2">
        <h2 class="step-q">${QUESTIONS[1]}</h2>
        <p class="meta">Reused whenever this behdin books - here or over
          WhatsApp. Leave it for later if you don't have them to hand.</p>
        <div id="savedRegion"></div>
      </div>

      ${memorialOk ? `<div class="step-sec hidden" data-bstep="3">
        <h2 class="step-q">${QUESTIONS[2]}</h2>
        <p class="meta">Is the behdin keeping prayers for someone they have lost? We will ask about them next.</p>
        <label class="choice"><input type="radio" name="bnMem" value="no" checked><span>No, just add the behdin</span></label>
        <label class="choice"><input type="radio" name="bnMem" value="yes"><span>Yes, set up the prayers next</span></label>
      </div>` : ""}

      <div class="wizard-nav" style="margin-top:20px">
        <button class="secondary" id="bnCancel">Cancel</button>
        <button id="bnSave">Next</button>
      </div>
    </div>
    </div>`;

  const formRoot = document.getElementById("bnForm");
  const wantsMemorial = () => {
    const yes = document.querySelector('input[name="bnMem"][value="yes"]');
    return !!(yes && yes.checked);
  };
  const snapshot = () => ({
    name: document.getElementById("bnName").value,
    cc: document.getElementById("bnPhone_cc").value,
    phone: document.getElementById("bnPhone").value,
    names: collectNames(region, false, "gujrela_nu"),
    memOn: wantsMemorial(),
  });
  const keep = () => saveDraft(draftKey, snapshot());

  const region = document.getElementById("savedRegion");
  renderNamesEditor(region, false, "gujrela_nu", held.names || []);
  if (held.name && !prefillName) document.getElementById("bnName").value = held.name;
  if (held.cc) document.getElementById("bnPhone_cc").value = held.cc;
  if (held.phone) document.getElementById("bnPhone").value = held.phone;
  // Ready to type in, without the page being moved to it: a screen opens at its top.
  if (!document.getElementById("bnName").value) document.getElementById("bnName").focus({ preventScroll: true });

  if (canPickContacts()) {
    document.getElementById("bnImport").onclick = async () => {
      const btn = document.getElementById("bnImport");
      // Come from an event or machi, this page is for the ONE behdin being
      // booked, and goes back with them chosen: one contact only. From the
      // Behdins tab, several at once is a bulk import.
      const picked = await pickContacts({ multiple: !returnTo });
      if (!picked.length) return;

      // One contact fills the form so the saved names below can be added in
      // the same pass. Several is a different intent - a bulk import - and
      // saved names make no sense per-person there.
      if (picked.length === 1) {
        fillFromContact(picked[0], { nameId: "bnName", phoneId: "bnPhone" });
        keep();
        return;
      }
      // Several at once have no form to finish them in: a contact without
      // a name or a number is left out, and said so rather than called
      // "already on file".
      const usable = picked.filter(c => c.name && c.phone);
      btn.disabled = true;
      btn.textContent = "Importing...";
      let added = 0, onFile = 0, failed = picked.length - usable.length;
      for (const c of usable) {
        try {
          const r = await createBehdin(state.currentAgyaryId, c.name, c.phone);
          r.created ? added++ : onFile++;
        } catch (e) { failed++; }
      }
      const said = [];
      if (added) said.push(`${added} behdin${added > 1 ? "s" : ""} added`);
      if (onFile) said.push(`${onFile} already on file`);
      if (failed) said.push(`${failed} could not be added (no name or a number that is not valid)`);
      // Shown once the list has drawn: said here, going back wiped it.
      flashInfo(said.join(", "));
      // A batch has no single behdin to hand back to the event - land on
      // the same place either way, and the event flow's search will find
      // whichever of these he needs.
      back(backTarget);
    };
  }

  if (held.memOn) {
    const yes = document.querySelector('input[name="bnMem"][value="yes"]');
    if (yes) yes.checked = true;
  }
  const saveBtn = document.getElementById("bnSave");
  const cancelBtn = document.getElementById("bnCancel");

  // Every keystroke and choice in the form is kept (the memorial's controls
  // update mdraft first, then bubble up to here).
  formRoot.addEventListener("input", keep);
  formRoot.addEventListener("change", keep);
  region.addEventListener("names-changed", keep);
  // Removing or adding a pair is not typing, so a mark on the names would
  // otherwise stay after what it complained of had been dealt with.
  region.addEventListener("names-changed", () => clearProblems(formRoot));

  /** What the mobed typed, checked - or null after saying what is wrong. */
  const validate = () => {
    const name = document.getElementById("bnName").value.trim();
    const phone = readPhone("bnPhone");
    const problems = [];
    if (!name) problems.push({ target: "#bnName", message: "Please enter the behdin's name." });
    if (!phone) problems.push({ target: "#bnForm .phone-field", message: "Please enter a valid phone number." });

    const rows = collectNames(region, false, "gujrela_nu");
    // Check the names BEFORE creating anybody, or a bad pair leaves a
    // half-made behdin behind and the mobed retypes the lot.
    const namesProblem = rows.length ? validateNames(rows) : null;
    if (namesProblem) problems.push({ target: "#savedRegion", message: namesProblem });
    if (problems.length) { flagProblems(formRoot, problems); return null; }
    return { name, phone, rows };
  };

  /** Create the behdin and their saved names. `btn` is whatever was pressed, so it
   *  can be released on failure. With `goMemorial`, carry straight on into the
   *  memorial's own steps for this behdin. */
  const saveAll = async (v, goMemorial, btn) => {
    const aid = state.currentAgyaryId;
    btn.disabled = true;
    let created;
    try {
      created = await createBehdin(aid, v.name, v.phone);
    } catch (e) {
      btn.disabled = false;
      return showError(e.message);
    }
    clearDraft(draftKey);   // saved: nothing left to hold on to
    // Said on their record once it has opened (see the flash below), so the
    // words are about the page it is read on.
    const onFile = !created.created && !returnTo && !goMemorial
      ? `${created.name} was already on file - this is their record.` : "";

    // Back to the event/machi draft with this behdin chosen, rather than
    // their own record - that record has nothing to do with what's being
    // booked.
    const landing = () => {
      if (returnTo && state.draft) {
        state.draft.behdin = { id: created.id, name: created.name, phone: created.phone };
        state.draft.step = Math.max(state.draft.step || 1, 2);   // the behdin is chosen: on to the next question
        back(RETURN_TARGETS[returnTo]);
      } else {
        // The add form is finished; their record takes its place in history.
        navigate(`#/behdins/${created.id}`, { replace: true });
      }
    };

    let namesProblem = "";
    if (v.rows.length) {
      try {
        await putSavedNames(aid, created.id, "pair", v.rows.filter(n => n.section === "pair"));
        await putSavedNames(aid, created.id, "farmayeshne", v.rows.filter(n => n.section === "farmayeshne"));
      } catch (e) {
        namesProblem = `${created.name} was added, but the names didn't save: ${e.message}`;
      }
    }

    if (goMemorial) {
      if (namesProblem) flashError(namesProblem);
      return navigate(`#/behdins/${created.id}/memorials/new`, { replace: true });
    }
    // Both are shown once the next screen has drawn: said on this one, the
    // move away wipes them. There is room for one message, and names that did
    // not save matter more than having been on file already.
    if (namesProblem) flashError(namesProblem);
    else if (onFile) flashInfo(onFile);
    landing();
  };

  /** Draw the step that `step` says. It moves nothing: choosing Yes or No on
   *  the last step re-draws that same step, and the page must stay where it is. */
  const paintStep = () => {
    mainEl.querySelectorAll(".step-sec").forEach(el => el.classList.toggle("hidden", Number(el.dataset.bstep) !== step));
    mainEl.querySelectorAll("#bnBar i").forEach((el, i) => el.classList.toggle("on", i < step));
    document.getElementById("bnCount").textContent = `Step ${step} of ${total}`;
    cancelBtn.textContent = step === 1 ? "Cancel" : "Back";
    saveBtn.textContent = step < total ? "Next" : wantsMemorial() ? "Add and continue" : "Add behdin";
  };
  /** Go to step `n`. A different step is a new page to the person filling it
   *  in, so it opens at the top. */
  const goStep = (n) => {
    const moved = n !== step;
    step = n;
    paintStep();
    if (moved) toTop();
  };
  document.querySelectorAll('input[name="bnMem"]').forEach(r => r.addEventListener("change", paintStep));
  cancelBtn.onclick = () => {
    if (step > 1) return goStep(step - 1);
    clearDraft(draftKey);
    back(backTarget);
  };

  saveBtn.onclick = async () => {
    if (step === 1) {
      // Only the name and number are asked on this step.
      const problems = [];
      if (!document.getElementById("bnName").value.trim()) problems.push({ target: "#bnName", message: "Please enter the behdin's name." });
      if (!readPhone("bnPhone")) problems.push({ target: "#bnForm .phone-field", message: "Please enter a valid phone number." });
      if (problems.length) return flagProblems(formRoot, problems);
      return goStep(2);
    }
    if (step < total) return goStep(step + 1);
    const v = validate();
    if (!v) {   // something on an earlier step: go back to it and mark it there
      goStep((!document.getElementById("bnName").value.trim() || !readPhone("bnPhone")) ? 1 : 2);
      return void validate();
    }
    await saveAll(v, wantsMemorial(), saveBtn);
  };
  paintStep();
}

export async function renderBehdinDetail({ id }) {
  chrome(true);
  refreshHeader();
  showFab(false);
  loading();

  const aid = state.currentAgyaryId;
  const cid = Number(id);
  const alive = navGuard();

  // The memorial and reminder cards used to depend on which of the two apps this ran in.
  const hasMemorials = true;
  let record = null, history = null, saved = [], memorials = [];
  // Only a 404 means "not there". Anything else is a failed load, which must
  // not read as a behdin who is not on file, or who has no memorials (UX-01).
  const ifMissing = (fallback) => (e) => { if (e.status === 404) return fallback; throw e; };
  try {
    [record, history, saved, memorials] = await Promise.all([
      getBehdin(aid, cid).catch(ifMissing(null)),
      // History is scoped to what THIS mobed entered, so it can legitimately
      // be empty for a behdin someone else booked for (a 404). Any other
      // failure is not allowed to take the page down with it, but it is said
      // in the History card rather than shown as "nothing booked".
      customerHistory(cid).catch((e) => (e.status === 404 ? null : { failed: true })),
      getSavedNames(aid, cid).catch(ifMissing([])),
      listMemorials(aid, cid).catch(ifMissing([])),
    ]);
  } catch (e) {
    if (!alive()) return;
    mainEl.innerHTML = loadFailedHtml("this behdin");
    return wireRetry(mainEl, () => renderBehdinDetail({ id }));
  }
  if (!alive()) return;
  // Not on file: said in the page. Trying again would only say the same, so
  // there is no button for it - the header's Back is the way out.
  if (!record) return screenFailed("That behdin isn't on file at this fire temple.");
  let reminders = record.reminders || { enabled: false, stopped_at: null, delivery: "off" };

  mainEl.innerHTML = `
    <div class="card">
      ${backBar(esc(record.name))}
      <label for="bdName">Name</label><input type="text" id="bdName" value="${esc(record.name)}">
      <label for="bdPhone">WhatsApp number</label>${phoneField("bdPhone", record.phone)}
      <p class="meta" style="margin-top:6px">
        <a class="tel" href="tel:${esc(record.phone)}">Call ${esc(record.phone)}</a></p>
      <div class="action-bar">
        <button class="small" id="bdSave">Save details</button>
        <button class="ghost small danger-outline" id="bdDeleteOpen">Delete behdin</button>
      </div>
      <div id="bdDeleteConfirm" style="margin-top:12px"></div>
    </div>

    ${hasMemorials ? `<div class="card">
      <div class="row tight" style="justify-content:space-between;align-items:center">
        <h2 style="margin:0">Memorials</h2>
        <button class="icon-add" id="bdAddMemorial" title="New memorial" aria-label="New memorial">+</button>
      </div>
      ${memorials.length ? memorials.map(m => `
        <div class="search-result" data-mem="${m.id}">
          <div>${esc(m.departed_name)}</div>
          <div class="addr">${m.status === "completed"
            ? `Completed - ${m.total} observances`
            : `${m.done} of ${m.total} done${m.next ? ` · Next: ${esc(m.next.label)}, ${esc(gregShort(m.next.date))}` : ""}`}</div>
          <div class="progress"><div style="width:${m.total ? Math.round(100 * m.done / m.total) : 0}%"></div></div>
        </div>`).join("") : '<p class="meta">None yet.</p>'}
    </div>

    <div class="card">
      <h2>WhatsApp reminders</h2>
      <p class="meta">A short message the evening before each memorial prayer after the
        first ten days. Turn this on only after you have asked ${esc(record.name)} and
        they have said yes - they can stop it any time by replying STOP.</p>
      <div class="check-row">
        <input type="checkbox" id="bdReminders" ${reminders.enabled ? "checked" : ""}>
        <label for="bdReminders">${esc(record.name)} has agreed to receive reminders</label>
      </div>
      <p class="meta" id="bdRemindersNote"></p>
    </div>` : ""}

    <div class="card">
      <h2>Names for prayers</h2>
      <p class="meta">Reused whenever this behdin books - here or over WhatsApp.</p>
      <div id="savedRegion"></div>
      <div style="margin-top:14px"><button class="small" id="bdSaveNames">Save names</button></div>
    </div>

    <div class="card">
      <h2>History</h2>
      ${history && history.failed
        ? `<p class="meta">The history couldn't be loaded. This does not mean there is none -
            check your signal and open this page again.</p>`
        : history && history.history.length ? history.history.map(h => `
        <div class="list-row"><div class="lr-main"><b>${esc(h.event)}</b><span>${esc(h.when)}</span></div></div>
      `).join("") : '<p class="meta">Nothing you have booked for this behdin yet.</p>'}
    </div>`;

  const detailsCard = document.getElementById("bdName").closest(".card");
  document.getElementById("bdSave").onclick = async (ev) => {
    const btn = ev.currentTarget;
    const name = document.getElementById("bdName").value.trim();
    const phone = readPhone("bdPhone");
    // Said on the field that is wrong, as the Add behdin page does.
    const problems = [];
    if (!name) problems.push({ target: "#bdName", message: "Please enter a name." });
    if (!phone) problems.push({ target: ".phone-field", message: "Please enter a valid phone number." });
    if (problems.length) return flagProblems(detailsCard, problems);
    btn.disabled = true;   // one save per tap
    try {
      await updateBehdin(aid, cid, { name, phone });
      showInfo("Saved.");
    } catch (e) {
      showError(e.message);
    } finally {
      btn.disabled = false;
    }
  };

  if (hasMemorials) {
    document.getElementById("bdAddMemorial").onclick = () => navigate(`#/behdins/${cid}/memorials/new`);

    // Reminders: the mobed asks the behdin in person and records the yes here.
    const box = document.getElementById("bdReminders");
    const note = document.getElementById("bdRemindersNote");
    const paintNote = () => {
      const parts = [];
      if (reminders.stopped_at) {
        parts.push(`${record.name} replied STOP on ${gregShort(reminders.stopped_at.slice(0, 10))}, `
          + "so reminders are off. Turn them back on only if they ask you to.");
      }
      if (reminders.enabled && reminders.delivery !== "live") {
        parts.push("Automatic sending is not switched on yet - until it is, use "
          + "Remind on WhatsApp from the Reminders list.");
      }
      note.textContent = parts.join(" ");
    };
    paintNote();

    let consentVersion = null;
    /** Save the choice. `btn` is the button that confirmed it, when there was
     *  one. Neither it nor the tick can be pressed again while the save runs. */
    const apply = async (want, confirmRestart, btn = null) => {
      box.disabled = true;
      if (btn) btn.disabled = true;
      try {
        reminders = await setBehdinReminders(aid, cid, want, confirmRestart, want ? consentVersion : null);
        box.checked = reminders.enabled;
        paintNote();
        showInfo(want ? "Reminders on." : "Reminders off.");
      } catch (e) {
        box.checked = reminders.enabled;
        // A person who replied STOP is only restored on purpose.
        if (e.status === 409 && want) {
          note.innerHTML = `${esc(e.message)}
            <div class="row tight" style="margin-top:8px">
              <button class="small" id="bdRemConfirm">They asked me to - turn on</button>
              <button class="ghost small" id="bdRemCancel">Cancel</button>
            </div>`;
          document.getElementById("bdRemConfirm").onclick = (ev) => apply(true, true, ev.currentTarget);
          document.getElementById("bdRemCancel").onclick = paintNote;
          return;
        }
        if (btn) btn.disabled = false;   // still on screen: it can be tried again
        showError(e.message);
      } finally {
        box.disabled = false;
      }
    };
    // Turning reminders on is a record that the family agreed to particular
    // words, so the mobed is shown them and confirms before anything is saved
    // (RM-6). Turning them off needs no ceremony.
    const askConsent = async () => {
      let wording;
      box.disabled = true;   // not to be ticked and unticked while the words are fetched
      try {
        wording = await consentWording();
      } catch (e) {
        box.checked = false;
        return showError(e.message);
      } finally {
        box.disabled = false;
      }
      note.innerHTML = `<div class="card" style="margin:8px 0 0">
          <p style="margin:0 0 8px"><b>Before you turn this on, please ask ${esc(record.name)}:</b></p>
          <p style="margin:0 0 12px">"${esc(wording.text)}"</p>
          <div class="row tight">
            <button class="small" id="bdConsentYes">They said yes</button>
            <button class="ghost small" id="bdConsentNo">Cancel</button>
          </div>
        </div>`;
      document.getElementById("bdConsentYes").onclick = (ev) => {
        consentVersion = wording.version;
        apply(true, false, ev.currentTarget);
      };
      document.getElementById("bdConsentNo").onclick = () => { box.checked = false; paintNote(); };
    };
    box.onchange = () => (box.checked ? askConsent() : apply(false, false));
  }
  mainEl.querySelectorAll("[data-mem]").forEach(el => {
    el.onclick = () => navigate(`#/memorial/${el.dataset.mem}`);
  });

  // Delete sits beside Save details, and its question opens directly under them.
  const deleteBox = document.getElementById("bdDeleteConfirm");
  document.getElementById("bdDeleteOpen").onclick = () => {
    // Already asking. A second tap must not start the question again under a
    // delete that is running; it shows the question that is there.
    if (deleteBox.firstElementChild) return deleteBox.scrollIntoView({ block: "center" });
    openDeleteBox(deleteBox, aid, { id: cid, name: record.name }, {
      onError: (m) => showError(m),
      onDone: (r) => {
        flashInfo(deleteResultText(record.name, r));
        // Their record is gone from the list; do not leave it behind us in history.
        back("#/behdins");
      },
    });
  };

  // The same editor the New Event wizard uses. Rendered in "service" shape
  // because the pool holds both pairs and farmayeshne singles, whatever any
  // one ceremony ends up using them for.
  const region = document.getElementById("savedRegion");
  renderNamesEditor(region, false, "gujrela_nu", saved);
  const namesCard = region.closest(".card");
  // Removing or adding a pair is not typing, so a mark on the names would
  // otherwise stay after what it complained of had been dealt with.
  region.addEventListener("names-changed", () => clearProblems(namesCard));
  document.getElementById("bdSaveNames").onclick = async (ev) => {
    const btn = ev.currentTarget;
    const rows = collectNames(region, false, "gujrela_nu");
    const problem = validateNames(rows);
    // Marked on the names themselves, as the Add behdin page does.
    if (problem) return flagProblems(namesCard, [{ target: "#savedRegion", message: problem }]);
    clearProblems(namesCard);
    btn.disabled = true;   // one save per tap
    try {
      // Section-wholesale: the API replaces a section at a time, which is
      // also the level the "a pair is two names" rule lives at.
      await putSavedNames(aid, cid, "pair", rows.filter(n => n.section === "pair"));
      await putSavedNames(aid, cid, "farmayeshne", rows.filter(n => n.section === "farmayeshne"));
      showInfo("Names for prayers updated.");
    } catch (e) {
      showError(e.message);
    } finally {
      btn.disabled = false;
    }
  };
}
