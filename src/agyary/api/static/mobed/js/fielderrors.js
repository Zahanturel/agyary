"use strict";

/**
 * Show what is wrong on the field itself, not in one line at the top.
 *
 * A form's check returns a list of problems - { target, message } - where
 * `target` is the control (or the group of controls) that needs attention.
 * `flagProblems` outlines each target, puts the message right under it, brings
 * the first one into view and focuses it. A flag clears the moment its target is
 * touched, so nothing stays red once it is dealt with.
 *
 * It only decorates the page: it never changes a form's layout, state or
 * values, so a form can adopt it one check at a time.
 */

import { showError } from "./ui.js";

const MSG = "field-msg";

/** Remove every flag below `root`. */
export function clearProblems(root) {
  root.querySelectorAll("." + MSG).forEach(el => el.remove());
  root.querySelectorAll(".has-error").forEach(el => el.classList.remove("has-error"));
}

function resolve(root, target) {
  if (!target) return null;
  return typeof target === "string" ? root.querySelector(target) : target;
}

/**
 * Flag `problems` ([{ target, message }]) under `root`. Returns true when
 * anything was flagged. Problems whose target cannot be found are shown in the
 * top banner instead, so a message is never lost.
 */
export function flagProblems(root, problems) {
  clearProblems(root);
  const flagged = [];
  const stray = [];
  for (const p of problems) {
    const el = resolve(root, p.target);
    if (!el) { stray.push(p.message); continue; }
    if (flagged.some(f => f.el === el)) continue;   // one message per target
    el.classList.add("has-error");
    const msg = document.createElement("div");
    msg.className = MSG;
    msg.setAttribute("role", "alert");
    msg.textContent = p.message;
    el.insertAdjacentElement("afterend", msg);
    const clear = () => {
      el.classList.remove("has-error");
      msg.remove();
      el.removeEventListener("input", clear);
      el.removeEventListener("change", clear);
    };
    el.addEventListener("input", clear);
    el.addEventListener("change", clear);
    flagged.push({ el, msg });
  }
  if (stray.length) showError(stray[0]);
  else if (flagged.length > 1) showError(`${flagged.length} things need attention - they are marked below.`);
  if (flagged.length) {
    const first = flagged[0].el;
    first.scrollIntoView({ block: "center", behavior: "smooth" });
    const focusable = first.matches("input,select,textarea,button") ? first
      : first.querySelector("input,select,textarea,button");
    if (focusable) focusable.focus({ preventScroll: true });
  }
  return flagged.length > 0 || stray.length > 0;
}
