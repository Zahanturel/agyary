"use strict";

/**
 * Getting a deployed update onto a phone that already has the app open.
 *
 * The app is a set of modules loaded once when the page opens. A new version
 * reaches the service worker in the background, but the page that is already
 * running keeps executing the OLD modules until it is reloaded - and a
 * mobed's phone can leave the app open for days. Fixes shipped, and nothing
 * changed on their screen. So:
 *
 *  - when a newer worker takes over, reload to pick up the new modules;
 *  - and ask for a newer worker whenever the app comes back to the front,
 *    because a page that never navigates never checks by itself.
 *
 * A reload throws away anything in memory, so it waits while a form is
 * mid-way (`busy`) and happens on the next screen change instead.
 */

export function watchForUpdates({ busy }) {
  if (!("serviceWorker" in navigator)) return () => {};

  // The very first install also fires controllerchange; there is nothing stale
  // to replace then, so only an already-controlled page reloads.
  const wasControlled = !!navigator.serviceWorker.controller;
  let pending = false;

  const reloadIfIdle = () => {
    if (pending && !busy()) location.reload();
  };

  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (!wasControlled) return;
    pending = true;
    reloadIfIdle();
  });

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible") return;
    navigator.serviceWorker.getRegistration()
      .then((reg) => reg && reg.update())
      .catch(() => { /* offline: try again next time */ });
    reloadIfIdle();
  });

  return reloadIfIdle;   // call after each screen change
}

/** The cached shell's version, for showing on the menu - so "which version is
 *  this phone actually running?" has an answer. */
export async function shellVersion() {
  try {
    const key = (await caches.keys()).find((k) => /-shell-v\d+$/.test(k));
    return key ? key.split("-").pop() : null;
  } catch (e) {
    return null;
  }
}
