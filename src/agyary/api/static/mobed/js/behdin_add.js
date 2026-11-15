"use strict";

/**
 * Adding a behdin, and reading one from the phone's own contacts.
 *
 * "Import from contacts" belongs only where a name and number are asked
 * for: this compact form (which the event and machi search opens when it
 * finds nobody) and the full Add behdin page. pickContacts opens the
 * device's contact list through the Contact Picker API (Chrome on Android,
 * so the Play Store app too). Where the browser has none (an iPhone, a
 * computer) the button is not drawn, and the name and number are typed.
 */

import { createBehdin } from "./api.js";
import { state } from "./state.js";
import { showError, showInfo } from "./ui.js";
import { phoneField, readPhone, setPhoneField, splitE164, esc } from "./util.js";

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

/** Nothing back sooner than this means the list never opened: a person takes
 *  longer than a second to see it and back out of it. */
export const TOO_QUICK_MS = 1000;

export const CONTACTS_DID_NOT_OPEN =
  "If your contact list did not open, Chrome may not be allowed to read contacts. " +
  "On the phone, open Settings, then Apps, Chrome, Permissions, Contacts, and choose Allow. Then try again.";

/**
 * Open the phone's contact list and hand back what was picked, normalised,
 * as [{name, phone}]. Either may be "" when the contact has none.
 *
 * It never fails silently. A web page cannot ask for the contacts
 * permission itself: Chrome asks Android when the list is opened. So:
 *   - the phone refusing to open the list rejects (MDN: InvalidStateError
 *     "if launching a contact picker failed"), and that is said on screen
 *     with the browser's own words, so the reason can be read off the phone;
 *   - an empty answer is the mobed backing out - unless it came back at once,
 *     which is the list never opening (Chrome without the permission), and
 *     then where to allow it is said.
 * Returns [] in all of those cases.
 */
export async function pickContacts({ multiple = true } = {}) {
  if (!canPickContacts()) return [];
  const asked = Date.now();
  let picked;
  try {
    picked = await navigator.contacts.select(["name", "tel"], { multiple });
  } catch (e) {
    console.error("Contact picker refused:", e);
    const why = [e && e.name, e && e.message].filter(Boolean).join(": ") || String(e);
    showError(`Your contacts could not be opened (${why}). Please type the name and number instead.`);
    return [];
  }
  if (!picked || !picked.length) {
    if (Date.now() - asked < TOO_QUICK_MS) showInfo(CONTACTS_DID_NOT_OPEN);
    return [];
  }
  return picked.map(c => ({
    name: ((c.name && c.name[0]) || "").trim(),
    phone: bestNumber(c.tel),
  })).filter(c => c.name || c.phone);
}

/** One contact read into a name-and-number form, saying what it lacked. */
export function fillFromContact(contact, { nameId, phoneId }) {
  if (contact.name) document.getElementById(nameId).value = contact.name;
  if (contact.phone) setPhoneField(phoneId, contact.phone);
  if (!contact.phone) showInfo("That contact has no phone number. Please type it in.");
  else if (!contact.name) showInfo("That contact has no name. Please type it in.");
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
      ${canPickContacts() ? `
        <button class="secondary" id="abImport" style="margin-bottom:12px">
          Import from contacts
        </button>` : ""}
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

  document.getElementById("abCancel").onclick = () => {
    container.innerHTML = "";
    if (onCancel) onCancel();
  };

  if (canPickContacts()) {
    document.getElementById("abImport").onclick = async () => {
      // One contact: this form is for the one behdin being booked.
      const [contact] = await pickContacts({ multiple: false });
      if (!contact) return;
      // A caller may hide the name row while its search box stands in for
      // the name. The contact's own name is shown here, to be checked
      // before saving - an address book's "Zubin Plumber" is seldom the
      // name wanted on a slip.
      const row = document.getElementById("abNameRow");
      if (row && contact.name) row.style.display = "";
      fillFromContact(contact, { nameId: "abName", phoneId: "abPhone" });
    };
  }

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
