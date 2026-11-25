"use strict";

/**
 * "Requests from people", a section at the top of the Requests tab (R4.2; docs/behdin-r4-2-design.md).
 *
 * A confirmed panthaky sees it when requests exist or their fire temple takes them. Each request is a card
 * of its items (service or memorial, day with Roj and Mah, time or geh, repeat), the names to pray, the
 * estimated total, the person's first name and how long ago. The number is not here. Confirm applies to the
 * whole request (a sheet first; an item with an open time asks for its time there) and puts the person in
 * the panthaky's behdins and each item in the diary. Decline has an optional reason.
 * Anyone who is not the panthaky sees nothing.
 */

import { getAsksSetting, listAsks, acceptAsk, rejectAsk } from "./api.js";
import { currentAgyary } from "./state.js";
import { openSheet, showInfo } from "./ui.js";
import { esc, gregLabel } from "./util.js";
import { flagProblems, clearProblems } from "./fielderrors.js";
import { navigate } from "./router.js";
import { refreshAfterAction } from "./notifications.js";

const SHOWN_ANSWERED = 10;
// What an accept made, by ask id, so the card can link to it until the screen is left.
const made = new Map();

function ago(iso) {
  if (!iso) return "";
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.round(hours / 24);
  return `${days} days ago`;
}

function clock(hhmm) {
  const [h, m] = hhmm.split(":").map(Number);
  return `${h % 12 || 12}:${String(m).padStart(2, "0")} ${h < 12 ? "am" : "pm"}`;
}

/** "Tue 24/11/2026, Roj Hormuzd Mah Aban". */
function dayText(date, parsi) {
  return parsi ? `${gregLabel(date)}, ${parsi}` : gregLabel(date);
}

function whenText(it) {
  if (it.geh_name) return `${it.geh_name} geh`;
  if (it.time) return clock(it.time);
  return "Time open";
}

/** "Every month, 12 in all" / "Every year". */
function repeatText(recurring, count) {
  if (!recurring) return "";
  const word = recurring === "yearly" ? "Every year" : "Every month";
  return count ? `${word}, ${count} in all` : word;
}

function nameText(n) {
  return esc(typeof n === "string" ? n : n.name);
}

function fact(label, value) {
  return `<div class="fact"><div class="fl">${esc(label)}</div><div class="fv">${value}</div></div>`;
}

function statusLine(a) {
  const label = a.label || a.status;
  return a.changed ? `${label}, changed` : label;
}

const GONE = "cancelled_by_fire_temple";

function itemHtml(it) {
  const gone = it.state === GONE;
  const m = it.memorial;
  const title = it.type === "memorial" ? "Memorial" : (it.service && it.service.name) || it.name;
  const facts = m
    ? `${fact("Departed", m.name_known ? esc(m.departed_name) : "Name not known")}
       ${fact("Passed away", esc(m.death_date_text || ""))}
       ${m.recurring ? fact("Repeats", esc(repeatText(m.recurring, m.recurring_count))) : ""}`
    : `${fact("Day", esc(dayText(it.date, it.parsi)))}
       ${fact("Time", esc(whenText(it)))}
       ${it.repeat ? fact("Repeats", esc(repeatText(it.repeat.recurring, it.repeat.recurring_count))) : ""}`;
  return `<div class="ask-item" data-item="${it.id}" style="padding:8px 0;border-top:1px solid var(--border)${gone ? ";opacity:.7" : ""}">
    <div style="font-weight:600">${esc(title)}${gone ? ` <span class="meta" style="font-weight:400">Cancelled by the fire temple</span>`
      : it.changed ? ` <span class="meta" style="font-weight:400">Changed</span>` : ""}</div>
    ${facts}
  </div>`;
}

function totalText(a) {
  if (a.total == null) return "";
  const n = Number(a.total).toLocaleString("en-IN", { maximumFractionDigits: 2 });
  return `${a.total_is_estimate ? "Estimate" : "Total"} \u20b9${n}`;
}

