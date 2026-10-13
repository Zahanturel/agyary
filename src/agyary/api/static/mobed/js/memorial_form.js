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

// The named days a family can add on top of the opening. The spellings are
// provisional (the mobeds settle them) and mirror NAMED_DAYS in
// calendar/memorial.py, which is what labels the saved schedule. The 10th is
// part of the opening, so it is not listed here.
const NAMED_DAYS = [
  [29, "Deci"], [30, "Masiso"], [59, "Deci"], [60, "Bamsi"],
  [179, "Deci"], [180, "Chamsi"], [359, "Deci"], [360, "Varsi"],
];

const MAX = { months: 120, years: 50, parabYears: 25 };

// A death on a Gatha day is given as Mah "Gatha days" (13) and the Gatha's number.
const GATHAS = ["Ahunavad", "Ushtavad", "Spentamad", "Vohukhshathra", "Vahishtoisht", "Sixth (Fasli leap years)"];

export function blankMemorialDraft() {
  return {
    name: "", death: "", calendar: primarySystem(), opening: null, days: [],
    // How the death is given (D5): a Gregorian date, or its Parsi day - a death
    // before sunrise belongs to the previous Parsi day, and the mobed knows which.
    deathBy: "date", deathRoj: "", deathMah: "", deathYear: "",
    monthly: false, months: "", yearly: false, years: "",
    parab: false, parabWhich: null, parabYears: "",
    services: [],
  };
}

/** The request body, or an error message if something is missing. Every check
 *  here is also made by the server; this is for a clear message before the
 *  round trip. */
export function buildMemorialBody(draft) {
  if (!draft.name.trim()) return { error: "Please enter the departed person's name." };
  const byParsi = draft.deathBy === "parsi";
  if (!byParsi && !draft.death) return { error: "Please enter the date of death." };
  if (byParsi && (!draft.deathRoj || !draft.deathMah)) return { error: "Please choose the Roj and the Mah of the death." };
  if (byParsi && draft.deathYear && !/^\d{3,4}$/.test(String(draft.deathYear).trim())) {
    return { error: "The Parsi year is a number such as 1396, or leave it empty." };
  }
  if (!draft.opening) return { error: "Choose how the opening is kept: days 1 to 10, or the 10th day only." };

  const count = (raw, label, unit, max) => {
    const n = Number(raw);
    if (!raw || !Number.isInteger(n) || n < 1) return { error: `Say how many ${unit} the ${label} should run for.` };
    if (n > max) return { error: `The ${label} can run for at most ${max} ${unit}.` };
    return { n };
  };
  const body = {
    departed_name: draft.name.trim(),
    death_date: byParsi ? null : draft.death,
    death_roj: byParsi ? Number(draft.deathRoj) : null,
    death_mah: byParsi ? Number(draft.deathMah) : null,
    death_year: byParsi && draft.deathYear ? Number(draft.deathYear) : null,
    calendar: draft.calendar,
    opening: draft.opening,
    day_counts: draft.days.slice().sort((a, b) => a - b),
    monthly: null, yearly: null, parabs: null,
    service_ids: draft.services,
  };
  if (draft.monthly) {
    const r = count(draft.months, "monthly observances", "months", MAX.months);
    if (r.error) return r;
    body.monthly = { count: r.n };
  }
  if (draft.yearly) {
    const r = count(draft.years, "yearly observances", "years", MAX.years);
    if (r.error) return r;
    body.yearly = { count: r.n };
  }
  if (draft.parab) {
    if (!draft.parabWhich) return { error: "Choose which Parabs: Fravardin and Tir only, or all of them." };
    const r = count(draft.parabYears, "Parabs", "years", MAX.parabYears);
    if (r.error) return r;
    body.parabs = { which: draft.parabWhich, years: r.n };
  }
  if (!draft.services.length) return { error: "Choose at least one service: Afringan, Farokshi or Baaj." };
  return { body };
}

