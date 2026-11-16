"use strict";

/**
 * One memorial: the departed person, where the schedule has got to, and every
 * observance in it.
 *
 * Every observance starts with the same services (chosen when the memorial
 * was made) and any one of them can be changed on its own here - a family
 * adds Farokshi to the 10th, say, without touching the rest. Time is optional
 * and usually left blank; the note is for whatever the mobed wants to remember
 * about that day. A date can also be moved to another day, or removed; the
 * whole memorial is changed on its own screen (memorial_edit.js).
 *
 * Opened from the calendar, it lands on the observance that was tapped.
 */

import {
  getMemorial, getBehdin, updateObservance, deleteMemorial, listServices, setObservancePaid, setMemorialPaid,
  removeObservance,
} from "../api.js";
import { state } from "../state.js";
import {
  chrome, mainEl, showFab, showError, showInfo, flashInfo, refreshHeader, loading, backBar,
} from "../ui.js";
import { esc, gregLabel, todayIst, parsiLabel } from "../util.js";
import { back, navigate, navGuard } from "../router.js";
import { shareCardHtml, wireShareCard } from "../memorial_share.js";
import { serviceToggleHtml, wireServiceToggles, selectedServiceIds } from "../service_toggle.js";
import { payChipHtml, flipPaidChip } from "../paid_chip.js";

// The services a memorial is made of. If a fire temple has renamed or removed
// all of them, fall back to everything it offers rather than showing nothing.
const PRAYER_NAMES = ["afringan", "farokshi", "baaj", "satum", "jashan", "jore nu"];

