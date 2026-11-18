"use strict";

/**
 * Edit a saved memorial, on one page (owner, 19 Nov 2026: "all the details in
 * one page, not step by step; keep step by step when creating"): the name, the
 * death (date, or Roj and Mah, with its Roj and Mah shown), the calendar, where
 * the schedule starts, the named days, what repeats and for how long, the
 * Parabs, Roj Fravardin, the birthday and the prayers for new dates - every
 * choice at once, filled in with what was saved.
 *
 * Nothing is saved until the mobed has seen what the change does: "Preview
 * changes" asks the server (the same re-work as before) and lists the dates
 * that are new, that move, and that come off. Every date is counted again from
 * the death, past ones included (the owner's call, 17 Nov 2026), and a date
 * that is still there keeps its prayers, time, note and paid mark. Dates
 * removed one at a time stay out, and can be put back here. A date moved by
 * hand stays where it was put. Changing anything after the preview asks for a
 * new preview before Save. One date at a time is still changed on the
 * memorial's own page; making a memorial keeps its steps (memorial_new.js).
 */

import { memorialEditForm, previewMemorialEdit, saveMemorialEdit } from "../api.js";
import { state } from "../state.js";
import {
  chrome, mainEl, showFab, showError, showInfo, flashInfo, refreshHeader, loading, screenFailed, toTop,
} from "../ui.js";
import { esc, gregLabel, todayIst } from "../util.js";
import { returnTo, navGuard } from "../router.js";
import { prayerServices, parsiText } from "./memorial.js";
import { blankMemorialDraft, buildMemorialBody, memorialFormHtml, wireMemorialForm, showMemorialProblems } from "../memorial_form.js";

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

function dateRow(o, side) {
  return `<div class="obs${o.date < todayIst() ? " past" : ""}"><div class="obs-head" style="cursor:default">
      <div class="obs-title"><b>${esc(o.label)}</b><span>${esc(parsiText(o))}${side ? ` · ${esc(side)}` : ""}</span></div>
      <div class="obs-when">${esc(gregLabel(o.date))}</div></div></div>`;
}

function section(title, intro, rows) {
  if (!rows.length) return "";
  return `<div class="names-group-label"><b>${esc(title)}</b><span>${rows.length}</span></div>
    ${intro ? `<p class="meta" style="margin:0 0 6px">${intro}</p>` : ""}${rows.join("")}`;
}

/** What the change does, date by date: new, moving, coming off, and the dates
 *  taken out earlier (with Put back). `restored` is the set of those put back. */
