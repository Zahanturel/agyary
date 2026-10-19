"use strict";

/**
 * One memorial: the departed person, where the schedule has got to, and every
 * observance in it.
 *
 * Every observance starts with the same services (chosen when the memorial
 * was made) and any one of them can be changed on its own here - a family
 * adds Farokshi to the 10th, say, without touching the rest. Time is optional
 * and usually left blank; the note is for whatever the mobed wants to remember
 * about that day.
 *
 * Opened from the calendar, it lands on the observance that was tapped.
 */

import {
  getMemorial, getBehdin, updateObservance, deleteMemorial, listServices,
} from "../api.js";
import { state } from "../state.js";
import {
  chrome, mainEl, showFab, showError, showInfo, flashInfo, refreshHeader, loading, backBar,
} from "../ui.js";
import { esc, gregLabel, todayIst } from "../util.js";
import { back, navGuard } from "../router.js";

// The services a memorial is made of. If a fire temple has renamed or removed
// all of them, fall back to everything it offers rather than showing nothing.
const PRAYER_NAMES = ["afringan", "farokshi", "baaj", "satum"];

/** The services offered for a memorial at this fire temple, in catalog order. */
export async function prayerServices(aid) {
  if (!state.formOptionsCache[aid]) {
    const all = await listServices(aid);
    state.formOptionsCache[aid] = { services: all.filter(s => s.is_active) };
  }
  const all = state.formOptionsCache[aid].services;
  const prayers = all.filter(s => PRAYER_NAMES.includes(s.name.trim().toLowerCase()));
  return prayers.length ? prayers : all.filter(s => s.name.trim().toLowerCase() !== "machi");
}

function optionTitle(list, n) {
  const hit = (list || []).find(o => Number(o.id.split("_")[1]) === Number(n));
  return hit ? hit.title : String(n);
}

/** "Roj Bahman, Mah Fravardin" - or "Gatha 2" for a day in the Gatha days.
 *  Read in the fire temple's own calendar, which is how the schedule was
 *  counted. */
export function parsiText(o) {
  if (o.gatha_index) return `Gatha ${o.gatha_index}`;
  const opts = state.calendarOptions;
  if (!opts) return `Roj ${o.roj}, Mah ${o.mah}`;
  return `Roj ${optionTitle(opts.roj, o.roj)}, Mah ${optionTitle(opts.mah, o.mah)}`;
}

const OPENING_TEXT = { days_1_to_10: "Days 1 to 10", tenth_only: "10th day only" };

function choicesText(m) {
  const parts = OPENING_TEXT[m.opening] ? [OPENING_TEXT[m.opening]] : [];
  if (m.day_counts && m.day_counts.length) parts.push(`${m.day_counts.map(d => d + "th").join(", ")} day`);
  if (m.monthly_months) parts.push(`monthly for ${m.monthly_months} month${m.monthly_months > 1 ? "s" : ""}`);
  if (m.fravardin_roj_months) {
    parts.push(`Roj Fravardin monthly for ${m.fravardin_roj_months} month${m.fravardin_roj_months > 1 ? "s" : ""}`);
  }
  if (m.yearly_years) parts.push(`yearly for ${m.yearly_years} year${m.yearly_years > 1 ? "s" : ""}`);
  if (m.parabs) {
    parts.push(`${m.parabs === "all" ? "all Parabs" : "Fravardin and Tir Parabs"} for ${m.parab_years} year${m.parab_years > 1 ? "s" : ""}`);
  }
  if (m.birthday) {
    parts.push(`birthday for ${m.birthday.years} year${m.birthday.years > 1 ? "s" : ""}`);
  }
  return parts.join(" · ");
}

function statusText(m) {
  if (m.status === "completed") return "Completed - every observance has passed.";
  const next = m.next ? `Next: ${m.next.label}, ${gregLabel(m.next.date)}` : "";
  return `${m.done} of ${m.total} done. ${next}`;
}

