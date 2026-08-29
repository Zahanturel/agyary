"use strict";

// One mutable app-wide object. Deliberately not a store with subscriptions -
// every screen re-renders itself on navigation, so the only thing shared
// state has to do is survive between renders.
export const state = {
  accessToken: null,
  user: null,
  // True when we booted from the remembered session because the network
  // was down. Signed in, but nothing server-backed will answer yet.
  offline: false,
  currentAgyaryId: null,
  preferences: null,          // GET /me/preferences, loaded once at boot
  calendarOptions: null,      // roj/mah/geh option lists
  formOptionsCache: {},       // per-agyari services + priests
  parsiCache: {},             // "ymd|system" -> label
  parsiMonthCache: {},        // "system-mah-year" -> day list

  // Calendar view state, shared by the calendar screen and My Day.
  calendar: { mode: "day", focus: null, parsiMonth: null, selectedDay: null },

  // In-flight New Event wizard, so a mid-flow navigation doesn't lose it.
  draft: null,

  // Set just before navigating to #/behdins/new from the New Event screen's
  // "+ Add a new behdin" button, so that page knows to hand the finished
  // behdin back to the draft instead of opening the behdin's own record.
  // Read once and cleared by the screen that consumes it.
  behdinReturnTo: null,
  behdinPrefillName: null,
};

export const GEHS = [[1, "Havan"], [2, "Rapithwin"], [3, "Uziran"], [4, "Aiwisruthrem"], [5, "Ushahin"]];
export const GEH_NAME_BY_NUM = Object.fromEntries(GEHS);

export const MACHI_PURPOSE_DISPLAY = {
  patet: "Patet (for the departed)",
  tandarosti: "Tandarosti (for the living)",
};
export const SERVICE_PURPOSE_DISPLAY = {
  gujrela_nu: "Gujrela nu (for the departed)",
  khushali_nu: "Khushali nu (for happiness)",
  hama_anjuman: "Hama Anjuman (for the community)",
};

export const NAME_TITLES = ["ervad", "behdin", "osta", "osti", "khud"];
export const TITLE_DISPLAY = { ervad: "Ervad", behdin: "Behdin", osta: "Osta", osti: "Osti", khud: "Khud" };

// Roles that get the management surface. Mirrors ADMIN_ROLES in
// models/enums.py - the backend is the one that enforces this, but the
// client needs the same list to decide what to route to.
export const ADMIN_ROLES = ["panthaky", "caretaker"];

export function currentAgyary() {
  if (!state.user) return null;
  const list = state.user.agyaries || [];
  return list.find(a => a.id === state.currentAgyaryId) || list[0] || null;
}

export function currentRole() {
  const agyary = currentAgyary();
  return agyary ? agyary.role : null;
}

export function isManager() {
  return ADMIN_ROLES.includes(currentRole());
}

/**
 * THE primary calendar: the Parsi system this mobed reads in.
 *
 * This is the single source for every Parsi date the app renders or
 * accepts - labels, month navigation, Roj/Mah entry, the slip. It is a
 * per-mobed preference and defaults to Shenshai.
 *
 * Explicitly NOT Agyary.calendar_system. That is the fire temple's own
 * system, used server-side to stamp a stable Roj/Mah onto the stored
 * record, and it must not follow a display preference. Reading it here
 * was a real bug: setting Kadmi as primary changed the calendar labels
 * while the New Event date fields silently stayed Shenshai.
 */
export function primarySystem() {
  const chosen = state.preferences && state.preferences.default_secondary_system;
  return chosen || "shenshai";
}

/** Every system the mobed keeps available, minus Gregorian - which is
 *  always the top-line date and never one of the Parsi alternates. The
 *  primary is listed first. */
export function visibleParsiSystems() {
  const visible = (state.preferences && state.preferences.visible_calendar_systems) || ["gregorian", "shenshai"];
  const parsi = visible.filter(s => s !== "gregorian");
  const primary = primarySystem();
  // The primary always appears, even if it somehow fell out of the
  // visible list, and it always leads.
  return [primary, ...parsi.filter(s => s !== primary)];
}

// --- Remembered session -----------------------------------------------------
// The refresh cookie is httpOnly, so the client cannot read it and cannot
// tell "my session is gone" from "I have no signal". That distinction is the
// whole point of this cache: it lets a boot with no network render the app
// the mobed was already signed in to, instead of throwing them back to the
// sign-in screen. It holds no token - only who we last knew we were, which
// is worthless without the cookie the browser still has.
const SESSION_KEY = "mobed.session.v1";

export function saveSession() {
  if (!state.user) return;
  try {
    localStorage.setItem(SESSION_KEY, JSON.stringify({
      user: state.user,
      currentAgyaryId: state.currentAgyaryId,
      preferences: state.preferences,
      calendarOptions: state.calendarOptions,
    }));
  } catch (e) { /* private mode, or the quota is full - not worth failing over */ }
}

/** Repopulates state from the last known-good session. Returns false if
 *  there isn't one, which means this really is a first sign-in. */
export function restoreSession() {
  let raw = null;
  try { raw = localStorage.getItem(SESSION_KEY); } catch (e) { return false; }
  if (!raw) return false;
  try {
    const s = JSON.parse(raw);
    if (!s || !s.user) return false;
    state.user = s.user;
    state.currentAgyaryId = s.currentAgyaryId;
    state.preferences = s.preferences;
    state.calendarOptions = s.calendarOptions;
    return true;
  } catch (e) { return false; }
}

/** Only ever call this when the SERVER rejected the session. A network
 *  failure must not reach here - that is exactly the bug this file exists
 *  to prevent. */
export function clearSession() {
  try { localStorage.removeItem(SESSION_KEY); } catch (e) { /* nothing to clear */ }
}
