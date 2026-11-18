"use strict";

/**
 * A Doongerwadi manager records a death and asks a fire temple for the prayers
 * (DECISIONS D10, D5; Phase 2 Step 4).
 *
 *  - The record form: the name as it is prayed, the death by its date or by
 *    its Roj and Mah (the other is worked out by the server and shown, to
 *    confirm), four days or one, bungli, Geh-saarnu, Uthamna, mobeds wanted,
 *    the family's preferred fire temple, and one family contact.
 *  - The record: everything on it, its requests, and Send / Withdraw / Edit.
 *    Once a fire temple accepts (Step 5): who accepted and where, and - only
 *    if they ticked "Share my name and number" - their number with Call and
 *    WhatsApp (the manager's own WhatsApp, a short message ready).
 *  - Choosing the fire temple: Suggested (nearest first) or Search all, then
 *    the tick that the family agreed, and Send.
 *
 * Nothing about the cause of death, age, address, certificate, ID numbers or
 * how the body goes is asked.
 */

import {
  calendarOptions, managerDeathDay, managerRecord, managerCreateRecord, managerUpdateRecord,
  managerSuggested, managerSearchAgyaries, managerSend, managerWithdraw,
} from "../api.js";
import { state } from "../state.js";
import {
  chrome, mainEl, showFab, showError, showInfo, refreshHeader, loading, screenFailed, toTop, openSheet, flashInfo,
} from "../ui.js";
import { esc, gregLabel, istHm, istYmd, todayIst, phoneField, readPhone, setPhoneField, MAH_NAMES_JS } from "../util.js";
import { navigate, navGuard, returnTo } from "../router.js";
import { flagProblems, clearProblems } from "../fielderrors.js";

const TITLES = [["behdin", "Behdin"], ["ervad", "Ervad"], ["osta", "Osta"], ["osti", "Osti"]];
const GATHAS = ["Ahunavad", "Ushtavad", "Spentamad", "Vohukhshathra", "Vahishtoisht"];
// The Geh-saarnu is prayed in daylight only.
const DAY_GEHS = [[1, "Havan"], [2, "Rapithwin"], [3, "Uziran"]];
const REACH = {
  panthaky: { text: "Panthaky in the app", cls: "role" },
  mobeds: { text: "Mobeds only", cls: "" },
  nobody: { text: "Not in the app yet", cls: "grey" },
};

// --- Shared words ---------------------------------------------------------------

function when(iso) {
  const day = istYmd(iso);
  return day === todayIst() ? istHm(iso) : `${gregLabel(day)}, ${istHm(iso)}`;
}

/** One request's state, in words: "Waiting at X since 10:42" and the like. */
export function requestState(q) {
  const where = q.agyari ? q.agyari.name : "the fire temple";
  if (q.status === "waiting") return `Waiting at ${where} since ${when(q.sent_at)}`;
  if (q.status === "accepted" || q.status === "taken") {
    return q.accepted_by ? `Accepted by ${q.accepted_by} of ${where}` : `Accepted at ${where}`;
  }
  if (q.status === "declined") return `Declined by ${where}${q.decline_reason ? `: ${q.decline_reason}` : ""}`;
  if (q.status === "withdrawn") return `Withdrawn from ${where}`;
  return q.status;
}

/** The record's state as a whole: its latest request, or not sent yet. */
export function recordState(rec) {
  return rec.requests.length ? requestState(rec.requests[0]) : "Not sent to a fire temple yet";
}

function gehSaarnuText(g) {
  return g ? `${gregLabel(g.date)}, ${g.geh_name} geh` : "Not given";
}

function uthamnaText(u) {
  if (!u) return "Not given";
  if (!u.time) return gregLabel(u.date);
  const [h, m] = u.time.split(":").map(Number);
  return `${gregLabel(u.date)}, ${h % 12 || 12}:${String(m).padStart(2, "0")} ${h < 12 ? "am" : "pm"}`;
}

async function loadCalendarOptions() {
  if (state.calendarOptions && state.calendarOptions.roj && state.calendarOptions.roj.length) return;
  try {
    state.calendarOptions = await calendarOptions();
  } catch (e) {
    state.calendarOptions = null;
    throw e;
  }
}

// --- The form ---------------------------------------------------------------------

function blankDraft() {
  return {
    title: "behdin", name: "", parent: "", calendar: "shenshai", deathBy: "date", death: "",
    deathRoj: "", deathMah: "", obsequies: "", bungli: "", gsDate: "", gsGeh: "", utDate: "", utTime: "",
    mobeds: "", preferred: null, contactName: "", contactPhone: "",
    placeId: ((state.user.funeral_places || [])[0] || {}).id || null,
  };
}