export async function renderMemorial({ id, oid }) {
  chrome(true);
  refreshHeader();
  showFab(false);
  loading();
  const alive = navGuard();

  const aid = state.currentAgyaryId;
  const mid = Number(id);
  let m, behdin = null, services = [];
  try {
    m = await getMemorial(aid, mid);
    [behdin, services] = await Promise.all([
      getBehdin(aid, m.customer_id).catch(() => null),
      prayerServices(aid).catch(() => []),
    ]);
  } catch (e) {
    if (!alive()) return;
    mainEl.innerHTML = "";
    return showError(e.status === 404 ? "That memorial isn't on file." : e.message);
  }
  if (!alive()) return;

  const today = todayIst();
  let openId = oid ? Number(oid) : null;

  mainEl.innerHTML = `
    <div class="card">
      ${backBar(esc(m.departed_name))}
      <p class="meta" style="margin:4px 0 0">
        ${behdin ? `For <a href="#/behdins/${m.customer_id}">${esc(behdin.name)}</a> · ` : ""}died
        ${esc(gregLabel(m.death_date))}</p>
      <p class="meta" style="margin:4px 0 0">${esc(choicesText(m))} · ${esc(m.calendar[0].toUpperCase() + m.calendar.slice(1))} calendar</p>
      <p style="margin:12px 0 0;font-size:var(--text-sm)"><b>${esc(statusText(m))}</b></p>
      <div class="progress"><div style="width:${m.total ? Math.round(100 * m.done / m.total) : 0}%"></div></div>
    </div>

    <div class="card">
      <h2>Observances</h2>
      <div id="obsList"></div>
    </div>

    <div class="card">
      <button class="ghost small" id="memDeleteOpen">Delete memorial</button>
      <div id="memDeleteConfirm" style="margin-top:12px"></div>
    </div>`;

  const listEl = document.getElementById("obsList");

  function rowHtml(o, index) {
    const isNext = m.next && m.next.id === o.id;
    const isLast = index === m.observances.length - 1;
    const cls = ["obs", o.date < today ? "past" : "", isNext ? "next" : "", isLast ? "last" : "",
      o.id === openId ? "focus" : ""].filter(Boolean).join(" ");
    const svc = o.services.map(s => s.name).join(", ");
    return `<div class="${cls}" data-obs="${o.id}">
      <div class="obs-head" data-obs-toggle="${o.id}">
        <div class="obs-title"><b>${esc(o.label)}</b>
          <span>${esc(svc)}${o.time ? ` · ${esc(o.time)}` : ""}${o.notes ? " · note" : ""}</span></div>
        <div class="obs-when">${esc(gregLabel(o.date))}<br>${esc(parsiText(o))}</div>
      </div>
      ${o.id === openId ? editorHtml(o) : ""}
    </div>`;
  }

  function editorHtml(o) {
    const have = new Set(o.service_ids);
    return `<div class="obs-edit">
      <label>Services</label>
      <div class="chip-row">${services.map(s => `
        <label class="chip ${have.has(s.id) ? "on" : ""}" style="margin:0">
          <input type="checkbox" data-svc="${s.id}" ${have.has(s.id) ? "checked" : ""}>${esc(s.name)}</label>`).join("")}
      </div>
      <label>Time <span class="meta">(optional)</span></label>
      <input type="time" id="obsTime" value="${esc(o.time || "")}">
      <label>Note <span class="meta">(optional)</span></label>
      <input type="text" id="obsNote" value="${esc(o.notes || "")}" autocomplete="off">
      <div class="row tight" style="margin-top:12px">
        <button class="small" id="obsSave">Save</button>
        <button class="ghost small" id="obsCancel">Close</button>
      </div></div>`;
  }

  function paint() {
    listEl.innerHTML = m.observances.map(rowHtml).join("");
    listEl.querySelectorAll("[data-obs-toggle]").forEach(el => {
      el.onclick = () => {
        const n = Number(el.dataset.obsToggle);
        openId = openId === n ? null : n;
        paint();
      };
    });
    const row = openId && m.observances.find(o => o.id === openId);
    if (!row) return;
    listEl.querySelectorAll("[data-svc]").forEach(cb => {
      cb.onchange = () => cb.closest(".chip").classList.toggle("on", cb.checked);
    });
    document.getElementById("obsCancel").onclick = () => { openId = null; paint(); };
    document.getElementById("obsSave").onclick = async () => {
      const ids = Array.from(listEl.querySelectorAll("[data-svc]"))
        .filter(cb => cb.checked).map(cb => Number(cb.dataset.svc));
      if (!ids.length) return showError("Keep at least one service on this observance.");
      const btn = document.getElementById("obsSave");
      btn.disabled = true;
      try {
        // An empty string clears the time or note; sending the field as it
        // stands is what lets one save cover all three edits.
        const updated = await updateObservance(aid, mid, row.id, {
          service_ids: ids,
          time: document.getElementById("obsTime").value,
          notes: document.getElementById("obsNote").value,
        });
        m.observances = m.observances.map(o => (o.id === row.id ? updated : o));
        openId = null;
        paint();
        showInfo("Saved.");
      } catch (e) {
        btn.disabled = false;
        showError(e.message);
      }
    };
  }
  paint();
  if (openId) {
    const el = listEl.querySelector(`[data-obs="${openId}"]`);
    if (el) el.scrollIntoView({ block: "center" });
  }

  document.getElementById("memDeleteOpen").onclick = () => {
    const panel = document.getElementById("memDeleteConfirm");
    panel.innerHTML = `
      <p class="meta">Delete the memorial for ${esc(m.departed_name)}? All ${m.total} of its
        observances are removed from your calendar. This can't be undone.</p>
      <div class="row tight">
        <button class="danger small" id="memDelOne">Delete</button>
        <button class="ghost small" id="memDelCancel">Cancel</button>
      </div>`;
    document.getElementById("memDelCancel").onclick = () => { panel.innerHTML = ""; };
    document.getElementById("memDelOne").onclick = async () => {
      try {
        await deleteMemorial(aid, mid);
      } catch (e) {
        return showError("Couldn't delete: " + e.message);
      }
      flashInfo(`Memorial for ${m.departed_name} deleted.`);
      back(`#/behdins/${m.customer_id}`);
    };
  };
}
