"use strict";

/**
 * The one calendar. Renders Month (the default) and Day, and is used both as
 * the app's home screen and as the date picker inside New Event. There is no
 * second grid implementation anywhere.
 *
 * Labelling rule: the top line of every cell is the Gregorian date, with
 * the mobed's PRIMARY calendar reading beneath it. Their other calendars
 * are shown on the Day view rather than stacked into every cell - four date
 * labels per cell is unreadable. Tapping a date opens that day.
 */

import { parsiMonth as fetchParsiMonth, convertDate } from "./api.js";
import { state, GEH_NAME_BY_NUM, primarySystem, visibleParsiSystems } from "./state.js";
import { navigate } from "./router.js";
import {
  esc, todayIst, shiftYmd, gregLabel, gregShort,
  parsiLabel, stepParsiMonth, monthYearLabel,
} from "./util.js";

/** A Parsi month's Roj<->Gregorian mapping never changes once computed, so
 *  re-opening a month already seen this session never re-hits the network. */
export async function parsiMonthDays(mah, year, system) {
  const key = `${system}-${mah}-${year}`;
  if (!state.parsiMonthCache[key]) {
    state.parsiMonthCache[key] = await fetchParsiMonth(mah, year, system);
  }
  return state.parsiMonthCache[key];
}

const MODES = ["day", "month"];
const YMD = /^\d{4}-\d{2}-\d{2}$/;

/** The URL of a calendar view. The view lives in the address - not just in
 *  memory - so Back undoes a drill-down (Month -> Day) and a reload, or a
 *  shared link, lands on the same view. Month is identified by any day inside
 *  it; the Parsi month is derived from that, never stored separately, which is
 *  what kept a stale month on screen after paging days. */
export function calendarHash(view) {
  return `#/calendar/${view.mode}/${view.focus || todayIst()}`;
}

/** Load the route's params into the view. Returns the canonical hash to
 *  redirect to when the params are missing or malformed, else null. */
export function applyCalendarRoute(view, { mode, date } = {}) {
  if (!MODES.includes(mode) || !YMD.test(date || "")) {
    // Includes an old #/calendar/week/... link: there is no Week view any
    // more, so it lands on the month rather than a dead page.
    return calendarHash({ mode: MODES.includes(view.mode) ? view.mode : "month", focus: view.focus });
  }
  view.mode = mode;
  view.focus = date;
  view.parsiMonth = null;
  return null;
}

/** The Gregorian days a view covers - and therefore the window any fetch
 *  of events must be bounded by. */
export async function viewRange(view, system) {
  if (view.mode === "day") return { days: [view.focus], from: view.focus, to: view.focus };
  if (!view.parsiMonth) {
    try {
      const p = await convertDate(view.focus, system);
      view.parsiMonth = { mah: p.is_gatha ? 13 : p.mah, year: p.year };
    } catch (e) {
      const p = await convertDate(todayIst(), system);
      view.parsiMonth = { mah: p.is_gatha ? 13 : p.mah, year: p.year };
    }
  }
  const monthDays = await parsiMonthDays(view.parsiMonth.mah, view.parsiMonth.year, system);
  const days = monthDays.map(p => p.gregorian_date);
  return { days, from: days[0], to: days[days.length - 1], monthDays };
}

function chromeHtml(view, label, secondaryLabel, picker) {
  const isMonth = view.mode === "month";
  // The date picker inside New Event only ever wants a month to pick from.
  return `
    ${picker ? "" : `<div class="toggle" style="margin-bottom:8px">
      <button data-cal-mode="day" class="${view.mode === "day" ? "active" : ""}">Day</button>
      <button data-cal-mode="month" class="${view.mode === "month" ? "active" : ""}">Month</button>
    </div>`}
    <div class="datebar">
      <button class="ghost small" data-cal-prev>&lsaquo;</button>
      <div class="dlabel" ${isMonth ? 'data-cal-monthjump style="cursor:pointer"' : ""}>
        <div class="greg">${esc(label)}</div>
        <div class="parsi">${esc(secondaryLabel)}</div>
      </div>
      <button class="ghost small" data-cal-next>&rsaquo;</button>
    </div>
    <div class="row tight" style="justify-content:space-between;margin-bottom:8px">
      <button class="ghost small" data-cal-today>Today</button>
      <button class="secondary small" data-cal-jump>Jump to a date</button>
    </div>
    <div data-cal-panel></div>`;
}