function draftFrom(rec) {
  return {
    title: rec.departed_title, name: rec.departed_name, parent: rec.departed_parent_name || "",
    calendar: rec.death.calendar, deathBy: rec.death.given_by === "roj_mah" ? "parsi" : "date",
    death: rec.death.date, deathRoj: String(rec.death.roj), deathMah: String(rec.death.mah),
    obsequies: rec.obsequies, bungli: rec.bungli || "",
    gsDate: rec.geh_saarnu ? rec.geh_saarnu.date : "", gsGeh: rec.geh_saarnu ? String(rec.geh_saarnu.geh) : "",
    utDate: rec.uthamna ? rec.uthamna.date : "", utTime: rec.uthamna && rec.uthamna.time ? rec.uthamna.time : "",
    mobeds: rec.mobeds_wanted ? String(rec.mobeds_wanted) : "",
    preferred: rec.preferred_agyari, contactName: rec.family_contact.name, contactPhone: rec.family_contact.phone,
    placeId: rec.funeral_place ? rec.funeral_place.id : null,
  };
}

function rojOptions(d) {
  const gatha = d.deathMah === "13";
  const names = ((state.calendarOptions && state.calendarOptions.roj) || []).map(o => o.title);
  return `<option value="">Choose</option>` + names.map((n, i) =>
    `<option value="${i + 1}" ${!gatha && d.deathRoj === String(i + 1) ? "selected" : ""}>${esc(n)}</option>`).join("")
    + `<optgroup label="Gatha days">` + GATHAS.map((n, i) =>
      `<option value="g${i + 1}" ${gatha && d.deathRoj === String(i + 1) ? "selected" : ""}>${esc(n)}</option>`).join("")
    + `</optgroup>`;
}

function radio(name, id, value, checked, text) {
  return `<div class="check-row"><input type="radio" name="${name}" id="${id}" value="${value}" ${checked ? "checked" : ""}>
    <label for="${id}">${text}</label></div>`;
}

function formHtml(d, { editing }) {
  const places = state.user.funeral_places || [];
  const today = todayIst();
  return `
    <div class="card" id="frCard">
      <h2>${editing ? "Change the record" : "Record a death"}</h2>
      <p class="meta">Only what the prayers need. The family's number is shown to a fire temple only once it
        accepts.</p>
      ${places.length > 1 ? `<label for="frPlace">Place</label>
        <select id="frPlace" ${editing ? "disabled" : ""}>${places.map(p =>
          `<option value="${p.id}" ${d.placeId === p.id ? "selected" : ""}>${esc(p.name)}</option>`).join("")}</select>` : ""}

      <label for="frTitle">Title</label>
      <select id="frTitle">${TITLES.map(([v, t]) => `<option value="${v}" ${d.title === v ? "selected" : ""}>${t}</option>`).join("")}</select>
      <label for="frName">Name of the departed</label>
      <input type="text" id="frName" autocomplete="off" maxlength="80" value="${esc(d.name)}">
      <label for="frParent">Father's or husband's name</label>
      <input type="text" id="frParent" autocomplete="off" maxlength="80" value="${esc(d.parent)}">
      <p class="meta" id="frPrayed" style="margin:6px 0 0"></p>

      <label for="frCalendar">Calendar the family keeps</label>
      <select id="frCalendar">${[["shenshai", "Shenshai"], ["kadmi", "Kadmi"]].map(([k, v]) =>
        `<option value="${k}" ${d.calendar === k ? "selected" : ""}>${v}</option>`).join("")}</select>

      <label>Death</label>
      <div class="choice-group" id="frDeathBy">
        ${radio("frDeathBy", "frByDate", "date", d.deathBy !== "parsi", "By the date")}
        ${radio("frDeathBy", "frByParsi", "parsi", d.deathBy === "parsi",
          "By Roj and Mah (for a death before sunrise, give the Parsi day it belonged to)")}
      </div>
      <div id="frDateBox" style="${d.deathBy === "parsi" ? "display:none" : ""}">
        <label for="frDeathDate">Date of death</label>
        <input type="date" id="frDeathDate" max="${today}" value="${esc(d.death)}">
      </div>
      <div id="frParsiBox" style="${d.deathBy === "parsi" ? "" : "display:none"}">
        <label for="frDeathRoj">Roj</label>
        <select id="frDeathRoj">${rojOptions(d)}</select>
        <div id="frMahBox" style="${d.deathMah === "13" ? "display:none" : ""}">
          <label for="frDeathMah">Mah</label>
          <select id="frDeathMah"><option value="">Choose</option>${MAH_NAMES_JS.map((n, i) =>
            `<option value="${i + 1}" ${d.deathMah === String(i + 1) ? "selected" : ""}>${esc(n)}</option>`).join("")}</select>
        </div>
      </div>
      <p class="meta" id="frDeathDay" role="status" style="margin:6px 0 0"></p>

      <label>Obsequies</label>
      <div class="choice-group" id="frObsequies">
        ${radio("frOb", "frObFour", "four_days", d.obsequies === "four_days", "Four days")}
        ${radio("frOb", "frObOne", "one_day", d.obsequies === "one_day", "One day")}
      </div>

      <label for="frBungli">Bungli or hall</label>
      <input type="text" id="frBungli" autocomplete="off" maxlength="80" value="${esc(d.bungli)}">

      <label for="frGsDate">Geh-saarnu: day</label>
      <input type="date" id="frGsDate" value="${esc(d.gsDate)}">
      <label for="frGsGeh">Geh-saarnu: geh</label>
      <select id="frGsGeh"><option value="">Choose</option>${DAY_GEHS.map(([n, t]) =>
        `<option value="${n}" ${d.gsGeh === String(n) ? "selected" : ""}>${t}</option>`).join("")}</select>

      <label for="frUtDate">Uthamna: day</label>
      <input type="date" id="frUtDate" value="${esc(d.utDate)}">
      <label for="frUtTime">Uthamna: time</label>
      <input type="time" id="frUtTime" value="${esc(d.utTime)}">

      <label for="frMobeds">Mobeds wanted (optional)</label>
      <input type="number" id="frMobeds" inputmode="numeric" min="1" max="20" value="${esc(d.mobeds)}">

      <label for="frPrefSearch">The family's fire temple (optional)</label>
      <div id="frPreferredBox"></div>

      <label for="frContact">Family contact: name</label>
      <input type="text" id="frContact" autocomplete="off" maxlength="100" value="${esc(d.contactName)}">
      <label for="frPhone">Family contact: number</label>
      <div id="frPhoneBox">${phoneField("frPhone")}</div>

      <div class="action-bar">
        <button type="button" id="frSave">${editing ? "Save changes" : "Save"}</button>
      </div>
    </div>`;
}