function linksHtml(a) {
  const m = made.get(a.id) || {};
  const btns = [];
  for (const r of m.items || []) {
    const it = a.items.find(x => x.id === r.id);
    const name = it && it.type === "memorial" ? "memorial" : (it && it.service && it.service.name) || "booking";
    if (r.booking_id) btns.push(`<button type="button" class="secondary small" data-go="#/booking/${m.agyary_id}/${r.booking_id}">Open ${esc(name)}</button>`);
    if (r.machi_id) btns.push(`<button type="button" class="secondary small" data-go="#/machi/${m.agyary_id}/${r.machi_id}">Open ${esc(name)}</button>`);
    if (r.memorial_id) btns.push(`<button type="button" class="secondary small" data-go="#/memorial/${r.memorial_id}">Open ${esc(name)}</button>`);
  }
  const cust = m.customer_id || a.customer_id;
  if (cust) btns.push(`<button type="button" class="ghost small" data-go="#/behdins/${cust}">Open ${esc(a.person.first_name || "them")} in Behdins</button>`);
  return btns.length ? `<div class="stack" style="margin-top:10px">${btns.join("")}</div>` : "";
}

function cardHtml(a) {
  const waiting = a.status === "waiting";
  const total = totalText(a);
  return `<div class="card ask-card" data-ask="${a.id}">
    <p style="margin:0 0 2px"><b>${esc(statusLine(a))}</b></p>
    <p class="meta" style="margin:0 0 6px">${esc(a.person.first_name || "A person")}, ${esc(ago(a.created_at))}</p>
    ${a.items.map(itemHtml).join("")}
    ${a.names && a.names.length ? fact("Names to pray", a.names.map(nameText).join("<br>")) : ""}
    ${total ? fact("Total", esc(total)) : ""}
    ${a.status === "rejected" && a.reject_reason ? fact("Reason", esc(a.reject_reason)) : ""}
    <p class="meta" role="alert" data-msg style="margin:6px 0 0"></p>
    ${waiting ? `<div class="stack" style="margin-top:10px">
        <button type="button" data-accept>Confirm</button>
        <button type="button" class="secondary" data-reject>Decline</button>
      </div>` : a.status === "accepted" ? linksHtml(a) : ""}
  </div>`;
}

function sectionHtml(asks, takes) {
  const waiting = asks.filter(a => a.status === "waiting");
  const answered = asks.filter(a => a.status !== "waiting");
  return `<h2 style="margin:0 0 8px">Requests from people</h2>
    ${waiting.length ? waiting.map(cardHtml).join("")
      : `<div class="card"><p style="margin:0">${takes ? "No requests pending." : "Not taking requests. Set up in Settings."}</p></div>`}
    ${answered.length ? `<h2 style="margin:16px 0 8px">Answered</h2>${answered.slice(0, SHOWN_ANSWERED).map(cardHtml).join("")}` : ""}
    <div style="margin-bottom:24px"></div>`;
}

/** Fill `box` (on the Requests tab). Draws nothing for anyone who is not the panthaky, nor when
 *  there are no asks and the fire temple does not take them. `alive()` is false once the screen is left. */
export async function paintAsks(box, alive) {
  const agyary = currentAgyary();
  if (!box || !agyary || agyary.role !== "panthaky") return;
  let takes = false, list;
  try {
    [takes, list] = await Promise.all([
      getAsksSetting(agyary.id).then(r => !!r.takes_asks, () => false),
      listAsks(agyary.id),
    ]);
  } catch (e) {
    // Not the panthaky of a fire temple the server knows: nothing to show. Any other failure is said.
    if (!alive() || e.status === 403 || e.status === 404) return;
    box.innerHTML = `<div class="card"><h2>Requests from people</h2><p class="meta">Couldn't load this: ${esc(e.message)}</p></div>`;
    return;
  }
  if (!alive()) return;
  if (!takes && !list.asks.length) return;
  const asks = list.asks.slice();
  const draw = () => {
    box.innerHTML = sectionHtml(asks, takes);
    wire();
  };
  const wire = () => {
    box.querySelectorAll("[data-ask]").forEach(card => {
      const a = asks.find(x => x.id === Number(card.dataset.ask));
      const msg = card.querySelector("[data-msg]");
      card.querySelectorAll("[data-go]").forEach(b => { b.onclick = () => navigate(b.dataset.go); });
      const yes = card.querySelector("[data-accept]");
      if (yes) yes.onclick = () => confirmAccept(a, agyary, msg, update, alive);
      const no = card.querySelector("[data-reject]");
      if (no) no.onclick = () => confirmReject(a, agyary, update, alive);
    });
  };
  const update = (fresh) => {
    const i = asks.findIndex(x => x.id === fresh.id);
    if (i >= 0) asks[i] = fresh;
    if (alive()) draw();
  };
  draw();
}

