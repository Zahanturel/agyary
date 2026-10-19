"use strict";

/**
 * The memorial form, shared by the two places a memorial is started: a
 * behdin's own page, and the New behdin page - where the whole schedule is
 * laid out from the date of death in one go.
 *
 * Nothing is pre-chosen. How the opening is kept, whether anything repeats,
 * for how long, and which services - the mobed picks each one. A repeating
 * series cannot be ticked without a length: there is no default length and
 * no "keep going", so the schedule is always a finite list that can be read
 * whole before it is saved.
 *
 * The form is plain HTML plus a draft object it keeps up to date, so a page
 * can hide it, show a preview, and bring it back exactly as it was.
 */

import { primarySystem, state } from "./state.js";
import { esc, gregLabel, todayIst, parsiLabel, MAH_NAMES_JS } from "./util.js";
import { parsiText } from "./screens/memorial.js";
import { flagProblems } from "./fielderrors.js";
import { convertDate } from "./api.js";

// The named days a family can add on top of the opening. The spellings are
// provisional (the mobeds settle them) and mirror NAMED_DAYS in
// calendar/memorial.py, which is what labels the saved schedule. The 10th is
// Dasmi is the 10th day, chosen here like the rest; days 1 to 9 are not offered.
const NAMED_DAYS = [
  [10, "Dasmi"], [29, "Deci"], [30, "Masiso"], [59, "Deci"], [60, "Bamsi"],
  [179, "Deci"], [180, "Chamsi"], [359, "Deci"], [360, "Varsi"],
];

const MAX = { months: 120, years: 50, parabYears: 25, birthYears: 50 };

// A death on a Gatha day is given as Mah "Gatha days" (13) and the Gatha's number.
const GATHAS = ["Ahunavad", "Ushtavad", "Spentamad", "Vohukhshathra", "Vahishtoisht", "Sixth (Fasli leap years)"];

export function blankMemorialDraft() {
  return {
    name: "", death: "", calendar: primarySystem(), days: [],
    // How the death is given (D5): a Gregorian date, or its Parsi day - a death
    // before sunrise belongs to the previous Parsi day, and the mobed knows which.
    // Where the schedule starts: the whole of it from the death, or only what is
    // still ahead from today (a family arriving late). Counting is from the death either way.
    startFrom: "death",
    deathBy: "date", deathRoj: "", deathMah: "", deathYear: "",
    monthly: false, months: "", yearly: false, years: "",
    fravRoj: false, fravRojMonths: "",
    parab: false, parabWhich: null, parabYears: "",
    // The deceased's birthday: a date fills in its Roj and Mah, or give Roj and Mah.
    birthday: false, birthDate: "", birthRoj: "", birthMah: "", birthYears: "",
    services: [],
  };
}

/** The request body, or `problems` - one per field that needs attention, each
 *  with the `target` selector of its control (see fielderrors.js) - plus
 *  `error`, the first message, for callers with nowhere to point. Every check
 *  here is also made by the server; this is for a clear message before the
 *  round trip. */
