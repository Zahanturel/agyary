"use strict";

/**
 * Recording a death, and choosing the fire temple, in four short steps, family
 * first (DECISIONS D12, owner, 24 Nov 2026). One group of questions per screen,
 * with Back, like New machi / New memorial:
 *
 *   1  The family: name and number, from the place's book (a search that also
 *      lists the first people of the book), Import from contacts, or typed.
 *   2  The departed: title, name and father's or husband's name (both left empty
 *      when not known), calendar, date of death (today unless changed; "give the
 *      Roj and Mah instead" for a death before sunrise).
 *   3  The prayers: four days (or one), Geh-saarnu, Uthamna, mobeds wanted.
 *   4  The fire temple: a list that is already full when the step opens (only fire
 *      temples with someone in Mobed Diary, the family's usual one first, then the
 *      nearest, then by town), a search above it, then the confirmation sheet and
 *      Send (manager_record.js). "Save without sending" keeps the record for later.
 *
 * Editing a record uses steps 1 to 3 filled in, ending in "Save changes".
 * "Send to another fire temple" on a record (after a withdraw) opens step 4 for
 * that record. What is typed is kept as a draft until the record is saved or
 * cancelled (drafts.js).
 *
 * The admin acting for one place (acting.js) uses these same screens: every
 * address goes through managerHash.
 */

import {
  calendarOptions, managerDeathDay, managerRecord, managerCreateRecord, managerUpdateRecord,
  managerSuggested, managerSuggestedFor, managerSearchAgyaries, managerBook,
} from "../api.js";
import { openBehdinSheet, familyLineHtml } from "./manager_behdins.js";
import { agyariRowHtml, confirmSend } from "./manager_record.js";
import { canPickContacts, pickContacts, fillFromContact } from "../behdin_add.js";
import { state } from "../state.js";
import {
  chrome, mainEl, showFab, showError, showInfo, refreshHeader, loading, screenFailed, toTop, flashInfo,
} from "../ui.js";
import { esc, gregLabel, gregShort, todayIst, phoneField, readPhone, MAH_NAMES_JS } from "../util.js";
import { navigate, back, navGuard, returnTo } from "../router.js";
import { flagProblems, clearProblems } from "../fielderrors.js";
import { managerHash, managerPlaces } from "../acting.js";
import { loadDraft, saveDraft, clearDraft, offerDraft } from "../drafts.js";

const TITLES = [["behdin", "Behdin"], ["ervad", "Ervad"], ["osta", "Osta"], ["osti", "Osti"], ["khud", "Khud"]];
const GATHAS = ["Ahunavad", "Ushtavad", "Spentamad", "Vohukhshathra", "Vahishtoisht"];
// The Geh-saarnu is prayed in daylight only.
const DAY_GEHS = [[1, "Havan"], [2, "Rapithwan"], [3, "Uzirin"]];
const QUESTIONS = ["Who is the family?", "Who passed away?", "Which prayers?", "Which fire temple?"];
// The first people of the place's book shown before anything is typed.
const BOOK_FIRST = 6;
// What a record reads as when the departed's name is not known (as the server writes it).
const NAME_NOT_KNOWN = "(name not known)";

// --- The draft --------------------------------------------------------------------

function blankDraft(placeId) {
  return {
    step: 1, placeId, recordId: null,
    contactName: "", contactPhone: "",
    title: "behdin", name: "", parent: "", calendar: "shenshai",
    deathBy: "date", death: todayIst(), deathTouched: false, deathRoj: "", deathMah: "",
    obsequies: "four_days", gsDate: "", gsGeh: "", utDate: "", utTime: "", mobeds: "",
    preferredId: null,
  };
}

function draftFrom(rec) {
  return {
    step: 1, placeId: rec.funeral_place ? rec.funeral_place.id : null, recordId: rec.id,
    contactName: rec.family_contact.name, contactPhone: rec.family_contact.phone,
    title: rec.departed_title, name: rec.departed_name || "", parent: rec.departed_parent_name || "",
    calendar: rec.death.calendar, deathBy: rec.death.given_by === "roj_mah" ? "parsi" : "date",
    death: rec.death.date, deathTouched: true, deathRoj: String(rec.death.roj), deathMah: String(rec.death.mah),
    obsequies: rec.obsequies,
    gsDate: rec.geh_saarnu ? rec.geh_saarnu.date : "", gsGeh: rec.geh_saarnu ? String(rec.geh_saarnu.geh) : "",
    utDate: rec.uthamna ? rec.uthamna.date : "", utTime: rec.uthamna && rec.uthamna.time ? rec.uthamna.time : "",
    mobeds: rec.mobeds_wanted ? String(rec.mobeds_wanted) : "",
    // An older record may have the fire temple the family named; it is kept as it was.
    preferredId: rec.preferred_agyari ? rec.preferred_agyari.id : null,
  };
}

