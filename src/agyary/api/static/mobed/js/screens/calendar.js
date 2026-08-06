"use strict";

/**
 * The Calendar screen and My Day, both driven by the shared calendar
 * component. The old Machi board is gone as a separate screen: its geh
 * slots are Day mode here, so a mobed sees services and machis on one
 * surface instead of switching tabs to find out what else is happening.
 */

import { myDay, machiBoard, pendingRequests, acceptBooking, declineBooking, convertDate } from "../api.js";
import { state, currentAgyary, GEH_NAME_BY_NUM } from "../state.js";
import { renderCalendar } from "../calendar.js";
import { chrome, mainEl, showFab, showError, keepScroll, markActiveTab, refreshHeader } from "../ui.js";
import { esc, istYmd, istTime, gregLabel, todayIst } from "../util.js";
import { navigate } from "../router.js";

/** Bookings assigned to me, as calendar items. Merged across every agyari I
 *  belong to - my day doesn't care about tenant boundaries, only we do. */
function bookingItems(rows) {
  return rows.map(b => ({
    kind: "booking",
    id: b.booking_id,
    agyaryId: b.agyary_id,
    day: istYmd(b.ceremony_datetime),
    time: istTime(b.ceremony_datetime),
    geh: null,
    label: b.service_name,
    sublabel: b.behdin_name || "-",
    tags: `<span class="tag">${esc(b.agyary_name)}</span>` +
      (b.is_offsite ? '<span class="tag">Offsite</span>' : ""),
  }));
}

/** Machis at this fire temple. Shared, not personal - every mobed there
 *  sees the same ones. */
function machiItems(rows) {
  return rows.map(m => ({
    kind: "machi",
    id: m.id,
    day: m.gregorian_date,
    time: null,
    geh: m.geh,
    label: `Machi (${m.purpose})`,
    sublabel: `${m.behdin_name || "-"} · ${GEH_NAME_BY_NUM[m.geh] || ""}`,
  }));
}

async function loadItems({ from, to }, { includeMachi = true } = {}) {
  const agyaryId = state.currentAgyaryId;
  const [bookings, machis] = await Promise.all([
    myDay().catch(() => []),
    // The window is required by the endpoint now, and this is the only
    // place it's called from - an unbounded fetch is no longer possible.
    includeMachi && agyaryId ? machiBoard(agyaryId, from, to).catch(() => []) : Promise.resolve([]),
  ]);
  const inRange = (d) => d >= from && d <= to;
  return [
    ...bookingItems(bookings).filter(i => inRange(i.day)),
    ...machiItems(machis).filter(i => inRange(i.day)),
  ];
}

function pendingCard(item) {
  return `<div class="card">
    <span class="tag">${esc(item.agyary_name)}</span>
    <h2>${esc(item.service_name)} · ${esc(item.behdin_name || "-")}</h2>
    <p class="meta">${istTime(item.ceremony_datetime)} ${gregLabel(istYmd(item.ceremony_datetime))}</p>
    <div class="row"><button data-accept="${item.booking_id}">Accept</button>
      <button class="secondary" data-decline="${item.booking_id}">Decline</button></div>
  </div>`;
}

/** My Day: today's work plus anything waiting on an accept/decline. Uses
 *  the same calendar component, opened on Day. */
export async function renderMyDay() {
  chrome(true);
  refreshHeader();
  markActiveTab("#/my-day");
  showFab(true, "Add an event");
  mainEl.innerHTML = `<div id="pending"></div><div id="cal"></div>`;

  let pending = [];
  try { pending = await pendingRequests(); } catch (e) { /* non-fatal */ }
  const pendingEl = document.getElementById("pending");
  if (pending.length) {
    pendingEl.innerHTML = `<h3 class="meta" style="margin:6px 0">Awaiting your response</h3>` +
      pending.map(pendingCard).join("");
    for (const item of pending) {
      pendingEl.querySelector(`[data-accept="${item.booking_id}"]`).onclick =
        () => resolveBooking(item.booking_id, "accept");
      pendingEl.querySelector(`[data-decline="${item.booking_id}"]`).onclick =
        () => resolveBooking(item.booking_id, "decline");
    }
  }

  state.calendar.focus = state.calendar.focus || todayIst();
  await draw(document.getElementById("cal"), renderMyDay);
}

/** The full calendar. Same component, same state - the only difference from
 *  My Day is that it doesn't lead with the pending list. */
export async function renderCalendarScreen() {
  chrome(true);
  refreshHeader();
  markActiveTab("#/calendar");
  showFab(true, "Add an event");
  mainEl.innerHTML = `<div id="cal"></div>`;
  state.calendar.focus = state.calendar.focus || todayIst();
  await draw(document.getElementById("cal"), renderCalendarScreen);
}

async function draw(container, rerender) {
  try {
    await renderCalendar(container, {
      view: state.calendar,
      agyaryId: state.currentAgyaryId,
      gehSlots: true,
      loadItems,
      rerender: () => draw(container, rerender),
      onItem: (kind, id) => {
        const agyaryId = state.currentAgyaryId;
        navigate(kind === "machi" ? `#/machi/${agyaryId}/${id}` : `#/booking/${agyaryId}/${id}`);
      },
      onBookGeh: (geh, ymd) => bookGeh(geh, ymd),
    });
  } catch (e) {
    showError(e.message);
  }
}

/**
 * Tapping an empty geh slot starts a new machi pre-filled for that slot.
 * Keeps the board's Gatha guard: machis are booked against a Roj/Mah slot,
 * and a Gatha day has no Roj to book against.
 */
async function bookGeh(geh, ymd) {
  const agyary = currentAgyary();
  const system = (agyary && agyary.calendar_system) || "shenshai";
  let conv;
  try {
    conv = await convertDate(ymd, system);
  } catch (e) {
    return showError(e.message);
  }
  if (conv.is_gatha) return showError("Machi cannot be booked on a Gatha day.");
  state.draft = {
    type: "machi",
    prefill: { roj: conv.roj, mah: conv.mah, year: conv.year, geh, gregorian: ymd },
  };
  navigate("#/event/new");
}

async function resolveBooking(id, action) {
  try {
    await (action === "accept" ? acceptBooking(id) : declineBooking(id));
    keepScroll(renderMyDay);
  } catch (e) {
    showError(e.message);
  }
}
