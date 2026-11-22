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
  constructor(status, detail, field = null) {
    super(detail);
    this.status = status;
    this.detail = detail;
    // Which field of a form the server says is wrong (X-Field), or null.
    this.field = field;
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

  // This mobed is waiting for approval, or an admin has switched them off
  // (DECISIONS D9). main.js puts the waiting screen up in place of whatever
  // asked; the error still goes to the caller, which says nothing more.
  const access = res.status === 403 ? res.headers.get("X-Mobed-Access") : null;
  if (access) globalThis.dispatchEvent?.(new CustomEvent("mobed:access", { detail: access }));
  // A Doongerwadi manager's account asked for part of the mobed app (D10): main.js
  // takes them to their own screen. The error still goes to the caller.
  const kind = res.status === 403 ? res.headers.get("X-Account-Kind") : null;
  if (kind) globalThis.dispatchEvent?.(new CustomEvent("mobed:account-kind", { detail: kind }));

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
    throw new ApiError(res.status, detail, res.headers.get("X-Field"));
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
/** Admin only: every mobed, those waiting for approval first. */
export const adminMobeds = () => get("/admin/mobeds");
/** Admin only: approve or turn on ("on"), or turn off ("off"), one mobed. */
export const adminSetMobedAccess = (userId, access) => post(`/admin/mobeds/${userId}/access`, { access });
// decision: "confirm" (make panthaky), "decline" (not the panthaky) or "remove" (a mobed again).
export const adminDecidePanthaky = (userId, agyaryId, decision) =>
  post(`/admin/mobeds/${userId}/panthaky`, { agyary_id: agyaryId, decision });
/** Admin only (D10, 22 Nov 2026): at a fire temple with no panthaky in the app, whether one who
 *  joined gets its prayer requests. action: "confirm", "off" (Not one of ours) or "on" (Put back). */
export const adminDecideRequests = (userId, agyaryId, action) =>
  post(`/admin/mobeds/${userId}/requests`, { agyary_id: agyaryId, action });
/** Admin only: the Doongerwadis, prayer halls and aramgahs (D10). Turned off, never deleted. */
export const adminFuneralPlaces = () => get("/admin/funeral-places");
export const adminFuneralPlace = (id) => get(`/admin/funeral-places/${id}`);
export const adminCreateFuneralPlace = (body) => post("/admin/funeral-places", body);
export const adminUpdateFuneralPlace = (id, body) => put(`/admin/funeral-places/${id}`, body);
export const adminSetFuneralPlaceActive = (id, active) => post(`/admin/funeral-places/${id}/active`, { active });
/** Admin only: phone notifications - whether the server can send, its key, this admin's devices. */
export const adminPush = () => get("/admin/push");
export const adminPushSubscribe = (sub) => post("/admin/push/subscribe", sub);
export const adminPushUnsubscribe = (endpoint) => post("/admin/push/unsubscribe", { endpoint });
export const adminPushTest = () => post("/admin/push/test", {});
// Notifications on this phone, for every account that is on (Settings).
export const myPush = () => get("/me/push");
export const myPushSubscribe = (sub) => post("/me/push/subscribe", sub);
export const myPushUnsubscribe = (endpoint) => post("/me/push/unsubscribe", { endpoint });
export const myPushTest = () => post("/me/push/test", {});
export const authOptions = () => get("/auth/options");
export const otpRequest = (phone, turnstileToken = null) =>
  post("/auth/otp/request", { phone, turnstile_token: turnstileToken });
export const otpVerify = (phone, code) => post("/auth/otp/verify", { phone, code });
export const waLoginStart = () => post("/auth/wa/start", {});
export const waLoginPoll = () => get("/auth/wa/poll");
export const waLoginComplete = (name) => post("/auth/wa/complete", { name });
/** The number we sent back to the phone the code came from (AU-1). */
export const waLoginConfirm = (number) => post("/auth/wa/confirm", { number });
/** Sign out; `endpoint` is this phone's push subscription, if any, which the server forgets too. */
export const logout = (endpoint = null) => post("/auth/logout", endpoint ? { endpoint } : {});
/** End every other signed-in device of this mobed, and their notifications; this one stays,
 *  with its own (`keepEndpoint`, this phone's push subscription, if any). */
export const signOutOtherDevices = (keepEndpoint = null) =>
  post("/auth/sessions/sign-out-others", { keep_endpoint: keepEndpoint || null });
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

// A brand-new account that works at a Doongerwadi or prayer hall (D10): the places
// the admin has added, and "I work here" (the account becomes a manager's and waits).
export const searchFuneralPlaces = (q) => get(`/funeral-places?q=${encodeURIComponent(q || "")}`);
export const joinFuneralPlace = (id) => post(`/funeral-places/${id}/join`, {});
// An admin acting for one funeral place ("Act for this place", #/admin/act/<id>/...)
// calls the manager's routes for that place: main.js sets state.actFor from the
// address, and the server checks it is an admin and a place in use.
function asManager(path) {
  return state.actFor ? `${path}${path.includes("?") ? "&" : "?"}act_for=${state.actFor}` : path;
}
/** A manager's own place(s), for their home screen (the admin's: the one they act for). */
export const managerPlace = () => get(asManager("/manager/place"));
/** Recording a death and sending it to a fire temple (D10, Step 4). */
export const managerDeathDay = (body) => post(asManager("/manager/death-day"), body);
export const managerRecords = (before) => get(asManager("/manager/records" + (before ? `?before=${before}` : "")));
export const managerRecord = (id) => get(asManager(`/manager/records/${id}`));
export const managerCreateRecord = (body) => post(asManager("/manager/records"), body);
export const managerUpdateRecord = (id, body) => put(asManager(`/manager/records/${id}`), body);
export const managerSuggested = (id) => get(asManager(`/manager/records/${id}/agyaries`));
export const managerSearchAgyaries = (q, placeId) =>
  get(asManager(`/manager/agyaries/search?q=${encodeURIComponent(q || "")}${placeId ? `&place_id=${placeId}` : ""}`));
// The one tick says both: the family agreed to share their name and number, and to
// get WhatsApp messages about the prayers from Mobed Diary (D10, Step 5b).
export const managerSend = (id, agyaryId, familyAgreed) =>
  post(asManager(`/manager/records/${id}/requests`),
    { agyary_id: agyaryId, family_agreed: familyAgreed, family_whatsapp_agreed: familyAgreed });
export const managerWithdraw = (requestId) => post(asManager(`/manager/requests/${requestId}/withdraw`), {});
/** The place's book of behdins (D10, 19 Nov 2026): the families it deals with. */
export const managerBook = (q) => get(asManager(`/manager/behdins?q=${encodeURIComponent(q || "")}`));
export const managerAddToBook = (body) => post(asManager("/manager/behdins"), body);
export const managerChangeInBook = (id, body) => put(asManager(`/manager/behdins/${id}`), body);
export const managerRemoveFromBook = (id) => del(asManager(`/manager/behdins/${id}`));
/** The fire temple's side (D10, Step 5): the requests this mobed was asked. */
export const myRequestCount = () => get("/requests/count");
export const myRequests = () => get("/requests");
export const myRequest = (id) => get(`/requests/${id}`);
/** An app mobed's own answer to a request that reached them (R3.1): "yes" (I can pray) or "no" (Not this time). */
export const answerRequest = (id, answer) => post(`/requests/${id}/answer`, { answer });
/** A confirmed panthaky's "We can't take this" (for anyone else the server takes it as Not this time). */
export const declineRequest = (id, reason) => post(`/requests/${id}/decline`, { reason: reason || null });
/** The "Who will pray" board on a request (R3.1): for the fire temple's confirmed panthakys
 *  the request reached, and the admin. Each action answers with the board as it is now and
 *  `done`, what happened in words. */
export const requestBoard = (rid) => get(`/requests/${rid}/board`);
export const boardAskEveryone = (rid) => post(`/requests/${rid}/ask-everyone`, {});
export const boardPrayMyself = (rid) => post(`/requests/${rid}/self`, {});
// key: "u<user id>" or "c<contact id>" from the board's mobeds; result: "going", "not_going" or "no_answer".
export const boardCallResult = (rid, key, result) => post(`/requests/${rid}/call-result`, { key, result });
/** "Confirm with who's going" (R3.1 step 5): all set with fewer than wanted. */
export const boardConfirmShort = (rid) => post(`/requests/${rid}/confirm-short`, {});
/** The board's "Can't go" on a place (R3.1 step 5b). key: the place's "u<user id>" or "c<contact id>". */
export const boardCantGo = (rid, key) => post(`/requests/${rid}/cant-go`, { key });
/** "I can't go any more" (R3.1 step 5b): someone going can no longer go; their place opens again. */
export const backOutRequest = (id) => post(`/requests/${id}/back-out`, {});
/** A fire temple's own list of mobeds, and the panthaky's call-out on WhatsApp (D10, Step 5c). */
export const ourMobeds = (aid) => get(`/agyaries/${aid}/our-mobeds`);
export const addOurMobed = (aid, name, phone, agreed) => post(`/agyaries/${aid}/our-mobeds`, { name, phone, agreed });
export const removeOurMobed = (aid, id) => del(`/agyaries/${aid}/our-mobeds/${id}`);
/** Joining needs the panthaky's confirmation (D10, 22 Nov 2026): "confirm" one who joined,
 *  "off" (Not one of ours / Take off the list) or "on" (Put back). The Mobeds page comes back. */
export const memberRequests = (aid, userId, what) => post(`/agyaries/${aid}/members/${userId}/${what}`, {});
/** How a prayer request reaches the fire temple (R3.1): mode "everyone" or "panthaky_first",
 *  and the safety net's minutes (15, 30, 60; null is Never). Its confirmed panthakys and the admin. */
export const getRequestSettings = (aid) => get(`/agyaries/${aid}/request-settings`);
export const putRequestSettings = (aid, mode, escalateMinutes) =>
  put(`/agyaries/${aid}/request-settings`, { mode, escalate_minutes: escalateMinutes });

export const searchAgyaries = (q) => get(`/agyaries/search?q=${encodeURIComponent(q)}`);
// claimedRole: "mobed" or "panthaky", what they said they are there (D10).
export const joinAgyary = (id, claimedRole) => post(`/agyaries/${id}/join`, { claimed_role: claimedRole });
export const activateAgyary = (id, body) => post(`/agyaries/${id}/activate`, body);
// From Settings: "I am the panthaky here" (a claim the admin confirms), and taking it back.
export const claimPanthaky = (id) => post(`/agyaries/${id}/panthaky-claim`, {});
export const withdrawPanthakyClaim = (id) => del(`/agyaries/${id}/panthaky-claim`);
export const createAgyary = (body) => post("/agyaries", body);
/** Where a fire temple is (D10): its own mobeds and the admin read it and move its pin. */
export const getAgyaryLocation = (aid) => get(`/agyaries/${aid}/location`);
export const putAgyaryLocation = (aid, latitude, longitude) => put(`/agyaries/${aid}/location`, { latitude, longitude });
/** An address or area on OpenStreetMap, asked by our server. */
export const searchPlaces = (q) => get(`/places/search?q=${encodeURIComponent(q)}`);
/** Whether "Find on Google" is set up on the server (never the key itself). */
export const placesOptions = () => get("/places/options");
/** A fire temple by name on Google, asked by our server with its own key. */
export const googlePlaces = (q) => get(`/places/google?q=${encodeURIComponent(q)}`);


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
// Editing after it is saved: one date taken out, or the whole memorial re-worked.
export const removeObservance = (aid, mid, oid) =>
  del(`/agyaries/${aid}/memorials/${mid}/observances/${oid}`);
export const memorialEditForm = (aid, mid) => get(`/agyaries/${aid}/memorials/${mid}/edit`);
export const previewMemorialEdit = (aid, mid, body) =>
  post(`/agyaries/${aid}/memorials/${mid}/edit/preview`, body);
export const saveMemorialEdit = (aid, mid, body) => put(`/agyaries/${aid}/memorials/${mid}`, body);

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
export const deleteBooking = (aid, id, future) => del(`/agyaries/${aid}/bookings/${id}${future ? "?future=true" : ""}`);

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