async function loadCalendarOptions() {
  if (state.calendarOptions && state.calendarOptions.roj && state.calendarOptions.roj.length) return;
  try {
    state.calendarOptions = await calendarOptions();
  } catch (e) {
    state.calendarOptions = null;
    throw e;
  }
}

/** The departed as it will be prayed: the title, the name (or "(name not known)"), the parent. */
export function prayedAs(d) {
  const title = (TITLES.find(([v]) => v === d.title) || ["", "Behdin"])[1];
  return [title, d.name.trim() || NAME_NOT_KNOWN, d.parent.trim()].filter(Boolean).join(" ");
}

/** The body for the API. The names may be empty; nothing else is invented here. */
export function recordBody(d) {
  const byParsi = d.deathBy === "parsi";
  return {
    funeral_place_id: d.placeId,
    departed_title: d.title, departed_name: d.name.trim(), departed_parent_name: d.parent.trim() || null,
    calendar: d.calendar,
    death_date: byParsi ? null : d.death || null,
    death_roj: byParsi && d.deathRoj ? Number(d.deathRoj) : null,
    death_mah: byParsi && d.deathMah ? Number(d.deathMah) : null,
    obsequies: d.obsequies,
    geh_saarnu_date: d.gsDate || null, geh_saarnu_geh: d.gsGeh ? Number(d.gsGeh) : null,
    uthamna_date: d.utDate || null, uthamna_time: d.utTime || null,
    mobeds_wanted: d.mobeds === "" ? null : Number(d.mobeds),
    preferred_agyary_id: d.preferredId,
    family_contact_name: d.contactName.trim(), family_contact_phone: d.contactPhone || "",
  };
}

/** What is wrong on step ``n`` (marked on that step). */
function problemsOf(d, n) {
  const out = [];
  const bad = (target, message) => out.push({ target, message });
  if (n === 1) {
    if (!d.contactName.trim()) bad("#frContact", "Please enter the family contact's name.");
    if (!d.contactPhone) bad("#frPhoneBox .phone-field", "Please enter the family contact's number.");
  } else if (n === 2) {
    if (d.deathBy === "parsi") {
      if (!d.deathRoj) bad("#frDeathRoj", "Please choose the Roj of the death.");
      else if (d.deathMah !== "13" && !d.deathMah) bad("#frDeathMah", "Please choose the Mah of the death.");
    } else if (!d.death) bad("#frDeathDate", "Please enter the date of death.");
    else if (d.death > todayIst()) bad("#frDeathDate", "The death cannot be after today.");
  } else if (n === 3) {
    if (d.gsDate && !d.gsGeh) bad("#frGsGeh", "Please choose the geh of the Geh-saarnu.");
    if (d.gsGeh && !d.gsDate) bad("#frGsDate", "Please give the day of the Geh-saarnu.");
    if (d.utTime && !d.utDate) bad("#frUtDate", "Please give the day of the Uthamna.");
    const died = d.deathBy === "parsi" ? null : d.death;
    if (died && d.gsDate && d.gsDate < died) bad("#frGsDate", "The Geh-saarnu cannot be before the death.");
    if (died && d.utDate && d.utDate < died) bad("#frUtDate", "The Uthamna cannot be before the death.");
    const mobeds = d.mobeds === "" ? null : Number(d.mobeds);
    if (mobeds !== null && !(Number.isInteger(mobeds) && mobeds >= 1 && mobeds <= 20)) {
      bad("#frMobeds", "The number of mobeds is from 1 to 20.");
    }
  }
  return out;
}

/** The step a field the server names belongs to, and what to mark there. */
function whereIs(field, d) {
  const at = {
    family_contact_name: [1, "#frContact"], family_contact_phone: [1, "#frPhoneBox .phone-field"],
    departed_title: [2, "#frTitle"], departed_name: [2, "#frName"], departed_parent_name: [2, "#frParent"],
    calendar: [2, "#frCalendar"], death: [2, d.deathBy === "parsi" ? "#frDeathRoj" : "#frDeathDate"],
    obsequies: [3, "#frObsequies"], geh_saarnu_date: [3, "#frGsDate"], geh_saarnu_geh: [3, "#frGsGeh"],
    uthamna_date: [3, "#frUtDate"], mobeds_wanted: [3, "#frMobeds"],
  }[field];
  return at || null;
}