/** The Roj picker: the thirty Roj, or the Gatha days when the Mah is "Gatha days". */
function rojOptionsHtml(draft) {
  const names = String(draft.deathMah) === "13"
    ? GATHAS
    : ((state.calendarOptions && state.calendarOptions.roj) || []).map(o => o.title);
  return `<option value="">Choose</option>` + names.map((n, i) =>
    `<option value="${i + 1}" ${String(draft.deathRoj) === String(i + 1) ? "selected" : ""}>${esc(n)}</option>`).join("");
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
        <label>Departed person</label>
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
        <label>Calendar</label>
        <select id="mmCalendar">${[["shenshai", "Shenshai"], ["kadmi", "Kadmi"], ["fasli", "Fasli"]].map(([k, v]) =>
          `<option value="${k}" ${draft.calendar === k ? "selected" : ""}>${v}</option>`).join("")}</select>
      </div>

      <div class="card">
        <h2>Observances</h2>

        <div class="names-group-label"><b>Prayers</b><span>on every day</span></div>
        <div class="chip-row" id="mmServices">${services.map(s => `
          <label class="chip ${draft.services.includes(s.id) ? "on" : ""}" style="margin:0">
            <input type="checkbox" data-svc="${s.id}" ${draft.services.includes(s.id) ? "checked" : ""}>${esc(s.name)}</label>`).join("")}
        </div>

        <div class="names-group-label"><b>First days</b></div>
        <div class="choice-group">
          ${radio("mmOpening", "mmOpenAll", "days_1_to_10", draft.opening === "days_1_to_10", "Days 1 to 10")}
          ${radio("mmOpening", "mmOpenTenth", "tenth_only", draft.opening === "tenth_only", "10th day only")}
        </div>

        <div class="names-group-label"><b>Named days</b></div>
        <div class="choice-group">${NAMED_DAYS.map(([n, name]) => `
          <div class="check-row"><input type="checkbox" data-day="${n}" id="mmDay${n}" ${has(n) ? "checked" : ""}>
            <label for="mmDay${n}">${n}th day · ${name}</label></div>`).join("")}
        </div>

        <div class="names-group-label"><b>Repeating</b></div>
        <div class="choice-group">
          <div class="check-row"><input type="checkbox" id="mmMonthly" ${draft.monthly ? "checked" : ""}>
            <label for="mmMonthly">Every month</label></div>
          <div class="sub-field" id="mmMonthlyBox" style="${draft.monthly ? "" : "display:none"}">
            <label>For how many months</label>
            <input type="number" inputmode="numeric" min="1" max="${MAX.months}" id="mmMonths" value="${esc(draft.months)}"></div>

          <div class="check-row"><input type="checkbox" id="mmYearly" ${draft.yearly ? "checked" : ""}>
            <label for="mmYearly">Every year</label></div>
          <div class="sub-field" id="mmYearlyBox" style="${draft.yearly ? "" : "display:none"}">
            <label>For how many years</label>
            <input type="number" inputmode="numeric" min="1" max="${MAX.years}" id="mmYears" value="${esc(draft.years)}"></div>

          <div class="check-row"><input type="checkbox" id="mmParab" ${draft.parab ? "checked" : ""}>
            <label for="mmParab">Parabs</label></div>
          <div class="sub-field" id="mmParabBox" style="${draft.parab ? "" : "display:none"}">
            ${radio("mmParabWhich", "mmParabFT", "fravardin_tir", draft.parabWhich === "fravardin_tir", "Fravardin and Tir only")}
            ${radio("mmParabWhich", "mmParabAll", "all", draft.parabWhich === "all", "All Parabs")}
            <label>For how many years</label>
            <input type="number" inputmode="numeric" min="1" max="${MAX.parabYears}" id="mmParabYears" value="${esc(draft.parabYears)}"></div>
        </div>
      </div>`;
}

/** Hook the form's controls up to `draft`. `root` is the element holding the
 *  form's HTML. */
export function wireMemorialForm(root, draft) {
  const $ = (sel) => root.querySelector(sel);

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
  $("#mmCalendar").onchange = (e) => { draft.calendar = e.target.value; readParsi(); };
  root.querySelectorAll("[name=mmOpening]").forEach(r => {
    r.onchange = () => { draft.opening = r.value; };
  });
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
  series("#mmParab", "#mmParabBox", "#mmParabYears", "parab", "parabYears");
  root.querySelectorAll("[name=mmParabWhich]").forEach(r => {
    r.onchange = () => { draft.parabWhich = r.value; };
  });

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
export function schedulePreviewHtml(body, preview, services, { heading = "" } = {}) {
  const today = todayIst();
  const names = body.service_ids
    .map(sid => (services.find(s => s.id === sid) || {}).name).filter(Boolean).join(", ");
  const passed = preview.observances.filter(o => o.date < today).length;
  return `
      <div class="card">
        ${heading}
        <p class="meta" style="margin:4px 0 0">${esc(body.departed_name)} · died ${esc(gregLabel(preview.death_date || body.death_date))}
          (${esc(parsiText(preview.death.mah === 13 ? { gatha_index: preview.death.roj } : preview.death))})</p>
        <p style="margin:12px 0 0;font-size:var(--text-sm)"><b>${preview.count} observance${preview.count === 1 ? "" : "s"}</b>,
          each with ${esc(names)}.</p>
        ${passed ? `<p class="meta" style="margin:4px 0 0">${passed} of these ${passed === 1 ? "has" : "have"}
          already passed - they stay on the calendar.</p>` : ""}
      </div>

      <div class="card">
        ${preview.observances.map((o, i) => `
          <div class="obs ${o.date < today ? "past" : ""} ${i === preview.observances.length - 1 ? "last" : ""}">
            <div class="obs-head" style="cursor:default">
              <div class="obs-title"><b>${esc(o.label)}</b><span>${esc(parsiText(o))}</span></div>
              <div class="obs-when">${esc(gregLabel(o.date))}</div>
            </div>
          </div>`).join("")}
      </div>`;
}
