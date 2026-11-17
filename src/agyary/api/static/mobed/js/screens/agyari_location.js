"use strict";

/**
 * "Edit location", from Settings: where the mobed's fire temple is on the map
 * (DECISIONS D10). Any of its approved mobeds or its panthaky can put the pin
 * down or move it; the server checks that again.
 */

import { getAgyaryLocation, putAgyaryLocation } from "../api.js";
import { state, currentAgyary, saveSession } from "../state.js";
import { chrome, mainEl, showFab, showError, showInfo, refreshHeader, loading, screenFailed } from "../ui.js";
import { esc } from "../util.js";
import { navGuard } from "../router.js";
import { mountLocationPicker } from "../location_picker.js";

export async function renderAgyariLocation() {
  chrome(true);
  refreshHeader();
  showFab(false);
  loading();
  const alive = navGuard();
  const agyary = currentAgyary();
  if (!agyary) return screenFailed("You are not at a fire temple yet.");

  let info;
  try {
    info = await getAgyaryLocation(agyary.id);
  } catch (e) {
    if (!alive()) return;
    return screenFailed(e.message, () => renderAgyariLocation());
  }
  if (!alive()) return;
  // What the app keeps for Settings follows what the server has now.
  const kept = (state.user.agyaries || []).find((a) => a.id === agyary.id);
  if (kept) { kept.location = info.location; saveSession(); }

  mainEl.innerHTML = `
    <div class="card">
      <h2>Where is ${esc(info.name)}?</h2>
      <p class="meta">${esc([info.address, info.city].filter(Boolean).join(", "))}</p>
      <p class="meta">Put the pin on the fire temple itself.</p>
      <div id="alPicker"></div>
      <div class="action-bar">
        <button type="button" id="alSave">Save location</button>
      </div>
    </div>`;

  const picker = mountLocationPicker(document.getElementById("alPicker"), {
    initial: info.location,
    suggest: () => [info.name, info.city].filter(Boolean).join(", "),
    tall: true,
  });
  let location = info.location;

  document.getElementById("alSave").onclick = async (ev) => {
    const btn = ev.currentTarget;
    const pin = picker.get();
    if (!pin) {
      return showError("Please put the pin on the fire temple first: tap the map, search, or use “I'm at the agyari now”.");
    }
    if (!picker.moved()) {
      // A town position saved as it is would claim to be the fire temple.
      if (location && location.source === "town") {
        return showError("The pin is still only on the town. Please move it onto the fire temple, then save.");
      }
      return showInfo("The pin has not moved, so there is nothing new to save.");
    }
    btn.disabled = true;   // one save per tap
    try {
      const saved = await putAgyaryLocation(agyary.id, pin.latitude, pin.longitude);
      if (!alive()) return;
      location = saved.location;
      picker.setSaved(location);
      // The fire temple the app keeps for this mobed has its new position too.
      if (kept) { kept.location = location; saveSession(); }
      showInfo("Location saved. The pin is on the fire temple.");
    } catch (e) {
      showError(e.message);
    } finally {
      btn.disabled = false;
    }
  };
}
