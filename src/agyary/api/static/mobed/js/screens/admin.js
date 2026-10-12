"use strict";

/**
 * Admin: what sending has cost so far, and the switch that stops it.
 *
 * Only for the numbers in the server's ADMIN_PHONES. The menu entry is hidden
 * from everyone else, and the server answers anyone else with a 404 whatever
 * this screen does, so hiding it is a courtesy and not the protection.
 */

import { adminOverview, adminSetPaused } from "../api.js";
import {
  chrome, mainEl, showFab, showError, showInfo, refreshHeader, loading, backBar,
} from "../ui.js";
import { esc, gregShort, istHm } from "../util.js";
import { navGuard } from "../router.js";

const rupees = (n) => "Rs " + Number(n).toFixed(2);

function fact(label, value) {
  return `<div class="fact"><div class="fl">${esc(label)}</div><div class="fv">${value}</div></div>`;
}

export async function renderAdmin() {
  chrome(true);
  refreshHeader();
  showFab(false);
  loading();
  const alive = navGuard();

  let o;
  try {
    o = await adminOverview();
  } catch (e) {
    if (!alive()) return;
    mainEl.innerHTML = "";
    return showError(e.status === 404 ? "That page isn't available." : e.message);
  }
  if (!alive()) return;

  const r = o.reminders;
  const state = r.paused
    ? `<span class="tag" style="background:var(--danger-600);color:#fff">Paused</span>`
    : r.mode === "live" ? `<span class="tag role">Sending</span>`
    : `<span class="tag grey">${r.mode === "off" ? "Off" : "Dry run"}</span>`;

  mainEl.innerHTML = `
    <div class="card">
      ${backBar("Admin")}
      <p class="meta" style="margin:4px 0 0">What WhatsApp sending is doing, and what it could cost.</p>
    </div>

    <div class="card">
      <h2>Reminders ${state}</h2>
      ${r.paused ? `<p class="meta" style="color:var(--danger-600)"><b>Paused:</b> ${esc(r.paused)}</p>` : ""}
      ${fact("Sending to", r.sending_to ? esc(r.sending_to) : "-")}
      ${fact("Today", `${r.today} of ${r.caps.daily}`)}
      ${fact("This month", `${r.month} of ${r.caps.monthly}`)}
      ${fact("Estimated cost this month", rupees(r.estimated_month_cost_inr))}
      <p class="meta" style="margin-top:10px">Limits per mobed: ${r.caps.per_mobed} a day.
        Per fire temple: ${r.caps.per_agyary} a day. The cost is an estimate;
        Meta's own bill is the real one.</p>
      <div style="margin-top:12px">
        ${r.paused
          ? `<button id="admResume">Resume sending</button>`
          : `<button class="danger" id="admPause">Pause all sending</button>`}
      </div>
      <div id="admConfirm" style="margin-top:12px"></div>
    </div>

    <div class="card">
      <h2>Sign-in codes</h2>
      ${fact("Status", o.otp.mode === "live" ? "On" : "Off")}
      ${fact("Sent today", `${o.otp.today} of ${o.otp.daily_cap}`)}
    </div>

    <div class="card">
      <h2>Recent failures</h2>
      ${o.recent_failures.length ? o.recent_failures.map(f => `
        <div class="list-row"><div class="lr-main"><b>${esc(f.to)}</b>
          <span>${esc(gregShort(f.when.slice(0, 10)))} ${esc(istHm(f.when))} - ${esc(f.reason)}</span></div></div>
      `).join("") : `<p class="meta">None.</p>`}
    </div>`;

  const confirm = document.getElementById("admConfirm");
  const apply = async (paused, reason) => {
    try {
      await adminSetPaused(paused, reason);
      showInfo(paused ? "Sending paused." : "Sending resumed.");
      renderAdmin();
    } catch (e) { showError(e.message); }
  };

  const resume = document.getElementById("admResume");
  if (resume) resume.onclick = () => apply(false, "");

  const pause = document.getElementById("admPause");
  if (pause) pause.onclick = () => {
    confirm.innerHTML = `
      <p class="meta">This stops every reminder and sign-in code at once, within a minute.
        Mobeds are told when a reminder they were counting on was not sent.</p>
      <label>Why (optional)</label>
      <input type="text" id="admReason" placeholder="e.g. checking the bill" autocomplete="off">
      <div class="row tight" style="margin-top:10px">
        <button class="danger small" id="admPauseGo">Pause</button>
        <button class="ghost small" id="admPauseNo">Cancel</button>
      </div>`;
    document.getElementById("admPauseNo").onclick = () => { confirm.innerHTML = ""; };
    document.getElementById("admPauseGo").onclick = () =>
      apply(true, document.getElementById("admReason").value);
  };
}
