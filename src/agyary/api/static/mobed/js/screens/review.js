"use strict";

/**
 * Review before saving - the step between the form and the event existing.
 *
 * The form collects who, what and when; this shows the slip exactly as it will
 * print, with the names beneath it to correct or reorder, and only "Confirm &
 * save" creates anything. It used to be the other way round: the event was
 * saved and the mobed saw the names for the first time on the finished slip.
 *
 * Shared by both apps and by new and edited events. The slip shown is the
 * server's own rendering (POST slip-preview), the same code that prints it, so
 * "what you checked" cannot differ from "what you got". Nothing is written
 * until Confirm, so leaving this screen at any point loses nothing but the
 * draft.
 *
 * There is deliberately no saved "draft" status behind this: the draft lives
 * in state.draft, and the event does not exist until it is confirmed.
 */

import {
  previewBooking, previewMachi, addBooking, editBooking, addMachi, editMachi,
} from "../api.js";
import { state, GEH_NAME_BY_NUM } from "../state.js";
import { clearDraft } from "../drafts.js";
import { repeatFields, repeatSentence } from "../repeat.js";
import { renderNamesEditor, collectNames, validateNames, halfFilledPair } from "../names.js";
import { slipCardHtml } from "./slip.js";
import { chrome, mainEl, showFab, showError, flashInfo, refreshHeader, loading, screenFailed } from "../ui.js";
import { flagProblems, clearProblems } from "../fielderrors.js";
import { esc, gregLabel } from "../util.js";
import { navigate, returnTo, navGuard } from "../router.js";

const FORM = { booking: "#/event/new", machi: "#/machi/new" };

/** The request body for the draft, with `names` when the mobed has them. */
function bodyFor(draft, names) {
  const base = { behdin_phone: draft.behdin.phone, behdin_name: draft.behdin.name };
  if (draft.kind === "machi") {
    return {
      ...base, roj: draft.roj, mah: draft.mah, year: draft.year, geh: draft.geh,
      gregorian: draft.gregorian, purpose: draft.purpose, names,
    };
  }
  return {
    ...base, service_id: draft.service_id,
    ceremony_datetime: `${draft.gregorian}T${draft.time}:00`, names,
  };
}

/** The form this review step follows - where "Edit details" and the header
 *  Back return to. A machi's edit screen is its own route in both apps. */
export function formFor(kind) {
  const draft = state.draft;
  if (draft && draft.edit) {
    return kind === "machi" ? `#/machi/${draft.edit.id}/edit` : `#/event/booking/${draft.edit.id}/edit`;
  }
  return FORM[kind];
}

/** Which editor shape the names take. Tandarosti is a list of living names;
 *  everything else - including Patet - is pairs plus farmayeshne. Patet used to
 *  get a single fixed pair here, but saving attached the behdin's WHOLE saved
 *  set to a patet machi, so the editor showed one pair while the slip printed
 *  several. The review step shows, and lets the mobed order, exactly what
 *  will be saved. */
function editorShape(draft) {
  const singlesOnly = draft.kind === "machi" && draft.purpose === "tandarosti";
  return { isMachi: singlesOnly, purpose: singlesOnly ? "tandarosti" : "gujrela_nu" };
}

