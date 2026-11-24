"use strict";

/**
 * The one page for a behdin's account that signed in at Mobed Diary (R4.0). The number is signed up
 * for the other app, the one for everyone; this app is for mobeds and panthakys. A mobed asks for
 * access here: the account becomes a mobed's, waiting for an admin's approval (D9), and from then on
 * it goes through the same steps as any new mobed (the fire temple, then the waiting screen).
 */

import { becomeMobed } from "../api.js";
import { state, saveSession } from "../state.js";
import { chrome, mainEl, showError, showFab, setHeader } from "../ui.js";
import { navigate } from "../router.js";
import { signOut, homeFor } from "../session.js";

// The behdin app's name is a placeholder the owner will change; it is written once, here, for this page.
const PARSI_APP = "Parsi";

export function renderBecomeMobed() {
  chrome(false);
  showFab(false);
  setHeader("Mobed Diary");
  mainEl.innerHTML = `
    <div class="card">
      <h2>Are you a mobed?</h2>
      <p>This number is signed up for the ${PARSI_APP} app (for everyone). Mobed Diary is for mobeds and
        panthakys.</p>
      <p class="meta">If you are a mobed or panthaky, ask for access: we will check and let you in.</p>
      <div class="action-bar" style="margin-top:14px">
        <button id="bmAsk">Ask to become a mobed</button>
        <a class="button secondary" id="bmOpen" href="/behdin">Open the ${PARSI_APP} app</a>
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
