"use strict";

/**
 * A Doongerwadi manager's record of a death, and sending it to a fire temple
 * (DECISIONS D10, D5, D12; Phase 2 Step 4).
 *
 *  - The record: everything on it, its requests, and Send / Withdraw / Edit.
 *    Where a request stands, in the server's words (R3.1 step 6): Waiting at
 *    X (or Sent to the panthaky of X), Finding mobeds at X: 1 of 2 going, A
 *    place has opened at X, All set at X with the mobeds' names and the
 *    panthaky's Call and WhatsApp (the manager's own phone, a short message
 *    ready), Declined by X, Nobody at X can take it, Withdrawn. While it
 *    waits, "Send to another fire temple" withdraws it (a sheet first) and opens
 *    the list of fire temples for it again. A request accepted the old way
 *    (Step 5) still shows who accepted, and - only if they ticked "Share my
 *    name and number" - their number with Call and WhatsApp.
 *  - Sending: a fire temple's row (agyariRowHtml), then the sheet saying what
 *    happens by that fire temple's way (its mobeds asked at once, or its
 *    panthaky choosing who to ask), the tick that the family agreed, and Send
 *    (confirmSend). The four steps that record a death and choose the fire
 *    temple are in manager_record_flow.js.
 *
 * Nothing about the cause of death, age, address, certificate, ID numbers or
 * how the body goes is asked.
 *
 * The admin acting for one place (acting.js) uses these same screens: every
 * address goes through managerHash, and what the admin recorded says so.
 */

import { managerRecord, managerSend, managerWithdraw } from "../api.js";
import { state } from "../state.js";
import {
  chrome, mainEl, showFab, showError, showInfo, refreshHeader, loading, screenFailed, openSheet, flashInfo,
  flashError,
} from "../ui.js";
import { esc, firstName, gregLabel, istHm, istYmd, todayIst } from "../util.js";
import { navigate, navGuard, returnTo } from "../router.js";
import { managerHash } from "../acting.js";
import { refreshAfterAction } from "../notifications.js";

const REACH = {
  panthaky: { text: "Panthaky in the app", cls: "role" },
  mobeds: { text: "Mobeds only", cls: "" },
  nobody: { text: "Not in Mobed Diary yet", cls: "grey" },
};

// --- Shared words ---------------------------------------------------------------

function when(iso) {
  const day = istYmd(iso);
  return day === todayIst() ? istHm(iso) : `${gregLabel(day)}, ${istHm(iso)}`;
}

/** One request's state, in words, as the server says it (R3.1 step 6): "Waiting at X",
 *  "Finding mobeds at X: 1 of 2 going", "All set at X: Er. A and Er. B are going" and the
 *  like. The rest is for a server from before those words. */
