"use strict";

/**
 * The Requests tab (DECISIONS D10, changed 21 Nov 2026; docs/phase2-requests-redesign.md;
 * R3.1 step 4): a Doongerwadi or prayer hall asks this mobed's fire temple for the prayers.
 *
 *  - The list: what waits (the departed's prayed name, the place, four days or one, the
 *    Geh-saarnu and Uthamna, mobeds wanted, which fire temple it was sent to, when), and
 *    "Earlier": all set, accepted (by whom), declined, withdrawn. Each says where it stands:
 *    "Waiting for you" (a panthaky's, not taken yet), "Finding mobeds: 1 of 2", "All set",
 *    and for an app mobed "Asked: can you pray?", "You are going", "Standby".
 *  - A request's page, for a confirmed panthaky the request reached and for the admin: the
 *    "Who will pray: n of N" board. The prayers without the family's name or number; a place
 *    per mobed wanted, filled or open, and the standbys in the order they said yes; Ask
 *    everyone and I'll pray, one tap each; the fire temple's mobeds, each with where they
 *    stand for this request and Call and WhatsApp from the panthaky's own phone (a message
 *    ready to edit, no family details); and "We can't take this" at the very bottom (the
 *    panthaky's decline, reason optional). The panthaky's first action takes the request
 *    for the fire temple: there is no Accept any more. While it waits and is on screen, the
 *    board is read again every 10 seconds. While someone is going and places are still
 *    empty, "Confirm with who's going" (a sheet first) makes it all set with fewer.
 *  - A request's page, for an app mobed of the fire temple it reached: the prayers (no family
 *    details, nobody else's number), "1 of 2 going", where they stand, and I can pray / Not
 *    this time until they have answered, here or on WhatsApp (the first answer counts).
 *  - All set (R3.1 step 5), for those it put the family in the book of (the panthaky on the
 *    board, a going app mobed on their card; the server's `all_set`): "All set: 2 going"
 *    (or confirmed with fewer), the family's contact with Call and WhatsApp (a message ready
 *    to edit), who is praying and the panthaky with Call and WhatsApp, and the memorial one
 *    tap away (Make or Open the memorial, Open in Behdins). Everyone else asked reads who is
 *    going (the board's names, or for an app mobed the count), never a contact.
 *  - A request accepted the old way (before R3.1) reads as it did (D8): for the one who
 *    accepted, the family's contact with "Message the family on WhatsApp" and "Call", and
 *    their own behdin and memorial.
 */

import {
  myRequests, myRequest, answerRequest, declineRequest, requestBoard, boardAskEveryone, boardPrayMyself,
  boardCallResult, boardConfirmShort,
} from "../api.js";
import { state, saveSession } from "../state.js";
import {
  chrome, mainEl, showFab, showError, showInfo, refreshHeader, loading, screenFailed, openSheet, toTop,
} from "../ui.js";
import { esc, gregLabel, istHm, istYmd, todayIst } from "../util.js";
import { navigate, navGuard } from "../router.js";
import { flagProblems } from "../fielderrors.js";
import { refreshRequestCount } from "../requests_count.js";
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

/** A funeral place: {name, kind_label?, city}. */
function placeText(p) {
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
  if (q.status === "all_set") return "All set";
  return "Waiting for an answer";
}

function fact(label, value) {
  return `<div class="fact"><div class="fl">${esc(label)}</div><div class="fv">${value}</div></div>`;
}

function factsHtml(q) {
  return `
    ${fact("Place", esc(placeText(q.funeral_place)))}
    ${fact("Died", `${esc(gregLabel(q.death.date))}<br><span class="meta">${esc(q.death.label)}</span>`)}
    ${fact("Obsequies", esc(q.obsequies_label))}
    ${fact("Geh-saarnu", esc(gehSaarnuText(q.geh_saarnu)))}
    ${fact("Uthamna", esc(uthamnaText(q.uthamna)))}
    ${q.mobeds_wanted ? fact("Mobeds wanted", String(q.mobeds_wanted)) : ""}
    ${fact("Sent to", `${esc(q.agyari.name)}<br><span class="meta">${esc(when(q.sent_at))}</span>`)}`;
}

// --- The list ---------------------------------------------------------------------

/** Where a request stands, in a few words: for a confirmed panthaky "Waiting for you" until
 *  the board's first action takes it (as the red count counts it), then "Finding mobeds: 1 of
 *  2"; for an app mobed their own answer; "All set"; and the old states as they were. */
function standsText(q) {
  if (q.status === "all_set") return allSetStands(q);
  if (q.my_answer) return BOARD.has(q.status) ? myHeadline(q) : stateText(q);
  if (q.status === "waiting") {
    const n = q.places || { going: 0, wanted: 0 };
    return q.taken === false ? "Waiting for you" : `Finding mobeds: ${n.going} of ${n.wanted}`;
  }
  return stateText(q);
}

/** An all-set request in a few words: "All set: 2 going", and whether this person is one of
 *  them or on standby. */
function allSetStands(q) {
  const a = q.all_set;
  const n = a ? a.going.length : (q.places || { going: 0 }).going;
  const mine = q.my_answer ? q.my_answer.state : "";
  const me = mine === "going" || (a && a.going.some(g => g.is_me));
  return `All set: ${n} going${me ? ", including you" : mine === "standby" ? ", you are on standby" : ""}`;
}

