"use strict";

/**
 * Adding a behdin - one form, used from every place you might need it:
 * the Behdins screen, the event form, and the menu.
 *
 * Supports importing contacts from the device's contact list via the
 * Contact Picker API (Android Chrome). Falls back to manual entry
 * everywhere else.
 */

import { createBehdin } from "./api.js";
import { state } from "./state.js";
import { showError, showInfo } from "./ui.js";
import { phoneField, readPhone, setPhoneField, splitE164, esc } from "./util.js";

function normalizeContactPhone(raw) {
  const digits = raw.replace(/[\s\-().]/g, "");
  if (digits.startsWith("+")) return digits;
  if (digits.length === 10 && /^[6-9]/.test(digits)) return "+91" + digits;
  return "+" + digits.replace(/^0+/, "");
}

function canPickContacts() {
  return "contacts" in navigator && "ContactsManager" in window;
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
        <label>Name</label>
        <input type="text" id="abName" placeholder="e.g. Behdin Jaidev Mistry"
               autocomplete="off" value="${esc(pf.name || "")}">
      </div>
      <label>WhatsApp number</label>
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

  // --- Contact Picker ---
  if (canPickContacts()) {
    document.getElementById("abImport").onclick = async () => {
      let contacts;
      try {
        contacts = await navigator.contacts.select(
          ["name", "tel"], { multiple: true }
        );
      } catch (e) {
        return; // user cancelled the picker
      }
      if (!contacts || !contacts.length) return;

      if (contacts.length === 1) {
        const c = contacts[0];
        const name = (c.name && c.name[0]) || "";
        const phone = (c.tel && c.tel[0]) || "";
        document.getElementById("abName").value = name;
        if (phone) {
          const norm = normalizeContactPhone(phone);
          setPhoneField("abPhone", norm);
        }
        return;
      }

      // Multiple contacts: batch-create, skip duplicates
      const btn = document.getElementById("abImport");
      btn.disabled = true;
      btn.textContent = "Importing...";
      let added = 0, skipped = 0, last = null;
      for (const c of contacts) {
        const name = (c.name && c.name[0]) || "";
        const rawPhone = (c.tel && c.tel[0]) || "";
        if (!name || !rawPhone) { skipped++; continue; }
        const phone = normalizeContactPhone(rawPhone);
        const { local } = splitE164(phone);
        if (local.length < 4) { skipped++; continue; }
        try {
          const result = await createBehdin(state.currentAgyaryId, name, phone);
          if (result.created) { added++; } else { skipped++; }
          last = result;
        } catch (e) {
          skipped++;
        }
      }
      const msg = added
        ? `${added} behdin${added > 1 ? "s" : ""} added` +
          (skipped ? `, ${skipped} already existed` : "")
        : "All contacts were already on file";
      showInfo(msg);
      container.innerHTML = "";
      if (last && onCreated) onCreated(last);
    };
  }

  // --- Manual submit ---
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
  container.querySelectorAll("input").forEach(el => {
    el.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); submit(); } };
  });
}
