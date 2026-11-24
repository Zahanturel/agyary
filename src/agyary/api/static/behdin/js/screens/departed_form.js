"use strict";

/**
 * Add (or change) the prayers kept for someone who has passed away: who, when, and which days and
 * repeating prayers to keep. The dates are counted by the server; this only asks. The wording of the
 * choices follows the one the fire temples use.
 */

import { createMemorial, reworkMemorial, getMemorial, getPersonNames } from "../api.js";
import { chrome, mainEl, setHeader, loading, wireRetry, loadFailedHtml, showError } from "/mobed-app/js/ui.js";
import { navGuard, navigate } from "/mobed-app/js/router.js";
import { flagProblems } from "/mobed-app/js/fielderrors.js";
import { esc, todayIst, MAH_NAMES, ROJ_NAMES, GATHAS } from "../util.js";

// The named days, as the fire temples spell them. The 10th is the Dasmu; the Deci is the day before.
const NAMED_DAYS = [
  [10, "Dasmu"], [29, "Deci"], [30, "Masiso"], [60, "Bamsi"],
  [179, "Deci"], [180, "Chhamsi"], [359, "Deci"], [360, "Varsi"],
];
// What is ticked for a new one: the four days most families keep.
const DEFAULT_DAYS = [10, 30, 180, 360];
const MAX = { months: 1200, years: 100, parabs: 1200 };

function rojOptions(selected) {
  return `<option value="">Choose</option>`
    + ROJ_NAMES.map((n, i) => `<option value="${i + 1}" ${selected === String(i + 1) ? "selected" : ""}>${esc(n)}</option>`).join("")
    + `<optgroup label="Gatha days">${GATHAS.map((n, i) =>
      `<option value="g${i + 1}" ${selected === `g${i + 1}` ? "selected" : ""}>${esc(n)}</option>`).join("")}</optgroup>`;
}

/** What the form starts with, from a saved memorial being changed or from nothing. */
function startingValues(saved) {
  if (!saved) {
    return {
      name: "", longAgo: false, death: "", roj: "", mah: "",
      fiveToNine: false, days: DEFAULT_DAYS.slice(),
      monthly: false, months: 12, yearly: false, years: 25, parab: false, parabWhich: "all", parabCount: 24,
    };
  }
  const c = saved.choices;
  const gatha = saved.death_mah === 13;
  return {
    name: saved.name_known ? saved.departed_name : "",
    longAgo: saved.long_ago, death: saved.death_date || "",
    roj: saved.long_ago && saved.death_roj ? (gatha ? `g${saved.death_roj}` : String(saved.death_roj)) : "",
    mah: saved.long_ago && saved.death_mah && !gatha ? String(saved.death_mah) : "",
    fiveToNine: c.opening === "days_5_to_9", days: (c.day_counts || []).slice(),
    monthly: !!c.monthly, months: c.monthly ? c.monthly.count : 12,
    yearly: !!c.yearly, years: c.yearly ? c.yearly.count : 25,
    parab: !!c.parabs, parabWhich: c.parabs ? c.parabs.which : "all",
    parabCount: c.parabs ? (c.parabs.count || (c.parabs.years || 2) * 12) : 24,
  };
}

