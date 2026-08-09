"use strict";

/**
 * UNREACHABLE IN THE MOBED APP. No route points here (see main.js); this
 * file is kept for the agyari management system, which will be designed
 * after talking to panthakies. Do not wire it up without that decision.
 *
 * Invites - the only way anyone becomes a panthaky or caretaker.
 *
 * COPY REVIEW NEEDED (flagged, not guessed):
 * The role names below are rendered bare - "Panthaky", "Mobed",
 * "Caretaker" - with no explanatory gloss, and this screen carries no
 * descriptive prose about what inviting someone means or what each role can
 * do. Those are this community's own terms for its own offices, and
 * inventing definitions for them in an English UI is not something to do
 * from the outside. The screen is fully functional without that text; the
 * places it belongs are marked with COPY: below.
 *
 * Also unwritten deliberately: there is no invitation message sent to the
 * invitee. The backend doesn't send one (an invite is redeemed silently
 * when that phone next signs in), so nothing here promises one.
 */

import { listInvites, createInvite, revokeInvite } from "../api.js";
import { state, currentAgyary } from "../state.js";
import {
  chrome, mainEl, showFab, showError, showInfo, refreshHeader,
  loading, backBar, wireAll,
} from "../ui.js";
import { esc, phoneField, readPhone } from "../util.js";
import { navigate } from "../router.js";

const ROLES = [
  ["mobed", "Mobed"],
  ["panthaky", "Panthaky"],
  ["caretaker", "Caretaker"],
];

export async function renderInvites() {
  chrome(true);
  refreshHeader();
  showFab(false);
  loading();

  const agyary = currentAgyary();
  const aid = agyary.id;
  let invites = [];
  try {
    invites = await listInvites(aid);
  } catch (e) {
    mainEl.innerHTML = "";
    return showError(e.message);
  }

  mainEl.innerHTML = `
    <div class="card">
      ${backBar("People", "#/settings")}
      <!-- COPY: a sentence here explaining what an invite does and when the
           person picks up the role would help. Left out pending review. -->
      <label>WhatsApp number</label>
      ${phoneField("invPhone")}
      <label>Role</label>
      <select id="invRole">
        ${ROLES.map(([k, label]) => `<option value="${k}">${label}</option>`).join("")}
      </select>
      <div style="margin-top:14px"><button id="invCreate">Create invite</button></div>
    </div>

    <div class="card">
      <h2>Open invites</h2>
      ${invites.length ? invites.map(i => `
        <div class="list-row">
          <div class="lr-main"><b>${esc(i.phone)}</b>
            <span><span class="tag role">${esc(i.role)}</span>expires ${esc(i.expires_at.slice(0, 10))}</span></div>
          <button class="ghost small" data-revoke="${i.id}">Revoke</button>
        </div>`).join("") : '<p class="meta">No open invites.</p>'}
    </div>`;

  wireAll("[data-back]", (el) => navigate(el.dataset.back));

  document.getElementById("invCreate").onclick = async () => {
    const phone = readPhone("invPhone");
    const role = document.getElementById("invRole").value;
    if (!phone) return showError("Please enter a valid phone number.");
    try {
      await createInvite(aid, phone, role);
      // Re-inviting a number replaces its open invite rather than adding a
      // second, so the list is always the current state.
      showInfo("Invite created.");
      renderInvites();
    } catch (e) {
      showError(e.message);
    }
  };

  wireAll("[data-revoke]", async (el) => {
    try {
      await revokeInvite(aid, el.dataset.revoke);
      renderInvites();
    } catch (e) {
      showError(e.message);
    }
  });
}
