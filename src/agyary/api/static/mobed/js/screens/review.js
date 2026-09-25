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
  previewBooking, previewMachi, addBooking, editBooking, addMachi, editMachi, putSavedNames,
} from "../api.js";
import { state, GEH_NAME_BY_NUM } from "../state.js";
import { renderNamesEditor, collectNames, validateNames } from "../names.js";
import { slipCardHtml } from "./slip.js";
import { chrome, mainEl, showFab, showError, refreshHeader, loading } from "../ui.js";
import { esc } from "../util.js";
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
  return async function () {
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
    });

    let first;
    try {
      first = await preview(draft.names || null);
    } catch (e) {
      if (!alive()) return;
      mainEl.innerHTML = "";
      return showError("Couldn't prepare the slip: " + e.message);
    }
    if (!alive()) return;
    draft.names = first.names;

    mainEl.innerHTML = `
      <div class="card no-print">
        <h2>Check the slip</h2>
        <p class="meta">This is what will print. Correct the names below if anything is wrong,
          then save.</p>
      </div>
      <div id="rvWarn"></div>
      <div id="rvSlip">${slipCardHtml(first.slip)}</div>
      <div class="card no-print">
        <h2>Names</h2>
        <p class="meta">For this ${isMachi ? "machi" : "event"} only - the behdin's saved names
          are not changed. Drag a pair, or use the arrows, to put it first.</p>
        <div id="rvNames"></div>
        <div id="rvHint" class="meta" style="margin-top:8px"></div>
        ${first.pool_empty && draft.behdin.id ? `
          <div class="check-row" style="margin-top:12px">
            <input type="checkbox" id="rvKeep">
            <label for="rvKeep">Also keep these as ${esc(draft.behdin.name)}'s saved names</label>
          </div>` : ""}
      </div>
      <div class="wizard-nav no-print" style="margin-top:4px">
        <button class="ghost" id="rvEdit">Edit details</button>
        <button id="rvConfirm">${draft.edit ? "Confirm & save changes" : "Confirm & save"}</button>
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
        } catch (e) { /* keep the last good slip on screen */ }
      }, 350);
    };
    region.addEventListener("input", refresh);
    region.addEventListener("names-changed", refresh);

    document.getElementById("rvEdit").onclick = () => {
      draft.names = editorNames();
      navigate(formFor(kind), { replace: true });
    };

    confirmBtn.onclick = async () => {
      const rows = editorNames();
      const problem = validateNames(rows);
      if (problem) return showError(problem);
      draft.names = rows;

      confirmBtn.disabled = true;
      try {
        const body = bodyFor(draft, rows);
        let res, slipHash;
        if (isMachi) {
          if (draft.recurring && !draft.edit) body.recurring = draft.recurring;
          res = draft.edit ? await editMachi(aid, draft.edit.id, body) : await addMachi(aid, body);
          if (res.confirmed === false) {
            // Somebody took the slot between the preview and now.
            showSlot(false, res.alternatives);
            return;
          }
          slipHash = `#/machi/${aid}/${draft.edit ? draft.edit.id : res.machi_id}`;
        } else {
          res = draft.edit ? await editBooking(aid, draft.edit.id, body) : await addBooking(aid, body);
          slipHash = `#/booking/${aid}/${draft.edit ? draft.edit.id : res.booking_id}`;
        }

        // The event is saved; keeping the names for next time is a courtesy
        // that must not turn a saved event into an error.
        const keep = document.getElementById("rvKeep");
        if (keep && keep.checked && draft.behdin.id) {
          try {
            await putSavedNames(aid, draft.behdin.id, "pair", rows.filter(n => n.section === "pair"));
            await putSavedNames(aid, draft.behdin.id, "farmayeshne", rows.filter(n => n.section === "farmayeshne"));
          } catch (e) { /* the event stands */ }
        }

        state.calendar.focus = draft.gregorian;
        state.draft = null;
        // Neither the form nor this review may stay behind the slip in
        // history. A new event replaces this entry; an edit pops back to the
        // slip it was opened from.
        if (draft.edit) returnTo(slipHash);
        else navigate(slipHash, { replace: true });
      } catch (e) {
        confirmBtn.disabled = false;
        showError(e.message);
      }
    };
  };
}
