"use strict";

/**
 * The calendar - the mobed app's home screen, and its only main screen.
 *
 * It shows this mobed's own events and nothing else: no agyari-wide machi
 * board, no other mobed's work. A machi they are responsible for is one of
 * their events, added the same way any event is.
 */

import { myDay, machiBoard } from "../api.js";
import { state, GEH_NAME_BY_NUM, MACHI_PURPOSE_DISPLAY } from "../state.js";
import { renderCalendar } from "../calendar.js";
import { chrome, mainEl, showFab, showError, refreshHeader } from "../ui.js";
import { esc, istYmd, istTime, todayIst } from "../util.js";
import { navigate } from "../router.js";

/** Services this mobed is on, as calendar items. Merged across every fire
 *  temple they belong to - their day doesn't care about tenant boundaries,
 *  only the database does. */
function serviceItems(rows) {
  return rows.map(b => ({
    kind: "booking",
    id: b.booking_id,
    agyaryId: b.agyary_id,
    day: istYmd(b.ceremony_datetime),
    time: istTime(b.ceremony_datetime),
    geh: null,
    label: b.service_name,
    sublabel: b.behdin_name || "-",
    tags: b.is_offsite ? '<span class="tag">Offsite</span>' : "",
  }));
}

/** Machis this mobed entered themselves. Filtered by created_by, so this is
 *  "my machis", not the fire temple's board. */
function machiItems(rows) {
  return rows.map(m => ({
    kind: "machi",
    id: m.id,
    day: m.gregorian_date,
    time: null,
    geh: m.geh,
    // Not `Machi (${display})` - the display names carry their own
    // parenthetical gloss, which would nest.
    label: `Machi · ${MACHI_PURPOSE_DISPLAY[m.purpose] || m.purpose}`,
    sublabel: `${m.behdin_name || "-"} · ${GEH_NAME_BY_NUM[m.geh] || ""} Geh`,
  }));
}

async function loadItems({ from, to }) {
  const agyaryId = state.currentAgyaryId;
  const [services, machis] = await Promise.all([
    myDay(from, to).catch(() => []),
    agyaryId ? machiBoard(agyaryId, from, to).catch(() => []) : Promise.resolve([]),
  ]);
  const inRange = (d) => d >= from && d <= to;
  return [
    ...serviceItems(services).filter(i => inRange(i.day)),
    ...machiItems(machis).filter(i => inRange(i.day)),
  ];
}

export async function renderCalendarScreen() {
  chrome(true);
  refreshHeader();
  showFab(true, "Add an event");
  mainEl.innerHTML = `<div id="cal"></div>`;
  state.calendar.focus = state.calendar.focus || todayIst();
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
      onItem: (kind, id) => {
        const aid = state.currentAgyaryId;
        navigate(kind === "machi" ? `#/machi/${aid}/${id}` : `#/booking/${aid}/${id}`);
      },
    });
  } catch (e) {
    showError(e.message);
  }
}
