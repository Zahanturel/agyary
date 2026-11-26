"use strict";

/**
 * Notifications on this phone (web push): asked once after the first sign-in, with a switch in the menu.
 * The phone's browser gives an address at its push service, which the server keeps; the service worker
 * (behdin-sw.js) shows what arrives and opens the request when it is tapped. The choice is remembered on this phone.
 */

import { myPush, myPushSubscribe, myPushUnsubscribe } from "./api.js";
import { state } from "./state.js";
import { APP_NAME } from "./brand.js";
import { openSheet, closeSheet } from "/mobed-app/js/ui.js";
import { keyBytes } from "/mobed-app/js/push.js";
import { detectPlatform, runningAsApp } from "/mobed-app/js/install.js";

const live = () => !!(state.user && (state.accessToken || state.offline));
const ASKED_KEY = "behdin.push.asked";

/** Why this phone cannot have notifications, in a plain line, or null when it can. */
export function blocker() {
  const mode = (q) => !!(window.matchMedia && window.matchMedia(q).matches);
  const asApp = runningAsApp({
    standalone: navigator.standalone,
    displayMode: ["standalone", "fullscreen", "minimal-ui"].some((m) => mode(`(display-mode: ${m})`)),
    referrer: document.referrer || "",
  });
  if (detectPlatform(navigator.userAgent, navigator.maxTouchPoints || 0) === "ios" && !asApp) {
    return `On an iPhone, add ${APP_NAME} to the Home Screen and open it from there.`;
  }
  if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
    return "Notifications are not available in this browser.";
  }
  if (Notification.permission === "denied") return "Notifications are blocked for this site.";
  return null;
}

function registration() {
  return Promise.race([
    navigator.serviceWorker.ready,
    new Promise((_, no) => setTimeout(() => no(new Error("Please try again in a moment.")), 10000)),
  ]);
}

/** This phone's subscription, or null. */
export async function current() {
  if (blocker()) return null;
  try {
    return await (await registration()).pushManager.getSubscription();
  } catch (e) {
    return null;
  }
}

/** Ask the browser, subscribe this phone and tell the server. Throws an Error with a plain line. */
export async function turnOn() {
  const blocked = blocker();
  if (blocked) throw new Error(blocked);
  const status = await myPush();
  if (!status.configured || !status.public_key) throw new Error("Notifications are not set up yet.");
  const answer = await Notification.requestPermission();
  if (answer !== "granted") throw new Error("Notifications were not allowed.");
  const reg = await registration();
  let sub = await reg.pushManager.getSubscription();
  if (sub && sub.options && sub.options.applicationServerKey) {
    const had = new Uint8Array(sub.options.applicationServerKey);
    const want = keyBytes(status.public_key);
    if (had.length !== want.length || had.some((b, i) => b !== want[i])) { await sub.unsubscribe(); sub = null; }
  }
  if (!sub) {
    try {
      sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(status.public_key) });
    } catch (e) {
      throw new Error("Could not turn on notifications. Check your signal and try again.");
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

function asked() {
  try { return localStorage.getItem(ASKED_KEY) !== null; } catch (e) { return true; }
}
export function remember(choice) {
  try { localStorage.setItem(ASKED_KEY, choice); } catch (e) { /* asked again next visit then */ }
}

let showing = false;

/** After the first sign-in, once per phone: "Allow notifications?". Only on Home, never over a form. */
export function offerPush() {
  if (showing || !live() || state.offline || location.hash !== "#/home" || asked()) return;
  if (blocker() || Notification.permission !== "default") return;
  showing = true;
  const { body } = openSheet({
    title: "Allow notifications?",
    html: `<p>You will be told when a fire temple answers.</p>
      <div class="row tight"><button type="button" id="pushYes">Allow</button>
      <button type="button" class="ghost" id="pushNo">Not now</button></div>`,
    onClose: () => { showing = false; },
  });
  body.querySelector("#pushNo").onclick = () => { remember("no"); closeSheet(); };
  body.querySelector("#pushYes").onclick = async (e) => {
    e.currentTarget.disabled = true;
    remember("yes");
    try { await turnOn(); } catch (err) { /* the menu switch says why */ }
    closeSheet();
  };
}

/** At most `ms` for `promise`, then `fallback`: signing out never waits long on the browser. */
const within = (promise, ms, fallback) =>
  Promise.race([promise, new Promise((ok) => setTimeout(() => ok(fallback), ms))]).catch(() => fallback);

/** This phone's subscription for signing out: never waits long, never throws. */
export const thisPhone = (ms = 3000) => within(Promise.resolve().then(() => current()), ms, null);

/** Stop `sub` in this browser once signed out (the server has forgotten it already). */
export async function forget(sub, ms = 3000) {
  if (sub) await within(Promise.resolve().then(() => sub.unsubscribe()), ms, false);
}
