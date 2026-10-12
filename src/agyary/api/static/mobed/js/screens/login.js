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
  getMe, waLoginStart, waLoginPoll, waLoginComplete, authOptions, otpRequest, otpVerify,
} from "../api.js";
import { state } from "../state.js";
import { chrome, mainEl, setHeader, showError } from "../ui.js";
import { esc, phoneField, readPhone } from "../util.js";
import { navigate } from "../router.js";
import { afterSignIn } from "../session.js";

let pollTimer = null;
let otpCleanup = null;

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

/** Sign-in by code, when the server offers it: type your number, get a code on
 *  WhatsApp, and the app picks it up from the clipboard and signs you in. The
 *  one-tap WhatsApp method below is always there as the other way. */
export async function renderLogin() {
  stopPolling();
  if (otpCleanup) otpCleanup();
  chrome(false);
  setHeader("Agyary");
  let offered = false;
  try { offered = (await authOptions()).otp === true; } catch (e) { /* the other way still works */ }
  return offered ? renderPhoneStep() : renderWaChoice();
}

const LAST_PHONE_KEY = "mobed_last_phone";
function rememberedPhone() {
  try { return localStorage.getItem(LAST_PHONE_KEY) || ""; } catch (e) { return ""; }
}
function rememberPhone(phone) {
  try { localStorage.setItem(LAST_PHONE_KEY, phone); } catch (e) { /* a convenience only */ }
}

/** Exactly one six digit code in whatever was pasted, or null. "482 913", a
 *  whole WhatsApp message and a bare "482913" all work; a message with two
 *  candidate numbers in it does not, because guessing which is the code is how
 *  the wrong one gets sent. */
export function extractCode(text) {
  const squeezed = String(text || "").replace(/(\d)[\s-]+(?=\d)/g, "$1");
  const found = squeezed.replace(/\D+/g, " ").trim().match(/\b\d{6}\b/g) || [];
  return found.length === 1 ? found[0] : null;
}

function renderPhoneStep(prefill) {
  mainEl.innerHTML = `
    <div class="card">
      <h2>Sign in</h2>
      <p class="meta">Enter your WhatsApp number and we'll send you a code there.</p>
      <label>WhatsApp number</label>
      ${phoneField("lgPhone", prefill || rememberedPhone())}
      <div style="margin-top:14px"><button id="lgSend">Send code</button></div>
      <p class="meta" style="margin-top:18px">
        Prefer not to type your number?
        <a href="#" id="lgOther">Sign in by sending us a message instead</a>.
        <a href="/privacy" target="_blank" rel="noopener">What we store</a>
      </p>
    </div>`;
  document.getElementById("lgOther").onclick = (e) => { e.preventDefault(); renderWaChoice(true); };

  const send = async () => {
    const phone = readPhone("lgPhone");
    if (!phone) return showError("Please enter a valid phone number.");
    const btn = document.getElementById("lgSend");
    btn.disabled = true;
    btn.textContent = "Sending...";
    try {
      const info = await otpRequest(phone);
      rememberPhone(phone);
      renderCodeStep(phone, info);
    } catch (e) {
      btn.disabled = false;
      btn.textContent = "Send code";
      showError(e.message);
    }
  };
  document.getElementById("lgSend").onclick = send;
  document.getElementById("lgPhone").onkeydown = (e) => { if (e.key === "Enter") send(); };
}

