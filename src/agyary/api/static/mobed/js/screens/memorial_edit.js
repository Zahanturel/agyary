"use strict";

/**
 * Edit a saved memorial: the name, the death (date, or Roj and Mah), the
 * calendar, what is kept and for how long - the same four steps as a new one,
 * filled in with what was saved.
 *
 * Nothing is saved until the mobed has seen what the change does to each date.
 * Every date is counted again from the death, past ones included (the owner's
 * call, 17 Nov 2026), and a date that is still there keeps its prayers, time,
 * note and paid mark, so the review says which dates move, which are new and
 * which come off. Dates removed one at a time stay out, and can be put back
 * here. A date moved by hand stays where it was put.
 */

import { memorialEditForm, previewMemorialEdit, saveMemorialEdit } from "../api.js";
import { state } from "../state.js";
import {
  chrome, mainEl, showFab, showError, flashInfo, refreshHeader, loading, backBar, screenFailed,
} from "../ui.js";
import { esc, gregLabel, todayIst } from "../util.js";
import { returnTo, navGuard } from "../router.js";
import { prayerServices, parsiText } from "./memorial.js";
import {
  blankMemorialDraft, buildMemorialBody, memorialFormHtml, wireMemorialForm, schedulePreviewHtml,
  wireSchedulePreview, showMemorialProblems, newReview, reviewPayload, reviewHasEmptyDate,
} from "../memorial_form.js";

/** The saved memorial as the form's draft. */
function draftFrom(form) {
  const s = (n) => (n == null ? "" : String(n));
  const days = [...form.day_counts];
  // "10th only", from before the Dasmi was a named day, is the Dasmi.
  if (form.opening === "tenth_only" && !days.includes(10)) days.push(10);
  return {
    ...blankMemorialDraft(),
    name: form.departed_name,
    longAgo: form.long_ago,
    death: form.death_date || "",
    deathBy: "date",
    deathRoj: form.long_ago ? s(form.death.roj) : "",
    deathMah: form.long_ago ? s(form.death.mah) : "",
    calendar: form.calendar,
    startFrom: form.start_from && !form.long_ago ? "today" : "death",
    startDate: form.start_from || todayIst(),
    oneToTen: form.opening === "days_1_to_10",
    fiveToNine: form.opening === "days_5_to_9",
    days,
    monthly: !!form.monthly_months, months: s(form.monthly_months),
    yearly: !!form.yearly_years, years: s(form.yearly_years),
    fravRoj: !!form.fravardin_roj_months, fravRojMonths: s(form.fravardin_roj_months),
    parab: !!form.parabs, parabWhich: form.parabs, parabCount: s(form.parab_count),
    birthday: !!form.birthday,
    birthRoj: form.birthday ? s(form.birthday.roj) : "",
    birthMah: form.birthday ? s(form.birthday.mah) : "",
    birthYears: form.birthday ? s(form.birthday.years) : "",
    services: [...form.service_ids],
  };
}

