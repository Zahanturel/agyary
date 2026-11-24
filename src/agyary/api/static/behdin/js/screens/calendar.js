"use strict";

/** The Calendar tab. A placeholder for now: the calendar itself is built in the next release (R4.1). */

import { chrome, mainEl, setHeader } from "/mobed-app/js/ui.js";
import { APP_NAME } from "../brand.js";

export function renderCalendar() {
  chrome(true);
  setHeader(APP_NAME);
  mainEl.innerHTML = `
    <div class="card empty-card"><h2>Calendar</h2>
      <p class="meta">The calendar is not here yet. It will appear in this tab as the app grows.</p></div>`;
}
