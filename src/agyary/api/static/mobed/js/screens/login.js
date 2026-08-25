"use strict";

/**
 * Two-step sign-in: phone -> code sent over WhatsApp -> session.
 *
 * Nothing but the phone number and the code is carried here. Signing in
 * neither creates nor raises a role: every membership this app makes is a
 * plain 'mobed'.
 */

import { requestOtp, verifyOtp, getMe, ApiError } from "../api.js";
import { state } from "../state.js";
import { chrome, mainEl, setHeader, showError, showInfo } from "../ui.js";
import { esc, phoneField, readPhone } from "../util.js";
import { navigate } from "../router.js";
import { afterSignIn } from "../session.js";

let countdownTimer = null;

function stopCountdown() {
  if (countdownTimer) { clearInterval(countdownTimer); countdownTimer = null; }
}

export function renderLogin() {
  stopCountdown();
  chrome(false);
  setHeader("Agyary");
  mainEl.innerHTML = `
    <div class="card">
      <h2>Sign in</h2>
      <p class="meta">Enter your WhatsApp number. We'll send you a code to confirm it's you.</p>
      <label>WhatsApp number</label>
      ${phoneField("loginPhone")}
      <div style="margin-top:14px"><button id="loginSend">Send code</button></div>
    </div>`;

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
  document.getElementById("otpBack").onclick = () => { stopCountdown(); renderLogin(); };
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
