"use strict";

/**
 * Sign in, the same two ways as Mobed Diary: by code (when the server offers it) and by sending us
 * a WhatsApp message. A number that has never signed in is asked for its name at the end; it is
 * the name we greet the person by. Signing in here never makes anyone a mobed.
 */

import {
  waLoginStart, waLoginPoll, waLoginComplete, waLoginConfirm, authOptions, otpRequest, otpVerify,
} from "../api.js";
import { state, LAST_PHONE_KEY } from "../state.js";
import { chrome, mainEl, setHeader, showError, toTop } from "/mobed-app/js/ui.js";
import { flagProblems, clearProblems } from "/mobed-app/js/fielderrors.js";
import { addGetApp } from "../install.js";
import { afterSignIn } from "../session.js";
import { APP_NAME } from "../brand.js";
import { esc } from "../util.js";

// Signing in is several screens under one address, so every stage calls toTop() once it is drawn.

/** A code or number that was refused is said on the box it was typed in; anything else floats. */
function sayOnField(input, e) {
  if (e && e.status >= 400 && e.status < 500) {
    flagProblems(mainEl, [{ target: input, message: e.message }]);
  } else {
    showError(e.message);
    input.focus({ preventScroll: true });
  }
}

let pollTimer = null;
let otpCleanup = null;
// The bot check's public site key, when the server has one. Without it the server offers no codes.
let turnstileSiteKey = null;

function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

/** The number in a phone box: country code and the rest, as the person typed them. */
function phoneBox(id, { cc = "91", local = "" } = {}) {
  return `<div class="phone-field">
    <div class="cc-group"><span class="cc-plus">+</span>
      <input type="tel" class="cc-input" id="${id}_cc" aria-label="Country code" inputmode="numeric" maxlength="3" value="${esc(cc)}"></div>
    <input type="tel" id="${id}" inputmode="numeric" maxlength="12" placeholder="98765 43210" value="${esc(local)}"></div>`;
}

function readPhone(id) {
  const cc = document.getElementById(id + "_cc").value.replace(/\D/g, "");
  // A national number never starts with 0 (the trunk prefix people dial locally).
  const digits = document.getElementById(id).value.replace(/\D/g, "").replace(/^0+/, "");
  return cc && digits.length >= 4 ? "+" + cc + digits : null;
}

export async function renderLogin() {
  stopPolling();
  if (otpCleanup) otpCleanup();
  chrome(false);
  setHeader(APP_NAME);
  let offered = false;
  try {
    const options = await authOptions();
    offered = options.otp === true;
    turnstileSiteKey = options.turnstile_site_key || null;
  } catch (e) { /* the other way still works */ }
  return offered ? renderPhoneStep() : renderWaChoice();
}

// The two boxes as last typed, offered again next time and when "Change number" comes back to them.
let lastBox = null;
function rememberedPhone() {
  if (lastBox) return lastBox;
  try {
    const stored = JSON.parse(localStorage.getItem(LAST_PHONE_KEY) || "null");
    return stored && typeof stored.local === "string" ? stored : {};
  } catch (e) { return {}; }
}
function rememberBox(id) {
  lastBox = {
    cc: document.getElementById(id + "_cc").value.replace(/\D/g, "") || "91",
    local: document.getElementById(id).value,
  };
  try { localStorage.setItem(LAST_PHONE_KEY, JSON.stringify(lastBox)); } catch (e) { /* a convenience only */ }
}

/** Exactly one six digit code in whatever was pasted, or null. */
export function extractCode(text) {
  const squeezed = String(text || "").replace(/(\d)[\s-]+(?=\d)/g, "$1");
  const found = squeezed.replace(/\D+/g, " ").trim().match(/\b\d{6}\b/g) || [];
  return found.length === 1 ? found[0] : null;
}

/** Cloudflare's script, loaded once and only when the server has a site key. */
let turnstileLoading = null;
function loadTurnstile() {
  if (window.turnstile) return Promise.resolve(window.turnstile);
  if (!turnstileLoading) {
    turnstileLoading = new Promise((resolve, reject) => {
      const tag = document.createElement("script");
      tag.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
      tag.async = true;
      tag.onload = () => resolve(window.turnstile);
      tag.onerror = () => { turnstileLoading = null; reject(new Error("The check could not load.")); };
      document.head.appendChild(tag);
    });
  }
  return turnstileLoading;
}