/** The Parsi-native month grid: exactly 30 Roj (or the Gatha days), so
 *  unlike a Gregorian month it needs no leading/trailing filler. */
function monthGridHtml(monthDays, items, secondaryByDay, selectedDay) {
  const today = todayIst();
  let html = '<div class="parsi-grid">';
  for (const p of monthDays) {
    const day = p.gregorian_date;
    const dayItems = items.filter(it => it.day === day);
    const cls = ["pg-cell", day === today ? "pg-today" : "", day === selectedDay ? "pg-selected" : ""]
      .filter(Boolean).join(" ");
    let inner = `<div class="pg-greg-day">${gregShort(day)}</div>`;
    inner += `<div class="pg-secondary">${esc(secondaryByDay[day] || (p.is_gatha ? p.gatha_name : p.roj_name) || "")}</div>`;
    const shown = dayItems.slice(0, 2);
    for (const it of shown) {
      inner += `<div class="pg-event ${it.kind === "machi" ? "machi" : ""}">${esc(it.label)}</div>`;
    }
    if (dayItems.length > shown.length) {
      inner += `<div class="pg-more">+${dayItems.length - shown.length} more</div>`;
    }
    html += `<div class="${cls}" data-cal-day="${day}">${inner}</div>`;
  }
  return html + "</div>";
}

function itemCardHtml(it) {
  const when = it.time ? `${it.time} · ` : it.geh ? `${GEH_NAME_BY_NUM[it.geh]} Geh · ` : "";
  return `<div class="event ${it.kind === "machi" ? "machi" : ""}" data-cal-item="${it.kind}:${it.id}">
    <div class="t">${esc(when)}${esc(it.label)}</div>
    <div class="s">${esc(it.sublabel || "")}</div>
    ${it.tags ? `<div class="meta">${it.tags}</div>` : ""}
  </div>`;
}

/** Day view: this mobed's own events for the day, in time order.
 *
 * There is no Geh slot grid here. A mobed does not need to see every
 * machi at their fire temple - a machi they are responsible for is simply
 * one of their events, added the same way any event is.
 */
function dayHtml(items) {
  if (!items.length) return `<div class="empty-state">Nothing on this day.</div>`;
  return items
    .slice()
    .sort((a, b) => (a.time || "").localeCompare(b.time || ""))
    .map(itemCardHtml)
    .join("");
}

/** The day's reading in every calendar system the mobed keeps visible. This is
 *  where Kadmi/Fasli live: on the Day view, not in every month cell. Nothing
 *  is added when the primary is the only one - the header already says it. */
async function dayReadingsHtml(ymd) {
  const systems = visibleParsiSystems();
  if (systems.length < 2) return "";
  const rows = await Promise.all(systems.map(async (sys) => {
    const label = await parsiLabel(ymd, sys);
    return `<div class="cd-row"><span class="cd-sys">${esc(sys)}</span>
      <span class="cd-val">${esc(label || "-")}</span></div>`;
  }));
  return `<div class="cell-detail" style="margin-bottom:12px">${rows.join("")}</div>`;
}

/**
 * Render the calendar into `container`.
 *
 * opts:
 *   view           {mode, focus, parsiMonth, selectedDay} - mutated in place
 *   loadItems      async ({from, to, days}) -> [{kind,id,day,time,geh,label,sublabel,tags}]
 *   onItem         (kind, id) -> void
 *   rerender       () -> void  (called after view state changes)
 */
