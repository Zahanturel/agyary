"use strict";

/**
 * The Calendar tab: one month at a time, each day with its English date and its Parsi Roj, today
 * marked, and a dot on every day that holds the person's own prayers or events. Tapping a day opens
 * what is on it; "Add" starts an event or a departed's prayers.
 */

import { getMyCalendar, getToday, parsiRange, deleteEvent } from "../api.js";
import { state } from "../state.js";
import { chrome, mainEl, setHeader, loading, wireRetry, loadFailedHtml, openSheet, closeSheet, showError, showInfo }
  from "/mobed-app/js/ui.js";
import { navGuard, navigate } from "/mobed-app/js/router.js";
import { APP_NAME } from "../brand.js";
import { esc, longDay, monthName, todayIst, ymdOf, parsiWords, eventKindLabel } from "../util.js";

const WEEK = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const REPEAT_TEXT = {
  none: "",
  yearly_english: "Every year on this English date",
  yearly_parsi: "Every year on this Parsi date",
};

let systemKnown = false;

function monthParts(key) {
  const [y, m] = key.split("-").map(Number);
  return { y, m, days: new Date(Date.UTC(y, m, 0)).getUTCDate(), first: new Date(Date.UTC(y, m - 1, 1)).getUTCDay() };
}

function shiftMonth(key, delta) {
  const { y, m } = monthParts(key);
  const t = new Date(Date.UTC(y, m - 1 + delta, 1));
  return `${t.getUTCFullYear()}-${String(t.getUTCMonth() + 1).padStart(2, "0")}`;
}

/** "Mah Aspandard, then Fravardin, Y.Z. 1396": the Parsi months a Gregorian month runs across. */
function parsiHeading(days) {
  const names = [];
  const years = [];
  for (const p of days) {
    const n = p.is_gatha ? "Gatha days" : p.mah_name;
    if (!names.includes(n)) names.push(n);
    if (!years.includes(p.year)) years.push(p.year);
  }
  const mah = names.length ? "Mah " + names.join(", then ") : "";
  return `${mah}${years.length ? ", Y.Z. " + years.join(" / ") : ""}`;
}

function rojCell(p) {
  if (!p) return "";
  const name = p.is_gatha ? (p.gatha_name || "Gatha") : p.roj_name;
  const num = p.is_gatha ? "G" + p.gatha_index : p.roj;
  return `<span class="cal-roj"><span class="cal-roj-name">${esc(name)}</span><span class="cal-roj-num" aria-hidden="true">${esc(num)}</span></span>`;
}

function dots(list) {
  if (!list.length) return "";
  const mem = list.filter((i) => i.source === "memorial").length;
  const ev = list.length - mem;
  return `<span class="cal-dots" aria-hidden="true">${mem ? '<i class="dot mem"></i>' : ""}${ev ? '<i class="dot ev"></i>' : ""}</span>`;
}

export async function renderCalendar() {
  chrome(true);
  setHeader(APP_NAME);
  loading();
  const alive = navGuard();

  const today = todayIst();
  if (!state.calMonth) state.calMonth = today.slice(0, 7);
  const key = state.calMonth;
  const { y, m, days, first } = monthParts(key);
  const start = ymdOf(y, m, 1);
  const end = ymdOf(y, m, days);

  if (!systemKnown) {
    try { state.system = (await getToday()).calendar || state.system; systemKnown = true; } catch (e) { /* the default */ }
    if (!alive()) return;
  }
  let parsi = [];
  let items = [];
  let failed = false;
  try {
    [parsi, items] = await Promise.all([
      parsiRange(start, end, state.system).catch(() => []),
      getMyCalendar(start, end).then((r) => r.items),
    ]);
  } catch (e) {
    failed = true;
  }
  if (!alive()) return;

  const byDay = {};
  for (const it of items) (byDay[it.date] = byDay[it.date] || []).push(it);
  const parsiOf = (d) => parsi[d - 1] || null;

  let cells = "";
  for (let i = 0; i < first; i++) cells += `<span class="cal-blank"></span>`;
  for (let d = 1; d <= days; d++) {
    const ymd = ymdOf(y, m, d);
    const list = byDay[ymd] || [];
    const p = parsiOf(d);
    const label = `${longDay(ymd)}${p ? ", " + parsiWords(p) : ""}${list.length ? ", " + list.length + (list.length === 1 ? " thing" : " things") : ""}`;
    cells += `<button type="button" class="cal-cell${ymd === today ? " cal-today" : ""}${list.length ? " cal-busy" : ""}"
      data-d="${ymd}" aria-label="${esc(label)}"><span class="cal-d">${d}</span>${rojCell(p)}${dots(list)}</button>`;
  }

  mainEl.innerHTML = `
    <div class="cal-top">
      <button type="button" class="ghost cal-nav" id="calPrev" aria-label="Previous month">&lsaquo;</button>
      <div class="cal-title"><b>${monthName(m)} ${y}</b><span>${esc(parsiHeading(parsi))}</span></div>
      <button type="button" class="ghost cal-nav" id="calNext" aria-label="Next month">&rsaquo;</button>
    </div>
    <div class="row cal-actions">
      <button type="button" class="secondary small" id="calToday">Today</button>
      <button type="button" class="small" id="calAdd">+ Add</button>
    </div>
    ${failed ? loadFailedHtml("your calendar") : ""}
    <div class="cal-grid" role="group" aria-label="${monthName(m)} ${y}">
      ${WEEK.map((w) => `<span class="cal-wd">${w}</span>`).join("")}${cells}
    </div>
    <p class="cal-key meta"><i class="dot mem"></i> A departed's prayer &nbsp; <i class="dot ev"></i> An event</p>`;
  wireRetry(mainEl, () => renderCalendar());

  const go = (k) => { state.calMonth = k; renderCalendar(); };
  document.getElementById("calPrev").onclick = () => go(shiftMonth(key, -1));
  document.getElementById("calNext").onclick = () => go(shiftMonth(key, 1));
  document.getElementById("calToday").onclick = () => go(today.slice(0, 7));
  document.getElementById("calAdd").onclick = () => openAdd(null);
  mainEl.querySelectorAll(".cal-cell").forEach((b) => {
    b.onclick = () => openDay(b.dataset.d, byDay[b.dataset.d] || [], parsiOf(Number(b.dataset.d.slice(8))));
  });
}

