"use strict";

/**
 * "My asks": every ask the person has made, newest first, each with where it stands; one ask in full,
 * with Cancel and (once it has been turned down, cancelled or not answered) "Ask another fire temple".
 */

import { getMyAsks, getAsk, cancelAsk, askAnother } from "../api.js";
import { chrome, mainEl, setHeader, loading, wireRetry, loadFailedHtml, showError, showInfo, openSheet, closeSheet }
  from "/mobed-app/js/ui.js";
import { navGuard, navigate } from "/mobed-app/js/router.js";
import { esc, todayIst, addDays, longDay, gregShort } from "../util.js";
import { mountPicker } from "./picker.js";
import { repeatWords } from "./ask.js";

/** The chip that says where an ask stands: the server's own label, with a colour for each. */
export function chipHtml(ask) {
  const kind = ask.no_answer ? "noanswer" : ask.status;
  return `<span class="tag status-${kind}">${esc(ask.label)}</span>`;
}

/** "Jashan, 25/12/2026, at Goti Adarian": the one line an ask is known by. */
export function askLine(a) {
  const when = a.kind === "memorial" ? `from ${gregShort(a.date)}` : gregShort(a.date);
  return `${a.service.name}, ${when}, at ${a.agyari.name || "a fire temple"}`;
}

function rowHtml(a) {
  return `<div class="event" data-ask="${a.id}">
    <div class="ev-row"><div class="ev-main">
      <div class="t">${esc(a.service.name)}</div>
      <div class="s">${esc(a.kind === "memorial" ? `From ${gregShort(a.date)}` : longDay(a.date))}${a.parsi ? ", " + esc(a.parsi) : ""}</div>
      <div class="s">${esc(a.agyari.name || "")}${a.agyari.city ? ", " + esc(a.agyari.city) : ""}</div>
    </div>${chipHtml(a)}</div>
  </div>`;
}

export async function renderAsks() {
  chrome(true);
  setHeader("My asks");
  loading();
  const alive = navGuard();
  let asks;
  try {
    asks = (await getMyAsks()).asks;
  } catch (e) {
    if (!alive()) return;
    mainEl.innerHTML = loadFailedHtml("your asks");
    wireRetry(mainEl, () => renderAsks());
    return;
  }
  if (!alive()) return;
  mainEl.innerHTML = asks.length
    ? asks.map(rowHtml).join("")
    : `<div class="empty-state">No asks yet.</div>`;
  mainEl.querySelectorAll("[data-ask]").forEach((el) => { el.onclick = () => navigate(`#/asks/${el.dataset.ask}`); });
}

function line(label, text) {
  return `<div class="ask-line"><span class="meta">${esc(label)}</span><span>${text}</span></div>`;
}

function whenText(a) {
  if (a.kind === "memorial") return "";
  return `${esc(longDay(a.date))}${a.parsi ? `<br><span class="meta">${esc(a.parsi)}</span>` : ""}`
    + (a.geh_name ? `<br>${esc(a.geh_name)} geh` : a.time ? `<br>${esc(a.time)}` : "");
}

const TITLES = { khud: "Myself", osta: "Mr (Osta)", osti: "Mrs (Osti)", ervad: "Ervad", behdin: "Behdin" };

