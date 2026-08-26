"use strict";

/**
 * Sign in.
 *
 * One path: we mint a code, the mobed sends it to us from their own
 * WhatsApp, and we learn their number from the message. They never type a
 * phone number, so there is nothing here to enumerate, and because we never
 * send anything it needs no approved template and costs nothing per sign-in.
 *
 * Signing in neither creates nor raises a role: every membership this app
 * makes is a plain 'mobed'.
 */

import {
  getMe, waLoginStart, waLoginPoll, waLoginComplete,
} from "../api.js";
import { state } from "../state.js";
import { chrome, mainEl, setHeader, showError } from "../ui.js";
import { esc } from "../util.js";
import { navigate } from "../router.js";
import { afterSignIn } from "../session.js";

let pollTimer = null;

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

export function renderLogin() {
  stopPolling();
  chrome(false);
  setHeader("Agyary");
  mainEl.innerHTML = `
    <div class="card">
      <h2>Sign in</h2>
      <p class="meta">
        Tap below to open WhatsApp with a one-time code ready to send.
        Send it and you're in - there's nothing to type.
      </p>
      <div style="margin-top:14px"><button id="waStart">Sign in with WhatsApp</button></div>
    </div>`;

  document.getElementById("waStart").onclick = startWaLogin;
}

async function startWaLogin() {
  const btn = document.getElementById("waStart");
  btn.disabled = true;
  btn.textContent = "Preparing...";
  let started;
  try {
    started = await waLoginStart();
  } catch (e) {
    btn.disabled = false;
    btn.textContent = "Sign in with WhatsApp";
    return showError(e.message);
  }
  renderWaWaiting(started);
}

function renderWaWaiting(started) {
  stopPolling();
  mainEl.innerHTML = `
    <div class="card">
      <h2>Send the code</h2>
      <p class="meta">
        WhatsApp should have opened with the message ready. Send it, then
        come back here - this page signs you in by itself.
      </p>
      <div style="margin-top:14px">
        <a class="button" id="waOpen" href="${esc(started.wa_link)}" target="_blank" rel="noopener">
          Open WhatsApp
        </a>
      </div>
      <p class="meta" style="margin-top:16px">
        If you'd rather type it, send this to our number:
      </p>
      <div class="code-display">${esc(started.code)}</div>
      <p class="meta" id="waStatus" style="margin-top:16px">Waiting for your message...</p>
      <div style="margin-top:14px">
        <button class="ghost small" id="waCancel">Start again</button>
      </div>
    </div>`;

  // Opening it for them saves a tap; the visible link is the fallback for
  // browsers that block a programmatic navigation to a new tab.
  window.open(started.wa_link, "_blank", "noopener");

  document.getElementById("waCancel").onclick = () => { stopPolling(); renderLogin(); };

  // Two seconds is brisk enough to feel instant when they switch back, and
  // the endpoint does one indexed lookup.
  pollTimer = setInterval(pollOnce, 2000);
  pollOnce();
}

async function pollOnce() {
  let res;
  try {
    res = await waLoginPoll();
  } catch (e) {
    stopPolling();
    return showError(e.message);
  }
  if (res.status === "pending") return;

  stopPolling();
  if (res.status === "needs_name") return renderWaNameStep();
  await finishSignIn(res);
}

function renderWaNameStep() {
  mainEl.innerHTML = `
    <div class="card">
      <h2>What should we call you?</h2>
      <p class="meta">
        Your first time here. This is the name that appears on your slips.
      </p>
      <label>Name</label>
      <input type="text" id="waName" placeholder="e.g. Er. Pervez Kias" autocomplete="name">
      <div style="margin-top:14px"><button id="waNameSave">Continue</button></div>
    </div>`;

  const nameEl = document.getElementById("waName");
  nameEl.focus();
  const save = async () => {
    const name = nameEl.value.trim();
    if (!name) return showError("Please enter your name.");
    const btn = document.getElementById("waNameSave");
    btn.disabled = true;
    btn.textContent = "Signing in...";
    try {
      await finishSignIn(await waLoginComplete(name));
    } catch (e) {
      btn.disabled = false;
      btn.textContent = "Continue";
      showError(e.message);
    }
  };
  document.getElementById("waNameSave").onclick = save;
  nameEl.onkeydown = (e) => { if (e.key === "Enter") save(); };
}

async function finishSignIn(res) {
  state.accessToken = res.access_token;
  state.user = res.user;
  await afterSignIn();
}


/** Signed in but not a member of any fire temple yet. */
export async function ensureMembership() {
  if (state.user && (state.user.agyaries || []).length) return true;
  navigate("#/onboarding");
  return false;
}

export async function reloadUser() {
  state.user = await getMe();
}
