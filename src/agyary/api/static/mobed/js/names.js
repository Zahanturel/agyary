"use strict";

/**
 * The pair + farmayeshne name editor, built once and used by both the New
 * Event wizard (step 5) and the Behdin detail screen's saved-name pool.
 *
 * Shapes it produces match what the API takes in both places:
 *   { section: "pair"|"farmayeshne", title, name, status, pair_group }
 *
 * Rules the UI enforces because the data means something:
 *   - a pair is exactly two people, so pair rows come in twos and share a
 *     pair_group. The backend refuses a half-pair outright;
 *   - Patet is one departed pair by definition, so that case renders a
 *     single fixed pair with no add, remove or reorder;
 *   - pairs are reorderable as units (the first pair is prayed first) and the
 *     two names inside a pair are not; single names are only added or removed.
 *
 * The order on screen IS the order that is saved: collectNames reads the DOM
 * top to bottom and numbers the groups in that order.
 */

import { esc } from "./util.js";
import { NAME_TITLES, TITLE_DISPLAY } from "./state.js";

function titleSelect(sel) {
  return `<select class="t">${NAME_TITLES.map(t =>
    `<option value="${t}" ${t === sel ? "selected" : ""}>${TITLE_DISPLAY[t]}</option>`).join("")}</select>`;
}

/** One half of a pair - no remove button; a pair is two people, and
 *  removing one of them is what the pair-level remove is for. */
function memberRow(n) {
  return `<div class="name-row">${titleSelect(n && n.title)}
    <input class="nm" placeholder="e.g. Zahan" value="${esc(n ? n.name : "")}"></div>`;
}

function singleRow(n) {
  return `<div class="name-row">${titleSelect(n && n.title)}
    <input class="nm" placeholder="e.g. Zahan" value="${esc(n ? n.name : "")}">
    <button type="button" class="rm" title="Remove">&times;</button></div>`;
}

/** `removable` is false for Patet's single fixed pair - the button used to
 *  render there and do nothing at all when clicked. It also means there is
 *  nothing to reorder. The drag handle is the touch/mouse affordance; the
 *  up/down buttons are the one that always works (keyboard, screen readers,
 *  and any browser where a drag misbehaves). */
function pairCard(status, m1, m2, removable = true) {
  return `<div class="pair-card" data-status="${status}">
    <div class="phead"><span class="ptitle">Pair</span>
      ${removable ? `<span class="pctl">
        <button type="button" class="mv up" title="Move up" aria-label="Move pair up">&#9650;</button>
        <button type="button" class="mv dn" title="Move down" aria-label="Move pair down">&#9660;</button>
        <span class="drag" title="Drag to reorder" aria-label="Drag to reorder">&#8942;&#8942;</span>
        <button type="button" class="rm" title="Remove pair">&times;</button></span>` : ""}</div>
    ${memberRow(m1)}${memberRow(m2)}</div>`;
}

/** Tell whoever is watching (the review screen redraws its slip) that the
 *  names changed by something other than typing - typing already fires
 *  `input`. */
function notify(el) {
  el.dispatchEvent(new CustomEvent("names-changed", { bubbles: true }));
}

/** Enable/disable the move buttons to match where each pair now sits. */
function refreshPairControls(box) {
  if (!box) return;
  const cards = [...box.querySelectorAll(".pair-card")];
  cards.forEach((card, i) => {
    const up = card.querySelector("button.up"), dn = card.querySelector("button.dn");
    if (up) up.disabled = i === 0;
    if (dn) dn.disabled = i === cards.length - 1;
  });
}

/** Drag a pair by its handle. Pointer events, not HTML5 drag-and-drop: the
 *  latter does not fire on touch screens, which is where this is used.
 *  `touch-action: none` on the handle (see app.css) is what stops the page
 *  scrolling under the finger while it is held; the rest of the card still
 *  scrolls normally. */
