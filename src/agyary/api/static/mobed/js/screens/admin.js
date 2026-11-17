"use strict";

/**
 * Admin: what sending has cost so far, and the switch that stops it.
 *
 * Only for the numbers in the server's ADMIN_PHONES. The menu entry is hidden
 * from everyone else, and the server answers anyone else with a 404 whatever
 * this screen does, so hiding it is a courtesy and not the protection.
 */

import {
  adminOverview, adminSetPaused, adminSignOutEverywhere, adminEraseNumber, adminPush, adminPushTest,
} from "../api.js";
import * as push from "../push.js";
import {
  chrome, mainEl, showFab, showError, showInfo, refreshHeader, loading, backBar, screenFailed,
} from "../ui.js";
import { esc, gregShort, istHm, phoneField, readPhone } from "../util.js";
import { navGuard, navigate } from "../router.js";
import { flagProblems } from "../fielderrors.js";

/** A number that will not do is said on its own box: the card has only the one. */
function flagPhone(id) {
  const field = document.getElementById(id).closest(".phone-field");
  flagProblems(field.closest(".card"), [{ target: field, message: "Please enter a valid phone number." }]);
}

const rupees = (n) => "Rs " + Number(n).toFixed(2);

/** The "Notifications on this phone" card: a new mobed waiting shows on this
 *  phone even when the app is closed. Drawn into `box` once it knows. */
