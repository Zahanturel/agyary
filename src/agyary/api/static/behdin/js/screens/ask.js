"use strict";

/**
 * "Ask for a prayer": one question to a screen, with Back and a bar that shows how far along it is.
 * The answers are kept in state.ask while the person moves between steps, and nothing is sent until
 * the last one. The server checks everything again and says what is wrong in plain words; that
 * is shown on the field it is about. A memorial's dates are asked for from a departed's page
 * (the same flow, with "which dates" in place of "when" and "repeat").
 */

import { getAsking, getMyAgyari, getPersonNames, getToday, convertDay, parsiRange, createAsk } from "../api.js";
import { state } from "../state.js";
import { chrome, mainEl, setHeader, loadFailedHtml, wireRetry, showBack, showError, showInfo, toTop }
  from "/mobed-app/js/ui.js";
import { navGuard, navigate, returnTo } from "/mobed-app/js/router.js";
import { flagProblems } from "/mobed-app/js/fielderrors.js";
import { esc, todayIst, addDays, longDay, gregShort, weekdayOf, parsiWords, KIND_LABELS } from "../util.js";
import { mountPicker, NOT_TAKING } from "./picker.js";

const PURPOSES = {
  gujrela_nu: "Gujrela nu (for those who have passed away)",
  khushali_nu: "Khushali nu (for happiness)",
  hama_anjuman: "Hama Anjuman (for the whole community)",
  patet: "Patet (for those who have passed away)",
  tandarosti: "Tandarosti (for those who are living)",
};
const BOOKING_PURPOSES = ["gujrela_nu", "khushali_nu", "hama_anjuman"];
const MACHI_PURPOSES = ["patet", "tandarosti"];
const NAME_TITLES = [["khud", "Myself"], ["osta", "Mr (Osta)"], ["osti", "Mrs (Osti)"], ["ervad", "Ervad"], ["behdin", "Behdin"]];
const NAME_MAX = 20;
const NOTE_MAX = 200;
const MAX_COUNT = { monthly: 120, yearly: 60 };
const DEFAULT_COUNT = { monthly: 6, yearly: 3 };
const DAYS_AHEAD = 400;

/** What a person is told about the cost: the agyari's own words, never a charge made here. */
export function priceLine(service) {
  return service.usual_price != null
    ? `Usual price Rs ${Number(service.usual_price).toLocaleString("en-IN")}, confirm with the agyari`
    : "Ask the agyari for the price";
}

export function repeatWords(r) {
  if (!r) return "Once";
  return r.pattern === "monthly" ? `Every month, ${r.count} times in all` : `Every year, ${r.count} times in all`;
}

// --- Starting ---------------------------------------------------------------
/**
 * Begin a new ask and open it. `agyari` ({id, name, city}) is the one to ask when it is already
 * known; `memorial` ({id, name, observances}) when it is for a departed's dates; `back` is where
 * the person was.
 */
export function startAsk({ agyari = null, memorial = null, back = "#/home" } = {}) {
  state.ask = {
    agyari, asking: null, memorial: memorial ? { ...memorial, codes: [] } : null, back,
    service: null, purpose: null, date: "", geh: null, time: "", where: "agyari", area: "",
    names: [], repeat: null, note: "", step: agyari ? "what" : "agyari", pick: false, triedMine: !!agyari,
  };
  navigate("#/ask");
}

function stepsOf(d) {
  const s = ["agyari", "what"];
  if (d.memorial) s.push("dates"); else s.push("purpose", "when");
  if (canHome(d)) s.push("where");
  s.push("names");
  if (!d.memorial) s.push("repeat");
  s.push("note", "review");
  return s;
}

function canHome(d) {
  return !!(d.service && d.service.offsite_capable && !d.service.by_geh);
}

/** A new agyari or service makes what depended on the old one a different question. */
function forgetDependents(d, { keepService = false } = {}) {
  if (!keepService) d.service = null;
  d.purpose = null;
  d.geh = null;
  d.time = "";
  if (!canHome(d)) { d.where = "agyari"; d.area = ""; }
}

let systemKnown = false;