export function buildMemorialBody(draft) {
  const problems = [];
  const bad = (target, message) => problems.push({ target, message });
  if (!draft.name.trim()) bad("#mmName", "Please enter the departed person's name.");
  const byParsi = draft.deathBy === "parsi";
  if (!byParsi && !draft.death) bad("#mmDeath", "Please enter the date of death.");
  if (byParsi) {
    if (!draft.deathMah) bad("#mmDeathMah", "Please choose the Mah of the death.");
    if (!draft.deathRoj) bad("#mmDeathRoj", "Please choose the Roj of the death.");
    if (draft.deathYear && !/^\d{3,4}$/.test(String(draft.deathYear).trim())) {
      bad("#mmDeathYear", "The Parsi year is a number such as 1396, or leave it empty.");
    }
  }

  const count = (raw, target, label, unit, max) => {
    const n = Number(raw);
    if (!raw || !Number.isInteger(n) || n < 1) { bad(target, `Say how many ${unit} the ${label} should run for.`); return null; }
    if (n > max) { bad(target, `The ${label} can run for at most ${max} ${unit}.`); return null; }
    return n;
  };
  const body = {
    departed_name: draft.name.trim(),
    death_date: byParsi ? null : draft.death,
    death_roj: byParsi ? Number(draft.deathRoj) : null,
    death_mah: byParsi ? Number(draft.deathMah) : null,
    death_year: byParsi && draft.deathYear ? Number(draft.deathYear) : null,
    calendar: draft.calendar,
    opening: "none",
    start_from: draft.startFrom === "today" ? todayIst() : null,
    day_counts: draft.days.slice().sort((a, b) => a - b),
    monthly: null, yearly: null, fravardin_roj: null, parabs: null, birthday: null,
    service_ids: draft.services,
  };
  if (!draft.services.length) bad("#mmServices", "Choose at least one prayer: Afringan, Farokshi, Baaj or Satum.");
  if (!draft.days.length && !draft.monthly && !draft.yearly && !draft.fravRoj && !draft.parab && !draft.birthday) {
    bad("#mmSchedule", "Choose at least one day, or something that repeats.");
  }
  if (draft.monthly) {
    const n = count(draft.months, "#mmMonths", "monthly observances", "months", MAX.months);
    if (n) body.monthly = { count: n };
  }
  if (draft.yearly) {
    const n = count(draft.years, "#mmYears", "yearly observances", "years", MAX.years);
    if (n) body.yearly = { count: n };
  }
  if (draft.fravRoj) {
    const n = count(draft.fravRojMonths, "#mmFravRojMonths", "Roj Fravardin observances", "months", MAX.months);
    if (n) body.fravardin_roj = { count: n };
  }
  if (draft.parab) {
    if (!draft.parabWhich) bad("#mmParabWhichBox", "Choose which Parabs: Fravardin and Tir only, or all of them.");
    const n = count(draft.parabYears, "#mmParabYears", "Parabs", "years", MAX.parabYears);
    if (n && draft.parabWhich) body.parabs = { which: draft.parabWhich, years: n };
  }
  if (draft.birthday) {
    if (!draft.birthMah) bad("#mmBirthMah", "Please choose the Mah of the birthday.");
    if (!draft.birthRoj) bad("#mmBirthRoj", "Please choose the Roj of the birthday.");
    const n = count(draft.birthYears, "#mmBirthYears", "birthday", "years", MAX.birthYears);
    if (n && draft.birthMah && draft.birthRoj) {
      body.birthday = { roj: Number(draft.birthRoj), mah: Number(draft.birthMah), years: n };
    }
  }
  if (problems.length) return { problems, error: problems[0].message };
  return { body };
}

/** Point at what is wrong in the form below `root`; true if the draft had problems. */
export function showMemorialProblems(root, built) {
  if (!built.problems) return false;
  flagProblems(root, built.problems);
  return true;
}

/** The Roj picker: the thirty Roj, or the Gatha days when the Mah is "Gatha days". */
function rojOptionsHtml(draft) {
  const names = String(draft.deathMah) === "13"
    ? GATHAS
    : ((state.calendarOptions && state.calendarOptions.roj) || []).map(o => o.title);
  return `<option value="">Choose</option>` + names.map((n, i) =>
    `<option value="${i + 1}" ${String(draft.deathRoj) === String(i + 1) ? "selected" : ""}>${esc(n)}</option>`).join("");
}

/** The birthday's Roj picker: the thirty Roj (never a Gatha day). */
function birthRojOptionsHtml(draft) {
  const names = ((state.calendarOptions && state.calendarOptions.roj) || []).map(o => o.title);
  return `<option value="">Choose</option>` + names.map((n, i) =>
    `<option value="${i + 1}" ${String(draft.birthRoj) === String(i + 1) ? "selected" : ""}>${esc(n)}</option>`).join("");
}

/** The form: who and when, then one card holding every option. `heading` goes
 *  at the top of the first card; `intro` is a line under it. */
