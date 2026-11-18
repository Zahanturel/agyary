"use strict";

/**
 * The Requests tab (DECISIONS D10 and its 18 Nov amendment; Phase 2 Step 5): a
 * Doongerwadi or prayer hall asks this mobed's fire temple for the prayers.
 *
 *  - The list: what waits for their answer (the departed's prayed name, the
 *    place, four days or one, the Geh-saarnu and Uthamna, mobeds
 *    wanted, which fire temple it was sent to, when), and "Earlier": accepted
 *    (by whom), declined, withdrawn.
 *  - One request: Accept (with the tick "Share my name and number", on) or
 *    Decline (with an optional reason). The family's name and number are not
 *    shown until this mobed accepts, and then only to them.
 *  - Accepting puts the family in their own Behdins and the prayers on their
 *    calendar, and opens the memorial form filled in, to check and save. The
 *    request then shows the family's contact with "Message the family on
 *    WhatsApp" (their own WhatsApp, a message ready to change) and "Call".
 *
 * With the share tick, accepting can also send WhatsApp messages from Mobed
 * Diary's own number (Step 5b, once Meta approves them): what went, or why not,
 * is said after accepting and on the request. A confirmed panthaky sees here
 * how many of the agyari's mobeds were asked on WhatsApp when the request came
 * and how many are going, and opens who is going (screens/callout.js).
 */

import { myRequests, myRequest, acceptRequest, declineRequest } from "../api.js";
import { state, saveSession } from "../state.js";
import {
  chrome, mainEl, showFab, showError, showInfo, refreshHeader, loading, screenFailed, openSheet, flashInfo, flashError,
} from "../ui.js";
import { esc, gregLabel, istHm, istYmd, todayIst } from "../util.js";
import { navigate, navGuard } from "../router.js";
import { flagProblems } from "../fielderrors.js";
import { refreshRequestCount, paintRequestCount } from "../requests_count.js";
import { memorialFromRequest } from "./memorial_new.js";

// --- Words ------------------------------------------------------------------------

function when(iso) {
  const day = istYmd(iso);
  return day === todayIst() ? `today, ${istHm(iso)}` : `${gregLabel(day)}, ${istHm(iso)}`;
}

function clock(hhmm) {
  const [h, m] = hhmm.split(":").map(Number);
  return `${h % 12 || 12}:${String(m).padStart(2, "0")} ${h < 12 ? "am" : "pm"}`;
}

function gehSaarnuText(g) {
  return g ? `${gregLabel(g.date)}, ${g.geh_name} geh` : "Not given";
}

function uthamnaText(u) {
  if (!u) return "Not given";
  return u.time ? `${gregLabel(u.date)}, ${clock(u.time)}` : `${gregLabel(u.date)} (time not given)`;
}

function placeText(q) {
  const p = q.funeral_place;
  // "Doongerwadi" once: the kind only when the name does not already say it.
  const kind = p.kind_label && !p.name.toLowerCase().includes(p.kind_label.toLowerCase()) ? p.kind_label : "";
  const town = p.city && !p.name.toLowerCase().includes(p.city.toLowerCase()) ? p.city : "";
  return [p.name, kind, town].filter(Boolean).join(" · ");
}

/** Where an answered request stands, for the list and the page. */
function stateText(q) {
  if (q.status === "accepted" || q.status === "taken") {
    return q.accepted_by_me ? "Accepted by you" : q.accepted_by ? `Accepted by ${q.accepted_by}` : "Accepted";
  }
  if (q.status === "declined") return q.declined_by_me ? "Declined by you" : q.declined_by ? `Declined by ${q.declined_by}` : "Declined";
  if (q.status === "withdrawn") return `Withdrawn by ${q.funeral_place.name}`;
  return "Waiting for an answer";
}

function fact(label, value) {
  return `<div class="fact"><div class="fl">${esc(label)}</div><div class="fv">${value}</div></div>`;
}

