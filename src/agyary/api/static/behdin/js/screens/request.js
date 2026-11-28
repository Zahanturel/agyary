"use strict";

/**
 * New request, on one screen: What (the prayers the fire temple offers), When (a date, and a time or geh, for
 * each one ticked), optional names, Send. Repeating is tucked under "Repeat (optional)". Nothing is sent before
 * Send; the server checks everything again and what it says is shown on the field it is about.
 */

import { getOffering, getMyAgyari, convertDay, createAsk } from "../api.js";
import { state } from "../state.js";
import { chrome, mainEl, setHeader, loadFailedHtml, wireRetry, showBack, showError, showInfo, toTop }
  from "/mobed-app/js/ui.js";
import { navGuard, navigate, returnTo } from "/mobed-app/js/router.js";
import { flagProblems } from "/mobed-app/js/fielderrors.js";
import { setRepeat, repeatCountHtml, wireRepeatCount, repeatCountProblem, repeatFields } from "/mobed-app/js/repeat.js";
import { esc, todayIst, addDays, longDay, gregShort, weekdayOf, parsiWords } from "../util.js";
import { mountPicker } from "./picker.js";

const MAX_NAMES = 20;
const DAYS_AHEAD = 400;

export const rupees = (n) => `₹${Number(n).toLocaleString("en-IN")}`;

/** "Every month, 6 in all": how a repeat reads, in this app's lists. */
export function repeatWords(r) {
  if (!r || !r.recurring) return "Once";
  return `${r.recurring === "monthly" ? "Every month" : "Every year"}, ${r.recurring_count} in all`;
}

/** Begin a new request and open it. `back` is where the person was. */
export function startRequest({ back = "#/home" } = {}) {
  state.request = { temple: null, offering: null, picked: [], items: {}, names: "", back, pick: false, triedMine: false };
  navigate("#/request");
}

const keyOf = (it) => (it.type === "memorial" ? "memorial" : `s${it.id}`);

function blank(it) {
  return { date: "", time: "", open: true, geh: null, name: "", death: "", recurring: null, recurringCount: null, _it: it };
}

export async function renderRequest() {
  chrome(true);
  setHeader("New request");
  const alive = navGuard();
  if (!state.request) state.request = { temple: null, offering: null, picked: [], items: {}, names: "", back: "#/home", pick: false, triedMine: false };
  const d = state.request;

  if (!d.temple && !d.triedMine) {
    d.triedMine = true;
    try {
      const mine = (await getMyAgyari()).agyari;
      if (mine && !mine.closed) d.temple = { id: mine.id, name: mine.name, city: mine.city, kind: mine.kind };
    } catch (e) { /* the list is there to choose from */ }
    if (!alive()) return;
  }
  if (!d.temple) d.pick = true;
  if (d.temple && (!d.offering || d.offering.id !== d.temple.id)) {
    mainEl.innerHTML = `<div class="empty-state">Loading...</div>`;
    try {
      d.offering = await getOffering(d.temple.id);
    } catch (e) {
      if (!alive()) return;
      mainEl.innerHTML = loadFailedHtml("this fire temple");
      wireRetry(mainEl, () => renderRequest());
      return;
    }
    if (!alive()) return;
    d.picked = []; d.items = {};
  }

  const leave = () => { state.request = null; returnTo(d.back); };
  let current = null;

  const goBack = () => {
    if (current) current.save();
    if (d.pick && d.temple) { d.pick = false; return draw(); }
    return leave();
  };

  function draw() {
    if (!alive()) return;
    if (d.pick) {
      mainEl.innerHTML = `<div id="rqPick"></div>`;
      showBack(goBack);
      mountPicker(document.getElementById("rqPick"), {
        alive, currentId: d.temple && d.temple.id, town: d.temple ? d.temple.city : "", pickLabel: "Choose",
        onPick: (a) => {
          if (!d.temple || d.temple.id !== a.id) { d.temple = a; d.offering = null; }
          d.pick = false;
          renderRequest();
        },
      });
      return;
    }
    current = STEP.all(d, { alive });
    mainEl.innerHTML = `
      <div class="card" id="rqCard">
        <div id="rqTemple" class="rq-temple"><b>${esc(d.temple.name)}</b>${d.temple.city ? `, ${esc(d.temple.city)}` : ""}
          <button type="button" class="ghost small" id="rqChange">Change</button></div>
        ${current.html}
      </div>
      ${d.offering.takes_requests ? `<div class="row" style="margin-top:var(--space-3)"><button type="button" id="rqNext">Send</button></div>` : ""}`;
    showBack(goBack);
    document.getElementById("rqChange").onclick = () => { current.save(); d.pick = true; draw(); };
    const sendBtn = document.getElementById("rqNext");
    if (sendBtn) sendBtn.onclick = async (e) => {
      current.save();
      const problems = current.check();
      if (problems && problems.length) return flagProblems(document.getElementById("rqCard"), problems);
      return send(e.currentTarget);
    };
    current.after(document.getElementById("rqCard"));
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
    state.request = null;
    showInfo("Request sent.");
    navigate(`#/asks/${made.id}`, { replace: true });
  }

  /** Put a server message on the field it is about. */
  function fieldFor(msg) {
    const text = msg.toLowerCase();
    if (/\bname/.test(text)) return flagProblems(document.getElementById("rqCard"), [{ target: "#rqNames", message: msg }]);
    if (/date|day|time|geh|repeat|times|passed|death|gatha|service/.test(text)) {
      const first = document.querySelector("#rqCard input, #rqCard .choice-group");
      return flagProblems(document.getElementById("rqCard"), [{ target: first, message: msg }]);
    }
    showError(msg);
  }

  draw();
}