export function memorialFormHtml(draft, services, { heading = "", intro = "" } = {}) {
  const has = (n) => draft.days.includes(n);
  const radio = (name, id, value, checked, text) =>
    `<div class="check-row"><input type="radio" name="${name}" id="${id}" value="${value}" ${checked ? "checked" : ""}>
        <label for="${id}">${text}</label></div>`;
  return `
      <div class="card">
        ${heading}
        ${intro ? `<p class="meta">${intro}</p>` : ""}
        <label for="mmName">Departed person</label>
        <input type="text" id="mmName" autocomplete="off" value="${esc(draft.name)}">
        <label>Death</label>
        <div class="choice-group">
          ${radio("mmDeathBy", "mmDeathByDate", "date", draft.deathBy !== "parsi", "By the date")}
          ${radio("mmDeathBy", "mmDeathByParsi", "parsi", draft.deathBy === "parsi",
            "By Roj and Mah (for a death before sunrise, give the Parsi day it belonged to)")}
        </div>
        <div id="mmDeathDateBox" style="${draft.deathBy === "parsi" ? "display:none" : ""}">
          <label for="mmDeath">Date of death</label>
          <input type="date" id="mmDeath" max="${todayIst()}" value="${esc(draft.death)}">
          <p class="meta" id="mmParsi" style="margin:6px 0 0"></p>
        </div>
        <div id="mmDeathParsiBox" style="${draft.deathBy === "parsi" ? "" : "display:none"}">
          <label for="mmDeathMah">Mah</label>
          <select id="mmDeathMah"><option value="">Choose</option>${MAH_NAMES_JS.map((n, i) =>
            `<option value="${i + 1}" ${String(draft.deathMah) === String(i + 1) ? "selected" : ""}>${esc(n)}</option>`).join("")}
            <option value="13" ${String(draft.deathMah) === "13" ? "selected" : ""}>Gatha days</option></select>
          <label for="mmDeathRoj">Roj</label>
          <select id="mmDeathRoj">${rojOptionsHtml(draft)}</select>
          <label for="mmDeathYear">Parsi year (leave empty for the most recent)</label>
          <input type="text" id="mmDeathYear" inputmode="numeric" maxlength="4" value="${esc(draft.deathYear)}">
        </div>
        <label for="mmCalendar">Calendar</label>
        <select id="mmCalendar">${[["shenshai", "Shenshai"], ["kadmi", "Kadmi"], ["fasli", "Fasli"]].map(([k, v]) =>
          `<option value="${k}" ${draft.calendar === k ? "selected" : ""}>${v}</option>`).join("")}</select>

        <label>Schedule from</label>
        <div class="choice-group">
          ${radio("mmStart", "mmStartDeath", "death", draft.startFrom !== "today", "The day of death (the whole schedule)")}
          ${radio("mmStart", "mmStartToday", "today", draft.startFrom === "today", "Today (only what is still ahead)")}
        </div>
        <div id="mmStartTodayBox" style="${draft.startFrom === "today" ? "" : "display:none"}">
          <label for="mmStartDate">Today</label>
          <input type="date" id="mmStartDate" value="${todayIst()}" disabled>
          <p class="meta" id="mmStartParsi" style="margin:6px 0 0"></p>
          <p class="meta" style="margin:6px 0 0">Still counted from the death. Days that have already passed are left
            out, and months, years, Parabs and birthdays run from the next date that is still to come.</p>
        </div>
      </div>

      <div class="card">
        <h2>Observances</h2>

        <div class="names-group-label"><b>Prayers</b><span>on every day</span></div>
        <div class="chip-row" id="mmServices">${services.map(s => `
          <label class="chip ${draft.services.includes(s.id) ? "on" : ""}" style="margin:0">
            <input type="checkbox" data-svc="${s.id}" ${draft.services.includes(s.id) ? "checked" : ""}>${esc(s.name)}</label>`).join("")}
        </div>

        <div class="names-group-label"><b>Named days</b></div>
        <div id="mmSchedule">
        <div class="choice-group">${NAMED_DAYS.map(([n, name]) => `
          <div class="check-row"><input type="checkbox" data-day="${n}" id="mmDay${n}" ${has(n) ? "checked" : ""}>
            <label for="mmDay${n}">${n}th day · ${name}</label></div>`).join("")}
        </div>

        <div class="names-group-label"><b>Repeating</b></div>
        <div class="choice-group">
          <div class="check-row"><input type="checkbox" id="mmMonthly" ${draft.monthly ? "checked" : ""}>
            <label for="mmMonthly">Every month</label></div>
          <div class="sub-field" id="mmMonthlyBox" style="${draft.monthly ? "" : "display:none"}">
            <label for="mmMonths">For how many months</label>
            <input type="number" inputmode="numeric" min="1" max="${MAX.months}" id="mmMonths" value="${esc(draft.months)}"></div>

          <div class="check-row"><input type="checkbox" id="mmYearly" ${draft.yearly ? "checked" : ""}>
            <label for="mmYearly">Every year</label></div>
          <div class="sub-field" id="mmYearlyBox" style="${draft.yearly ? "" : "display:none"}">
            <label for="mmYears">For how many years</label>
            <input type="number" inputmode="numeric" min="1" max="${MAX.years}" id="mmYears" value="${esc(draft.years)}"></div>

          <div class="check-row"><input type="checkbox" id="mmFravRoj" ${draft.fravRoj ? "checked" : ""}>
            <label for="mmFravRoj">Roj Fravardin, every month</label></div>
          <div class="sub-field" id="mmFravRojBox" style="${draft.fravRoj ? "" : "display:none"}">
            <label for="mmFravRojMonths">For how many months</label>
            <input type="number" inputmode="numeric" min="1" max="${MAX.months}" id="mmFravRojMonths" value="${esc(draft.fravRojMonths)}"></div>

          <div class="check-row"><input type="checkbox" id="mmParab" ${draft.parab ? "checked" : ""}>
            <label for="mmParab">Parabs</label></div>
          <div class="sub-field" id="mmParabBox" style="${draft.parab ? "" : "display:none"}">
            <div id="mmParabWhichBox">
            ${radio("mmParabWhich", "mmParabFT", "fravardin_tir", draft.parabWhich === "fravardin_tir", "Fravardin and Tir only")}
            ${radio("mmParabWhich", "mmParabAll", "all", draft.parabWhich === "all", "All Parabs")}</div>
            <label for="mmParabYears">For how many years</label>
            <input type="number" inputmode="numeric" min="1" max="${MAX.parabYears}" id="mmParabYears" value="${esc(draft.parabYears)}"></div>

          <div class="check-row"><input type="checkbox" id="mmBirthday" ${draft.birthday ? "checked" : ""}>
            <label for="mmBirthday">Birthday of the departed</label></div>
          <div class="sub-field" id="mmBirthdayBox" style="${draft.birthday ? "" : "display:none"}">
            <label for="mmBirthDate">Date of birth (fills in the Roj and Mah)</label>
            <input type="date" id="mmBirthDate" max="${todayIst()}" value="${esc(draft.birthDate)}">
            <p class="meta" id="mmBirthNote" style="margin:6px 0 0"></p>
            <label for="mmBirthMah">Mah</label>
            <select id="mmBirthMah"><option value="">Choose</option>${MAH_NAMES_JS.map((n, i) =>
              `<option value="${i + 1}" ${String(draft.birthMah) === String(i + 1) ? "selected" : ""}>${esc(n)}</option>`).join("")}</select>
            <label for="mmBirthRoj">Roj</label>
            <select id="mmBirthRoj">${birthRojOptionsHtml(draft)}</select>
            <label for="mmBirthYears">For how many years</label>
            <input type="number" inputmode="numeric" min="1" max="${MAX.birthYears}" id="mmBirthYears" value="${esc(draft.birthYears)}"></div>
        </div>
        </div>
      </div>`;
}

