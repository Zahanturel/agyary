"use strict";

/** Shown when an admin has switched this account off: the one screen, with a way to sign out. */

import { chrome, mainEl, setHeader } from "/mobed-app/js/ui.js";
import { APP_NAME } from "../brand.js";
import { signOut } from "../session.js";

export function renderOff() {
  chrome(false);
  setHeader(APP_NAME);
  mainEl.innerHTML = `
    <div class="card">
      <h2>Your access is switched off</h2>
      <p class="meta">You cannot use ${APP_NAME} right now. If you think this is a mistake, please
        get in touch with the people who run it.</p>
      <div style="margin-top:14px"><button class="ghost" id="offSignOut">Sign out</button></div>
    </div>`;
  document.getElementById("offSignOut").onclick = (ev) => signOut(ev.currentTarget);
}