export function requestState(q) {
  if (q.headline) return q.headline;
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

async function fetchRecord(id, retry) {
  try {
    return (await managerRecord(id)).record;
  } catch (e) {
    screenFailed(e.message, retry);
    return null;
  }
}

// --- The record ---------------------------------------------------------------------

/** A number with Call and WhatsApp from the manager's own phone, a short message ready to edit. */
function reachHtml(rec, name, phone, idPrefix) {
  const me = state.user ? state.user.name : "";
  const place = rec.funeral_place ? rec.funeral_place.name : "";
  // "Sahebji <first name>" (owner, 22 Nov 2026): the Parsi way one addresses a mobed. The words
  // are the owner's (word review, 23 Nov 2026).
  const first = firstName(name);
  const who = [me, place].filter(Boolean).join(" of ");
  const text = `${first ? `Sahebji ${first}` : "Sahebji"}, ${who ? `this is ${who}, ` : ""}about the prayers for ${rec.prayed_name}.`;
  const digits = phone.replace(/\D/g, "");
  return `
    <p style="margin:6px 0 0"><a class="tel" href="tel:${esc(phone)}">${esc(phone)}</a></p>
    <div class="row tight" style="margin-top:8px;flex-wrap:wrap">
      <a class="button small secondary" id="${idPrefix}Call" href="tel:${esc(phone)}">Call</a>
      <a class="button small secondary" id="${idPrefix}Wa" target="_blank" rel="noopener"
        href="https://wa.me/${esc(digits)}?text=${esc(encodeURIComponent(text))}">WhatsApp</a>
    </div>`;
}

/** Who accepted, and a way to reach them only if they shared their number. */
function accepterHtml(rec, q) {
  if (!q || !q.accepter_phone) {
    return q ? `<p class="meta" style="margin:4px 0 0">They did not share their number. You can reach them through
      ${esc(q.agyari ? q.agyari.name : "the fire temple")}.</p>` : "";
  }
  return reachHtml(rec, q.accepted_by, q.accepter_phone, "mr");
}

/** All set (R3.1): the panthaky the family went to, with Call and WhatsApp. With no confirmed
 *  panthaky in the app the headline's names are all there is. */
function panthakysHtml(rec, q) {
  const heads = q.panthakys || [];
  if (!heads.length) {
    return `<p class="meta" style="margin:4px 0 0">${esc(q.agyari ? q.agyari.name : "The fire temple")} has no
      panthaky in Mobed Diary, so the mobeds going are all there is to know.</p>`;
  }
  return heads.map((p, i) => `
    <div style="margin-top:10px">
      <p style="margin:0">The panthaky: <b>${esc(p.name)}</b></p>
      ${p.phone ? reachHtml(rec, p.name, p.phone, `mrHead${i}`) : ""}
    </div>`).join("");
}

/** What else to say under a request's words, by where it stands. */
function standingHtml(rec, q) {
  if (q.stage === "all_set") return panthakysHtml(rec, q);
  if (q.stage === "accepted") return accepterHtml(rec, q);
  if (q.status !== "waiting") return "";
  const where = q.agyari ? q.agyari.name : "the fire temple";
  const lines = [`Sent ${esc(when(q.sent_at))}.`];
  if (q.stage === "reopened") {
    // Seen at All set, so still shown: who is going now, and the panthaky with Call and WhatsApp.
    lines.push("Someone going can no longer go, so their place is being filled.");
    const names = q.going_names || [];
    return `<p class="meta" style="margin:4px 0 0">${lines.join(" ")}</p>
      ${names.length ? `<p style="margin:6px 0 0">Still going: <b>${esc(names.join(", "))}</b></p>` : ""}
      ${panthakysHtml(rec, q)}`;
  } else if (q.no_answer_told_at) {
    lines.push(`Nobody at ${esc(where)} has answered in an hour. You can send it to another fire temple.`);
  } else if (q.stage === "waiting" || q.stage === "panthaky_first") {
    lines.push("You see here when they answer.");
  }
  return `<p class="meta" style="margin:4px 0 0">${lines.join(" ")}</p>`;
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
  drawRecord(rec, alive);
}

function drawRecord(rec, alive) {
  const waiting = rec.requests.find(q => q.status === "waiting");
  const latest = rec.requests[0];
  const placeOn = !!(rec.funeral_place && rec.funeral_place.is_active);
  const death = rec.death;
  mainEl.innerHTML = `
    <div class="card">
      <h2>${esc(rec.prayed_name)}</h2>
      ${rec.funeral_place ? `<p class="meta" style="margin:0">${esc(rec.funeral_place.name)}</p>` : ""}
      ${rec.recorded_by_admin ? `<p class="meta" style="margin:4px 0 0">Recorded by the admin</p>` : ""}
      <div style="margin-top:10px">
        ${fact("Passed away", `${esc(gregLabel(death.date))}<br><span class="meta">${esc(death.label)}${death.given_by === "roj_mah"
          ? " (given by Roj and Mah)" : ""}</span>`)}
        ${fact("Days of prayers", esc(rec.obsequies_label))}
        ${fact("Geh-saarnu", esc(gehSaarnuText(rec.geh_saarnu)))}
        ${fact("Uthamna", esc(uthamnaText(rec.uthamna)))}
        ${rec.mobeds_wanted ? fact("Mobeds wanted", String(rec.mobeds_wanted)) : ""}
        ${rec.preferred_agyari ? fact("The family's fire temple", esc(rec.preferred_agyari.name)) : ""}
        ${fact("Family contact", `${esc(rec.family_contact.name)}<br><span class="meta">${esc(rec.family_contact.phone)}</span>`)}
      </div>
    </div>

    <div class="card">
      <h2>Prayers</h2>
      <p style="margin:4px 0 0"><b>${esc(recordState(rec))}</b></p>
      ${latest ? standingHtml(rec, latest) : ""}
      ${rec.requests.length > 1 ? `<div style="margin-top:10px">${rec.requests.slice(1).map(q =>
        `<p class="meta" style="margin:2px 0">${esc(requestState(q))}</p>`).join("")}</div>` : ""}
      <div class="action-bar">
        ${waiting && placeOn ? `<button type="button" class="secondary" id="mrElsewhere">Send to another fire temple</button>` : ""}
        ${waiting ? `<button type="button" class="ghost" id="mrWithdraw">Withdraw</button>` : ""}
        ${rec.may_send ? `<button type="button" id="mrSend">${rec.requests.length ? "Send to another fire temple"
          : "Send to a fire temple"}</button>` : ""}
        ${rec.may_edit ? `<button type="button" class="ghost" id="mrEdit">Change</button>` : ""}
      </div>
      ${rec.funeral_place && !rec.funeral_place.is_active ? `<p class="meta" style="margin:10px 0 0">This place is
        turned off in Mobed Diary at the moment, so nothing can be sent from it.</p>` : ""}
    </div>`;
  const on = (sel, fn) => { const el = document.getElementById(sel); if (el) el.onclick = fn; };
  on("mrSend", () => navigate(managerHash(`/record/${rec.id}/send`)));
  on("mrEdit", () => navigate(managerHash(`/record/${rec.id}/edit`)));
  on("mrWithdraw", () => confirmWithdraw(rec, waiting));
  on("mrElsewhere", () => confirmElsewhere(rec, waiting, alive));
}

/** "Send to another agyari" (R3.1 step 6): a sheet first, then the request is withdrawn there
 *  (those asked are told it is no longer needed) and Ask a fire temple opens. A refusal (it is
 *  all set by now, say) is said over the record read again; no signal is said in the sheet, to
 *  tap again. */
function confirmElsewhere(rec, q, alive) {
  const where = q.agyari ? q.agyari.name : "the fire temple";
  const sheet = openSheet({
    title: `Withdraw the request from ${where} and send it to another?`,
    html: `
      <p style="margin-top:0">The people asked at ${esc(where)} are told it is no longer needed. Then you choose
        another fire temple.</p>
      <p class="meta" data-msg role="alert" style="margin:0 0 8px"></p>
      <div class="stack">
        <button type="button" data-yes>Withdraw and choose another</button>
        <button type="button" class="ghost" data-no>Keep it waiting</button>
      </div>`,
  });
  const body = sheet.body;
  body.querySelector("[data-no]").onclick = sheet.close;
  const yes = body.querySelector("[data-yes]");
  yes.onclick = async () => {
    if (yes.disabled) return;
    yes.disabled = true;
    body.querySelector("[data-msg]").textContent = "";
    try {
      await managerWithdraw(q.id);
    } catch (e) {
      if (!alive()) return;
      if (e.status === 400 || e.status === 404 || e.status === 409) {
        sheet.close();
        await renderRecordView({ id: rec.id });
        return showError(e.message);
      }
      yes.disabled = false;
      body.querySelector("[data-msg]").textContent = e.message;
      return;
    }
    sheet.close();
    refreshAfterAction();
    if (!alive()) return;
    flashInfo(`Withdrawn from ${where}. Now choose another fire temple.`);
    navigate(managerHash(`/record/${rec.id}/send`));
  };
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
    refreshAfterAction();
    await renderRecordView({ id: rec.id });
    showInfo("Withdrawn. You can now send it to another fire temple.");
  };
}