function formHtml(v, editing) {
  const radio = (name, id, value, checked, text) =>
    `<div class="check-row"><input type="radio" name="${name}" id="${id}" value="${value}" ${checked ? "checked" : ""}>
      <label for="${id}">${text}</label></div>`;
  const check = (id, on, text, extra = "") =>
    `<div class="check-row"><input type="checkbox" id="${id}" ${on ? "checked" : ""} ${extra}><label for="${id}">${text}</label></div>`;
  return `
    <div class="card" id="dpWho">
      <div id="dpSuggest"></div>
      <label for="dpName">Departed person</label>
      <input type="text" id="dpName" autocomplete="off" maxlength="120" value="${esc(v.name)}">

      <label>Did they pass away more than a year ago?</label>
      <div class="choice-group">
        ${radio("dpAgo", "dpAgoNo", "no", !v.longAgo, "No, within the last year")}
        ${radio("dpAgo", "dpAgoYes", "yes", v.longAgo, "Yes, more than a year ago")}
      </div>

      <div id="dpDateBox" style="${v.longAgo ? "display:none" : ""}">
        <label for="dpDeath">Date of death</label>
        <input type="date" id="dpDeath" max="${todayIst()}" value="${esc(v.death)}">
      </div>
      <div id="dpRojBox" style="${v.longAgo ? "" : "display:none"}">
        <label for="dpRoj">Roj</label>
        <select id="dpRoj">${rojOptions(v.roj)}</select>
        <div id="dpMahBox" style="${v.roj.startsWith("g") ? "display:none" : ""}">
          <label for="dpMah">Mah</label>
          <select id="dpMah"><option value="">Choose</option>${MAH_NAMES.map((n, i) =>
            `<option value="${i + 1}" ${v.mah === String(i + 1) ? "selected" : ""}>${esc(n)}</option>`).join("")}</select>
        </div>
      </div>
    </div>

    <div class="card" id="dpPrayers">
      <h2>Observances</h2>
      <div id="dpDaysBox" style="${v.longAgo ? "display:none" : ""}">
        <div class="names-group-label"><b>Named days</b></div>
        <div class="choice-group">
          ${check("dpFive", v.fiveToNine, "5th to 9th days")}
          ${NAMED_DAYS.map(([n, name]) => check(`dpDay${n}`, v.days.includes(n), `${n}th day · ${name}`, `data-day="${n}"`)).join("")}
        </div>
      </div>

      <div class="names-group-label"><b>Repeating</b></div>
      <div class="choice-group">
        ${check("dpMonthly", v.monthly, "Every month")}
        <div class="sub-field" id="dpMonthlyBox" style="${v.monthly ? "" : "display:none"}">
          <label for="dpMonths">For how many months (12 to a year)</label>
          <input type="number" inputmode="numeric" min="1" max="${MAX.months}" id="dpMonths" value="${esc(v.months)}"></div>

        ${check("dpYearly", v.yearly, "Every year")}
        <div class="sub-field" id="dpYearlyBox" style="${v.yearly ? "" : "display:none"}">
          <label for="dpYears">For how many years</label>
          <input type="number" inputmode="numeric" min="1" max="${MAX.years}" id="dpYears" value="${esc(v.years)}"></div>

        ${check("dpParab", v.parab, "Parabs")}
        <div class="sub-field" id="dpParabBox" style="${v.parab ? "" : "display:none"}">
          ${radio("dpParabWhich", "dpParabAll", "all", v.parabWhich === "all", "All Parabs")}
          ${radio("dpParabWhich", "dpParabFT", "fravardin_tir", v.parabWhich === "fravardin_tir", "Fravardin and Tir only")}
          <label for="dpParabCount">How many Parabs (a year has 12 of them, so 24 is two years)</label>
          <input type="number" inputmode="numeric" min="1" max="${MAX.parabs}" id="dpParabCount" value="${esc(v.parabCount)}"></div>
      </div>
    </div>

    <div class="row" style="margin-bottom:var(--space-4)">
      <button type="button" id="dpSave">${editing ? "Save changes" : "Save"}</button>
    </div>`;
}

/** Points at what is wrong, or returns the request body. */
function readForm(saved) {
  const val = (id) => document.getElementById(id).value;
  const on = (id) => document.getElementById(id).checked;
  const problems = [];
  const bad = (target, message) => problems.push({ target, message });

  const longAgo = document.querySelector('input[name="dpAgo"]:checked').value === "yes";
  const body = {
    departed_name: val("dpName").trim(),
    death_date: null, death_roj: null, death_mah: null, death_year: null,
    long_ago: longAgo, opening: "none", day_counts: [],
    monthly: null, yearly: null, parabs: null,
  };
  if (longAgo) {
    const roj = val("dpRoj");
    if (!roj) bad("#dpRoj", "Please choose the Roj of the passing.");
    else if (roj.startsWith("g")) { body.death_roj = Number(roj.slice(1)); body.death_mah = 13; }
    else {
      body.death_roj = Number(roj);
      if (!val("dpMah")) bad("#dpMah", "Please choose the Mah of the passing.");
      else body.death_mah = Number(val("dpMah"));
    }
  } else {
    if (!val("dpDeath")) bad("#dpDeath", "Please choose the date of passing.");
    body.death_date = val("dpDeath");
    if (on("dpFive")) body.opening = "days_5_to_9";
    body.day_counts = NAMED_DAYS.map(([n]) => n).filter((n) => on(`dpDay${n}`));
  }

  const count = (id, label, unit, max) => {
    const n = Number(val(id));
    if (!val(id) || !Number.isInteger(n) || n < 1) { bad(`#${id}`, `Please say how many ${unit} the ${label} should run for.`); return null; }
    if (n > max) { bad(`#${id}`, `The ${label} can run for at most ${max} ${unit}.`); return null; }
    return n;
  };
  if (on("dpMonthly")) { const n = count("dpMonths", "monthly prayers", "months", MAX.months); if (n) body.monthly = { count: n }; }
  if (on("dpYearly")) { const n = count("dpYears", "yearly prayers", "years", MAX.years); if (n) body.yearly = { count: n }; }
  if (on("dpParab")) {
    const n = count("dpParabCount", "Parabs", "Parabs", MAX.parabs);
    if (n) body.parabs = { which: document.querySelector('input[name="dpParabWhich"]:checked').value, count: n };
  }
  // Prayers kept from before that this form does not ask about stay as they were.
  if (saved && saved.choices.fravardin_roj) body.fravardin_roj = saved.choices.fravardin_roj;
  if (saved && saved.choices.birthday) body.birthday = saved.choices.birthday;

  const anything = body.day_counts.length || body.opening !== "none" || body.monthly || body.yearly || body.parabs
    || body.fravardin_roj || body.birthday;
  if (!anything && !problems.length) {
    bad("#dpPrayers h2", longAgo
      ? "Please choose what repeats: every month, every year or the Parabs."
      : "Please choose at least one day, or something that repeats.");
  }
  return problems.length ? { problems } : { body };
}