function renderPhoneStep() {
  mainEl.innerHTML = `
    <div class="card">
      <h2>Sign in</h2>
      <p class="meta">Enter your WhatsApp number and we'll send you a code there.</p>
      <label for="lgPhone">WhatsApp number</label>
      ${phoneBox("lgPhone", rememberedPhone())}
      ${turnstileSiteKey ? `<div id="lgCheck" style="margin-top:12px"></div>` : ""}
      <div style="margin-top:14px"><button id="lgSend">Send code</button></div>
      <p class="meta" style="margin-top:18px">
        Prefer not to type your number?
        <a href="#" id="lgOther">Sign in by sending us a message instead</a>.
        <a href="/privacy" target="_blank" rel="noopener">What we store</a>
      </p>
    </div>`;
  addGetApp(mainEl);
  toTop();
  document.getElementById("lgOther").onclick = (e) => { e.preventDefault(); renderWaChoice(true); };

  // Each bot-check token is good for one request, so a new one is needed for every Send.
  let checkToken = null;
  if (turnstileSiteKey) {
    loadTurnstile().then((ts) => {
      const box = document.getElementById("lgCheck");
      if (!box) return;
      ts.render(box, {
        sitekey: turnstileSiteKey,
        callback: (token) => { checkToken = token; box.dispatchEvent(new Event("change")); },
        "expired-callback": () => { checkToken = null; },
        "error-callback": () => { checkToken = null; },
      });
    }).catch(() => showError("The check could not load. Sign in by sending us a message instead."));
  }

  const send = async () => {
    const btn = document.getElementById("lgSend");
    if (btn.disabled) return;   // Enter comes here too: one code per tap
    const phone = readPhone("lgPhone");
    if (!phone) {
      return flagProblems(mainEl, [{ target: ".phone-field", message: "Please enter a valid phone number." }]);
    }
    if (turnstileSiteKey && !checkToken) {
      return flagProblems(mainEl, [{ target: "#lgCheck", message: "Please wait for the check to finish, then tap Send code." }]);
    }
    btn.disabled = true;
    btn.textContent = "Sending...";
    try {
      const info = await otpRequest(phone, checkToken);
      rememberBox("lgPhone");
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

function renderCodeStep(phone, info, { redraw = false } = {}) {
  mainEl.innerHTML = `
    <div class="card">
      <h2>Enter the code</h2>
      <p class="meta">We sent a 6-digit code to <b>${esc(phone)}</b> on WhatsApp.
        Tap <b>Copy code</b> in that message, then come back here.</p>
      <input type="text" id="lgCode" class="otp-input" inputmode="numeric" autocomplete="one-time-code"
        maxlength="7" placeholder="000000" aria-label="Six digit code">
      ${navigator.clipboard && navigator.clipboard.readText
        ? `<div style="margin-top:10px"><button class="secondary small" id="lgPaste">Paste code</button></div>` : ""}
      <div style="margin-top:10px"><button class="small hidden" id="lgUse">Sign in with this code</button></div>
      <p class="meta" id="lgStatus" style="margin-top:12px"></p>
      <div class="row tight" style="margin-top:6px">
        <button class="ghost small" id="lgResend" disabled>Resend code</button>
        <button class="ghost small" id="lgChange">Change number</button>
      </div>
      <p class="meta" style="margin-top:14px">No code after a minute? If you use a WhatsApp
        username, WhatsApp may not deliver codes to you.
        <a href="#" id="lgUseWa">Sign in by sending us a message instead</a>.</p>
    </div>`;
  if (!redraw) toTop();
  document.getElementById("lgUseWa").onclick = (e) => { e.preventDefault(); otpCleanup(); renderWaChoice(true); };

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
    clearProblems(mainEl);   // the last code's refusal is not about this one
    say("Checking...");
    try {
      const res = await otpVerify(phone, code);
      otpCleanup();
      if (res.status === "needs_name") return renderNameStep();
      await finishSignIn(res);
    } catch (e) {
      busy = false;
      codeEl.value = "";
      say("");
      sayOnField(codeEl, e);
    }
  };

  // Six digits is the whole code: submit the moment it is complete, however it got there.
  const fill = (raw, { send = true } = {}) => {
    const digits = String(raw).replace(/\D+/g, "").slice(0, 6);
    codeEl.value = digits;
    if (send && digits.length === 6) submit(digits);
  };
  codeEl.oninput = () => fill(codeEl.value);
  codeEl.focus();

  // "Copy code" in WhatsApp puts the code on the clipboard, so asking for it back is as close to
  // automatic as a browser allows.
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
      if (!code) return;
      // Not sent by itself: a lone six digits could be a bank's code.
      fill(code, { send: false });
      say("Found this on your clipboard. If it is the code from WhatsApp, tap Sign in.");
      const use = document.getElementById("lgUse");
      use.classList.remove("hidden");
      use.onclick = () => submit(codeEl.value);
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
    // A fresh bot check is needed for every code, so resending goes back to the number step.
    if (turnstileSiteKey) { otpCleanup(); return renderPhoneStep(); }
    resendBtn.disabled = true;
    try {
      const again = await otpRequest(phone);
      otpCleanup();
      renderCodeStep(phone, again, { redraw: true });
    } catch (e) {
      showError(e.message);
      wait = 0; tick();
    }
  };
  document.getElementById("lgChange").onclick = () => { otpCleanup(); renderPhoneStep(); };

  // Only on a laptop with no way to send: the server hands the code back so the flow can be tried.
  if (info.debug_code) {
    say(`Dev mode - the code is ${info.debug_code}`);
    fill(info.debug_code);
  }
}

/** The one-tap method: open WhatsApp with a code ready, send it, and the page signs you in by itself. */
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
        We learn your number from the message you send.
        <a href="/privacy" target="_blank" rel="noopener">What we store</a>
      </p>
      ${fromCodes ? `<p class="meta"><a href="#" id="lgBack">Sign in with my number instead</a></p>` : ""}
    </div>`;
  addGetApp(mainEl);
  toTop();
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
  toTop();

  // Opening it for them saves a tap; the visible link is the fallback for blocked pop-ups.
  window.open(started.wa_link, "_blank", "noopener");

  document.getElementById("waCancel").onclick = () => { stopPolling(); renderLogin(); };

  pollTimer = setInterval(pollOnce, 2000);
  pollOnce();
}

async function pollOnce() {
  let res;
  try {
    res = await waLoginPoll();
  } catch (e) {
    stopPolling();
    // The attempt is over (refused, expired): stop saying it is waiting.
    const status = document.getElementById("waStatus");
    if (status) status.textContent = "Not signed in. Tap Start again to try once more.";
    const open = document.getElementById("waOpen");
    if (open) open.remove();
    return showError(e.message);
  }
  if (res.status === "pending") return;

  stopPolling();
  if (res.status === "confirm") return renderConfirmStep();
  if (res.status === "needs_name") return renderNameStep();
  await finishSignIn(res);
}

/** The code arrived, and we sent a four digit number back to that phone. Typing it here proves this
 *  screen belongs to whoever has the phone. */
function renderConfirmStep() {
  mainEl.innerHTML = `
    <div class="card">
      <h2>One more step</h2>
      <p class="meta">We have sent a 4-digit number to your WhatsApp. Type it here to finish
        signing in.</p>
      <label for="waConfirm">Number from WhatsApp</label>
      <input type="text" id="waConfirm" class="otp-input" inputmode="numeric" autocomplete="one-time-code"
        maxlength="4" placeholder="0000">
      <div style="margin-top:14px"><button id="waConfirmGo">Continue</button></div>
      <div style="margin-top:12px"><button class="ghost small" id="waConfirmRestart">Start again</button></div>
    </div>`;
  toTop();
  const input = document.getElementById("waConfirm");
  input.focus();
  const go = async () => {
    const btn = document.getElementById("waConfirmGo");
    if (btn.disabled) return;   // Enter comes here too: one try at a time
    const number = input.value.replace(/\D/g, "");
    if (number.length !== 4) {
      return flagProblems(mainEl, [{ target: input, message: "Please type the 4-digit number from WhatsApp." }]);
    }
    btn.disabled = true;
    try {
      const res = await waLoginConfirm(number);
      if (res.status === "needs_name") return renderNameStep();
      await finishSignIn(res);
    } catch (e) {
      btn.disabled = false;
      input.value = "";
      sayOnField(input, e);
    }
  };
  document.getElementById("waConfirmGo").onclick = go;
  input.onkeydown = (e) => { if (e.key === "Enter") go(); };
  document.getElementById("waConfirmRestart").onclick = () => renderLogin();
}

/** Asked of a number that has never signed in: the name we greet them by. */
function renderNameStep() {
  mainEl.innerHTML = `
    <div class="card">
      <h2>What should we call you?</h2>
      <label for="waName">Your name</label>
      <input type="text" id="waName" placeholder="Your name" autocomplete="name">
      <div style="margin-top:14px"><button id="waNameSave">Continue</button></div>
    </div>`;
  toTop();

  const nameEl = document.getElementById("waName");
  nameEl.focus();
  const save = async () => {
    const btn = document.getElementById("waNameSave");
    if (btn.disabled) return;   // Enter comes here too: one try at a time
    const name = nameEl.value.trim();
    if (!name) return flagProblems(mainEl, [{ target: nameEl, message: "Please enter your name." }]);
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

function finishSignIn(res) {
  state.accessToken = res.access_token;
  state.user = res.user;
  afterSignIn();
}