/** Field the server names (X-Field) -> what to mark on the form. */
function fieldTarget(field, d) {
  return {
    departed_title: "#frTitle", departed_name: "#frName", departed_parent_name: "#frParent",
    calendar: "#frCalendar", death: d.deathBy === "parsi" ? "#frDeathRoj" : "#frDeathDate",
    obsequies: "#frObsequies", bungli: "#frBungli", geh_saarnu_date: "#frGsDate", geh_saarnu_geh: "#frGsGeh",
    uthamna_date: "#frUtDate", mobeds_wanted: "#frMobeds", preferred_agyary_id: "#frPreferredBox",
    family_contact_name: "#frContact", family_contact_phone: "#frPhoneBox .phone-field",
  }[field] || null;
}

/** The form's body for the API, and what is wrong with it (marked on the form). */
function build(d) {
  const problems = [];
  const bad = (target, message) => problems.push({ target, message });
  if (!d.name.trim()) bad("#frName", "Please enter the name of the departed.");
  const byParsi = d.deathBy === "parsi";
  if (byParsi) {
    if (!d.deathRoj) bad("#frDeathRoj", "Please choose the Roj of the death.");
    else if (d.deathMah !== "13" && !d.deathMah) bad("#frDeathMah", "Please choose the Mah of the death.");
  } else if (!d.death) bad("#frDeathDate", "Please enter the date of death.");
  else if (d.death > todayIst()) bad("#frDeathDate", "The death cannot be after today.");
  if (!d.obsequies) bad("#frObsequies", "Please choose four days or one day.");
  if (d.gsDate && !d.gsGeh) bad("#frGsGeh", "Please choose the geh of the Geh-saarnu.");
  if (d.gsGeh && !d.gsDate) bad("#frGsDate", "Please give the day of the Geh-saarnu.");
  if (d.utTime && !d.utDate) bad("#frUtDate", "Please give the day of the Uthamna.");
  const deathDay = byParsi ? null : d.death;
  if (deathDay && d.gsDate && d.gsDate < deathDay) bad("#frGsDate", "The Geh-saarnu cannot be before the death.");
  if (deathDay && d.utDate && d.utDate < deathDay) bad("#frUtDate", "The Uthamna cannot be before the death.");
  const mobeds = d.mobeds === "" ? null : Number(d.mobeds);
  if (mobeds !== null && !(Number.isInteger(mobeds) && mobeds >= 1 && mobeds <= 20)) {
    bad("#frMobeds", "The number of mobeds is from 1 to 20.");
  }
  if (!d.contactName.trim()) bad("#frContact", "Please enter the family contact's name.");
  const phone = readPhone("frPhone");
  if (!phone) bad("#frPhoneBox .phone-field", "Please enter the family contact's number.");
  return {
    problems,
    body: {
      funeral_place_id: d.placeId,
      departed_title: d.title, departed_name: d.name.trim(), departed_parent_name: d.parent.trim() || null,
      calendar: d.calendar,
      death_date: byParsi ? null : d.death || null,
      death_roj: byParsi && d.deathRoj ? Number(d.deathRoj) : null,
      death_mah: byParsi && d.deathMah ? Number(d.deathMah) : null,
      obsequies: d.obsequies, bungli: d.bungli.trim() || null,
      geh_saarnu_date: d.gsDate || null, geh_saarnu_geh: d.gsGeh ? Number(d.gsGeh) : null,
      uthamna_date: d.utDate || null, uthamna_time: d.utTime || null,
      mobeds_wanted: mobeds,
      preferred_agyary_id: d.preferred ? d.preferred.id : null,
      family_contact_name: d.contactName.trim(), family_contact_phone: phone || "",
    },
  };
}