function factsHtml(q) {
  return `
    ${fact("Place", esc(placeText(q)))}
    ${fact("Died", `${esc(gregLabel(q.death.date))}<br><span class="meta">${esc(q.death.label)}</span>`)}
    ${fact("Obsequies", esc(q.obsequies_label))}
    ${fact("Geh-saarnu", esc(gehSaarnuText(q.geh_saarnu)))}
    ${fact("Uthamna", esc(uthamnaText(q.uthamna)))}
    ${q.mobeds_wanted ? fact("Mobeds wanted", String(q.mobeds_wanted)) : ""}
    ${fact("Sent to", `${esc(q.agyari.name)}<br><span class="meta">${esc(when(q.sent_at))}</span>`)}`;
}

// --- The list ---------------------------------------------------------------------

function waitingCardHtml(q) {
  return `<div class="card search-result req-card" data-rid="${q.id}">
      <h2>${esc(q.prayed_name)}</h2>
      <p class="meta" style="margin:0">${esc(placeText(q))}</p>
      <p style="margin:6px 0 0">${esc(q.obsequies_label)}${q.mobeds_wanted
        ? ` · ${q.mobeds_wanted} mobed${q.mobeds_wanted === 1 ? "" : "s"} wanted` : ""}</p>
      <p style="margin:2px 0 0">Geh-saarnu: ${esc(gehSaarnuText(q.geh_saarnu))}</p>
      <p style="margin:2px 0 0">Uthamna: ${esc(uthamnaText(q.uthamna))}</p>
      <p class="meta" style="margin:6px 0 0">Sent to ${esc(q.agyari.name)}, ${esc(when(q.sent_at))}</p>
    </div>`;
}

function earlierRowHtml(q) {
  return `<div class="search-result" data-rid="${q.id}">
      <div><strong>${esc(q.prayed_name)}</strong></div>
      <div class="addr">${q.status === "withdrawn" ? "" : `${esc(q.funeral_place.name)} · `}${esc(stateText(q))}</div>
    </div>`;
}

export async function renderRequests() {
  chrome(true);
  refreshHeader();
  showFab(false);
  loading();
  const alive = navGuard();
  let got;
  try {
    got = await myRequests();
  } catch (e) {
    if (!alive()) return;
    return screenFailed("Couldn't load your requests: " + e.message, renderRequests);
  }
  if (!alive()) return;
  paintRequestCount(got.waiting.length);
  mainEl.innerHTML = `
    <h2 style="margin:0 0 4px">Requests</h2>
    <p class="meta" style="margin:0 0 12px">When a Doongerwadi or prayer hall asks your fire temple for the prayers,
      it is here. The family's name and number are shown to the one who accepts.</p>
    ${got.waiting.length ? got.waiting.map(waitingCardHtml).join("")
      : `<div class="card"><p style="margin:0">Nothing is waiting for you.</p></div>`}
    ${got.earlier.length ? `<h2 style="margin:20px 0 8px">Earlier</h2>
      ${got.earlier.map(earlierRowHtml).join("")}` : ""}`;
  mainEl.querySelectorAll("[data-rid]").forEach(el => {
    el.onclick = () => navigate(`#/requests/${el.dataset.rid}`);
  });
}

// --- One request ------------------------------------------------------------------

function waLink(phone, text) {
  const digits = String(phone || "").replace(/\D/g, "");
  return `https://wa.me/${digits}?text=${encodeURIComponent(text)}`;
}

