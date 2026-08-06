"use strict";

/**
 * Adding a behdin - one form, used from every place you might need it:
 * the Behdins screen (button and FAB) and step 1 of New Event.
 *
 * It lives on its own because "add a behdin" is not a management action.
 * Any member of the fire temple can do it - the API asks only for
 * membership - and the mobed taking a walk-in at the counter is the most
 * likely person to need it. An earlier version of this screen hid the
 * button behind the panthaky/caretaker check, which left an ordinary
 * mobed with no way to add anyone from the Behdins screen at all.
 */

import { createBehdin } from "./api.js";
import { state } from "./state.js";
import { showError, showInfo } from "./ui.js";
import { phoneField, readPhone } from "./util.js";

/**
 * Render the add form into `container`.
 *   onCreated(behdin) - {id, name, phone, created}
 *   onCancel()        - optional
 */
export function renderAddBehdin(container, { onCreated, onCancel } = {}) {
  container.innerHTML = `
    <div class="card" style="margin-top:12px">
      <h2>New behdin</h2>
      <label>Name</label>
      <input type="text" id="abName" placeholder="e.g. Behdin Jaidev Mistry" autocomplete="off">
      <label>WhatsApp number</label>
      ${phoneField("abPhone")}
      <div class="row tight" style="margin-top:12px">
        <button class="small" id="abSave">Add behdin</button>
        <button class="ghost small" id="abCancel">Cancel</button>
      </div>
    </div>`;

  const nameEl = document.getElementById("abName");
  nameEl.focus();

  document.getElementById("abCancel").onclick = () => {
    container.innerHTML = "";
    if (onCancel) onCancel();
  };

  const submit = async () => {
    const name = nameEl.value.trim();
    const phone = readPhone("abPhone");
    if (!name) return showError("Please enter the behdin's name.");
    if (!phone) return showError("Please enter a valid phone number.");

    const btn = document.getElementById("abSave");
    btn.disabled = true;
    try {
      const created = await createBehdin(state.currentAgyaryId, name, phone);
      if (!created.created) {
        // Phone is the identity, so an existing number resolves to that
        // person rather than making a second record. Say so - silently
        // showing a different name than the one just typed is worse.
        showInfo(`${created.name} is already on file - opening their record.`);
      }
      container.innerHTML = "";
      if (onCreated) onCreated(created);
    } catch (e) {
      btn.disabled = false;
      showError(e.message);
    }
  };

  document.getElementById("abSave").onclick = submit;
  // Enter anywhere in the little form submits it.
  container.querySelectorAll("input").forEach(el => {
    el.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); submit(); } };
  });
}