/** The family's preferred fire temple: chosen (with Change), or a search. */
function paintPreferred(box, d) {
  if (d.preferred) {
    box.innerHTML = `<div class="search-result" style="cursor:default;min-height:0">
        <div><strong>${esc(d.preferred.name)}</strong></div><div class="addr">${esc(d.preferred.city || "")}</div></div>
      <button type="button" class="ghost small" id="frPrefClear">Not this one</button>`;
    box.querySelector("#frPrefClear").onclick = () => { d.preferred = null; paintPreferred(box, d); };
    return;
  }
  box.innerHTML = `<input type="text" id="frPrefSearch" placeholder="Search by name or town" autocomplete="off">
    <div id="frPrefResults" style="margin-top:8px"></div>`;
  const input = box.querySelector("#frPrefSearch");
  const results = box.querySelector("#frPrefResults");
  let timer, token = 0;
  input.oninput = () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const q = input.value.trim();
      const mine = ++token;
      if (!q) { results.innerHTML = ""; return; }
      let found;
      try {
        found = (await managerSearchAgyaries(q, d.placeId)).agyaries;
      } catch (e) {
        if (mine === token) results.innerHTML = `<p class="meta" role="alert">${esc(e.message)}</p>`;
        return;
      }
      if (mine !== token || !box.isConnected) return;
      if (!found.length) { results.innerHTML = `<p class="meta">No fire temple found for “${esc(q)}”.</p>`; return; }
      results.innerHTML = found.map((a, i) => `<div class="search-result" data-i="${i}">
          <div><strong>${esc(a.name)}</strong></div><div class="addr">${esc(a.city || "")}</div></div>`).join("");
      results.querySelectorAll("[data-i]").forEach(row => {
        row.onclick = () => {
          const a = found[+row.dataset.i];
          d.preferred = { id: a.id, name: a.name, city: a.city };
          paintPreferred(box, d);
        };
      });
    }, 250);
  };
}

