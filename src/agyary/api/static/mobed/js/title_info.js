"use strict";

/**
 * What the religious titles mean (owner, 29 Nov 2026): an "i" button beside every place a title is chosen
 * opens one sheet with each title, its meaning, and the rule for a child who dies before the Navjote.
 * Source: Dastur (Dr.) Firoze M. Kotwal, "Zoroastrian religious titles and some notes concerning the dead"
 * (The Funerary Observances in the Sacred Zoroastrian Tradition, Part I.A).
 */

import { openSheet } from "./ui.js";
import { esc } from "./util.js";

export const TITLE_MEANINGS = [
  ["Dastur", "One who wields religious authority: a high priest."],
  ["Ervad", "Master of the scriptures. A priest of the priestly class who had the naawar ordainment before puberty, "
    + "and who may or may not have had the maraatab ordainment."],
  ["Osta", "A disciple of a religious teacher. A boy of the priestly class whose Navjote was done before puberty "
    + "but who has not had the naawar ordainment."],
  ["Osti", "A woman who has studied the scripture. A woman of the priestly class whose Navjote has been done. "
    + "Also given to a woman of the lay class after she marries a member of the priestly class."],
  ["Behdin", "One belonging to the Good Religion. A Parsi or Irani Zoroastrian of the lay (non-priestly) class "
    + "whose Navjote was done before puberty. Also given to a woman of the priestly class after she marries a "
    + "member of the lay class."],
  ["Khurd", "Small, little. (Often said wrongly as Khud, which means self.) A small boy or girl of the priestly "
    + "or lay class before the Navjote."],
  ["Wahmaan", "So and so, such a one. Used only for an unnamed baby who dies, or when the name is not known."],
];

export const CHILD_RULES = [
  "A child of about 7 whose Navjote has not been done and who dies is invested with the sudreh-kusti during "
  + "the sachkaar, so the child can be declared Osta, Osti or Behdin in all the death ceremonies.",
  "That child is remembered as Osta or Osti if from the priestly class, or as Behdin if from the lay class. "
  + "Khurd is not used.",
  "A child below 7 whose Navjote has not been done is remembered with the title Khurd.",
];

/** The small round button to put beside a title picker. */
export const titleInfoButton = () =>
  `<button type="button" class="info-btn" data-title-info aria-label="What the titles mean">i</button>`;

export function openTitleInfo() {
  const html = `
    <dl class="title-meanings">${TITLE_MEANINGS.map(([t, m]) =>
      `<dt>${esc(t)}</dt><dd>${esc(m)}</dd>`).join("")}</dl>
    <h3 style="margin:16px 0 4px">A child who dies before the Navjote</h3>
    <ul style="margin:0;padding-left:20px">${CHILD_RULES.map((r) => `<li style="margin:0 0 6px">${esc(r)}</li>`).join("")}</ul>
    <p class="meta" style="margin:12px 0 0">From the writing of Dastur (Dr.) Firoze M. Kotwal, High Priest,
      H.B. Wadia Atash Bahram.</p>`;
  openSheet({ title: "What the titles mean", html });
}

/** Open the sheet when an "i" button inside `root` is tapped. Safe to call again on the same root. */
export function wireTitleInfo(root) {
  root.addEventListener("click", (e) => {
    if (e.target.closest("[data-title-info]")) { e.preventDefault(); openTitleInfo(); }
  });
}
