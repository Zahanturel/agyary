"use strict";

import { state } from "./state.js";

const MOBED_BASE = "/api/mobed";
// "Connected but dead" signal: without a limit a save or a launch just hangs (FE-05).
const TIMEOUT_MS = 25000;

/** fetch, given up on after TIMEOUT_MS with an AbortError. */
async function timedFetch(url, opts) {
  const stop = new AbortController();
  const timer = setTimeout(() => stop.abort(), TIMEOUT_MS);
  try {
    return await fetch(url, Object.assign({}, opts, { signal: stop.signal }));
  } finally {
    clearTimeout(timer);
  }
}

/** Thrown for any non-2xx. `.detail` is the server's message where it sent
 *  a plain string one; `.status` lets callers branch (401, 409, 429...). */
export class ApiError extends Error {
  constructor(status, detail) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

/**
 * `path` is relative to /api/mobed. A path starting with "/../" escapes
 * that prefix and is resolved against /api instead (the calendar router
 * lives outside the mobed namespace).
 */
export async function api(path, opts = {}) {
  const base = path.startsWith("/../") ? "/api" : MOBED_BASE;
  const p = path.startsWith("/../") ? path.slice(3) : path;
  const headers = Object.assign({ "Content-Type": "application/json" }, opts.headers || {});
  if (state.accessToken) headers["Authorization"] = "Bearer " + state.accessToken;

  let res;
  try {
    res = await timedFetch(base + p, Object.assign({}, opts, { headers, credentials: "include" }));
  } catch (e) {
    throw new ApiError(0, e && e.name === "AbortError"
      ? "Mobed Diary is taking too long to answer. Please check your signal and try again."
      : "Could not reach Mobed Diary. Please check your internet connection and try again.");
  }

  // One silent refresh attempt per call. The refresh cookie is httpOnly and
  // sliding, so a 60-minute access token expiring mid-session should be
  // invisible rather than a surprise logout.
  if (res.status === 401 && !opts._retried) {
    // Strictly true: REFRESH_OFFLINE is truthy but means "ask again later",
    // and retrying the call on it would just fail the same way.
    const refreshed = await tryRefresh();
    if (refreshed === true) return api(path, Object.assign({}, opts, { _retried: true }));
    // The server has ended this sign-in. main.js takes it from here (FE-09).
    if (refreshed === false && state.user) globalThis.dispatchEvent?.(new Event("mobed:signed-out"));
  }

  if (!res.ok) {
    // Our own handlers answer in plain words; anything else gets a plain
    // sentence rather than "Unprocessable Entity" or "Internal Server Error".
    let detail = res.status === 422 ? "Something in the form doesn't look right. Please check it and try again."
      : res.status === 429 ? "That was a lot of tries in a short time. Please wait a minute and try again."
      : res.status >= 500 ? "Something went wrong on our side. Please try again in a minute."
      : "That didn't work. Please try again.";
    try {
      const body = await res.json();
      // A FastAPI validation 422's `detail` is a list of structured objects,
      // not a string - keep the plain sentence rather than showing
      // "[object Object]" if it isn't the plain-string shape our own
      // handlers return.
      if (typeof body.detail === "string") detail = body.detail;
    } catch (e) { /* non-JSON body; the plain sentence it is */ }
    throw new ApiError(res.status, detail);
  }
  return res.status === 204 ? null : res.json();
}

/** tryRefresh() returned neither a session nor a refusal - there was no
 *  network. The session may well still be perfectly good. */
export const REFRESH_OFFLINE = "offline";

/**
 * Three outcomes, and keeping them apart is the difference between a
 * session that survives a tunnel and one that doesn't:
 *
 *   true            - refreshed, `state.accessToken` is live
 *   false           - the SERVER refused: cookie missing, expired, revoked.
 *                     Always a 401. This is the only outcome that means
 *                     "signed out"; a 403 here can only be Cloudflare's own
 *                     block page, which says nothing about the session.
 *   REFRESH_OFFLINE - no answer about the session: the request never landed,
 *                     or the server (or Cloudflare in front of it) failed -
 *                     a 5xx during a deploy, a 429. Treating that as a
 *                     refusal is what made a blip look like a logout.
 *
 * One refresh at a time. Screens fire several calls at once, and each 401
 * used to start its own refresh with the same cookie: the server rotates the
 * cookie on the first and takes the second for a stolen copy, ending the
 * whole session (FE-01). Callers that arrive while one is running share it.
 */
let refreshing = null;
export function tryRefresh() {
  if (!refreshing) refreshing = doRefresh().finally(() => { refreshing = null; });
  return refreshing;
}

async function doRefresh() {
  let res;
  try {
    res = await timedFetch(MOBED_BASE + "/auth/refresh", { method: "POST", credentials: "include" });
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
export const put = (path, body) => api(path, { method: "PUT", body: JSON.stringify(body || {}) });
export const patch = (path, body) => api(path, { method: "PATCH", body: JSON.stringify(body || {}) });
export const del = (path) => api(path, { method: "DELETE" });

// --- Endpoint wrappers ------------------------------------------------------
// Thin, but they keep URL shapes in one place: several of these gained
// required parameters in the backend pass (machi-board's window, from-parsi's
// optional year) and a screen shouldn't be able to forget one.

// Sign-in: the mobed messages US a code, so we never send anything and
// never ask for their number - the webhook learns it from Meta. start()
// mints the code and sets an httpOnly cookie; poll() matches on that cookie,
// never on the code, which is public by the time it reaches WhatsApp.
export const adminOverview = () => get("/admin/overview");
export const adminSetPaused = (paused, reason) => post("/admin/reminders/pause", { paused, reason: reason || "" });
export const authOptions = () => get("/auth/options");
export const otpRequest = (phone, turnstileToken = null) =>
  post("/auth/otp/request", { phone, turnstile_token: turnstileToken });
export const otpVerify = (phone, code) => post("/auth/otp/verify", { phone, code });
export const waLoginStart = () => post("/auth/wa/start", {});
export const waLoginPoll = () => get("/auth/wa/poll");
export const waLoginComplete = (name) => post("/auth/wa/complete", { name });
/** The number we sent back to the phone the code came from (AU-1). */
export const waLoginConfirm = (number) => post("/auth/wa/confirm", { number });
export const logout = () => post("/auth/logout");
/** End every other signed-in device of this mobed; this one stays. */
export const signOutOtherDevices = () => post("/auth/sessions/sign-out-others", {});
/** Delete this account and everything that is the mobed's. Cannot be undone. */
export const deleteMyAccount = () => post("/auth/account/delete", { confirm: true });
/** Admin only: end every signed-in device of the mobed with this number. */
export const adminSignOutEverywhere = (phone) => post("/admin/sign-out-everywhere", { phone });
export const adminEraseNumber = (phone, confirm) => post("/admin/erase-number", { phone, confirm });
export const getMe = () => get("/auth/me");
export const updateMyName = (name) => patch("/auth/me", { name });

/** The evening-before report on or off, for this mobed. */
export const putDailyReport = (enabled) => put("/me/daily-report", { enabled });
export const getPreferences = () => get("/me/preferences");
export const putPreferences = (prefs) => put("/me/preferences", prefs);

export const searchAgyaries = (q) => get(`/agyaries/search?q=${encodeURIComponent(q)}`);
export const joinAgyary = (id) => post(`/agyaries/${id}/join`);
export const activateAgyary = (id, body) => post(`/agyaries/${id}/activate`, body);
export const createAgyary = (body) => post("/agyaries", body);


/** This mobed's services. With a window it is that window, past days
 *  included; without one it is the upcoming list. The calendar always
 *  passes one - it scrolls to any month, and asking without a window got
 *  back "upcoming", which is why past events looked deleted. */
export const myDay = (from, to) =>
  get(from && to ? `/my-day?from=${from}&to=${to}` : "/my-day");

/** Machis in a bounded window. The mobed app passes `mine=true` to see
 *  only their own; the machi board app omits it to see the full board. */
export const machiBoard = (aid, from, to, { mine = true } = {}) =>
  get(`/agyaries/${aid}/machi-board?from=${from}&to=${to}${mine ? "&mine=true" : ""}`);
/** The mobed's own tick on an event: this behdin has paid, or has not. */
export const setEventPaid = (kind, aid, id, paid) =>
  put(`/agyaries/${aid}/${kind === "machi" ? "machis" : "bookings"}/${id}/paid`, { paid });
export const setObservancePaid = (aid, mid, oid, paid) =>
  put(`/agyaries/${aid}/memorials/${mid}/observances/${oid}/paid`, { paid });
export const setMemorialPaid = (aid, mid, paid) => put(`/agyaries/${aid}/memorials/${mid}/paid`, { paid });
export const bookableGehs = (aid, on) => get(`/agyaries/${aid}/bookable-gehs?on=${on}`);

export const calendarOptions = () => get("/reference/calendar-options");
export const listServices = (aid) => get(`/agyaries/${aid}/services`);
export const createService = (aid, name, offsite_capable) =>
  post(`/agyaries/${aid}/services`, { name, offsite_capable });
export const customerHistory = (id) => get(`/customers/${id}/history`);

/** THIS mobed's own behdins - scoped server-side, and unlike
 *  the old booking-derived customer search it includes people registered
 *  but not yet booked for. */
export const listBehdins = (aid, q) => get(`/agyaries/${aid}/behdins?q=${encodeURIComponent(q || "")}`);
export const createBehdin = (aid, name, phone) => post(`/agyaries/${aid}/behdins`, { name, phone });
export const getBehdin = (aid, cid) => get(`/agyaries/${aid}/behdins/${cid}`);
export const deleteBehdin = (aid, cid, scope = "list") => del(`/agyaries/${aid}/behdins/${cid}?scope=${scope}`);
export const memorialShareInfo = (aid, mid, note) =>
  get(`/agyaries/${aid}/memorials/${mid}/share?note=${encodeURIComponent(note || "")}`);
export const memorialShareSend = (aid, mid) => post(`/agyaries/${aid}/memorials/${mid}/share/send`, {});

/** The schedule PDF as a blob. Not through api(): that always parses JSON. */
export async function memorialSchedulePdf(aid, mid, note) {
  const url = `${MOBED_BASE}/agyaries/${aid}/memorials/${mid}/schedule.pdf?note=${encodeURIComponent(note || "")}`;
  const go = () => fetch(url, { headers: { Authorization: "Bearer " + state.accessToken }, credentials: "include" });
  let res;
  try { res = await go(); } catch (e) { throw new ApiError(0, "Could not reach Mobed Diary. Please check your internet connection."); }
  if (res.status === 401 && await tryRefresh() === true) res = await go();
  if (!res.ok) throw new ApiError(res.status, "The PDF could not be made. Please try again.");
  const match = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") || "");
  return { blob: await res.blob(), filename: match ? match[1] : "Memorial-prayers.pdf" };
}

export const behdinDeleteSummary = (aid, cid) => get(`/agyaries/${aid}/behdins/${cid}/delete-summary`);
export const updateBehdin = (aid, cid, body) => patch(`/agyaries/${aid}/behdins/${cid}`, body);
export const getSavedNames = (aid, cid) => get(`/agyaries/${aid}/behdins/${cid}/saved-names`);
export const putSavedNames = (aid, cid, section, names) =>
  put(`/agyaries/${aid}/behdins/${cid}/saved-names/${section}`, { names });
export const deleteSavedName = (aid, cid, rowId) => del(`/agyaries/${aid}/behdins/${cid}/saved-names/${rowId}`);

// --- Memorials: the observances a family keeps for one departed person ------
export const memorialFeed = (aid, from, to) =>
  get(`/agyaries/${aid}/memorial-feed?from=${from}&to=${to}`);
export const setBehdinReminders = (aid, cid, enabled, confirmRestart = false, consentVersion = null) =>
  put(`/agyaries/${aid}/behdins/${cid}/reminders`,
    { enabled, confirm_restart: confirmRestart, consent_version: consentVersion });
/** The words to read to a family before turning reminders on, and their version. */
export const consentWording = () => get("/reminders/consent");
export const getNotifications = () => get("/notifications");
export const markNotificationsSeen = (ids) => post("/notifications/seen", ids ? { ids } : {});
export const memorialReminders = (aid, days) =>
  get(`/agyaries/${aid}/memorial-reminders?days=${days}`);
/** Record (or take back) that the mobed told the family themselves. */
export const markReminded = (aid, observanceId, reminded) =>
  put(`/agyaries/${aid}/memorial-observances/${observanceId}/reminded`, { reminded });
export const listMemorials = (aid, cid) => get(`/agyaries/${aid}/behdins/${cid}/memorials`);
export const previewMemorial = (aid, cid, body) =>
  post(`/agyaries/${aid}/behdins/${cid}/memorials/preview`, body);
export const previewNewMemorial = (aid, body) =>
  post(`/agyaries/${aid}/memorials/preview`, body);
// Which of the days a family can pick have already passed for this death.
export const memorialDayStatus = (aid, body) =>
  post(`/agyaries/${aid}/memorials/day-status`, body);
export const createMemorial = (aid, cid, body) =>
  post(`/agyaries/${aid}/behdins/${cid}/memorials`, body);
export const getMemorial = (aid, mid) => get(`/agyaries/${aid}/memorials/${mid}`);
export const updateObservance = (aid, mid, oid, body) =>
  patch(`/agyaries/${aid}/memorials/${mid}/observances/${oid}`, body);
export const deleteMemorial = (aid, mid) => del(`/agyaries/${aid}/memorials/${mid}`);

export const addMachi = (aid, body) => post(`/agyaries/${aid}/manual-add/machi`, body);
export const addBooking = (aid, body) => post(`/agyaries/${aid}/manual-add/booking`, body);
export const previewBooking = (aid, body) => post(`/agyaries/${aid}/slip-preview/booking`, body);
export const previewMachi = (aid, body) => post(`/agyaries/${aid}/slip-preview/machi`, body);
export const machiDetail = (aid, id) => get(`/agyaries/${aid}/machis/${id}/detail`);
export const bookingDetail = (aid, id) => get(`/agyaries/${aid}/bookings/${id}/detail`);
export const editMachi = (aid, id, body) => put(`/agyaries/${aid}/machis/${id}`, body);
export const editBooking = (aid, id, body) => put(`/agyaries/${aid}/bookings/${id}`, body);
export const machiSlip = (aid, id) => get(`/agyaries/${aid}/machis/${id}/slip`);
export const bookingSlip = (aid, id) => get(`/agyaries/${aid}/bookings/${id}/slip`);
export const deleteMachi = (aid, id, future) => del(`/agyaries/${aid}/machis/${id}${future ? "?future=true" : ""}`);
export const deleteBooking = (aid, id) => del(`/agyaries/${aid}/bookings/${id}`);

// --- Calendar (outside the /api/mobed prefix) -------------------------------
export const convertDate = (ymd, system) => get(`/../calendar/convert?date=${ymd}&system=${system}`);
export const parsiMonth = (mah, year, system) =>
  get(`/../calendar/parsi-month?mah=${mah}&year=${year}&system=${system}`);

/**
 * Roj/Mah -> Gregorian. `year` is OPTIONAL and should normally be omitted:
 * the server then resolves the nearest occurrence itself.
 *
 * Never compute the Yazdegerdi year in the client. It is NOT
 * `gregorianYear - 630` - Shenshai and Kadmi Navroze falls in mid-August, so
 * that subtraction is wrong for every date between January 1st and Navroze.
 * The previous build did exactly that in two places and could file a machi
 * a whole Parsi year off; the endpoint exists so this can't happen again.
 */
export function fromParsi(roj, mah, system, year) {
  const q = new URLSearchParams({ roj, mah, system });
  if (year != null && year !== "") q.set("year", year);
  return get(`/../calendar/from-parsi?${q.toString()}`);
}
