"use strict";

/**
 * Finding and claiming a fire temple. Unchanged in substance from the
 * previous build - "fire temple" rather than "agyari" in every visible
 * string, because the seed list and real search results are Adarians,
 * Atash Behrams, Dadgahs and prayer halls at least as often as agyaris
 * proper.
 */

import { searchAgyaries, joinAgyary, activateAgyary, createAgyary } from "../api.js";
import { state } from "../state.js";
import { chrome, mainEl, showError } from "../ui.js";
import { esc, phoneField, readOptionalPhone } from "../util.js";
import { navigate } from "../router.js";
import { refreshHeader } from "../ui.js";

export function renderOnboarding() {
  chrome(false);
  mainEl.innerHTML = `
    <div class="card">
      <h2>Which fire temple do you work at?</h2>
      <p class="meta">Search by name or city, then select it below.</p>
      <input type="text" id="agySearch" placeholder="Start typing..." autocomplete="off">
      <div id="agyResults" style="margin-top:8px"></div>
    </div>`;

  const input = document.getElementById("agySearch");
  const results = document.getElementById("agyResults");
  let timer, token = 0;

  const run = async () => {
    const q = input.value.trim();
    if (!q) { results.innerHTML = ""; return; }
    const mine = ++token;
    let list = [];
    try { list = await searchAgyaries(q); } catch (e) { return showError(e.message); }
    if (mine !== token) return;   // a newer keystroke already superseded this

    results.innerHTML = "";
    for (const a of list) {
      const row = document.createElement("div");
      row.className = "search-result";
      const badge = a.status === "unclaimed" ? '<span class="tag grey">not set up yet</span>' : "";
      row.innerHTML = `<div><strong>${esc(a.name)}</strong> ${badge}</div>
        <div class="addr">${esc([a.address, a.city].filter(Boolean).join(", "))}</div>`;
      row.onclick = () => pick(a);
      results.appendChild(row);
    }
    // One "create" prompt, worded for whichever case actually happened.
    const create = document.createElement("div");
    if (list.length) {
      create.className = "meta";
      create.style.marginTop = "8px";
      create.innerHTML = `Not here? <a href="#" id="createInline">Add "${esc(q)}" as a new fire temple</a>`;
    } else {
      create.className = "search-result";
      create.style.borderStyle = "dashed";
      create.innerHTML = `<strong>No fire temple found.</strong>
        <div class="addr">Tap to add "${esc(q)}" as a new fire temple.</div>`;
    }
    create.onclick = (e) => { e.preventDefault(); renderCreate(q); };
    results.appendChild(create);
  };
  input.oninput = () => { clearTimeout(timer); timer = setTimeout(run, 150); };
}

async function pick(a) {
  try {
    const res = await joinAgyary(a.id);
    state.user = res.user;
    state.currentAgyaryId = a.id;
    // An unclaimed seed entry still has 2012-era details nobody has
    // vouched for - confirm them before it goes live.
    if (a.status === "unclaimed") renderActivate(a);
    else { refreshHeader(); navigate("#/calendar"); }
  } catch (e) {
    showError(e.message);
  }
}

function renderActivate(a) {
  chrome(false);
  mainEl.innerHTML = `
    <div class="card">
      <h2>Set up ${esc(a.name)}</h2>
      <p class="meta">Please confirm or correct these details before this fire temple goes live.</p>
      <label>Name</label><input type="text" id="acName" value="${esc(a.name)}">
      <label>City</label><input type="text" id="acCity" value="${esc(a.city || "")}">
      <label>Address</label><input type="text" id="acAddr" value="${esc(a.address || "")}">
      <label>Contact phone (optional)</label>${phoneField("acPhone")}
      <div style="margin-top:14px"><button id="acGo">Confirm &amp; activate</button></div>
    </div>`;
  document.getElementById("acGo").onclick = async () => {
    const phoneRes = readOptionalPhone("acPhone");
    if (!phoneRes.ok) return showError("Please enter a valid phone number, or leave it blank.");
    const body = {
      name: document.getElementById("acName").value.trim(),
      city: document.getElementById("acCity").value.trim(),
      address: document.getElementById("acAddr").value.trim() || null,
      contact_phone: phoneRes.value,
    };
    if (!body.name || !body.city) return showError("Name and city are required.");
    try {
      const res = await activateAgyary(a.id, body);
      state.user = res.user;
      state.currentAgyaryId = a.id;
      refreshHeader();
      navigate("#/calendar");
    } catch (e) {
      showError(e.message);
    }
  };
}

function renderCreate(prefillName) {
  chrome(false);
  mainEl.innerHTML = `
    <div class="card">
      <h2>Add a new fire temple</h2>
      <p class="meta">Enter its details - it will be set up and ready to use.</p>
      <label>Name</label><input type="text" id="crName" value="${esc(prefillName || "")}">
      <label>City</label><input type="text" id="crCity">
      <label>Address</label><input type="text" id="crAddr">
      <label>Contact phone (optional)</label>${phoneField("crPhone")}
      <div style="margin-top:14px" class="row tight">
        <button id="crGo">Create</button>
        <button class="ghost" id="crBack">Back to search</button></div>
    </div>`;
  document.getElementById("crBack").onclick = () => renderOnboarding();
  document.getElementById("crGo").onclick = async () => {
    const phoneRes = readOptionalPhone("crPhone");
    if (!phoneRes.ok) return showError("Please enter a valid phone number, or leave it blank.");
    const body = {
      name: document.getElementById("crName").value.trim(),
      city: document.getElementById("crCity").value.trim(),
      address: document.getElementById("crAddr").value.trim() || null,
      contact_phone: phoneRes.value,
    };
    if (!body.name || !body.city) return showError("Name and city are required.");
    try {
      const res = await createAgyary(body);
      state.user = res.user;
      state.currentAgyaryId = res.agyary.id;
      refreshHeader();
      navigate("#/calendar");
    } catch (e) {
      showError(e.message);
    }
  };
}
