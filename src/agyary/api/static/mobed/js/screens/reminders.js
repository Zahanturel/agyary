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

function rowHtml(o) {
  const svc = o.services.map(s => s.name).join(", ");
  return `<div class="obs" data-mid="${o.memorial_id}" data-oid="${o.id}">
    <div class="obs-head">
      <div class="obs-title"><b>${esc(o.label)} · ${esc(o.departed_name)}</b>
        <span>${esc(o.behdin_name)}${svc ? " · " + esc(svc) : ""}</span></div>
      <div class="obs-when"><b>${esc(whenText(o.days_away))}</b><br>${esc(gregLabel(o.date))}<br>${esc(parsiText(o))}</div>
    </div>
    <div class="row tight" style="margin-top:8px">
      <a class="button small" data-wa href="${esc(o.wa_link)}" target="_blank" rel="noopener">Remind on WhatsApp</a>
    </div>
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

  const group = (title, note, list) => list.length ? `
    <div class="card">
      <div class="names-group-label" style="margin-top:0"><b>${title}</b><span>${note}</span></div>
      ${list.map(rowHtml).join("")}
    </div>` : "";

  mainEl.innerHTML = `
    <div class="card">
      ${backBar("Reminders")}
      <p class="meta" style="margin:4px 0 0">Observances in the next ${HORIZON_DAYS} days
        for the families you look after. Remind a family from
        ${data.lead_days} days before.</p>
    </div>
    ${data.items.length ? "" : `<div class="card">
      <p class="meta" style="margin:0">Nothing in the next ${HORIZON_DAYS} days.</p></div>`}
    ${group("Remind now", `within ${data.lead_days} days`, due)}
    ${group("Coming up", "", later)}`;

  mainEl.querySelectorAll("[data-oid]").forEach(el => {
    el.onclick = (e) => {
      // The WhatsApp link opens WhatsApp; it must not also open the memorial.
      if (e.target.closest("[data-wa]")) return;
      navigate(`#/memorial/${el.dataset.mid}/${el.dataset.oid}`);
    };
  });
}