async function renderForm(rec) {
  chrome(true);
  refreshHeader();
  showFab(false);
  loading();
  const alive = navGuard();
  try {
    await loadCalendarOptions();
  } catch (e) {
    if (!alive()) return;
    return screenFailed(e.message, () => renderForm(rec));
  }
  if (!alive()) return;
  const editing = !!rec;
  const d = rec ? draftFrom(rec) : blankDraft();
  mainEl.innerHTML = formHtml(d, { editing });
  toTop();
  const root = document.getElementById("frCard");
  const $ = (sel) => root.querySelector(sel);
  if (d.contactPhone) setPhoneField("frPhone", d.contactPhone);

  const prayed = () => {
    const title = (TITLES.find(([v]) => v === d.title) || ["", ""])[1];
    const whole = [title, d.name.trim(), d.parent.trim()].filter(Boolean).join(" ");
    $("#frPrayed").textContent = d.name.trim() ? `Prayed as: ${whole}` : "";
  };
  prayed();

  // The Roj and Mah of the death (or its date), from the server, to confirm (D5).
  let dayToken = 0;
  const showDay = async () => {
    const out = $("#frDeathDay");
    const mine = ++dayToken;
    const parsi = d.deathBy === "parsi";
    if (parsi ? !(d.deathRoj && (d.deathMah || d.deathMah === "13")) : !d.death) { out.textContent = ""; return; }
    out.textContent = "Working it out...";
    try {
      const day = await managerDeathDay({
        calendar: d.calendar, death_date: parsi ? null : d.death,
        death_roj: parsi ? Number(d.deathRoj) : null, death_mah: parsi ? Number(d.deathMah) : null,
      });
      if (mine !== dayToken || !out.isConnected) return;
      out.innerHTML = parsi
        ? `That is <b>${esc(gregLabel(day.date))}</b> (${esc(day.label)}). Please check it is right.`
        : `That is <b>${esc(day.label)}</b>. Please check it is right; for a death before sunrise, give the Roj and
           Mah instead.`;
    } catch (e) {
      if (mine !== dayToken || !out.isConnected) return;
      out.textContent = e.message;
    }
  };
  showDay();

  const bind = (sel, key, after) => {
    const el = $(sel);
    el.addEventListener(el.tagName === "SELECT" || el.type === "date" || el.type === "time" ? "change" : "input",
      () => { d[key] = el.value; if (after) after(); });
  };
  if ($("#frPlace")) $("#frPlace").onchange = (e) => { d.placeId = Number(e.target.value); };
  bind("#frTitle", "title", prayed);
  bind("#frName", "name", prayed);
  bind("#frParent", "parent", prayed);
  bind("#frCalendar", "calendar", showDay);
  bind("#frDeathDate", "death", showDay);
  bind("#frDeathMah", "deathMah", showDay);
  bind("#frBungli", "bungli");
  bind("#frGsDate", "gsDate");
  bind("#frGsGeh", "gsGeh");
  bind("#frUtDate", "utDate");
  bind("#frUtTime", "utTime");
  bind("#frMobeds", "mobeds");
  bind("#frContact", "contactName");
  $("#frDeathRoj").onchange = (e) => {
    const v = e.target.value;
    if (v.startsWith("g")) {            // a Gatha day has no Mah of its own
      d.deathMah = "13"; d.deathRoj = v.slice(1);
      $("#frMahBox").style.display = "none";
    } else {
      if (d.deathMah === "13") { d.deathMah = ""; $("#frDeathMah").value = ""; }
      d.deathRoj = v;
      $("#frMahBox").style.display = "";
    }
    showDay();
  };
  root.querySelectorAll("[name=frDeathBy]").forEach(r => {
    r.onchange = () => {
      d.deathBy = r.value;
      $("#frDateBox").style.display = d.deathBy === "parsi" ? "none" : "";
      $("#frParsiBox").style.display = d.deathBy === "parsi" ? "" : "none";
      showDay();
    };
  });
  root.querySelectorAll("[name=frOb]").forEach(r => { r.onchange = () => { d.obsequies = r.value; }; });
  paintPreferred($("#frPreferredBox"), d);

  let saving = false;
  $("#frSave").onclick = async (ev) => {
    if (saving) return;
    const btn = ev.currentTarget;
    const { problems, body } = build(d);
    if (problems.length) return flagProblems(root, problems);
    clearProblems(root);
    saving = true;
    btn.disabled = true;
    let res;
    try {
      res = editing ? await managerUpdateRecord(rec.id, body) : await managerCreateRecord(body);
    } catch (e) {
      saving = false;
      btn.disabled = false;
      const target = e.field ? fieldTarget(e.field, d) : null;
      if (target && root.querySelector(target)) return flagProblems(root, [{ target, message: e.message }]);
      return showError(e.message);
    }
    if (!alive()) return;
    const saved = res.record;
    if (editing) {
      flashInfo(res.told
        ? `Saved. The ${res.told === 1 ? "person" : `${res.told} people`} asked at the fire temple ${res.told === 1
          ? "was" : "were"} sent the new details.`
        : "Saved.");
      returnTo(`#/manager/record/${saved.id}`);
    } else if (saved.may_send) {
      flashInfo("Saved. Now choose the fire temple to ask for the prayers.");
      navigate(`#/manager/record/${saved.id}`, { replace: true });
      navigate(`#/manager/record/${saved.id}/send`);
    } else {
      flashInfo("Saved.");
      navigate(`#/manager/record/${saved.id}`, { replace: true });
    }
  };
}

export function renderRecordNew() {
  const places = state.user.funeral_places || [];
  if (places.length && !places.some(p => p.is_active)) {
    flashInfo("Your place is turned off in Mobed Diary at the moment, so a death cannot be recorded there.");
    return navigate("#/manager", { replace: true });
  }
  return renderForm(null);
}