async function paintPush(box, alive) {
  const plural = (n) => `${n} phone${n === 1 ? "" : "s"}`;
  let status, sub;
  try {
    [status, sub] = await Promise.all([adminPush(), push.current()]);
  } catch (e) {
    if (alive()) box.innerHTML = `<p class="meta">${esc(e.message)}</p>`;
    return;
  }
  if (!alive()) return;
  const again = () => paintPush(box, alive);

  if (!status.configured) {
    box.innerHTML = `<p class="meta">Not set up on the server yet. Once the server has its notification keys,
      you can turn them on here.</p>`;
    return;
  }
  const blocked = push.blockerHere();
  if (blocked && !sub) {
    box.innerHTML = `<p class="meta">${esc(blocked)}</p>
      <div style="margin-top:10px"><button class="secondary small" id="admPushRetry">Check again</button></div>`;
    document.getElementById("admPushRetry").onclick = again;
    return;
  }
  if (sub) {
    box.innerHTML = `<p class="meta"><b>On for this phone.</b> When a new mobed is waiting, it shows here even
        when Mobed Diary is closed.${status.devices > 1 ? ` On for ${plural(status.devices)} in all.` : ""}</p>
      <div class="action-bar" style="margin-top:10px">
        <button class="small" id="admPushTest">Send a test</button>
        <button class="ghost small" id="admPushOff">Turn off on this phone</button>
      </div>`;
    document.getElementById("admPushTest").onclick = async (ev) => {
      const btn = ev.currentTarget;
      btn.disabled = true;
      try {
        const r = await adminPushTest();
        if (r.sent) showInfo(`Test sent to ${plural(r.sent)}. It should appear in a few seconds.`);
        else showError("The test could not be delivered. Turn notifications off on this phone and on again.");
      } catch (e) {
        showError(e.message);
      } finally {
        btn.disabled = false;
      }
    };
    document.getElementById("admPushOff").onclick = async (ev) => {
      ev.currentTarget.disabled = true;
      try {
        await push.turnOff();
        showInfo("Notifications are off on this phone.");
      } catch (e) {
        showError(e.message);
      }
      if (alive()) again();
    };
    return;
  }
  box.innerHTML = `<p class="meta">Get a notification on this phone when a new mobed is waiting for approval,
      even when Mobed Diary is closed.${status.devices ? ` On for ${plural(status.devices)} already.` : ""}</p>
    <div style="margin-top:10px"><button class="small" id="admPushOn">Turn on for this phone</button></div>`;
  document.getElementById("admPushOn").onclick = async (ev) => {
    const btn = ev.currentTarget;
    btn.disabled = true;
    try {
      await push.turnOn();
      showInfo("Notifications are on for this phone. Try Send a test.");
    } catch (e) {
      btn.disabled = false;
      return showError(e.message);
    }
    if (alive()) again();
  };
}

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
    // Said in the page, not over a blank one. A 404 is the server saying this
    // is not an admin's phone, which trying again will not change.
    if (e.status === 404) return screenFailed("That page isn't available.");
    return screenFailed(e.message, () => renderAdmin());
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
      <h2>Mobeds ${o.mobeds_waiting
        ? `<span class="tag" style="background:var(--amber-100);color:var(--amber-600)">${o.mobeds_waiting} waiting</span>` : ""}</h2>
      <p class="meta">${o.mobeds_waiting
        ? `${o.mobeds_waiting} new mobed${o.mobeds_waiting === 1 ? " is" : "s are"} waiting for your approval.`
        : "Nobody is waiting for approval."}${o.panthaky_claims_waiting
        ? ` ${o.panthaky_claims_waiting} say${o.panthaky_claims_waiting === 1 ? "s" : ""} they are a panthaky.` : ""}
        Approve new mobeds, confirm panthakys, and turn any mobed off or on.</p>
      <div style="margin-top:10px"><button class="small" id="admMobeds">Open Mobeds</button></div>
    </div>

    <div class="card">
      <h2>Notifications on this phone</h2>
      <div id="admPush"><p class="meta">Checking...</p></div>
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
      ${fact("Bot check", o.otp.bot_check ? "On" : "Not set up")}
      ${o.otp.mode === "live" && !o.otp.bot_check ? `<p class="meta" style="margin:8px 0 0">Anyone can ask
        for codes without passing a bot check. Add the TURNSTILE keys to the server's settings.</p>` : ""}
    </div>

    <div class="card">
      <h2>Recent failures</h2>
      ${o.recent_failures.length ? o.recent_failures.map(f => `
        <div class="list-row"><div class="lr-main"><b>${esc(f.to)}</b>
          <span>${esc(gregShort(f.when.slice(0, 10)))} ${esc(istHm(f.when))} - ${esc(f.reason)}</span></div></div>
      `).join("") : `<p class="meta">None.</p>`}
    </div>

    <div class="card">
      <h2>Sign a mobed out everywhere</h2>
      <p class="meta">Ends every device they are signed in on - a lost or taken phone, or a
        sign-in nobody recognises. They can sign in again with WhatsApp.</p>
      <label for="admOut">Their WhatsApp number</label>
      ${phoneField("admOut", "")}
      <div style="margin-top:10px"><button class="secondary small" id="admOutGo">Sign them out</button></div>
    </div>

    <div class="card">
      <h2>Erase a family</h2>
      <p class="meta">When a family asks to be removed. This takes their name, number, memorials and
        prayer names out of every mobed's book. It cannot be undone.</p>
      <label for="admErase">The family's WhatsApp number</label>
      ${phoneField("admErase", "")}
      <div style="margin-top:10px"><button class="secondary small" id="admEraseFind">See what we hold</button></div>
      <div id="admEraseAsk" style="margin-top:12px"></div>
    </div>`;

  document.getElementById("admMobeds").onclick = () => navigate("#/admin/mobeds");
  paintPush(document.getElementById("admPush"), alive);

  const askErase = document.getElementById("admEraseAsk");
  document.getElementById("admEraseFind").onclick = async (ev) => {
    const findBtn = ev.currentTarget;
    askErase.innerHTML = "";
    const phone = readPhone("admErase");
    if (!phone) return flagPhone("admErase");
    let f;
    findBtn.disabled = true;   // one look-up per tap
    try {
      f = (await adminEraseNumber(phone, false)).found;
    } catch (e) {
      return showError(e.message);
    } finally {
      findBtn.disabled = false;
    }
    if (!f.records && !f.messages) {
      askErase.innerHTML = `<p class="meta">We hold nothing for that number.</p>`;
      return;
    }
    askErase.innerHTML = `
      <p class="meta">We hold ${f.records} record${f.records === 1 ? "" : "s"} with ${f.mobeds}
        mobed${f.mobeds === 1 ? "" : "s"}: ${f.memorials} memorial${f.memorials === 1 ? "" : "s"},
        ${f.events} event${f.events === 1 ? "" : "s"} and ${f.messages} message${f.messages === 1 ? "" : "s"}.
        Past events stay on the calendar, marked Erased. Each mobed is told. If they replied STOP, that stays.</p>
      <div class="row tight" style="margin-top:10px">
        <button class="danger small" id="admEraseGo">Erase for good</button>
        <button class="ghost small" id="admEraseNo">Cancel</button>
      </div>`;
    document.getElementById("admEraseNo").onclick = () => { askErase.innerHTML = ""; };
    document.getElementById("admEraseGo").onclick = async (ev) => {
      const btn = ev.currentTarget;
      btn.disabled = true;
      try {
        await adminEraseNumber(phone, true);
        askErase.innerHTML = "";
        showInfo("That family's details have been erased.");
      } catch (e) {
        // It stayed disabled after a failure, so the only way on was Cancel
        // and the whole look-up again.
        btn.disabled = false;
        showError(e.message);
      }
    };
  };

  const confirm = document.getElementById("admConfirm");
  /** Pause or resume. `btn` is the button pressed: off while the change is
   *  made, and back on if it fails. */
  const apply = async (paused, reason, btn) => {
    btn.disabled = true;
    try {
      await adminSetPaused(paused, reason);
    } catch (e) {
      btn.disabled = false;
      return showError(e.message);
    }
    showInfo(paused ? "Sending paused." : "Sending resumed.");
    // Gone to another screen meanwhile: it is done and said, and this page
    // must not be drawn over the screen that is there now.
    if (!alive()) return;
    // The same screen with its new figures: it stays where it was. Drawing it
    // again passes through "Loading...", which would otherwise leave it at the top.
    const y = window.scrollY;
    await renderAdmin();
    if (alive()) window.scrollTo(0, y);
  };

  document.getElementById("admOutGo").onclick = async (ev) => {
    const btn = ev.currentTarget;
    const phone = readPhone("admOut");
    if (!phone) return flagPhone("admOut");
    btn.disabled = true;   // one request per tap
    try {
      const r = await adminSignOutEverywhere(phone);
      showInfo(`Signed out of ${r.signed_out} device${r.signed_out === 1 ? "" : "s"}.`);
    } catch (e) {
      showError(e.message);
    } finally {
      btn.disabled = false;
    }
  };

  const resume = document.getElementById("admResume");
  if (resume) resume.onclick = (ev) => apply(false, "", ev.currentTarget);

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
    document.getElementById("admPauseGo").onclick = (ev) =>
      apply(true, document.getElementById("admReason").value, ev.currentTarget);
  };
}
