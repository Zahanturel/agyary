"use strict";

/**
 * Admin -> Mobeds: who is waiting for approval, and the one switch per mobed
 * (DECISIONS D9). On is the whole app; off is one screen saying so, with
 * everything they saved kept and nothing sent under their account.
 *
 * Doongerwadi and prayer hall managers are here too (D10), with the place they
 * say they work at, and the same one switch.
 *
 * And who says they are a fire temple's panthaky (D10). That is only a claim
 * until "Confirm as panthaky" here, because the panthaky sees every machi at
 * their temple (D7). A confirmed panthaky can be made a mobed again.
 *
 * And who joined a fire temple with no panthaky in the app (D10, 22 Nov 2026): they
 * get its prayer requests only once confirmed, which the admin does here (Confirm or
 * Not one of ours; Put back for one taken off). Where it has a panthaky, the
 * panthaky does it on their Mobeds page.
 *
 * For the numbers in ADMIN_PHONES only; the server answers anyone else with a
 * 404, so hiding the way here is a courtesy and not the protection.
 */

import { adminMobeds, adminSetMobedAccess, adminDecidePanthaky, adminDecideRequests } from "../api.js";
import { chrome, mainEl, showFab, showError, showInfo, refreshHeader, loading, backBar, screenFailed } from "../ui.js";
import { esc, istShortWhen } from "../util.js";
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
    ? `<span class="meta" style="display:block">${temple} already has ${t.other_panthakys.length === 1 ? "a panthaky" : "panthakys"} in the app:
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
      ${buttons ? `<div class="row tight" style="margin-top:6px;flex-wrap:wrap">${buttons}</div>` : ""}
    </div>`;
}

const isManager = (m) => m.account_kind === "funeral_manager";

function row(m) {
  const where = isManager(m)
    ? (m.funeral_places.length
      ? m.funeral_places.map(p => `Manager at <strong>${esc(p.name)}</strong>${p.city && !p.name.includes(p.city) ? `, ${esc(p.city)}` : ""}`).join("; ")
      : "Doongerwadi manager, no place")
    : m.agyaries.length ? m.agyaries.map(esc).join(", ") : "No fire temple chosen yet";
  // In India time, as everywhere in the app (not the UTC day the server's timestamp starts with).
  const when = m.signed_up ? `Signed up ${esc(istShortWhen(m.signed_up))}` : "";
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
      <div class="lr-main"><b>${esc(m.name)} ${TAGS[m.access] || ""}${isManager(m)
          ? ` <span class="tag grey">Doongerwadi</span>` : ""}</b>
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
  const rest = data.mobeds.filter(m => m.access !== "pending" && !m.panthaky_claim_waiting && !isManager(m));
  const managers = data.mobeds.filter(m => m.access !== "pending" && isManager(m));
  // Joined a fire temple with no panthaky in the app, or taken off its list there: the
  // admin decides who gets its prayer requests. A sign-up still waiting is confirmed by
  // the approval itself, so is not here.
  const joins = [];
  for (const m of data.mobeds) {
    if (m.access === "pending" || isManager(m) || m.is_admin) continue;
    for (const t of m.memberships) {
      if (!t.has_panthaky && (t.requests === "waiting" || t.requests === "off")) joins.push({ m, t });
    }
  }

  mainEl.innerHTML = `
    <div class="card">
      ${backBar("Mobeds")}
      <p class="meta" style="margin:4px 0 0">A new mobed or Doongerwadi manager can use Mobed Diary only once
        you approve them. Turning someone off keeps everything they saved, and stops all reminders and messages
        under their account until you turn them on again.</p>
    </div>

    <div class="card">
      <h2>Waiting for approval${waiting.length ? ` (${waiting.length})` : ""}</h2>
      ${waiting.length ? waiting.map(row).join("") : `<p class="meta">Nobody is waiting.</p>`}
    </div>

    ${joins.length ? `<div class="card">
      <h2>Joined, waiting for you (${joins.length})</h2>
      <p class="meta" style="margin:4px 0 0">These fire temples have no panthaky in the app, so you confirm who
        gets their prayer requests.</p>
      ${joins.map(({ m, t }) => `<div class="list-row" style="flex-wrap:wrap;gap:8px">
        <div class="lr-main"><b>${esc(m.name)}</b>
          <span style="display:block">${t.requests === "off" ? `Off the list at ${esc(t.name)}`
            : `Joined ${esc(t.name)}`}</span></div>
        <div class="row tight">${t.requests === "off"
          ? `<button class="secondary small" data-ract="on" data-id="${m.id}" data-aid="${t.agyary_id}">Put back</button>`
          : `<button class="small" data-ract="confirm" data-id="${m.id}" data-aid="${t.agyary_id}">Confirm</button>
             <button class="ghost small" data-ract="off" data-id="${m.id}" data-aid="${t.agyary_id}">Not one of ours</button>`}
        </div>
      </div>`).join("")}
    </div>` : ""}

    ${claims.length ? `<div class="card">
      <h2>Say they are the panthaky (${claims.length})</h2>
      <p class="meta" style="margin:4px 0 0">Until you confirm it they are a mobed, and see only their own
        machis. A panthaky sees every machi at their fire temple.</p>
      ${claims.map(row).join("")}
    </div>` : ""}

    <div class="card">
      <h2>All mobeds (${rest.length})</h2>
      ${rest.length ? rest.map(row).join("") : `<p class="meta">None yet.</p>`}
    </div>

    <div class="card">
      <h2>Doongerwadi managers (${managers.length})</h2>
      <p class="meta" style="margin:4px 0 0">They see only their own place's page, none of a mobed's.</p>
      ${managers.length ? managers.map(row).join("") : `<p class="meta">None yet.</p>`}
    </div>`;

  const byId = new Map(data.mobeds.map(m => [String(m.id), m]));

  /** Make the change. `btn` is the button that confirmed it: off while the
   *  change is made, and back on if it fails. */
  const apply = async (m, access, btn) => {
    btn.disabled = true;
    let res;
    try {
      res = await adminSetMobedAccess(m.id, access);
    } catch (e) {
      btn.disabled = false;
      return showError(e.message);
    }
    // Turned off, a place they held on a request is freed, and the server says so (D10, 22 Nov 2026).
    showInfo(access === "off" ? `${m.name} is turned off.${res && res.freed ? ` ${res.freed}` : ""}`
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

  /** Whether one who joined gets the fire temple's prayer requests; the server's words say what happened. */
  mainEl.querySelectorAll("[data-ract]").forEach(btn => {
    btn.onclick = async () => {
      const m = byId.get(btn.dataset.id);
      if (!m || btn.disabled) return;
      btn.disabled = true;
      let res;
      try {
        res = await adminDecideRequests(m.id, Number(btn.dataset.aid), btn.dataset.ract);
      } catch (e) {
        btn.disabled = false;
        return showError(e.message);
      }
      showInfo(res.done.message);
      if (!alive()) return;
      const y = window.scrollY;
      await renderAdminMobeds();
      if (alive()) window.scrollTo(0, y);
    };
  });

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
          : isManager(m)
          ? `Turn ${esc(m.name)} off? They will see that their access is off. Nothing is deleted.`
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