async function fetchRecord(id, retry) {
  try {
    return (await managerRecord(id)).record;
  } catch (e) {
    screenFailed(e.message, retry);
    return null;
  }
}

export async function renderRecordEdit({ id }) {
  chrome(true);
  loading();
  const alive = navGuard();
  const rec = await fetchRecord(id, () => renderRecordEdit({ id }));
  if (!rec || !alive()) return;
  if (!rec.may_edit) {
    flashInfo("A fire temple has accepted this request, so the record can no longer be changed here.");
    return navigate(`#/manager/record/${id}`, { replace: true });
  }
  return renderForm(rec);
}

// --- The record ---------------------------------------------------------------------

/** Who accepted, and a way to reach them only if they shared their number. */
function accepterHtml(rec, q) {
  if (!q || !q.accepter_phone) {
    return q ? `<p class="meta" style="margin:4px 0 0">They did not share their number. You can reach them through
      ${esc(q.agyari ? q.agyari.name : "the fire temple")}.</p>` : "";
  }
  const me = state.user ? state.user.name : "";
  const place = rec.funeral_place ? rec.funeral_place.name : "";
  const text = `Namaste ${q.accepted_by}, about the prayers for ${rec.prayed_name} - ${[me, place].filter(Boolean).join(", ")}.`;
  const digits = q.accepter_phone.replace(/\D/g, "");
  return `
    <p style="margin:6px 0 0"><a class="tel" href="tel:${esc(q.accepter_phone)}">${esc(q.accepter_phone)}</a></p>
    <div class="row tight" style="margin-top:8px;flex-wrap:wrap">
      <a class="button small secondary" id="mrCall" href="tel:${esc(q.accepter_phone)}">Call</a>
      <a class="button small secondary" id="mrWa" target="_blank" rel="noopener"
        href="https://wa.me/${esc(digits)}?text=${esc(encodeURIComponent(text))}">WhatsApp</a>
    </div>`;
}

function fact(label, value) {
  return `<div class="fact"><div class="fl">${esc(label)}</div><div class="fv">${value}</div></div>`;
}

export async function renderRecordView({ id }) {
  chrome(true);
  refreshHeader();
  showFab(false);
  loading();
  const alive = navGuard();
  const rec = await fetchRecord(id, () => renderRecordView({ id }));
  if (!rec || !alive()) return;
  const waiting = rec.requests.find(q => q.status === "waiting");
  const taken = rec.requests.find(q => q.status === "accepted" || q.status === "taken");
  const death = rec.death;
  mainEl.innerHTML = `
    <div class="card">
      <h2>${esc(rec.prayed_name)}</h2>
      ${rec.funeral_place ? `<p class="meta" style="margin:0">${esc(rec.funeral_place.name)}</p>` : ""}
      <div style="margin-top:10px">
        ${fact("Died", `${esc(gregLabel(death.date))}<br><span class="meta">${esc(death.label)}${death.given_by === "roj_mah"
          ? " (given by Roj and Mah)" : ""}</span>`)}
        ${fact("Obsequies", esc(rec.obsequies_label))}
        ${fact("Bungli or hall", esc(rec.bungli || "Not given"))}
        ${fact("Geh-saarnu", esc(gehSaarnuText(rec.geh_saarnu)))}
        ${fact("Uthamna", esc(uthamnaText(rec.uthamna)))}
        ${rec.mobeds_wanted ? fact("Mobeds wanted", String(rec.mobeds_wanted)) : ""}
        ${fact("The family's fire temple", esc(rec.preferred_agyari ? rec.preferred_agyari.name : "Not named"))}
        ${fact("Family contact", `${esc(rec.family_contact.name)}<br><span class="meta">${esc(rec.family_contact.phone)}</span>`)}
      </div>
    </div>

    <div class="card">
      <h2>Prayers</h2>
      <p style="margin:4px 0 0"><b>${esc(recordState(rec))}</b></p>
      ${taken ? accepterHtml(rec, taken) : ""}
      ${waiting ? `<p class="meta" style="margin:4px 0 0">${waiting.asked} ${waiting.asked === 1 ? "person was" : "people were"}
        told. You see here when they answer.</p>` : ""}
      ${rec.requests.length > 1 ? `<div style="margin-top:10px">${rec.requests.slice(1).map(q =>
        `<p class="meta" style="margin:2px 0">${esc(requestState(q))}</p>`).join("")}</div>` : ""}
      <div class="action-bar">
        ${waiting ? `<button type="button" class="secondary" id="mrWithdraw">Withdraw</button>` : ""}
        ${rec.may_send ? `<button type="button" id="mrSend">${rec.requests.length ? "Send to another fire temple"
          : "Send to a fire temple"}</button>` : ""}
        ${rec.may_edit ? `<button type="button" class="ghost" id="mrEdit">Change</button>` : ""}
      </div>
      ${rec.funeral_place && !rec.funeral_place.is_active ? `<p class="meta" style="margin:10px 0 0">This place is
        turned off in Mobed Diary at the moment, so nothing can be sent from it.</p>` : ""}
    </div>`;
  const on = (sel, fn) => { const el = document.getElementById(sel); if (el) el.onclick = fn; };
  on("mrSend", () => navigate(`#/manager/record/${rec.id}/send`));
  on("mrEdit", () => navigate(`#/manager/record/${rec.id}/edit`));
  on("mrWithdraw", () => confirmWithdraw(rec, waiting));
}