/** Hook the form's controls up to `draft`. `root` is the element holding the
 *  form's HTML. */
export function wireMemorialForm(root, draft, onChange) {
  const $ = (sel) => root.querySelector(sel);
  // Anything the mobed touches updates `draft` first (below), then bubbles
  // here, so the caller can keep a copy of the draft that outlives this screen.
  if (onChange) {
    root.addEventListener("input", () => onChange(draft));
    root.addEventListener("change", () => onChange(draft));
  }

  const readParsi = async () => {
    const note = $("#mmParsi");
    if (!draft.death) { note.textContent = ""; return; }
    const label = await parsiLabel(draft.death, draft.calendar);
    if (note.isConnected) note.textContent = label;
  };
  readParsi();

  $("#mmName").oninput = (e) => { draft.name = e.target.value; };
  $("#mmDeath").onchange = (e) => { draft.death = e.target.value; readParsi(); };
  root.querySelectorAll("[name=mmDeathBy]").forEach(r => {
    r.onchange = () => {
      draft.deathBy = r.value;
      $("#mmDeathDateBox").style.display = r.value === "parsi" ? "none" : "";
      $("#mmDeathParsiBox").style.display = r.value === "parsi" ? "" : "none";
    };
  });
  $("#mmDeathMah").onchange = (e) => {
    draft.deathMah = e.target.value;
    draft.deathRoj = "";
    $("#mmDeathRoj").innerHTML = rojOptionsHtml(draft);
  };
  $("#mmDeathRoj").onchange = (e) => { draft.deathRoj = e.target.value; };
  $("#mmDeathYear").oninput = (e) => { draft.deathYear = e.target.value; };
  const readStart = async () => {
    const note = $("#mmStartParsi");
    const label = await parsiLabel(todayIst(), draft.calendar);
    if (note.isConnected) note.textContent = label;
  };
  readStart();
  root.querySelectorAll("[name=mmStart]").forEach(r => {
    r.onchange = () => {
      draft.startFrom = r.value;
      $("#mmStartTodayBox").style.display = r.value === "today" ? "" : "none";
    };
  });
  $("#mmCalendar").onchange = (e) => { draft.calendar = e.target.value; readParsi(); readStart(); };
  root.querySelectorAll("[data-day]").forEach(cb => {
    cb.onchange = () => {
      const n = Number(cb.dataset.day);
      draft.days = cb.checked ? [...new Set([...draft.days, n])] : draft.days.filter(d => d !== n);
    };
  });

  // A series' length only appears once the series is ticked, and unticking it
  // forgets the length - nothing carries over by accident.
  const series = (checkId, boxId, inputId, flag, field) => {
    $(checkId).onchange = (e) => {
      draft[flag] = e.target.checked;
      $(boxId).style.display = e.target.checked ? "" : "none";
      if (!e.target.checked) { draft[field] = ""; $(inputId).value = ""; }
    };
    $(inputId).oninput = (e) => { draft[field] = e.target.value; };
  };
  series("#mmMonthly", "#mmMonthlyBox", "#mmMonths", "monthly", "months");
  series("#mmYearly", "#mmYearlyBox", "#mmYears", "yearly", "years");
  series("#mmFravRoj", "#mmFravRojBox", "#mmFravRojMonths", "fravRoj", "fravRojMonths");
  series("#mmParab", "#mmParabBox", "#mmParabYears", "parab", "parabYears");
  root.querySelectorAll("[name=mmParabWhich]").forEach(r => {
    r.onchange = () => { draft.parabWhich = r.value; };
  });

  // The birthday: a date gives the Roj and Mah (read in the family's calendar);
  // or they are chosen directly. Either way the Roj and Mah are what is used.
  $("#mmBirthday").onchange = (e) => {
    draft.birthday = e.target.checked;
    $("#mmBirthdayBox").style.display = e.target.checked ? "" : "none";
    if (!e.target.checked) {
      Object.assign(draft, { birthDate: "", birthRoj: "", birthMah: "", birthYears: "" });
      $("#mmBirthDate").value = ""; $("#mmBirthMah").value = ""; $("#mmBirthRoj").value = "";
      $("#mmBirthYears").value = ""; $("#mmBirthNote").textContent = "";
    }
  };
  $("#mmBirthMah").onchange = (e) => { draft.birthMah = e.target.value; };
  $("#mmBirthRoj").onchange = (e) => { draft.birthRoj = e.target.value; };
  $("#mmBirthYears").oninput = (e) => { draft.birthYears = e.target.value; };
  const readBirth = async () => {
    const note = $("#mmBirthNote");
    note.textContent = "";
    if (!draft.birthDate) return;
    try {
      const p = await convertDate(draft.birthDate, draft.calendar);
      if (!note.isConnected) return;
      if (p.is_gatha) { note.textContent = "That day is a Gatha day - give the birthday as a Roj and Mah instead."; return; }
      draft.birthMah = String(p.mah); draft.birthRoj = String(p.roj);
      $("#mmBirthMah").value = draft.birthMah; $("#mmBirthRoj").value = draft.birthRoj;
      note.textContent = `Roj ${p.roj_name}, Mah ${p.mah_name}`;
      if (onChange) onChange(draft);
    } catch (e) { /* leave it for the mobed to choose */ }
  };
  $("#mmBirthDate").onchange = (e) => { draft.birthDate = e.target.value; readBirth(); };
  // The calendar decides what Roj and Mah a date is.
  $("#mmCalendar").addEventListener("change", () => { if (draft.birthDate) readBirth(); });

  root.querySelectorAll("[data-svc]").forEach(cb => {
    cb.onchange = () => {
      const n = Number(cb.dataset.svc);
      cb.closest(".chip").classList.toggle("on", cb.checked);
      draft.services = cb.checked ? [...new Set([...draft.services, n])] : draft.services.filter(s => s !== n);
    };
  });
}