function renderCodeStep(phone, info) {
  mainEl.innerHTML = `
    <div class="card">
      <h2>Enter the code</h2>
      <p class="meta">We sent a 6-digit code to <b>${esc(phone)}</b> on WhatsApp.
        Tap <b>Copy code</b> in that message, then come back here.</p>
      <input type="text" id="lgCode" class="otp-input" inputmode="numeric" autocomplete="one-time-code"
        maxlength="7" placeholder="000000" aria-label="Six digit code">
      ${navigator.clipboard && navigator.clipboard.readText
        ? `<div style="margin-top:10px"><button class="secondary small" id="lgPaste">Paste code</button></div>` : ""}
      <p class="meta" id="lgStatus" style="margin-top:12px"></p>
      <div class="row tight" style="margin-top:6px">
        <button class="ghost small" id="lgResend" disabled>Resend code</button>
        <button class="ghost small" id="lgChange">Change number</button>
      </div>
    </div>`;

  const codeEl = document.getElementById("lgCode");
  const statusEl = document.getElementById("lgStatus");
  const abort = new AbortController();
  let busy = false;
  let timer = null;
  otpCleanup = () => { abort.abort(); clearInterval(timer); otpCleanup = null; };

  const say = (msg) => { statusEl.textContent = msg; };

  const submit = async (code) => {
    if (busy) return;
    busy = true;
    say("Checking...");
    try {
      const res = await otpVerify(phone, code);
      otpCleanup();
      if (res.status === "needs_name") return renderWaNameStep();
      await finishSignIn(res);
    } catch (e) {
      busy = false;
      codeEl.value = "";
      say(e.message);
      codeEl.focus();
    }
  };

  // Six digits is the whole code: submit the moment it is complete, however it
  // got there - typed, pasted, or read off the clipboard.
  const fill = (raw) => {
    const digits = String(raw).replace(/\D+/g, "").slice(0, 6);
    codeEl.value = digits;
    if (digits.length === 6) submit(digits);
  };
  codeEl.oninput = () => fill(codeEl.value);
  codeEl.focus();

  // The clipboard. A web page cannot read WhatsApp, but "Copy code" puts the
  // code on the clipboard, so asking for it back is as close to automatic as a
  // browser allows. It is only done silently once the browser has already been
  // allowed (otherwise reading would pop a permission prompt every return);
  // the Paste button is the way to grant that, and the way on browsers with
  // no such permission.
  const readClipboard = async () => {
    try {
      const code = extractCode(await navigator.clipboard.readText());
      if (code) fill(code);
      else say("There's no code on your clipboard yet. Tap Copy code in the WhatsApp message.");
    } catch (e) {
      say("Couldn't read your clipboard - type the code instead.");
    }
  };
  const pasteBtn = document.getElementById("lgPaste");
  if (pasteBtn) pasteBtn.onclick = readClipboard;

  const quietRead = async () => {
    if (busy || codeEl.value || document.hidden || !document.hasFocus()) return;
    try {
      const perm = await navigator.permissions.query({ name: "clipboard-read" });
      if (perm.state !== "granted") return;
      const code = extractCode(await navigator.clipboard.readText());
      if (code) fill(code);
    } catch (e) { /* no permissions API here; the Paste button covers it */ }
  };
  document.addEventListener("visibilitychange", quietRead, { signal: abort.signal });
  window.addEventListener("focus", quietRead, { signal: abort.signal });

  // The code expires in minutes and can only be asked for every so often.
  let wait = info.resend_after || 30;
  const resendBtn = document.getElementById("lgResend");
  const tick = () => {
    if (wait > 0) { resendBtn.textContent = `Resend in ${wait}s`; resendBtn.disabled = true; wait -= 1; }
    else { resendBtn.textContent = "Resend code"; resendBtn.disabled = false; clearInterval(timer); }
  };
  timer = setInterval(tick, 1000);
  tick();
  resendBtn.onclick = async () => {
    resendBtn.disabled = true;
    try {
      const again = await otpRequest(phone);
      otpCleanup();
      renderCodeStep(phone, again);
    } catch (e) {
      say(e.message);
      wait = 0; tick();
    }
  };
  document.getElementById("lgChange").onclick = () => { otpCleanup(); renderPhoneStep(phone); };

  // Only on a laptop with no way to send: the server hands the code back so
  // the whole flow can be tried. A real server never does.
  if (info.debug_code) {
    say(`Dev mode - the code is ${info.debug_code}`);
    fill(info.debug_code);
  }
}

/** The one-tap method: open WhatsApp with a code ready, send it, and the page
 *  signs you in by itself. `fromCodes` adds a way back to typing a number. */
function renderWaChoice(fromCodes = false) {
  mainEl.innerHTML = `
    <div class="card">
      <h2>Sign in</h2>
      <p class="meta">
        Tap below to open WhatsApp with a one-time code ready to send.
        Send it and you're in - there's nothing to type.
      </p>
      <div style="margin-top:14px"><button id="waStart">Sign in with WhatsApp</button></div>
      <p class="meta" style="margin-top:18px">
        We learn your number from the message you send, and never send you one.
        <a href="/privacy" target="_blank" rel="noopener">What we store</a>
      </p>
      ${fromCodes ? `<p class="meta"><a href="#" id="lgBack">Sign in with my number instead</a></p>` : ""}
    </div>`;

  document.getElementById("waStart").onclick = startWaLogin;
  if (fromCodes) document.getElementById("lgBack").onclick = (e) => { e.preventDefault(); renderPhoneStep(); };
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
        This is the name that will appear on your slips.
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
  navigate("#/onboarding", { replace: true });
  return false;
}

export async function reloadUser() {
  state.user = await getMe();
}