function confirmWithdraw(rec, q) {
  const sheet = openSheet({
    title: `Withdraw the request to ${q.agyari ? q.agyari.name : "the fire temple"}?`,
    html: `
      <p style="margin-top:0">The people asked there are told it is no longer needed. You can then send it to another
        fire temple.</p>
      <div class="stack">
        <button type="button" class="danger" data-yes>Withdraw</button>
        <button type="button" class="ghost" data-no>Keep it waiting</button>
      </div>`,
  });
  sheet.body.querySelector("[data-no]").onclick = sheet.close;
  sheet.body.querySelector("[data-yes]").onclick = async (ev) => {
    const btn = ev.currentTarget;
    btn.disabled = true;
    try {
      await managerWithdraw(q.id);
    } catch (e) {
      btn.disabled = false;
      return showError(e.message);
    }
    sheet.close();
    await renderRecordView({ id: rec.id });
    showInfo("Withdrawn. You can now send it to another fire temple.");
  };
}

// --- Choosing the fire temple ---------------------------------------------------------

function agyariRowHtml(a, i) {
  const reach = REACH[a.reach] || REACH.nobody;
  const km = a.km == null ? "" : `${a.location_source === "town" ? "about " : ""}${a.km < 10 ? a.km : Math.round(a.km)} km`;
  return `<div class="search-result${a.may_send ? "" : " unavailable"}" data-i="${i}" ${a.may_send ? "" : 'aria-disabled="true"'}>
      <div><strong>${esc(a.name)}</strong></div>
      <div class="addr">${esc([a.city, km].filter(Boolean).join(" · "))}</div>
      <div style="margin-top:4px">${a.preferred ? `<span class="tag">The family's choice</span>` : ""}<span
        class="tag ${reach.cls}">${reach.text}</span></div>
    </div>`;
}

function wireRows(container, list, rec) {
  container.querySelectorAll("[data-i]").forEach(row => {
    const a = list[+row.dataset.i];
    if (!a.may_send) {
      // Shown so the manager knows it is there, but a request would reach nobody.
      row.removeAttribute("role");
      row.tabIndex = -1;
      return;
    }
    row.onclick = () => confirmSend(rec, a);
  });
}

export async function renderRecordSend({ id }) {
  chrome(true);
  refreshHeader();
  showFab(false);
  loading();
  const alive = navGuard();
  const rec = await fetchRecord(id, () => renderRecordSend({ id }));
  if (!rec || !alive()) return;
  if (!rec.may_send) {
    flashInfo(rec.requests.some(q => q.status === "waiting")
      ? "This request is already waiting at a fire temple. Withdraw it first to send it to another."
      : "This record cannot be sent now.");
    return navigate(`#/manager/record/${id}`, { replace: true });
  }
  mainEl.innerHTML = `
    <div class="card">
      <h2>Ask a fire temple</h2>
      <p class="meta" style="margin:0">For ${esc(rec.prayed_name)}. Choose the fire temple; its panthaky is asked, or
        if it has none in Mobed Diary, its mobeds.</p>
      <div class="chip-row" style="margin-top:12px" role="tablist">
        <button type="button" class="chip on" data-tab="near" role="tab" aria-selected="true">Suggested</button>
        <button type="button" class="chip" data-tab="all" role="tab" aria-selected="false">Search all</button>
      </div>
    </div>
    <div class="card" id="msNear"><p class="meta">Loading...</p></div>
    <div class="card hidden" id="msAll">
      <input type="text" id="msSearch" placeholder="Search by name or town" autocomplete="off">
      <div id="msResults" style="margin-top:8px"></div>
    </div>`;
  toTop();
  const near = document.getElementById("msNear");
  const all = document.getElementById("msAll");
  const tabs = mainEl.querySelectorAll("[data-tab]");
  const show = (tab) => {
    tabs.forEach(b => { const onTab = b.dataset.tab === tab; b.classList.toggle("on", onTab); b.setAttribute("aria-selected", String(onTab)); });
    near.classList.toggle("hidden", tab !== "near");
    all.classList.toggle("hidden", tab !== "all");
    if (tab === "all") document.getElementById("msSearch").focus();
  };
  tabs.forEach(b => { b.onclick = () => show(b.dataset.tab); });

  const placeName = rec.funeral_place ? rec.funeral_place.name : "Your place";
  const loadNear = async () => {
    let got;
    try {
      got = await managerSuggested(rec.id);
    } catch (e) {
      if (!alive()) return;
      near.innerHTML = `<div class="load-failed" role="alert"><p><b></b></p>
        <button class="small" type="button" data-retry>Try again</button></div>`;
      near.querySelector("b").textContent = e.message;
      near.querySelector("[data-retry]").onclick = loadNear;
      return;
    }
    if (!alive()) return;
    const list = got.agyaries;
    const intro = got.place_has_position
      ? `<p class="meta" style="margin-top:0">Nearest first, within ${got.near_km} km of ${esc(placeName)}, in a
          straight line.</p>`
      : `<p class="meta" style="margin-top:0">${esc(placeName)} is not on the map yet, so nothing can be suggested
          by distance. Use Search all.</p>`;
    near.innerHTML = intro + (list.length ? list.map(agyariRowHtml).join("")
      : got.place_has_position ? `<p class="meta">No fire temple in Mobed Diary is within ${got.near_km} km.
          Use Search all.</p>` : "")
      + (got.place_has_position ? "" : `<div class="action-bar"><button type="button" class="secondary"
          id="msToAll">Search all</button></div>`);
    const toAll = document.getElementById("msToAll");
    if (toAll) toAll.onclick = () => show("all");
    wireRows(near, list, rec);
  };
  loadNear();

  const input = document.getElementById("msSearch");
  const results = document.getElementById("msResults");
  let timer, token = 0;
  input.oninput = () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const q = input.value.trim();
      const mine = ++token;
      if (!q) { results.innerHTML = ""; return; }
      let found;
      try {
        found = (await managerSearchAgyaries(q, rec.funeral_place && rec.funeral_place.id)).agyaries;
      } catch (e) {
        if (mine === token) results.innerHTML = `<p class="meta" role="alert">${esc(e.message)}</p>`;
        return;
      }
      if (mine !== token || !alive()) return;
      results.innerHTML = found.length ? found.map(agyariRowHtml).join("")
        : `<p class="meta">No fire temple found for “${esc(q)}”.</p>`;
      wireRows(results, found, rec);
    }, 250);
  };
}

