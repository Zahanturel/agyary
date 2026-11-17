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
import { chrome, mainEl, showError, toTop, openSheet } from "../ui.js";
import { esc, phoneField, readOptionalPhone } from "../util.js";
import { navigate } from "../router.js";
import { refreshHeader } from "../ui.js";
import { flagProblems } from "../fielderrors.js";
import { mountLocationPicker } from "../location_picker.js";

/**
 * The fire temple's details as typed into the set-up or the new-temple form
 * (`p` is "ac" or "cr", the start of that form's ids) - or null after marking
 * what is missing on the fields themselves, each where it is, together with
 * any `more` problems the form found itself.
 */
function readDetails(p, more = []) {
  const el = (name) => document.getElementById(p + name);
  const phoneRes = readOptionalPhone(p + "Phone");
  const body = {
    name: el("Name").value.trim(),
    city: el("City").value.trim(),
    address: el("Addr").value.trim() || null,
    contact_phone: phoneRes.value,
  };
  const missing = "Please enter the fire temple's name and city.";
  const problems = [];
  if (!body.name) problems.push({ target: el("Name"), message: missing });
  if (!body.city) problems.push({ target: el("City"), message: missing });
  if (!phoneRes.ok) {
    problems.push({
      target: el("Phone").closest(".phone-field"),
      message: "Please enter a valid phone number, or leave it blank.",
    });
  }
  problems.push(...more);
  if (problems.length) { flagProblems(mainEl, problems); return null; }
  return body;
}

// "Are you a mobed here, or the panthaky?" (DECISIONS D10). Saying panthaky is
// only a claim: the admin confirms it, and until then they are a mobed in the
// app like anyone else. Neither answer is chosen for them.
const CLAIM_NOTE = "If you are the panthaky, the admin checks this first. Until then you use the app as a mobed.";

function claimChoicesHtml() {
  return `
    <div class="choice-group" id="crClaim">
      <label class="choice"><input type="radio" name="crClaim" value="mobed"><span>I am a mobed here</span></label>
      <label class="choice"><input type="radio" name="crClaim" value="panthaky"><span>I am the panthaky here</span></label>
    </div>`;
}

