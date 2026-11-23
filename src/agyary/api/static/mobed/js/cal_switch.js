"use strict";

/**
 * The switch at the bottom of the Calendar tab: Events or Machi (owner, 24 Nov
 * 2026). Machi and Calendar used to be two bottom tabs; they are one now, with
 * this switch, which leaves room in the bar for Behdins, Requests and Mobeds.
 * Both views share one day (state.calendar), so the same day stays on screen
 * when the mobed switches, and the tab remembers which one was last open
 * (state.calendarView: "events" or "machi", set by each of the two screens).
 */

import { state } from "./state.js";
import { navigate } from "./router.js";
import { calendarHash, boardHash } from "./calendar.js";

/** The two-button switch, with `active` ("events" or "machi") lit. */
export function switchHtml(active) {
  const btn = (key, label) => `<button type="button" role="tab" data-seg="${key}"
    aria-selected="${active === key}" class="${active === key ? "on" : ""}">${label}</button>`;
  return `<div class="seg" role="tablist" aria-label="Show">${btn("events", "Events")}${btn("machi", "Machi")}</div>`;
}

/** Make the switch in `root` go to the other view, on the same day. */
export function wireSwitch(root) {
  root.querySelectorAll("[data-seg]").forEach(b => {
    b.onclick = () => {
      if (b.classList.contains("on")) return;
      navigate(b.dataset.seg === "machi" ? boardHash(state.calendar) : calendarHash(state.calendar));
    };
  });
}
