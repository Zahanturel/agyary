"use strict";

import { state } from "./state.js";

const MOBED_BASE = "/api/mobed";

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

  const res = await fetch(base + p, Object.assign({}, opts, { headers, credentials: "include" }));

  // One silent refresh attempt per call. The refresh cookie is httpOnly and
  // sliding, so a 60-minute access token expiring mid-session should be
  // invisible rather than a surprise logout.
  if (res.status === 401 && !opts._retried) {
    if (await tryRefresh()) return api(path, Object.assign({}, opts, { _retried: true }));
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      // A FastAPI validation 422's `detail` is a list of structured objects,
      // not a string - fall back to statusText rather than showing
      // "[object Object]" if it isn't the plain-string shape our own
      // handlers return.
      if (typeof body.detail === "string") detail = body.detail;
    } catch (e) { /* non-JSON body; statusText it is */ }
    throw new ApiError(res.status, detail);
  }
  return res.status === 204 ? null : res.json();
}

export async function tryRefresh() {
  try {
    const res = await fetch(MOBED_BASE + "/auth/refresh", { method: "POST", credentials: "include" });
    if (!res.ok) return false;
    state.accessToken = (await res.json()).access_token;
    return true;
  } catch (e) {
    return false;
  }
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

export const requestOtp = (phone) => post("/auth/otp/request", { phone });
export const verifyOtp = (phone, code, name) => post("/auth/otp/verify", { phone, code, name });
export const logout = () => post("/auth/logout");
export const getMe = () => get("/auth/me");
export const updateMyName = (name) => patch("/auth/me", { name });

export const getPreferences = () => get("/me/preferences");
export const putPreferences = (prefs) => put("/me/preferences", prefs);

export const searchAgyaries = (q) => get(`/agyaries/search?q=${encodeURIComponent(q)}`);
export const joinAgyary = (id) => post(`/agyaries/${id}/join`);
export const activateAgyary = (id, body) => post(`/agyaries/${id}/activate`, body);
export const createAgyary = (body) => post("/agyaries", body);


export const myDay = () => get("/my-day");

/** Machis in a bounded window. The mobed app passes `mine=true` to see
 *  only their own; the machi board app omits it to see the full board. */
export const machiBoard = (aid, from, to, { mine = true } = {}) =>
  get(`/agyaries/${aid}/machi-board?from=${from}&to=${to}${mine ? "&mine=true" : ""}`);
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
export const updateBehdin = (aid, cid, body) => patch(`/agyaries/${aid}/behdins/${cid}`, body);
export const getSavedNames = (aid, cid) => get(`/agyaries/${aid}/behdins/${cid}/saved-names`);
export const putSavedNames = (aid, cid, section, names) =>
  put(`/agyaries/${aid}/behdins/${cid}/saved-names/${section}`, { names });
export const deleteSavedName = (aid, cid, rowId) => del(`/agyaries/${aid}/behdins/${cid}/saved-names/${rowId}`);

export const addMachi = (aid, body) => post(`/agyaries/${aid}/manual-add/machi`, body);
export const addBooking = (aid, body) => post(`/agyaries/${aid}/manual-add/booking`, body);
export const machiDetail = (aid, id) => get(`/agyaries/${aid}/machis/${id}/detail`);
export const bookingDetail = (aid, id) => get(`/agyaries/${aid}/bookings/${id}/detail`);
export const editMachi = (aid, id, body) => put(`/agyaries/${aid}/machis/${id}`, body);
export const editBooking = (aid, id, body) => put(`/agyaries/${aid}/bookings/${id}`, body);
export const machiSlip = (aid, id) => get(`/agyaries/${aid}/machis/${id}/slip`);
export const bookingSlip = (aid, id) => get(`/agyaries/${aid}/bookings/${id}/slip`);

// --- Calendar (outside the /api/mobed prefix) -------------------------------
export const convertDate = (ymd, system) => get(`/../calendar/convert?date=${ymd}&system=${system}`);
/** Every day in [start, end] with its Parsi reading, in one call - the
 *  week view needs seven and shouldn't make seven round trips. */
export const calendarRange = (start, end, system) =>
  get(`/../calendar/range?start=${start}&end=${end}&system=${system}`);
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