export async function renderDepartedForm(params) {
  chrome(true);
  const id = params && params.id ? Number(params.id) : null;
  setHeader(id ? "Change prayers" : "Prayers for the departed");
  loading();
  const alive = navGuard();

  let saved = null;
  if (id) {
    try {
      saved = await getMemorial(id);
    } catch (e) {
      if (!alive()) return;
      mainEl.innerHTML = e.status === 404
        ? `<div class="card"><p>That could not be found. It may have been deleted.</p></div>`
        : loadFailedHtml("these prayers");
      wireRetry(mainEl, () => renderDepartedForm(params));
      return;
    }
    if (!alive()) return;
  }

  mainEl.innerHTML = formHtml(startingValues(saved), !!saved);

  // Names already kept for this person's own departed: a tap fills the box.
  if (!saved) {
    getPersonNames().then((r) => {
      if (!alive()) return;
      const seen = new Set();
      const names = (r.names || []).filter((n) => {
        const key = (n.departed_name || "").trim().toLowerCase();
        if (!key || seen.has(key)) return false;
        seen.add(key);
        return true;
      }).slice(0, 8);
      const box = document.getElementById("dpSuggest");
      if (!names.length || !box) return;
      box.innerHTML = `<p class="meta" style="margin:0 0 var(--space-2)">Your saved names</p>
        <div class="chip-row">${names.map((n, i) =>
          `<button type="button" class="chip" data-fill="${i}">${esc(n.departed_name)}</button>`).join("")}</div>`;
      box.querySelectorAll("[data-fill]").forEach((b) => {
        b.onclick = () => { document.getElementById("dpName").value = names[Number(b.dataset.fill)].departed_name; };
      });
    }).catch(() => { /* names are only a help */ });
  }

  const show = (id, yes) => { document.getElementById(id).style.display = yes ? "" : "none"; };
  const toggles = [["dpMonthly", "dpMonthlyBox"], ["dpYearly", "dpYearlyBox"], ["dpParab", "dpParabBox"]];
  toggles.forEach(([box, sub]) => {
    document.getElementById(box).onchange = (e) => show(sub, e.target.checked);
  });
  document.querySelectorAll('input[name="dpAgo"]').forEach((r) => {
    r.onchange = () => {
      const yes = document.querySelector('input[name="dpAgo"]:checked').value === "yes";
      show("dpDateBox", !yes);
      show("dpRojBox", yes);
      show("dpDaysBox", !yes);
      // Only what repeats is left, so start it off on every year rather than on nothing.
      if (yes && !toggles.some(([box]) => document.getElementById(box).checked)) {
        document.getElementById("dpYearly").checked = true;
        show("dpYearlyBox", true);
      }
    };
  });
  document.getElementById("dpRoj").onchange = (e) => show("dpMahBox", !e.target.value.startsWith("g"));

  document.getElementById("dpSave").onclick = async (e) => {
    const built = readForm(saved);
    if (built.problems) return flagProblems(mainEl, built.problems);
    const btn = e.currentTarget;
    btn.disabled = true;   // one save per tap
    try {
      const made = saved ? await reworkMemorial(id, built.body) : await createMemorial(built.body);
      navigate(`#/departed/${made.id}`, { replace: true });
    } catch (err) {
      btn.disabled = false;
      showError(err.message);
    }
  };
}
