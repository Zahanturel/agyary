"use strict";

// The words shown once, the first time a person keeps something of their own in the app.
// Remembered on this phone; when the phone keeps nothing they are simply shown again.

import { openSheet } from "/mobed-app/js/ui.js";

const KEY = "behdin.consent.v1";
export const CONSENT_WORDS = "These dates are kept for you alone. Nobody else can see them. You can delete them any time.";

function seen() {
  try { return localStorage.getItem(KEY) === "1"; } catch (e) { return false; }
}

/** Resolves when the person has pressed OK (at once if they have before). */
export function ensureConsent() {
  if (seen()) return Promise.resolve();
  return new Promise((resolve) => {
    const { body, close } = openSheet({
      title: "Before you add anything",
      dismissable: false,
      html: `<p>${CONSENT_WORDS}</p><button type="button" id="consentOk" style="width:100%">OK</button>`,
    });
    body.querySelector("#consentOk").onclick = () => {
      try { localStorage.setItem(KEY, "1"); } catch (e) { /* shown again next time */ }
      close();
      resolve();
    };
  });
}