function radio(name, id, value, checked, text) {
  return `<div class="check-row"><input type="radio" name="${name}" id="${id}" value="${value}" ${checked ? "checked" : ""}>
    <label for="${id}">${text}</label></div>`;
}

function rojOptions(d) {
  const gatha = d.deathMah === "13";
  const names = ((state.calendarOptions && state.calendarOptions.roj) || []).map(o => o.title);
  return `<option value="">Choose</option>` + names.map((n, i) =>
    `<option value="${i + 1}" ${!gatha && d.deathRoj === String(i + 1) ? "selected" : ""}>${esc(n)}</option>`).join("")
    + `<optgroup label="Gatha days">` + GATHAS.map((n, i) =>
      `<option value="g${i + 1}" ${gatha && d.deathRoj === String(i + 1) ? "selected" : ""}>${esc(n)}</option>`).join("")
    + `</optgroup>`;
}

// --- The steps ------------------------------------------------------------------------

function stepOneHtml(d, editing) {
  const places = managerPlaces();
  return `
    <div class="card" id="frCard">
      ${places.length > 1 ? `<label for="frPlace">Place</label>
        <select id="frPlace" ${editing || d.recordId ? "disabled" : ""}>${places.map(p =>
          `<option value="${p.id}" ${d.placeId === p.id ? "selected" : ""}>${esc(p.name)}</option>`).join("")}</select>` : ""}
      <p class="meta" style="margin:0 0 8px">Choose them from your book of behdins, import them from your contacts, or
        type their name and number. The family's number is shown to a fire temple only once it accepts.</p>
      <input type="text" id="frFamilySearch" placeholder="Search your book by name or number" autocomplete="off">
      <div id="frFamilyResults" style="margin-top:8px"></div>
      <div class="row tight" style="margin-top:8px;flex-wrap:wrap">
        ${canPickContacts() ? `<button type="button" class="secondary small" id="frImport">Import from contacts</button>` : ""}
        <button type="button" class="secondary small" id="frFamilyAdd">Add a new behdin</button>
      </div>
      <p class="meta" id="frFamilyNote" role="status" style="margin:6px 0 0"></p>

      <label for="frContact" style="margin-top:16px">Family contact: name</label>
      <input type="text" id="frContact" autocomplete="off" maxlength="100" value="${esc(d.contactName)}">
      <label for="frPhone">Family contact: number</label>
      <div id="frPhoneBox">${phoneField("frPhone", d.contactPhone || "")}</div>
    </div>`;
}

function stepTwoHtml(d) {
  const parsi = d.deathBy === "parsi";
  return `
    <div class="card" id="frCard">
      <label for="frTitle">Title</label>
      <select id="frTitle">${TITLES.map(([v, t]) => `<option value="${v}" ${d.title === v ? "selected" : ""}>${t}</option>`).join("")}</select>
      <label for="frName">Name of the departed <span class="meta">(leave empty if not known)</span></label>
      <input type="text" id="frName" autocomplete="off" maxlength="80" value="${esc(d.name)}">
      <label for="frParent">Father's or husband's name <span class="meta">(leave empty if not known)</span></label>
      <input type="text" id="frParent" autocomplete="off" maxlength="80" value="${esc(d.parent)}">
      <p class="meta" id="frPrayed" style="margin:6px 0 0"></p>

      <label for="frCalendar">Calendar the family keeps</label>
      <select id="frCalendar">${[["shenshai", "Shenshai"], ["kadmi", "Kadmi"]].map(([k, v]) =>
        `<option value="${k}" ${d.calendar === k ? "selected" : ""}>${v}</option>`).join("")}</select>

      <div id="frDateBox" style="${parsi ? "display:none" : ""}">
        <label for="frDeathDate">Date of death</label>
        <input type="date" id="frDeathDate" max="${todayIst()}" value="${esc(d.death)}">
      </div>
      <div id="frParsiBox" style="${parsi ? "" : "display:none"}">
        <label for="frDeathRoj">Roj</label>
        <select id="frDeathRoj">${rojOptions(d)}</select>
        <div id="frMahBox" style="${d.deathMah === "13" ? "display:none" : ""}">
          <label for="frDeathMah">Mah</label>
          <select id="frDeathMah"><option value="">Choose</option>${MAH_NAMES_JS.map((n, i) =>
            `<option value="${i + 1}" ${d.deathMah === String(i + 1) ? "selected" : ""}>${esc(n)}</option>`).join("")}</select>
        </div>
      </div>
      <p class="meta" id="frDeathDay" role="status" style="margin:6px 0 0"></p>
      <button type="button" class="ghost small" id="frDeathBy" style="margin-top:4px">${parsi
        ? "Use the date instead" : "Give the Roj and Mah instead (a death before sunrise)"}</button>
    </div>`;
}

