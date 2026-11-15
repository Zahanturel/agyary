"use strict";

/**
 * Adding a behdin, and reading one from the phone's own contacts.
 *
 * renderAddBehdin is the compact form the event and machi forms open when a
 * search finds nobody. pickContacts reads the device's contact list through
 * the Contact Picker API (Chrome on Android, so the Play Store app too), and
 * chooseFromContacts is the "Import from contacts" button on their first step.
 * Where the browser has no picker (an iPhone, a computer) the button is not
 * drawn: a web page has no other way to read the contact list there, and the
 * name and number are typed as before.
 */

import { createBehdin, listBehdins } from "./api.js";
import { state } from "./state.js";
import { showError, showInfo } from "./ui.js";
import { phoneField, readPhone, splitE164, esc } from "./util.js";

const E164 = /^\+[1-9]\d{7,14}$/;
const INDIAN_MOBILE = /^\+91[6-9]\d{9}$/;

/**
 * A contact's number in the one shape the server stores. Address books keep
 * numbers however they were typed - "98200 12345", "098200-12345",
 * "0091 98200 12345", "+91 (0)98200 12345" - and all four are the same
 * person. A number with no country code is taken as Indian, the default
 * everywhere else in the app. The trunk 0 is dropped rather than read as part
 * of the number: "09820012345" is +91 98200 12345, not a number in Iran (+98).
 */
export function normalizeContactPhone(raw) {
  let d = String(raw || "").replace(/[^\d+]/g, "");
  if (d.startsWith("+")) d = d.slice(1).replace(/\+/g, "");
  else if (d.startsWith("00")) d = d.slice(2);
  else {
    d = d.replace(/\+/g, "").replace(/^0+/, "");
    if (d.length === 10) d = "91" + d;
  }
  if (!d) return "";
  // A trunk 0 written after the country code ("+91 098...") goes as well.
  const { cc, local } = splitE164(d);
  return d.startsWith(cc) ? "+" + cc + local.replace(/^0+/, "") : "+" + d;
}

/** Of a contact's numbers, the one WhatsApp is likeliest to be on: an Indian
 *  mobile over the landline listed first, else the first that is a number. */
function bestNumber(tels) {
  const numbers = (tels || []).map(normalizeContactPhone).filter(p => E164.test(p));
  return numbers.find(p => INDIAN_MOBILE.test(p)) || numbers[0] || "";
}

export function canPickContacts() {
  return "contacts" in navigator && "ContactsManager" in window;
}

/**
 * Read contacts from the device and hand them back normalised, as
 * [{name, phone}]. Either may be "" when the contact has none; a caller
 * adding several at once skips those. Returns [] if the picker is
 * unavailable or the mobed cancelled, so "nothing to do" and "said no" are
 * the same to the caller.
 */
export async function pickContacts({ multiple = true } = {}) {
  if (!canPickContacts()) return [];
  let picked;
  try {
    picked = await navigator.contacts.select(["name", "tel"], { multiple });
  } catch (e) {
    return [];   // cancelled
  }
  return (picked || []).map(c => ({
    name: ((c.name && c.name[0]) || "").trim(),
    phone: bestNumber(c.tel),
  })).filter(c => c.name || c.phone);
}

/**
 * "Import from contacts" on the first step of a new event or machi. One
 * contact: if their number is already on file, they are the behdin and the
 * form moves on in the same tap. Someone new opens the add form in `panel`
 * filled in from the contact, because the name in an address book ("Zubin
 * Plumber", "Kaka") is seldom the one wanted on a slip, so it is shown for
 * checking before anybody is saved.
 *
 * Returns "chosen", "form", or null when nothing was picked.
 */
export async function chooseFromContacts(panel, { onChosen, onCancel } = {}) {
  const [contact] = await pickContacts({ multiple: false });
  if (!contact) return null;
  if (contact.phone) {
    let onFile = [];
    try {
      onFile = await listBehdins(state.currentAgyaryId, contact.phone);
    } catch (e) {
      // Not found is not proven - the form below still links an existing
      // number to its record when saved.
    }
    const match = onFile.find(m => m.phone === contact.phone);
    if (match) {
      // After the form has moved on, or redrawing it wipes the note - and
      // the note matters: the name on file may not be the contact's.
      await onChosen(match);
      showInfo(`${match.name} is already on file.`);
      return "chosen";
    }
  }
  renderAddBehdin(panel, { prefill: contact, onCreated: onChosen, onCancel });
  if (!contact.phone) showInfo("That contact has no phone number. Please type it in.");
  else if (!contact.name) showInfo("That contact has no name. Please type it in.");
  return "form";
}

/**
 * Render the add form into `container`.
 *   onCreated(behdin) - {id, name, phone, created}
 *   onCancel()        - optional
 *   prefill           - optional {name, phone} to pre-fill fields
 */
export function renderAddBehdin(container, { onCreated, onCancel, prefill } = {}) {
  const pf = prefill || {};

  container.innerHTML = `
    <div class="card" style="margin-top:12px">
      <h2>New behdin</h2>
      <div id="abNameRow">
        <label for="abName">Name</label>
        <input type="text" id="abName" placeholder="e.g. Behdin Zubin Mistry"
               autocomplete="off" value="${esc(pf.name || "")}">
      </div>
      <label for="abPhone">WhatsApp number</label>
      ${phoneField("abPhone", pf.phone || "")}
      <div class="row tight" style="margin-top:12px">
        <button class="small" id="abSave">Add behdin</button>
        <button class="ghost small" id="abCancel">Cancel</button>
      </div>
    </div>`;

  const nameEl = document.getElementById("abName");
  if (!pf.name) nameEl.focus();
  else if (!pf.phone) document.getElementById("abPhone").focus();

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
      container.innerHTML = "";
      if (onCreated) await onCreated(created);
      // Said after the caller has redrawn, which would otherwise wipe it.
      if (!created.created) showInfo(`${created.name} is already on file.`);
    } catch (e) {
      btn.disabled = false;
      showError(e.message);
    }
  };

  document.getElementById("abSave").onclick = submit;
  container.querySelectorAll("input").forEach(el => {
    el.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); submit(); } };
  });
}