let sending = false;

/** The tick, then Send. The tick is asked every time, for this fire temple. */
function confirmSend(rec, a) {
  const who = a.reach === "panthaky" ? "its panthaky" : "its mobeds in Mobed Diary";
  const sheet = openSheet({
    title: `Send to ${a.name}?`,
    html: `
      <p class="meta" style="margin-top:0">${esc(rec.prayed_name)}. It goes to ${who}, with the prayers and their
        times. The family's name and number are shown only to the one who accepts.</p>
      <div class="check-row" id="msTickRow"><input type="checkbox" id="msTick">
        <label for="msTick">The family agreed to share their name and number with this agyari</label></div>
      <p class="meta" data-msg role="alert" style="margin:6px 0 0"></p>
      <div class="stack" style="margin-top:12px">
        <button type="button" data-send>Send</button>
        <button type="button" class="ghost" data-cancel>Cancel</button>
      </div>`,
  });
  const body = sheet.body;
  body.querySelector("[data-cancel]").onclick = sheet.close;
  body.querySelector("[data-send]").onclick = async (ev) => {
    if (sending) return;
    const msg = body.querySelector("[data-msg]");
    msg.textContent = "";
    if (!body.querySelector("#msTick").checked) {
      return flagProblems(body, [{ target: "#msTickRow",
        message: "Please tick this first: the request cannot go without the family's agreement." }]);
    }
    const btn = ev.currentTarget;
    sending = true;
    btn.disabled = true;
    let res;
    try {
      res = await managerSend(rec.id, a.id, true);
    } catch (e) {
      btn.disabled = false;
      msg.textContent = e.message;   // in the sheet, where they are looking
      return;
    } finally {
      sending = false;
    }
    sheet.close();
    const n = res.asked;
    flashInfo(`Sent to ${a.name}. ${n} ${n === 1 ? "person there was" : "people there were"} told.`);
    returnTo(`#/manager/record/${rec.id}`);
  };
}
