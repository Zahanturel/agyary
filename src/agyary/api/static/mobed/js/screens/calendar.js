"use strict";

/**
 * The calendar - the mobed app's home screen, and its only main screen.
 *
 * It shows this mobed's own events and nothing else: no agyari-wide machi
 * board, no other mobed's work. A machi they are responsible for is one of
 * their events, added the same way any event is.
 */

import { myDay, machiBoard, memorialFeed, memorialReminders, setEventPaid } from "../api.js";
import { state, GEH_NAME_BY_NUM, MACHI_PURPOSE_DISPLAY } from "../state.js";
import { renderCalendar, applyCalendarRoute, calendarHash } from "../calendar.js";
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
    short: b.service_name,
    sublabel: b.behdin_name || "-",
    tags: b.is_offsite ? '<span class="tag">Offsite</span>' : "",
    paid: !!b.paid,
    agyaryId: b.agyary_id,
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
    short: "Machi",
    sublabel: `${m.behdin_name || "-"} · ${GEH_NAME_BY_NUM[m.geh] || ""} Geh`,
    // Only the mobed's own machis can be ticked (the board is shared, the money is not).
    paid: m.mine === false ? undefined : !!m.paid,
  }));
}

// Which memorial an observance on the calendar belongs to, so a tap can open
// it on that observance. Rebuilt on every load.
const memorialOfObservance = new Map();

/** This mobed's memorial observances, and the closing notice on a memorial's
 *  last day. The notice is pinned to the top of its day by the calendar. */
function memorialItems(rows) {
  memorialOfObservance.clear();
  return rows.map(r => {
    if (r.kind === "memorial_closing") {
      return {
        kind: "memorial_closing",
        id: r.memorial_id,
        day: r.date,
        time: null,
        geh: null,
        label: "Memorial closes today",
        short: "Closes today",
        sublabel: r.text,
      };
    }
    memorialOfObservance.set(r.id, r.memorial_id);
    return {
      kind: "memorial",
      id: r.id,
      day: r.date,
      time: r.time,
      geh: null,
      label: `${r.label} · ${r.departed_name}`,
      short: r.label,
      sublabel: `${r.services.map(s => s.name).join(", ")} · ${r.behdin_name || "-"}`,
    };
  });
}

async function loadItems({ from, to }) {
  const agyaryId = state.currentAgyaryId;
  const [services, machis, memorials] = await Promise.all([
    myDay(from, to).catch(() => []),
    agyaryId ? machiBoard(agyaryId, from, to).catch(() => []) : Promise.resolve([]),
    agyaryId ? memorialFeed(agyaryId, from, to).catch(() => []) : Promise.resolve([]),
  ]);
  const inRange = (d) => d >= from && d <= to;
  return [
    ...serviceItems(services).filter(i => inRange(i.day)),
    ...machiItems(machis).filter(i => inRange(i.day)),
    ...memorialItems(memorials).filter(i => inRange(i.day)),
  ];
}

export async function renderCalendarScreen(params) {
  chrome(true);
  refreshHeader();
  showFab(true, "Add an event");
  // The view is in the URL; a bare or malformed one is normalised to the
  // last view (replacing, so Back never lands on the un-normalised entry).
  state.calendar.focus = state.calendar.focus || todayIst();
  const redirect = applyCalendarRoute(state.calendar, params);
  if (redirect) return navigate(redirect, { replace: true });
  mainEl.innerHTML = `<div id="calReminders"></div><div id="cal"></div>`;
  showReminderNotice();
  await draw();
}

const DONE = ["sent", "delivered", "read"];

/** A line above the calendar when there is a family to remind today or
 *  tomorrow - the thing a mobed would otherwise only find by knowing to look
 *  in the Behdins tab. Not shown for reminders that are going out on their own
 *  or already went. Silent on any failure: the calendar matters more. */
async function showReminderNotice() {
  try {
    const r = await memorialReminders(state.currentAgyaryId, 1);
    const todo = r.items.filter(o => !DONE.includes(o.sent_status) && !(o.auto && r.delivery === "live"));
    const slot = document.getElementById("calReminders");
    if (!slot || !todo.length) return;
    slot.innerHTML = `<div class="card">
      <div class="section-bar" id="calRemBar">
        <div class="sb-text"><b>${todo.length} reminder${todo.length === 1 ? "" : "s"} to send</b>
          <span>For today and tomorrow - tap to see who</span></div>
        <div class="sb-actions"><span class="chev">&rsaquo;</span></div>
      </div></div>`;
    document.getElementById("calRemBar").onclick = () => navigate("#/reminders");
  } catch (e) { /* the calendar does not depend on it */ }
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
      // The paid / unpaid tick on a day's events.
      onPay: (kind, id, paid) => setEventPaid(kind, state.currentAgyaryId, id, paid),
      onItem: (kind, id) => {
        const aid = state.currentAgyaryId;
        if (kind === "memorial_closing") return navigate(`#/memorial/${id}`);
        if (kind === "memorial") return navigate(`#/memorial/${memorialOfObservance.get(id)}/${id}`);
        navigate(kind === "machi" ? `#/machi/${aid}/${id}` : `#/booking/${aid}/${id}`);
      },
    });
  } catch (e) {
    showError(e.message);
  }
}
