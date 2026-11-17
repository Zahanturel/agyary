"use strict";

/**
 * "Get the app", the card under the sign-in card.
 *
 * Android: the app itself (Mobed-Diary.apk, the Trusted Web Activity of this
 * site), downloaded from this site in one tap. It does not come from the Play
 * Store, so the phone asks the mobed to allow it; the steps that open after the
 * tap say what each question means, so none of them looks like something broke.
 *
 * iPhone and iPad: Apple allows no app from outside its App Store, so no file
 * can be downloaded for them. Add to Home Screen is their way: it installs this
 * site as an app, with its own icon, opening full screen.
 *
 * A computer: the browser's own Install, when it offers one; otherwise how to
 * get the app on a phone.
 *
 * Never shown inside the installed app, whichever kind it is. Nothing here
 * touches the page until addGetApp() is called, so the tests can run it in Node.
 */

export const APK_URL = "/download/android";
// The APK is about 1.8 MB; tests/test_android_app.py keeps it that size.
const APK_NOTE = "About 2 MB. It does not come from the Play Store, so your phone will ask you to allow it.";

/** "android", "ios" or "other", from the browser's user agent. */
export function detectPlatform(ua = "", touchPoints = 0) {
  if (/Android/i.test(ua)) return "android";
  if (/iPhone|iPad|iPod/i.test(ua)) return "ios";
  // An iPad asks for desktop sites, so it says it is a Mac. A Mac has no touch screen.
  if (/Macintosh/i.test(ua) && touchPoints > 1) return "ios";
  return "other";
}

/** Inside another Android app's own browser (Instagram, Facebook and the like),
 *  which usually cannot download a file at all. Chrome's own tabs, which
 *  WhatsApp opens links in, are not this: they say they are Chrome. */
export function inWebView(ua = "") {
  return /Android/i.test(ua) && /; wv\)/.test(ua);
}

/** True inside the installed app: the Android app (a standalone window, and it
 *  says so in the referrer), a Home Screen app on an iPhone, or a computer's
 *  installed window. */
export function runningAsApp({ standalone = false, displayMode = false, referrer = "" } = {}) {
  return standalone === true || displayMode === true || String(referrer).startsWith("android-app://");
}

function runningAsAppHere() {
  const mode = (q) => !!(window.matchMedia && window.matchMedia(q).matches);
  return runningAsApp({
    standalone: navigator.standalone,
    displayMode: ["standalone", "fullscreen", "minimal-ui", "window-controls-overlay"]
      .some((m) => mode(`(display-mode: ${m})`)),
    referrer: document.referrer || "",
  });
}

// The browser's own install offer (Chrome, Edge). It comes once per page load,
// often after the card is already drawn, so it is kept here and the card is
// told. Chrome's own "Add to Home screen" bar is held back: on Android it would
// offer a second, different install beside the Android app.
let installOffer = null;
const onOfferChange = new Set();
if (typeof window !== "undefined" && window.addEventListener) {
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    installOffer = e;
    onOfferChange.forEach((fn) => fn());
  });
  window.addEventListener("appinstalled", () => {
    installOffer = null;
    onOfferChange.forEach((fn) => fn());
  });
}

/** Asks the browser to install the site as an app. True if the mobed said yes.
 *  False as well when the browser would not ask at all (it throws then): the
 *  card that called goes on to say what to do instead, where a throw used to
 *  leave its button doing nothing. */
async function useInstallOffer() {
  const offer = installOffer;
  if (!offer) return false;
  installOffer = null; // one use only, whatever the answer
  try {
    await offer.prompt();
    const choice = await offer.userChoice;
    return !!(choice && choice.outcome === "accepted");
  } catch (e) {
    return false;
  }
}

const ICON_DOWNLOAD = `<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
  <path d="M12 3v12M6.5 10.5 12 16l5.5-5.5M4 20h16" fill="none" stroke="currentColor" stroke-width="2.2"
    stroke-linecap="round" stroke-linejoin="round"/></svg>`;
const ICON_SHARE = `<svg class="share-icon" viewBox="0 0 24 24" role="img" aria-label="Share" focusable="false">
  <path d="M12 3v12M8 7l4-4 4 4M7 10H5.5v10.5h13V10H17" fill="none" stroke="currentColor" stroke-width="2"
    stroke-linecap="round" stroke-linejoin="round"/></svg>`;