function detailHtml(a) {
  const names = a.names || [];
  const out = [
    `<div class="card"><p style="margin:0 0 var(--space-2)">${chipHtml(a)}</p>
      <h2>${esc(a.service.name)}</h2>
      <p class="meta" style="margin:0">${esc(a.agyari.name || "")}${a.agyari.city ? ", " + esc(a.agyari.city) : ""}</p>`,
  ];
  if (a.status === "rejected") {
    out.push(`<p style="margin:var(--space-3) 0 0"><b>${esc(a.agyari.name || "The fire temple")} cannot take this.</b>
      ${a.reject_reason ? `<br>${esc(a.reject_reason)}` : ""}</p>`);
  } else if (a.no_answer) {
    out.push(`<p style="margin:var(--space-3) 0 0"><b>No answer yet.</b></p>`);
  } else if (a.status === "accepted") {
    out.push(`<p style="margin:var(--space-3) 0 0"><b>${esc(a.agyari.name || "The fire temple")} accepted this ask.</b></p>`);
  }
  out.push(`</div><div class="card">`);
  if (a.purpose && a.kind !== "memorial") out.push(line("For", esc(a.purpose_label)));
  if (a.kind === "memorial") {
    out.push(line("Days", `For ${esc(a.memorial.departed_name)}:<br>${a.memorial.dates.map((d) =>
      `${esc(gregShort(d.date))} ${esc(d.label)}${d.parsi ? ` <span class="meta">${esc(d.parsi)}</span>` : ""}`).join("<br>")}`));
  } else {
    out.push(line("When", whenText(a)));
  }
  out.push(line("Where", a.where === "home" ? `At home, ${esc(a.area || "")}` : "At the fire temple"));
  if (a.repeat) out.push(line("Repeats", esc(repeatWords(a.repeat))));
  out.push(line("Names", names.length ? names.map((n) => `${esc(n.name)} <span class="meta">${esc(TITLES[n.title] || "")}</span>`).join("<br>") : "None"));
  if (a.note) out.push(line("Note", esc(a.note)));
  out.push(`</div>`);
  const buttons = [];
  if (a.can_ask_another) buttons.push(`<button type="button" id="askAnother">Ask another fire temple</button>`);
  if (a.can_cancel) buttons.push(`<button type="button" class="${a.can_ask_another ? "ghost " : ""}danger-outline" id="askCancel">Cancel this ask</button>`);
  if (buttons.length) out.push(`<div class="stack">${buttons.join("")}</div>`);
  return out.join("");
}

export async function renderAskView(params) {
  chrome(true);
  setHeader("My ask");
  loading();
  const alive = navGuard();
  const id = Number(params.id);
  let a;
  try {
    a = await getAsk(id);
  } catch (e) {
    if (!alive()) return;
    mainEl.innerHTML = e.status === 404
      ? `<div class="card"><p>That ask could not be found.</p></div>`
      : loadFailedHtml("this ask");
    wireRetry(mainEl, () => renderAskView(params));
    return;
  }
  if (!alive()) return;
  mainEl.innerHTML = detailHtml(a);

  const another = document.getElementById("askAnother");
  if (another) another.onclick = () => navigate(`#/asks/${id}/another`);

  const cancel = document.getElementById("askCancel");
  if (cancel) {
    cancel.onclick = () => {
      const accepted = a.status === "accepted";
      const soon = a.date <= addDays(todayIst(), 1);
      const { body } = openSheet({
        title: "Cancel this ask?",
        html: `<p><b>${esc(askLine(a))}</b></p>
          <p class="meta">${accepted
            ? `${esc(a.agyari.name || "The fire temple")} will be told.`
            : `${esc(a.agyari.name || "The fire temple")}'s panthaky will be told.`}
            ${accepted && soon ? "<br><b>Please also call them, as the day is so close.</b>" : ""}</p>
          <div class="row tight"><button type="button" class="danger" id="askYes">Cancel this ask</button>
          <button type="button" class="ghost" id="askNo">Keep it</button></div>`,
      });
      body.querySelector("#askNo").onclick = closeSheet;
      body.querySelector("#askYes").onclick = async (e) => {
        const btn = e.currentTarget;
        btn.disabled = true;
        try {
          await cancelAsk(id);
        } catch (err) {
          btn.disabled = false;
          return showError(err.message);
        }
        closeSheet();
        showInfo("Your ask was cancelled.");
        renderAskView(params);
      };
    };
  }
}

/** Pick another fire temple for an ask that was turned down, cancelled or not answered: the ask is copied. */
export async function renderAskAnother(params) {
  chrome(true);
  setHeader("Ask another fire temple");
  loading();
  const alive = navGuard();
  const id = Number(params.id);
  let a;
  try {
    a = await getAsk(id);
  } catch (e) {
    if (!alive()) return;
    mainEl.innerHTML = loadFailedHtml("this ask");
    wireRetry(mainEl, () => renderAskAnother(params));
    return;
  }
  if (!alive()) return;
  mainEl.innerHTML = `<div class="card"><h2>${esc(a.service.name)}, ${esc(gregShort(a.date))}</h2>
    </div><div id="anyPick"></div>`;
  mountPicker(document.getElementById("anyPick"), {
    alive, pickLabel: "Ask this fire temple",
    onPick: async (temple) => {
      let made;
      try {
        made = await askAnother(id, temple.id);
      } catch (err) {
        return showError(err.message);
      }
      showInfo(`Your ask was sent to ${temple.name}.`);
      navigate(`#/asks/${made.id}`, { replace: true });
    },
  });
}