function familyCardHtml(q) {
  const c = q.family_contact;
  return `
    <div class="card">
      <h2>The family of ${esc(q.prayed_name)}</h2>
      ${fact("Family contact", `${esc(c.name)}<br><a class="tel" href="tel:${esc(c.phone)}">${esc(c.phone)}</a>`)}
      <label for="rqMsg" style="margin-top:10px">Message to the family</label>
      <textarea id="rqMsg" rows="7" maxlength="1000">${esc(q.family_message)}</textarea>
      <p class="meta" style="margin:6px 0 0">Change it as you like. It opens in your own WhatsApp, ready to send.</p>
      <div class="action-bar">
        <a class="button" id="rqWa" href="${esc(waLink(c.phone, q.family_message))}" target="_blank"
          rel="noopener">Message the family on WhatsApp</a>
        <a class="button secondary" id="rqCall" href="tel:${esc(c.phone)}">Call</a>
      </div>
      <p class="meta" style="margin:10px 0 0">${q.shared_contact
        ? `You shared your name and number with ${esc(q.funeral_place.name)}.`
        : `You did not share your number with ${esc(q.funeral_place.name)}: they see your name and fire temple.`}</p>
      ${whatsappHtml(q.whatsapp)}
    </div>
    <div class="card">
      <h2>In your book</h2>
      <p class="meta" style="margin:0">${q.customer_id
        ? `${esc(c.name)} is in your Behdins, with reminders off until you ask them.`
        : `${esc(c.name)} is no longer in your Behdins.`}</p>
      <div class="stack" style="margin-top:10px">
        ${q.memorial_id ? `<button type="button" class="secondary" id="rqMemorial">Open the memorial</button>`
          : q.customer_id ? `<button type="button" id="rqMakeMemorial">Make the memorial</button>` : ""}
        ${q.customer_id ? `<button type="button" class="ghost" id="rqBehdin">Open ${esc(c.name)}</button>` : ""}
      </div>
    </div>`;
}

/** What Mobed Diary's own WhatsApp sent on accepting (Step 5b), if anything. */
function whatsappHtml(wa) {
  if (!wa || wa.state === "not_shared") return "";
  const failed = (wa.items || []).filter(i => i.status === "failed");
  return `<p class="meta" style="margin:6px 0 0">${wa.state === "failed" ? "" : esc(wa.message || "")}</p>
    ${failed.map(i => `<p class="meta" style="margin:4px 0 0"><b>The WhatsApp message to ${esc(i.to_words)} could not be
      sent:</b> ${esc(i.why || "")}</p>`).join("")}
    ${wa.family_note ? `<p class="meta" style="margin:4px 0 0">${esc(wa.family_note)}</p>` : ""}`;
}

/** A confirmed panthaky of the fire temple: who was asked on WhatsApp when the
 *  request came, and who is going (the first yeses go, 19 Nov 2026). */
function calloutCardHtml(q) {
  const wa = q.callout_whatsapp || { on: false, why_not: "" };
  const c = q.callout || { asked: 0, yes: 0, going: 0, wanted: 2 };
  const words = c.asked
    ? `${c.asked} ${c.asked === 1 ? "mobed was" : "mobeds were"} asked on WhatsApp. <b>${c.going} of ${c.wanted}
        going</b>${c.yes > c.going ? `; ${c.yes - c.going} more said yes and were thanked` : ""}.`
    : wa.on ? "Nobody on your list has been asked on WhatsApp for this request."
      : `<b>${esc(wa.why_not)}</b> So nobody has been asked on WhatsApp yet.`;
  return `<div class="card">
      <h2>Mobeds to pray</h2>
      <p style="margin:0">${words}</p>
      <p class="meta" style="margin:6px 0 0">The first ${c.wanted === 1 ? "mobed" : `${c.wanted} mobeds`} of
        ${esc(q.agyari.name)} to say yes go, and get the details and the family's contact on WhatsApp.</p>
      <div class="action-bar"><button type="button" class="secondary" id="rqCallout">Who is going</button></div>
    </div>`;
}