/** The services offered for a memorial at this fire temple, in catalog order. */
export async function prayerServices(aid) {
  if (!state.formOptionsCache[aid]) {
    const all = await listServices(aid);
    state.formOptionsCache[aid] = { services: all.filter(s => s.is_active) };
  }
  const all = state.formOptionsCache[aid].services;
  // In the order the family would say them, not the catalog's.
  const rank = (s) => PRAYER_NAMES.indexOf(s.name.trim().toLowerCase());
  const prayers = all.filter(s => rank(s) >= 0).sort((a, b) => rank(a) - rank(b));
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

const OPENING_TEXT = { days_1_to_10: "Days 1 to 10", tenth_only: "10th day only", days_5_to_9: "Days 5 to 9" };

function choicesText(m) {
  const parts = OPENING_TEXT[m.opening] ? [OPENING_TEXT[m.opening]] : [];
  if (m.day_counts && m.day_counts.length) parts.push(`${m.day_counts.map(d => d + "th").join(", ")} day`);
  if (m.monthly_months) parts.push(`monthly for ${m.monthly_months} month${m.monthly_months > 1 ? "s" : ""}`);
  if (m.fravardin_roj_months) {
    parts.push(`Roj Fravardin monthly for ${m.fravardin_roj_months} month${m.fravardin_roj_months > 1 ? "s" : ""}`);
  }
  if (m.yearly_years) parts.push(`yearly for ${m.yearly_years} year${m.yearly_years > 1 ? "s" : ""}`);
  if (m.parabs) {
    const which = m.parabs === "all" ? "all Parabs" : "Fravardin and Tir Parabs";
    parts.push(m.parab_count ? `${m.parab_count} of the ${which}`
      : `${which} for ${m.parab_years} year${m.parab_years > 1 ? "s" : ""}`);
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
        ${behdin ? `For <a href="#/behdins/${m.customer_id}">${esc(behdin.name)}</a> · ` : ""}${m.long_ago
          ? `passed away more than a year ago (${esc(parsiText({ ...m.death, gatha_index: m.death.mah === 13 ? m.death.roj : null }))})`
          : `died ${esc(gregLabel(m.death_date))}`}</p>
      <p class="meta" style="margin:4px 0 0">${esc(choicesText(m))} · ${esc(m.calendar[0].toUpperCase() + m.calendar.slice(1))} calendar</p>
      <p style="margin:12px 0 0;font-size:var(--text-sm)"><b id="memStatus"></b></p>
      <div class="progress"><div id="memProgress"></div></div>
      <div class="row tight" style="margin-top:12px;align-items:center;justify-content:space-between">
        <span class="meta" id="paidCount"></span>
        <button class="ghost small" id="paidAll" type="button"></button>
      </div>
      <button class="secondary small" id="memEdit" type="button" style="margin-top:12px">Edit memorial</button>
    </div>

    <div class="card">
      <h2>Observances</h2>
      <p class="meta" style="margin:4px 0 12px">Tap Edit on a date to move it to another day, change its prayers,
        time or note, or remove it.</p>
      <div id="obsList"></div>
    </div>

    ${shareCardHtml()}

    <div class="card">
      <button class="ghost small" id="memDeleteOpen">Delete memorial</button>
      <div id="memDeleteConfirm" style="margin-top:12px"></div>
    </div>`;

  wireShareCard(document.getElementById("shareCard"), aid, m);
  document.getElementById("memEdit").onclick = () => navigate(`#/memorial/${mid}/edit`);

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
          <span>${esc(svc)}${o.time ? ` · ${esc(o.time)}` : ""}${o.notes ? " · note" : ""}${o.moved_by_hand
            ? " · moved by you" : ""}</span></div>
        <div class="obs-when">${esc(gregLabel(o.date))}<br>${esc(parsiText(o))}</div>
        ${payChipHtml("memorial", o.id, !!o.paid)}
        <button type="button" class="ghost small obs-edit-btn" aria-expanded="${o.id === openId}"
          aria-label="${o.id === openId ? "Close" : "Edit"} ${esc(o.label)} on ${esc(gregLabel(o.date))}">${
          o.id === openId ? "Close" : "Edit"}</button>
      </div>
      ${o.id === openId ? editorHtml(o) : ""}
    </div>`;
  }

  function editorHtml(o) {
    const have = new Set(o.service_ids);
    return `<div class="obs-edit">
      <label for="obsDate">Day</label>
      <input type="date" id="obsDate" value="${esc(o.date)}">
      <p class="meta" id="obsDateParsi" style="margin:6px 0 0"></p>
      ${o.moved_by_hand ? `<p class="meta" style="margin:6px 0 0">You moved this date off its usual day. Editing the
        memorial leaves it here.</p>
        <button type="button" class="ghost small" id="obsUsual" style="margin-top:6px">Back to its usual day</button>` : ""}
      <label>Prayers on this day <span class="meta">(tap to turn on or off)</span></label>
      <div class="chip-row">${services.map(s => serviceToggleHtml(s.id, s.name, have.has(s.id))).join("")}</div>
      <label for="obsTime">Time <span class="meta">(optional)</span></label>
      <input type="time" id="obsTime" value="${esc(o.time || "")}">
      <label for="obsNote">Note <span class="meta">(optional)</span></label>
      <input type="text" id="obsNote" value="${esc(o.notes || "")}" autocomplete="off">
      <div class="row tight" style="margin-top:12px;flex-wrap:wrap">
        <button class="small" id="obsSave" type="button">Save</button>
        <button class="ghost small" id="obsCancel" type="button">Close</button>
        <button class="ghost small danger-outline" id="obsRemove" type="button" style="margin-left:auto">Remove this date</button>
      </div>
      <div id="obsRemoveConfirm"></div></div>`;
  }

  // "3 of 36 dates paid", and one button that ticks (or clears) every date.
  function paintPaid() {
    const n = m.observances.filter(o => o.paid).length;
    document.getElementById("paidCount").textContent = `${n} of ${m.observances.length} dates paid`;
    document.getElementById("paidAll").textContent = n === m.observances.length ? "Mark all not paid" : "Mark all paid";
  }
  document.getElementById("paidAll").onclick = async (ev) => {
    const btn = ev.currentTarget;
    const want = m.observances.some(o => !o.paid);   // anything unpaid: tick the lot
    btn.disabled = true;
    try {
      await setMemorialPaid(aid, mid, want);
      m.observances.forEach(o => { o.paid = want; });
      paint();
    } catch (e) {
      showError("Couldn't save that: " + e.message);
    } finally {
      btn.disabled = false;
    }
  };

  function paintTop() {
    document.getElementById("memStatus").textContent = statusText(m);
    document.getElementById("memProgress").style.width = `${m.total ? Math.round(100 * m.done / m.total) : 0}%`;
    paintPaid();
  }

  /** After a date was moved or removed: read the memorial again, since its
   *  order, its next date and its last date may all have changed. */
  async function reload(message) {
    try {
      m = await getMemorial(aid, mid);
    } catch (e) {
      return showError(e.message);
    }
    if (!alive()) return;
    paint();
    if (message) showInfo(message);
  }

  function paint() {
    paintTop();
    listEl.innerHTML = m.observances.map(rowHtml).join("");
    listEl.querySelectorAll(".pay-chip").forEach(chip => {
      chip.onclick = (e) => {
        e.stopPropagation();   // the chip does not open the date's editor
        const oid = Number(chip.dataset.pay.split(":")[1]);
        flipPaidChip(chip, (paid) => setObservancePaid(aid, mid, oid, paid), (paid) => {
          const o = m.observances.find(x => x.id === oid);
          if (o) o.paid = paid;
          paintPaid();
        });
      };
    });
    listEl.querySelectorAll("[data-obs-toggle]").forEach(el => {
      el.onclick = () => {   // the row, or its Edit button
        const n = Number(el.dataset.obsToggle);
        openId = openId === n ? null : n;
        paint();
      };
    });
    const row = openId && m.observances.find(o => o.id === openId);
    if (!row) return;
    wireServiceToggles(listEl);

    // The Roj and Mah of the day chosen, so a move is checked before it is saved.
    const dateEl = document.getElementById("obsDate");
    const showDay = async () => {
      const note = document.getElementById("obsDateParsi");
      if (!dateEl.value) { note.textContent = ""; return; }
      const label = await parsiLabel(dateEl.value, m.calendar);
      if (note.isConnected) {
        note.textContent = dateEl.value === row.date ? label : `Moves to ${gregLabel(dateEl.value)} - ${label}`;
      }
    };
    dateEl.onchange = showDay;
    showDay();

    document.getElementById("obsCancel").onclick = () => { openId = null; paint(); };
    document.getElementById("obsSave").onclick = async () => {
      const ids = selectedServiceIds(listEl);
      if (!ids.length) return showError("Keep at least one prayer on this day.");
      const to = dateEl.value;
      if (!to) return showError("Choose the day for this date.");
      const btn = document.getElementById("obsSave");
      btn.disabled = true;
      // An empty string clears the time or note; sending the field as it
      // stands is what lets one save cover every edit.
      const body = {
        service_ids: ids,
        time: document.getElementById("obsTime").value,
        notes: document.getElementById("obsNote").value,
      };
      const moving = to !== row.date;
      if (moving) body.move_to = to;
      let updated;
      try {
        updated = await updateObservance(aid, mid, row.id, body);
      } catch (e) {
        btn.disabled = false;
        return showError(e.message);
      }
      openId = null;
      if (moving) return reload(`${row.label} moved to ${gregLabel(to)}.`);
      m.observances = m.observances.map(o => (o.id === row.id ? updated : o));
      paint();
      showInfo("Saved.");
    };

    const usual = document.getElementById("obsUsual");
    if (usual) {
      usual.onclick = async () => {
        usual.disabled = true;
        try {
          const moved = await updateObservance(aid, mid, row.id, { back_to_usual_day: true });
          openId = null;
          reload(`${row.label} is back on its usual day, ${gregLabel(moved.date)}.`);
        } catch (e) {
          usual.disabled = false;
          showError(e.message);
        }
      };
    }

    document.getElementById("obsRemove").onclick = () => {
      const box = document.getElementById("obsRemoveConfirm");
      if (m.observances.length <= 1) {
        box.innerHTML = `<p class="field-msg">This is the memorial's only date. To take it off, delete the memorial
          at the bottom of this page.</p>`;
        return;
      }
      box.innerHTML = `<div class="row-confirm row-pending" style="margin-top:8px;flex-wrap:wrap">
          <span>Remove ${esc(row.label)} on ${esc(gregLabel(row.date))} from this memorial?</span>
          <span class="row"><button type="button" class="ghost small" id="obsRemoveKeep">Keep</button>
          <button type="button" class="danger small" id="obsRemoveYes">Remove</button></span></div>
        <p class="meta" style="margin:6px 0 0">It stays off when the memorial is edited later. Edit memorial can
          put it back.</p>`;
      document.getElementById("obsRemoveKeep").onclick = () => { box.innerHTML = ""; };
      document.getElementById("obsRemoveYes").onclick = async (ev) => {
        const yes = ev.currentTarget;
        yes.disabled = true;
        try {
          await removeObservance(aid, mid, row.id);
        } catch (e) {
          yes.disabled = false;
          return showError("Couldn't remove it: " + e.message);
        }
        openId = null;
        reload(`${row.label} on ${gregLabel(row.date)} was removed.`);
      };
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