function stepThreeHtml(d) {
  return `
    <div class="card" id="frCard">
      <label>Days of prayers</label>
      <div class="choice-group" id="frObsequies">
        ${radio("frOb", "frObFour", "four_days", d.obsequies === "four_days", "Four days")}
        ${radio("frOb", "frObOne", "one_day", d.obsequies === "one_day", "One day")}
      </div>

      <label for="frGsDate">Geh-saarnu: day <span class="meta">(optional)</span></label>
      <input type="date" id="frGsDate" value="${esc(d.gsDate)}">
      <label for="frGsGeh">Geh-saarnu: geh</label>
      <select id="frGsGeh"><option value="">Choose</option>${DAY_GEHS.map(([n, t]) =>
        `<option value="${n}" ${d.gsGeh === String(n) ? "selected" : ""}>${t}</option>`).join("")}</select>

      <label for="frUtDate">Uthamna: day <span class="meta">(optional)</span></label>
      <input type="date" id="frUtDate" value="${esc(d.utDate)}">
      <label for="frUtTime">Uthamna: time</label>
      <input type="time" id="frUtTime" value="${esc(d.utTime)}">

      <label for="frMobeds">Mobeds wanted <span class="meta">(optional)</span></label>
      <input type="number" id="frMobeds" inputmode="numeric" min="1" max="20" value="${esc(d.mobeds)}">
    </div>`;
}

// --- The flow --------------------------------------------------------------------------

/** Steps 1 to 4 for a new record, or 1 to 3 for ``rec`` being changed. */
async function renderFlow(rec) {
  chrome(true);
  refreshHeader();
  showFab(false);
  loading();
  const alive = navGuard();
  try {
    await loadCalendarOptions();
  } catch (e) {
    if (!alive()) return;
    return screenFailed(e.message, () => renderFlow(rec));
  }
  if (!alive()) return;
  const editing = !!rec;
  const total = editing ? 3 : 4;
  let d = editing ? draftFrom(rec) : blankDraft((managerPlaces()[0] || {}).id || null);
  const key = () => `record:${state.actFor || ""}:${d.placeId}`;
  const keep = () => { if (!editing) saveDraft(key(), d); };
  let saving = false;

  /** Save the record (new, or the one already saved by an earlier tap). Null if it did not go. */
  async function save() {
    if (saving) return null;
    saving = true;
    try {
      const body = recordBody(d);
      const res = d.recordId ? await managerUpdateRecord(d.recordId, body) : await managerCreateRecord(body);
      d.recordId = res.record.id;
      keep();
      return res;
    } catch (e) {
      const at = e.field ? whereIs(e.field, d) : null;
      if (at) {
        d.step = at[0];
        show();
        flagProblems(mainEl, [{ target: at[1], message: e.message }]);
      } else {
        showError(e.message);
      }
      return null;
    } finally {
      saving = false;
    }
  }

  function show() {
    const step = d.step;
    const body = [stepOneHtml, stepTwoHtml, stepThreeHtml][step - 1];
    mainEl.innerHTML = `
      <div class="step-head">
        <div class="step-count">${editing ? "Change the record · " : ""}Step ${step} of ${total}</div>
        <div class="step-bar">${Array.from({ length: total }, (_, i) => i + 1).map(n =>
          `<i class="${n <= step ? "on" : ""}"></i>`).join("")}</div>
        <h2 class="step-q">${esc(QUESTIONS[step - 1])}</h2>
      </div>
      ${step === 4 ? `<div id="frStep4"></div>` : body(d, editing)}
      <div class="wizard-nav" style="margin-top:4px">
        <button type="button" class="secondary" id="frBack">${step === 1 ? "Cancel" : "Back"}</button>
        ${step === 4 ? "" : `<button type="button" id="frNext">${step === total ? "Save changes" : "Next"}</button>`}
      </div>`;
    toTop();
    const root = mainEl;
    const $ = (sel) => root.querySelector(sel);

    $("#frBack").onclick = () => {
      if (step > 1) { d.step = step - 1; keep(); return show(); }
      if (!editing) clearDraft(key());
      back(managerHash(editing ? `/record/${rec.id}` : ""));
    };
    if (step === 1) wireFamily($, d, keep);
    else if (step === 2) wireDeparted($, d, keep);
    else if (step === 3) wireStepThree($, d, keep);
    else wireFireTemple(d, { alive, save, clear: () => clearDraft(key()) });

    const next = $("#frNext");
    if (!next) return;
    next.onclick = async () => {
      if (step === 1) {
        d.contactName = $("#frContact").value;
        d.contactPhone = readPhone("frPhone") || "";
      }
      const problems = problemsOf(d, step);
      if (problems.length) return flagProblems(root, problems);
      clearProblems(root);
      if (step < 3) { d.step = step + 1; keep(); return show(); }
      // Step 3: a record being changed is saved here; a new one goes on to the fire temple.
      if (editing) {
        next.disabled = true;
        const res = await save();
        if (!alive()) return;
        if (!res) { next.disabled = false; return; }
        flashInfo(res.told
          ? `Saved. The ${res.told === 1 ? "person" : `${res.told} people`} asked at the fire temple ${res.told === 1
            ? "was" : "were"} sent the new details.`
          : "Saved.");
        return returnTo(managerHash(`/record/${res.record.id}`));
      }
      d.step = 4;
      keep();
      show();
    };
  }

  if (!editing) {
    const stored = loadDraft(key());
    if (stored && (stored.contactName || stored.contactPhone || stored.name)) {
      return offerDraft({
        title: "Unfinished record",
        summary: [stored.contactName ? `Family: ${stored.contactName}` : "The family is not chosen yet",
          stored.name ? `For ${stored.name}` : "The departed is not named yet"],
        onStartNew: () => { clearDraft(key()); d = blankDraft(d.placeId); show(); },
        onContinue: () => {
          d = { ...blankDraft(stored.placeId), ...stored };
          // A date nobody chose is today, whichever day this is.
          if (!d.deathTouched && d.deathBy === "date") d.death = todayIst();
          show();
        },
      });
    }
  }
  show();
}