/** The "+" choices. `ymd` is the day an event starts on, when a day was open. */
export function openAdd(ymd) {
  const { body } = openSheet({
    title: "Add",
    html: `<div class="stack">
      <button type="button" id="addEvent">Add an event</button>
      <button type="button" id="addDeparted">Add a departed's prayers</button>
    </div>`,
  });
  body.querySelector("#addEvent").onclick = () => { state.draftDate = ymd; closeSheet(); navigate("#/event/new"); };
  body.querySelector("#addDeparted").onclick = () => { closeSheet(); navigate("#/departed/new"); };
}

function itemHtml(it) {
  if (it.source === "memorial") {
    return `<div class="day-item mem">
      <p class="di-title">${esc(it.title)}</p>
      <p class="meta">A departed's prayer: ${esc(it.label)}</p>
      <button type="button" class="small secondary" data-open="${it.memorial_id}">Open</button>
    </div>`;
  }
  const rep = REPEAT_TEXT[it.repeats] || "";
  return `<div class="day-item ev">
    <p class="di-title">${esc(it.title)}</p>
    <p class="meta">${esc(eventKindLabel(it.kind))}${rep ? ". " + esc(rep) : ""}</p>
    <div class="row tight">
      <button type="button" class="small secondary" data-edit="${it.id}">Edit</button>
      <button type="button" class="small danger-outline ghost" data-del="${it.id}">Delete</button>
    </div>
  </div>`;
}

function openDay(ymd, list, parsi) {
  const draw = () => `
    <p class="meta" style="margin:0 0 var(--space-3)">${esc(parsiWords(parsi))}</p>
    ${list.length ? list.map(itemHtml).join("") : `<p>Nothing on this day.</p>`}
    <button type="button" class="secondary" id="dayAdd" style="width:100%;margin-top:var(--space-2)">Add something on this day</button>`;
  const { body } = openSheet({ title: longDay(ymd), html: draw() });

  const wire = () => {
    body.querySelectorAll("[data-open]").forEach((b) => {
      b.onclick = () => { closeSheet(); navigate(`#/departed/${b.dataset.open}`); };
    });
    body.querySelectorAll("[data-edit]").forEach((b) => {
      b.onclick = () => { closeSheet(); navigate(`#/event/${b.dataset.edit}`); };
    });
    body.querySelectorAll("[data-del]").forEach((b) => {
      b.onclick = () => confirmDelete(list.find((i) => i.source === "event" && String(i.id) === b.dataset.del));
    });
    body.querySelector("#dayAdd").onclick = () => { closeSheet(); openAdd(ymd); };
  };

  const confirmDelete = (ev) => {
    body.innerHTML = `
      <p><b>Delete "${esc(ev.title)}"?</b></p>
      <p class="meta">${ev.repeats === "none" ? "It will be removed." : "It will be removed from every year."} This cannot be undone.</p>
      <div class="row tight">
        <button type="button" class="danger" id="delYes">Delete</button>
        <button type="button" class="ghost" id="delNo">Keep it</button>
      </div>`;
    body.querySelector("#delNo").onclick = () => { body.innerHTML = draw(); wire(); };
    body.querySelector("#delYes").onclick = async (e) => {
      const btn = e.currentTarget;
      btn.disabled = true;
      try {
        await deleteEvent(ev.id);
      } catch (err) {
        btn.disabled = false;
        return showError(err.message);
      }
      closeSheet();
      showInfo("Deleted.");
      renderCalendar();
    };
  };
  wire();
}
