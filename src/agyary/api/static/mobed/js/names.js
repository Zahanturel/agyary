"use strict";

/**
 * The pair + farmayeshne name editor, built once and used by both the New
 * Event wizard (step 5) and the Behdin detail screen's saved-name pool.
 *
 * Shapes it produces match what the API takes in both places:
 *   { section: "pair"|"farmayeshne", title, name, status, pair_group }
 *
 * Two rules the UI enforces because the data means something:
 *   - a pair is exactly two people, so pair rows come in twos and share a
 *     pair_group. The backend refuses a half-pair outright;
 *   - Patet is one departed pair by definition, so that case renders a
 *     single fixed pair with no add or remove.
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
 *  render there and do nothing at all when clicked. */
function pairCard(status, m1, m2, removable = true) {
  return `<div class="pair-card" data-status="${status}">
    <div class="phead"><span class="ptitle">Pair</span>
      ${removable ? '<button type="button" class="rm" title="Remove pair">&times;</button>' : ""}</div>
    ${memberRow(m1)}${memberRow(m2)}</div>`;
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
    region.querySelector("#addSingle").onclick = () => box.insertAdjacentHTML("beforeend", singleRow(null));

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
    region.querySelector("#addPair").onclick = () => addPair(null);
    region.querySelector("#addFarm").onclick = () => farmBox.insertAdjacentHTML("beforeend", singleRow(null));
  }

  // Delegated remove for singles and (service) pair cards.
  region.onclick = (e) => {
    const btn = e.target.closest("button.rm");
    if (!btn) return;
    const card = btn.closest(".pair-card");
    if (card) card.remove();
    else {
      const row = btn.closest(".name-row");
      if (row) row.remove();
    }
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