function wireDrag(box) {
  box.addEventListener("pointerdown", (e) => {
    const handle = e.target.closest(".drag");
    if (!handle || !box.contains(handle)) return;
    const card = handle.closest(".pair-card");
    e.preventDefault();
    // Capture keeps the events coming if the finger leaves the handle; the
    // listeners below are on the document anyway, so a browser that refuses
    // capture still drags.
    try { handle.setPointerCapture(e.pointerId); } catch (err) { /* not fatal */ }
    card.classList.add("dragging");

    const onMove = (ev) => {
      // Near the top/bottom edge, keep the page moving so a long list can be
      // dragged across more than one screen.
      if (ev.clientY < 70) window.scrollBy(0, -12);
      else if (ev.clientY > window.innerHeight - 70) window.scrollBy(0, 12);

      const others = [...box.querySelectorAll(".pair-card")].filter(c => c !== card);
      const before = others.find(c => {
        const r = c.getBoundingClientRect();
        return ev.clientY < r.top + r.height / 2;
      });
      if (before) { if (card.nextElementSibling !== before) box.insertBefore(card, before); }
      else if (box.lastElementChild !== card) box.appendChild(card);
    };
    const end = () => {
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerup", end);
      document.removeEventListener("pointercancel", end);
      card.classList.remove("dragging");
      refreshPairControls(box);
      notify(box);
    };
    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerup", end);
    document.addEventListener("pointercancel", end);
  });
}

/** Rebuild pair groupings from a flat row list (edit / prefill). */
export function groupPairs(names) {
  const byGroup = {};
  names.filter(n => n.section === "pair" && n.pair_group != null)
    .forEach(n => { (byGroup[n.pair_group] = byGroup[n.pair_group] || []).push(n); });
  return Object.values(byGroup);
}

/**
 * Render the editor into `region`.
 *   isMachi  - machi ceremonies have their own two shapes
 *   purpose  - patet | tandarosti | gujrela_nu | khushali_nu | hama_anjuman
 *   existing - flat rows to prefill from
 */
export function renderNamesEditor(region, isMachi, purpose, existing) {
  const names = existing || [];

  if (isMachi && purpose === "tandarosti") {
    // Living names, one per line. These are stored as 'farmayeshne' - they
    // are the living family the machi is for, which is what that section
    // means, and is how the saved-name pool has always held them.
    const singles = names.filter(n => n.section === "farmayeshne" || n.pair_group == null);
    region.innerHTML = `<div class="names-group-label"><b>Living names</b><span>one name per line</span></div>
      <div id="fSingles"></div>
      <button class="secondary small" id="addSingle" type="button">+ Add name</button>`;
    const box = region.querySelector("#fSingles");
    (singles.length ? singles : [null]).forEach(n => box.insertAdjacentHTML("beforeend", singleRow(n)));
    region.querySelector("#addSingle").onclick = () => { box.insertAdjacentHTML("beforeend", singleRow(null)); notify(region); };

  } else if (isMachi) {
    // Patet: exactly one departed pair, fixed. No add, no remove.
    const pair = groupPairs(names)[0] || [];
    region.innerHTML = `<div class="names-group-label"><b>Departed pair</b><span>two names</span></div>
      <div id="fPairs">${pairCard("departed", pair[0], pair[1], false)}</div>`;

  } else {
    // Services: pairs (departed or living, per purpose) + farmayeshne singles.
    const pairs = groupPairs(names);
    const farm = names.filter(n => n.section === "farmayeshne");
    const defStatus = purpose === "gujrela_nu" ? "departed" : "living";
    region.innerHTML = `
      <div class="names-group-label"><b>Pairs</b><span>two names per pair</span></div>
      <div id="fPairs"></div>
      <button class="secondary small" id="addPair" type="button">+ Add pair</button>
      <div class="names-group-label"><b>Farmayeshne</b><span>one name per line</span></div>
      <div id="fFarm"></div>
      <button class="secondary small" id="addFarm" type="button">+ Add name</button>`;
    const pairsBox = region.querySelector("#fPairs");
    const farmBox = region.querySelector("#fFarm");
    const addPair = (members) => {
      const st = members && members[0] ? members[0].status : defStatus;
      pairsBox.insertAdjacentHTML("beforeend", pairCard(st, members && members[0], members && members[1]));
    };
    (pairs.length ? pairs : [null]).forEach(addPair);
    (farm.length ? farm : [null]).forEach(n => farmBox.insertAdjacentHTML("beforeend", singleRow(n)));
    region.querySelector("#addPair").onclick = () => { addPair(null); refreshPairControls(pairsBox); notify(region); };
    wireDrag(pairsBox);
    refreshPairControls(pairsBox);
    region.querySelector("#addFarm").onclick = () => { farmBox.insertAdjacentHTML("beforeend", singleRow(null)); notify(region); };
  }

  // Delegated remove for singles and (service) pair cards, and the move
  // buttons on pair cards.
  region.onclick = (e) => {
    const mv = e.target.closest("button.mv");
    if (mv) {
      const card = mv.closest(".pair-card");
      const box = card.parentElement;
      if (mv.classList.contains("up") && card.previousElementSibling) box.insertBefore(card, card.previousElementSibling);
      else if (mv.classList.contains("dn") && card.nextElementSibling) box.insertBefore(card.nextElementSibling, card);
      refreshPairControls(box);
      notify(region);
      return;
    }
    const btn = e.target.closest("button.rm");
    if (!btn) return;
    const card = btn.closest(".pair-card");
    if (card) {
      const box = card.parentElement;
      card.remove();
      refreshPairControls(box);
    } else {
      const row = btn.closest(".name-row");
      if (row) row.remove();
    }
    notify(region);
  };
}

