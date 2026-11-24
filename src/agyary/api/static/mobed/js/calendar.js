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

import { parsiMonth as fetchParsiMonth, convertDate, fromParsi } from "./api.js";
import { state, GEH_NAME_BY_NUM, primarySystem, visibleParsiSystems } from "./state.js";
import { navigate } from "./router.js";
import { payChipHtml, flipPaidChip } from "./paid_chip.js";
import { loadFailedHtml, wireRetry, showError, showInfo, openSheet } from "./ui.js";
import {
  esc, todayIst, shiftYmd, gregLabel, gregShort, gregCell,
  parsiLabel, stepParsiMonth, monthYearLabel, MAH_NAMES_JS,
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
export function calendarHash(view, root = "calendar") {
  return `#/${root}/${view.mode}/${view.focus || todayIst()}`;
}

/** The Machi tab's view of the same day: one view object, two tabs, so
 *  switching between them never moves the date or the Day/Month choice. */
export function boardHash(view) {
  return calendarHash(view, "board");
}

/** Load the route's params into the view. Returns the canonical hash to
 *  redirect to when the params are missing or malformed, else null. */
export function applyCalendarRoute(view, { mode, date } = {}, root = "calendar") {
  if (!MODES.includes(mode) || !YMD.test(date || "")) {
    // Includes an old #/calendar/week/... link: there is no Week view any
    // more, so it lands on the month rather than a dead page.
    return calendarHash({ mode: MODES.includes(view.mode) ? view.mode : "month", focus: view.focus }, root);
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
  // A local copy of the month being drawn: another tap or route can clear view.parsiMonth while this
  // awaits (the red "Cannot read properties of null (reading 'mah')", owner, 24 Nov 2026), so nothing
  // below reads it again after an await.
  let pm = view.parsiMonth;
  if (!pm) {
    try {
      const p = await convertDate(view.focus, system);
      pm = { mah: p.is_gatha ? 13 : p.mah, year: p.year };
    } catch (e) {
      const p = await convertDate(todayIst(), system);
      pm = { mah: p.is_gatha ? 13 : p.mah, year: p.year };
    }
    view.parsiMonth = pm;
  }
  const monthDays = await parsiMonthDays(pm.mah, pm.year, system);
  const days = monthDays.map(p => p.gregorian_date);
  return { days, from: days[0], to: days[days.length - 1], monthDays, parsiMonth: pm };
}

function chromeHtml(view, label, secondaryLabel, picker) {
  const unit = view.mode === "month" ? "month" : "day";
  // The date picker inside New Event only ever wants a month to pick from.
  // The title is the way to anywhere: it opens every month of the year at once
  // (openGoTo), so a month ten away is two taps, not ten. The arrows and a
  // swipe still step one at a time.
  return `
    <div class="cal-top">
      ${picker ? "<span></span>" : `<div class="toggle">
        <button data-cal-mode="day" class="${view.mode === "day" ? "active" : ""}">Day</button>
        <button data-cal-mode="month" class="${view.mode === "month" ? "active" : ""}">Month</button>
      </div>`}
      <button type="button" class="ghost small" data-cal-today>Today</button>
    </div>
    <div class="datebar">
      <button type="button" class="ghost small" data-cal-prev aria-label="Previous ${unit}">&lsaquo;</button>
      <button type="button" class="dlabel" data-cal-goto aria-haspopup="dialog"
        aria-label="${esc(label)}, ${esc(secondaryLabel)}. Go to another month or date">
        <span class="greg">${esc(label)}<span class="caret" aria-hidden="true"></span></span>
        <span class="parsi">${esc(secondaryLabel)}</span>
      </button>
      <button type="button" class="ghost small" data-cal-next aria-label="Next ${unit}">&rsaquo;</button>
    </div>`;
}

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

// A month cell on a phone holds about six letters at a readable size, so the
// longer names break at a syllable rather than shrink (UX-03).
const SYLLABLES = {
  Ardibehesht: ["Ardi", "be", "hesht"], Ashishvangh: ["Ashish", "vangh"], Mareshpand: ["Mar", "esh", "pand"],
  Fravardin: ["Fra", "var", "din"], Aspandard: ["Aspan", "dard"], Shahrevar: ["Shah", "re", "var"],
  Khorshed: ["Khor", "shed"], Khordad: ["Khor", "dad"], Amardad: ["Amar", "dad"], Hormazd: ["Hor", "mazd"],
  Behram: ["Beh", "ram"], Zamyad: ["Zam", "yad"], Bahman: ["Bah", "man"], Ahunavad: ["Ahu", "na", "vad"],
  Ushtavad: ["Ushta", "vad"], Spentamad: ["Spen", "ta", "mad"], Vohukhshathra: ["Vohu", "khsha", "thra"],
  Vahishtoisht: ["Vahish", "toisht"],
};
const rojForCell = (name) => (SYLLABLES[name] ? SYLLABLES[name].join("\u00AD") : name);

function weekdayIndex(ymd) {
  const [y, m, d] = ymd.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).getUTCDay();   // Sun = 0
}

/** The month, laid out like the wall calendar on the fire temple's wall.
 *
 * A Parsi month is 30 Roj (or the Gatha days) and starts on whatever weekday
 * Roj 1 falls on, so the grid is weekday-aligned: the seven weekdays run down
 * the left, each week is a column, and the month simply starts in the row of
 * its first day, with blanks above it. Weekday labels sit once at the edge
 * instead of inside every cell, which is what keeps the cells uncramped.
 *
 * A cell is the date, the Roj, and what is on that day - up to two short event
 * names, then "+N". The mobed reads the month to see what is happening when,
 * so the names stay in the cells; the full detail is on the Day view, which a
 * tap opens. */
function monthGridHtml(monthDays, items, selectedDay, chips = {}) {
  const maxChips = chips.max || 2;
  const today = todayIst();
  const lead = weekdayIndex(monthDays[0].gregorian_date);
  const cols = Math.ceil((lead + monthDays.length) / 7);
  let html = `<div class="parsi-grid" style="--cols:${cols}">`;
  for (let row = 0; row < 7; row++) {
    html += `<div class="pg-wd${row === 0 ? " sun" : ""}">${WEEKDAYS[row]}</div>`;
    for (let col = 0; col < cols; col++) {
      const idx = col * 7 + row - lead;
      const p = monthDays[idx];
      if (idx < 0 || !p) { html += `<div class="pg-blank"></div>`; continue; }

      const day = p.gregorian_date;
      const dayItems = items.filter(it => it.day === day).sort(pinnedFirst);
      // How many things are on the day. The closing notice is a note about a
      // memorial's last date, not a second thing to do, so it is not counted
      // beside that date.
      const n = dayItems.filter(it => it.kind !== "memorial_closing").length || dayItems.length;
      const roj = (p.is_gatha ? p.gatha_name : p.roj_name) || "";
      const cls = ["pg-cell", n ? "pg-busy" : "", day === today ? "pg-today" : "",
        day === selectedDay ? "pg-selected" : ""].filter(Boolean).join(" ");
      // The day number alone, except where the Gregorian month turns over.
      const dayNo = Number(day.slice(8));
      const withMonth = idx === 0 || dayNo === 1;
      const numLabel = withMonth ? gregCell(day) : String(dayNo);
      const shown = dayItems.slice(0, maxChips)
        .map(it => `<span class="pg-event${KIND_CLASS[it.kind] || ""}"
          title="${esc(it.label)}${it.sublabel ? " - " + esc(it.sublabel) : ""}">${esc(it.short || it.label)}</span>`)
        .join("");
      const more = dayItems.length > maxChips
        ? `<span class="pg-more">+${dayItems.length - maxChips} more</span>` : "";
      // A phone's cell is too narrow for names, so there every kind of event is
      // marked the one way: the date is shaded and carries how many (the names
      // are a tap away, on the day). Wide screens show the names instead.
      html += `<div class="${cls}" data-cal-day="${day}" role="button" tabindex="0"
        aria-label="${esc(gregLabel(day))}, ${esc(roj)}${n ? `, ${n} event${n > 1 ? "s" : ""}` : ""}">
        <span class="pg-greg-day${withMonth ? " with-month" : ""}">${esc(numLabel)}</span>
        <span class="pg-roj">${esc(rojForCell(roj))}</span>
        ${n ? `<span class="pg-count" aria-hidden="true">${n}</span>` : ""}
        <span class="pg-events${chips.wrap ? " wrap" : ""}">${shown}${more}</span></div>`;
    }
  }
  // The shading needs saying once, and only where there is any.
  const any = items.length > 0;
  return html + `</div>${any ? `
    <p class="pg-key no-print"><span class="pg-key-cell"><span class="pg-count">2</span></span>A shaded date has something on it - the
      number is how many. Tap the date to see.</p>` : ""}`;
}

// Kinds with their own look. Memorial observances are a category of their own,
// and the closing notice is pinned: it sorts above everything else on its day.
const KIND_CLASS = { machi: " machi", memorial: " memorial", memorial_closing: " closing" };
const pinnedFirst = (a, b) => (b.kind === "memorial_closing") - (a.kind === "memorial_closing");

function itemCardHtml(it) {
  const when = it.time ? `${it.time} · ` : it.geh ? `${GEH_NAME_BY_NUM[it.geh]} Geh · ` : "";
  return `<div class="event${KIND_CLASS[it.kind] || ""}" data-cal-item="${it.kind}:${it.id}">
    <div class="ev-row"><div class="ev-main">
      <div class="t">${esc(when)}${esc(it.label)}</div>
      <div class="s">${esc(it.sublabel || "")}</div>
    </div>${it.paid === undefined ? "" : payChipHtml(it.kind, it.id, it.paid)}</div>
    ${it.tags ? `<div class="meta">${it.tags}</div>` : ""}
    ${it.kind === "memorial" ? `<div class="ev-actions">
      <button type="button" class="ghost small" data-ev-edit aria-label="Edit ${esc(it.label)}">Edit</button>
      <button type="button" class="ghost small ev-remove" data-ev-remove aria-label="Remove ${esc(it.label)}">Remove</button>
    </div><div class="ev-confirm"></div>` : ""}
  </div>`;
}

/** "Remove this date?" in place on a memorial date in the day list; a yes takes
 *  it out of its memorial (opts.onRemove) and redraws the day. */
function confirmRemove(card, kind, id, opts) {
  const box = card.querySelector(".ev-confirm");
  if (!box || box.innerHTML) return;
  const label = card.querySelector(".t").textContent;
  box.innerHTML = `<div class="row-confirm row-pending" style="margin-top:8px;flex-wrap:wrap">
    <span>Remove ${esc(label)} from its memorial? It stays off if the memorial is edited later.</span>
    <span class="row"><button type="button" class="ghost small" data-ev-keep>Keep</button>
    <button type="button" class="danger small" data-ev-yes>Remove</button></span></div>`;
  // Neither tap may reach the card, which would open the memorial (Keep empties
  // the box, so by then the card can no longer tell where the tap came from).
  box.querySelector("[data-ev-keep]").onclick = (e) => { e.stopPropagation(); box.innerHTML = ""; };
  box.querySelector("[data-ev-yes]").onclick = async (e) => {
    e.stopPropagation();
    const yes = e.currentTarget;
    yes.disabled = true;
    try {
      if (!opts.onRemove) throw new Error("Open the memorial to remove this date.");
      await opts.onRemove(kind, id);
    } catch (err) {
      yes.disabled = false;
      return showError("Couldn't remove it: " + err.message);
    }
    showInfo(`${label} was removed from its memorial.`);
    if (opts.rerender) opts.rerender();
  };
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
    .sort((a, b) => pinnedFirst(a, b) || (a.time || "").localeCompare(b.time || ""))
    .map(itemCardHtml)
    .join("");
}

/** The day's reading in every calendar system the mobed keeps visible. This is
 *  where Kadmi lives: on the Day view, not in every month cell. Nothing
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
 *   monthChips     how many event names a month cell lists before "+N more" (default 2)
 *   monthChipWrap  let a long event name wrap onto a second line instead of clipping
 *   rerender       () -> void  (called after view state changes)
 */
export async function renderCalendar(container, opts) {
  const view = opts.view;
  const system = primarySystem();
  view.focus = view.focus || todayIst();

  const what = view.mode === "day" ? "this day" : "this month";
  container.innerHTML = `<div class="empty-state">Loading...</div>`;
  let range;
  try {
    range = await viewRange(view, system);
  } catch (e) {
    // Not even the month's dates: nothing can be drawn, so nothing is.
    container.innerHTML = loadFailedHtml(what);
    return wireRetry(container, opts.rerender);
  }

  // Never an empty calendar for a failed load: a mobed would read it as a free
  // day (UX-01). A list marked .incomplete is part of what was asked for.
  let items = [], failed = false;
  try {
    items = await opts.loadItems(range);
    failed = !!items.incomplete;
  } catch (e) {
    failed = true;
  }

  const label = view.mode === "day" ? gregLabel(view.focus)
    : monthYearLabel(range.parsiMonth.mah, range.parsiMonth.year);
  const secondaryLabel = view.mode === "day"
    ? await parsiLabel(view.focus, system)
    : `${gregShort(range.from)} - ${gregShort(range.to)}`;

  const notice = failed ? loadFailedHtml(what, { whole: !items.length }) : "";
  let body;
  if (view.mode === "month") {
    // No per-day lookups: the month grid is already built FROM the
    // primary system's own month payload, so every cell's Roj (or Gatha)
    // name is sitting in the data we just fetched.
    body = monthGridHtml(range.monthDays, items, view.selectedDay, {
      max: opts.monthChips, wrap: opts.monthChipWrap,
    });
  } else if (failed) {
    body = items.length ? dayHtml(items) : "";
  } else {
    body = (await dayReadingsHtml(view.focus))
      + (opts.renderDay ? await opts.renderDay(items, view) : dayHtml(items));
  }

  container.innerHTML = chromeHtml(view, label, secondaryLabel, !!opts.onDayPick) + notice + body;
  wireRetry(container, opts.rerender);
  if (opts.wireDay && view.mode === "day" && !failed) opts.wireDay(container);
  wireChrome(container, view, system, opts, range);
}

function wireChrome(container, view, system, opts, range) {
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
      // The month on screen (range), not view.parsiMonth, which a tap or a route may have cleared meanwhile.
      const cur = range.parsiMonth || view.parsiMonth;
      if (!cur) return;
      const pm = stepParsiMonth(cur.mah, cur.year, delta);
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
  container.querySelector("[data-cal-goto]").onclick = () => openGoTo(view, system, go);

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
    el.onclick = (e) => {
      // The paid chip is its own control: it flips the tick and never opens the event.
      const chip = e.target.closest(".pay-chip");
      if (chip) {
        e.stopPropagation();
        const [k, i] = chip.dataset.pay.split(":");
        return flipPaidChip(chip, opts.onPay && ((paid) => opts.onPay(k, Number(i), paid)));
      }
      const [kind, id] = el.dataset.calItem.split(":");
      // A memorial date's Remove asks first, in place; its own buttons do the rest.
      if (e.target.closest("[data-ev-remove]")) return confirmRemove(el, kind, Number(id), opts);
      if (e.target.closest(".ev-confirm") || !el.contains(e.target)) return;
      // The card itself, or its Edit button, opens it.
      opts.onItem && opts.onItem(kind, Number(id));
    };
  });
}