function waitingCardHtml(q) {
  return `<div class="card search-result req-card" data-rid="${q.id}">
      <p style="margin:0 0 4px"><b>${esc(standsText(q))}</b></p>
      <h2>${esc(q.prayed_name)}</h2>
      <p class="meta" style="margin:0">${esc(placeText(q.funeral_place))}</p>
      <p style="margin:6px 0 0">${esc(q.obsequies_label)}${q.mobeds_wanted
        ? ` · ${q.mobeds_wanted} mobed${q.mobeds_wanted === 1 ? "" : "s"} wanted` : ""}</p>
      <p style="margin:2px 0 0">Geh-saarnu: ${esc(gehSaarnuText(q.geh_saarnu))}</p>
      <p style="margin:2px 0 0">Uthamna: ${esc(uthamnaText(q.uthamna))}</p>
      <p class="meta" style="margin:6px 0 0">Sent to ${esc(q.agyari.name)}, ${esc(when(q.sent_at))}</p>
    </div>`;
}

function earlierRowHtml(q) {
  // All set, with the family in their book and no memorial made from it yet: a hint that
  // it is one tap away on the request.
  const a = q.status === "all_set" ? q.all_set : null;
  const hint = a && a.customer_id && !a.memorial_id;
  return `<div class="search-result" data-rid="${q.id}">
      <div><strong>${esc(q.prayed_name)}</strong></div>
      <div class="addr">${q.status === "withdrawn" ? "" : `${esc(q.funeral_place.name)} · `}${esc(standsText(q))}</div>
      ${hint ? `<div class="meta">You can make the memorial</div>` : ""}
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
  // The server's count, not the list's length: a request taken on the board, or answered,
  // still waits here but no longer waits for this person.
  refreshRequestCount();
  mainEl.innerHTML = `
    <h2 style="margin:0 0 4px">Requests</h2>
    <p class="meta" style="margin:0 0 12px">When a Doongerwadi or prayer hall asks your fire temple for the prayers,
      it is here. The family's name and number are not shown until enough mobeds are going.</p>
    ${got.waiting.length ? got.waiting.map(waitingCardHtml).join("")
      : `<div class="card"><p style="margin:0">Nothing is waiting for you.</p></div>`}
    ${got.earlier.length ? `<h2 style="margin:20px 0 8px">Earlier</h2>
      ${got.earlier.map(earlierRowHtml).join("")}` : ""}`;
  mainEl.querySelectorAll("[data-rid]").forEach(el => {
    el.onclick = () => navigate(`#/requests/${el.dataset.rid}`);
  });
}

// --- One request ------------------------------------------------------------------

/** Statuses that have a board on the page; the others read as before. */
const BOARD = new Set(["waiting", "all_set"]);

export async function renderRequest({ id }) {
  chrome(true);
  refreshHeader();
  showFab(false);
  loading();
  const alive = navGuard();
  onScreen = null;    // a board drawn before this is no longer read or answered
  let q = null;
  try {
    q = (await myRequest(id)).request;
  } catch (e) {
    if (!alive()) return;
    // A 404 may still be the admin, whom a request never reaches: they have its board only.
    if (e.status !== 404) return screenFailed("Couldn't open the request: " + e.message, () => renderRequest({ id }));
  }
  if (!alive()) return;
  if (q && (q.my_answer || !BOARD.has(q.status))) return drawFor(q, alive);
  return openBoard(id, q, alive);
}

/** The page of a request as it stands for this person. funeral_answers.serialize gives
 *  `my_answer` only to an app mobed the request reached (not the fire temple's confirmed
 *  panthaky, who has the board with the admin): they answer for themselves. */
function drawFor(q, alive) {
  // All set, and the family is in their book (a going app mobed): the contacts and the memorial.
  if (q.status === "all_set" && q.all_set) return drawAllSet(q);
  return q.my_answer && BOARD.has(q.status) ? drawAnswerCard(q, alive) : drawRequest(q, alive);
}

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

/** A confirmed panthaky of the fire temple, on a request accepted the old way (or closed):
 *  who was asked on WhatsApp when it came, and who is going (the first yeses went, 19 Nov
 *  2026). The names come from the board (showWhoPrays), where the old "Who is going" screen
 *  was. */
function calloutCardHtml(q) {
  const wa = q.callout_whatsapp || { on: false, why_not: "" };
  const c = q.callout || { asked: 0, yes: 0, going: 0, wanted: 2 };
  const words = c.asked
    ? `${c.asked} ${c.asked === 1 ? "mobed was" : "mobeds were"} asked on WhatsApp. <b>${c.going} of ${c.wanted}
        going</b>${c.yes > c.going ? `; ${c.yes - c.going} more said yes but ${c.yes - c.going === 1 ? "is" : "are"}
        not needed` : ""}.`
    : wa.on ? "Nobody on your list has been asked on WhatsApp for this request."
      : `<b>${esc(wa.why_not)}</b> So nobody has been asked on WhatsApp yet.`;
  return `<div class="card">
      <h2>Mobeds to pray</h2>
      <p style="margin:0">${words}</p>
      <p class="meta" style="margin:6px 0 0">${c.wanted === 1
        ? `The first mobed of ${esc(q.agyari.name)} to say yes goes, and gets`
        : `The first ${c.wanted} mobeds of ${esc(q.agyari.name)} to say yes go, and get`} the details and the family's
        contact on WhatsApp.</p>
      <div id="rqWhoPrays"></div>
    </div>`;
}

/** The names going (and on standby) under calloutCardHtml's counts, from the board. */
async function showWhoPrays(q, alive) {
  let b = null;
  try {
    b = await requestBoard(q.id);
  } catch (e) {
    b = null;
  }
  const box = alive() ? document.getElementById("rqWhoPrays") : null;
  if (!box) return;
  box.innerHTML = b
    ? `${slotsHtml(b, { open: q.status === "accepted" || q.status === "taken" })}${standbysHtml(b)}`
    : `<p class="meta" style="margin:8px 0 0">Couldn't load who is going just now.</p>`;
}