/** Every date the memorial would have, as a pair of cards - nothing is saved
 *  yet. `heading` goes at the top of the first card. */
export function schedulePreviewHtml(body, preview, services, { heading = "", removed = new Set() } = {}) {
  const today = todayIst();
  const names = body.service_ids
    .map(sid => (services.find(s => s.id === sid) || {}).name).filter(Boolean).join(", ");
  const kept = preview.observances.filter(o => !removed.has(o.code));
  const passed = kept.filter(o => o.date < today).length;
  return `
      <div class="card">
        ${heading}
        <p class="meta" style="margin:4px 0 0">${esc(body.departed_name)} · died ${esc(gregLabel(preview.death_date || body.death_date))}
          (${esc(parsiText(preview.death.mah === 13 ? { gatha_index: preview.death.roj } : preview.death))})</p>
        <p style="margin:12px 0 0;font-size:var(--text-sm)"><b id="schedCount">${kept.length} observance${kept.length === 1 ? "" : "s"}</b>,
          each with ${esc(names)}.</p>
        ${preview.passed_not_booked ? `<p class="meta" style="margin:4px 0 0">Starting from today:
          ${preview.passed_not_booked} earlier date${preview.passed_not_booked === 1 ? " was" : "s were"} already past and
          ${preview.passed_not_booked === 1 ? "is" : "are"} not booked.</p>` : ""}
        ${passed ? `<p class="meta" style="margin:4px 0 0">${passed} of these ${passed === 1 ? "has" : "have"}
          already passed - they stay on the calendar.</p>` : ""}
      </div>

      <div class="card">
        <div id="schedRows">${kept.map(o => `
          <div class="obs ${o.date < today ? "past" : ""}" data-code="${esc(o.code)}">
            <div class="obs-head" style="cursor:default">
              <div class="obs-title"><b>${esc(o.label)}</b><span>${esc(parsiText(o))}</span></div>
              <div class="obs-when">${esc(gregLabel(o.date))}</div>
              <button type="button" class="row-x" data-remove aria-label="Remove ${esc(o.label)} on ${esc(gregLabel(o.date))}"
                title="Remove this date">&times;</button>
            </div>
          </div>`).join("")}</div>
      </div>`;
}