export async function renderCalendar(container, opts) {
  const view = opts.view;
  const system = primarySystem();
  view.focus = view.focus || todayIst();

  container.innerHTML = `<div class="empty-state">Loading...</div>`;
  const range = await viewRange(view, system);

  let items = [];
  try {
    items = await opts.loadItems(range);
  } catch (e) {
    container.innerHTML = "";
    throw e;
  }

  const label = view.mode === "day" ? gregLabel(view.focus)
    : monthYearLabel(view.parsiMonth.mah, view.parsiMonth.year);
  const secondaryLabel = view.mode === "day"
    ? await parsiLabel(view.focus, system)
    : "Tap the title to jump to a month";

  let body;
  if (view.mode === "month") {
    // No per-day lookups: the month grid is already built FROM the
    // secondary system's own month payload, so every cell's Roj (or Gatha)
    // name is sitting in the data we just fetched. Asking the server again
    // per cell was 30 extra round trips for something already in hand.
    body = monthGridHtml(range.monthDays, items, {}, view.selectedDay);
  } else {
    body = (await dayReadingsHtml(view.focus))
      + (opts.renderDay ? await opts.renderDay(items, view) : dayHtml(items));
  }

  container.innerHTML = chromeHtml(view, label, secondaryLabel, !!opts.onDayPick) + body;
  if (opts.wireDay && view.mode === "day") opts.wireDay(container);
  wireChrome(container, view, system, opts);
}

function wireChrome(container, view, system, opts) {
  const panel = container.querySelector("[data-cal-panel]");

  // Every change of what is showing goes through here. On the app's own
  // screens that is a navigation (opts.viewHash): a drill-down pushes an
  // entry so Back undoes it, paging replaces the current one so Back is not
  // a walk through every day visited. The date picker inside New Event has
  // no URL and simply redraws.
  const go = (patch, { push = false } = {}) => {
    // The picker only has a month to show; never let a jump strand it on a day.
    Object.assign(view, opts.onDayPick ? { ...patch, mode: "month" } : patch);
    if (opts.viewHash) navigate(opts.viewHash(view), { replace: !push });
    else opts.rerender();
  };

  container.querySelectorAll("[data-cal-mode]").forEach(b => {
    b.onclick = () => go({ mode: b.dataset.calMode, parsiMonth: null }, { push: true });
  });

  const step = async (delta) => {
    if (view.mode === "month") {
      const pm = stepParsiMonth(view.parsiMonth.mah, view.parsiMonth.year, delta);
      const days = await parsiMonthDays(pm.mah, pm.year, system);
      return go({ focus: days[0].gregorian_date, parsiMonth: null });
    }
    go({ focus: shiftYmd(view.focus, delta), parsiMonth: null });
  };
  container.querySelector("[data-cal-prev]").onclick = () => step(-1);
  container.querySelector("[data-cal-next]").onclick = () => step(1);
  // Today keeps the view you are in: the month containing today, or today.
  container.querySelector("[data-cal-today]").onclick = () => {
    go({ focus: todayIst(), parsiMonth: null });
  };
  container.querySelector("[data-cal-jump]").onclick = () => renderJumpPanel(panel, view, system, go);
  const monthJump = container.querySelector("[data-cal-monthjump]");
  if (monthJump) monthJump.onclick = () => renderMonthJumpPanel(panel, view, system, go);

  // Tapping a date opens that day - one tap, no intermediate panel.
  //
  // In picker mode (New Event's date step) a tap means "this is the date I
  // want" instead.
  container.querySelectorAll("[data-cal-day]").forEach(cell => {
    cell.onclick = () => {
      const day = cell.dataset.calDay;
      if (opts.onDayPick) {
        view.selectedDay = day;
        return opts.onDayPick(day);
      }
      go({ mode: "day", focus: day, parsiMonth: null }, { push: true });
    };
  });

  container.querySelectorAll("[data-cal-item]").forEach(el => {
    el.onclick = () => {
      const [kind, id] = el.dataset.calItem.split(":");
      opts.onItem && opts.onItem(kind, Number(id));
    };
  });
}