// --- Step 1: the family ----------------------------------------------------------------

function wireFamily($, d, keep) {
  const nameEl = $("#frContact");
  const phoneEl = $("#frPhone");
  const ccEl = $("#frPhone_cc");
  const note = $("#frFamilyNote");
  const sync = () => { d.contactName = nameEl.value; d.contactPhone = readPhone("frPhone") || ""; keep(); };
  [nameEl, phoneEl, ccEl].forEach(el => el.addEventListener("input", sync));
  if ($("#frPlace")) $("#frPlace").onchange = (e) => { d.placeId = Number(e.target.value); keep(); paintBook(); };

  const use = (b) => {
    nameEl.value = b.name;
    d.contactName = b.name;
    d.contactPhone = b.phone;
    // The phone field splits the country code from the number itself.
    const box = $("#frPhoneBox");
    box.innerHTML = phoneField("frPhone", b.phone);
    box.querySelectorAll("input").forEach(el => el.addEventListener("input", sync));
    note.textContent = `${b.name}, from your book.`;
    clearProblems($("#frCard"));
    keep();
  };

  // The book: the first people when nothing is typed, so the box is never blank.
  const input = $("#frFamilySearch");
  const results = $("#frFamilyResults");
  let timer, token = 0;
  async function paintBook() {
    const q = input.value.trim();
    const mine = ++token;
    let found;
    try {
      found = await managerBook(q);
    } catch (e) {
      if (mine === token && results.isConnected) results.innerHTML = `<p class="meta" role="alert">${esc(e.message)}</p>`;
      return;
    }
    if (mine !== token || !results.isConnected) return;
    const shown = q ? found.behdins : found.behdins.slice(0, BOOK_FIRST);
    if (!shown.length) {
      results.innerHTML = `<p class="meta" style="margin:0">${q ? `Nobody in your book for “${esc(q)}”. Add them as a new behdin.`
        : "Your book of behdins is empty. Add the family as a new behdin, or type their name and number below."}</p>`;
      return;
    }
    results.innerHTML = shown.map((b, i) => `<div class="search-result" data-i="${i}">${familyLineHtml(b)}</div>`).join("")
      + (!q && found.behdins.length > BOOK_FIRST ? `<p class="meta" style="margin:6px 0 0">Search to find others.</p>` : "");
    results.querySelectorAll("[data-i]").forEach(row => { row.onclick = () => use(shown[+row.dataset.i]); });
  }
  input.oninput = () => { clearTimeout(timer); timer = setTimeout(paintBook, 250); };
  paintBook();

  const imp = $("#frImport");
  if (imp) {
    imp.onclick = async () => {
      const [contact] = await pickContacts({ multiple: false });
      if (!contact || !nameEl.isConnected) return;
      fillFromContact(contact, { nameId: "frContact", phoneId: "frPhone" });
      sync();
      note.textContent = contact.name ? `${contact.name}, from your contacts. Please check the name and number.` : "";
    };
  }
  $("#frFamilyAdd").onclick = () => {
    const typed = input.value.trim();
    openBehdinSheet({
      placeId: d.placeId,
      prefill: { name: typed && !/\d/.test(typed) ? typed : nameEl.value.trim(), phone: readPhone("frPhone") || "" },
      onSaved: (b) => { use(b); showInfo(`${b.name} is in your book of behdins.`); },
    });
  };
}