export function renderOnboarding() {
  chrome(false);
  mainEl.innerHTML = `
    <div class="card">
      <h2>Which fire temple do you work at?</h2>
      <p class="meta">Search by name or city. Tap yours when you see it.</p>
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
    try { list = await searchAgyaries(q); } catch (e) {
      // Only the latest search speaks: an older one failing is not news.
      if (mine === token) showError(e.message);
      return;
    }
    if (mine !== token) return;   // a newer keystroke already superseded this

    results.innerHTML = "";
    for (const a of list) {
      const row = document.createElement("div");
      row.className = "search-result";
      const badge = a.status === "unclaimed" ? '<span class="tag grey">not set up yet</span>' : "";
      row.innerHTML = `<div><strong>${esc(a.name)}</strong> ${badge}</div>
        <div class="addr">${esc([a.address, a.city].filter(Boolean).join(", "))}</div>`;
      row.onclick = () => askRole(a);
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

// A row is not a button, so nothing greys it out while it is joining: this
// stops a second tap (on it, or on another row) from joining twice.
let joining = false;

/** The fire temple is chosen: ask what they are there, then join. Closing the
 *  sheet leaves them on the search, with nothing joined. */
function askRole(a) {
  if (joining) return;
  const sheet = openSheet({
    title: "Are you a mobed here, or the panthaky?",
    html: `
      <p><b>${esc(a.name)}</b>${a.city ? `, ${esc(a.city)}` : ""}</p>
      <div class="stack">
        <button type="button" class="secondary" data-claim="mobed">I am a mobed here</button>
        <button type="button" class="secondary" data-claim="panthaky">I am the panthaky here</button>
      </div>
      <p class="meta" style="margin:12px 0 0">${CLAIM_NOTE}</p>`,
  });
  const buttons = sheet.body.querySelectorAll("[data-claim]");
  buttons.forEach(b => {
    b.onclick = () => pick(a, b.dataset.claim, buttons, sheet);
  });
}

async function pick(a, claimedRole, buttons, sheet) {
  if (joining) return;
  joining = true;
  buttons.forEach(b => { b.disabled = true; });   // one join per tap
  try {
    const res = await joinAgyary(a.id, claimedRole);
    state.user = res.user;
    state.currentAgyaryId = a.id;
    sheet.close();
    // An unclaimed seed entry still has 2012-era details nobody has
    // vouched for - confirm them before it goes live.
    if (a.status === "unclaimed") renderActivate(a);
    else { refreshHeader(); navigate("#/calendar", { replace: true }); }
  } catch (e) {
    buttons.forEach(b => { b.disabled = false; });
    showError(e.message);
  } finally {
    joining = false;
  }
}

function renderActivate(a) {
  chrome(false);
  mainEl.innerHTML = `
    <div class="card">
      <h2>Please help us set up ${esc(a.name)}</h2>
      <p class="meta">These are the details we have on file, but nobody has checked
        them in years. You would know best - please correct anything that's wrong.</p>
      <label>Name</label><input type="text" id="acName" value="${esc(a.name)}">
      <label>City</label><input type="text" id="acCity" value="${esc(a.city || "")}">
      <label>Address</label><input type="text" id="acAddr" value="${esc(a.address || "")}">
      <label>Contact phone (optional)</label>${phoneField("acPhone")}
      <div style="margin-top:14px"><button id="acGo">Looks right - set it up</button></div>
    </div>`;
  // This took the place of the search without the address changing: a new
  // page to the person reading it, so it opens at its top.
  toTop();
  document.getElementById("acGo").onclick = async (ev) => {
    // `btn` was never defined here, so a failed set-up threw inside its own
    // error handling and said nothing at all.
    const btn = ev.currentTarget;
    const body = readDetails("ac");
    if (!body) return;
    btn.disabled = true;   // one set-up per tap
    try {
      const res = await activateAgyary(a.id, body);
      state.user = res.user;
      state.currentAgyaryId = a.id;
      refreshHeader();
      navigate("#/calendar", { replace: true });
    } catch (e) {
      btn.disabled = false;
      showError(e.message);
    }
  };
}

function renderCreate(prefillName) {
  chrome(false);
  mainEl.innerHTML = `
    <div class="card">
      <h2>Tell us about your fire temple</h2>
      <p class="meta">Just a few details and it's ready to use.</p>
      <label>Name</label><input type="text" id="crName" value="${esc(prefillName || "")}">
      <label>City</label><input type="text" id="crCity">
      <label>Address</label><input type="text" id="crAddr">
      <label>Contact phone (optional)</label>${phoneField("crPhone")}
    </div>
    <div class="card">
      <h2>Are you a mobed here, or the panthaky?</h2>
      ${claimChoicesHtml()}
      <p class="meta" style="margin:10px 0 0">${CLAIM_NOTE}</p>
    </div>
    <div class="card">
      <h2>Where is it? (optional)</h2>
      <p class="meta">Put the pin on the fire temple. You can also do this later, from Settings.</p>
      <div id="crPicker"></div>
    </div>
    <div class="row tight" style="margin-bottom:14px">
      <button id="crGo">Add it</button>
      <button class="ghost" id="crBack">Back to search</button></div>`;
  // A different view under the same address: each way opens at its top.
  toTop();
  // The map is only drawn here, so Leaflet loads only for this step.
  const picker = mountLocationPicker(document.getElementById("crPicker"), {
    suggest: () => [document.getElementById("crName").value.trim(), document.getElementById("crCity").value.trim()]
      .filter(Boolean).join(", "),
  });
  document.getElementById("crBack").onclick = () => { picker.destroy(); renderOnboarding(); toTop(); };
  document.getElementById("crGo").onclick = async (ev) => {
    const btn = ev.currentTarget;
    if (btn.disabled) return;
    // One of the two must be chosen; neither is chosen for them.
    const claim = mainEl.querySelector('input[name="crClaim"]:checked');
    const body = readDetails("cr", claim ? []
      : [{ target: "#crClaim", message: "Please choose: a mobed here, or the panthaky." }]);
    if (!body) return;
    body.claimed_role = claim.value;
    // Optional: only if a pin was put down.
    const pin = picker.get();
    if (pin) body.location = pin;
    btn.disabled = true;
    try {
      const res = await createAgyary(body);
      picker.destroy();
      state.user = res.user;
      state.currentAgyaryId = res.agyary.id;
      refreshHeader();
      navigate("#/calendar", { replace: true });
    } catch (e) {
      // Left disabled, a failed attempt could never be tried again.
      btn.disabled = false;
      showError(e.message);
    }
  };
}