/** Make the x on each date work: it asks "Remove this date?" in place, and a yes
 *  drops the row and adds its code to `removed` (which the caller sends as
 *  exclude_codes when it saves). Nothing else changes. `root` holds the preview. */
export function wireSchedulePreview(root, preview, removed, onChange) {
  const rows = root.querySelector("#schedRows");
  const count = root.querySelector("#schedCount");
  const total = () => preview.observances.length - removed.size;
  rows.addEventListener("click", (e) => {
    const x = e.target.closest("[data-remove]");
    const row = e.target.closest(".obs");
    if (!row) return;
    if (x) {
      if (row.querySelector(".row-confirm")) return;
      row.classList.add("row-pending");
      row.insertAdjacentHTML("beforeend", `<div class="row-confirm"><span>Remove this date?</span>
        <span class="row"><button type="button" class="ghost small" data-keep>Keep</button>
        <button type="button" class="small" data-yes>Remove</button></span></div>`);
      return;
    }
    if (e.target.closest("[data-keep]")) {
      row.classList.remove("row-pending");
      row.querySelector(".row-confirm").remove();
    } else if (e.target.closest("[data-yes]")) {
      if (total() <= 1) {   // an empty schedule is not a memorial
        row.classList.remove("row-pending");
        row.querySelector(".row-confirm").innerHTML = "<span>Keep at least one date.</span>";
        return;
      }
      removed.add(row.dataset.code);
      row.remove();
      count.textContent = `${total()} observance${total() === 1 ? "" : "s"}`;
      if (onChange) onChange(removed);
    }
  });
}