// --- The screen -------------------------------------------------------------
export async function renderAsk() {
  chrome(true);
  setHeader("Ask for a prayer");
  const alive = navGuard();
  if (!state.ask) {
    // Opened with no flow behind it (a reload, an old link): begin one, here.
    state.ask = {
      agyari: null, asking: null, memorial: null, back: "#/home", service: null, purpose: null, date: "",
      geh: null, time: "", where: "agyari", area: "", names: [], repeat: null, note: "", step: "agyari",
      pick: false, triedMine: false,
    };
  }
  const d = state.ask;
  if (!systemKnown) {
    try { state.system = (await getToday()).calendar || state.system; systemKnown = true; } catch (e) { /* the default */ }
    if (!alive()) return;
  }

  // Started from an agyari already chosen: what it offers is read before the first question.
  if (d.agyari && (!d.asking || d.asking.id !== d.agyari.id)) {
    mainEl.innerHTML = `<div class="empty-state">Loading...</div>`;
    try {
      d.asking = await getAsking(d.agyari.id);
    } catch (e) {
      if (!alive()) return;
      mainEl.innerHTML = loadFailedHtml("this agyari");
      wireRetry(mainEl, () => renderAsk());
      showBack(() => { state.ask = null; returnTo(d.back); });
      return;
    }
    if (!alive()) return;
    if (!d.asking.takes_asks) d.step = "agyari";
  }

  const ctx = { alive, redraw: () => draw(), go: (step) => { d.step = step; draw(); toTop(); } };
  let current = null;   // the step on show: { save, next }

  const leave = () => { state.ask = null; returnTo(d.back); };

  const goBack = () => {
    if (current) current.save();
    const steps = stepsOf(d);
    const i = steps.indexOf(d.step);
    if (d.step === "agyari" && d.pick && d.agyari && d.asking) { d.pick = false; return draw(); }
    if (i <= 0) return leave();
    ctx.go(steps[i - 1]);
  };

  function draw() {
    if (!alive()) return;
    const steps = stepsOf(d);
    if (!steps.includes(d.step)) d.step = steps[0];
    const i = steps.indexOf(d.step);
    const last = d.step === "review";
    current = STEPS[d.step](d, ctx);
    mainEl.innerHTML = `
      <div class="ask-top">
        <p class="meta" style="margin:0">Question ${i + 1} of ${steps.length}</p>
        <div class="progress" role="progressbar" aria-valuemin="1" aria-valuemax="${steps.length}" aria-valuenow="${i + 1}">
          <div style="width:${Math.round(((i + 1) / steps.length) * 100)}%"></div></div>
      </div>
      <div class="card" id="askCard">${current.html}</div>
      <div class="row ask-actions">
        <button type="button" class="secondary" id="askBack">Back</button>
        ${d.pick && d.step === "agyari" ? "" : `<button type="button" id="askNext">${last ? "Send my ask" : "Next"}</button>`}
      </div>`;
    showBack(goBack);
    document.getElementById("askBack").onclick = goBack;
    const nextBtn = document.getElementById("askNext");
    if (nextBtn) {
      nextBtn.onclick = async () => {
        const card = document.getElementById("askCard");
        current.save();
        const problems = current.check ? current.check() : null;
        if (problems && problems.length) return flagProblems(card, problems);
        if (last) return send(nextBtn);
        // The answer just given can change what comes next (a service that can be done at home).
        const now = stepsOf(d);
        ctx.go(now[now.indexOf(d.step) + 1]);
      };
    }
    if (current.after) current.after(document.getElementById("askCard"));
  }

  async function send(btn) {
    btn.disabled = true;   // one send per tap
    let made;
    try {
      made = await createAsk(bodyOf(d));
    } catch (err) {
      btn.disabled = false;
      return fieldFor(err.message);
    }
    state.ask = null;
    showInfo("Your ask was sent. You will be told here when the panthaky answers.");
    navigate(`#/asks/${made.id}`, { replace: true });
  }

  /** Put a server message on the question it is about, so it is read where it can be fixed. */
  function fieldFor(msg) {
    const text = msg.toLowerCase();
    const rules = [
      [/memorial|monthly and yearly|one of those dates|at least one date|all of those dates/, "dates", "#askDates"],
      [/area|only be done at the fire temple|at home/, "where", "#askArea"],
      [/what it is for/, "purpose", "#askPurposes"],
      [/geh/, "when", "#askGehs"],
      [/time of day|time has/, "when", "#askTime"],
      [/date|day |passed|next year|calendar/, "when", "#askDate"],
      [/service|offered/, "what", "#askServices"],
      [/repeat|times in all|every month|gatha/, "repeat", "#askRepeatBox"],
      [/\bname/, "names", "#askNameBox"],
      [/note/, "note", "#askNote"],
    ];
    const hit = rules.find(([re]) => re.test(text));
    if (!hit || !stepsOf(d).includes(hit[1])) return showError(msg);
    d.step = hit[1];
    draw();
    flagProblems(document.getElementById("askCard"), [{ target: hit[2], message: msg }]);
  }

  draw();
}

