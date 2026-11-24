"use strict";

/**
 * Home, the first screen: a greeting by first name, today's date and today's Parsi date, and three
 * cards that are honestly empty for now. They fill in as the app grows; no dates are promised.
 */

import { getToday } from "../api.js";
import { state } from "../state.js";
import { chrome, mainEl, setHeader, loading, wireRetry, loadFailedHtml } from "/mobed-app/js/ui.js";
import { navGuard } from "/mobed-app/js/router.js";
import { APP_NAME } from "../brand.js";
import { esc, firstName, gregShort, todayIst, weekdayOf } from "../util.js";

/** "Roj Hormuzd, Mah Aspandard", or a Gatha day's own name. */
function parsiLine(p) {
  if (p.is_gatha) return `${p.gatha_name || "Extra day"} (Gatha)`;
  return `Roj ${p.roj_name}, Mah ${p.mah_name}`;
}

function emptyCard(title, text) {
  return `<div class="card empty-card"><h2>${title}</h2><p class="meta">${text}</p></div>`;
}

const FILLS_IN = "Nothing here yet. This will fill in as the app grows.";

export async function renderHome() {
  chrome(true);
  setHeader(APP_NAME);
  loading();
  const alive = navGuard();

  const name = firstName(state.user && state.user.name);
  let today = null;
  let failed = false;
  try {
    today = await getToday();
  } catch (e) {
    failed = true;
  }
  if (!alive()) return;

  // The date comes from the server (India's day); with no answer the phone's own clock, read in India.
  const ymd = today ? today.gregorian_date : todayIst();
  const greeting = name ? `Namaste ${esc(name)}` : "Namaste";
  mainEl.innerHTML = `
    <p class="greeting">${greeting}</p>
    <div class="card" id="homeToday">
      <p class="meta" style="margin:0">${weekdayOf(ymd)}</p>
      <p class="today-date">${gregShort(ymd)}</p>
      ${today ? `<p class="today-parsi">${esc(parsiLine(today))}</p>
        <p class="meta" style="margin:4px 0 0">Y.Z. ${esc(today.year)}</p>` : ""}
      ${failed ? loadFailedHtml("today's Parsi date", { whole: false }) : ""}
    </div>
    ${emptyCard("Your next prayer", FILLS_IN)}
    ${emptyCard("Answers to your asks", FILLS_IN)}
    ${emptyCard("Notices", FILLS_IN)}`;
  wireRetry(mainEl, () => renderHome());
}