function changesHtml(preview, restored) {
  const back = preview.left_out.filter(o => restored.has(o.code));
  const stillOut = preview.left_out.filter(o => !restored.has(o.code));
  const added = [...preview.observances.filter(o => o.status === "new"), ...back]
    .sort((a, b) => a.date.localeCompare(b.date));
  const moved = preview.observances.filter(o => o.status === "moved");
  const same = preview.observances.filter(o => o.status === "same" || o.status === "moved_by_hand").length;
  const total = preview.observances.length + back.length;
  const nothing = !added.length && !moved.length && !preview.dropped.length;
  return `
    <div class="card" id="mmChanges">
      <h2>What changes</h2>
      <p style="margin:0">${nothing ? "No date changes." : [
        added.length ? `${added.length} new date${added.length === 1 ? "" : "s"}` : "",
        moved.length ? `${moved.length} date${moved.length === 1 ? " moves" : "s move"}` : "",
        preview.dropped.length ? `${preview.dropped.length} date${preview.dropped.length === 1 ? " comes" : "s come"} off` : "",
      ].filter(Boolean).join(", ") + "."}</p>
      <p class="meta" style="margin:4px 0 8px">The memorial will have ${total} date${total === 1 ? "" : "s"}. ${same} stay as
        they are, keeping their prayers, time, note and paid mark.</p>
      ${section("New dates", "With the prayers chosen above.", added.map(o => dateRow(o, "")))}
      ${section("Moving", "", moved.map(o => dateRow(o, `from ${gregLabel(o.old_date)}`)))}
      ${section("Coming off", "No longer in what you chose.", preview.dropped.map(o =>
        dateRow(o, [o.paid ? "paid" : "", o.notes ? "has a note" : ""].filter(Boolean).join(", "))))}
      ${stillOut.length ? `${section("Removed earlier", "You took these off before, so they stay off. Put one back to keep it again.",
        stillOut.map(o => `<div class="obs"><div class="obs-head" style="cursor:default">
          <div class="obs-title"><b>${esc(o.label)}</b><span>${esc(parsiText(o))}</span></div>
          <div class="obs-when">${esc(gregLabel(o.date))}</div>
          <button type="button" class="ghost small" data-put-back="${esc(o.code)}">Put back</button></div></div>`))}` : ""}
      ${back.length ? `<p class="meta" style="margin:8px 0 0">Put back: ${back.map(o => esc(o.label)).join(", ")}.
        <button type="button" class="ghost small" data-undo-back>Leave them off</button></p>` : ""}
    </div>`;
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
  // The preview shown, for the body it was made from; and the dates taken out
  // earlier that are put back.
  let shown = null;
  const restored = new Set();

  mainEl.innerHTML = `
    <div id="mmForm">${memorialFormHtml(draft, services, {
      heading: `<h2>Edit memorial</h2>`,
      intro: "Every choice is here. Change what you need, then tap Preview changes to see which dates are added, "
        + "moved or taken off. Nothing is saved until you tap Save changes.",
      editing,
    })}</div>
    <div id="mmPreview"></div>
    <div class="action-bar">
      <button type="button" class="secondary" id="mmPreviewBtn">Preview changes</button>
      <button type="button" id="mmSave" disabled>Save changes</button>
    </div>`;
  toTop();
  const formEl = document.getElementById("mmForm");
  const previewEl = document.getElementById("mmPreview");
  const previewBtn = document.getElementById("mmPreviewBtn");
  const saveBtn = document.getElementById("mmSave");

  // Anything changed after a preview needs a new one before it can be saved.
  const stale = () => {
    if (!shown) return;
    shown = null;
    restored.clear();
    previewEl.innerHTML = `<div class="card" role="status"><p class="meta" style="margin:0">You changed something.
      Tap Preview changes again to see what it does before saving.</p></div>`;
    saveBtn.disabled = true;
  };
  wireMemorialForm(formEl, draft, stale, { editing });

  const paintPreview = () => {
    previewEl.innerHTML = changesHtml(shown.preview, restored);
    previewEl.querySelectorAll("[data-put-back]").forEach(btn => {
      btn.onclick = () => { restored.add(btn.dataset.putBack); paintPreview(); };
    });
    const undo = previewEl.querySelector("[data-undo-back]");
    if (undo) undo.onclick = () => { restored.clear(); paintPreview(); };
  };

  previewBtn.onclick = async () => {
    const built = buildMemorialBody(draft);
    if (showMemorialProblems(mainEl, built)) return;
    previewBtn.disabled = true;
    let preview;
    try {
      preview = await previewMemorialEdit(aid, mid, built.body);
    } catch (e) {
      previewBtn.disabled = false;
      return showError(e.message);
    }
    previewBtn.disabled = false;
    if (!alive()) return;
    restored.clear();
    shown = { body: built.body, preview };
    paintPreview();
    saveBtn.disabled = false;
    document.getElementById("mmChanges").scrollIntoView({ block: "start" });
  };

  saveBtn.onclick = async () => {
    if (!shown) return showInfo("Tap Preview changes first, to see what the change does.");
    saveBtn.disabled = true;
    try {
      await saveMemorialEdit(aid, mid, {
        ...shown.body, exclude_codes: [], service_overrides: {}, restore_codes: [...restored],
      });
    } catch (e) {
      saveBtn.disabled = false;
      return showError(e.message);
    }
    flashInfo("Memorial saved.");
    returnTo(home);
  };
}