/** What is sent: only what the server asks for, in the shapes it checks. */
function bodyOf(d) {
  const items = d.picked.map((k) => {
    const v = d.items[k];
    const it = v._it;
    if (it.type === "memorial") {
      return { type: "memorial", death_date: v.death, departed_name: v.name.trim() || null, ...repeatFields(v) };
    }
    const out = { service_id: it.id, date: v.date, ...repeatFields(v) };
    if (it.by_geh) out.geh = v.geh; else if (!v.open && v.time) out.time = v.time;
    return out;
  });
  const names = d.names.split("\n").map((n) => n.trim()).filter(Boolean);
  return { agyary_id: d.temple.id, names, items };
}

const row = (name, id, checked, title, price) =>
  `<div class="check-row"><input type="checkbox" id="${id}" value="${esc(name)}" ${checked ? "checked" : ""}>
    <label for="${id}">${esc(title)}${price != null ? ` <span class="ptag">${rupees(price)}</span>` : ""}</label></div>`;

// --- The parts of the screen ----------------------------------------------------
const PARTS = {
  what(d) {
    const o = d.offering;
    const list = [...o.services, ...(o.memorial ? [o.memorial] : [])];
    const html = o.takes_requests
      ? `<h2>What</h2><div id="rqWhat" class="choice-group">${list.map((it) =>
        row(keyOf(it), `rqW_${keyOf(it)}`, d.picked.includes(keyOf(it)), it.name, it.price)).join("")}</div>`
      : `<h2>What</h2><p>${esc(o.message || "Not taking requests yet")}</p>`;
    return {
      html,
      save() {
        if (!o.takes_requests) return;
        const keys = [...document.querySelectorAll("#rqWhat input:checked")].map((c) => c.value);
        d.picked = list.map(keyOf).filter((k) => keys.includes(k));
        for (const it of list) if (d.picked.includes(keyOf(it)) && !d.items[keyOf(it)]) d.items[keyOf(it)] = blank(it);
      },
      check: () => (d.picked.length ? null : [{ target: "#rqWhat", message: o.takes_requests ? "Choose at least one." : o.message }]),
    };
  },

  when(d, ctx) {
    const today = todayIst();
    const blocks = d.picked.map((k) => {
      const v = d.items[k];
      const it = v._it;
      const repeat = `<details class="rq-repeat"${v.recurring ? " open" : ""}><summary>Repeat (optional)</summary>
        <div class="choice-group" id="rqRep_${k}">
          ${["", "monthly", "yearly"].map((r) => `<div class="check-row"><input type="radio" name="rep_${k}" id="rep_${k}_${r || "no"}" value="${r}" ${(v.recurring || "") === r ? "checked" : ""}>
            <label for="rep_${k}_${r || "no"}">${r === "" ? "Don't repeat" : r === "monthly" ? "Every month, on the same Roj" : "Every year, on the same Roj and Mah (a birthday or anniversary)"}</label></div>`).join("")}
        </div><div id="rqCount_${k}">${repeatCountHtml(v, `rqN_${k}`)}</div></details>`;
      if (it.type === "memorial") {
        return `<div class="rq-block" data-k="${k}"><h2>${esc(it.name)}</h2>
          <label for="rqName_${k}">Name of the departed (optional)</label>
          <input type="text" id="rqName_${k}" maxlength="120" autocomplete="off" value="${esc(v.name)}">
          <label for="rqDate_${k}">Date of passing</label>
          <input type="date" id="rqDate_${k}" max="${today}" value="${esc(v.death)}">
          ${repeat}</div>`;
      }
      return `<div class="rq-block" data-k="${k}"><h2>${esc(it.name)}</h2>
        <label for="rqDate_${k}">Date</label>
        <input type="date" id="rqDate_${k}" min="${today}" max="${addDays(today, DAYS_AHEAD)}" value="${esc(v.date)}">
        <p class="meta" id="rqParsi_${k}" style="margin:6px 0 0"></p>
        ${it.by_geh ? `<label>Geh</label><div class="choice-group" id="rqGeh_${k}">${d.offering.gehs.map((g) =>
          `<div class="check-row"><input type="radio" name="geh_${k}" id="geh_${k}_${g.geh}" value="${g.geh}" ${v.geh === g.geh ? "checked" : ""}>
            <label for="geh_${k}_${g.geh}">${esc(g.name)}</label></div>`).join("")}</div>`
        : `<label for="rqTime_${k}">Time</label>
          <div class="row"><input type="time" id="rqTime_${k}" value="${esc(v.time)}" ${v.open ? "disabled" : ""}>
          <div class="check-row"><input type="checkbox" id="rqOpen_${k}" ${v.open ? "checked" : ""}><label for="rqOpen_${k}">Any time</label></div></div>`}
        ${repeat}</div>`;
    });
    return {
      html: blocks.join(""),
      after(root) {
        d.picked.forEach((k) => {
          const v = d.items[k];
          const dateEl = root.querySelector(`#rqDate_${k}`);
          const out = root.querySelector(`#rqParsi_${k}`);
          if (out) {
            let asked = 0;
            const show = async () => {
              const mine = ++asked;
              out.textContent = "";
              if (!dateEl.value) return;
              try {
                const p = await convertDay(dateEl.value, state.system);
                if (mine === asked && ctx.alive()) out.textContent = `${weekdayOf(dateEl.value)}, ${parsiWords(p)}`;
              } catch (e) { /* the line is only a help */ }
            };
            dateEl.onchange = show; dateEl.oninput = show; show();
          }
          const open = root.querySelector(`#rqOpen_${k}`);
          if (open) open.onchange = () => { root.querySelector(`#rqTime_${k}`).disabled = open.checked; };
          root.querySelectorAll(`input[name="rep_${k}"]`).forEach((r) => {
            r.onchange = () => {
              setRepeat(v, r.value);
              root.querySelector(`#rqCount_${k}`).innerHTML = repeatCountHtml(v, `rqN_${k}`);
              wireRepeatCount(v, `rqN_${k}`, () => {});
            };
          });
          wireRepeatCount(v, `rqN_${k}`, () => {});
        });
      },
      save() {
        for (const k of d.picked) {
          const v = d.items[k];
          const date = document.getElementById(`rqDate_${k}`);
          if (!date) return;
          if (v._it.type === "memorial") { v.death = date.value; v.name = document.getElementById(`rqName_${k}`).value; }
          else {
            v.date = date.value;
            if (v._it.by_geh) { const g = document.querySelector(`input[name="geh_${k}"]:checked`); v.geh = g ? Number(g.value) : null; }
            else { v.open = document.getElementById(`rqOpen_${k}`).checked; v.time = document.getElementById(`rqTime_${k}`).value; }
          }
        }
      },
      check() {
        const problems = [];
        for (const k of d.picked) {
          const v = d.items[k];
          const it = v._it;
          if (it.type === "memorial") {
            if (!v.death) problems.push({ target: `#rqDate_${k}`, message: "Enter the date of passing." });
            else if (v.death > todayIst()) problems.push({ target: `#rqDate_${k}`, message: "The date of passing cannot be in the future." });
          } else {
            if (!v.date) problems.push({ target: `#rqDate_${k}`, message: "Choose a date." });
            else if (v.date < todayIst()) problems.push({ target: `#rqDate_${k}`, message: "That date has passed." });
            if (it.by_geh && !v.geh) problems.push({ target: `#rqGeh_${k}`, message: "Choose a geh." });
            if (!it.by_geh && !v.open && !v.time) problems.push({ target: `#rqTime_${k}`, message: "Enter a time, or choose Any time." });
          }
          const bad = repeatCountProblem(v);
          if (bad) problems.push({ target: `#rqN_${k}`, message: bad });
        }
        return problems;
      },
    };
  },

  /** The cost of what is ticked, and the optional names. */
  extras(d) {
    let total = 0;
    let estimate = false;
    for (const k of d.picked) {
      const v = d.items[k];
      const it = v._it;
      const count = v.recurring ? v.recurringCount || 1 : 1;
      if (it.type === "memorial") estimate = true;
      else if (it.price != null) total += it.price * count;
      if (v.recurring) estimate = true;
    }
    return {
      html: `${total || estimate ? `<p id="rqTotal" style="margin:var(--space-3) 0 0"><b>Total ${rupees(total)}${estimate ? " (estimate)" : ""}</b></p>` : ""}
        <label for="rqNames">Names to pray (optional, one per line, up to ${MAX_NAMES})</label>
        <textarea id="rqNames" rows="3">${esc(d.names)}</textarea>
        <p class="meta" style="margin:var(--space-3) 0 0">Your name and number go to the panthaky only if they accept.</p>`,
      save() { const t = document.getElementById("rqNames"); if (t) d.names = t.value; },
      check() {
        const n = d.names.split("\n").map((x) => x.trim()).filter(Boolean).length;
        return n > MAX_NAMES ? [{ target: "#rqNames", message: `Up to ${MAX_NAMES} names.` }] : null;
      },
    };
  },
};

