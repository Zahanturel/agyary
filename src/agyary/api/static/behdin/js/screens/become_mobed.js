"use strict";

/**
 * "Are you a mobed?" explained. Asking to become one is done in Mobed Diary, not here: this page
 * says how, and links there.
 */

import { chrome, mainEl, setHeader } from "/mobed-app/js/ui.js";
import { APP_NAME } from "../brand.js";

export function renderBecomeMobed() {
  chrome(true);
  setHeader(APP_NAME);
  mainEl.innerHTML = `
    <div class="card">
      <h2>Are you a mobed?</h2>
      <p>Mobed Diary is a separate app, for mobeds and panthakies, to keep their ceremonies and
        memorial prayers.</p>
      <p class="meta">Open it and sign in with the same WhatsApp number. It will offer to make your
        account a mobed's. An admin then checks and approves it, and until then you go on using
        ${APP_NAME} as you do now.</p>
      <div style="margin-top:14px"><a class="button link-button" href="/mobed">Open Mobed Diary</a></div>
    </div>`;
}
