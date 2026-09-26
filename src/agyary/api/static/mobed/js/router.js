"use strict";

import { drainFlash, showBack } from "./ui.js";

// A hash router, kept deliberately small: pattern -> handler, with :params.
// Hash rather than a real path because the PWA is served from a single
// backend route (/mobed) and a path would 404 on refresh or on a shared link.
//
// History is driven explicitly (pushState/replaceState) rather than by
// assigning location.hash, for one reason: Back has to be something the app
// can reason about. Each entry we create carries its depth, so a screen can
// ask "is there an app screen behind me?" - and if there isn't (a deep link,
// a reload onto a form), Back goes to a sensible parent instead of silently
// doing nothing or leaving the app. See back() and returnTo().

const routes = [];
let notFound = null;
let guard = null;
let current = null;
let token = 0;
// The hash at each history depth we created this session, so returnTo() can
// tell whether the entry behind us is the one it wants. Lost on reload, which
// only costs it that optimisation.
const trail = [];

/**
 * `pattern` looks like "#/behdins/:id".
 *
 * opts.parent: where Back goes when there is nothing behind us - a hash, or
 * a function of the route params. A route WITH a parent shows the header
 * Back control; the roots (calendar, login, onboarding) have none.
 *
 * opts.stepBack: the parent is the PREVIOUS STEP of a flow, not merely an
 * earlier screen - Back swaps to it in place instead of walking history.
 * The review step uses this: Back returns to the form it came from.
 */
export function route(pattern, handler, opts = {}) {
  const names = [];
  const regex = new RegExp(
    "^" + pattern.replace(/:[A-Za-z_]+/g, (m) => { names.push(m.slice(1)); return "([^/]+)"; }) + "$"
  );
  routes.push({
    pattern, regex, names, handler,
    manage: !!opts.manage, open: !!opts.open, parent: opts.parent || null,
    stepBack: !!opts.stepBack,
  });
}

export function setNotFound(handler) { notFound = handler; }

// Called after every screen has rendered - used to apply a pending app update
// at a moment when nothing is half-finished. See update.js.
let afterNav = null;
export function onNavigated(fn) { afterNav = fn; }

/**
 * Called before every navigation with the matched route. Return a hash
 * string to redirect, or nothing to allow. This is where auth and the
 * management-role check live - route-level, not just hidden nav items.
 */
export function setGuard(fn) { guard = fn; }

export function currentRoute() { return current; }

function depth() {
  return (history.state && history.state.depth) || 0;
}

/**
 * Go to `hash`. Pushes a history entry, or with {replace: true} swaps the
 * current one - use replace for anything the user should not be able to Back
 * into: a redirect, a finished form, a sign-in.
 */
export function navigate(hash, { replace = false } = {}) {
  if (location.hash === hash) return resolve();
  const d = replace ? depth() : depth() + 1;
  history[replace ? "replaceState" : "pushState"]({ depth: d }, "", hash);
  trail.length = d;
  trail[d] = hash;
  return resolve();
}

/**
 * Back, as a screen should mean it: the previous app screen if there is one,
 * otherwise `fallback`. Never a no-op and never out of the app.
 */
export function back(fallback) {
  if (depth() > 0) history.back();
  else navigate(fallback, { replace: true });
}

/**
 * Finish a screen that was opened from `hash` (an edit form saved back to the
 * slip it came from): pop back to it if it is the entry behind us, so Back
 * afterwards does not step through the form again; otherwise replace.
 */
export function returnTo(hash) {
  if (depth() > 0 && trail[depth() - 1] === hash) history.back();
  else navigate(hash, { replace: true });
}

/**
 * A screen renders asynchronously: it fetches, then writes into <main>. If
 * the user has navigated on by then, that late write lands on top of the new
 * screen while the URL says otherwise - the app showing one thing under
 * another's address. Call this first thing in a handler and check the result
 * after each await, before touching the page.
 */
export function navGuard() {
  const mine = token;
  return () => mine === token;
}

function match(hash) {
  for (const r of routes) {
    const m = hash.match(r.regex);
    if (m) {
      const params = {};
      r.names.forEach((n, i) => { params[n] = decodeURIComponent(m[i + 1]); });
      return { route: r, params };
    }
  }
  return null;
}

export async function resolve() {
  const mine = ++token;
  const hash = location.hash || "#/calendar";
  const found = match(hash);

  if (!found) {
    if (notFound) await notFound(hash);
    return;
  }
  if (guard) {
    const redirect = await guard(found.route, found.params);
    if (mine !== token) return;
    if (redirect) return navigate(redirect, { replace: true });
  }
  current = { hash, ...found };
  const parent = typeof found.route.parent === "function"
    ? found.route.parent(found.params) : found.route.parent;
  showBack(parent
    ? () => (found.route.stepBack ? navigate(parent, { replace: true }) : back(parent))
    : null);
  window.scrollTo(0, 0);
  await found.route.handler(found.params);
  // Any message queued by a guard (or by the screen we just left) is shown
  // here, after the destination has rendered - see ui.flashError.
  if (mine === token) {
    drainFlash();
    if (afterNav) afterNav();
  }
}

export function start() {
  window.addEventListener("popstate", () => {
    trail[depth()] = location.hash;
    resolve();
  });
  if (!location.hash) history.replaceState({ depth: 0 }, "", "#/calendar");
  else if (!history.state) history.replaceState({ depth: 0 }, "");
  trail[depth()] = location.hash;
  return resolve();
}
