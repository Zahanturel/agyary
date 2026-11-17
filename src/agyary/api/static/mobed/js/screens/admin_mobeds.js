"use strict";

/**
 * Admin -> Mobeds: who is waiting for approval, and the one switch per mobed
 * (DECISIONS D9). On is the whole app; off is one screen saying so, with
 * everything they saved kept and nothing sent under their account.
 *
 * For the numbers in ADMIN_PHONES only; the server answers anyone else with a
 * 404, so hiding the way here is a courtesy and not the protection.
 */

import { adminMobeds, adminSetMobedAccess } from "../api.js";
import { chrome, mainEl, showFab, showError, showInfo, refreshHeader, loading, backBar, screenFailed } from "../ui.js";
import { esc, gregShort } from "../util.js";
import { navGuard } from "../router.js";

const TAGS = {
  pending: `<span class="tag" style="background:var(--amber-100);color:var(--amber-600)">Waiting</span>`,
  on: `<span class="tag role">On</span>`,
  off: `<span class="tag grey">Off</span>`,
};

function row(m) {
  const where = m.agyaries.length ? m.agyaries.map(esc).join(", ") : "No fire temple chosen yet";
  const when = m.signed_up ? `Signed up ${esc(gregShort(m.signed_up.slice(0, 10)))}` : "";
  let actions = "";
  if (m.is_admin) {
    actions = `<span class="meta">Admin - always on</span>`;
  } else if (m.access === "pending") {
    actions = `<button class="small" data-act="on" data-id="${m.id}">Approve</button>
      <button class="ghost small" data-act="off" data-id="${m.id}">Turn off</button>`;
  } else if (m.access === "on") {
    actions = `<button class="secondary small" data-act="off" data-id="${m.id}">Turn off</button>`;
  } else {
    actions = `<button class="small" data-act="on" data-id="${m.id}">Turn on</button>`;
  }
  return `
    <div class="list-row" data-row="${m.id}" style="flex-wrap:wrap;gap:8px">
      <div class="lr-main"><b>${esc(m.name)} ${TAGS[m.access] || ""}</b>
        <span style="display:block">${esc(m.phone)}</span>
        <span style="display:block">${where}${when ? ` - ${when}` : ""}</span></div>
      <div class="row tight">${actions}</div>
      <div data-ask="${m.id}" style="flex-basis:100%"></div>
    </div>`;
}

export async function renderAdminMobeds() {
  chrome(true);
  refreshHeader();
  showFab(false);
  loading();
  const alive = navGuard();

  let data;
  try {
    data = await adminMobeds();
  } catch (e) {
    if (!alive()) return;
    if (e.status === 404) return screenFailed("That page isn't available.");
    return screenFailed(e.message, () => renderAdminMobeds());
  }
  if (!alive()) return;

  const waiting = data.mobeds.filter(m => m.access === "pending");
  const rest = data.mobeds.filter(m => m.access !== "pending");

  mainEl.innerHTML = `
    <div class="card">
      ${backBar("Mobeds")}
      <p class="meta" style="margin:4px 0 0">A new mobed can use Mobed Diary only once you approve them.
        Turning a mobed off keeps everything they saved, and stops all reminders and messages under their
        account until you turn them on again.</p>
    </div>

    <div class="card">
      <h2>Waiting for approval${waiting.length ? ` (${waiting.length})` : ""}</h2>
      ${waiting.length ? waiting.map(row).join("") : `<p class="meta">Nobody is waiting.</p>`}
    </div>

    <div class="card">
      <h2>All mobeds (${rest.length})</h2>
      ${rest.length ? rest.map(row).join("") : `<p class="meta">None yet.</p>`}
    </div>`;

  const byId = new Map(data.mobeds.map(m => [String(m.id), m]));

  /** Make the change. `btn` is the button that confirmed it: off while the
   *  change is made, and back on if it fails. */
  const apply = async (m, access, btn) => {
    btn.disabled = true;
    try {
      await adminSetMobedAccess(m.id, access);
    } catch (e) {
      btn.disabled = false;
      return showError(e.message);
    }
    showInfo(access === "off" ? `${m.name} is turned off.`
      : m.access === "pending" ? `${m.name} is approved. They are told when they next open the app.`
      : `${m.name} is turned on again.`);
    if (!alive()) return;
    // Drawn again with the new state, in the same place on the page.
    const y = window.scrollY;
    await renderAdminMobeds();
    if (alive()) window.scrollTo(0, y);
  };

  mainEl.querySelectorAll("[data-act]").forEach(btn => {
    btn.onclick = () => {
      const m = byId.get(btn.dataset.id);
      if (!m) return;
      if (btn.dataset.act === "on") return apply(m, "on", btn);
      // Turning off is asked first: their families stop getting reminders.
      const ask = mainEl.querySelector(`[data-ask="${m.id}"]`);
      ask.innerHTML = `
        <p class="meta" style="margin:8px 0">${m.access === "pending"
          ? `Turn ${esc(m.name)} off instead of approving them? They will see that their access is off.`
          : `Turn ${esc(m.name)} off? They will see that their access is off, and no reminders or daily
             report go out under their account until you turn them on again. Nothing is deleted.`}</p>
        <div class="row tight">
          <button class="danger small" data-go>Turn off</button>
          <button class="ghost small" data-no>Cancel</button>
        </div>`;
      ask.querySelector("[data-no]").onclick = () => { ask.innerHTML = ""; };
      ask.querySelector("[data-go]").onclick = (ev) => apply(m, "off", ev.currentTarget);
    };
  });
}
