"use strict";

/**
 * The one page for an account that is not a mobed's. This app is for mobeds and panthakys. A mobed asks for
 * access here: the account becomes a mobed's, waiting for an admin's approval (D9), and from then on
 * it goes through the same steps as any new mobed (the fire temple, then the waiting screen).
 */

import { becomeMobed } from "../api.js";
import { state, saveSession } from "../state.js";
import { chrome, mainEl, showError, showFab, setHeader } from "../ui.js";
import { navigate } from "../router.js";
import { signOut, homeFor } from "../session.js";

export function renderBecomeMobed() {
  chrome(false);
  showFab(false);
  setHeader("Mobed Diary");
  mainEl.innerHTML = `
    <div class="card">
      <h2>This number is not set up as a mobed's</h2>
      <p>Mobed Diary is for mobeds and panthakys. If you are one, ask for access and we will check and let you in.</p>
      <div class="action-bar" style="margin-top:14px">
        <button id="bmAsk">Ask to become a mobed</button>
      </div>
      <div style="margin-top:18px"><button class="ghost small" id="bmSignOut">Sign out</button></div>
    </div>`;

  document.getElementById("bmAsk").onclick = async (ev) => {
    const btn = ev.currentTarget;
    btn.disabled = true;   // one request per tap
    let me;
    try {
      me = await becomeMobed();
    } catch (e) {
      btn.disabled = false;
      return showError(e.message);
    }
    // Now a mobed waiting for approval: the same steps as a new sign-up (fire temple, then waiting).
    state.user = me;
    state.currentAgyaryId = me.agyaries && me.agyaries[0] ? me.agyaries[0].id : null;
    saveSession();
    navigate(homeFor(), { replace: true });
  };
  document.getElementById("bmSignOut").onclick = (ev) => signOut(ev.currentTarget);
}
