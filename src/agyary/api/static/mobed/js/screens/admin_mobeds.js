"use strict";

/**
 * Admin -> Mobeds: who is waiting for approval, and the one switch per mobed
 * (DECISIONS D9). On is the whole app; off is one screen saying so, with
 * everything they saved kept and nothing sent under their account.
 *
 * And who says they are a fire temple's panthaky (D10). That is only a claim
 * until "Confirm as panthaky" here, because the panthaky sees every machi at
 * their temple (D7). A confirmed panthaky can be made a mobed again.
 *
 * For the numbers in ADMIN_PHONES only; the server answers anyone else with a
 * 404, so hiding the way here is a courtesy and not the protection.
 */

import { adminMobeds, adminSetMobedAccess, adminDecidePanthaky } from "../api.js";
import { chrome, mainEl, showFab, showError, showInfo, refreshHeader, loading, backBar, screenFailed } from "../ui.js";
import { esc, gregShort } from "../util.js";
import { navGuard } from "../router.js";

const TAGS = {
  pending: `<span class="tag" style="background:var(--amber-100);color:var(--amber-600)">Waiting</span>`,
  on: `<span class="tag role">On</span>`,
  off: `<span class="tag grey">Off</span>`,
};

/** One line per fire temple about the panthaky role there, with its buttons. */
function roleLine(m, t) {
  const temple = esc(t.name);
  const others = t.other_panthakys.length
    ? `<span class="meta" style="display:block">${temple} already has a panthaky in the app:
        ${t.other_panthakys.map(esc).join(", ")}.</span>` : "";
  const btn = (act, label, cls = "small") =>
    `<button class="${cls}" data-pact="${act}" data-id="${m.id}" data-aid="${t.agyary_id}">${label}</button>`;
  let text = "", buttons = "";
  if (t.panthaky_claim_waiting) {
    text = `<b>Says they are the panthaky of ${temple}</b>${others}`;
    buttons = btn("confirm", "Confirm as panthaky") + btn("decline", "Not the panthaky", "ghost small");
  } else if (t.role === "panthaky") {
    text = `<b>Panthaky of ${temple}</b>`;
    buttons = btn("remove", "Remove as panthaky", "secondary small");
  } else if (t.role === "caretaker") {
    text = `<b>Caretaker of ${temple}</b>`;
  } else if (t.claimed_role === "panthaky" && t.claim_decision === "declined") {
    text = `<span>Said they are the panthaky of ${temple}. You said no.</span>${others}`;
    buttons = btn("confirm", "Confirm as panthaky", "ghost small");
  } else if (t.claimed_role === "panthaky" && t.claim_decision === "removed") {
    text = `<span>Was the panthaky of ${temple} until you removed them.</span>${others}`;
    buttons = btn("confirm", "Confirm as panthaky", "ghost small");
  }
  if (!text) return "";
  return `<div style="flex-basis:100%">
      <span style="display:block">${text}</span>
      ${buttons ? `<div class="row tight" style="margin-top:6px">${buttons}</div>` : ""}
    </div>`;
}

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
      ${m.memberships.map(t => roleLine(m, t)).join("")}
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
  // Already using the app, and saying they are a panthaky: at the top, not
  // somewhere down the list by name.
  const claims = data.mobeds.filter(m => m.access !== "pending" && m.panthaky_claim_waiting);
  const rest = data.mobeds.filter(m => m.access !== "pending" && !m.panthaky_claim_waiting);

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

    ${claims.length ? `<div class="card">
      <h2>Say they are the panthaky (${claims.length})</h2>
      <p class="meta" style="margin:4px 0 0">Until you confirm it they are a mobed, and see only their own
        machis. A panthaky sees every machi at their fire temple.</p>
      ${claims.map(row).join("")}
    </div>` : ""}

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

  /** The owner's word on the panthaky role at one fire temple. */
  const decide = async (m, t, decision, btn) => {
    btn.disabled = true;
    try {
      await adminDecidePanthaky(m.id, t.agyary_id, decision);
    } catch (e) {
      btn.disabled = false;
      return showError(e.message);
    }
    showInfo(decision === "confirm" ? `${m.name} is now the panthaky of ${t.name}. They are told in the app.`
      : decision === "decline" ? `${m.name} stays a mobed at ${t.name}. They are told in the app.`
      : `${m.name} is a mobed at ${t.name} again. They are told in the app.`);
    if (!alive()) return;
    const y = window.scrollY;
    await renderAdminMobeds();
    if (alive()) window.scrollTo(0, y);
  };

  mainEl.querySelectorAll("[data-pact]").forEach(btn => {
    btn.onclick = () => {
      const m = byId.get(btn.dataset.id);
      const t = m && m.memberships.find(x => String(x.agyary_id) === btn.dataset.aid);
      if (!m || !t) return;
      const act = btn.dataset.pact;
      if (act === "decline") return decide(m, t, act, btn);
      // Making someone panthaky, or taking it away, changes what they see: asked first.
      const ask = mainEl.querySelector(`[data-ask="${m.id}"]`);
      ask.innerHTML = `
        <p class="meta" style="margin:8px 0">${act === "confirm"
          ? `Make ${esc(m.name)} the panthaky of ${esc(t.name)}? They will see every machi there, by every
             mobed.${t.other_panthakys.length ? ` ${esc(t.name)} already has a panthaky in the app.` : ""}`
          : `Make ${esc(m.name)} a mobed at ${esc(t.name)} again? They will see only their own machis there.`}</p>
        <div class="row tight">
          <button class="${act === "confirm" ? "" : "danger "}small" data-go>${act === "confirm"
            ? "Yes, confirm" : "Yes, remove"}</button>
          <button class="ghost small" data-no>Cancel</button>
        </div>`;
      ask.querySelector("[data-no]").onclick = () => { ask.innerHTML = ""; };
      ask.querySelector("[data-go]").onclick = (ev) => decide(m, t, act, ev.currentTarget);
    };
  });

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
