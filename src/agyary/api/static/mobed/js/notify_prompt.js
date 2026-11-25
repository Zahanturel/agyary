"use strict";

/**
 * Once per device, right after a mobed signs in and is approved: "Allow notifications?" with Allow and
 * Not now. The choice is remembered on this phone so the sheet is not shown again; the switch in Settings
 * (push_card.js) stays. A phone that cannot have notifications, or already has them, is never asked.
 */

import * as push from "./push.js";
import { state } from "./state.js";
import { openSheet, showError } from "./ui.js";

const KEY = "mobed.notifyAsked";

function asked() {
  try { return localStorage.getItem(KEY) === "1"; } catch (e) { return false; }
}

function remember() {
  try { localStorage.setItem(KEY, "1"); } catch (e) { /* asked again next time: harmless */ }
}

export async function askNotificationsOnce() {
  const u = state.user;
  if (!u || state.offline || u.account_kind === "behdin" || (u.access && u.access !== "on") || asked()) return;
  // Nothing to ask where it cannot work; and nothing to ask if it is already on.
  if (push.blockerHere() || await push.current()) return remember();
  if (document.querySelector(".sheet-backdrop")) return;
  const sheet = openSheet({
    title: "Allow notifications?",
    html: `<p style="margin-top:0">You will be told of new requests.</p>
      <div class="stack" style="margin-top:12px">
        <button type="button" data-allow>Allow</button>
        <button type="button" class="ghost" data-later>Not now</button>
      </div>`,
    onClose: remember,
  });
  sheet.body.querySelector("[data-later]").onclick = sheet.close;
  sheet.body.querySelector("[data-allow]").onclick = async () => {
    sheet.close();
    try {
      await push.turnOn();
    } catch (e) {
      showError(e.message);
    }
  };
}
