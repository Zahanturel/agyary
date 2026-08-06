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

/** The Parsi system shown as the secondary label, from the user's own
 *  preferences. Falls back to the agyari's stamping system, then shenshai. */
export function secondarySystem() {
  if (state.preferences && state.preferences.default_secondary_system)
    return state.preferences.default_secondary_system;
  const agyary = currentAgyary();
  return (agyary && agyary.calendar_system) || "shenshai";
}

/** Which systems the user asked to be able to see, minus Gregorian, which
 *  is always the primary label and never one of the alternates. */
export function visibleParsiSystems() {
  const visible = (state.preferences && state.preferences.visible_calendar_systems) || ["gregorian", "shenshai"];
  return visible.filter(s => s !== "gregorian");
}