// --- Step 2: the departed --------------------------------------------------------------

function wireDeparted($, d, keep) {
  const prayed = () => { $("#frPrayed").textContent = `Prayed as: ${prayedAs(d)}`; };
  prayed();

  // The Roj and Mah of the death (or its date), from the server, to confirm (D5).
  let dayToken = 0;
  const showDay = async () => {
    const out = $("#frDeathDay");
    const mine = ++dayToken;
    const parsi = d.deathBy === "parsi";
    if (parsi ? !(d.deathRoj && (d.deathMah || d.deathMah === "13")) : !d.death) { out.textContent = ""; return; }
    out.textContent = "Working it out...";
    try {
      const day = await managerDeathDay({
        calendar: d.calendar, death_date: parsi ? null : d.death,
        death_roj: parsi ? Number(d.deathRoj) : null, death_mah: parsi ? Number(d.deathMah) : null,
      });
      if (mine !== dayToken || !out.isConnected) return;
      out.innerHTML = parsi
        ? `That is <b>${esc(gregLabel(day.date))}</b> (${esc(day.label)}). Please check it is right.`
        : `That is <b>${esc(day.label)}</b>. Please check it is right.`;
    } catch (e) {
      if (mine !== dayToken || !out.isConnected) return;
      out.textContent = e.message;
    }
  };
  showDay();

  const bind = (sel, key, after, touched) => {
    const el = $(sel);
    el.addEventListener(el.tagName === "SELECT" || el.type === "date" ? "change" : "input",
      () => { d[key] = el.value; if (touched) d.deathTouched = true; keep(); if (after) after(); });
  };
  bind("#frTitle", "title", prayed);
  bind("#frName", "name", prayed);
  bind("#frParent", "parent", prayed);
  bind("#frCalendar", "calendar", showDay);
  bind("#frDeathDate", "death", showDay, true);
  bind("#frDeathMah", "deathMah", showDay, true);
  $("#frDeathRoj").onchange = (e) => {
    const v = e.target.value;
    d.deathTouched = true;
    if (v.startsWith("g")) {            // a Gatha day has no Mah of its own
      d.deathMah = "13"; d.deathRoj = v.slice(1);
      $("#frMahBox").style.display = "none";
    } else {
      if (d.deathMah === "13") { d.deathMah = ""; $("#frDeathMah").value = ""; }
      d.deathRoj = v;
      $("#frMahBox").style.display = "";
    }
    keep();
    showDay();
  };
  $("#frDeathBy").onclick = () => {
    d.deathBy = d.deathBy === "parsi" ? "date" : "parsi";
    d.deathTouched = true;
    keep();
    const parsi = d.deathBy === "parsi";
    $("#frDateBox").style.display = parsi ? "none" : "";
    $("#frParsiBox").style.display = parsi ? "" : "none";
    $("#frDeathBy").textContent = parsi ? "Use the date instead" : "Give the Roj and Mah instead (a death before sunrise)";
    clearProblems($("#frCard"));
    showDay();
  };
}

// --- Step 3: the prayers ---------------------------------------------------------------

