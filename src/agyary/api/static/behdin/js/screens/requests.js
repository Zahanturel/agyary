"use strict";

/** Requests: the person's requests newest first, one request in full, and "Ask another fire temple". */

import { getMyAsks, getAsk, cancelAsk, askAnother } from "../api.js";
import { chrome, mainEl, setHeader, loading, wireRetry, loadFailedHtml, showError, showInfo, openSheet, closeSheet }
  from "/mobed-app/js/ui.js";
import { navGuard, navigate } from "/mobed-app/js/router.js";
import { esc, gregShort, longDay } from "../util.js";
import { mountPicker } from "./picker.js";
import { rupees, repeatWords } from "./request.js";

/** The chip that says where a request stands: the server's own label. */
export function chipHtml(r) {
  const kind = r.no_answer ? "noanswer" : r.changed ? "changed" : r.status;
  return `<span class="tag status-${kind}">${esc(r.label)}</span>`;
}

/** "Jashan, Afringan +1 · 29/11/2026": the one line a request is known by. */
export function summary(r) {
  const names = r.items.map((i) => i.name);
  const first = r.items[0];
  const text = names.length > 2 ? `${names.slice(0, 2).join(", ")} +${names.length - 2}` : names.join(", ");
  return `${text}${first ? ` · ${gregShort(first.date)}` : ""}`;
}

function rowHtml(r) {
  return `<div class="event" data-ask="${r.id}">
    <div class="ev-row"><div class="ev-main">
      <div class="t">${esc(summary(r))}</div>
      <div class="s">${esc(r.agyari.name || "")}${r.agyari.city ? ", " + esc(r.agyari.city) : ""}</div>
    </div>${chipHtml(r)}</div>
  </div>`;
}

export async function renderAsks() {
  chrome(true);
  setHeader("Requests");
  loading();
  const alive = navGuard();
  let list;
  try {
    list = (await getMyAsks()).asks;
  } catch (e) {
    if (!alive()) return;
    mainEl.innerHTML = loadFailedHtml("your requests");
    wireRetry(mainEl, () => renderAsks());
    return;
  }
  if (!alive()) return;
  mainEl.innerHTML = list.length ? list.map(rowHtml).join("") : `<div class="empty-state">No requests.</div>`;
  mainEl.querySelectorAll("[data-ask]").forEach((el) => { el.onclick = () => navigate(`#/asks/${el.dataset.ask}`); });
}

function line(label, text) {
  return `<div class="ask-line"><span class="meta">${esc(label)}</span><span>${text}</span></div>`;
}

function itemHtml(i) {
  const when = i.type === "memorial"
    ? `${i.memorial.name_known ? esc(i.memorial.departed_name) + ", " : ""}passed away ${esc(i.memorial.death_date_text)}`
    : `${esc(longDay(i.date))}${i.parsi ? `, ${esc(i.parsi)}` : ""}, ${i.geh_name ? esc(i.geh_name) + " geh" : i.time_open ? "time open" : esc(i.time)}`;
  const flag = i.state === "cancelled_by_fire_temple" ? "Cancelled by the fire temple" : i.changed ? "Changed" : "";
  return `<div class="ask-line"><b>${esc(i.name)}</b>
    <span>${when}</span>
    ${i.repeat ? `<span>${esc(repeatWords({ recurring: i.repeat.recurring, recurring_count: i.repeat.recurring_count }))}</span>` : ""}
    ${i.type === "memorial" && i.memorial.dates.length ? `<span class="meta">${i.memorial.dates.map((d) => `${esc(d.date_text)} ${esc(d.label)}`).join(", ")}</span>` : ""}
    ${i.total != null ? `<span class="meta">${rupees(i.total)}</span>` : ""}
    ${flag ? `<span class="tag grey">${flag}</span>` : ""}</div>`;
}

function detailHtml(r) {
  const out = [`<div class="card"><p style="margin:0 0 var(--space-2)">${chipHtml(r)}</p>
      <h2>${esc(r.agyari.name || "")}</h2>
      <p class="meta" style="margin:0">${esc(r.agyari.city || "")}</p>
      ${r.status === "rejected" && r.reject_reason ? `<p style="margin:var(--space-3) 0 0">Reason: ${esc(r.reject_reason)}</p>` : ""}
    </div><div class="card">${r.items.map(itemHtml).join("")}`];
  if (r.total != null) out.push(line("Total", `${rupees(r.total)}${r.total_is_estimate ? " (estimate)" : ""}`));
  if (r.names.length) out.push(line("Names", r.names.map(esc).join("<br>")));
  out.push("</div>");
  const buttons = [];
  if (r.can_ask_another) buttons.push(`<button type="button" id="askAnother">Ask another fire temple</button>`);
  if (r.can_cancel) buttons.push(`<button type="button" class="${r.can_ask_another ? "ghost " : ""}danger-outline" id="askCancel">Cancel</button>`);
  if (buttons.length) out.push(`<div class="stack">${buttons.join("")}</div>`);
  return out.join("");
}

export async function renderAskView(params) {
  chrome(true);
  setHeader("Request");
  loading();
  const alive = navGuard();
  const id = Number(params.id);
  let r;
  try {
    r = await getAsk(id);
  } catch (e) {
    if (!alive()) return;
    mainEl.innerHTML = e.status === 404 ? `<div class="card"><p>Request not found.</p></div>` : loadFailedHtml("this request");
    wireRetry(mainEl, () => renderAskView(params));
    return;
  }
  if (!alive()) return;
  mainEl.innerHTML = detailHtml(r);

  const another = document.getElementById("askAnother");
  if (another) another.onclick = () => navigate(`#/asks/${id}/another`);

  const cancel = document.getElementById("askCancel");
  if (cancel) {
    cancel.onclick = () => {
      const { body } = openSheet({
        title: "Cancel this request?",
        html: `<p><b>${esc(summary(r))}</b></p>
          <div class="row tight"><button type="button" class="danger" id="askYes">Cancel request</button>
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
        showInfo("Request cancelled.");
        renderAskView(params);
      };
    };
  }
}

/** Another fire temple for a request that was declined, cancelled or not answered: the request is copied. */
export async function renderAskAnother(params) {
  chrome(true);
  setHeader("Another fire temple");
  loading();
  const alive = navGuard();
  const id = Number(params.id);
  if (!alive()) return;
  mainEl.innerHTML = `<div id="anyPick"></div>`;
  mountPicker(document.getElementById("anyPick"), {
    alive, pickLabel: "Send here",
    onPick: async (temple) => {
      let made;
      try {
        made = await askAnother(id, temple.id);
      } catch (err) {
        return showError(err.message);
      }
      showInfo(`Request sent to ${temple.name}.`);
      navigate(`#/asks/${made.id}`, { replace: true });
    },
  });
}
