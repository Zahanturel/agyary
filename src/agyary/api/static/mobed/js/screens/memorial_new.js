"use strict";

/**
 * New memorial, for a behdin who is already on file: a family tells us when
 * someone died and which observances they keep, and we lay out the whole
 * schedule. (A new behdin gets the same form on the New behdin page - see
 * behdins.js.)
 *
 * Two steps on one route. The form, then a preview of every date - nothing is
 * saved until the mobed has seen the dates and confirms them. The form itself
 * is in memorial_form.js.
 */

import { getBehdin, previewMemorial, createMemorial } from "../api.js";
import { state } from "../state.js";
import {
  chrome, mainEl, showFab, showError, refreshHeader, loading, backBar,
} from "../ui.js";
import { esc } from "../util.js";
import { navigate, back, navGuard } from "../router.js";
import { prayerServices } from "./memorial.js";
import {
  blankMemorialDraft, buildMemorialBody, memorialFormHtml, wireMemorialForm, schedulePreviewHtml,
  wireSchedulePreview, showMemorialProblems, newReview, reviewPayload, reviewHasEmptyDate,
} from "../memorial_form.js";
import { loadDraft, saveDraft, clearDraft, offerDraft } from "../drafts.js";

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

  // What was typed stays until the memorial is saved or cancelled; coming back
  // asks whether to continue it or start a new one.
  const draftKey = `memorial:${aid}:${cid}`;
  let draft = blankMemorialDraft();
  const keep = () => saveDraft(draftKey, draft);
  // Dates taken out on the review screen; kept while the form is changed and
  // reviewed again, dropped with the draft.
  let review = newReview();

  // One question at a time: who, when they passed away, which prayers - then the
  // check of every date (the fourth step).
  const QUESTIONS = ["Who are we remembering?", "When did they pass away?", "Which prayers?"];
  const stepOfTarget = (t) => (t === "#mmName" ? 1 : /^#mmDeath/.test(t) ? 2 : 3);
  let step = 1;

  function showForm() {
    mainEl.innerHTML = `
      <div class="step-head">
        <div class="step-count">Step ${step} of 4</div>
        <div class="step-bar">${[1, 2, 3, 4].map(n => `<i class="${n <= step ? "on" : ""}"></i>`).join("")}</div>
        <h2 class="step-q">${esc(QUESTIONS[step - 1])}</h2>
      </div>
      ${memorialFormHtml(draft, services, {
        heading: "",
        intro: step === 1 ? `For the family of ${esc(behdin.name)}.` : "",
      })}
      <div class="wizard-nav" style="margin-top:4px">
        <button class="secondary" id="mmCancel">${step === 1 ? "Cancel" : "Back"}</button>
        <button id="mmReview">${step === 3 ? "Check the dates" : "Next"}</button>
      </div>`;
    wireMemorialForm(mainEl, draft, keep);
    mainEl.querySelectorAll(".mstep").forEach(el => el.classList.toggle("hidden", Number(el.dataset.mstep) !== step));
    // The first card holds steps 1 and 2; on step 3 only the prayers card shows.
    mainEl.querySelector(".card").classList.toggle("hidden", step === 3);
    window.scrollTo(0, 0);

    document.getElementById("mmCancel").onclick = () => {
      if (step > 1) { step -= 1; return showForm(); }
      clearDraft(draftKey);
      back(`#/behdins/${cid}`);
    };
    document.getElementById("mmReview").onclick = async () => {
      const built = buildMemorialBody(draft);
      // Only what this step asks; the rest is checked when the last one is done.
      const mine = built.problems ? built.problems.filter(p => stepOfTarget(p.target) === step) : [];
      if (mine.length) return void showMemorialProblems(mainEl, { problems: mine, error: mine[0].message });
      if (step < 3) { step += 1; return showForm(); }
      if (built.problems) {   // something on an earlier step: go back to it
        step = Math.min(...built.problems.map(p => stepOfTarget(p.target)));
        showForm();
        return void showMemorialProblems(mainEl, { problems: built.problems.filter(p => stepOfTarget(p.target) === step), error: built.error });
      }
      const btn = document.getElementById("mmReview");
      btn.disabled = true;
      try {
        review = newReview();   // a changed form is a new schedule
        showPreview(built.body, await previewMemorial(aid, cid, built.body));
      } catch (e) {
        btn.disabled = false;
        showError(e.message);
      }
    };
  }

  function showPreview(body, preview) {
    mainEl.innerHTML = `
      ${schedulePreviewHtml(body, preview, services, { heading: backBar("Review the schedule"), review })}
      <div class="wizard-nav" style="margin-top:4px">
        <button class="ghost" id="mmEdit">Change</button>
        <button id="mmCreate">Create memorial</button>
      </div>`;
    wireSchedulePreview(mainEl, preview, review, services);
    document.getElementById("mmEdit").onclick = () => { step = 3; showForm(); };
    document.getElementById("mmCreate").onclick = async () => {
      if (reviewHasEmptyDate(mainEl, review)) return;
      const btn = document.getElementById("mmCreate");
      btn.disabled = true;
      try {
        const made = await createMemorial(aid, cid, { ...body, ...reviewPayload(body, preview, services, review) });
        clearDraft(draftKey);
        // The form is finished; the memorial takes its place in history.
        navigate(`#/memorial/${made.id}`, { replace: true });
      } catch (e) {
        btn.disabled = false;
        showError(e.message);
      }
    };
  }

  const stored = loadDraft(draftKey);
  if (!stored) return showForm();
  offerDraft({
    title: "Unfinished memorial",
    summary: [behdin.name, stored.name ? `For ${stored.name}` : "The person they lost is not named yet",
      stored.longAgo ? "Passed away more than a year ago" : stored.death ? `Died ${stored.death}` : "No date given yet"],
    onStartNew: () => { clearDraft(draftKey); draft = blankMemorialDraft(); showForm(); },
    onContinue: () => { draft = { ...blankMemorialDraft(), ...stored }; showForm(); },
  });
}
