"use strict";

/**
 * New memorial: a family tells us when someone died and which observances
 * they keep, and we lay out the whole schedule.
 *
 * Two steps on one route. The form, then a preview of every date - nothing is
 * saved until the mobed has seen the dates and confirms them.
 *
 * Nothing is pre-chosen. How the opening is kept, whether anything repeats,
 * for how long, and which services - the mobed picks each one. A repeating
 * series cannot be ticked without a length: there is no default length and
 * no "keep going", so the schedule is always a finite list that can be read
 * whole before it is saved.
 */

import { getBehdin, previewMemorial, createMemorial } from "../api.js";
import { state, primarySystem } from "../state.js";
import {
  chrome, mainEl, showFab, showError, refreshHeader, loading, backBar,
} from "../ui.js";
import { esc, gregLabel, todayIst, parsiLabel } from "../util.js";
import { navigate, back, navGuard } from "../router.js";
import { prayerServices, parsiText } from "./memorial.js";

// The named days a family can add on top of the opening. The spellings are
// provisional (the mobeds settle them) and mirror NAMED_DAYS in
// calendar/memorial.py, which is what labels the saved schedule. The 10th is
// part of the opening, so it is not listed here.
const NAMED_DAYS = [
  [29, "Deci"], [30, "Masiso - one month"], [59, "Deci"], [60, "Bamsi - two months"],
  [179, "Deci"], [180, "Chamsi - six months"], [359, "Deci"], [360, "Varsi - one year"],
];

const MAX = { months: 120, years: 50, parabYears: 25 };

function blankDraft(cid) {
  return {
    cid, name: "", death: "", opening: null, days: [],
    monthly: false, months: "", yearly: false, years: "",
    parab: false, parabWhich: null, parabYears: "",
    services: [],
  };
}

