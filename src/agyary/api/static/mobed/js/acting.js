"use strict";

/**
 * The admin acting for one Doongerwadi or prayer hall ("Act for this place",
 * owner, 18 Nov 2026): the manager's own screens, at #/admin/act/<placeId>/...,
 * for that place, so the owner can show and try the whole of it without a
 * manager's account. main.js sets state.actFor from the address (admins only),
 * api.js adds it to every manager call, and the server checks both again.
 * Everything done here is the place's: its managers see it too.
 */

import { state } from "./state.js";
import { mainEl } from "./ui.js";
import { esc } from "./util.js";
import { navigate } from "./router.js";

/** A manager's screen's address: #/manager/... for a manager, and the same
 *  screen under #/admin/act/<placeId> for the admin acting for that place. */
export function managerHash(rest = "") {
  return state.actFor ? `#/admin/act/${state.actFor}${rest}` : `#/manager${rest}`;
}

/** The place the admin acts for, once known. */
export function actPlace() {
  return state.actFor && state.actPlace && state.actPlace.id === state.actFor ? state.actPlace : null;
}

/** The places the manager's screens are for: the manager's own, or the one
 *  the admin acts for. */
export function managerPlaces() {
  if (state.actFor) return actPlace() ? [actPlace()] : [];
  return (state.user && state.user.funeral_places) || [];
}

/** The strip above every screen while acting, with the way back; gone otherwise. */
export function paintActBanner() {
  let bar = document.getElementById("actBar");
  if (!state.actFor) {
    if (bar) bar.remove();
    return;
  }
  if (!bar) {
    bar = document.createElement("div");
    bar.id = "actBar";
    bar.className = "act-bar no-print";
    bar.setAttribute("role", "status");
    mainEl.parentNode.insertBefore(bar, mainEl);
  }
  const place = actPlace();
  bar.innerHTML = `<span>You are acting for <b>${esc(place ? place.name : "this place")}</b> as admin</span>
    <button type="button" class="small secondary" data-back>Back to Admin</button>`;
  bar.querySelector("[data-back]").onclick = () => navigate("#/admin/funeral-places");
}
