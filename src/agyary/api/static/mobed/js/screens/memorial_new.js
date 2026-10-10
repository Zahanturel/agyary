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
} from "../memorial_form.js";

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

  const draft = blankMemorialDraft();

  function showForm() {
    mainEl.innerHTML = `
      ${memorialFormHtml(draft, services, {
        heading: backBar("New memorial"),
        intro: `For the family of ${esc(behdin.name)}.`,
      })}
      <div class="wizard-nav" style="margin-top:4px">
        <button class="ghost" id="mmCancel">Cancel</button>
        <button id="mmReview">Review schedule</button>
      </div>`;
    wireMemorialForm(mainEl, draft);

    document.getElementById("mmCancel").onclick = () => back(`#/behdins/${cid}`);
    document.getElementById("mmReview").onclick = async () => {
      const built = buildMemorialBody(draft);
      if (built.error) return showError(built.error);
      const btn = document.getElementById("mmReview");
      btn.disabled = true;
      try {
        showPreview(built.body, await previewMemorial(aid, cid, built.body));
      } catch (e) {
        btn.disabled = false;
        showError(e.message);
      }
    };
  }

  function showPreview(body, preview) {
    mainEl.innerHTML = `
      ${schedulePreviewHtml(body, preview, services, { heading: backBar("Review the schedule") })}
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
