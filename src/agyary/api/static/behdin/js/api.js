"use strict";

// The behdin app's own door to /api/behdin. It follows the mobed app's api.js on purpose (one
// silent refresh at a time, only a 401 means signed out), but keeps its own token and its own
// events, so the two apps never touch each other.

import { state } from "./state.js";
import { APP_NAME } from "./brand.js";

const BASE = "/api/behdin";
// "Connected but dead": without a limit a save or a launch just hangs.
const TIMEOUT_MS = 25000;

async function timedFetch(url, opts) {
  const stop = new AbortController();
  const timer = setTimeout(() => stop.abort(), TIMEOUT_MS);
  try {
    return await fetch(url, Object.assign({}, opts, { signal: stop.signal }));
  } finally {
    clearTimeout(timer);
  }
}

/** Thrown for any non-2xx. `.detail` is the server's plain message; `.status` lets callers branch. */
export class ApiError extends Error {
  constructor(status, detail) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

export async function api(path, opts = {}) {
  const headers = Object.assign({ "Content-Type": "application/json" }, opts.headers || {});
  if (state.accessToken) headers["Authorization"] = "Bearer " + state.accessToken;

  let res;
  try {
    res = await timedFetch(BASE + path, Object.assign({}, opts, { headers, credentials: "include" }));
  } catch (e) {
    throw new ApiError(0, e && e.name === "AbortError"
      ? `${APP_NAME} is taking too long to answer. Please check your signal and try again.`
      : `Could not reach ${APP_NAME}. Please check your internet connection and try again.`);
  }

  // One silent refresh attempt per call: a 60-minute token running out mid-use should be invisible.
  if (res.status === 401 && !opts._retried) {
    // Strictly true: REFRESH_OFFLINE is truthy but means "ask again later".
    const refreshed = await tryRefresh();
    if (refreshed === true) return api(path, Object.assign({}, opts, { _retried: true }));
    // The server has ended this sign-in. main.js takes it from here.
    if (refreshed === false && state.user) globalThis.dispatchEvent?.(new Event("behdin:signed-out"));
  }

  // An admin has switched this account off: main.js puts the one screen that says so in place.
  const access = res.status === 403 ? res.headers.get("X-Mobed-Access") : null;
  if (access) globalThis.dispatchEvent?.(new CustomEvent("behdin:access", { detail: access }));

  if (!res.ok) {
    let detail = res.status === 422 ? "Something doesn't look right. Please check it and try again."
      : res.status === 429 ? "That was a lot of tries in a short time. Please wait a minute and try again."
      : res.status >= 500 ? "Something went wrong on our side. Please try again in a minute."
      : "That didn't work. Please try again.";
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch (e) { /* non-JSON body; the plain sentence it is */ }
    throw new ApiError(res.status, detail);
  }
  return res.status === 204 ? null : res.json();
}

/** tryRefresh() reached no answer about the session at all: there was no network. */
export const REFRESH_OFFLINE = "offline";

/**
 * Three outcomes, kept apart so a blip is never a logout:
 *   true            - refreshed, state.accessToken is live
 *   false           - the SERVER refused (a 401): the only outcome that means "signed out"
 *   REFRESH_OFFLINE - the request never landed, or the server failed (a 5xx, a 429)
 * One refresh at a time: the server rotates the cookie on the first and would take a second
 * with the same cookie for a stolen copy, so callers that arrive while one runs share it.
 */
let refreshing = null;
export function tryRefresh() {
  if (!refreshing) refreshing = doRefresh().finally(() => { refreshing = null; });
  return refreshing;
}

async function doRefresh() {
  let res;
  try {
    res = await timedFetch(BASE + "/auth/refresh", { method: "POST", credentials: "include" });
  } catch (e) {
    return REFRESH_OFFLINE;
  }
  if (res.status === 401) return false;
  if (!res.ok) return REFRESH_OFFLINE;
  try {
    state.accessToken = (await res.json()).access_token;
  } catch (e) {
    return REFRESH_OFFLINE;
  }
  return true;
}

export const get = (path) => api(path);
export const post = (path, body) => api(path, { method: "POST", body: JSON.stringify(body || {}) });
export const patch = (path, body) => api(path, { method: "PATCH", body: JSON.stringify(body || {}) });
export const del = (path, body) => api(path, { method: "DELETE", body: JSON.stringify(body || {}) });

// Signing in: the person messages US a code on WhatsApp, or we send one by WhatsApp and they type it.
export const authOptions = () => get("/auth/options");
export const otpRequest = (phone, turnstileToken = null) =>
  post("/auth/otp/request", { phone, turnstile_token: turnstileToken });
export const otpVerify = (phone, code) => post("/auth/otp/verify", { phone, code });
export const waLoginStart = () => post("/auth/wa/start", {});
export const waLoginPoll = () => get("/auth/wa/poll");
export const waLoginConfirm = (number) => post("/auth/wa/confirm", { number });
export const waLoginComplete = (name) => post("/auth/wa/complete", { name });
export const logout = () => post("/auth/logout", {});

export const getMe = () => get("/me");
export const updateMyName = (name) => patch("/me", { name });
export const deleteMyAccount = () => del("/account", { confirm: true });
export const getToday = () => get("/today");
