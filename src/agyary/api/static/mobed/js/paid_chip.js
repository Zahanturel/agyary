"use strict";

/**
 * The paid / not paid tick: a button the mobed taps to say a behdin has paid for
 * an event (a booking, a machi, or a date of a memorial) or has not. Plain on both
 * sides so it reads at a glance down a list. Shared by the day list and the
 * memorial page.
 */

import { showError } from "./ui.js";

const inner = (paid) =>
  `<span class="pay-mark" aria-hidden="true">${paid ? "&#10003;" : "&#8377;"}</span>${paid ? "Paid" : "Not paid"}`;

/** `kind:id` is what the handler gets back to know which event was tapped. */
export function payChipHtml(kind, id, paid) {
  return `<button type="button" class="pay-chip ${paid ? "paid" : "unpaid"}" data-pay="${kind}:${id}"
    aria-pressed="${paid ? "true" : "false"}" title="Tap to mark as ${paid ? "not paid" : "paid"}">${inner(paid)}</button>`;
}

function show(chip, paid) {
  chip.classList.toggle("paid", paid);
  chip.classList.toggle("unpaid", !paid);
  chip.setAttribute("aria-pressed", paid ? "true" : "false");
  chip.title = `Tap to mark as ${paid ? "not paid" : "paid"}`;
  chip.innerHTML = inner(paid);
}

/** Flip a chip. It changes at once and is put back, with a message, if `save(paid)`
 *  fails - so a lost connection never leaves a false "Paid". `after(paid)` runs on success. */
export async function flipPaidChip(chip, save, after) {
  if (!save || chip.disabled) return;
  const was = chip.getAttribute("aria-pressed") === "true";
  show(chip, !was);
  chip.disabled = true;
  try {
    await save(!was);
    if (after) after(!was);
  } catch (e) {
    show(chip, was);
    showError("Couldn't save that: " + e.message);
  } finally {
    chip.disabled = false;
  }
}