// --- The one screen ------------------------------------------------------------
// What is drawn once; ticking a prayer redraws only the When part below it, so what was typed stays.
const STEP = {
  all(d, ctx) {
    const what = PARTS.what(d);
    let when = PARTS.when(d, ctx);
    let extras = PARTS.extras(d);
    return {
      html: `${what.html}${d.offering.takes_requests ? `<div id="rqWhenBox">${when.html}</div><div id="rqExtras">${extras.html}</div>` : ""}`,
      after(root) {
        if (!d.offering.takes_requests) return;
        when.after(root);
        const box = root.querySelector("#rqWhenBox");
        const tail = root.querySelector("#rqExtras");
        const refresh = () => {
          const names = root.querySelector("#rqNames").value;
          extras = PARTS.extras(d);
          tail.innerHTML = extras.html;
          root.querySelector("#rqNames").value = names;
        };
        root.querySelectorAll("#rqWhat input").forEach((c) => {
          c.onchange = () => {
            when.save(); what.save();
            when = PARTS.when(d, ctx);
            box.innerHTML = when.html;
            when.after(root);
            refresh();
          };
        });
        // The total follows a repeat choice made under a prayer.
        root.addEventListener("change", (e) => {
          if (!e.target.name || !e.target.name.startsWith("rep_")) return;
          when.save(); refresh();
        });
      },
      save() { what.save(); when.save(); extras.save(); },
      check() {
        const first = what.check();
        if (first) return first;
        return [...when.check(), ...(extras.check() || [])];
      },
    };
  },
};
