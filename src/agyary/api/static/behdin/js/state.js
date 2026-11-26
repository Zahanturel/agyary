"use strict";

// One mutable app-wide object, as in the mobed app: every screen redraws itself on navigation, so the
// only job of shared state is to survive between renders. The access token lives here and nowhere else.
export const state = {
  accessToken: null,
  user: null,
  // True when we booted from the remembered session because the network was down: signed in, but
  // nothing server-backed will answer yet.
  offline: false,
  // The calendar's view (month or day, and where), kept in the address by the shared calendar module.
  calendar: { mode: "month", focus: null, parsiMonth: null, selectedDay: null },
  // What the shared calendar keeps in its state object: the months it has read, and the Go-to lists.
  parsiMonthCache: {},
  calendarOptions: null,
  // A day chosen in the calendar for a new event to start on.
  draftDate: null,
  // The Parsi calendar the person reads in ("shenshai" until Home has asked).
  system: "shenshai",
  // The new request so far (js/screens/request.js); null when none is being made.
  request: null,
};

// The refresh cookie is httpOnly, so the page cannot tell "my session is gone" from "I have no
// signal". This remembers who we last were (never a token) so an offline launch shows the app.
const SESSION_KEY = "behdin.session.v1";
export const LAST_PHONE_KEY = "behdin_last_phone";

export function saveSession() {
  if (!state.user) return;
  try { localStorage.setItem(SESSION_KEY, JSON.stringify({ user: state.user })); } catch (e) { /* not worth failing over */ }
}

/** False when there is nothing remembered, which means this really is a first sign-in. */
export function restoreSession() {
  let raw = null;
  try { raw = localStorage.getItem(SESSION_KEY); } catch (e) { return false; }
  if (!raw) return false;
  try {
    const s = JSON.parse(raw);
    if (!s || !s.user) return false;
    state.user = s.user;
    return true;
  } catch (e) { return false; }
}

/** Only when the SERVER rejected the session: a network failure must never reach here. */
export function clearSession() {
  try { localStorage.removeItem(SESSION_KEY); } catch (e) { /* nothing to clear */ }
}

export function forgetLastPhone() {
  try { localStorage.removeItem(LAST_PHONE_KEY); } catch (e) { /* nothing to forget */ }
}
