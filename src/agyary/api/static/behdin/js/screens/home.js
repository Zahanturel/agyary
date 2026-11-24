"use strict";

/**
 * Home: today's date and Parsi day, the next prayer or event, the answers to the person's asks, and their
 * fire temple. Titles and buttons only; a card with nothing to say is left out.
 */

import { getToday, getMyCalendar, getMyAgyari, getMyAsks } from "../api.js";
import { chrome, mainEl, setHeader, loading, wireRetry, loadFailedHtml } from "/mobed-app/js/ui.js";
import { navGuard, navigate } from "/mobed-app/js/router.js";
import { APP_NAME } from "../brand.js";
import { esc, gregShort, todayIst, weekdayOf, addDays, parsiWords, eventKindLabel, departedName } from "../util.js";
import { kindLabel } from "./agyari.js";
import { startAsk } from "./ask.js";
import { chipHtml, askLine } from "./asks.js";

/** The next prayer or event in the next 60 days. `undefined` means it could not be read. */
function nextCard(it) {
  if (it === undefined) return `<div class="card"><h2>Next</h2>${loadFailedHtml("your next prayer", { whole: false })}</div>`;
  if (!it) return "";
  const memorial = it.source === "memorial";
  return `<div class="card">
    <h2>Next</h2>
    <div class="event${memorial ? " memorial" : ""}" id="homeNext">
      <div class="ev-row"><div class="ev-main">
        <div class="t">${esc(memorial ? `${it.label} · ${departedName(it)}` : it.title)}</div>
        <div class="s">${weekdayOf(it.date)} ${gregShort(it.date)}${it.parsi ? ", " + esc(parsiWords(it.parsi)) : ""}${memorial ? "" : " · " + esc(eventKindLabel(it.kind))}</div>
      </div></div>
    </div>
  </div>`;
}

function agyariCard(a) {
  if (a === undefined) return `<div class="card"><h2>My fire temple</h2>${loadFailedHtml("your fire temple", { whole: false })}</div>`;
  const body = a
    ? `<p style="margin:0"><b>${esc(a.name)}</b></p>
       <p class="meta" style="margin:2px 0 0">${esc([a.city, kindLabel(a.kind)].filter(Boolean).join(" · "))}</p>`
    : "";
  return `<div class="card"><h2>My fire temple</h2>${body}
    <div style="margin-top:var(--space-3)"><button type="button" class="small secondary" id="homeAgyari">${a ? "Change" : "Choose your fire temple"}</button></div></div>`;
}

/** The latest answers to the person's asks (accepted, turned down, or not answered). */
function answersCard(asks) {
  if (asks === undefined) return `<div class="card"><h2>Answers to your asks</h2>${loadFailedHtml("your asks", { whole: false })}</div>`;
  const answered = asks.filter((a) => a.status === "accepted" || a.status === "rejected" || a.no_answer)
    .sort((a, b) => String(b.decided_at || b.created_at).localeCompare(String(a.decided_at || a.created_at))).slice(0, 3);
  if (!asks.length) return "";
  return `<div class="card"><h2>Answers to your asks</h2>
    ${answered.map((a) => `<a class="home-ask" href="#/asks/${a.id}"><span>${esc(askLine(a))}</span>${chipHtml(a)}</a>`).join("")}
    <div style="margin-top:var(--space-3)"><button type="button" class="small secondary" id="homeAsks">My asks</button></div></div>`;
}

export async function renderHome() {
  chrome(true);
  setHeader(APP_NAME);
  loading();
  const alive = navGuard();

  let today = null;
  let failed = false;
  const start = todayIst();
  const [todayRes, nextRes, agyariRes, asksRes] = await Promise.allSettled([
    getToday(), getMyCalendar(start, addDays(start, 60)), getMyAgyari(), getMyAsks(),
  ]);
  if (!alive()) return;
  if (todayRes.status === "fulfilled") today = todayRes.value; else failed = true;
  const next = nextRes.status === "fulfilled" ? (nextRes.value.items[0] || null) : undefined;
  const mine = agyariRes.status === "fulfilled" ? agyariRes.value.agyari : undefined;
  const asks = asksRes.status === "fulfilled" ? asksRes.value.asks : undefined;

  // The date comes from the server (India's day); with no answer the phone's own clock, read in India.
  const ymd = today ? today.gregorian_date : todayIst();
  mainEl.innerHTML = `
    <div class="card" id="homeToday">
      <p class="meta" style="margin:0">${weekdayOf(ymd)}</p>
      <p class="today-date">${gregShort(ymd)}</p>
      ${today ? `<p class="today-parsi">${esc(parsiWords(today))} · Y.Z. ${esc(today.year)}</p>` : ""}
      ${failed ? loadFailedHtml("today's Parsi date", { whole: false }) : ""}
    </div>
    <button type="button" class="ask-big" id="homeAsk">Ask for a prayer</button>
    ${nextCard(next)}
    ${answersCard(asks)}
    ${agyariCard(mine)}`;
  wireRetry(mainEl, () => renderHome());
  const go = (id, hash) => { const b = document.getElementById(id); if (b) b.onclick = () => navigate(hash); };
  go("homeNext", "#/calendar");
  go("homeAgyari", "#/agyari");
  go("homeAsks", "#/asks");
  document.getElementById("homeAsk").onclick = () => startAsk({ back: "#/home" });
}
