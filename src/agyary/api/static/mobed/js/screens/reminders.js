"use strict";

/**
 * Reminders: which families this mobed should be reminded about soon.
 *
 * It is the mobed's own memorials only - like the behdin book and the
 * memorials themselves - so a colleague's families never appear here.
 * "Due" means inside the reminder lead time (the server's number, so this
 * screen and the future automatic sender can never disagree): the point at
 * which a family should hear about an observance.
 *
 * Tapping a row opens that observance on its memorial. "Remind on WhatsApp"
 * opens a chat with the family, with the message already written, from the
 * mobed's own WhatsApp - nothing is sent until they press Send there, and it
 * costs us nothing.
 */

import { memorialReminders } from "../api.js";
import { state } from "../state.js";
import {
  chrome, mainEl, showFab, showError, refreshHeader, loading, backBar,
} from "../ui.js";
import { esc, gregLabel } from "../util.js";
import { navigate, navGuard } from "../router.js";
import { parsiText } from "./memorial.js";

const HORIZON_DAYS = 14;

function whenText(daysAway) {
  if (daysAway === 0) return "Today";
  if (daysAway === 1) return "Tomorrow";
  return `In ${daysAway} days`;
}

const SENT = { sent: "Sent", delivered: "Delivered", read: "Read" };

function clockHour(h) {
  return `${h % 12 || 12} ${h < 12 ? "am" : "pm"}`;
}

/** What to show under a reminder: how it went, or how it will go. */
function actionHtml(o, data) {
  if (SENT[o.sent_status]) {
    return `<p class="meta" style="margin:8px 0 0">&#10003; ${SENT[o.sent_status]} to ${esc(o.behdin_name)} on WhatsApp.</p>`;
  }
  const button = `<div class="row tight" style="margin-top:8px">
      <a class="button small" data-wa href="${esc(o.wa_link)}" target="_blank" rel="noopener">Remind on WhatsApp</a>
    </div>`;
  if (o.sent_status === "failed") {
    return `<p class="meta" style="margin:8px 0 0">It could not be sent automatically.</p>${button}`;
  }
  // Only promise an automatic reminder when the server says the planner will
  // really send it (sending live, not paused, this account on, on the allowlist).
  if (o.auto && data.delivery === "live") {
    return `<p class="meta" style="margin:8px 0 0">Will be sent to ${esc(o.behdin_name)} automatically
      at about ${esc(clockHour(data.send_hour ?? 19))} the evening before.</p>`;
  }
  return button;
}

function rowHtml(o, data) {
  const svc = o.services.map(s => s.name).join(", ");
  return `<div class="obs" data-mid="${o.memorial_id}" data-oid="${o.id}">
    <div class="obs-head">
      <div class="obs-title"><b>${esc(o.label)} · ${esc(o.departed_name)}</b>
        <span>${esc(o.behdin_name)}${svc ? " · " + esc(svc) : ""}</span></div>
      <div class="obs-when"><b>${esc(whenText(o.days_away))}</b><br>${esc(gregLabel(o.date))}<br>${esc(parsiText(o))}</div>
    </div>
    ${actionHtml(o, data)}
  </div>`;
}

export async function renderReminders() {
  chrome(true);
  refreshHeader();
  showFab(false);
  loading();
  const alive = navGuard();

  let data;
  try {
    data = await memorialReminders(state.currentAgyaryId, HORIZON_DAYS);
  } catch (e) {
    if (!alive()) return;
    mainEl.innerHTML = "";
    return showError(e.message);
  }
  if (!alive()) return;

  const due = data.items.filter(o => o.due);
  const later = data.items.filter(o => !o.due);

  // One day ahead means today and tomorrow; say so rather than "within 1 days".
  const leadText = data.lead_days === 1 ? "the day before" : `${data.lead_days} days before`;
  const dueText = data.lead_days === 1 ? "today and tomorrow" : `within ${data.lead_days} days`;

  const group = (title, note, list) => list.length ? `
    <div class="card">
      <div class="names-group-label" style="margin-top:0"><b>${title}</b><span>${note}</span></div>
      ${list.map(o => rowHtml(o, data)).join("")}
    </div>` : "";

  mainEl.innerHTML = `
    <div class="card">
      ${backBar("Reminders")}
      <p class="meta" style="margin:4px 0 0">What is coming up in the next ${HORIZON_DAYS} days
        for the families you look after. Remind a family ${leadText} - not
        during the first ten days, when they are with you at the fire temple.</p>
      ${data.paused ? `<p class="meta" style="margin:8px 0 0"><b>Automatic sending is paused just now</b>,
        so please remind families yourself with the WhatsApp button.</p>` : ""}
    </div>
    ${data.items.length ? "" : `<div class="card">
      <p class="meta" style="margin:0">Nothing in the next ${HORIZON_DAYS} days.</p></div>`}
    ${group("Remind now", dueText, due)}
    ${group("Coming up", "", later)}`;

  mainEl.querySelectorAll("[data-oid]").forEach(el => {
    el.onclick = (e) => {
      // The WhatsApp link opens WhatsApp; it must not also open the memorial.
      if (e.target.closest("[data-wa]")) return;
      navigate(`#/memorial/${el.dataset.mid}/${el.dataset.oid}`);
    };
  });
}
