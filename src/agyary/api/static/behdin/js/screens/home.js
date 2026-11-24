"use strict";

/**
 * Home, the first screen: a greeting by first name, today's date and today's Parsi date, the next
 * prayer or event from the person's own calendar, their agyari, and cards that are honestly empty
 * for now. Those fill in as the app grows; no dates are promised.
 */

import { getToday, getMyCalendar, getMyAgyari } from "../api.js";
import { state } from "../state.js";
import { chrome, mainEl, setHeader, loading, wireRetry, loadFailedHtml } from "/mobed-app/js/ui.js";
import { navGuard, navigate } from "/mobed-app/js/router.js";
import { APP_NAME } from "../brand.js";
import { esc, firstName, gregShort, todayIst, weekdayOf, addDays, parsiWords, eventKindLabel, departedName } from "../util.js";
import { kindLabel } from "./agyari.js";

/** "Roj Hormuzd, Mah Aspandard", or a Gatha day's own name. */
function parsiLine(p) {
  if (p.is_gatha) return `${p.gatha_name || "Extra day"} (Gatha)`;
  return `Roj ${p.roj_name}, Mah ${p.mah_name}`;
}

function emptyCard(title, text) {
  return `<div class="card empty-card"><h2>${title}</h2><p class="meta">${text}</p></div>`;
}

/** The next prayer or event in the next 60 days. `undefined` means it could not be read. */
function nextCard(it) {
  if (it === undefined) return `<div class="card"><h2>Your next prayer</h2>${loadFailedHtml("your next prayer", { whole: false })}</div>`;
  if (!it) {
    return `<div class="card empty-card"><h2>Your next prayer</h2>
      <p class="meta">Nothing in the next 60 days. You can add your departed's prayers or an event in the Calendar.</p>
      <div style="margin-top:var(--space-3)"><button type="button" class="small secondary" id="homeNext">Open the Calendar</button></div></div>`;
  }
  const memorial = it.source === "memorial";
  return `<div class="card">
    <h2>${memorial ? "Your next prayer" : "Coming up"}</h2>
    <p style="margin:0"><b>${esc(memorial ? `${it.label} - ${departedName(it)}` : it.title)}</b></p>
    <p class="meta" style="margin:2px 0 0">${weekdayOf(it.date)} ${gregShort(it.date)}${it.parsi ? ", " + esc(parsiWords(it.parsi)) : ""}</p>
    ${memorial ? "" : `<p class="meta" style="margin:2px 0 0">${esc(eventKindLabel(it.kind))}</p>`}
    <div style="margin-top:var(--space-3)"><button type="button" class="small secondary" id="homeNext">Open the Calendar</button></div>
  </div>`;
}

function agyariCard(a) {
  if (a === undefined) return `<div class="card"><h2>My agyari</h2>${loadFailedHtml("your agyari", { whole: false })}</div>`;
  const body = a
    ? `<p style="margin:0"><b>${esc(a.name)}</b></p>
       <p class="meta" style="margin:2px 0 0">${esc([a.city, kindLabel(a.kind)].filter(Boolean).join(" · "))}</p>`
    : `<p class="meta">You have not chosen one yet.</p>`;
  return `<div class="card"><h2>My agyari</h2>${body}
    <div style="margin-top:var(--space-3)"><button type="button" class="small secondary" id="homeAgyari">${a ? "Change" : "Choose my agyari"}</button></div></div>`;
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
  const start = todayIst();
  const [todayRes, nextRes, agyariRes] = await Promise.allSettled([
    getToday(), getMyCalendar(start, addDays(start, 60)), getMyAgyari(),
  ]);
  if (!alive()) return;
  if (todayRes.status === "fulfilled") today = todayRes.value; else failed = true;
  const next = nextRes.status === "fulfilled" ? (nextRes.value.items[0] || null) : undefined;
  const agyari = agyariRes.status === "fulfilled" ? agyariRes.value.agyari : undefined;

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
    ${nextCard(next)}
    ${agyariCard(agyari)}
    ${emptyCard("Answers to your asks", FILLS_IN)}
    ${emptyCard("Notices", FILLS_IN)}`;
  wireRetry(mainEl, () => renderHome());
  const go = (id, hash) => { const b = document.getElementById(id); if (b) b.onclick = () => navigate(hash); };
  go("homeNext", "#/calendar");
  go("homeAgyari", "#/agyari");
}
