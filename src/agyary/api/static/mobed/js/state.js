"use strict";

// One mutable app-wide object. Deliberately not a store with subscriptions -
// every screen re-renders itself on navigation, so the only thing shared
// state has to do is survive between renders.
export const state = {
  accessToken: null,
  user: null,
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