/** The page as it was before R3.1: a request accepted the old way, declined or withdrawn
 *  (and a request an app mobed can no longer answer). */
function drawRequest(q, alive) {
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
    </div>
    ${q.may_call_out && !waiting ? calloutCardHtml(q) : ""}`;

  const on = (sel, fn) => { const el = document.getElementById(sel); if (el) el.onclick = fn; };
  if (q.may_call_out && !waiting) showWhoPrays(q, alive);
  if (!q.accepted_by_me) return;
  const msg = document.getElementById("rqMsg");
  const wa = document.getElementById("rqWa");
  msg.addEventListener("input", () => { wa.href = waLink(q.family_contact.phone, msg.value.trim()); });
  on("rqMemorial", () => navigate(`#/memorial/${q.memorial_id}`));
  on("rqMakeMemorial", () => openMemorialForm(requestCtx(q), q.customer_id, q.memorial_prefill));
  on("rqBehdin", () => { useFireTempleOf(q); navigate(`#/behdins/${q.customer_id}`); });
}

/** The behdin and their events are at the request's fire temple: the screens
 *  that follow work in that one. (Almost every mobed has only one.) */
function useFireTemple(aid) {
  if (aid !== state.currentAgyaryId && (state.user.agyaries || []).some(a => a.id === aid)) {
    state.currentAgyaryId = aid;
    saveSession();
    refreshHeader();
  }
}

function useFireTempleOf(q) {
  useFireTemple(q.agyari.id);
}

/** What the memorial form needs to know of the request it is made from. */
function requestCtx(q) {
  return { rid: q.id, aid: q.agyari.id, place: q.funeral_place.name };
}

/** The memorial form for their own record of the family, filled in from the request; the
 *  memorial saved is linked to the request (their own book's row, at All set). */
function openMemorialForm({ rid, aid, place }, customerId, prefill) {
  useFireTemple(aid);
  memorialFromRequest(customerId, { id: rid, place, prefill });
  navigate(`#/behdins/${customerId}/memorials/new`);
}

/** After an answer the request may have changed meanwhile: the page is drawn again, and
 *  what happened is said over it. Nothing, if the mobed has gone to another screen. */
async function redrawSaying(q, message, isError, alive) {
  if (!alive()) return;
  await renderRequest({ id: q.id });
  refreshRequestCount();
  (isError ? showError : showInfo)(message);
}

// --- An app mobed it reached: I can pray / Not this time (R3.1) -----------------------

// As the server words them (prayer_callout.GOING_WORDS, funeral_whatsapp.ENOUGH_TEXT).
const GOING_WORDS = "You are going. You will get the details once enough mobeds are going.";
const STANDBY_WORDS = "Thank you. Enough mobeds are going this time. If a place opens, we may ask you again.";

/** An app mobed's own request, in a few words, for the list and the page. */
function myHeadline(q) {
  const mine = q.my_answer.state;
  if (q.status === "all_set") return allSetStands(q);
  return { going: "You are going", standby: "Standby", said_no: "You said not this time" }[mine]
    || "Asked: can you pray?";
}

/** Where they stand, in a sentence. */
function myWords(q) {
  const mine = q.my_answer.state;
  if (mine === "going") return q.status === "all_set" ? "Enough mobeds are going, and you are one of them." : GOING_WORDS;
  if (mine === "standby") return STANDBY_WORDS;
  if (mine === "said_no") return "You said not this time. Nothing more is needed from you.";
  return q.status === "all_set"
    ? "Enough mobeds are going already. If you can pray too, you are kept on standby in case a place opens."
    : "If you can pray, you will get the details once enough mobeds are going, and your name and number will be "
      + "shared with the family.";
}

/** The prayers (never the family's name or number, nor anyone else's number), how many are
 *  going, where they stand, and their answer while they have not given one. Once all set,
 *  for someone it did not put the family in the book of (they said no, a standby, asked
 *  late), the headline says how many are going: their card has nobody's name. */
function drawAnswerCard(q, alive) {
  const n = q.places || { going: 0, wanted: 0 };
  mainEl.innerHTML = `
    <div class="card">
      <h2>${esc(q.prayed_name)}</h2>
      <p style="margin:0"><b>${esc(myHeadline(q))}</b></p>
      <p style="margin:4px 0 0">${n.going} of ${n.wanted} going</p>
      <div style="margin-top:10px">${factsHtml(q)}</div>
      <p style="margin:10px 0 0">${esc(myWords(q))}</p>
      ${q.my_answer.may_answer ? `<div class="action-bar">
        <button type="button" class="secondary" id="rqNo">Not this time</button>
        <button type="button" id="rqYes">I can pray</button>
      </div>` : ""}
    </div>`;
  const yes = document.getElementById("rqYes");
  const no = document.getElementById("rqNo");
  if (yes) yes.onclick = () => answer(q, "yes", [yes, no], alive);
  if (no) no.onclick = () => answer(q, "no", [yes, no], alive);
}

async function answer(q, choice, buttons, alive) {
  if (buttons.some(b => b.disabled)) return;
  buttons.forEach(b => { b.disabled = true; });
  let res;
  try {
    res = await answerRequest(q.id, choice);
  } catch (e) {
    if (!alive()) return;
    // Answered meanwhile (on WhatsApp, say), or closed: said over the page as it is now.
    if (e.status === 400 || e.status === 404 || e.status === 409) return redrawSaying(q, e.message, true, alive);
    buttons.forEach(b => { b.disabled = false; });
    return showError(e.message);
  }
  if (!alive()) return;
  refreshRequestCount();
  drawFor(res.request, alive);
  // Their yes made it all set: a new page (the family's contact, who is praying), from its top.
  if (res.request.status === "all_set" && res.request.all_set) toTop();
  showInfo(res.done.message);
}

