"use strict";

/**
 * The one calendar. Renders Day/Week/Month, and is used both as the app's
 * home screen and as the date picker inside New Event. There is no second
 * grid implementation anywhere.
 *
 * Labelling rule: the top line of every cell is the Gregorian date, with
 * the mobed's PRIMARY calendar reading beneath it. Their other calendars
 * are revealed by tapping a day rather than stacked into every cell -
 * four date labels per cell is unreadable.
 */

import { parsiMonth as fetchParsiMonth, convertDate, calendarRange } from "./api.js";
import { state, GEH_NAME_BY_NUM, primarySystem, visibleParsiSystems } from "./state.js";
import {
  esc, todayIst, shiftYmd, weekDays, gregLabel, gregShort,
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

/** The Gregorian days a view covers - and therefore the window any fetch
 *  of events must be bounded by. */
export async function viewRange(view, system) {
  if (view.mode === "day") return { days: [view.focus], from: view.focus, to: view.focus };
  if (view.mode === "week") {
    const days = weekDays(view.focus);
    return { days, from: days[0], to: days[days.length - 1] };
  }
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

function chromeHtml(view, label, secondaryLabel) {
  const isMonth = view.mode === "month";
  return `
    <div class="toggle" style="margin-bottom:8px">
      <button data-cal-mode="day" class="${view.mode === "day" ? "active" : ""}">Day</button>
      <button data-cal-mode="week" class="${view.mode === "week" ? "active" : ""}">Week</button>
      <button data-cal-mode="month" class="${view.mode === "month" ? "active" : ""}">Month</button>
    </div>
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

/** The week's seven Parsi readings, fetched as one range rather than seven
 *  conversions, and cached like every other reading. */
async function weekReadings(range, system) {
  const out = {};
  const missing = range.days.filter(d => !state.parsiCache[`${d}|short|${system}`]);
  if (missing.length) {
    try {
      const rows = await calendarRange(range.from, range.to, system);
      for (const p of rows) {
        const label = p.is_gatha ? p.gatha_name : `Roj ${p.roj_name}`;
        state.parsiCache[`${p.gregorian_date}|short|${system}`] = label;
      }
    } catch (e) { /* fall through: the week renders without readings */ }
  }
  for (const d of range.days) out[d] = state.parsiCache[`${d}|short|${system}`] || "";
  return out;
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

function weekHtml(days, items, readings) {
  let html = "";
  for (const day of days) {
    const dayItems = items.filter(it => it.day === day)
      .sort((a, b) => (a.time || "").localeCompare(b.time || ""));
    // Every date carries its primary-calendar reading, week view included -
    // a mobed scanning the week needs the Roj as much as the weekday.
    const reading = readings[day] ? ` <span class="wk-parsi">${esc(readings[day])}</span>` : "";
    html += `<div class="daysection"><h3 data-cal-day="${day}" style="cursor:pointer">${gregLabel(day)}${reading}</h3>`;
    html += dayItems.length
      ? dayItems.map(itemCardHtml).join("")
      : `<div class="meta" style="padding:2px 2px 8px">Nothing.</div>`;
    html += `</div>`;
  }
  return html;
}

/** The tapped day's reading in every system the user chose to see. This is
 *  where Kadmi/Fasli live: on demand, not in every cell. */
async function cellDetailHtml(ymd) {
  const systems = visibleParsiSystems();
  const rows = await Promise.all(systems.map(async (sys) => {
    const label = await parsiLabel(ymd, sys);
    return `<div class="cd-row"><span class="cd-sys">${esc(sys)}</span>
      <span class="cd-val">${esc(label || "-")}</span></div>`;
  }));
  return `<div class="cell-detail">
    <div class="cd-row"><span class="cd-sys">Gregorian</span>
      <span class="cd-val">${esc(gregLabel(ymd))}</span></div>
    ${rows.join("")}
    <div class="row tight" style="margin-top:8px">
      <button class="small" data-cal-open="${ymd}">Open this day</button>
      <button class="ghost small" data-cal-closedetail>Close</button>
    </div>
  </div>`;
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
    : view.mode === "week" ? "Week of " + gregLabel(range.days[0])
      : monthYearLabel(view.parsiMonth.mah, view.parsiMonth.year);
  const secondaryLabel = view.mode === "day"
    ? await parsiLabel(view.focus, system)
    : view.mode === "month" ? "Tap the title to jump to a month" : "";

  let body;
  if (view.mode === "month") {
    // No per-day lookups: the month grid is already built FROM the
    // secondary system's own month payload, so every cell's Roj (or Gatha)
    // name is sitting in the data we just fetched. Asking the server again
    // per cell was 30 extra round trips for something already in hand.
    body = monthGridHtml(range.monthDays, items, {}, view.selectedDay);
  } else if (view.mode === "week") {
    body = weekHtml(range.days, items, await weekReadings(range, system));
  } else {
    body = opts.renderDay ? await opts.renderDay(items, view) : dayHtml(items);
  }

  container.innerHTML = chromeHtml(view, label, secondaryLabel) + body;
  if (opts.wireDay && view.mode === "day") opts.wireDay(container);
  wireChrome(container, view, system, opts);
}

function wireChrome(container, view, system, opts) {
  const rerender = opts.rerender;
  const panel = container.querySelector("[data-cal-panel]");

  container.querySelectorAll("[data-cal-mode]").forEach(b => {
    b.onclick = () => { view.mode = b.dataset.calMode; rerender(); };
  });
  container.querySelector("[data-cal-prev]").onclick = () => {
    if (view.mode === "month") view.parsiMonth = stepParsiMonth(view.parsiMonth.mah, view.parsiMonth.year, -1);
    else view.focus = shiftYmd(view.focus, view.mode === "day" ? -1 : -7);
    rerender();
  };
  container.querySelector("[data-cal-next]").onclick = () => {
    if (view.mode === "month") view.parsiMonth = stepParsiMonth(view.parsiMonth.mah, view.parsiMonth.year, 1);
    else view.focus = shiftYmd(view.focus, view.mode === "day" ? 1 : 7);
    rerender();
  };
  container.querySelector("[data-cal-today]").onclick = () => {
    view.focus = todayIst();
    view.parsiMonth = null;
    view.mode = "day";
    rerender();
  };
  container.querySelector("[data-cal-jump]").onclick = () => renderJumpPanel(panel, view, system, rerender);
  const monthJump = container.querySelector("[data-cal-monthjump]");
  if (monthJump) monthJump.onclick = () => renderMonthJumpPanel(panel, view, rerender);

  // Tapping a day in Month/Week reveals that day's other calendar systems
  // rather than navigating immediately - the reveal IS the multi-calendar
  // feature, and "open this day" is one more tap from there.
  //
  // Except in picker mode (New Event's date step), where a tap means
  // "this is the date I want" and anything else would be an extra step.
  container.querySelectorAll("[data-cal-day]").forEach(cell => {
    cell.onclick = async () => {
      const day = cell.dataset.calDay;
      if (opts.onDayPick) {
        view.selectedDay = day;
        return opts.onDayPick(day);
      }
      view.selectedDay = day;
      panel.innerHTML = await cellDetailHtml(day);
      panel.querySelector("[data-cal-open]").onclick = () => {
        view.mode = "day"; view.focus = day; view.selectedDay = null; rerender();
      };
      panel.querySelector("[data-cal-closedetail]").onclick = () => {
        view.selectedDay = null; panel.innerHTML = "";
      };
      panel.scrollIntoView({ block: "nearest" });
    };
  });

  container.querySelectorAll("[data-cal-item]").forEach(el => {
    el.onclick = () => {
      const [kind, id] = el.dataset.calItem.split(":");
      opts.onItem && opts.onItem(kind, Number(id));
    };
  });
}

function renderMonthJumpPanel(panel, view, rerender) {
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
  document.getElementById("calMonthGo").onclick = () => {
    view.parsiMonth = {
      mah: Number(document.getElementById("calMah").value),
      year: Number(document.getElementById("calYear").value),
    };
    rerender();
  };
}

/** Jump by a plain date, or by Roj/Mah. The Roj/Mah path sends NO year -
 *  the server resolves the nearest occurrence. The old build asked for a
 *  YZ year here and pre-filled it with `getUTCFullYear() - 630`, which is
 *  wrong for every date between January 1st and Navroze. */
async function renderJumpPanel(panel, view, system, rerender) {
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
    view.mode = "day"; view.focus = d; view.parsiMonth = null; rerender();
  };
  document.getElementById("calJumpRojGo").onclick = async () => {
    const roj = document.getElementById("calJumpRoj").value;
    const mah = document.getElementById("calJumpMah").value;
    const { fromParsi } = await import("./api.js");
    try {
      const p = await fromParsi(roj, mah, system);   // no year: server resolves
      view.mode = "day"; view.focus = p.gregorian_date; view.parsiMonth = null; rerender();
    } catch (e) {
      panel.innerHTML = `<div class="error-banner">${esc(e.message)}</div>`;
    }
  };
}
