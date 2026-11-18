"use strict";

/**
 * "Ask our mobeds on WhatsApp" (DECISIONS D10, Phase 2 Step 5c): on a request
 * the panthaky's fire temple accepted, ask the agyari's mobeds whether they can
 * pray, see every answer, and pick who goes.
 *
 *  - Who to ask: everyone on "Our mobeds" who can be messaged is ticked; those
 *    who replied STOP, are switched off, or were asked already say why.
 *  - The message has no family details. The answers come back as the mobeds
 *    tap "Yes, I can pray" or "Not this time" in WhatsApp.
 *  - Picking: those picked get the details and the family's contact; the other
 *    yeses are told enough mobeds are going, but only within 24 hours of their
 *    answer (WhatsApp's rule), and the page says when it was too late.
 *
 * While the messages are not switched on (Meta has not approved them yet) the
 * page says so, and the list of mobeds can still be built.
 */

import { getCallout, sendCallout, pickFromCallout } from "../api.js";
import { chrome, mainEl, showFab, showError, showInfo, refreshHeader, loading, screenFailed, toTop } from "../ui.js";
import { esc } from "../util.js";
import { navigate, navGuard } from "../router.js";

const ANSWERS = { yes: "Yes, can pray", no: "Not this time" };

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

function answerHtml(p) {
  const answer = p.answer ? ANSWERS[p.answer] : "No answer yet";
  const lines = [
    p.asked && p.asked.why ? stateLine("WhatsApp", p.asked) : "",
    p.picked ? `<div><b>Going</b></div>${stateLine("Details", p.details)}` : "",
    stateLine("Enough mobeds message", p.enough),
  ].join("");
  const label = `<strong>${esc(p.name)}</strong> · ${esc(answer)}${lines}`;
  if (p.may_pick) {
    return `<div class="check-row"><input type="checkbox" id="pk_${p.id}" data-answer="${p.id}">
      <label for="pk_${p.id}">${label}</label></div>`;
  }
  return `<div class="search-result">${label}</div>`;
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
    if (e.status === 404) return screenFailed("Only the panthaky of the fire temple that accepted this request can ask its mobeds.");
    return screenFailed("Couldn't open this: " + e.message, () => renderCallout({ id }));
  }
  if (!alive()) return;
  draw(id, v);
}

function draw(id, v) {
  const on = v.whatsapp.on;
  const askable = v.candidates.filter(c => c.may_ask).length;
  const yeses = v.asked.filter(p => p.answer === "yes").length;
  mainEl.innerHTML = `
    <div class="card">
      <h2>Ask our mobeds: ${esc(v.prayed_name)}</h2>
      <div class="fact"><div class="fl">Place</div><div class="fv">${esc(v.place)}${v.bungli ? `, ${esc(v.bungli)}` : ""}</div></div>
      <div class="fact"><div class="fl">Geh-saarnu</div><div class="fv">${esc(v.geh_saarnu)}</div></div>
      <div class="fact"><div class="fl">Uthamna</div><div class="fv">${esc(v.uthamna)}</div></div>
      ${v.mobeds_wanted ? `<div class="fact"><div class="fl">Mobeds wanted</div><div class="fv">${v.mobeds_wanted}</div></div>` : ""}
      <p class="meta" style="margin:10px 0 0">The WhatsApp message asks whether they can pray, with these times. It
        has no family details: only those you pick get them.</p>
    </div>
    ${v.asked.length ? `<div class="card">
      <h2>Answers</h2>
      <p class="meta" style="margin:0 0 6px">${yeses} said yes. Tick who goes: they get the details and the family's
        contact. The others who said yes are told enough mobeds are going (only within 24 hours of their answer).</p>
      ${v.asked.map(answerHtml).join("")}
      ${v.asked.some(p => p.may_pick) ? `<div class="action-bar"><button type="button" id="coPick">Send the details to those picked</button></div>` : ""}
    </div>` : ""}
    <div class="card">
      <h2>Ask on WhatsApp</h2>
      ${on ? "" : `<p class="meta" style="margin:0 0 8px"><b>${esc(v.whatsapp.why_not)}</b> Until then you can build
        your list of mobeds.</p>`}
      ${v.candidates.length ? v.candidates.map(candidateHtml).join("")
        : `<p class="meta" style="margin:0">Nobody is on your list yet besides you.</p>`}
      <div class="action-bar">
        <button type="button" class="secondary" id="coList">Our mobeds</button>
        <button type="button" id="coSend" ${askable ? "" : "disabled"}>Ask on WhatsApp</button>
      </div>
    </div>`;

  document.getElementById("coList").onclick = () => navigate("#/our-mobeds");
  document.getElementById("coSend").onclick = async (ev) => {
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
      ? `Asked ${res.asked_now} of ${who.length} on WhatsApp. The others could not be sent: see below.`
      : `Asked ${res.asked_now} on WhatsApp. Their answers will show here.`);
  };
  const pickBtn = document.getElementById("coPick");
  if (pickBtn) {
    pickBtn.onclick = async () => {
      const answers = [...mainEl.querySelectorAll("[data-answer]:checked")].map(el => Number(el.dataset.answer));
      if (!answers.length) return showError("Please tick who goes.");
      pickBtn.disabled = true;
      let res;
      try {
        res = await pickFromCallout(id, answers);
      } catch (e) {
        pickBtn.disabled = false;
        return showError(e.message);
      }
      draw(id, res);
      toTop();
      const d = res.done;
      const words = [`${d.picked} picked. Details sent to ${d.details_sent}.`];
      if (d.enough_sent) words.push(`${d.enough_sent} told enough mobeds are going.`);
      if (d.enough_too_late) words.push(`${d.enough_too_late} not told: more than 24 hours had passed since they answered.`);
      (d.details_sent < d.picked ? showError : showInfo)(
        d.details_sent < d.picked ? words.join(" ") + " Some details could not be sent: see below." : words.join(" "));
    };
  }
}