/** What is sent: only what the server asks for, in the shapes it checks. */
function bodyOf(d) {
  const body = {
    agyary_id: d.agyari.id, service_id: d.service.id, where: d.where,
    area: d.where === "home" ? d.area.trim() : null,
    names: d.names.map((n) => ({ section: "farmayeshne", title: n.title, name: n.name, status: n.status, pair_group: null })),
    note: d.note.trim() || null,
  };
  if (d.memorial) {
    body.memorial = { memorial_id: d.memorial.id, codes: d.memorial.codes };
    return body;
  }
  body.purpose = d.purpose;
  body.date = d.date;
  if (d.service.by_geh) body.geh = d.geh; else body.time = d.time;
  if (d.repeat) body.repeat = { pattern: d.repeat.pattern, count: d.repeat.count };
  return body;
}

// --- The steps --------------------------------------------------------------
const choiceRow = (name, value, checked, title, sub = "") =>
  `<label class="choice"><input type="radio" name="${name}" value="${esc(value)}" ${checked ? "checked" : ""}>
    <span>${esc(title)}${sub ? `<small class="meta" style="display:block">${esc(sub)}</small>` : ""}</span></label>`;

const picked = (name) => {
  const el = document.querySelector(`input[name="${name}"]:checked`);
  return el ? el.value : null;
};

function stepAgyari(d, ctx) {
  const html = `<h2>Which agyari do you want to ask?</h2><div id="askAgy"><p class="meta">Loading...</p></div>`;
  const after = async (root) => {
    const box = root.querySelector("#askAgy");
    if (!d.agyari && !d.triedMine) {
      d.triedMine = true;
      try {
        const mine = (await getMyAgyari()).agyari;
        if (mine && !mine.closed) d.agyari = { id: mine.id, name: mine.name, city: mine.city };
      } catch (e) { /* the list is there to choose from */ }
      if (!ctx.alive()) return;
    }
    if (!d.agyari) d.pick = true;
    if (d.pick) {
      mountPicker(box, {
        alive: ctx.alive, currentId: d.agyari && d.agyari.id,
        onPick: (a, asking) => {
          if (!d.agyari || d.agyari.id !== a.id) { d.service = null; forgetDependents(d); }
          d.agyari = a; d.asking = asking; d.pick = false;
          ctx.go("what");
        },
      });
      return;
    }
    if (!d.asking || d.asking.id !== d.agyari.id) {
      try {
        d.asking = await getAsking(d.agyari.id);
      } catch (e) {
        if (!ctx.alive()) return;
        box.innerHTML = loadFailedHtml("this agyari");
        wireRetry(box, () => ctx.redraw());
        return;
      }
      if (!ctx.alive()) return;
    }
    const a = d.asking;
    box.innerHTML = `<div class="agy-pick">
        <p style="margin:0"><b>${esc(a.name)}</b></p>
        <p class="meta" style="margin:0">${esc([a.city, KIND_LABELS[a.kind]].filter(Boolean).join(" · "))}</p>
        ${a.takes_asks ? "" : `<p style="margin:var(--space-2) 0 0"><b>${NOT_TAKING}.</b> Please choose another agyari.</p>`}
      </div>
      <div style="margin-top:var(--space-3)"><button type="button" class="ghost small" id="askOther">Choose another agyari</button></div>`;
    box.querySelector("#askOther").onclick = () => { d.pick = true; ctx.redraw(); };
  };
  return {
    html, after,
    save() {},
    check: () => (d.agyari && d.asking && d.asking.id === d.agyari.id && d.asking.takes_asks ? null
      : [{ target: "#askAgy", message: d.agyari ? `${NOT_TAKING}. Please choose another agyari.` : "Please choose an agyari." }]),
  };
}

