"use strict";

/**
 * The delete box for a behdin, shared by the behdin's own page and the x on
 * the Behdins list. It asks the server what the behdin has - memorials,
 * upcoming events, performed ceremonies, payments - and offers only the
 * choices that mean something:
 *
 *   list       take them out of the list; every event stays on the calendar
 *   memorials  also delete their memorials and all memorial dates
 *   all        also delete their upcoming bookings and machis
 *
 * Ceremonies already performed and anything with a recorded payment always
 * stay. Nothing is deleted until the red button is pressed.
 */

import { behdinDeleteSummary, deleteBehdin } from "./api.js";
import { esc } from "./util.js";

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

/** Fill `box` with the delete choices for `behdin` ({id, name}). `onDone(result)`
 *  runs after a successful delete; `onCancel()` when the mobed backs out. */
export async function openDeleteBox(box, aid, behdin, { onDone, onCancel, onError } = {}) {
  box.innerHTML = `<p class="meta">Checking what ${esc(behdin.name)} has...</p>`;
  let s;
  try {
    s = await behdinDeleteSummary(aid, behdin.id);
  } catch (e) {
    box.innerHTML = "";
    if (onError) onError("Couldn't check: " + e.message);
    return;
  }
  const hasMem = s.memorials > 0;
  const hasUpcoming = s.upcoming_events > 0;
  const opts = [{
    value: "list",
    title: "Remove from my list only",
    detail: "Their events and memorial dates stay on your calendar and slips. Adding the same number again brings them back.",
  }];
  if (hasMem) {
    opts.push({
      value: "memorials",
      title: "Also delete their memorials",
      detail: `Deletes ${plural(s.memorials, "memorial", "memorials")} and ${plural(s.memorial_dates_ahead, "date", "dates")} still ahead from your calendar. Bookings stay.`,
    });
  }
  if (hasMem || hasUpcoming) {
    const parts = [];
    if (hasMem) parts.push(`${plural(s.memorials, "memorial", "memorials")}`);
    if (hasUpcoming) parts.push(`${plural(s.upcoming_events, "upcoming booking or machi", "upcoming bookings and machis")}`);
    const keeps = [];
    if (s.past_events) keeps.push(`${plural(s.past_events, "ceremony", "ceremonies")} already performed`);
    if (s.payments) keeps.push("anything with a recorded payment");
    opts.push({
      value: "all",
      title: "Delete everything upcoming",
      detail: `Deletes ${parts.join(" and ")}.` + (keeps.length ? ` Stays: ${keeps.join(" and ")}.` : ""),
    });
  }

  const single = opts.length === 1;
  box.innerHTML = `
    <div class="delete-box">
      <p style="margin:0 0 8px"><b>Delete ${esc(behdin.name)}?</b></p>
      ${single ? `<p class="meta">${esc(opts[0].detail)}</p>` : opts.map((o, i) => `
        <div class="check-row" style="align-items:flex-start">
          <input type="radio" name="bdScope" id="bdScope_${o.value}" value="${o.value}" ${i === 0 ? "checked" : ""}>
          <label for="bdScope_${o.value}"><b>${esc(o.title)}</b><br><span class="meta">${esc(o.detail)}</span></label>
        </div>`).join("")}
      <div class="row tight" style="margin-top:10px">
        <button class="danger small" type="button" data-go>Delete</button>
        <button class="ghost small" type="button" data-no>Keep</button>
      </div>
    </div>`;
  box.querySelector("[data-no]").onclick = () => { box.innerHTML = ""; if (onCancel) onCancel(); };
  box.querySelector("[data-go]").onclick = async (ev) => {
    const btn = ev.currentTarget;
    const pick = box.querySelector("[name=bdScope]:checked");
    const scope = pick ? pick.value : "list";
    btn.disabled = true;
    try {
      const result = await deleteBehdin(aid, behdin.id, scope);
      if (onDone) onDone({ ...result, scope });
    } catch (e) {
      btn.disabled = false;
      if (onError) onError("Couldn't delete: " + e.message);
    }
  };
}

/** A sentence saying what a delete did. */
export function deleteResultText(name, r) {
  const bits = [];
  if (r.memorials_deleted) bits.push(plural(r.memorials_deleted, "memorial", "memorials"));
  if (r.events_deleted) bits.push(plural(r.events_deleted, "booking or machi", "bookings and machis"));
  let text = `${name} removed` + (bits.length ? `, with ${bits.join(" and ")}.` : ".");
  if (r.events_kept) text += ` ${plural(r.events_kept, "event was", "events were")} kept (a payment or someone else's).`;
  return text;
}
