"use strict";

/**
 * A prayer (Afringan, Jashan...) as a button that is plainly on or off.
 *
 *   ON  - filled, with a tick and a cross: the cross says "tap to turn this off".
 *   OFF - plain and dashed, with a plus: "tap to turn this on".
 *
 * The whole button is one control, so the cross and the button do the same thing.
 * The state lives in aria-pressed, which is also what screen readers announce.
 */

import { esc } from "./util.js";

export function serviceToggleHtml(id, name, on) {
  return `<button type="button" class="svc-toggle ${on ? "on" : ""}" data-svc="${id}" aria-pressed="${on ? "true" : "false"}">
    <span class="svc-mark" aria-hidden="true">${on ? "&#10003;" : "+"}</span>
    <span class="svc-name">${esc(name)}</span>
    <span class="svc-state">${on ? "On" : "Off"}</span>
    <span class="svc-x" aria-hidden="true">&times;</span>
  </button>`;
}

function setOn(btn, on) {
  btn.classList.toggle("on", on);
  btn.setAttribute("aria-pressed", on ? "true" : "false");
  btn.querySelector(".svc-mark").innerHTML = on ? "&#10003;" : "+";
  btn.querySelector(".svc-state").textContent = on ? "On" : "Off";
}

/** Make the toggles below `root` work; `onChange(ids)` after each tap. */
export function wireServiceToggles(root, onChange) {
  root.querySelectorAll("button.svc-toggle").forEach(btn => {
    btn.onclick = () => {
      setOn(btn, btn.getAttribute("aria-pressed") !== "true");
      if (onChange) onChange(selectedServiceIds(root));
      // So a form's "needs attention" mark on the group clears, like any other field.
      btn.dispatchEvent(new Event("change", { bubbles: true }));
    };
  });
}

/** The ids of the prayers that are on, below `root`. */
export function selectedServiceIds(root) {
  return [...root.querySelectorAll("button.svc-toggle[aria-pressed=true]")].map(b => Number(b.dataset.svc));
}