export async function renderMemorialEdit({ id }) {
  chrome(true);
  refreshHeader();
  showFab(false);
  loading();
  const alive = navGuard();

  const aid = state.currentAgyaryId;
  const mid = Number(id);
  const home = `#/memorial/${mid}`;
  let form, services;
  try {
    [form, services] = await Promise.all([memorialEditForm(aid, mid), prayerServices(aid)]);
  } catch (e) {
    if (!alive()) return;
    if (e.status === 404) return screenFailed("That memorial isn't on file.");
    return screenFailed("Couldn't open this memorial: " + e.message, () => renderMemorialEdit({ id }));
  }
  if (!alive()) return;

  const editing = { oneToTen: form.opening === "days_1_to_10" };
  const draft = draftFrom(form);
  // The review's own state: dates taken out and prayers changed on it, and
  // dates taken out earlier that are put back.
  let review = Object.assign(newReview(), { restored: new Set() });

  const QUESTIONS = ["Who are we remembering?", "When did they pass away?", "Which prayers?"];
  const stepOfTarget = (t) => (t === "#mmName" ? 1 : /^#mmDeath/.test(t) ? 2 : 3);
  let step = 1;

  function showForm() {
    mainEl.innerHTML = `
      <div class="step-head">
        <div class="step-count">Edit memorial · Step ${step} of 4</div>
        <div class="step-bar">${[1, 2, 3, 4].map(n => `<i class="${n <= step ? "on" : ""}"></i>`).join("")}</div>
        <h2 class="step-q">${esc(QUESTIONS[step - 1])}</h2>
      </div>
      ${memorialFormHtml(draft, services, {
        heading: "",
        intro: step === 1 ? "Change what you need; the next steps show what was saved." : "",
        editing,
      })}
      <div class="wizard-nav" style="margin-top:4px">
        <button class="secondary" id="mmCancel">${step === 1 ? "Cancel" : "Back"}</button>
        <button id="mmReview">${step === 3 ? "Check the changes" : "Next"}</button>
      </div>`;
    wireMemorialForm(mainEl, draft, null, { editing });
    mainEl.querySelectorAll(".mstep").forEach(el => el.classList.toggle("hidden", Number(el.dataset.mstep) !== step));
    mainEl.querySelector(".card").classList.toggle("hidden", step === 3);
    window.scrollTo(0, 0);

    document.getElementById("mmCancel").onclick = () => {
      if (step > 1) { step -= 1; return showForm(); }
      returnTo(home);
    };
    document.getElementById("mmReview").onclick = async () => {
      const built = buildMemorialBody(draft);
      const mine = built.problems ? built.problems.filter(p => stepOfTarget(p.target) === step) : [];
      if (mine.length) return void showMemorialProblems(mainEl, { problems: mine, error: mine[0].message });
      if (step < 3) { step += 1; return showForm(); }
      if (built.problems) {
        step = Math.min(...built.problems.map(p => stepOfTarget(p.target)));
        showForm();
        return void showMemorialProblems(mainEl, { problems: built.problems.filter(p => stepOfTarget(p.target) === step), error: built.error });
      }
      const btn = document.getElementById("mmReview");
      btn.disabled = true;
      try {
        const preview = await previewMemorialEdit(aid, mid, built.body);
        if (!alive()) return;
        review = Object.assign(newReview(), { restored: new Set() });   // a changed form is a new schedule
        showPreview(built.body, preview);
      } catch (e) {
        btn.disabled = false;
        showError(e.message);
      }
    };
  }

  function showPreview(body, preview) {
    // Dates taken out earlier and put back here join the list as new ones.
    const back = preview.left_out.filter(o => review.restored.has(o.code))
      .map(o => ({ ...o, status: "new", service_ids: null }));
    const shown = {
      ...preview,
      observances: [...preview.observances, ...back].sort((a, b) => a.date.localeCompare(b.date)),
    };
    const stillOut = preview.left_out.filter(o => !review.restored.has(o.code));
    const where = (o) => parsiText(o);   // a Gatha day comes with its gatha_index

    mainEl.innerHTML = `
      ${schedulePreviewHtml(body, shown, services, { heading: backBar("Check the changes"), review, editing: true })}
      ${preview.dropped.length ? `<div class="card">
        <h2>Coming off</h2>
        <p class="meta" style="margin:4px 0 8px">${preview.dropped.length === 1 ? "This date is" : "These dates are"}
          no longer in what you chose, so ${preview.dropped.length === 1 ? "it comes" : "they come"} off the memorial
          when you save.</p>
        ${preview.dropped.map(o => `<div class="obs past">
          <div class="obs-head"><div class="obs-title"><b>${esc(o.label)}</b>
            <span>${esc(where(o))}${o.paid ? " · paid" : ""}${o.notes ? " · has a note" : ""}</span></div>
            <div class="obs-when">${esc(gregLabel(o.date))}</div></div></div>`).join("")}
      </div>` : ""}
      ${stillOut.length ? `<div class="card">
        <h2>Removed earlier</h2>
        <p class="meta" style="margin:4px 0 8px">You took ${stillOut.length === 1 ? "this date" : "these dates"} off
          before, so ${stillOut.length === 1 ? "it stays" : "they stay"} off. Put one back to keep it again.</p>
        ${stillOut.map(o => `<div class="obs">
          <div class="obs-head"><div class="obs-title"><b>${esc(o.label)}</b><span>${esc(where(o))}</span></div>
            <div class="obs-when">${esc(gregLabel(o.date))}</div>
            <button type="button" class="ghost small" data-put-back="${esc(o.code)}">Put back</button></div></div>`).join("")}
      </div>` : ""}
      <div class="wizard-nav" style="margin-top:4px">
        <button class="ghost" id="mmEdit">Change</button>
        <button id="mmSave">Save changes</button>
      </div>`;
    wireSchedulePreview(mainEl, shown, review, services);
    window.scrollTo(0, 0);

    mainEl.querySelectorAll("[data-put-back]").forEach(btn => {
      btn.onclick = () => {
        review.restored.add(btn.dataset.putBack);
        review.removed.delete(btn.dataset.putBack);
        showPreview(body, preview);
      };
    });
    document.getElementById("mmEdit").onclick = () => { step = 3; showForm(); };
    document.getElementById("mmSave").onclick = async () => {
      if (reviewHasEmptyDate(mainEl, review)) return;
      const btn = document.getElementById("mmSave");
      btn.disabled = true;
      try {
        await saveMemorialEdit(aid, mid, {
          ...body,
          ...reviewPayload(body, shown, services, review),
          restore_codes: [...review.restored],
        });
      } catch (e) {
        btn.disabled = false;
        return showError(e.message);
      }
      flashInfo("Memorial saved.");
      returnTo(home);
    };
  }

  showForm();
}