// --- All set: the family's contact and everyone praying (R3.1 step 5) ------------------
// Only from the server's `all_set`, which it gives only to those it put the family in the
// book of, and only once it is all set.

// How each one going said yes, as the server words it (prayer_callout.HOW_WORDS).
const SAID_YES = {
  whatsapp: "Said yes on WhatsApp", app: "Said yes in the app", phone: "Said yes on the phone", self: "The panthaky",
};

/** Names as words: A; A and B; A, B and C (as the server joins them). */
function joinNames(names) {
  if (names.length < 2) return names[0] || "";
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

/** "Er. A is going", "Er. A and Er. B are going". */
function goingWords(names) {
  return names.length ? `${joinNames(names)} ${names.length === 1 ? "is" : "are"} going` : "Enough mobeds are going";
}

/** Under "All set: 2 going": every place filled, or confirmed with fewer. */
function allSetLine(going, wanted, short) {
  return short ? `Confirmed with ${going} of ${wanted} going.` : "All the places are filled.";
}

/** A WhatsApp chat with someone, from this person's own phone, with nothing typed. */
function waChat(phone) {
  return `https://wa.me/${String(phone || "").replace(/\D/g, "")}`;
}

/** One person praying, or the panthaky: their name, how, their number, and Call and
 *  WhatsApp from this person's own phone - not for themselves, nor without a number. */
function prayerHtml(name, phone, isMe, note) {
  const reach = phone && !isMe;
  return `<div class="fact">
      <div><b>${esc(name)}${isMe ? " (you)" : ""}</b></div>
      ${note ? `<div class="meta">${esc(note)}</div>` : ""}
      ${reach ? `<div class="meta">${esc(phone)}</div>
        <div class="row" style="margin-top:8px">
          <a class="button secondary" href="tel:${esc(phone)}" aria-label="Call ${esc(name)}">Call</a>
          <a class="button secondary" href="${esc(waChat(phone))}" target="_blank" rel="noopener"
            aria-label="WhatsApp ${esc(name)}">WhatsApp</a>
        </div>` : ""}
    </div>`;
}

/** The family's contact, with Call and their own WhatsApp opening a message ready to edit. */
function allSetFamilyHtml(a, prayed) {
  const c = a.family_contact;
  const msg = a.family_message || "";
  return `<div class="card">
      <h2>The family of ${esc(prayed)}</h2>
      ${fact("Family contact", `${esc(c.name)}<br><a class="tel" href="tel:${esc(c.phone)}">${esc(c.phone)}</a>`)}
      <label for="rqAsMsg" style="margin-top:10px">Message to the family</label>
      <textarea id="rqAsMsg" rows="7" maxlength="1000">${esc(msg)}</textarea>
      <p class="meta" style="margin:6px 0 0">Change it as you like. It opens in your own WhatsApp, ready to send.</p>
      <div class="row" style="margin-top:10px">
        <a class="button" id="rqAsWa" href="${esc(waLink(c.phone, msg))}" target="_blank" rel="noopener">WhatsApp
          the family</a>
        <a class="button secondary" href="tel:${esc(c.phone)}">Call the family</a>
      </div>
    </div>`;
}

/** Everyone going, in the order the places filled, then the panthaky. `extra` goes under
 *  them (the board's standbys). */
function allSetPrayingHtml(a, extra = "") {
  const heads = a.panthakys || [];
  return `<div class="card">
      <h2>Who is praying</h2>
      ${a.going.map(g => prayerHtml(g.name, g.phone, g.is_me, SAID_YES[g.how] || "")).join("")}
      ${heads.length ? `<p style="margin:14px 0 0"><b>${heads.length === 1 ? "The panthaky" : "The panthakys"}</b></p>
        ${heads.map(p => prayerHtml(p.name, p.phone, p.is_me, "")).join("")}` : ""}
      ${extra}
    </div>`;
}

/** Their own record of the family and the memorial, one tap away: the page's one action bar. */
function allSetBookHtml(a) {
  const main = a.memorial_id ? `<button type="button" id="rqAsMemorial">Open the memorial</button>`
    : a.customer_id ? `<button type="button" id="rqAsMakeMemorial">Make the memorial</button>` : "";
  const behdin = a.customer_id
    ? `<button type="button" class="secondary" id="rqAsBehdin">Open in Behdins</button>` : "";
  return `<div class="card">
      <h2>In your book</h2>
      <p class="meta" style="margin:0">${a.customer_id
        ? "The family's contact is in your Behdins, with reminders off until you ask them."
        : "The family's contact is no longer in your Behdins."}</p>
      ${a.customer_id && !a.memorial_id ? `<p class="meta" style="margin:4px 0 0">Make the memorial starts the
        form with the name and the date of death, for you to check.</p>` : ""}
      ${main || behdin ? `<div class="action-bar">${behdin}${main}</div>` : ""}
    </div>`;
}

/** The family, who is praying, and the book, in that order. */
function allSetMoreHtml(a, prayed, extra = "") {
  return `${allSetFamilyHtml(a, prayed)}${allSetPrayingHtml(a, extra)}${allSetBookHtml(a)}`;
}

/** The All set buttons, drawn in `root`. `ctx` is the request: {rid, aid, place}. */
function wireAllSet(root, a, ctx) {
  const msg = root.querySelector("#rqAsMsg");
  const wa = root.querySelector("#rqAsWa");
  if (msg && wa) msg.addEventListener("input", () => { wa.href = waLink(a.family_contact.phone, msg.value.trim()); });
  const on = (sel, fn) => { const el = root.querySelector(sel); if (el) el.onclick = fn; };
  on("#rqAsMemorial", () => { useFireTemple(ctx.aid); navigate(`#/memorial/${a.memorial_id}`); });
  on("#rqAsMakeMemorial", () => openMemorialForm(ctx, a.customer_id, a.memorial_prefill));
  on("#rqAsBehdin", () => { useFireTemple(ctx.aid); navigate(`#/behdins/${a.customer_id}`); });
}

/** All set, on the card of a going app mobed (or anyone else it put the family in the book
 *  of who has no board): the prayers with "All set: 2 going", then the family, who is
 *  praying and the memorial. */
function drawAllSet(q) {
  const a = q.all_set;
  const n = a.going.length;
  const wanted = (q.places || { wanted: n }).wanted;
  const me = a.going.some(g => g.is_me);
  mainEl.innerHTML = `
    <div class="card">
      <h2>${esc(q.prayed_name)}</h2>
      <p style="margin:0"><b>${esc(`All set: ${n} going`)}</b></p>
      <p style="margin:4px 0 0">${esc(allSetLine(n, wanted, a.confirmed_short))}${me ? " You are going." : ""}</p>
      <div style="margin-top:10px">${factsHtml(q)}</div>
    </div>
    ${allSetMoreHtml(a, q.prayed_name)}`;
  wireAllSet(mainEl, a, requestCtx(q));
}

// --- The board: "Who will pray" (R3.1) ----------------------------------------------

// How a place was filled, in a word or two.
const HOW = { whatsapp: "On WhatsApp", app: "In the app", phone: "By phone", self: "I'll pray" };
const SAID_HOW = { whatsapp: "on WhatsApp", app: "in the app", phone: "on the phone", self: "" };
// While it waits and is on screen, the board is read again this often.
const LIVE_MS = 10000;

function myKey() {
  return state.user ? `u${state.user.id}` : "";
}

/** Read the board, and draw the page around it. `q` is the request as the panthaky was
 *  asked it (null for the admin, whom it never reached). */
async function openBoard(id, q, alive) {
  let b;
  try {
    b = await requestBoard(id);
  } catch (e) {
    if (!alive()) return;
    // No longer theirs to answer (no longer the panthaky there, say): the page as it reads to them.
    if (e.status === 404) return q ? drawFor(q, alive) : screenFailed("That request could not be found.");
    return screenFailed("Couldn't open the request: " + e.message, () => renderRequest({ id }));
  }
  if (!alive()) return;
  // `seq` counts every read and action, so an answer that arrives after a newer one is dropped.
  const view = { id: b.request_id, q, b, alive, seq: 0, reading: 0, acting: false, timer: null, liveError: "" };
  onScreen = view;
  mainEl.innerHTML = `${boardFactsHtml(view)}<div id="rqBoard"></div>`;
  paintBoard(view);
  keepLive(view);
  // Opened again after the phone closed the app during a call made from here.
  const call = takeCall(view, { reloaded: true });
  if (call) askAbout(view, call);
}

/** The prayers, as the board gives them: never the family's name or number. */
function boardFactsHtml({ q, b }) {
  const facts = q ? factsHtml(q) : `
    ${fact("Place", esc(placeText(b.place)))}
    ${fact("Geh-saarnu", esc(b.geh_saarnu ? b.geh_saarnu.text : "Not given"))}
    ${fact("Uthamna", esc(b.uthamna ? b.uthamna.text : "Not given"))}
    ${fact("Sent to", esc(b.agyari.name))}`;
  return `<div class="card">
      <h2>${esc(b.prayed_name)}</h2>
      <div style="margin-top:6px">${facts}</div>
    </div>`;
}

/** Where the board stands, under its heading. `asked`: the request reached them (not the
 *  admin, whom it never reaches). */
function boardStateText(b, asked) {
  if (b.status === "all_set") {
    // Those it put the family in the book of have who is praying below, with the contacts.
    if (b.all_set) return allSetLine(b.going, b.wanted, b.confirmed_short);
    return `${goingWords(b.places.map(p => p.name))}${b.confirmed_short ? `: confirmed with ${b.going} of ${b.wanted}` : ""}.`
      + (asked ? " Nothing more is needed from you." : "");
  }
  if (b.status === "waiting") {
    if (b.taken) return b.taken.by ? `Finding mobeds: ${b.taken.by} has taken this on.` : "Finding mobeds.";
    return b.way === "panthaky_first"
      ? "Waiting for you. Only you were told: ask everyone, call a mobed, or pray yourself."
      : "Waiting for you. Your mobeds were asked when it came, and the first to say yes fill the places.";
  }
  if (b.status === "declined") return "Declined: nothing more is needed for it.";
  if (b.status === "withdrawn") return `Withdrawn by ${b.place.name}: nothing more is needed for it.`;
  return "Accepted.";
}

/** A place per mobed wanted: who fills it and how, or "Open place" (not on a closed request). */
function slotsHtml(b, { open = true } = {}) {
  const me = myKey();
  const out = b.places.map(p => `<div class="wp-slot"><b>${esc(p.name)}${p.key === me ? " (you)" : ""}</b>
      <span class="meta">${esc(HOW[p.how] || "")}</span></div>`);
  for (let i = b.places.length; open && i < b.wanted; i += 1) out.push(`<div class="wp-slot open">Open place</div>`);
  return out.join("");
}

function standbysHtml(b) {
  if (!b.standbys.length) return "";
  const me = myKey();
  return `<p style="margin:14px 0 4px"><b>Standby, in order</b></p>
    <ol style="margin:0;padding-left:28px">${b.standbys.map(s => `<li>${esc(s.name)}${s.key === me ? " (you)" : ""}
      ${HOW[s.how] ? `<span class="meta">· ${esc(HOW[s.how])}</span>` : ""}</li>`).join("")}</ol>`;
}

function boardCardHtml(view) {
  const { b } = view;
  const waiting = b.status === "waiting";
  const me = myKey();
  // "I'll pray" only for the fire temple's confirmed panthaky, and not twice.
  const self = waiting && b.may_pray && !b.places.concat(b.standbys).some(p => p.key === me);
  const ask = b.ask_everyone || { can: false, why_not: null };
  const allSet = b.status === "all_set";
  // All set, for the one it put the family in the book of: who is praying is drawn below with
  // the family's contact (#rqAllSetMore), so the places are not listed twice.
  const contacts = allSet && b.all_set;
  return `<div class="card">
      <h2>${allSet ? esc(`All set: ${b.going} going`) : `Who will pray: ${b.going} of ${b.wanted}`}</h2>
      <p ${allSet ? "" : `class="meta" `}style="margin:0">${esc(boardStateText(b, !!view.q))}</p>
      <p class="meta" id="rqLive" role="status" style="margin:4px 0 0">${esc(view.liveError)}</p>
      ${contacts ? "" : `${slotsHtml(b, { open: !["declined", "withdrawn", "all_set"].includes(b.status) })}
        ${standbysHtml(b)}`}
      ${waiting ? `
        <div class="action-bar">
          ${self ? `<button type="button" class="secondary" id="rqSelf">I'll pray</button>` : ""}
          <button type="button" id="rqAsk" ${ask.can ? "" : "disabled"}>Ask everyone</button>
        </div>
        ${ask.can ? "" : `<p class="meta" style="margin:6px 0 0">${esc(ask.why_not || "There is nobody more to ask now.")}</p>`}
        <p class="meta" style="margin:10px 0 0">The family's name and number are not shown until enough mobeds are
          going.</p>` : ""}
    </div>`;
}

/** Where one of the fire temple's mobeds stands for this request. */
function mobedStateText(m) {
  if (m.state === "going") return "Going";
  if (m.state === "standby") return "Standby";
  if (m.state === "said_no") return `Said no${SAID_HOW[m.how] ? ` ${SAID_HOW[m.how]}` : ""}`;
  if (m.state === "asked_whatsapp") {
    const wa = m.whatsapp;
    return `Asked on WhatsApp${wa ? `: ${wa.state}${wa.why ? ` (${wa.why})` : ""}` : ""}${m.in_app ? ", and in the app" : ""}`;
  }
  if (m.state === "asked_app") return "Asked in the app";
  return "Not asked yet";
}

/** What the panthaky's own WhatsApp opens with, to one of their mobeds: no family details. */
function askText(b) {
  return [
    `A prayer request has come to ${b.agyari.name} for ${b.prayed_name} at ${b.place.name}.`,
    b.geh_saarnu ? `Geh-saarnu: ${b.geh_saarnu.text}.` : "",
    b.uthamna ? `Uthamna: ${b.uthamna.text}.` : "",
    "Can you pray?",
  ].filter(Boolean).join(" ");
}

function mobedRowHtml(b, m) {
  const notes = [];
  if (m.phone) notes.push(esc(m.phone));
  if (m.stopped) notes.push("Replied STOP: not asked on WhatsApp");
  else if (!m.can_message && m.why_not) notes.push(`Not asked on WhatsApp: ${esc(m.why_not)}`);
  // Call and WhatsApp use the panthaky's own phone, so only someone whose number is shown.
  const reach = m.phone ? `<div class="row" style="margin-top:8px">
      <a class="button secondary" href="tel:${esc(m.phone)}" data-call="${esc(m.key)}"
        aria-label="Call ${esc(m.name)}">Call</a>
      <a class="button secondary" href="${esc(waLink(m.phone, askText(b)))}" target="_blank" rel="noopener"
        data-chat="${esc(m.key)}" aria-label="WhatsApp ${esc(m.name)}">WhatsApp</a>
    </div>` : "";
  const going = MAY_MARK.has(m.state) ? `<button type="button" class="secondary" data-going="${esc(m.key)}"
      style="width:100%;margin-top:8px" aria-label="Is ${esc(m.name)} going?">Going?</button>` : "";
  return `<div class="fact">
      <div><b>${esc(m.name)}</b></div>
      <div class="meta"><b>${esc(mobedStateText(m))}</b></div>
      ${notes.map(n => `<div class="meta">${n}</div>`).join("")}
      ${reach}${going}
    </div>`;
}

function mobedsCardHtml(view) {
  const { b, q } = view;
  return `<div class="card">
      <h2>Mobeds</h2>
      <p class="meta" style="margin:0 0 4px">Call or message one of your mobeds from your own phone. When you come
        back, you are asked whether they are going.</p>
      ${b.mobeds.length ? b.mobeds.map(m => mobedRowHtml(b, m)).join("") : `
        <p style="margin:8px 0 0">Nobody else is on ${esc(b.agyari.name)}'s list of mobeds yet.</p>
        ${q ? `<button type="button" class="ghost small" id="rqMobedsPage" style="margin-top:8px">Open the Mobeds
          page</button>` : ""}`}
    </div>`;
}

/** The board and what goes with it, drawn again from `view.b`. */
function paintBoard(view) {
  const area = document.getElementById("rqBoard");
  if (!area) return;
  const { b, q } = view;
  const waiting = b.status === "waiting";
  view.drawn = JSON.stringify(b);
  // All set, and the family is in their book: the family, who is praying (the standbys under
  // them) and the memorial.
  const contacts = b.status === "all_set" && b.all_set;
  area.innerHTML = `${boardCardHtml(view)}
    ${contacts ? `<div id="rqAllSetMore">${allSetMoreHtml(b.all_set, b.prayed_name, standbysHtml(b))}</div>` : ""}
    ${waiting ? mobedsCardHtml(view) : ""}
    ${waiting && q ? `<p style="margin:20px 0 0;text-align:center">
      <button type="button" class="ghost small" id="rqCantTake">We can't take this</button></p>` : ""}`;
  if (contacts) wireAllSet(area, b.all_set, { rid: b.request_id, aid: b.agyari.id, place: b.place.name });

  const on = (sel, fn) => { const el = area.querySelector(sel); if (el) el.onclick = fn; };
  on("#rqAsk", (ev) => act(view, ev.currentTarget, () => boardAskEveryone(view.id)));
  on("#rqSelf", (ev) => act(view, ev.currentTarget, () => boardPrayMyself(view.id)));
  on("#rqCantTake", () => confirmDecline(q, view.alive));
  on("#rqMobedsPage", () => { useFireTempleOf(q); navigate("#/mobeds"); });
  const mobed = (key) => view.b.mobeds.find(m => m.key === key);
  // The link does the calling or the chat; remembered, to ask "Is <name> going?" on coming back.
  area.querySelectorAll("[data-call], [data-chat]").forEach(a => {
    a.addEventListener("click", () => {
      const m = mobed(a.dataset.call || a.dataset.chat);
      if (m) rememberCall(view, m);
    });
  });
  area.querySelectorAll("[data-going]").forEach(btn => {
    btn.onclick = () => {
      const m = mobed(btn.dataset.going);
      if (m) askGoing(view, m);
    };
  });
}

let onScreen = null;   // the board being shown (renderRequest forgets it), for the page coming back into view

/** Whether this board is still the one on screen. */
function here(view) {
  return onScreen === view && view.alive();
}

/** A board read or action has answered: drawn, unless something newer has been asked since. */
function showBoard(view, b, seq) {
  if (seq !== view.seq || !here(view)) return;
  view.b = b;
  view.liveError = "";
  paintBoard(view);
  keepLive(view);
}

/** One board action: one tap, the button held while it runs; then the board as the server
 *  has it now, and what happened in words. */
async function act(view, btn, call) {
  if (btn.disabled) return;
  btn.disabled = true;
  view.acting = true;
  const seq = ++view.seq;
  let res;
  try {
    res = await call();
  } catch (e) {
    view.acting = false;
    if (here(view)) refused(view, e, btn);
    return;
  }
  view.acting = false;
  if (!here(view)) return;
  const { done = {}, ...b } = res;
  showBoard(view, b, seq);
  refreshRequestCount();
  (done.state === "failed" ? showError : showInfo)(done.message || "Done.");
}

/** An action the server refused, in its own words, over the board as it is now. A failure
 *  to reach the server leaves the button to try again. */
async function refused(view, e, btn = null) {
  if (e.status === 404) {
    // No longer theirs (or no longer there): the page as it reads to them now.
    await renderRequest({ id: view.id });
    return showError(e.message);
  }
  showError(e.message);
  if (btn) btn.disabled = false;
  if (e.status === 409 || e.status === 400) return readBoard(view);
}

/** Read the board again now (a read already on its way is then dropped: `seq`). A failure
 *  is said on the board, and the next read tries again. */
async function readBoard(view) {
  view.reading += 1;
  const seq = ++view.seq;
  try {
    const b = await requestBoard(view.id);
    if (seq === view.seq && here(view) && JSON.stringify(b) === view.drawn) {
      view.liveError = "";
      const line = document.getElementById("rqLive");
      if (line) line.textContent = "";
    } else {
      showBoard(view, b, seq);
    }
  } catch (e) {
    if (seq === view.seq && here(view)) {
      if (e.status === 404) return renderRequest({ id: view.id });
      view.liveError = "Could not check for new answers just now. Trying again.";
      const line = document.getElementById("rqLive");
      if (line) line.textContent = view.liveError;
    }
  } finally {
    view.reading -= 1;
  }
}

// --- Live: the board read again while it waits and is on screen ---------------------

function keepLive(view) {
  clearTimeout(view.timer);
  view.timer = null;
  if (!here(view) || view.b.status !== "waiting" || document.hidden) return;
  view.timer = setTimeout(() => tick(view), LIVE_MS);
}

async function tick(view) {
  clearTimeout(view.timer);
  view.timer = null;
  if (!here(view) || view.b.status !== "waiting" || document.hidden) return;
  // Never two at once, and not while a tap is being answered: its answer is the board.
  if (!view.acting && !view.reading) await readBoard(view);
  if (here(view) && !view.timer) keepLive(view);
}

// --- "Is <name> going?": back from a call or a chat started on the board -------------

// Whose answer a call can still give: not someone going or on standby. (Going may turn an
// earlier no into a yes: people change their mind on the phone.)
const MAY_MARK = new Set(["not_asked", "asked_app", "asked_whatsapp", "said_no"]);
// A call or chat is asked about when the panthaky is back in the app within this.
const CALL_WITHIN_MS = 30 * 60 * 1000;
// Kept for this tab too: a phone short of memory may close the app during a long call.
const CALL_KEY = "mobed.boardCall";
let lastCall = null;   // {rid, key, name, at, left}: the last Call or WhatsApp tapped on a board

function rememberCall(view, m) {
  lastCall = { rid: view.id, key: m.key, name: m.name, at: Date.now(), left: false };
  try { sessionStorage.setItem(CALL_KEY, JSON.stringify(lastCall)); } catch (e) { /* this visit only, then */ }
}

function forgetCall() {
  lastCall = null;
  try { sessionStorage.removeItem(CALL_KEY); } catch (e) { /* nothing was kept */ }
}

/** The call or chat to ask about on this board now, once: one started here that the
 *  panthaky left the app for and came back from within 30 minutes - or, `reloaded`, one
 *  from before the app was opened again. */
function takeCall(view, { reloaded = false } = {}) {
  let call = lastCall;
  if (!call && reloaded) {
    try { call = JSON.parse(sessionStorage.getItem(CALL_KEY) || "null"); } catch (e) { call = null; }
    if (call) call.left = true;
  }
  if (!call || !call.left) return null;
  if (!(Date.now() - call.at <= CALL_WITHIN_MS)) {
    forgetCall();
    return null;
  }
  if (String(call.rid) !== String(view.id)) return null;
  forgetCall();
  return call;
}

/** Ask about `call` on the board as it now reads, if that mobed can still be marked. */
function askAbout(view, call) {
  if (!here(view) || view.b.status !== "waiting") return;
  const m = view.b.mobeds.find(x => x.key === call.key);
  if (!m) return;
  if (MAY_MARK.has(m.state)) return askGoing(view, m);
  showInfo(m.state === "going" ? `${m.name} is going already.` : `${m.name} is on standby already.`);
}

/** Back in the app: the board read again (answers may have come meanwhile), then the
 *  question about the call or chat, if there was one. */
async function backInApp() {
  const view = onScreen;
  if (!view || !here(view) || document.hidden) return;
  const call = takeCall(view);
  if (view.b.status === "waiting" && (call || !view.timer)) await tick(view);
  if (call) askAbout(view, call);
}

function leftApp() {
  if (lastCall) lastCall.left = true;
  const view = onScreen;
  if (view && document.hidden) {
    clearTimeout(view.timer);    // nothing is read while the page is out of sight
    view.timer = null;
  }
}

document.addEventListener("visibilitychange", () => (document.hidden ? leftApp() : backInApp()));
window.addEventListener("blur", leftApp);
window.addEventListener("focus", backInApp);

/** "Is <name> going?", from a mobed's Going? or on coming back from a call: one tap, then
 *  the board as the server has it. A refusal is said in the server's words. */
function askGoing(view, m) {
  const sheet = openSheet({
    title: `Is ${m.name} going?`,
    html: `
      <p class="meta" style="margin-top:0">To pray for ${esc(view.b.prayed_name)}.</p>
      <p class="meta" data-msg role="alert" style="margin:0 0 8px"></p>
      <div class="stack">
        <button type="button" data-result="going">Going</button>
        <button type="button" class="secondary" data-result="not_going">Not this time</button>
        <button type="button" class="ghost" data-result="no_answer">No answer</button>
      </div>`,
  });
  const body = sheet.body;
  const buttons = [...body.querySelectorAll("[data-result]")];
  buttons.forEach(btn => {
    btn.onclick = async () => {
      if (btn.disabled) return;
      buttons.forEach(x => { x.disabled = true; });
      body.querySelector("[data-msg]").textContent = "";
      view.acting = true;
      const seq = ++view.seq;
      let res;
      try {
        res = await boardCallResult(view.id, m.key, btn.dataset.result);
      } catch (e) {
        view.acting = false;
        if (!here(view)) return;
        if (e.status === 400 || e.status === 404 || e.status === 409) {
          sheet.close();
          return refused(view, e);
        }
        // No signal, or a passing failure: said where they are looking, to tap again.
        buttons.forEach(x => { x.disabled = false; });
        body.querySelector("[data-msg]").textContent = e.message;
        return;
      }
      view.acting = false;
      sheet.close();
      if (!here(view)) return;
      const { done = {}, ...b } = res;
      showBoard(view, b, seq);
      refreshRequestCount();
      showInfo(done.message || "Noted.");
    };
  });
}

// --- We can't take this ---------------------------------------------------------------

function confirmDecline(q, alive) {
  const sheet = openSheet({
    title: `Can't take the prayers for ${q.prayed_name}?`,
    html: `
      <p class="meta" style="margin-top:0">${esc(q.funeral_place.name)} is told that ${esc(q.agyari.name)} cannot
        take it, and can ask another fire temple. It is then closed for everyone asked here.</p>
      <label for="rqReason">Reason <span class="meta">(optional, for ${esc(q.funeral_place.name)})</span></label>
      <textarea id="rqReason" rows="2" maxlength="200" placeholder="e.g. No mobed free on that day"></textarea>
      <p class="meta" data-msg role="alert" style="margin:6px 0 0"></p>
      <div class="stack" style="margin-top:12px">
        <button type="button" class="danger" data-yes>We can't take this</button>
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
        return redrawSaying(q, e.message, true, alive);
      }
      body.querySelector("[data-msg]").textContent = e.message;
      return;
    }
    sheet.close();
    redrawSaying(q, `Declined. ${q.funeral_place.name} is told and can ask another fire temple.`, false, alive);
  };
}
