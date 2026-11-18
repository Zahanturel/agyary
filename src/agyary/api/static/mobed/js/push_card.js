"use strict";

/**
 * The "Notifications on this phone" card: what Mobed Diary tells this account
 * shows on this phone even when the app is closed (web push, push.js). In
 * Settings for every account that is on (a mobed's, a manager's), and on the
 * admin screen for an admin. Each phone is turned on by itself.
 */

import { myPush, myPushTest } from "./api.js";
import * as push from "./push.js";
import { showError, showInfo } from "./ui.js";
import { esc } from "./util.js";

const plural = (n) => `${n} phone${n === 1 ? "" : "s"}`;

/** Draw the card's inside into `box` once it knows. `what` finishes "Get a
 *  notification on this phone when ...", e.g. "a Doongerwadi asks your fire
 *  temple for prayers". `alive` is the screen's navGuard. */
export async function paintPushCard(box, alive, { what }) {
  let status, sub;
  try {
    [status, sub] = await Promise.all([myPush(), push.current()]);
  } catch (e) {
    if (!alive()) return;
    box.innerHTML = `<p class="meta"></p>
      <div style="margin-top:10px"><button class="secondary small" type="button" data-push-retry>Try again</button></div>`;
    box.querySelector("p").textContent = e.message;
    box.querySelector("[data-push-retry]").onclick = () => paintPushCard(box, alive, { what });
    return;
  }
  if (!alive()) return;
  const again = () => { if (alive()) paintPushCard(box, alive, { what }); };

  if (!status.configured) {
    box.innerHTML = `<p class="meta">Not set up on the server yet. Once it is, you can turn them on here.</p>`;
    return;
  }
  const blocked = push.blockerHere();
  if (blocked && !sub) {
    box.innerHTML = `<p class="meta">${esc(blocked)}</p>
      <div style="margin-top:10px"><button class="secondary small" type="button" data-push-retry>Check again</button></div>`;
    box.querySelector("[data-push-retry]").onclick = again;
    return;
  }
  if (sub) {
    box.innerHTML = `<p class="meta"><b>On for this phone.</b> When ${esc(what)}, it shows here even when Mobed
        Diary is closed.${status.devices > 1 ? ` On for ${plural(status.devices)} in all.` : ""}</p>
      <div class="action-bar" style="margin-top:10px">
        <button class="small" type="button" data-push-test>Send a test</button>
        <button class="ghost small" type="button" data-push-off>Turn off on this phone</button>
      </div>`;
    box.querySelector("[data-push-test]").onclick = async (ev) => {
      const btn = ev.currentTarget;
      btn.disabled = true;
      try {
        const r = await myPushTest();
        if (r.sent) showInfo(`Test sent to ${plural(r.sent)}. It should appear in a few seconds.`);
        else showError("The test could not be delivered. Turn notifications off on this phone and on again.");
      } catch (e) {
        showError(e.message);
      } finally {
        btn.disabled = false;
      }
    };
    box.querySelector("[data-push-off]").onclick = async (ev) => {
      ev.currentTarget.disabled = true;
      try {
        await push.turnOff();
        showInfo("Notifications are off on this phone.");
      } catch (e) {
        showError(e.message);
      }
      again();
    };
    return;
  }
  box.innerHTML = `<p class="meta">Get a notification on this phone when ${esc(what)}, even when Mobed Diary is
      closed.${status.devices ? ` On for ${plural(status.devices)} already.` : ""}</p>
    <div style="margin-top:10px"><button class="small" type="button" data-push-on>Turn on for this phone</button></div>`;
  box.querySelector("[data-push-on]").onclick = async (ev) => {
    const btn = ev.currentTarget;
    btn.disabled = true;
    try {
      await push.turnOn();
      showInfo("Notifications are on for this phone. Try Send a test.");
    } catch (e) {
      btn.disabled = false;
      return showError(e.message);
    }
    again();
  };
}