function readMember(row) {
  const name = row.querySelector(".nm").value.trim();
  return name ? { title: row.querySelector(".t").value, name } : null;
}

/** Read the editor back out as API-shaped rows. */
export function collectNames(region, isMachi, purpose) {
  const out = [];
  let group = 0;

  if (isMachi && purpose === "tandarosti") {
    region.querySelectorAll("#fSingles .name-row").forEach(row => {
      const m = readMember(row);
      if (m) out.push({ section: "farmayeshne", title: m.title, name: m.name, status: "living", pair_group: null });
    });
    return out;
  }

  if (isMachi) {
    region.querySelectorAll("#fPairs .pair-card").forEach(card => {
      group++;
      card.querySelectorAll(".name-row").forEach(row => {
        const m = readMember(row);
        if (m) out.push({ section: "pair", title: m.title, name: m.name, status: "departed", pair_group: group });
      });
    });
    return out;
  }

  region.querySelectorAll("#fPairs .pair-card").forEach(card => {
    const members = [];
    card.querySelectorAll(".name-row").forEach(row => { const m = readMember(row); if (m) members.push(m); });
    if (!members.length) return;
    group++;
    const st = card.dataset.status || "departed";
    members.forEach(m => out.push({ section: "pair", title: m.title, name: m.name, status: st, pair_group: group }));
  });
  region.querySelectorAll("#fFarm .name-row").forEach(row => {
    const m = readMember(row);
    if (m) out.push({ section: "farmayeshne", title: m.title, name: m.name, status: "living", pair_group: null });
  });
  return out;
}

/**
 * Client-side check matching the server's. Worth doing here because the
 * server's refusal of a half-pair is a 400 with the whole form's work in
 * it, and because a lone pair name that DID save would be silently dropped
 * from the behdin's options later rather than erroring.
 */
export function validateNames(rows) {
  const groups = {};
  for (const n of rows.filter(r => r.section === "pair")) {
    if (n.pair_group == null) return "Every pair name needs a partner.";
    (groups[n.pair_group] = groups[n.pair_group] || []).push(n);
  }
  for (const members of Object.values(groups)) {
    if (members.length !== 2) return "A pair is exactly two names - fill both, or remove the pair.";
    if (members[0].status !== members[1].status) return "Both names in a pair must be living, or both departed.";
  }
  return null;
}