function escapeText(s) {
  return String(s).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/** Adds the card to the end of `container` (the sign-in screen). Inside the
 *  installed app it adds nothing. */
export function addGetApp(container) {
  if (!container || runningAsAppHere()) return;
  const ua = navigator.userAgent || "";
  const kind = detectPlatform(ua, navigator.maxTouchPoints || 0);
  const card = document.createElement("div");
  card.className = "card get-app";
  card.id = "getApp";
  container.appendChild(card);
  if (kind === "android") androidCard(card, ua);
  else if (kind === "ios") iosCard(card, ua);
  else computerCard(card);
}

/** Calls `fn` when the browser's install offer comes or goes, for as long as
 *  `card` is on screen. */
function whileShown(card, fn) {
  const call = () => {
    if (!card.isConnected) { onOfferChange.delete(call); return; }
    fn();
  };
  onOfferChange.add(call);
}

function androidCard(card, ua) {
  card.innerHTML = `
    <h2>Get the app</h2>
    <p class="meta">Have Mobed Diary on your phone as an app, with its own icon on your home screen.</p>
    ${inWebView(ua) ? `<p class="get-app-warn">This page is open inside another app, which may not be able to
      download it. If nothing happens, tap <b>&#8942;</b> at the top and choose <b>Open in Chrome</b>
      (or <b>Open in browser</b>), then tap Download there.</p>` : ""}
    <a class="button secondary get-app-btn" id="appDownload" href="${APK_URL}" download="Mobed-Diary.apk">
      ${ICON_DOWNLOAD}<span>Download the app</span></a>
    <p class="meta" id="appNote">${APK_NOTE}</p>
    <div class="get-app-steps hidden" id="appSteps">
      <p><b>Your download has started.</b> Then:</p>
      <ol>
        <li>If your phone warns you about the file, tap <b>Download anyway</b>. It says this about
          every app that does not come from the Play Store.</li>
        <li>When it has downloaded, tap <b>Open</b>. Or find <b>Mobed-Diary.apk</b> in your
          notifications, or in the Files app under Downloads.</li>
        <li>If it asks, tap <b>Settings</b>, turn on <b>Allow from this source</b>, then go back.</li>
        <li>Tap <b>Install</b>. If Play Protect asks, choose to install anyway (it may be under
          <b>More details</b>).</li>
        <li>Open <b>Mobed Diary</b> from your home screen.</li>
      </ol>
      <div id="appFallback"></div>
    </div>`;

  const link = card.querySelector("#appDownload");
  const note = card.querySelector("#appNote");
  const steps = card.querySelector("#appSteps");
  link.addEventListener("click", (e) => {
    // Chrome would only say "download failed" somewhere else; say it here.
    if (navigator.onLine === false) {
      e.preventDefault();
      note.textContent = "You're offline. Connect to the internet, then tap Download again.";
      note.classList.add("get-app-error");
      return;
    }
    note.textContent = APK_NOTE;
    note.classList.remove("get-app-error");
    steps.classList.remove("hidden");
    steps.scrollIntoView({ block: "nearest" });
  });

  // When the phone will not take the file (some work phones refuse every app
  // from outside the Play Store), Chrome can still add the app itself.
  const fallback = card.querySelector("#appFallback");
  const paintFallback = () => {
    if (installOffer) {
      fallback.innerHTML = `<p class="meta">Phone won't install it?</p>
        <button class="ghost small" id="appChrome">Add it from Chrome instead</button>`;
      fallback.querySelector("#appChrome").onclick = async (ev) => {
        ev.currentTarget.disabled = true;   // one question at a time; either answer redraws this
        if (await useInstallOffer()) {
          fallback.innerHTML = `<p class="meta">Added. Open <b>Mobed Diary</b> from your home screen.</p>`;
        } else paintFallback();
      };
    } else {
      fallback.innerHTML = `<p class="meta">Phone won't install it? In Chrome, tap <b>&#8942;</b> at the top,
        then <b>Install app</b> or <b>Add to Home screen</b>.</p>`;
    }
  };
  paintFallback();
  whileShown(card, paintFallback);
}

function iosCard(card, ua) {
  const device = /iPad/i.test(ua) || !/iPhone|iPod/i.test(ua) ? "iPad" : "iPhone";
  card.innerHTML = `
    <h2>Get the app</h2>
    <p class="meta">An ${device} can't install apps from outside the App Store, but you can add
      Mobed Diary to your Home Screen. It then opens like an app, with its own icon.</p>
    <button class="secondary get-app-btn" id="appHow" aria-expanded="false" aria-controls="appSteps">
      Add to Home Screen</button>
    <div class="get-app-steps hidden" id="appSteps">
      <ol>
        <li>Tap the Share button ${ICON_SHARE}. It is at the bottom or the top of the screen;
          in the newest Safari, tap <b>&bull;&bull;&bull;</b> first to find it.</li>
        <li>Scroll down and tap <b>Add to Home Screen</b>.</li>
        <li>If you see <b>Open as Web App</b>, leave it on. Tap <b>Add</b>.</li>
        <li>Open <b>Mobed Diary</b> from your Home Screen, and sign in there once more.</li>
      </ol>
      <p class="meta">No Add to Home Screen? Open this page in Safari, then try again.</p>
    </div>`;
  const how = card.querySelector("#appHow");
  const steps = card.querySelector("#appSteps");
  how.onclick = () => {
    const open = steps.classList.toggle("hidden") === false;
    how.setAttribute("aria-expanded", String(open));
    if (open) steps.scrollIntoView({ block: "nearest" });
  };
}

function computerCard(card) {
  let done = false;
  // Install was pressed and nothing was installed (the answer was no, or the
  // browser would not ask). The button goes with the offer, so the card says
  // what happened and where Install still is, rather than just losing it.
  let notInstalled = false;
  const paint = () => {
    if (done) {
      card.innerHTML = `<h2>Get the app</h2>
        <p class="meta">Installed. Mobed Diary is now with your other programs.</p>`;
      return;
    }
    const phone = `<p class="meta">For your phone: open <b>${escapeText(location.host)}</b> on it and tap
      <b>Get the app</b> there. An Android phone downloads the app; an iPhone adds it to the Home Screen.</p>`;
    if (installOffer) {
      card.innerHTML = `<h2>Get the app</h2>
        <p class="meta">Install Mobed Diary on this computer. It opens in its own window, like any other program.</p>
        <button class="secondary get-app-btn" id="appInstall">Install on this computer</button>
        ${phone}`;
      card.querySelector("#appInstall").onclick = async (ev) => {
        ev.currentTarget.disabled = true;   // one question at a time; the answer redraws the card
        done = await useInstallOffer();
        notInstalled = !done;
        paint();
      };
    } else {
      card.innerHTML = `<h2>Get the app</h2>
        ${notInstalled ? `<p class="meta">Not installed on this computer. You can still install it from your
          browser's menu.</p>` : ""}${phone}`;
    }
  };
  paint();
  whileShown(card, paint);
}
