"use strict";

/**
 * "How long does it repeat?" - the number asked under the repeat choice, shared
 * by the new machi and new event forms and read back by the review step.
 * Counted in all, including the first: 12 monthly is a year of months.
 */

import { esc } from "./util.js";

const MAX = { monthly: 120, yearly: 60 };
const DEFAULT = { monthly: 12, yearly: 5 };
const UNIT = { monthly: "months", yearly: "years" };

/** Choose (or clear) the repeat on a draft, with a sensible number to start from. */
export function setRepeat(draft, value) {
  draft.recurring = value || null;
  draft.recurringCount = value ? DEFAULT[value] : null;
}

/** The number box, shown only once a repeat is chosen. */
export function repeatCountHtml(draft, id) {
  if (!draft.recurring) return "";
  const unit = UNIT[draft.recurring];
  const n = draft.recurringCount || DEFAULT[draft.recurring];
  return `<div class="repeat-count">
    <label for="${id}">For how many ${unit} in all?</label>
    <input type="number" inputmode="numeric" id="${id}" min="2" max="${MAX[draft.recurring]}" value="${esc(String(n))}">
    <p class="meta">Counting this one. For example ${n} means this one and the next ${n - 1}.</p>
  </div>`;
}

/** Keep what is typed on the draft as it is typed (no redraw: that would drop the keyboard). */
export function wireRepeatCount(draft, id, keep) {
  const el = document.getElementById(id);
  if (!el) return;
  el.oninput = () => {
    draft.recurringCount = el.value === "" ? null : Number(el.value);
    keep(draft);
  };
}

/** What is wrong with the number, in words, or "" when it is fine (or nothing repeats). */
export function repeatCountProblem(draft) {
  if (!draft.recurring) return "";
  const n = draft.recurringCount;
  const max = MAX[draft.recurring];
  if (!Number.isInteger(n) || n < 2 || n > max) {
    return `Please enter how many ${UNIT[draft.recurring]} in all, from 2 to ${max}.`;
  }
  return "";
}

/** The request field for the draft: {} for a single event. */
export function repeatFields(draft) {
  return draft.recurring ? { recurring: draft.recurring, recurring_count: draft.recurringCount } : {};
}

/** One plain sentence for the review step. */
export function repeatSentence(draft) {
  const unit = UNIT[draft.recurring];
  const how = draft.recurring === "yearly" ? "every year, on the same Roj and Mah" : "every month, on the same Roj";
  return `This will repeat ${how}, ${draft.recurringCount} ${unit} in all counting this one.`;
}