function openTimeFields(a) {
  return a.items.filter(it => it.time_open && it.state !== GONE).map(it => {
    const what = it.type === "memorial" ? "Memorial" : (it.service && it.service.name) || "Prayer";
    return `<label for="askTime${it.id}">Time for ${esc(what)}, ${esc(it.date_text || "")}</label>
      <input type="time" id="askTime${it.id}" data-time="${it.id}">`;
  }).join("");
}

function confirmAccept(a, agyary, msg, update, alive) {
  const sheet = openSheet({
    title: "Confirm this request?",
    html: `<p style="margin-top:0">${esc(a.person.first_name || "The person")}'s name and number will be added to your
        behdins and this goes into your diary.</p>
      ${openTimeFields(a)}
      <p class="meta" role="alert" data-err style="margin:6px 0 0"></p>
      <div class="stack" style="margin-top:12px">
        <button type="button" data-yes>Confirm</button>
        <button type="button" class="ghost" data-no>Cancel</button>
      </div>`,
  });
  const body = sheet.body;
  body.querySelector("[data-no]").onclick = sheet.close;
  body.querySelector("[data-yes]").onclick = async (ev) => {
    const btn = ev.currentTarget;
    if (btn.disabled) return;
    btn.disabled = true;
    clearProblems(body);
    body.querySelector("[data-err]").textContent = "";
    const times = {};
    body.querySelectorAll("[data-time]").forEach(i => { if (i.value) times[i.dataset.time] = i.value; });
    let res;
    try {
      res = await acceptAsk(agyary.id, a.id, times);
    } catch (e) {
      btn.disabled = false;
      // The server says why in plain words; the request stays as it was.
      const empty = [...body.querySelectorAll("[data-time]")].find(i => !i.value);
      if (/^Enter a time/i.test(e.message) && empty) return flagProblems(body, [{ target: empty, message: e.message }]);
      body.querySelector("[data-err]").textContent = e.message;
      return;
    }
    sheet.close();
    made.set(a.id, { ...res, agyary_id: agyary.id });
    update(res.ask);
    refreshAfterAction();
    showInfo("Confirmed.");
  };
}

function confirmReject(a, agyary, update, alive) {
  const sheet = openSheet({
    title: "Decline this request?",
    html: `<label for="askReason" style="margin-top:0">Reason (optional)</label>
      <textarea id="askReason" rows="2" maxlength="100"></textarea>
      <p class="meta" role="alert" data-err style="margin:6px 0 0"></p>
      <div class="stack" style="margin-top:12px">
        <button type="button" class="danger" data-yes>Decline</button>
        <button type="button" class="ghost" data-no>Cancel</button>
      </div>`,
  });
  const body = sheet.body;
  body.querySelector("[data-no]").onclick = sheet.close;
  body.querySelector("[data-yes]").onclick = async (ev) => {
    const btn = ev.currentTarget;
    if (btn.disabled) return;
    btn.disabled = true;
    body.querySelector("[data-err]").textContent = "";
    let res;
    try {
      res = await rejectAsk(agyary.id, a.id, body.querySelector("#askReason").value.trim());
    } catch (e) {
      btn.disabled = false;
      body.querySelector("[data-err]").textContent = e.message;
      return;
    }
    sheet.close();
    update(res);
    refreshAfterAction();
    showInfo("Declined.");
  };
}
