"use strict";

/**
 * The Calendar tab: the very same calendar as the other app (the shared module, with this app's own calendar
 * calls and state given to it). Everything a person keeps is an event on it: a departed's prayer dates, a
 * birthday, a navjote, an anniversary, a prayer a fire temple accepted. A tap on a day opens the day, a tap on an
 * event opens the event, and "+" starts a new one.
 */

import { getMyCalendar, getToday, parsiMonth, convertDay, fromParsi } from "../api.js";
import { state } from "../state.js";
import { chrome, mainEl, setHeader, showFab, showError } from "/mobed-app/js/ui.js";
import { navigate } from "/mobed-app/js/router.js";
import { renderCalendar, applyCalendarRoute, calendarHash, useCalendarDeps } from "/mobed-app/js/calendar.js";
import { APP_NAME } from "../brand.js";
import { todayIst, eventKindLabel, departedName, ROJ_NAMES, MAH_NAMES } from "../util.js";

state.calendarOptions = {
  roj: ROJ_NAMES.map((title, i) => ({ id: `roj_${i + 1}`, title })),
  mah: MAH_NAMES.map((title, i) => ({ id: `mah_${i + 1}`, title })),
};
useCalendarDeps({
  parsiMonth, convertDate: convertDay, fromParsi, state,
  primarySystem: () => state.system, visibleParsiSystems: () => [state.system],
});

let systemKnown = false;
// Which departed's page an event on the calendar belongs to, rebuilt on every load.
const memorialOf = new Map();

async function loadItems({ from, to }) {
  const got = await Promise.allSettled([getMyCalendar(from, to)]);
  const [own] = got.map((r) => (r.status === "fulfilled" ? r.value : null));
  memorialOf.clear();
  const items = [];
  for (const it of (own ? own.items : [])) {
    if (it.source === "memorial") {
      memorialOf.set(it.id, it.memorial_id);
      items.push({
        kind: "departed", id: it.id, day: it.date, time: null, geh: null,
        label: `${it.label} · ${departedName(it)}`, short: it.label, sublabel: "",
      });
    } else if (it.source === "request") {
      items.push({
        kind: "request", id: it.id, day: it.date, time: it.time || null, geh: it.geh || null,
        label: it.title, short: it.title, sublabel: "",
      });
    } else {
      items.push({
        kind: "event", id: it.id, day: it.date, time: null, geh: null,
        label: it.title, short: it.title, sublabel: eventKindLabel(it.kind),
      });
    }
  }
  items.incomplete = got.some((r) => r.status === "rejected");
  return items;
}

export async function renderCalendarScreen(params) {
  chrome(true);
  setHeader(APP_NAME);
  showFab(true, "Add an event");
  state.calendar.focus = state.calendar.focus || todayIst();
  const redirect = applyCalendarRoute(state.calendar, params);
  if (redirect) return navigate(redirect, { replace: true });
  mainEl.innerHTML = `<div id="cal"></div>`;
  if (!systemKnown) {
    try { state.system = (await getToday()).calendar || state.system; systemKnown = true; } catch (e) { /* the default */ }
  }
  await draw();
}

async function draw() {
  const container = document.getElementById("cal");
  if (!container) return;
  try {
    await renderCalendar(container, {
      view: state.calendar,
      loadItems,
      rerender: draw,
      viewHash: calendarHash,
      onItem: (kind, id) => {
        if (kind === "departed") return navigate(`#/departed/${memorialOf.get(id)}`);
        if (kind === "request") return navigate(`#/asks/${id}`);
        navigate(`#/event/${id}`);
      },
    });
  } catch (e) {
    showError(e.message);
  }
}
