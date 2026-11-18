"use strict";

/**
 * Notifications on this phone even when Mobed Diary is closed (web push).
 * For every account that is on: an admin's "a new mobed is waiting" (D9), a
 * mobed's "a Doongerwadi asks for prayers" (D10). Turned on from Settings
 * (push_card.js), and by an admin also on the admin screen.
 *
 * The phone's browser asks the person first, then gives us an address at its
 * push service, which the server keeps (services/web_push.py). The service
 * worker shows what arrives (mobed-sw.js). Each phone is turned on by itself.
 */

import { myPush, myPushSubscribe, myPushUnsubscribe } from "./api.js";
import { detectPlatform, runningAsApp } from "./install.js";

/** Why this browser cannot have notifications, in words for the person, or
 *  null when it can. Pure, so it can be tested without a browser. */
export function pushBlocker({
  hasServiceWorker, hasPushManager, hasNotification, permission, platform, asApp,
}) {
  // An iPhone has web push only for a site added to the Home Screen and opened from there.
  if (platform === "ios" && !asApp) {
    return "On an iPhone, notifications work only in the Home Screen app. In Safari tap Share, then "
      + "Add to Home Screen, open Mobed Diary from the new icon, and turn them on there.";
  }
  if (!hasServiceWorker || !hasPushManager || !hasNotification) {
    return "This browser cannot show notifications. Please open Mobed Diary in Chrome.";
  }
  if (permission === "denied") {
    return "Notifications are blocked for Mobed Diary on this phone. Allow them in the browser's "
      + "settings for this site (or the phone's settings for the app), then come back here.";
  }
  return null;
}

export function blockerHere() {
  const mode = (q) => !!(window.matchMedia && window.matchMedia(q).matches);
  return pushBlocker({
    hasServiceWorker: "serviceWorker" in navigator,
    hasPushManager: "PushManager" in window,
    hasNotification: "Notification" in window,
    permission: "Notification" in window ? Notification.permission : "default",
    platform: detectPlatform(navigator.userAgent, navigator.maxTouchPoints || 0),
    asApp: runningAsApp({
      standalone: navigator.standalone,
      displayMode: ["standalone", "fullscreen", "minimal-ui"].some((m) => mode(`(display-mode: ${m})`)),
      referrer: document.referrer || "",
    }),
  });
}

/** The VAPID public key, base64url, as the bytes subscribe() wants. */
export function keyBytes(b64url) {
  const b64 = (b64url + "=".repeat((4 - (b64url.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/");
  return Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
}

async function registration() {
  // The worker is registered on every load (main.js); wait for it, but not forever.
  return Promise.race([
    navigator.serviceWorker.ready,
    new Promise((_, no) => setTimeout(() => no(new Error(
      "Mobed Diary is still getting ready on this phone. Please try again in a moment.")), 10000)),
  ]);
}

/** This phone's subscription, or null. */
export async function current() {
  if (blockerHere()) return null;
  try {
    return await (await registration()).pushManager.getSubscription();
  } catch (e) {
    return null;
  }
}

/** Ask the person, subscribe this phone and tell the server. Throws an Error
 *  with a message for the person if it cannot be done. */
export async function turnOn() {
  const blocked = blockerHere();
  if (blocked) throw new Error(blocked);
  const status = await myPush();
  if (!status.configured || !status.public_key) {
    throw new Error("Phone notifications are not set up on the server yet.");
  }
  const answer = await Notification.requestPermission();
  if (answer !== "granted") {
    throw new Error(answer === "denied"
      ? blockerHere() || "Notifications were not allowed."
      : "Notifications were not turned on. Tap the button again and choose Allow.");
  }
  const reg = await registration();
  let sub = await reg.pushManager.getSubscription();
  // One made with another key (the server's keys changed) cannot be used.
  if (sub && sub.options && sub.options.applicationServerKey) {
    const had = new Uint8Array(sub.options.applicationServerKey);
    const want = keyBytes(status.public_key);
    if (had.length !== want.length || had.some((b, i) => b !== want[i])) {
      await sub.unsubscribe();
      sub = null;
    }
  }
  if (!sub) {
    try {
      sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(status.public_key) });
    } catch (e) {
      throw new Error("This phone could not sign up for notifications. Please check your signal and try again.");
    }
  }
  const json = sub.toJSON();
  return myPushSubscribe({ endpoint: json.endpoint, keys: json.keys });
}

/** Stop notifications on this phone, here and on the server. */
export async function turnOff() {
  const sub = await current();
  if (!sub) return null;
  const endpoint = sub.endpoint;
  await sub.unsubscribe().catch(() => {});
  return myPushUnsubscribe(endpoint);
}