function wireStepThree($, d, keep) {
  const bind = (sel, key) => {
    const el = $(sel);
    el.addEventListener(el.tagName === "SELECT" || el.type === "date" || el.type === "time" ? "change" : "input",
      () => { d[key] = el.value; keep(); });
  };
  bind("#frGsDate", "gsDate");
  bind("#frGsGeh", "gsGeh");
  bind("#frUtDate", "utDate");
  bind("#frUtTime", "utTime");
  bind("#frMobeds", "mobeds");
  $("#frCard").querySelectorAll("[name=frOb]").forEach(r => { r.onchange = () => { d.obsequies = r.value; keep(); }; });
}

// --- Step 4: the fire temple -------------------------------------------------------------

function agyariCards(list, empty) {
  return list.length ? list.map(agyariRowHtml).join("") : empty;
}

function wireRows(container, list, onPick) {
  container.querySelectorAll("[data-i]").forEach(row => {
    const a = list[+row.dataset.i];
    if (!a.may_send) {
      // Shown so the manager knows it is there, but a request would reach nobody.
      row.removeAttribute("role");
      row.tabIndex = -1;
      return;
    }
    row.onclick = () => onPick(a);
  });
}

/**
 * The list of fire temples, already full when the step opens, a search above it, and
 * "Save without sending". ``load()`` reads the list; ``pick(a)`` is what tapping a fire
 * temple does; ``placeId`` is where the search measures from. Used for a new record (the
 * record is saved when a fire temple is tapped) and for a saved one (Send to another).
 */
function fireTempleStep(host, { head, placeId, load, pick, alive, saveLater = null, note = "" }) {
  host.innerHTML = `
    ${head}
    <div class="card">
      <p class="meta" id="ftNote" role="status" style="margin:0 0 8px">${esc(note)}</p>
      <input type="text" id="ftSearch" placeholder="Search by name or town" autocomplete="off">
      <p class="meta" id="ftIntro" style="margin:8px 0"></p>
      <div id="ftList"><p class="meta">Loading...</p></div>
      ${saveLater ? `<div class="action-bar"><button type="button" class="ghost" id="ftSave">Save without sending</button></div>` : ""}
    </div>`;
  const list = host.querySelector("#ftList");
  const intro = host.querySelector("#ftIntro");
  const input = host.querySelector("#ftSearch");
  let whatsappOn = false;
  let full = null;
  let token = 0;

  const paintFull = () => {
    if (!full) return;
    intro.textContent = full.place_has_position
      ? "Fire temples with someone in Mobed Diary: the family's usual one first, then the nearest, then the rest by town."
      : "Fire temples with someone in Mobed Diary: the family's usual one first, then the rest by town.";
    list.innerHTML = agyariCards(full.agyaries, `<p class="meta">No fire temple has anyone in Mobed Diary yet.
      Search to see the others, and get in touch with one yourself.</p>`);
    wireRows(list, full.agyaries, (a) => pick(a, whatsappOn));
  };
  const loadFull = async () => {
    const mine = ++token;
    list.innerHTML = `<p class="meta">Loading...</p>`;
    let got;
    try {
      got = await load();
    } catch (e) {
      if (!alive() || mine !== token) return;
      list.innerHTML = `<div class="load-failed" role="alert"><p><b></b></p>
        <button class="small" type="button" data-retry>Try again</button></div>`;
      list.querySelector("b").textContent = e.message;
      list.querySelector("[data-retry]").onclick = loadFull;
      return;
    }
    if (!alive() || mine !== token || !list.isConnected) return;
    full = got;
    whatsappOn = got.whatsapp_on;
    if (!input.value.trim()) paintFull();
  };
  loadFull();

  let timer;
  input.oninput = () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const q = input.value.trim();
      const mine = ++token;
      if (!q) { paintFull(); return; }
      let got;
      try {
        got = await managerSearchAgyaries(q, placeId);
      } catch (e) {
        if (mine === token && list.isConnected) list.innerHTML = `<p class="meta" role="alert">${esc(e.message)}</p>`;
        return;
      }
      if (mine !== token || !alive() || !list.isConnected) return;
      whatsappOn = got.whatsapp_on;
      intro.textContent = "Search results. A fire temple nobody uses in Mobed Diary yet cannot be sent to.";
      list.innerHTML = agyariCards(got.agyaries, `<p class="meta">No fire temple found for “${esc(q)}”.</p>`);
      wireRows(list, got.agyaries, (a) => pick(a, whatsappOn));
    }, 250);
  };
  if (saveLater) host.querySelector("#ftSave").onclick = saveLater;
}

