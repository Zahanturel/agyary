"use strict";

/**
 * New event, or an event of the person's own: the one place anything is added from the calendar's "+". The kind
 * is a choice (Birthday, Navjote, Anniversary, Prayers for the departed, Other); the prayers for a departed lead
 * to their own form, and every other kind is this plain form.
 */

import { createEvent, updateEvent, deleteEvent, getMyEvents, convertDay } from "../api.js";
import { state } from "../state.js";
import { chrome, mainEl, setHeader, loading, wireRetry, loadFailedHtml, showError, openSheet, closeSheet } from "/mobed-app/js/ui.js";
import { navGuard, navigate, returnTo } from "/mobed-app/js/router.js";
import { flagProblems } from "/mobed-app/js/fielderrors.js";
import { calendarHash } from "/mobed-app/js/calendar.js";
import { esc, todayIst, EVENT_KINDS, parsiWords } from "../util.js";

const REPEATS = [
  ["none", "Does not repeat"],
  ["yearly_english", "Every year on this English date"],
  ["yearly_parsi", "Every year on this Parsi date"],
];
const DEPARTED = "departed";

export async function renderEvent(params) {
  chrome(true);
  const id = params && params.id ? Number(params.id) : null;
  setHeader(id ? "Change event" : "New event");
  loading();
  const alive = navGuard();

  let ev = { title: "", kind: "birthday", date: state.draftDate || todayIst(), repeats: "none", notes: "" };
  state.draftDate = null;
  if (id) {
    try {
      const found = (await getMyEvents()).events.find((e) => e.id === id);
      if (!alive()) return;
      if (!found) {
        mainEl.innerHTML = `<div class="card"><p>That event could not be found. It may have been deleted.</p></div>`;
        return;
      }
      ev = found;
    } catch (e) {
      if (!alive()) return;
      mainEl.innerHTML = loadFailedHtml("this event");
      wireRetry(mainEl, () => renderEvent(params));
      return;
    }
  }

  const kinds = id ? EVENT_KINDS : [...EVENT_KINDS.filter(([k]) => k !== "other"), [DEPARTED, "Prayers for the departed"], ["other", "Other"]];
  mainEl.innerHTML = `
    <div class="card" id="evCard">
      <label>Kind of event</label>
      <div class="choice-group" id="evKinds">${kinds.map(([k, t]) => `<div class="check-row">
        <input type="radio" name="evKind" id="evKind_${k}" value="${k}" ${ev.kind === k ? "checked" : ""}>
        <label for="evKind_${k}">${esc(t)}</label></div>`).join("")}</div>

      <div id="evFields">
        <label for="evTitle">Name</label>
        <input type="text" id="evTitle" maxlength="120" autocomplete="off" value="${esc(ev.title)}">

        <label for="evDate">Date</label>
        <input type="date" id="evDate" value="${esc(ev.date)}" min="1850-01-01">
        <p class="meta" id="evParsi" style="margin:6px 0 0"></p>

        <label for="evRepeat">Repeat</label>
        <select id="evRepeat">${REPEATS.map(([k, t]) => `<option value="${k}" ${ev.repeats === k ? "selected" : ""}>${t}</option>`).join("")}</select>

        <label for="evNote">Note</label>
        <textarea id="evNote" rows="3" maxlength="500">${esc(ev.notes || "")}</textarea>
      </div>

      <div class="row" style="margin-top:var(--space-4)">
        <button type="button" id="evSave">Save</button>
        ${id ? `<button type="button" class="ghost danger-outline" id="evDelete">Delete</button>` : ""}
      </div>
    </div>`;

  const kindOf = () => document.querySelector('input[name="evKind"]:checked').value;
  const fields = document.getElementById("evFields");
  const saveBtn = document.getElementById("evSave");
  // Prayers for the departed have a form of their own: Next goes there instead of saving.
  const showKind = () => {
    const departed = kindOf() === DEPARTED;
    fields.style.display = departed ? "none" : "";
    saveBtn.textContent = departed ? "Next" : "Save";
  };
  document.querySelectorAll('input[name="evKind"]').forEach((r) => { r.onchange = showKind; });
  showKind();

  // The Parsi name of the date chosen, so "Every year on this Parsi date" is not a guess.
  const dateEl = document.getElementById("evDate");
  const parsiEl = document.getElementById("evParsi");
  let asked = 0;
  const showParsi = async () => {
    const mine = ++asked;
    parsiEl.textContent = "";
    if (!dateEl.value) return;
    try {
      const p = await convertDay(dateEl.value, state.system);
      if (mine === asked) parsiEl.textContent = parsiWords(p);
    } catch (e) { /* the line is only a help */ }
  };
  dateEl.onchange = showParsi;
  showParsi();

  saveBtn.onclick = async (e) => {
    if (kindOf() === DEPARTED) return navigate("#/departed/new");
    const card = document.getElementById("evCard");
    const body = {
      title: document.getElementById("evTitle").value.trim(),
      kind: kindOf(),
      date: dateEl.value,
      repeats: document.getElementById("evRepeat").value,
      notes: document.getElementById("evNote").value.trim() || null,
    };
    const problems = [];
    if (!body.title) problems.push({ target: "#evTitle", message: "Please enter a name." });
    if (!body.date) problems.push({ target: "#evDate", message: "Please choose the date." });
    if (problems.length) return flagProblems(card, problems);
    const btn = e.currentTarget;
    btn.disabled = true;   // one save per tap
    try {
      if (id) await updateEvent(id, body); else await createEvent(body);
    } catch (err) {
      btn.disabled = false;
      return showError(err.message);
    }
    state.calendar = { mode: "month", focus: body.date, parsiMonth: null, selectedDay: null };
    returnTo(calendarHash(state.calendar));
  };

  const del = document.getElementById("evDelete");
  if (del) {
    del.onclick = () => {
      const { body } = openSheet({
        title: "Delete this event?",
        html: `<p><b>${esc(ev.title)}</b></p>
          <div class="row tight"><button type="button" class="danger" id="evYes">Delete</button>
          <button type="button" class="ghost" id="evNo">Keep it</button></div>`,
      });
      body.querySelector("#evNo").onclick = closeSheet;
      body.querySelector("#evYes").onclick = async (e) => {
        const btn = e.currentTarget;
        btn.disabled = true;
        try {
          await deleteEvent(id);
        } catch (err) {
          btn.disabled = false;
          return showError(err.message);
        }
        closeSheet();
        returnTo(calendarHash(state.calendar));
      };
    };
  }
}