// --- Choosing the fire temple ---------------------------------------------------------

/** One fire temple as a row (the list at step 4 of recording a death, manager_record_flow.js). */
export function agyariRowHtml(a, i) {
  const reach = REACH[a.reach] || REACH.nobody;
  const how = a.way === "panthaky_first" ? "Its panthaky chooses who to ask"
    : a.way === "everyone" ? "Its mobeds are asked at once" : "";
  const km = a.km == null ? "" : `${a.location_source === "town" ? "about " : ""}${a.km < 10 ? a.km : Math.round(a.km)} km`;
  return `<div class="search-result${a.may_send ? "" : " unavailable"}" data-i="${i}" ${a.may_send ? "" : 'aria-disabled="true"'}>
      <div><strong>${esc(a.name)}</strong></div>
      <div class="addr">${esc([a.city, km].filter(Boolean).join(" · "))}</div>
      <div style="margin-top:4px">${a.preferred ? `<span class="tag">Family's usual</span> ` : ""}<span
        class="tag ${reach.cls}">${reach.text}</span></div>
      ${how ? `<div class="addr" style="margin-top:2px">${how}</div>` : ""}
    </div>`;
}

let sending = false;

/** What happens at Send, by the fire temple's way (R3.1 step 6). */
export function sendWords(a, whatsappOn) {
  const how = a.way === "panthaky_first"
    ? "Its panthaky is told and chooses who to ask."
    : `Its mobeds are asked at once, ${whatsappOn ? "in the app and on WhatsApp" : "in the app"}, whether they can pray.`;
  const shared = a.reach === "panthaky" ? "with its panthaky and the mobeds who go" : "with the mobeds who go";
  return `${how} The family's name and number are shared only once enough mobeds are going, ${shared}.`;
}

/** The tick, then Send. The tick is asked every time, for this fire temple. */
export function confirmSend(rec, a, whatsappOn, { onSent = null } = {}) {
  const sheet = openSheet({
    title: `Send to ${a.name}?`,
    html: `
      <p class="meta" style="margin-top:0">${esc(rec.prayed_name)}. ${esc(sendWords(a, whatsappOn))}</p>
      <div class="check-row" id="msTickRow"><input type="checkbox" id="msTick">
        <label for="msTick">The family agreed to share their name and number with this fire temple, and to get
          WhatsApp messages about the prayers from Mobed Diary</label></div>
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
    refreshAfterAction();
    if (onSent) onSent();
    const n = res.asked;
    const wa = res.callout || {};
    if (wa.state === "panthaky_first") {
      // Come to me first (R3.1): only the panthaky was told, and nobody was asked on WhatsApp.
      flashInfo(wa.message);
    } else {
      // What the WhatsApp call-out to its mobeds did, or why nothing went (19 Nov 2026).
      const waWords = wa.state === "off" || wa.state === "not_now"
        ? `${wa.message} So no mobed was asked on WhatsApp.` : (wa.message || "");
      (wa.state === "failed" ? flashError : flashInfo)(
        `Sent to ${a.name}. ${n} ${n === 1 ? "person there was" : "people there were"} told in the app. ${waWords}`.trim());
    }
    returnTo(managerHash(`/record/${rec.id}`));
  };
}
