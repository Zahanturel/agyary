"use strict";

/** Add or change one of the person's own events: a birthday, a navjote, an anniversary or anything else. */

import { createEvent, updateEvent, deleteEvent, getMyEvents, convertDay } from "../api.js";
import { state } from "../state.js";
import { chrome, mainEl, setHeader, loading, wireRetry, loadFailedHtml, showError, openSheet, closeSheet } from "/mobed-app/js/ui.js";
import { navGuard, returnTo } from "/mobed-app/js/router.js";
import { flagProblems } from "/mobed-app/js/fielderrors.js";
import { esc, todayIst, EVENT_KINDS, parsiWords } from "../util.js";
import { ensureConsent } from "../consent.js";

const REPEATS = [
  ["none", "Does not repeat"],
  ["yearly_english", "Every year on this English date"],
  ["yearly_parsi", "Every year on this Parsi date"],
];

export async function renderEvent(params) {
  chrome(true);
  const id = params && params.id ? Number(params.id) : null;
  setHeader(id ? "Change event" : "Add an event");
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
  } else {
    ensureConsent();
  }

  mainEl.innerHTML = `
    <div class="card" id="evCard">
      <label for="evTitle">What is it?</label>
      <input type="text" id="evTitle" maxlength="120" autocomplete="off" value="${esc(ev.title)}" placeholder="For example: Farzin's birthday">

      <label for="evKind">Kind</label>
      <select id="evKind">${EVENT_KINDS.map(([k, t]) => `<option value="${k}" ${ev.kind === k ? "selected" : ""}>${t}</option>`).join("")}</select>

      <label for="evDate">Date</label>
      <input type="date" id="evDate" value="${esc(ev.date)}" min="1850-01-01">
      <p class="meta" id="evParsi" style="margin:6px 0 0"></p>

      <label for="evRepeat">Repeat</label>
      <select id="evRepeat">${REPEATS.map(([k, t]) => `<option value="${k}" ${ev.repeats === k ? "selected" : ""}>${t}</option>`).join("")}</select>

      <label for="evNote">Note (if you like)</label>
      <textarea id="evNote" rows="3" maxlength="500">${esc(ev.notes || "")}</textarea>

      <div class="row" style="margin-top:var(--space-4)">
        <button type="button" id="evSave">Save</button>
        ${id ? `<button type="button" class="ghost danger-outline" id="evDelete">Delete</button>` : ""}
      </div>
    </div>`;

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

  document.getElementById("evSave").onclick = async (e) => {
    const card = document.getElementById("evCard");
    const body = {
      title: document.getElementById("evTitle").value.trim(),
      kind: document.getElementById("evKind").value,
      date: dateEl.value,
      repeats: document.getElementById("evRepeat").value,
      notes: document.getElementById("evNote").value.trim() || null,
    };
    const problems = [];
    if (!body.title) problems.push({ target: "#evTitle", message: "Please enter what it is." });
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
    state.calMonth = body.date.slice(0, 7);
    returnTo("#/calendar");
  };

  const del = document.getElementById("evDelete");
  if (del) {
    del.onclick = () => {
      const { body } = openSheet({
        title: "Delete this event?",
        html: `<p><b>${esc(ev.title)}</b></p>
          <p class="meta">${ev.repeats === "none" ? "It will be removed." : "It will be removed from every year."} This cannot be undone.</p>
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
        returnTo("#/calendar");
      };
    };
  }
}
