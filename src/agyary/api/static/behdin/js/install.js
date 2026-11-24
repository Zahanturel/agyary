"use strict";

// "Install the app" on the menu. Mobed Diary's own card offers that app's Android file, which is not
// this app, so this one only does what a web app can: the browser's own install, or the steps for an
// iPhone. The platform checks are the shared ones.
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

/** Fills `card` (an element already on the page). Inside the installed app it says so and offers nothing. */
export function paintInstall(card) {
  if (insideApp()) {
    card.innerHTML = `<h2>Install the app</h2><p class="meta">You are using the installed app.</p>`;
    return;
  }
  const kind = detectPlatform(navigator.userAgent || "", navigator.maxTouchPoints || 0);
  let notInstalled = false;
  const paint = () => {
    if (!card.isConnected) { listeners.delete(paint); return; }
    if (offer) {
      card.innerHTML = `<h2>Install the app</h2>
        <p class="meta">Put ${esc(APP_NAME)} on your home screen, with its own icon.</p>
        <button class="secondary" id="biInstall">Install</button>`;
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
      card.innerHTML = `<h2>Install the app</h2>
        <p class="meta">Tap the Share button in Safari, then <b>Add to Home Screen</b>. Then open
          ${esc(APP_NAME)} from your Home Screen and sign in there once more.</p>`;
    } else {
      card.innerHTML = `<h2>Install the app</h2>
        <p class="meta">${notInstalled ? "It was not installed. " : ""}In your browser's menu, choose
          <b>Install app</b> or <b>Add to Home screen</b>.</p>`;
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