export async function renderRequest({ id }) {
  chrome(true);
  refreshHeader();
  showFab(false);
  loading();
  const alive = navGuard();
  let q;
  try {
    q = (await myRequest(id)).request;
  } catch (e) {
    if (!alive()) return;
    if (e.status === 404) return screenFailed("That request could not be found.");
    return screenFailed("Couldn't open the request: " + e.message, () => renderRequest({ id }));
  }
  if (!alive()) return;
  const waiting = q.status === "waiting";
  mainEl.innerHTML = `
    ${q.accepted_by_me ? familyCardHtml(q) : ""}
    <div class="card">
      <h2>${esc(q.prayed_name)}</h2>
      <p style="margin:0"><b>${esc(stateText(q))}</b>${q.decided_at && !waiting
        ? `<span class="meta">, ${esc(when(q.decided_at))}</span>` : ""}</p>
      ${q.decline_reason ? `<p class="meta" style="margin:4px 0 0">Your reason: ${esc(q.decline_reason)}</p>` : ""}
      ${!waiting && !q.accepted_by_me ? `<p class="meta" style="margin:4px 0 0">Nothing more is needed from you.</p>` : ""}
      <div style="margin-top:10px">${factsHtml(q)}</div>
      ${waiting ? `<p class="meta" style="margin:10px 0 0">The family's name and number are shown to the one who
        accepts. The first to accept takes it.</p>
      <div class="action-bar">
        <button type="button" class="secondary" id="rqDecline">Decline</button>
        <button type="button" id="rqAccept">Accept</button>
      </div>` : ""}
    </div>
    ${q.may_call_out ? calloutCardHtml(q) : ""}`;

  const on = (sel, fn) => { const el = document.getElementById(sel); if (el) el.onclick = fn; };
  on("rqCallout", () => navigate(`#/requests/${q.id}/callout`));
  on("rqAccept", () => confirmAccept(q));
  on("rqDecline", () => confirmDecline(q));
  if (!q.accepted_by_me) return;
  const msg = document.getElementById("rqMsg");
  const wa = document.getElementById("rqWa");
  msg.addEventListener("input", () => { wa.href = waLink(q.family_contact.phone, msg.value.trim()); });
  on("rqMemorial", () => navigate(`#/memorial/${q.memorial_id}`));
  on("rqMakeMemorial", () => openMemorialForm(q, q.customer_id));
  on("rqBehdin", () => { useFireTempleOf(q); navigate(`#/behdins/${q.customer_id}`); });
}

/** The behdin and their events are at the request's fire temple: the screens
 *  that follow work in that one. (Almost every mobed has only one.) */
function useFireTempleOf(q) {
  const aid = q.agyari.id;
  if (aid !== state.currentAgyaryId && (state.user.agyaries || []).some(a => a.id === aid)) {
    state.currentAgyaryId = aid;
    saveSession();
    refreshHeader();
  }
}

function openMemorialForm(q, customerId) {
  useFireTempleOf(q);
  memorialFromRequest(customerId, { id: q.id, place: q.funeral_place.name, prefill: q.memorial_prefill });
  navigate(`#/behdins/${customerId}/memorials/new`);
}

/** After an answer the request may have been taken by someone else meanwhile:
 *  the page is drawn again, and what happened is said over it. */
async function redrawSaying(q, message, isError) {
  await renderRequest({ id: q.id });
  refreshRequestCount();
  (isError ? showError : showInfo)(message);
}

function acceptedWords(res) {
  const q = res.request;
  const words = [`Accepted. ${q.family_contact.name} is in your Behdins, with reminders off.`];
  const put = res.events.map(e => e.what);
  if (put.length) words.push(`${put.join(" and ")} ${put.length === 1 ? "is" : "are"} on your calendar.`);
  res.events.filter(e => e.time_guessed).forEach(e =>
    words.push(`No time was given for the ${e.what}: it is at ${clock(e.time)}; change it when you know.`));
  res.events.filter(e => e.conflict).forEach(e => words.push(`You already have something at the time of the ${e.what}.`));
  res.skipped.forEach(s => words.push(`The ${s.what} is not on your calendar: ${s.why}`));
  return words.join(" ");
}

/** What to add about Mobed Diary's own WhatsApp messages after accepting. */
function whatsappWords(wa) {
  if (!wa || wa.state === "not_shared") return { text: "" };
  if (wa.state === "off") return { text: `${wa.message} Nothing was sent from Mobed Diary's WhatsApp.` };
  return { text: wa.message || "", error: wa.state === "failed" };
}

