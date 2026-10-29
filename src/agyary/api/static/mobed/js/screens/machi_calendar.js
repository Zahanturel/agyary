"use strict";

/**
 * The Machi tab - the five-geh board for the day, and the same calendar the
 * Calendar tab shows for week and month.
 *
 * Day view shows all 5 gehs as blocks: booked (with behdin/purpose), free (tap
 * to book), or already passed. It is the mobed's OWN board: a machi is private
 * to the mobed who made it (docs/DECISIONS.md D2), so a colleague's bookings
 * never appear and never make a geh look taken. (A panthaky, who has authority
 * over the temple, is sent every machi there by the server and sees them all.)
 *
 * It reads and writes the one shared calendar view (state.calendar), so
 * switching to the Calendar tab and back keeps the same day.
 */

import { machiBoard, bookableGehs } from "../api.js";
import { state, GEHS, GEH_NAME_BY_NUM, MACHI_PURPOSE_DISPLAY } from "../state.js";
import { renderCalendar, applyCalendarRoute, boardHash } from "../calendar.js";
import { chrome, mainEl, showFab, showError, refreshHeader } from "../ui.js";
import { esc, todayIst } from "../util.js";
import { navigate } from "../router.js";

let dayGehs = [];
let dayMachis = [];

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
    // What a month cell shows: which geh is booked, and for what - "Havan -
    // Patet". The board is about slots, so the geh is the first thing to read.
    // Aiwisruthrem carries a soft hyphen: at phone width it is wider than a
    // cell, and this breaks it at a syllable instead of mid-letter.
    short: `${(GEH_NAME_BY_NUM[m.geh] || "").replace("Aiwisruthrem", "Aiwis­ruthrem")} - ${
      m.purpose === "tandarosti" ? "Tandarosti" : "Patet"}`,
    sublabel: `${m.behdin_name || "-"} · ${GEH_NAME_BY_NUM[m.geh] || ""} Geh`,
  }));
}

async function loadItems({ from, to }) {
  const aid = state.currentAgyaryId;
  if (!aid) return [];
  try {
    const machis = await machiBoard(aid, from, to, { mine: false });
    dayMachis = machis;
    if (from === to) {
      try {
        const res = await bookableGehs(aid, from);
        dayGehs = res.bookable || res;
      } catch (e) {
        dayGehs = [];
      }
    }
    // Geh order, so a month cell lists Havan before Rapithwin whatever order
    // the rows arrived in.
    return machiItems(machis).sort((a, b) => a.geh - b.geh);
  } catch (e) {
    return [];
  }
}

function gehSlotHtml(items) {
  let html = '<div class="geh-slots">';
  for (const [num, name] of GEHS) {
    // Normally one. More than one only for a panthaky looking at a temple
    // where two mobeds hold the same geh - each is shown, none hidden.
    const here = dayMachis.filter(m => m.geh === num);
    const available = dayGehs.includes(num);

    if (here.length) {
      html += here.map(m => {
        const purpose = MACHI_PURPOSE_DISPLAY[m.purpose] || m.purpose;
        return `<div class="geh-slot booked" data-cal-item="machi:${m.id}">
        <div class="geh-slot-head">${esc(name)}</div>
        <div class="geh-slot-purpose">${esc(purpose)}</div>
        <div class="geh-slot-behdin">${esc(m.behdin_name || "-")}</div>
      </div>`;
      }).join("");
    } else if (available) {
      html += `<div class="geh-slot open" data-geh-book="${num}">
        <div class="geh-slot-head">${esc(name)}</div>
        <div class="geh-slot-open">Available</div>
      </div>`;
    } else {
      // Not free and nothing of yours in it: the geh's time has gone.
      html += `<div class="geh-slot taken">
        <div class="geh-slot-head">${esc(name)}</div>
        <div class="geh-slot-taken">Passed</div>
      </div>`;
    }
  }
  return html + "</div>";
}

function wireSlots(container) {
  container.querySelectorAll("[data-geh-book]").forEach(el => {
    el.onclick = () => {
      const geh = Number(el.dataset.gehBook);
      state.draft = { prefill: { gregorian: state.calendar.focus, geh } };
      navigate("#/machi/new");
    };
  });
}

/** The + on this tab adds a machi, on the day being looked at. */
function addMachi() {
  state.draft = state.calendar.mode === "day" && state.calendar.focus
    ? { prefill: { gregorian: state.calendar.focus } }
    : null;
  navigate("#/machi/new");
}

export async function renderMachiCalendarScreen(params) {
  chrome(true);
  refreshHeader();
  showFab(true, "Add a machi", addMachi);
  state.calendar.focus = state.calendar.focus || todayIst();
  const redirect = applyCalendarRoute(state.calendar, params, "board");
  if (redirect) return navigate(redirect, { replace: true });
  mainEl.innerHTML = `<div id="cal"></div>`;
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
      viewHash: boardHash,
      // Up to five gehs can be booked on a day, and which ones is the point of
      // the board, so a cell lists them all rather than "+3 more".
      monthChips: 5,
      monthChipWrap: true,
      renderDay: gehSlotHtml,
      wireDay: wireSlots,
      onItem: (kind, id) => {
        navigate(`#/machi/${state.currentAgyaryId}/${id}`);
      },
    });
  } catch (e) {
    showError(e.message);
  }
}