/** Step 4 of a new record: the summary, the list, then save and send. */
function wireFireTemple(d, { alive, save, clear }) {
  const host = document.getElementById("frStep4");
  const head = `
    <div class="card">
      <h2 style="margin:0">${esc(prayedAs(d))}</h2>
      <p class="meta" style="margin:4px 0 0">${d.deathBy === "parsi" ? "Died on the Parsi day you gave"
        : `Died ${esc(gregShort(d.death))}`} · ${d.obsequies === "one_day" ? "one day" : "four days"} of prayers</p>
      <p class="meta" style="margin:4px 0 0">Family: ${esc(d.contactName)}, ${esc(d.contactPhone)}</p>
    </div>`;
  let busy = false;
  fireTempleStep(host, {
    head, placeId: d.placeId, alive,
    note: d.recordId ? "Saved. It is not sent yet: choose a fire temple, or save it for later." : "",
    load: () => managerSuggestedFor(d.placeId, d.contactPhone),
    pick: async (a, whatsappOn) => {
      if (busy) return;
      busy = true;
      try {
        const res = await save();
        if (!res || !alive()) return;
        if (!res.record.may_send) {
          clear();
          flashInfo("Saved, but it cannot be sent from here now.");
          return navigate(managerHash(`/record/${res.record.id}`), { replace: true });
        }
        const noteEl = document.getElementById("ftNote");
        if (noteEl) noteEl.textContent = "Saved. It is not sent yet: choose a fire temple, or save it for later.";
        confirmSend(res.record, a, whatsappOn, { onSent: clear });
      } finally {
        busy = false;
      }
    },
    saveLater: async () => {
      if (busy) return;
      busy = true;
      try {
        const res = await save();
        if (!res || !alive()) return;
        clear();
        flashInfo("Saved. You can send it to a fire temple later, from the record.");
        navigate(managerHash(`/record/${res.record.id}`), { replace: true });
      } finally {
        busy = false;
      }
    },
  });
}

// --- The routes -------------------------------------------------------------------------

export function renderRecordNew() {
  const places = managerPlaces();
  if (places.length && !places.some(p => p.is_active)) {
    flashInfo("Your place is turned off in Mobed Diary at the moment, so a death cannot be recorded there.");
    return navigate(managerHash(), { replace: true });
  }
  return renderFlow(null);
}

async function fetchRecord(id, retry) {
  try {
    return (await managerRecord(id)).record;
  } catch (e) {
    screenFailed(e.message, retry);
    return null;
  }
}

export async function renderRecordEdit({ id }) {
  chrome(true);
  loading();
  const alive = navGuard();
  const rec = await fetchRecord(id, () => renderRecordEdit({ id }));
  if (!rec || !alive()) return;
  if (!rec.may_edit) {
    flashInfo("A fire temple has accepted this request, so the record can no longer be changed here.");
    return navigate(managerHash(`/record/${id}`), { replace: true });
  }
  return renderFlow(rec);
}

/** Choosing a fire temple for a record already saved: after Withdraw (Send to another fire
 *  temple), or one saved without sending. The same list as step 4. */
export async function renderRecordSend({ id }) {
  chrome(true);
  refreshHeader();
  showFab(false);
  loading();
  const alive = navGuard();
  const rec = await fetchRecord(id, () => renderRecordSend({ id }));
  if (!rec || !alive()) return;
  if (!rec.may_send) {
    flashInfo(rec.requests.some(q => q.status === "waiting")
      ? "This request is already waiting at a fire temple. Withdraw it first to send it to another."
      : "This record cannot be sent now.");
    return navigate(managerHash(`/record/${id}`), { replace: true });
  }
  mainEl.innerHTML = `
    <div class="step-head"><h2 class="step-q">${esc(QUESTIONS[3])}</h2></div>
    <div id="frStep4"></div>
    <div class="wizard-nav" style="margin-top:4px"><button type="button" class="secondary" id="frBack">Back</button></div>`;
  toTop();
  document.getElementById("frBack").onclick = () => back(managerHash(`/record/${id}`));
  fireTempleStep(document.getElementById("frStep4"), {
    head: `<div class="card"><h2 style="margin:0">${esc(rec.prayed_name)}</h2>
      <p class="meta" style="margin:4px 0 0">Choose the fire temple; its panthaky is asked, or if it has none in
        Mobed Diary, its mobeds.</p></div>`,
    placeId: rec.funeral_place && rec.funeral_place.id, alive,
    load: () => managerSuggested(rec.id),
    pick: (a, whatsappOn) => confirmSend(rec, a, whatsappOn),
  });
}
