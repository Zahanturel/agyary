"use strict";

/**
 * Machi board calendar — the agyary's 5-slot geh board.
 *
 * Day view shows all 5 gehs as visual blocks: booked (with behdin/purpose),
 * available (tap to book), or taken/elapsed. Week and month views use the
 * standard calendar item list.
 */

import { machiBoard, bookableGehs } from "../api.js";
import { state, GEHS, GEH_NAME_BY_NUM, MACHI_PURPOSE_DISPLAY } from "../state.js";
import { renderCalendar } from "../calendar.js";
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
    label: `Machi (${m.purpose})`,
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
    return machiItems(machis);
  } catch (e) {
    return [];
  }
}

function gehSlotHtml(items) {
  const byGeh = {};
  for (const m of dayMachis) byGeh[m.geh] = m;

  let html = '<div class="geh-slots">';
  for (const [num, name] of GEHS) {
    const m = byGeh[num];
    const available = dayGehs.includes(num);

    if (m) {
      const purpose = MACHI_PURPOSE_DISPLAY[m.purpose] || m.purpose;
      html += `<div class="geh-slot booked" data-cal-item="machi:${m.id}">
        <div class="geh-slot-head">${esc(name)}</div>
        <div class="geh-slot-purpose">${esc(purpose)}</div>
        <div class="geh-slot-behdin">${esc(m.behdin_name || "-")}</div>
      </div>`;
    } else if (available) {
      html += `<div class="geh-slot open" data-geh-book="${num}">
        <div class="geh-slot-head">${esc(name)}</div>
        <div class="geh-slot-open">Available</div>
      </div>`;
    } else {
      html += `<div class="geh-slot taken">
        <div class="geh-slot-head">${esc(name)}</div>
        <div class="geh-slot-taken">Taken</div>
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

export async function renderMachiCalendarScreen() {
  chrome(true);
  refreshHeader();
  showFab(true, "Add a machi");
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
      renderDay: gehSlotHtml,
      wireDay: wireSlots,
      onItem: (kind, id) => {
        const aid = state.currentAgyaryId;
        navigate(`#/machi/${aid}/${id}`);
      },
    });
  } catch (e) {
    showError(e.message);
  }
}