export function renderReview(kind) {
  return async function show() {
    chrome(true);
    refreshHeader();
    showFab(false);
    loading();
    const alive = navGuard();

    const draft = state.draft;
    // A reload drops the in-memory draft; there is nothing to review, so send
    // them back to an empty form rather than to a blank page.
    if (!draft || draft.kind !== kind || !draft.behdin) {
      return navigate(FORM[kind], { replace: true });
    }
    const aid = state.currentAgyaryId;
    const isMachi = kind === "machi";
    const preview = (names) => (isMachi ? previewMachi : previewBooking)(aid, {
      ...bodyFor(draft, names),
      ...(isMachi && draft.edit ? { editing_machi_id: draft.edit.id } : {}),
      // So the server can say now which dates of the series are already taken.
      ...(!draft.edit ? repeatFields(draft) : {}),
    });

    // Whichever way the mobed leaves this step for the form (Edit details, or
    // the header Back), the form keeps this draft instead of reloading it. Set
    // before the slip is asked for, so Back from a slip that could not be
    // prepared keeps an edit's changes too.
    draft.returning = true;

    let first;
    try {
      first = await preview(draft.names || null);
    } catch (e) {
      if (!alive()) return;
      // In the page, with a way to try again - it used to be a blank page
      // under a passing message.
      return screenFailed("Couldn't prepare the slip: " + e.message, e.status === 404 ? null : show);
    }
    if (!alive()) return;
    draft.names = first.names;

    mainEl.innerHTML = `
      <div class="step-head no-print">
        <h2 class="step-q">Check and save</h2>
        <p class="meta">This is what will print. Correct the names below if anything is wrong,
          then save.</p>
      </div>
      <div id="rvWarn"></div>
      <div id="rvSeries"></div>
      <div id="rvSlip">${slipCardHtml(first.slip)}</div>
      <div class="card no-print">
        <h2>Names</h2>
        <p class="meta">Add, remove or reorder for this ${isMachi ? "machi" : "event"}.
          Drag a pair, or use the arrows, to put it first.</p>
        <div id="rvNames"></div>
        <div id="rvHint" class="meta" style="margin-top:8px"></div>
        <div class="check-row" style="margin-top:12px">
          <input type="checkbox" id="rvKeep" checked>
          <label for="rvKeep">Remember any new names for ${esc(draft.behdin.name)}</label>
        </div>
        <p class="meta" style="margin-top:4px">Adds to their saved names, so next time they are
          already here. Nothing already saved is removed.</p>
      </div>
      <div class="wizard-nav no-print" style="margin-top:4px">
        <button class="secondary" id="rvEdit">Change details</button>
        <button class="ok" id="rvConfirm">${draft.edit ? "Save changes" : "Save"}</button>
      </div>`;

    const region = document.getElementById("rvNames");
    const slipBox = document.getElementById("rvSlip");
    const warn = document.getElementById("rvWarn");
    const hint = document.getElementById("rvHint");
    const confirmBtn = document.getElementById("rvConfirm");
    const shape = editorShape(draft);
    const editorNames = () => collectNames(region, shape.isMachi, shape.purpose);
    renderNamesEditor(region, shape.isMachi, shape.purpose, draft.names);

    const showSlot = (available, alternatives) => {
      if (isMachi && !available) {
        const other = alternatives && alternatives.same_day_gehs && alternatives.same_day_gehs.length
          ? ` Free that day: ${alternatives.same_day_gehs.map(g => GEH_NAME_BY_NUM[g] || g).join(", ")}.` : "";
        warn.innerHTML = `<div class="error-banner">That geh is already booked.${esc(other)}
          Go back and choose another.</div>`;
        confirmBtn.disabled = true;
      } else {
        warn.innerHTML = "";
        confirmBtn.disabled = false;
      }
    };
    showSlot(first.slot_available !== false);

    // A repeating series runs into somebody else's booking only for those dates;
    // the rest still book. Say which, before the mobed confirms.
    if (draft.recurring && !draft.edit) {
      document.getElementById("rvSeries").innerHTML = `<div class="info-banner">
        ${repeatSentence(draft)} The next ones are added to the calendar for you.</div>`;
    }
    const clashes = first.series_conflicts || [];
    if (clashes.length) {
      document.getElementById("rvSeries").innerHTML += `<div class="info-banner">
        The geh is already booked on ${clashes.length === 1 ? "this date" : "these dates"} in the repeat,
        so ${clashes.length === 1 ? "it" : "they"} will be left out:
        ${clashes.map(d => esc(gregLabel(d))).join("; ")}.</div>`;
    }

    // Redraw the slip as the names change. Only a valid set is sent - a
    // half-filled pair would be refused - and the hint says why nothing moved.
    let timer = null, token = 0;
    const refresh = () => {
      clearTimeout(timer);
      timer = setTimeout(async () => {
        const rows = editorNames();
        const problem = validateNames(rows);
        hint.textContent = problem || "";
        if (problem) return;
        draft.names = rows;
        const mine = ++token;
        try {
          const res = await preview(rows);
          if (mine !== token || !alive()) return;
          slipBox.innerHTML = slipCardHtml(res.slip);
        } catch (e) {
          if (mine !== token || !alive()) return;
          // The last good slip stays on screen, but it no longer shows the
          // names as they now are - so say so, here under the names, rather
          // than leave "this is what will print" standing over an old slip.
          hint.textContent = "Couldn't redraw the slip above - please check your signal. Your names are kept.";
        }
      }, 350);
    };
    region.addEventListener("input", refresh);
    region.addEventListener("names-changed", refresh);
    // A marked pair that is then moved or removed would leave its message
    // behind where the pair used to be, so the mark comes off. If the pair is
    // still half filled the hint under the names goes on saying so (refresh).
    region.addEventListener("names-changed", () => clearProblems(region.parentElement));

    const editBtn = document.getElementById("rvEdit");
    editBtn.onclick = () => {
      draft.names = editorNames();
      draft.returning = true;   // tells the edit form to keep this draft, not reload it
      navigate(formFor(kind), { replace: true });
    };

    confirmBtn.onclick = async () => {
      const rows = editorNames();
      const problem = validateNames(rows);
      if (problem) {
        // Marked on the pair itself, with the cursor put in its empty box.
        // The grey hint under the names says the same words, so it steps aside.
        const half = halfFilledPair(region);
        clearTimeout(timer);   // a redraw still waiting would only write the hint back
        hint.textContent = "";
        flagProblems(mainEl, [{ target: half ? half.card : region, message: problem }]);
        if (half) half.empty.focus({ preventScroll: true });
        return;
      }
      draft.names = rows;

      confirmBtn.disabled = true;
      // Leaving for the form while the save is on its way would end with the
      // event saved behind a form that still looks unsaved.
      editBtn.disabled = true;
      let res, slipHash;
      try {
        const body = bodyFor(draft, rows);
        // Part of the save, not a request afterwards: see _remember on the server.
        const keep = document.getElementById("rvKeep");
        body.remember_names = !keep || keep.checked;
        if (isMachi) {
          if (!draft.edit) Object.assign(body, repeatFields(draft));
          res = draft.edit ? await editMachi(aid, draft.edit.id, body) : await addMachi(aid, body);
          if (res.confirmed === false) {
            // Somebody took the slot between the preview and now. The notice
            // is at the head of the page and Save is at its foot, so bring it
            // to where the mobed is looking - otherwise the tap seems to do
            // nothing. Save stays off (showSlot); the way back is open again.
            showSlot(false, res.alternatives);
            editBtn.disabled = false;
            warn.scrollIntoView({ block: "center" });
            return;
          }
          slipHash = `#/machi/${aid}/${draft.edit ? draft.edit.id : res.machi_id}`;
        } else {
          if (!draft.edit) Object.assign(body, repeatFields(draft));
          res = draft.edit ? await editBooking(aid, draft.edit.id, body) : await addBooking(aid, body);
          slipHash = `#/booking/${aid}/${draft.edit ? draft.edit.id : res.booking_id}`;
        }
      } catch (e) {
        confirmBtn.disabled = false;
        editBtn.disabled = false;
        return showError(e.message);
      }

      // Saved. What follows is only the way to the slip, and is kept out of
      // the try above on purpose: a hitch here must never hand Save back, or
      // a second tap would book the same event twice.
      state.calendar.focus = draft.gregorian;
      state.draft = null;
      if (!draft.edit) clearDraft(isMachi ? "machi" : "event");   // saved: nothing left to continue
      // Neither the form nor this review may stay behind the slip in
      // history. An edit pops back to the slip it was opened from.
      if (draft.edit) return returnTo(slipHash);
      // A new event: put the calendar on the day it was booked for, THEN open
      // the slip on top. Back from the slip must show the event just made -
      // it used to return to whichever calendar day the mobed happened to be
      // on (or had left in the address from a previous visit), so a saved
      // event looked as though it had not been.
      await navigate(`#/${isMachi ? "board" : "calendar"}/day/${draft.gregorian}`, { replace: true });
      // Said on the slip, where the mobed lands - not on the calendar they pass through.
      const skipped = (res.skipped || []).map(x => gregLabel(x.gregorian));
      if (skipped.length) {
        flashInfo(`Booked. The geh was already taken on ${skipped.join("; ")}, so ${skipped.length === 1 ? "that date was" : "those dates were"} left out of the repeat.`);
      }
      navigate(slipHash);
    };
  };
}
