"use strict";

/**
 * Who is going (DECISIONS D10, changed 19 Nov 2026): when a Doongerwadi sends a
 * request, the agyari's mobeds are asked on WhatsApp at once whether they can
 * pray, and the first to say yes, up to the number wanted, go. This page is for
 * the panthaky: read-only lists of who is going, who said yes, who said no and
 * who has not answered, and what WhatsApp did with each message.
 *
 *  - Going: they got the details and the family's contact on WhatsApp.
 *    "Send the details again" is there only for someone going whose details
 *    did not go (sending was paused, say).
 *  - Said yes after enough were going: thanked ("Enough mobeds are going").
 *  - Ask on WhatsApp: those on the Mobeds page not asked yet for this request
 *    (someone added since). Nobody is asked twice.
 *
 * The message has no family details. While the messages are not switched on
 * (Meta has not approved them yet) the page says so, and the list of mobeds can
 * still be built.
 */

import { getCallout, sendCallout, calloutDetailsAgain } from "../api.js";
import { chrome, mainEl, showFab, showError, showInfo, refreshHeader, loading, screenFailed, toTop } from "../ui.js";
import { esc } from "../util.js";
import { navigate, navGuard } from "../router.js";

function candidateHtml(c) {
  const why = c.asked_already ? "Asked already" : c.may_ask ? "" : `Not asked: ${c.why_not}`;
  return `<div class="check-row">
      <input type="checkbox" id="co_${esc(c.key)}" data-key="${esc(c.key)}" ${c.may_ask ? "checked" : "disabled"}>
      <label for="co_${esc(c.key)}">${esc(c.name)}${why ? `<br><span class="meta">${esc(why)}</span>` : ""}</label>
    </div>`;
}

function stateLine(label, s) {
  if (!s) return "";
  return `<div class="meta">${esc(label)}: ${esc(s.state)}${s.why ? ` (${esc(s.why)})` : ""}</div>`;
}

function personHtml(p) {
  const lines = [
    p.asked && p.asked.why ? stateLine("Asked on WhatsApp", p.asked) : "",
    p.going ? stateLine("Details", p.details) : "",
    !p.going && p.answer === "yes" ? stateLine("Thank-you message", p.enough) : "",
    stateLine("Told it was withdrawn", p.withdrawn_note),
  ].join("");
  return `<div class="search-result" style="cursor:default"><strong>${esc(p.name)}</strong>${lines}</div>`;
}

function group(title, people, empty) {
  return `<div class="names-group-label"><b>${esc(title)}</b><span>${people.length}</span></div>
    ${people.length ? people.map(personHtml).join("") : `<p class="meta" style="margin:0">${esc(empty)}</p>`}`;
}

export async function renderCallout({ id }) {
  chrome(true);
  refreshHeader();
  showFab(false);
  loading();
  const alive = navGuard();
  let v;
  try {
    v = await getCallout(id);
  } catch (e) {
    if (!alive()) return;
    if (e.status === 404) return screenFailed("Only the panthaky of the fire temple this request was sent to can see this.");
    return screenFailed("Couldn't open this: " + e.message, () => renderCallout({ id }));
  }
  if (!alive()) return;
  draw(id, v);
}