function stepWhat(d) {
  const services = ((d.asking && d.asking.services) || []).filter((s) => !(d.memorial && s.by_geh));
  const html = `<h2>What would you like prayed?</h2>
    <p class="meta" style="margin:0 0 var(--space-2)">At ${esc(d.agyari.name)}.</p>
    <div id="askServices" class="choice-group">${services.length
      ? services.map((s) => choiceRow("askService", s.id, d.service && d.service.id === s.id, s.name, priceLine(s))).join("")
      : `<p class="meta">This agyari has not listed anything to ask for yet.</p>`}</div>
    <p class="meta" style="margin:var(--space-2) 0 0">Nothing is paid in the app.</p>`;
  return {
    html,
    save() {
      const id = Number(picked("askService"));
      const s = services.find((x) => x.id === id);
      if (s && (!d.service || d.service.id !== s.id)) { d.service = s; forgetDependents(d, { keepService: true }); }
    },
    check: () => (d.service ? null : [{ target: "#askServices", message: "Please choose what you would like prayed." }]),
  };
}

function stepPurpose(d) {
  const list = d.service.by_geh ? MACHI_PURPOSES : BOOKING_PURPOSES;
  const html = `<h2>What is it for?</h2>
    <div id="askPurposes" class="choice-group">${list.map((p) => choiceRow("askPurpose", p, d.purpose === p, PURPOSES[p])).join("")}</div>`;
  return {
    html,
    save() { const v = picked("askPurpose"); if (v) d.purpose = v; },
    check: () => (list.includes(d.purpose) ? null : [{ target: "#askPurposes", message: "Please choose what it is for." }]),
  };
}

function stepWhen(d, ctx) {
  const today = todayIst();
  const gehs = (d.asking.gehs || []);
  const html = `<h2>When?</h2>
    <label for="askDate">The day</label>
    <input type="date" id="askDate" value="${esc(d.date)}" min="${today}" max="${addDays(today, DAYS_AHEAD)}">
    <p class="meta" id="askParsi" style="margin:6px 0 0"></p>
    ${d.service.by_geh ? `<label>Which geh?</label>
      <div id="askGehs" class="choice-group">${gehs.map((g) => choiceRow("askGeh", g.geh, d.geh === g.geh, g.name)).join("")}</div>
      <p class="meta" style="margin:var(--space-2) 0 0">The geh is the part of the day. The agyari confirms it.</p>`
    : `<label for="askTime">The time</label>
      <input type="time" id="askTime" value="${esc(d.time)}">
      <p class="meta" style="margin:6px 0 0">The agyari confirms the time.</p>`}`;
  const after = (root) => {
    const dateEl = root.querySelector("#askDate");
    const out = root.querySelector("#askParsi");
    let asked = 0;
    const show = async () => {
      const mine = ++asked;
      out.textContent = "";
      if (!dateEl.value) return;
      try {
        const p = await convertDay(dateEl.value, state.system);
        if (mine === asked && ctx.alive()) out.textContent = `${weekdayOf(dateEl.value)}: ${parsiWords(p)}`;
      } catch (e) { /* the line is only a help */ }
    };
    dateEl.onchange = show;
    dateEl.oninput = show;
    show();
  };
  return {
    html, after,
    save() {
      d.date = document.getElementById("askDate").value;
      if (d.service.by_geh) { const g = picked("askGeh"); d.geh = g ? Number(g) : null; }
      else d.time = document.getElementById("askTime").value;
    },
    check() {
      const problems = [];
      if (!d.date) problems.push({ target: "#askDate", message: "Please choose the day." });
      else if (d.date < todayIst()) problems.push({ target: "#askDate", message: "That day has already passed. Please choose another." });
      if (d.service.by_geh && !d.geh) problems.push({ target: "#askGehs", message: "Please choose a geh." });
      if (!d.service.by_geh && !d.time) problems.push({ target: "#askTime", message: "Please choose a time." });
      return problems;
    },
  };
}

