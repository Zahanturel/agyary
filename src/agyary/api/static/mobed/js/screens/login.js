"use strict";

/**
 * Sign in, two ways.
 *
 * The default is inbound: we mint a code, the mobed sends it to us from
 * their own WhatsApp, and we learn their number from the message. They
 * never type a phone number, so there is nothing here to enumerate, and
 * because we never send anything it needs no approved template and costs
 * nothing per sign-in.
 *
 * The older path - type a number, receive a code - is kept behind a link
 * as a fallback while inbound proves itself against a real number.
 *
 * Signing in neither creates nor raises a role: every membership this app
 * makes is a plain 'mobed'.
 */

import {
  requestOtp, verifyOtp, getMe, ApiError,
  waLoginStart, waLoginPoll, waLoginComplete,
} from "../api.js";
import { state } from "../state.js";
import { chrome, mainEl, setHeader, showError, showInfo } from "../ui.js";
import { esc, phoneField, readPhone } from "../util.js";
import { navigate } from "../router.js";
import { afterSignIn } from "../session.js";

let countdownTimer = null;

function stopCountdown() {
  if (countdownTimer) { clearInterval(countdownTimer); countdownTimer = null; }
}

// --- Inbound: they message us ------------------------------------------------
let pollTimer = null;

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

export function renderLogin() {
  stopCountdown();
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
      <div style="margin-top:18px">
        <button class="ghost small" id="useOtp">Use a phone number and code instead</button>
      </div>
    </div>`;

  document.getElementById("waStart").onclick = startWaLogin;
  document.getElementById("useOtp").onclick = renderOtpLogin;
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


// --- Fallback: we message them -----------------------------------------------
export function renderOtpLogin() {
  stopCountdown();
  stopPolling();
  chrome(false);
  setHeader("Agyary");
  mainEl.innerHTML = `
    <div class="card">
      <h2>Sign in</h2>
      <p class="meta">Enter your WhatsApp number. We'll send you a code to confirm it's you.</p>
      <label>WhatsApp number</label>
      ${phoneField("loginPhone")}
      <div style="margin-top:14px"><button id="loginSend">Send code</button></div>
      <div style="margin-top:18px">
        <button class="ghost small" id="useWa">Sign in with WhatsApp instead</button>
      </div>
    </div>`;

  document.getElementById("useWa").onclick = renderLogin;

  document.getElementById("loginSend").onclick = async () => {
    const phone = readPhone("loginPhone");
    if (!phone) return showError("Please enter a valid phone number.");
    const btn = document.getElementById("loginSend");
    btn.disabled = true;
    btn.textContent = "Sending...";
    try {
      const res = await requestOtp(phone);
      renderCodeStep(phone, res.expires_in_seconds || 300);
    } catch (e) {
      btn.disabled = false;
      btn.textContent = "Send code";
      showError(e.message);
    }
  };
}

function renderCodeStep(phone, ttlSeconds) {
  stopCountdown();
  chrome(false);
  mainEl.innerHTML = `
    <div class="card">
      <h2>Enter your code</h2>
      <p class="meta">We sent a 6-digit code to ${esc(phone)} on WhatsApp.</p>
      <label>Code</label>
      <input type="text" id="otpCode" class="otp-input" inputmode="numeric"
             autocomplete="one-time-code" maxlength="6" placeholder="------">
      <label>Your name</label>
      <input type="text" id="otpName" placeholder="e.g. Er. Firstname Lastname">
      <p class="meta">Only needed the first time you sign in.</p>
      <div style="margin-top:14px"><button id="otpVerify">Sign in</button></div>
      <div style="margin-top:12px" class="row tight" style="justify-content:space-between">
        <span class="meta countdown" id="otpCountdown"></span>
        <button class="ghost small hidden" id="otpResend">Send a new code</button>
      </div>
      <div style="margin-top:10px"><button class="ghost small" id="otpBack">Use a different number</button></div>
    </div>`;

  const codeInput = document.getElementById("otpCode");
  codeInput.focus();
  // Digits only, and submit itself once six are in - the code arrives in
  // another app, so the fewer taps between reading it and being signed in
  // the better.
  codeInput.oninput = () => {
    codeInput.value = codeInput.value.replace(/\D/g, "").slice(0, 6);
    if (codeInput.value.length === 6) submit();
  };

  startCountdown(ttlSeconds);
  // Back to the number entry, not to the inbound screen - they chose this path.
  document.getElementById("otpBack").onclick = () => { stopCountdown(); renderOtpLogin(); };
  document.getElementById("otpVerify").onclick = submit;
  document.getElementById("otpResend").onclick = async () => {
    try {
      const res = await requestOtp(phone);
      showInfo("A new code is on its way.");
      startCountdown(res.expires_in_seconds || 300);
      codeInput.value = "";
      codeInput.focus();
    } catch (e) {
      showError(e.message);
    }
  };

  async function submit() {
    const code = codeInput.value.trim();
    const name = document.getElementById("otpName").value.trim();
    if (code.length !== 6) return showError("Please enter the 6-digit code.");
    const btn = document.getElementById("otpVerify");
    btn.disabled = true;
    try {
      const data = await verifyOtp(phone, code, name);
      stopCountdown();
      state.accessToken = data.access_token;
      state.user = data.user;
      await afterSignIn();
    } catch (e) {
      btn.disabled = false;
      // The server counts attempts and says how many are left, so surface
      // its message rather than a generic one. Running out invalidates the
      // code entirely - offer a new one immediately rather than leaving
      // the user typing into a dead field.
      showError(e.message);
      codeInput.value = "";
      codeInput.focus();
      if (e instanceof ApiError && /too many/i.test(e.detail || "")) {
        stopCountdown();
        revealResend("That code is no longer usable.");
      }
    }
  }
}

function startCountdown(seconds) {
  stopCountdown();
  const el = document.getElementById("otpCountdown");
  const resend = document.getElementById("otpResend");
  resend.classList.add("hidden");
  let left = seconds;
  const tick = () => {
    if (left <= 0) {
      stopCountdown();
      revealResend("Your code has expired.");
      return;
    }
    const m = Math.floor(left / 60);
    const s = String(left % 60).padStart(2, "0");
    el.textContent = `Code expires in ${m}:${s}`;
    left -= 1;
  };
  tick();
  countdownTimer = setInterval(tick, 1000);
}

function revealResend(reason) {
  const el = document.getElementById("otpCountdown");
  const resend = document.getElementById("otpResend");
  if (el) el.textContent = reason;
  if (resend) resend.classList.remove("hidden");
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
