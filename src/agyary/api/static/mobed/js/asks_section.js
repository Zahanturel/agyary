"use strict";

/**
 * "Asks from people", a section at the top of the Requests tab (R4.2; docs/behdin-r4-2-design.md).
 *
 * A confirmed panthaky sees it when asks exist or their fire temple takes asks. Each ask is a card:
 * the service, the day (with Roj and Mah), the geh or time, where, the names to pray, the note, the
 * person's first name and how long ago. The person's number is not here: Accept (a sheet first) puts
 * their name and number in the panthaky's behdins and the booking in their diary. Can't take it
 * opens a sheet with an optional reason. Anyone who is not the panthaky sees nothing.
 */

import { getAsksSetting, listAsks, acceptAsk, rejectAsk } from "./api.js";
import { currentAgyary, TITLE_DISPLAY } from "./state.js";
import { openSheet, showInfo } from "./ui.js";
import { esc, gregLabel } from "./util.js";
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

function whenText(a) {
  if (a.geh_name) return `${a.geh_name} geh`;
  if (a.time) return clock(a.time);
  return "";
}

function repeatText(r) {
  if (!r) return "";
  const unit = r.pattern === "yearly" || r.pattern === "same_roj_mah_every_year" ? "year" : "month";
  const word = unit === "year" ? "every year" : "every month";
  return r.count ? `Repeats ${word}, ${r.count} ${unit}s in all` : `Repeats ${word}`;
}

/** One name to pray, as the diary reads it: "Osta Rustom Test (departed)". */
function nameText(n) {
  const title = TITLE_DISPLAY[n.title] || "";
  return esc(`${title} ${n.name}${n.status === "departed" ? " (departed)" : ""}`.trim());
}

function fact(label, value) {
  return `<div class="fact"><div class="fl">${esc(label)}</div><div class="fv">${value}</div></div>`;
}

function statusLine(a) {
  if (a.status === "waiting") return a.no_answer ? "Waiting, no answer yet" : "Waiting for you";
  return a.label || a.status;
}

function memorialFacts(a) {
  const m = a.memorial;
  return `${fact("For", `Memorial prayers for ${esc(m.departed_name)}`)}
    ${fact("Dates", m.dates.map(d => `${esc(dayText(d.date, d.parsi))}${d.label ? ` <span class="meta">(${esc(d.label)})</span>` : ""}`)
      .join("<br>"))}`;
}

function singleFacts(a) {
  const when = whenText(a);
  return `${fact("Day", esc(dayText(a.date, a.parsi)))}
    ${when ? fact("Geh or time", esc(when)) : ""}
    ${a.repeat ? fact("Repeats", esc(repeatText(a.repeat).replace(/^Repeats /, ""))) : ""}`;
}

function linksHtml(a) {
  const m = made.get(a.id) || {};
  const btns = [];
  if (m.booking_id) btns.push(`<button type="button" class="secondary small" data-go="#/booking/${m.agyary_id}/${m.booking_id}">Open the booking</button>`);
  if (m.machi_id) btns.push(`<button type="button" class="secondary small" data-go="#/machi/${m.agyary_id}/${m.machi_id}">Open the machi</button>`);
  if (m.memorial_id) btns.push(`<button type="button" class="secondary small" data-go="#/memorial/${m.memorial_id}">Open the memorial</button>`);
  const cust = m.customer_id || a.customer_id;
  if (cust) btns.push(`<button type="button" class="ghost small" data-go="#/behdins/${cust}">Open ${esc(a.person.first_name || "them")} in Behdins</button>`);
  return btns.length ? `<div class="stack" style="margin-top:10px">${btns.join("")}</div>` : "";
}