function stepDates(d) {
  const today = todayIst();
  const ahead = d.memorial.observances.filter((o) => o.date >= today);
  const html = `<h2>Which days should be prayed?</h2>
    <p class="meta" style="margin:0 0 var(--space-2)">For ${esc(d.memorial.name)}. Tick every day you would like the agyari to pray.</p>
    <div id="askDates" class="choice-group">${ahead.length ? ahead.map((o) =>
      `<div class="check-row"><input type="checkbox" id="askD${o.id}" value="${esc(o.code)}" ${d.memorial.codes.includes(o.code) ? "checked" : ""}>
        <label for="askD${o.id}"><b>${esc(gregShort(o.date))}</b> ${esc(o.label)}<br><span class="meta">${esc(parsiWords(o.parsi))}</span></label></div>`).join("")
      : `<p class="meta">There are no more days to come.</p>`}</div>
    ${ahead.length > 1 ? `<button type="button" class="ghost small" id="askAllDates" style="margin-top:var(--space-2)">Tick all</button>` : ""}`;
  return {
    html,
    after(root) {
      const all = root.querySelector("#askAllDates");
      if (all) all.onclick = () => root.querySelectorAll("#askDates input").forEach((c) => { c.checked = true; });
    },
    save() {
      d.memorial.codes = [...document.querySelectorAll("#askDates input:checked")].map((c) => c.value);
    },
    check: () => (d.memorial.codes.length ? null : [{ target: "#askDates", message: "Please tick at least one day." }]),
  };
}

function stepWhere(d) {
  const html = `<h2>Where?</h2>
    <div id="askWhere" class="choice-group">
      ${choiceRow("askWhere", "agyari", d.where === "agyari", "At the agyari")}
      ${choiceRow("askWhere", "home", d.where === "home", "At home")}
    </div>
    <div id="askHomeBox" style="${d.where === "home" ? "" : "display:none"}">
      <label for="askArea">Your area</label>
      <input type="text" id="askArea" maxlength="100" autocomplete="off" value="${esc(d.area)}" placeholder="For example: Dadar, Mumbai">
      <p class="meta" style="margin:6px 0 0">Only the area for now. The address is for later, if the agyari accepts.</p>
    </div>`;
  return {
    html,
    after(root) {
      root.querySelectorAll('input[name="askWhere"]').forEach((r) => {
        r.onchange = () => { root.querySelector("#askHomeBox").style.display = picked("askWhere") === "home" ? "" : "none"; };
      });
    },
    save() { d.where = picked("askWhere") || "agyari"; d.area = document.getElementById("askArea").value; },
    check: () => (d.where === "home" && !d.area.trim() ? [{ target: "#askArea", message: "Please enter your area." }] : null),
  };
}

function stepNames(d, ctx) {
  const html = `<h2>Whose names should be prayed?</h2>
    <p class="meta" style="margin:0 0 var(--space-2)">Up to ${NAME_MAX} names. You can leave this empty.</p>
    <div id="askNameBox">
      <div id="askNameList"></div>
      <div id="askSuggest"></div>
      <label for="askNewName">Add a name</label>
      <input type="text" id="askNewName" maxlength="120" autocomplete="off">
      <div class="row" style="margin-top:var(--space-2)">
        <div><label for="askNewTitle" style="margin-top:0">Title</label>
          <select id="askNewTitle">${NAME_TITLES.map(([k, t]) => `<option value="${k}">${t}</option>`).join("")}</select></div>
        <div><label for="askNewStatus" style="margin-top:0">Is this person</label>
          <select id="askNewStatus"><option value="departed">Passed away</option><option value="living">Living</option></select></div>
      </div>
      <button type="button" class="secondary small" id="askAddName" style="margin-top:var(--space-2)">Add this name</button>
    </div>`;
  const after = (root) => {
    const listEl = root.querySelector("#askNameList");
    const paint = () => {
      listEl.innerHTML = d.names.length ? d.names.map((n, i) => `<div class="name-row">
        <span><b>${esc(n.name)}</b><small class="meta" style="display:block">${esc(titleWords(n.title))}, ${n.status === "departed" ? "passed away" : "living"}</small></span>
        <button type="button" class="ghost small" data-rm="${i}" aria-label="Remove ${esc(n.name)}">Remove</button></div>`).join("") : "";
      listEl.querySelectorAll("[data-rm]").forEach((b) => { b.onclick = () => { d.names.splice(Number(b.dataset.rm), 1); paint(); }; });
    };
    const add = (name, title, status) => {
      const text = name.trim();
      if (!text) return flagProblems(root, [{ target: "#askNewName", message: "Please enter a name." }]);
      if (d.names.length >= NAME_MAX) return flagProblems(root, [{ target: "#askNewName", message: `You can give up to ${NAME_MAX} names.` }]);
      if (d.names.some((n) => n.name.toLowerCase() === text.toLowerCase() && n.title === title)) return;
      d.names.push({ name: text, title, status });
      paint();
    };
    paint();
    root.querySelector("#askAddName").onclick = () => {
      const input = root.querySelector("#askNewName");
      add(input.value, root.querySelector("#askNewTitle").value, root.querySelector("#askNewStatus").value);
      if (!root.querySelector(".has-error")) input.value = "";
    };
    // Names kept before (from the person's own departed): one tap adds one.
    getPersonNames().then((r) => {
      if (!ctx.alive()) return;
      const box = root.querySelector("#askSuggest");
      const seen = new Set();
      const pool = (r.names || []).filter((n) => {
        const key = (n.departed_name || "").trim().toLowerCase();
        if (!key || seen.has(key)) return false;
        seen.add(key);
        return true;
      }).slice(0, 12);
      if (!box || !pool.length) return;
      box.innerHTML = `<p class="meta" style="margin:var(--space-2) 0">Names you have used before. Tap one to add it.</p>
        <div class="chip-row">${pool.map((n, i) => `<button type="button" class="chip" data-pool="${i}">${esc(n.departed_name)}</button>`).join("")}</div>`;
      box.querySelectorAll("[data-pool]").forEach((b) => {
        b.onclick = () => {
          const n = pool[Number(b.dataset.pool)];
          add(n.departed_name, NAME_TITLES.some(([k]) => k === n.departed_title) ? n.departed_title : "osta", "departed");
        };
      });
    }).catch(() => { /* the saved names are only a help */ });
  };
  return {
    html, after,
    save() {},
    check: () => null,
  };
}