function draw(id, v) {
  const on = v.whatsapp.on;
  const going = v.asked.filter(p => p.going);
  const yes = v.asked.filter(p => !p.going && p.answer === "yes");
  const no = v.asked.filter(p => p.answer === "no");
  const silent = v.asked.filter(p => !p.answer);
  const askable = v.candidates.filter(c => c.may_ask).length;
  const resend = v.asked.some(p => p.may_resend);
  mainEl.innerHTML = `
    <div class="card">
      <h2>Who is going: ${esc(v.prayed_name)}</h2>
      <div class="fact"><div class="fl">Place</div><div class="fv">${esc(v.place)}</div></div>
      <div class="fact"><div class="fl">Geh-saarnu</div><div class="fv">${esc(v.geh_saarnu)}</div></div>
      <div class="fact"><div class="fl">Uthamna</div><div class="fv">${esc(v.uthamna)}</div></div>
      <div class="fact"><div class="fl">Mobeds wanted</div><div class="fv">${v.wanted}${v.mobeds_wanted ? "" : " (none given, so 2)"}</div></div>
      ${v.open ? "" : `<p style="margin:10px 0 0"><b>This request is closed.</b> Nobody more is asked or sent anything for it.</p>`}
      ${on ? "" : `<p style="margin:10px 0 0"><b>${esc(v.whatsapp.why_not)}</b> Until then nobody is asked on WhatsApp, and
        you can build your list of mobeds.</p>`}
      <p class="meta" style="margin:10px 0 0">When the request came, the mobeds on your list were asked on WhatsApp
        whether they can pray (no family details). ${v.wanted === 1 ? "The first to say yes goes and gets"
        : `The first ${v.wanted} to say yes go and get`} the details and the family's contact at once. Those who say yes
        later are thanked.</p>
    </div>
    <div class="card">
      <h2>Answers</h2>
      ${v.asked.length ? `
        ${group(`Going (${going.length} of ${v.wanted})`, going, "Nobody yet.")}
        ${resend && on ? `<div style="margin:8px 0 4px"><button type="button" class="small" id="coAgain">Send the details
          again</button></div>` : ""}
        ${group("Said yes, not needed", yes, "Nobody.")}
        ${group("Said no", no, "Nobody.")}
        ${group("No answer yet", silent, "Nobody.")}`
        : `<p class="meta" style="margin:0">Nobody has been asked on WhatsApp for this request.</p>`}
    </div>
    ${v.open ? `<div class="card">
      <h2>Ask on WhatsApp</h2>
      <p class="meta" style="margin:0 0 8px">For mobeds not asked yet, such as someone you added to your list since.
        Nobody is asked twice.</p>
      ${v.candidates.length ? v.candidates.map(candidateHtml).join("")
        : `<p class="meta" style="margin:0">Nobody is on your list yet besides you.</p>`}
      <div class="action-bar">
        <button type="button" class="secondary" id="coList">Mobeds</button>
        <button type="button" id="coSend" ${askable ? "" : "disabled"}>Ask on WhatsApp</button>
      </div>
    </div>` : ""}`;

  const list = document.getElementById("coList");
  if (list) list.onclick = () => navigate("#/mobeds");
  const send = document.getElementById("coSend");
  if (send) {
    send.onclick = async (ev) => {
      if (!on) return showInfo(`${v.whatsapp.why_not} Until then you can build your list of mobeds.`);
      const who = [...mainEl.querySelectorAll("[data-key]:checked")].map(el => el.dataset.key);
      if (!who.length) return showError("Please tick who to ask.");
      if (who.length > v.max) return showError(`One call-out can ask at most ${v.max} mobeds.`);
      const btn = ev.currentTarget;
      btn.disabled = true;
      let res;
      try {
        res = await sendCallout(id, who);
      } catch (e) {
        btn.disabled = false;
        return showError(e.message);
      }
      draw(id, res);
      toTop();
      const failed = who.length - res.asked_now;
      (failed ? showError : showInfo)(failed
        ? `Asked ${res.asked_now} of ${who.length} on WhatsApp. The others could not be sent: see the answers.`
        : `Asked ${res.asked_now} on WhatsApp. Their answers will show here.`);
    };
  }
  const again = document.getElementById("coAgain");
  if (again) {
    again.onclick = async () => {
      again.disabled = true;
      let res;
      try {
        res = await calloutDetailsAgain(id);
      } catch (e) {
        again.disabled = false;
        return showError(e.message);
      }
      draw(id, res);
      toTop();
      const d = res.done;
      (d.sent < d.tried ? showError : showInfo)(d.sent < d.tried
        ? `Details sent to ${d.sent} of ${d.tried}. The others could not be sent: see the answers.`
        : `Details sent to ${d.sent}.`);
    };
  }
}