function cardHtml(a) {
  const waiting = a.status === "waiting";
  return `<div class="card ask-card" data-ask="${a.id}">
    <p style="margin:0 0 4px"><b>${esc(statusLine(a))}</b></p>
    <h2 style="margin:0">${esc(a.service.name)}${a.purpose_label ? ` <span class="meta" style="font-weight:400">${esc(a.purpose_label)}</span>` : ""}</h2>
    <p class="meta" style="margin:2px 0 8px">${esc(a.person.first_name || "A person")} asked ${esc(ago(a.created_at))}</p>
    ${a.kind === "memorial" && a.memorial ? memorialFacts(a) : singleFacts(a)}
    ${fact("Where", a.where === "home" ? `At home${a.area ? `, ${esc(a.area)}` : ""}` : "At the agyari")}
    ${a.names.length ? fact("Names to pray", a.names.map(nameText).join("<br>")) : ""}
    ${a.note ? fact("Note", esc(a.note)) : ""}
    ${a.status === "rejected" && a.reject_reason ? fact("Your reason", esc(a.reject_reason)) : ""}
    <p class="meta" role="alert" data-msg style="margin:6px 0 0"></p>
    ${waiting ? `<div class="stack" style="margin-top:10px">
        <button type="button" data-accept>Accept</button>
        <button type="button" class="secondary" data-reject>Can't take it</button>
      </div>` : a.status === "accepted" ? linksHtml(a) : ""}
  </div>`;
}

function sectionHtml(asks, takes) {
  const waiting = asks.filter(a => a.status === "waiting");
  const answered = asks.filter(a => a.status !== "waiting");
  return `<h2 style="margin:0 0 4px">Asks from people</h2>
    <p class="meta" style="margin:0 0 12px">People ask you for a prayer here. Their number is shared with you only when you accept.</p>
    ${waiting.length ? waiting.map(cardHtml).join("")
      : `<div class="card"><p style="margin:0">${takes ? "No asks are waiting for you." : "No asks yet. You are not taking asks from people: switch it on in Settings."}</p></div>`}
    ${answered.length ? `<h2 style="margin:16px 0 8px">Answered asks</h2>${answered.slice(0, SHOWN_ANSWERED).map(cardHtml).join("")}` : ""}
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
    box.innerHTML = `<div class="card"><h2>Asks from people</h2><p class="meta">Couldn't load this: ${esc(e.message)}</p></div>`;
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

function confirmAccept(a, agyary, msg, update, alive) {
  const sheet = openSheet({
    title: `Accept ${a.service.name}?`,
    html: `<p style="margin-top:0">${esc(a.person.first_name || "The person")}'s name and number will be added to your
        behdins and this goes into your diary.</p>
      <p class="meta" role="alert" data-err style="margin:6px 0 0"></p>
      <div class="stack" style="margin-top:12px">
        <button type="button" data-yes>Accept</button>
        <button type="button" class="ghost" data-no>Not yet</button>
      </div>`,
  });
  const body = sheet.body;
  body.querySelector("[data-no]").onclick = sheet.close;
  body.querySelector("[data-yes]").onclick = async (ev) => {
    const btn = ev.currentTarget;
    if (btn.disabled) return;
    btn.disabled = true;
    let res;
    try {
      res = await acceptAsk(agyary.id, a.id);
    } catch (e) {
      sheet.close();
      // The server says why in plain words ("that geh is already yours"); the card stays as it was.
      if (alive() && msg && msg.isConnected) msg.textContent = e.message;
      else showInfo(e.message);
      return;
    }
    sheet.close();
    made.set(a.id, { ...res, agyary_id: agyary.id });
    update(res.ask);
    refreshAfterAction();
    showInfo(`Accepted. ${a.person.first_name || "They"} is in your behdins and it is in your diary.`);
  };
}

function confirmReject(a, agyary, update, alive) {
  const sheet = openSheet({
    title: "Can't take it?",
    html: `<p class="meta" style="margin-top:0">${esc(a.person.first_name || "The person")} is told, and can ask another agyari.</p>
      <label for="askReason">Reason <span class="meta">(optional, 100 letters at most)</span></label>
      <textarea id="askReason" rows="2" maxlength="100" placeholder="e.g. No mobed free that day"></textarea>
      <p class="meta" role="alert" data-err style="margin:6px 0 0"></p>
      <div class="stack" style="margin-top:12px">
        <button type="button" class="danger" data-yes>Can't take it</button>
        <button type="button" class="ghost" data-no>Keep it</button>
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
    showInfo(`Done. ${a.person.first_name || "The person"} is told.`);
  };
}
