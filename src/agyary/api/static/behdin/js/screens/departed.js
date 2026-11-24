"use strict";

/** One departed person's prayers: every date the server has counted, with its Roj and Mah and its day's name. */

import { getMemorial, deleteMemorial } from "../api.js";
import { chrome, mainEl, setHeader, loading, wireRetry, loadFailedHtml, showError, openSheet, closeSheet } from "/mobed-app/js/ui.js";
import { navGuard, navigate, returnTo } from "/mobed-app/js/router.js";
import { esc, todayIst, gregShort, weekdayOf, parsiWords, MAH_NAMES, ROJ_NAMES, GATHAS } from "../util.js";

const SHOW_AT_FIRST = 60;

function rojMahWords(roj, mah) {
  if (!roj || !mah) return "";
  if (mah === 13) return `${GATHAS[roj - 1] || "Extra day"} (Gatha)`;
  return `Roj ${ROJ_NAMES[roj - 1]}, Mah ${MAH_NAMES[mah - 1]}`;
}

function passedLine(m) {
  const words = rojMahWords(m.death_roj, m.death_mah);
  if (m.long_ago) return `Passed away more than a year ago, on ${words}.`;
  return `Passed away on ${weekdayOf(m.death_date)} ${gregShort(m.death_date)}${words ? ", " + words : ""}.`;
}

function dateRow(o, today, next) {
  const past = o.date < today;
  return `<div class="obs-row${past ? " past" : ""}${next ? " next" : ""}">
    <div class="obs-date"><b>${gregShort(o.date)}</b><span>${weekdayOf(o.date).slice(0, 3)}</span></div>
    <div class="obs-what"><b>${esc(o.label)}</b><span>${esc(parsiWords(o.parsi) || rojMahWords(o.parsi_roj, o.parsi_mah))}</span>
      ${next ? `<span class="tag">Next</span>` : past ? `<span class="tag grey">Done</span>` : ""}</div>
  </div>`;
}

export async function renderDeparted(params) {
  chrome(true);
  setHeader("A departed's prayers");
  loading();
  const alive = navGuard();
  const id = Number(params.id);

  let m;
  try {
    m = await getMemorial(id);
  } catch (e) {
    if (!alive()) return;
    mainEl.innerHTML = e.status === 404
      ? `<div class="card"><p>That could not be found. It may have been deleted.</p></div>`
      : loadFailedHtml("these prayers");
    wireRetry(mainEl, () => renderDeparted(params));
    return;
  }
  if (!alive()) return;

  const today = todayIst();
  const all = m.observances;
  const ahead = all.filter((o) => o.date >= today);
  const done = all.filter((o) => o.date < today);
  const name = m.name_known ? m.departed_name : "Name not known";
  let shown = SHOW_AT_FIRST;

  const draw = () => {
    mainEl.innerHTML = `
      <div class="card">
        <h2>${esc(name)}</h2>
        <p class="meta" style="margin:0">${esc(passedLine(m))}</p>
        <div class="row" style="margin-top:var(--space-3)">
          <button type="button" class="secondary small" id="dEdit">Edit</button>
          <button type="button" class="ghost small danger-outline" id="dDelete">Delete</button>
        </div>
      </div>
      <div class="card">
        <h2>Dates still to come</h2>
        ${ahead.length ? ahead.slice(0, shown).map((o, i) => dateRow(o, today, i === 0)).join("")
          : `<p class="meta">There are no more dates to come.</p>`}
        ${ahead.length > shown ? `<button type="button" class="ghost small" id="dMore" style="margin-top:var(--space-2)">Show ${Math.min(ahead.length - shown, SHOW_AT_FIRST)} more</button>` : ""}
      </div>
      ${done.length ? `<details class="card"><summary><b>Dates already past (${done.length})</b></summary>
        ${done.map((o) => dateRow(o, today, false)).join("")}</details>` : ""}`;
    document.getElementById("dEdit").onclick = () => navigate(`#/departed/${id}/edit`);
    document.getElementById("dDelete").onclick = askDelete;
    const more = document.getElementById("dMore");
    if (more) more.onclick = () => { shown += SHOW_AT_FIRST; draw(); };
  };

  const askDelete = () => {
    const { body } = openSheet({
      title: "Delete these prayers?",
      html: `<p><b>${esc(name)}</b></p>
        <p class="meta">All ${m.count} dates are removed from your calendar. This cannot be undone.</p>
        <div class="row tight"><button type="button" class="danger" id="dYes">Delete</button>
        <button type="button" class="ghost" id="dNo">Keep them</button></div>`,
    });
    body.querySelector("#dNo").onclick = closeSheet;
    body.querySelector("#dYes").onclick = async (e) => {
      const btn = e.currentTarget;
      btn.disabled = true;
      try {
        await deleteMemorial(id);
      } catch (err) {
        btn.disabled = false;
        return showError(err.message);
      }
      closeSheet();
      returnTo("#/calendar");
    };
  };

  draw();
}
