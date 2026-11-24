"use strict";

// "Get the app" on the sign-in screens. The other app's card offers that app's Android file, which is not
// this app, so this one only does what a web app can. The platform checks are the shared ones.
import { detectPlatform, runningAsApp } from "/mobed-app/js/install.js";
import { APP_NAME } from "./brand.js";
import { esc } from "./util.js";

// The browser's own install offer comes once per page load, often after the card is drawn.
let offer = null;
const listeners = new Set();
if (typeof window !== "undefined" && window.addEventListener) {
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    offer = e;
    listeners.forEach((fn) => fn());
  });
  window.addEventListener("appinstalled", () => {
    offer = null;
    listeners.forEach((fn) => fn());
  });
}

function insideApp() {
  const mode = (q) => !!(window.matchMedia && window.matchMedia(q).matches);
  return runningAsApp({
    standalone: navigator.standalone,
    displayMode: ["standalone", "fullscreen", "minimal-ui", "window-controls-overlay"].some((m) => mode(`(display-mode: ${m})`)),
    referrer: document.referrer || "",
  });
}

/**
 * "Get the app", the card under the sign-in card, in the same look as the other app's. This app has no file
 * to download, so it is the browser's own install, or the steps for an iPhone. Never shown inside the installed app.
 */
export function addGetApp(container) {
  if (!container || insideApp()) return;
  const kind = detectPlatform(navigator.userAgent || "", navigator.maxTouchPoints || 0);
  const card = document.createElement("div");
  card.className = "card get-app";
  card.id = "getApp";
  container.appendChild(card);
  let notInstalled = false;
  const paint = () => {
    if (!card.isConnected) { listeners.delete(paint); return; }
    if (offer) {
      card.innerHTML = `<h2>Get the app</h2>
        <p class="meta">Have ${esc(APP_NAME)} on your phone as an app, with its own icon on your home screen.</p>
        <button class="secondary get-app-btn" id="biInstall">Install</button>`;
      card.querySelector("#biInstall").onclick = async (ev) => {
        ev.currentTarget.disabled = true;   // one question at a time; the answer redraws the card
        const asked = offer;
        offer = null;
        try {
          await asked.prompt();
          const choice = await asked.userChoice;
          notInstalled = !(choice && choice.outcome === "accepted");
        } catch (e) { notInstalled = true; }
        paint();
      };
    } else if (kind === "ios") {
      card.innerHTML = `<h2>Get the app</h2>
        <p class="meta">Tap the Share button in Safari, then <b>Add to Home Screen</b>.</p>`;
    } else {
      card.innerHTML = `<h2>Get the app</h2>
        <p class="meta">${notInstalled ? "Not installed. " : ""}In your browser's menu, tap <b>Install app</b> or <b>Add to Home screen</b>.</p>`;
    }
  };
  listeners.add(paint);
  paint();
}

/** The cached shell's version ("v1"), so "which version is this phone running?" has an answer. */
export async function shellVersion() {
  try {
    const key = (await caches.keys()).find((k) => /^behdin-shell-v\d+$/.test(k));
    return key ? key.split("-").pop() : null;
  } catch (e) {
    return null;
  }
}