function renderMonthJumpPanel(panel, view, system, go) {
  const mahOptions = [
    ...Array.from({ length: 12 }, (_, i) =>
      `<option value="${i + 1}" ${view.parsiMonth.mah === i + 1 ? "selected" : ""}>${
        ["Fravardin", "Ardibehesht", "Khordad", "Tir", "Amardad", "Shahrevar",
          "Meher", "Avan", "Adar", "Dae", "Bahman", "Aspandard"][i]}</option>`),
    `<option value="13" ${view.parsiMonth.mah === 13 ? "selected" : ""}>Gatha days</option>`,
  ].join("");
  panel.innerHTML = `<div class="card">
    <div class="row">
      <div><label>Mah</label><select id="calMah">${mahOptions}</select></div>
      <div><label>Year (YZ)</label><input type="number" id="calYear" value="${view.parsiMonth.year}"></div>
    </div>
    <div style="margin-top:10px" class="row tight">
      <button class="small" id="calMonthGo">Go</button>
      <button class="ghost small" id="calMonthCancel">Cancel</button>
    </div></div>`;
  document.getElementById("calMonthCancel").onclick = () => { panel.innerHTML = ""; };
  document.getElementById("calMonthGo").onclick = async () => {
    const mah = Number(document.getElementById("calMah").value);
    const year = Number(document.getElementById("calYear").value);
    try {
      const days = await parsiMonthDays(mah, year, system);
      go({ focus: days[0].gregorian_date, parsiMonth: null }, { push: true });
    } catch (e) {
      panel.innerHTML = `<div class="error-banner">${esc(e.message)}</div>`;
    }
  };
}

/** Jump by a plain date, or by Roj/Mah. The Roj/Mah path sends NO year -
 *  the server resolves the nearest occurrence. The old build asked for a
 *  YZ year here and pre-filled it with `getUTCFullYear() - 630`, which is
 *  wrong for every date between January 1st and Navroze. */
async function renderJumpPanel(panel, view, system, go) {
  const opts = state.calendarOptions;
  panel.innerHTML = `<div class="card">
    <div class="names-group-label"><b>By date</b></div>
    <input type="date" id="calJumpDate" value="${view.focus}">
    <div style="margin-top:10px"><button class="small" id="calJumpDateGo">Go</button></div>
    <div class="names-group-label" style="margin-top:16px"><b>By Roj &amp; Mah</b>
      <span>next occurrence</span></div>
    <div class="row">
      <div><label>Roj</label><select id="calJumpRoj">${
        opts.roj.map(o => `<option value="${o.id.replace("roj_", "")}">${esc(o.title)}</option>`).join("")}</select></div>
      <div><label>Mah</label><select id="calJumpMah">${
        opts.mah.map(o => `<option value="${o.id.replace("mah_", "")}">${esc(o.title)}</option>`).join("")}</select></div>
    </div>
    <div style="margin-top:10px" class="row tight">
      <button class="small" id="calJumpRojGo">Go</button>
      <button class="ghost small" id="calJumpCancel">Cancel</button>
    </div></div>`;

  document.getElementById("calJumpCancel").onclick = () => { panel.innerHTML = ""; };
  document.getElementById("calJumpDateGo").onclick = () => {
    const d = document.getElementById("calJumpDate").value;
    if (!d) return;
    go({ mode: "day", focus: d, parsiMonth: null }, { push: true });
  };
  document.getElementById("calJumpRojGo").onclick = async () => {
    const roj = document.getElementById("calJumpRoj").value;
    const mah = document.getElementById("calJumpMah").value;
    const { fromParsi } = await import("./api.js");
    try {
      const p = await fromParsi(roj, mah, system);   // no year: server resolves
      go({ mode: "day", focus: p.gregorian_date, parsiMonth: null }, { push: true });
    } catch (e) {
      panel.innerHTML = `<div class="error-banner">${esc(e.message)}</div>`;
    }
  };
}