export async function renderMemorialNew({ id }) {
  chrome(true);
  refreshHeader();
  showFab(false);
  loading();
  const alive = navGuard();

  const aid = state.currentAgyaryId;
  const cid = Number(id);
  let behdin, services;
  try {
    [behdin, services] = await Promise.all([getBehdin(aid, cid), prayerServices(aid)]);
  } catch (e) {
    if (!alive()) return;
    mainEl.innerHTML = "";
    return showError(e.status === 404 ? "That behdin isn't on file at this fire temple." : e.message);
  }
  if (!alive()) return;

  const draft = blankDraft(cid);
  const serviceName = (sid) => (services.find(s => s.id === sid) || {}).name || "";

  /** The request body, or an error message if something is missing. Every
   *  check here is also made by the server; this is for a clear message
   *  before the round trip. */
  function build() {
    if (!draft.name.trim()) return { error: "Please enter the departed person's name." };
    if (!draft.death) return { error: "Please enter the date of death." };
    if (!draft.opening) return { error: "Choose how the opening is kept: days 1 to 10, or the 10th day only." };

    const count = (raw, label, unit, max) => {
      const n = Number(raw);
      if (!raw || !Number.isInteger(n) || n < 1) return { error: `Say how many ${unit} the ${label} should run for.` };
      if (n > max) return { error: `The ${label} can run for at most ${max} ${unit}.` };
      return { n };
    };
    const body = {
      departed_name: draft.name.trim(),
      death_date: draft.death,
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

  // --- Step 1: the form ---------------------------------------------------
  function showForm() {
    const has = (n) => draft.days.includes(n);
    mainEl.innerHTML = `
      <div class="card">
        ${backBar("New memorial")}
        <p class="meta">For the family of ${esc(behdin.name)}.</p>
        <label>Departed person</label>
        <input type="text" id="mmName" placeholder="e.g. Dinshaw Mistry" autocomplete="off"
               value="${esc(draft.name)}">
        <label>Date of death</label>
        <input type="date" id="mmDeath" max="${todayIst()}" value="${esc(draft.death)}">
        <p class="meta" id="mmParsi" style="margin:6px 0 0"></p>
      </div>

      <div class="card">
        <h2>Opening</h2>
        <p class="meta">The first days after the death. The day of death is day 1.</p>
        <div class="choice-group">
          <div class="check-row"><input type="radio" name="mmOpening" id="mmOpenAll" value="days_1_to_10"
            ${draft.opening === "days_1_to_10" ? "checked" : ""}><label for="mmOpenAll">Every day, days 1 to 10</label></div>
          <div class="check-row"><input type="radio" name="mmOpening" id="mmOpenTenth" value="tenth_only"
            ${draft.opening === "tenth_only" ? "checked" : ""}><label for="mmOpenTenth">The 10th day only</label></div>
        </div>
      </div>

      <div class="card">
        <h2>Other days</h2>
        <p class="meta">Masiso, Bamsi, Chamsi and Varsi fall on the same Roj, that many months on. A Deci is the day before. If you also choose monthly or yearly below, each date is listed once.</p>
        <div class="choice-group">${NAMED_DAYS.map(([n, name]) => `
          <div class="check-row"><input type="checkbox" data-day="${n}" id="mmDay${n}" ${has(n) ? "checked" : ""}>
            <label for="mmDay${n}">${n}th day · ${name}</label></div>`).join("")}
        </div>
      </div>

      <div class="card">
        <h2>Repeating</h2>
        <p class="meta">Each one needs a length - choose how long it should run.</p>
        <div class="choice-group">
          <div class="check-row"><input type="checkbox" id="mmMonthly" ${draft.monthly ? "checked" : ""}>
            <label for="mmMonthly">Every month, on the same Roj</label></div>
          <div class="sub-field" id="mmMonthlyBox" style="${draft.monthly ? "" : "display:none"}">
            <label>For how many months</label>
            <input type="number" inputmode="numeric" min="1" max="${MAX.months}" id="mmMonths" value="${esc(draft.months)}"></div>

          <div class="check-row"><input type="checkbox" id="mmYearly" ${draft.yearly ? "checked" : ""}>
            <label for="mmYearly">Every year, on the same Roj and Mah</label></div>
          <div class="sub-field" id="mmYearlyBox" style="${draft.yearly ? "" : "display:none"}">
            <label>For how many years</label>
            <input type="number" inputmode="numeric" min="1" max="${MAX.years}" id="mmYears" value="${esc(draft.years)}"></div>

          <div class="check-row"><input type="checkbox" id="mmParab" ${draft.parab ? "checked" : ""}>
            <label for="mmParab">Parabs</label></div>
          <div class="sub-field" id="mmParabBox" style="${draft.parab ? "" : "display:none"}">
            <div class="check-row"><input type="radio" name="mmParabWhich" id="mmParabFT" value="fravardin_tir"
              ${draft.parabWhich === "fravardin_tir" ? "checked" : ""}><label for="mmParabFT">Fravardin and Tir only</label></div>
            <div class="check-row"><input type="radio" name="mmParabWhich" id="mmParabAll" value="all"
              ${draft.parabWhich === "all" ? "checked" : ""}><label for="mmParabAll">All Parabs</label></div>
            <p class="meta" style="margin:0">Each Parab comes round once a year.</p>
            <label>For how many years</label>
            <input type="number" inputmode="numeric" min="1" max="${MAX.parabYears}" id="mmParabYears" value="${esc(draft.parabYears)}"></div>
        </div>
      </div>

      <div class="card">
        <h2>Services</h2>
        <p class="meta">Every observance starts with these. You can change any one of them later.</p>
        <div class="chip-row" id="mmServices">${services.map(s => `
          <label class="chip ${draft.services.includes(s.id) ? "on" : ""}" style="margin:0">
            <input type="checkbox" data-svc="${s.id}" ${draft.services.includes(s.id) ? "checked" : ""}>${esc(s.name)}</label>`).join("")}
        </div>
      </div>

      <div class="wizard-nav" style="margin-top:4px">
        <button class="ghost" id="mmCancel">Cancel</button>
        <button id="mmReview">Review schedule</button>
      </div>`;

    const $ = (sel) => mainEl.querySelector(sel);

    const readParsi = async () => {
      const note = $("#mmParsi");
      if (!draft.death) { note.textContent = ""; return; }
      const label = await parsiLabel(draft.death, primarySystem());
      if (!note.isConnected) return;
      note.textContent = label;
    };
    readParsi();

    $("#mmName").oninput = (e) => { draft.name = e.target.value; };
    $("#mmDeath").onchange = (e) => { draft.death = e.target.value; readParsi(); };
    mainEl.querySelectorAll("[name=mmOpening]").forEach(r => {
      r.onchange = () => { draft.opening = r.value; };
    });
    mainEl.querySelectorAll("[data-day]").forEach(cb => {
      cb.onchange = () => {
        const n = Number(cb.dataset.day);
        draft.days = cb.checked ? [...new Set([...draft.days, n])] : draft.days.filter(d => d !== n);
      };
    });

    // A series' length only appears once the series is ticked, and unticking
    // it forgets the length - nothing carries over by accident.
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
    mainEl.querySelectorAll("[name=mmParabWhich]").forEach(r => {
      r.onchange = () => { draft.parabWhich = r.value; };
    });

    mainEl.querySelectorAll("[data-svc]").forEach(cb => {
      cb.onchange = () => {
        const n = Number(cb.dataset.svc);
        cb.closest(".chip").classList.toggle("on", cb.checked);
        draft.services = cb.checked ? [...new Set([...draft.services, n])] : draft.services.filter(s => s !== n);
      };
    });

    $("#mmCancel").onclick = () => back(`#/behdins/${cid}`);
    $("#mmReview").onclick = async () => {
      const built = build();
      if (built.error) return showError(built.error);
      const btn = $("#mmReview");
      btn.disabled = true;
      try {
        const preview = await previewMemorial(aid, cid, built.body);
        showPreview(built.body, preview);
      } catch (e) {
        btn.disabled = false;
        showError(e.message);
      }
    };
  }

  // --- Step 2: every date, before anything is saved ------------------------
  function showPreview(body, preview) {
    const today = todayIst();
    const names = body.service_ids.map(serviceName).filter(Boolean).join(", ");
    const passed = preview.observances.filter(o => o.date < today).length;

    mainEl.innerHTML = `
      <div class="card">
        ${backBar("Review the schedule")}
        <p class="meta" style="margin:4px 0 0">${esc(body.departed_name)} · died ${esc(gregLabel(body.death_date))}</p>
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
      </div>

      <div class="wizard-nav" style="margin-top:4px">
        <button class="ghost" id="mmEdit">Change</button>
        <button id="mmCreate">Create memorial</button>
      </div>`;

    document.getElementById("mmEdit").onclick = () => showForm();
    document.getElementById("mmCreate").onclick = async () => {
      const btn = document.getElementById("mmCreate");
      btn.disabled = true;
      try {
        const made = await createMemorial(aid, cid, body);
        // The form is finished; the memorial takes its place in history.
        navigate(`#/memorial/${made.id}`, { replace: true });
      } catch (e) {
        btn.disabled = false;
        showError(e.message);
      }
    };
  }

  showForm();
}