function confirmAccept(q) {
  const place = q.funeral_place.name;
  const sheet = openSheet({
    title: `Accept the prayers for ${q.prayed_name}?`,
    html: `
      <p class="meta" style="margin-top:0">For ${esc(q.agyari.name)}. Once you accept:</p>
      <ul class="meta" style="margin:0 0 10px;padding-left:20px">
        <li>The family's contact goes into your Behdins, with reminders off until you ask them.</li>
        <li>The Geh-saarnu and the Uthamna go on your calendar.</li>
        <li>The memorial form opens, filled in, for you to check and save.</li>
      </ul>
      <div class="check-row" id="rqShareRow"><input type="checkbox" id="rqShare" checked>
        <label for="rqShare">Share my name and number with ${esc(place)}</label></div>
      <p class="meta" style="margin:4px 0 0">So they can call you about the prayers. Untick it and they see only your
        name and fire temple.</p>
      <p class="meta" data-msg role="alert" style="margin:6px 0 0"></p>
      <div class="stack" style="margin-top:12px">
        <button type="button" data-yes>Accept</button>
        <button type="button" class="ghost" data-no>Cancel</button>
      </div>`,
  });
  const body = sheet.body;
  body.querySelector("[data-no]").onclick = sheet.close;
  body.querySelector("[data-yes]").onclick = async (ev) => {
    const btn = ev.currentTarget;
    if (btn.disabled) return;
    btn.disabled = true;
    body.querySelector("[data-msg]").textContent = "";
    let res;
    try {
      res = await acceptRequest(q.id, body.querySelector("#rqShare").checked);
    } catch (e) {
      if (e.status === 409 || e.status === 404) {
        // Taken, withdrawn or declined meanwhile: say so over the page as it is now.
        sheet.close();
        return redrawSaying(q, e.message, true);
      }
      btn.disabled = false;
      body.querySelector("[data-msg]").textContent = e.message;   // in the sheet, where they are looking
      return;
    }
    sheet.close();
    refreshRequestCount();
    const wa = whatsappWords(res.whatsapp);
    (wa.error ? flashError : flashInfo)([acceptedWords(res), wa.text].filter(Boolean).join(" "));
    openMemorialForm(res.request, res.customer_id);
  };
}

function confirmDecline(q) {
  const sheet = openSheet({
    title: `Decline the request for ${q.prayed_name}?`,
    html: `
      <p class="meta" style="margin-top:0">${esc(q.funeral_place.name)} is told that ${esc(q.agyari.name)} cannot
        take it, and can ask another fire temple. It is then closed for everyone asked here.</p>
      <label for="rqReason">Reason <span class="meta">(optional, for ${esc(q.funeral_place.name)})</span></label>
      <textarea id="rqReason" rows="2" maxlength="200" placeholder="e.g. No mobed free on that day"></textarea>
      <p class="meta" data-msg role="alert" style="margin:6px 0 0"></p>
      <div class="stack" style="margin-top:12px">
        <button type="button" class="danger" data-yes>Decline</button>
        <button type="button" class="ghost" data-no>Keep it</button>
      </div>`,
  });
  const body = sheet.body;
  body.querySelector("[data-no]").onclick = sheet.close;
  body.querySelector("[data-yes]").onclick = async (ev) => {
    const btn = ev.currentTarget;
    if (btn.disabled) return;
    btn.disabled = true;
    body.querySelector("[data-msg]").textContent = "";
    try {
      await declineRequest(q.id, body.querySelector("#rqReason").value.trim());
    } catch (e) {
      btn.disabled = false;
      if (e.field === "reason") return flagProblems(body, [{ target: "#rqReason", message: e.message }]);
      if (e.status === 409 || e.status === 404) {
        sheet.close();
        return redrawSaying(q, e.message, true);
      }
      body.querySelector("[data-msg]").textContent = e.message;
      return;
    }
    sheet.close();
    redrawSaying(q, `Declined. ${q.funeral_place.name} is told and can ask another fire temple.`, false);
  };
}
