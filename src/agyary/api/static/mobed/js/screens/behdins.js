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
  createBehdin, deleteBehdin,
  getSavedNames, putSavedNames, listMemorials, previewNewMemorial, createMemorial,
} from "../api.js";
import { state } from "../state.js";
import { canPickContacts, pickContacts } from "../behdin_add.js";
import { renderNamesEditor, collectNames, validateNames } from "../names.js";
import {
  chrome, mainEl, showFab, showError, showInfo, flashInfo, flashError,
  refreshHeader, loading, backBar,
} from "../ui.js";
import { esc, gregShort, phoneField, readPhone, setPhoneField } from "../util.js";
import { navigate, back, navGuard } from "../router.js";

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
    mainEl.innerHTML = "";
    return showError(e.message);
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
  // whole schedule is laid out from it. Only in the mobed app (the Machi Board
  // has no memorial screens), and not when this page is a detour from a form.
  const memorialOk = !returnTo && !!document.getElementById("tabs");

  mainEl.innerHTML = `
    <div id="bnForm">
    <div class="card">
      ${backBar("New behdin")}
      ${canPickContacts() ? `
        <button class="secondary" id="bnImport" style="margin-bottom:12px">
          Import from contacts
        </button>` : ""}
      <label for="bnName">Name</label>
      <input type="text" id="bnName" placeholder="e.g. Behdin Zubin Mistry"
             autocomplete="off" value="${esc(prefillName)}">
      <label for="bnPhone">WhatsApp number</label>${phoneField("bnPhone")}
    </div>

    <div class="card">
      <h2>Saved names</h2>
      <p class="meta">Reused whenever this behdin books - here or over
        WhatsApp. Leave it for later if you don't have them to hand.</p>
      <div id="savedRegion"></div>
    </div>

    ${memorialOk ? `<div class="card">
      <div class="check-row"><input type="checkbox" id="bnMemOn">
        <label for="bnMemOn"><b>They are keeping observances for someone they have lost</b></label></div>
    </div>
    <div id="bnMemForm" style="display:none"></div>` : ""}

    <div class="wizard-nav" style="margin-top:4px">
      <button class="ghost" id="bnCancel">Cancel</button>
      <button id="bnSave">Add behdin</button>
    </div>
    </div>
    <div id="bnPreview" style="display:none"></div>`;

  document.getElementById("bnCancel").onclick = () => back(backTarget);
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
      back(backTarget);
    };
  }

  // The memorial, if one is being set up here. Its form is built the first
  // time the box is ticked, and loaded then: it is not needed to add a behdin.
  let mem = null, mdraft = null, mservices = [];
  const saveBtn = document.getElementById("bnSave");
  const memOn = memorialOk ? document.getElementById("bnMemOn") : null;
  if (memOn) {
    memOn.onchange = async () => {
      const box = document.getElementById("bnMemForm");
      saveBtn.textContent = memOn.checked ? "Review schedule" : "Add behdin";
      box.style.display = memOn.checked ? "" : "none";
      if (!memOn.checked || mdraft) return;   // off, or already built: just show/hide
      try {
        const [form, { prayerServices }] = await Promise.all([
          import("../memorial_form.js"), import("./memorial.js"),
        ]);
        mservices = await prayerServices(state.currentAgyaryId);
        mem = form;
        mdraft = form.blankMemorialDraft();
        box.innerHTML = form.memorialFormHtml(mdraft, mservices, {
          heading: "<h2>Someone they have lost</h2>",
        });
        form.wireMemorialForm(box, mdraft);
      } catch (e) {
        memOn.checked = false;
        box.style.display = "none";
        saveBtn.textContent = "Add behdin";
        showError("Couldn't load the memorial form: " + e.message);
      }
    };
  }

  /** What the mobed typed, checked - or null after saying what is wrong. */
  const validate = () => {
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
    return { name, phone, rows };
  };

  /** Create the behdin, their saved names, and - if there is one - the
   *  memorial. `btn` is whatever was pressed, so it can be released on failure. */
  const saveAll = async (v, memorialBody, btn) => {
    const aid = state.currentAgyaryId;
    btn.disabled = true;
    let created;
    try {
      created = await createBehdin(aid, v.name, v.phone);
    } catch (e) {
      btn.disabled = false;
      return showError(e.message);
    }
    if (!created.created && !returnTo && !memorialBody) {
      showInfo(`${created.name} was already on file - opening their record.`);
    }

    // Back to the event/machi draft with this behdin chosen, rather than
    // their own record - that record has nothing to do with what's being
    // booked.
    const landing = () => {
      if (returnTo && state.draft) {
        state.draft.behdin = { id: created.id, name: created.name, phone: created.phone };
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

    if (memorialBody) {
      try {
        const made = await createMemorial(aid, created.id, memorialBody);
        if (namesProblem) flashError(namesProblem);
        return navigate(`#/memorial/${made.id}`, { replace: true });
      } catch (e) {
        // The behdin exists either way - say so rather than losing them.
        flashError(`${created.name} was added, but the memorial wasn't: ${e.message}`);
        return navigate(`#/behdins/${created.id}`, { replace: true });
      }
    }
    landing();
    if (namesProblem) showError(namesProblem);
  };

  /** Every date, before anything is saved - the same step the behdin's own
   *  page has. Nothing exists yet: not the behdin, not the memorial. */
  const showPreview = (v, body, preview) => {
    const formEl = document.getElementById("bnForm");
    const previewEl = document.getElementById("bnPreview");
    // A message from an earlier attempt would sit above a schedule it no longer applies to.
    mainEl.querySelectorAll(".error-banner, .info-banner").forEach(el => el.remove());
    formEl.style.display = "none";
    previewEl.style.display = "";
    previewEl.innerHTML = `
      ${mem.schedulePreviewHtml(body, preview, mservices, { heading: backBar("Review the schedule") })}
      <p class="meta">For ${esc(v.name)}. Nothing is saved until you confirm.</p>
      <div class="wizard-nav" style="margin-top:4px">
        <button class="ghost" id="bnPrevBack">Change</button>
        <button id="bnPrevGo">Add behdin and memorial</button>
      </div>`;
    window.scrollTo(0, 0);
    document.getElementById("bnPrevBack").onclick = () => {
      previewEl.style.display = "none";
      formEl.style.display = "";
    };
    document.getElementById("bnPrevGo").onclick = (e) => saveAll(v, body, e.currentTarget);
  };

  saveBtn.onclick = async () => {
    const v = validate();
    if (!v) return;
    if (memOn && memOn.checked) {
      const built = mem.buildMemorialBody(mdraft);
      if (built.error) return showError(built.error);
      saveBtn.disabled = true;
      try {
        showPreview(v, built.body, await previewNewMemorial(state.currentAgyaryId, built.body));
      } catch (e) {
        showError(e.message);
      } finally {
        saveBtn.disabled = false;
      }
      return;
    }
    await saveAll(v, null, saveBtn);
  };
}

export async function renderBehdinDetail({ id }) {
  chrome(true);
  refreshHeader();
  showFab(false);
  loading();

  const aid = state.currentAgyaryId;
  const cid = Number(id);
  const alive = navGuard();

  // Memorials live in the mobed app; the Machi Board has no screens for them.
  const hasMemorials = !!document.getElementById("tabs");
  let record = null, history = null, saved = [], memorials = [];
  try {
    [record, history, saved, memorials] = await Promise.all([
      getBehdin(aid, cid).catch(() => null),
      // History is scoped to what THIS mobed entered, so it can legitimately
      // be empty for a behdin someone else booked for.
      customerHistory(cid).catch(() => null),
      getSavedNames(aid, cid).catch(() => []),
      hasMemorials ? listMemorials(aid, cid).catch(() => []) : [],
    ]);
  } catch (e) {
    if (!alive()) return;
    mainEl.innerHTML = "";
    return showError(e.message);
  }
  if (!alive()) return;
  if (!record) {
    mainEl.innerHTML = "";
    return showError("That behdin isn't on file at this fire temple.");
  }
  let reminders = record.reminders || { enabled: false, stopped_at: null, delivery: "off" };

  mainEl.innerHTML = `
    <div class="card">
      ${backBar(esc(record.name))}
      <label for="bdName">Name</label><input type="text" id="bdName" value="${esc(record.name)}">
      <label for="bdPhone">WhatsApp number</label>${phoneField("bdPhone", record.phone)}
      <p class="meta" style="margin-top:6px">
        <a class="tel" href="tel:${esc(record.phone)}">Call ${esc(record.phone)}</a></p>
      <div style="margin-top:12px"><button class="small" id="bdSave">Save details</button></div>
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
    </div>

    <div class="card">
      <button class="ghost small" id="bdDeleteOpen">Delete behdin</button>
      <div id="bdDeleteConfirm" style="margin-top:12px"></div>
    </div>`;

  document.getElementById("bdSave").onclick = async () => {
    const name = document.getElementById("bdName").value.trim();
    const phone = readPhone("bdPhone");
    if (!name) return showError("Please enter a name.");
    if (!phone) return showError("Please enter a valid phone number.");
    try {
      await updateBehdin(aid, cid, { name, phone });
      showInfo("Saved.");
    } catch (e) {
      showError(e.message);
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
    const apply = async (want, confirmRestart) => {
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
          document.getElementById("bdRemConfirm").onclick = () => apply(true, true);
          document.getElementById("bdRemCancel").onclick = paintNote;
          return;
        }
        showError(e.message);
      }
    };
    // Turning reminders on is a record that the family agreed to particular
    // words, so the mobed is shown them and confirms before anything is saved
    // (RM-6). Turning them off needs no ceremony.
    const askConsent = async () => {
      let wording;
      try {
        wording = await consentWording();
      } catch (e) {
        box.checked = false;
        return showError(e.message);
      }
      note.innerHTML = `<div class="card" style="margin:8px 0 0">
          <p style="margin:0 0 8px"><b>Before you turn this on, please ask ${esc(record.name)}:</b></p>
          <p style="margin:0 0 12px">"${esc(wording.text)}"</p>
          <div class="row tight">
            <button class="small" id="bdConsentYes">They said yes</button>
            <button class="ghost small" id="bdConsentNo">Cancel</button>
          </div>
        </div>`;
      document.getElementById("bdConsentYes").onclick = () => { consentVersion = wording.version; apply(true, false); };
      document.getElementById("bdConsentNo").onclick = () => { box.checked = false; paintNote(); };
    };
    box.onchange = () => (box.checked ? askConsent() : apply(false, false));
  }
  mainEl.querySelectorAll("[data-mem]").forEach(el => {
    el.onclick = () => navigate(`#/memorial/${el.dataset.mem}`);
  });

  document.getElementById("bdDeleteOpen").onclick = () => {
    const panel = document.getElementById("bdDeleteConfirm");
    const n = history && history.history ? history.history.length : 0;
    panel.innerHTML = `
      <p class="meta">Remove ${esc(record.name)} from your behdins?
        ${n ? `Their ${n} event${n > 1 ? "s" : ""} stay on your calendar and slips.` : ""}
        Adding the same number again brings them back.</p>
      <div class="row tight">
        <button class="danger small" id="bdDelOne">Delete</button>
        <button class="ghost small" id="bdDelCancel">Cancel</button>
      </div>`;
    document.getElementById("bdDelCancel").onclick = () => { panel.innerHTML = ""; };
    document.getElementById("bdDelOne").onclick = async () => {
      try {
        await deleteBehdin(aid, cid);
      } catch (e) {
        return showError("Couldn't delete: " + e.message);
      }
      flashInfo(`${record.name} removed.`);
      // Their record is gone from the list; do not leave it behind us in history.
      back("#/behdins");
    };
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