function titleWords(k) {
  const hit = NAME_TITLES.find(([key]) => key === k);
  return hit ? hit[1] : "";
}

function stepRepeat(d, ctx) {
  const r = d.repeat;
  const html = `<h2>Once, or again and again?</h2>
    <div id="askRepeatBox">
      <div class="choice-group">
        ${choiceRow("askRep", "none", !r, "Once")}
        ${choiceRow("askRep", "monthly", r && r.pattern === "monthly", "Every month", "On the same Roj of each Parsi month")}
        ${choiceRow("askRep", "yearly", r && r.pattern === "yearly", "Every year", "On the same Roj and Mah each Parsi year")}
      </div>
      <div id="askCountBox" style="${r ? "" : "display:none"}">
        <label for="askCount" id="askCountLabel"></label>
        <input type="number" id="askCount" inputmode="numeric" min="2" step="1" value="${r ? r.count : ""}">
        <p class="meta" id="askPreview" style="margin:var(--space-2) 0 0"></p>
      </div>
    </div>`;
  const after = (root) => {
    const countEl = root.querySelector("#askCount");
    const label = root.querySelector("#askCountLabel");
    const preview = root.querySelector("#askPreview");
    let asked = 0;
    const pattern = () => { const v = picked("askRep"); return v === "monthly" || v === "yearly" ? v : null; };
    const refresh = async () => {
      const p = pattern();
      root.querySelector("#askCountBox").style.display = p ? "" : "none";
      if (!p) return;
      label.textContent = p === "monthly" ? "For how many months?" : "For how many years?";
      countEl.max = MAX_COUNT[p];
      if (!countEl.value) countEl.value = DEFAULT_COUNT[p];
      const mine = ++asked;
      preview.textContent = "";
      const n = Number(countEl.value);
      if (!d.date || !Number.isInteger(n)) return;
      const dates = await upcoming(d.date, p, Math.min(n, p === "monthly" ? 4 : 2));
      if (mine !== asked || !ctx.alive() || !dates.length) return;
      preview.textContent = `First day: ${longDay(d.date)}. Then ${dates.map((x) => gregShort(x)).join(", ")}${n > dates.length + 1 ? " and so on" : ""}.`;
    };
    root.querySelectorAll('input[name="askRep"]').forEach((x) => { x.onchange = () => { countEl.value = ""; refresh(); }; });
    countEl.oninput = refresh;
    refresh();
  };
  return {
    html, after,
    save() {
      const v = picked("askRep");
      if (v === "monthly" || v === "yearly") {
        const n = Number(document.getElementById("askCount").value);
        d.repeat = { pattern: v, count: Number.isInteger(n) ? n : 0 };
      } else d.repeat = null;
    },
    check() {
      if (!d.repeat) return null;
      const max = MAX_COUNT[d.repeat.pattern];
      if (!(d.repeat.count >= 2 && d.repeat.count <= max)) {
        return [{ target: "#askCount", message: `Please choose between 2 and ${max} times in all.` }];
      }
      return null;
    },
  };
}