// --- Go to ----------------------------------------------------------------------
// One sheet for getting anywhere: every month of a year on one screen (and the
// years either side one tap away), or a plain date, or a Roj and Mah.

/** The Parsi month on screen and the Gregorian day it starts on - what the
 *  other months of the sheet are counted from. */
async function monthAnchor(view, system) {
  let pm = view.parsiMonth;
  if (!pm) {
    const p = await convertDate(view.focus, system);
    pm = { mah: p.is_gatha ? 13 : p.mah, year: p.year };
  }
  const days = await parsiMonthDays(pm.mah, pm.year, system);
  return { mah: pm.mah, year: pm.year, start: days[0].gregorian_date };
}

/** First and last Gregorian day of a month, counted from the anchor. Shenshai
 *  and Kadmi years are twelve months of 30 days and five Gatha days, with no
 *  leap day, so this is exact for them. It is only ever used for the small
 *  print on a tile: opening a month asks the server for its real days. Fasli
 *  has a leap day, so its tiles go without the small print. */
function monthSpan(anchor, mah, year) {
  const start = shiftYmd(anchor.start, (mah - anchor.mah) * 30 + (year - anchor.year) * 365);
  return { start, end: shiftYmd(start, mah === 13 ? 4 : 29) };
}

function goToMonthsHtml(anchor, year, system) {
  const today = todayIst();
  const spans = system !== "fasli";
  const tile = (mah) => {
    const s = monthSpan(anchor, mah, year);
    const cls = ["goto-month", mah === 13 ? "wide" : "",
      mah === anchor.mah && year === anchor.year ? "current" : "",
      spans && today >= s.start && today <= s.end ? "now" : ""].filter(Boolean).join(" ");
    return `<button type="button" class="${cls}" data-goto-mah="${mah}">
      <b>${mah === 13 ? "Gatha days" : esc(rojForCell(MAH_NAMES_JS[mah - 1]))}</b>
      ${spans ? `<span>${esc(gregCell(s.start))} - ${esc(gregCell(s.end))}</span>` : ""}
    </button>`;
  };
  const from = monthSpan(anchor, 1, year).start.slice(0, 4);
  const to = monthSpan(anchor, 13, year).end.slice(0, 4);
  return `
    <div class="goto-year">
      <button type="button" class="ghost small" data-goto-year="-1" aria-label="Previous year">&lsaquo;</button>
      <div class="gy-label"><b>Y.Z. ${year}</b>${spans ? `<span>${from === to ? from : `${from} - ${to}`}</span>` : ""}</div>
      <button type="button" class="ghost small" data-goto-year="1" aria-label="Next year">&rsaquo;</button>
    </div>
    <div class="goto-months">${Array.from({ length: 13 }, (_, i) => tile(i + 1)).join("")}</div>`;
}

