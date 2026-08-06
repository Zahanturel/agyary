"use strict";

import { drainFlash } from "./ui.js";

// A hash router, kept deliberately small: pattern -> handler, with :params.
// Hash rather than History API because the PWA is served from a single
// backend route (/mobed) and a real path would 404 on refresh or on a
// shared link.

const routes = [];
let notFound = null;
let guard = null;
let current = null;

/** `pattern` looks like "#/behdins/:id". */
export function route(pattern, handler, opts = {}) {
  const names = [];
  const regex = new RegExp(
    "^" + pattern.replace(/:[A-Za-z_]+/g, (m) => { names.push(m.slice(1)); return "([^/]+)"; }) + "$"
  );
  routes.push({ pattern, regex, names, handler, manage: !!opts.manage, open: !!opts.open });
}

export function setNotFound(handler) { notFound = handler; }

/**
 * Called before every navigation with the matched route. Return a hash
 * string to redirect, or nothing to allow. This is where auth and the
 * management-role check live - route-level, not just hidden nav items.
 */
export function setGuard(fn) { guard = fn; }

export function currentRoute() { return current; }

export function navigate(hash, { replace = false } = {}) {
  if (location.hash === hash) return resolve();
  if (replace) location.replace(hash);
  else location.hash = hash;
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
  const hash = location.hash || "#/my-day";
  const found = match(hash);

  if (!found) {
    if (notFound) await notFound(hash);
    return;
  }
  if (guard) {
    const redirect = await guard(found.route, found.params);
    if (redirect) return navigate(redirect, { replace: true });
  }
  current = { hash, ...found };
  window.scrollTo(0, 0);
  await found.route.handler(found.params);
  // Any message queued by a guard (or by the screen we just left) is shown
  // here, after the destination has rendered - see ui.flashError.
  drainFlash();
}

export function start() {
  window.addEventListener("hashchange", () => { resolve(); });
  if (!location.hash) location.replace("#/my-day");
  return resolve();
}