/**
 * The next few days a repeat will fall on, from the Parsi calendar itself: the same Roj in each
 * following Parsi month, or the same Roj and Mah in the following Parsi year. A help only.
 */
async function upcoming(startYmd, pattern, how) {
  try {
    const first = (await convertDay(startYmd, state.system));
    if (first.is_gatha) return [];
    const out = [];
    if (pattern === "monthly") {
      for (let from = 1; out.length < how && from < 190; from += 62) {
        const days = await parsiRange(addDays(startYmd, from), addDays(startYmd, from + 61), state.system);
        for (const p of days) if (!p.is_gatha && p.roj === first.roj && out.length < how) out.push(p.gregorian_date);
      }
    } else {
      for (let k = 1; out.length < how && k <= how; k++) {
        const days = await parsiRange(addDays(startYmd, k * 365 - 5), addDays(startYmd, k * 365 + 5), state.system);
        const hit = days.find((p) => !p.is_gatha && p.roj === first.roj && p.mah === first.mah);
        if (hit) out.push(hit.gregorian_date);
      }
    }
    return out;
  } catch (e) {
    return [];
  }
}

function stepNote(d) {
  const html = `<h2>Is there anything you would like to add?</h2>
    <label for="askNote">A note for the panthaky (if you like)</label>
    <textarea id="askNote" rows="4" maxlength="${NOTE_MAX}">${esc(d.note)}</textarea>
    <p class="meta" style="margin:6px 0 0"><span id="askNoteCount">${d.note.length}</span> of ${NOTE_MAX} letters.
      Please do not put links, phone numbers or @-handles in it.</p>`;
  return {
    html,
    after(root) {
      const t = root.querySelector("#askNote");
      t.oninput = () => { root.querySelector("#askNoteCount").textContent = t.value.length; };
    },
    save() { d.note = document.getElementById("askNote").value; },
    check: () => (d.note.length > NOTE_MAX ? [{ target: "#askNote", message: `Please keep the note to ${NOTE_MAX} letters or fewer.` }] : null),
  };
}

function stepReview(d, ctx) {
  const row = (title, text, step) => `<div class="rv-row"><div><b>${esc(title)}</b><br>${text}</div>
    <button type="button" class="ghost small" data-go="${step}" aria-label="Change ${esc(title.toLowerCase())}">Change</button></div>`;
  const rows = [row("Agyari", esc(`${d.agyari.name}${d.agyari.city ? ", " + d.agyari.city : ""}`), "agyari"),
    row("What", `${esc(d.service.name)}<br><span class="meta">${esc(priceLine(d.service))}</span>`, "what")];
  if (d.memorial) {
    const chosen = d.memorial.observances.filter((o) => d.memorial.codes.includes(o.code));
    rows.push(row("Days", `For ${esc(d.memorial.name)}:<br>${chosen.map((o) => `${esc(gregShort(o.date))} ${esc(o.label)}`).join("<br>")}`, "dates"));
  } else {
    rows.push(row("What for", esc(PURPOSES[d.purpose]), "purpose"));
    rows.push(row("When", `${esc(longDay(d.date))}<br>${d.service.by_geh ? esc(((d.asking.gehs.find((g) => g.geh === d.geh)) || {}).name || "") + " geh" : esc(d.time)}`, "when"));
  }
  if (canHome(d)) rows.push(row("Where", d.where === "home" ? `At home, ${esc(d.area.trim())}` : "At the agyari", "where"));
  rows.push(row("Names", d.names.length ? d.names.map((n) => esc(n.name)).join(", ") : "None", "names"));
  if (!d.memorial) rows.push(row("Repeats", esc(repeatWords(d.repeat)), "repeat"));
  rows.push(row("Note", d.note.trim() ? esc(d.note.trim()) : "None", "note"));
  const html = `<h2>Please check your ask</h2>${rows.join("")}
    <p class="rv-promise"><b>Your name and number go to the panthaky only if they accept.</b></p>`;
  return {
    html,
    after(root) { root.querySelectorAll("[data-go]").forEach((b) => { b.onclick = () => ctx.go(b.dataset.go); }); },
    save() {},
    check: () => null,
  };
}

const STEPS = {
  agyari: stepAgyari, what: stepWhat, purpose: stepPurpose, when: stepWhen, dates: stepDates,
  where: stepWhere, names: stepNames, repeat: stepRepeat, note: stepNote, review: stepReview,
};