async function openGoTo(view, system, go) {
  const opts = state.calendarOptions || { roj: [], mah: [] };
  let anchor = null;
  try {
    anchor = await monthAnchor(view, system);
  } catch (e) { /* no months to show; a plain date still works, and the sheet says so */ }

  const sheet = openSheet({
    title: "Go to",
    html: `
      <div data-goto-months>${anchor ? "" : `<p class="field-msg">Couldn't load the months. Check your signal
        and try again - or go to a date below.</p>`}</div>
      <div data-goto-error role="alert"></div>
      <div class="names-group-label"><b>Or a date</b></div>
      <div class="goto-row">
        <input type="date" id="gotoDate" aria-label="Date" value="${esc(view.focus)}">
        <button type="button" class="small" id="gotoDateGo">Go</button>
      </div>
      ${opts.roj.length ? `<div class="names-group-label"><b>Or a Roj and Mah</b><span>next occurrence</span></div>
      <div class="goto-row">
        <select id="gotoRoj" aria-label="Roj">${
          opts.roj.map(o => `<option value="${o.id.replace("roj_", "")}">${esc(o.title)}</option>`).join("")}</select>
        <select id="gotoMah" aria-label="Mah">${
          opts.mah.map(o => `<option value="${o.id.replace("mah_", "")}">${esc(o.title)}</option>`).join("")}</select>
        <button type="button" class="small" id="gotoRojGo">Go</button>
      </div>` : ""}`,
  });
  const body = sheet.body;
  const fail = (msg) => {
    body.querySelector("[data-goto-error]").innerHTML = `<div class="error-banner">${esc(msg)}</div>`;
  };
  // Leaving for another view. A jump can be undone with Back; the sheet goes first
  // because the date picker inside New Event redraws in place and would keep it.
  const leave = (patch) => { sheet.close(); go(patch, { push: true }); };

  const paintMonths = (year) => {
    const box = body.querySelector("[data-goto-months]");
    box.innerHTML = goToMonthsHtml(anchor, year, system);
    box.querySelectorAll("[data-goto-year]").forEach(b => {
      b.onclick = () => paintMonths(year + Number(b.dataset.gotoYear));
    });
    box.querySelectorAll("[data-goto-mah]").forEach(b => {
      b.onclick = async () => {
        const tiles = box.querySelectorAll("button");
        tiles.forEach(t => { t.disabled = true; });
        try {
          const days = await parsiMonthDays(Number(b.dataset.gotoMah), year, system);
          leave({ mode: "month", focus: days[0].gregorian_date, parsiMonth: null });
        } catch (e) {
          tiles.forEach(t => { t.disabled = false; });
          fail("Couldn't open that month: " + e.message);
        }
      };
    });
  };
  if (anchor) paintMonths(anchor.year);

  body.querySelector("#gotoDateGo").onclick = () => {
    const d = body.querySelector("#gotoDate").value;
    if (!YMD.test(d)) return fail("Choose a date first.");
    leave({ mode: "day", focus: d, parsiMonth: null });
  };
  const rojGo = body.querySelector("#gotoRojGo");
  if (rojGo) {
    // The Roj/Mah path sends NO year: the server resolves the nearest occurrence.
    // (An old build asked for a YZ year and pre-filled it wrongly for every date
    // between January 1st and Navroze.)
    rojGo.onclick = async () => {
      rojGo.disabled = true;
      try {
        const p = await fromParsi(body.querySelector("#gotoRoj").value, body.querySelector("#gotoMah").value, system);
        leave({ mode: "day", focus: p.gregorian_date, parsiMonth: null });
      } catch (e) {
        rojGo.disabled = false;
        fail(e.message);
      }
    };
  }
}
