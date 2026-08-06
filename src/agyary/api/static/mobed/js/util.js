"use strict";

import { state } from "./state.js";
import { convertDate } from "./api.js";

export function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, c => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// Every date the app reasons about is an IST calendar day: the fire temple
// is in India, the Parsi day is anchored to sunrise there, and a mobed
// travelling shouldn't see their day shift.
export function istYmd(iso) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit",
  }).format(new Date(iso));
}
export function istTime(iso) {
  return new Date(iso).toLocaleTimeString([], {
    timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit",
  });
}
export function todayIst() {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit",
  }).format(new Date());
}
export function shiftYmd(ymd, delta) {
  const [y, m, d] = ymd.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  dt.setUTCDate(dt.getUTCDate() + delta);
  return dt.toISOString().slice(0, 10);
}
export function weekDays(ymd) {  // Mon..Sun containing ymd
  const [y, m, d] = ymd.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  const dow = (dt.getUTCDay() + 6) % 7; // Mon=0
  const start = shiftYmd(ymd, -dow);
  return Array.from({ length: 7 }, (_, i) => shiftYmd(start, i));
}
export function gregLabel(ymd) {
  const [y, m, d] = ymd.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString([], {
    weekday: "short", day: "numeric", month: "short", year: "numeric", timeZone: "UTC",
  });
}
export function gregShort(ymd) {
  const [y, m, d] = ymd.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString([], {
    day: "numeric", month: "short", timeZone: "UTC",
  });
}

export const MAH_NAMES_JS = ["Fravardin", "Ardibehesht", "Khordad", "Tir", "Amardad", "Shahrevar",
  "Meher", "Avan", "Adar", "Dae", "Bahman", "Aspandard"];

/** Mah 1..12, then Gatha (13), then Mah 1 of the next year. */
export function stepParsiMonth(mah, year, delta) {
  if (delta > 0) {
    if (mah < 12) return { mah: mah + 1, year };
    if (mah === 12) return { mah: 13, year };
    return { mah: 1, year: year + 1 };
  }
  if (mah === 1) return { mah: 13, year: year - 1 };
  if (mah === 13) return { mah: 12, year };
  return { mah: mah - 1, year };
}
export function monthYearLabel(mah, year) {
  return mah === 13 ? `Gatha days, Y${year}` : `${MAH_NAMES_JS[mah - 1]}, Y${year}`;
}

/** A Parsi day's reading in one system, cached - the mapping never changes. */
export async function parsiLabel(ymd, system) {
  const key = ymd + "|" + system;
  if (state.parsiCache[key]) return state.parsiCache[key];
  try {
    const p = await convertDate(ymd, system);
    const label = p.is_gatha
      ? `${p.gatha_name} (Gatha), Y${p.year}`
      : `Roj ${p.roj_name}, Mah ${p.mah_name}, Y${p.year}`;
    state.parsiCache[key] = label;
    return label;
  } catch (e) {
    return "";
  }
}

/** The same reading, short enough for a calendar cell. */
export async function parsiShort(ymd, system) {
  const key = ymd + "|short|" + system;
  if (state.parsiCache[key]) return state.parsiCache[key];
  try {
    const p = await convertDate(ymd, system);
    const label = p.is_gatha ? p.gatha_name : p.roj_name;
    state.parsiCache[key] = label;
    return label;
  } catch (e) {
    return "";
  }
}

// --------------------------------------------------------------------------
// Phone field: a country-code box (defaults to 91/India) next to a local
// number box - editable, not locked, since behdins and mobeds alike can be
// from anywhere (the fire-temple list spans India, Iran, Pakistan, Canada,
// the UK, Hong Kong).
// --------------------------------------------------------------------------
const KNOWN_COUNTRY_CODES = [
  "971", "852", "966", "968", "965", "974",
  "91", "98", "92", "94", "44", "61", "64", "65", "86", "81", "82",
  "49", "33", "39", "34", "27", "20", "60", "66", "63",
  "1", "7",
];

/** Best-effort split of a stored E.164 number for edit prefill only. Country
 *  codes are 1-3 digits with no separator, so this is a heuristic over common
 *  codes. What gets SAVED is always recomposed from the two boxes, so a wrong
 *  guess is a cosmetic prefill glitch the mobed can fix by eye. */
export function splitE164(value) {
  const digits = (value || "").replace(/^\+/, "").replace(/\D/g, "");
  for (const cc of KNOWN_COUNTRY_CODES) {
    if (digits.startsWith(cc)) return { cc, local: digits.slice(cc.length) };
  }
  return { cc: "91", local: digits };
}

export function phoneField(id, existingValue) {
  const { cc, local } = existingValue ? splitE164(existingValue) : { cc: "91", local: "" };
  return `<div class="phone-field">
    <div class="cc-group"><span class="cc-plus">+</span>
      <input type="tel" class="cc-input" id="${id}_cc" inputmode="numeric" maxlength="3" value="${esc(cc)}"></div>
    <input type="tel" id="${id}" inputmode="numeric" maxlength="12"
      placeholder="98765 43210" value="${esc(local)}"></div>`;
}

/** Required fields: null means "not a valid phone number". */
export function readPhone(id) {
  const cc = document.getElementById(id + "_cc").value.replace(/\D/g, "");
  const digits = document.getElementById(id).value.replace(/\D/g, "");
  return cc && digits.length >= 4 ? "+" + cc + digits : null;
}

/** Optional fields: distinguishes blank from malformed. */
export function readOptionalPhone(id) {
  const raw = document.getElementById(id).value.trim();
  if (!raw) return { ok: true, value: null };
  const cc = document.getElementById(id + "_cc").value.replace(/\D/g, "");
  const digits = raw.replace(/\D/g, "");
  return cc && digits.length >= 4 ? { ok: true, value: "+" + cc + digits } : { ok: false, value: null };
}

export function setPhoneField(id, e164) {
  const { cc, local } = splitE164(e164);
  document.getElementById(id + "_cc").value = cc;
  document.getElementById(id).value = local;
}

/** Debounce that also drops out-of-order responses: a slower earlier request
 *  must never overwrite a newer one's results. */
export function searchBox(input, run, delay = 220) {
  let timer = null, token = 0;
  input.oninput = () => {
    clearTimeout(timer);
    const q = input.value.trim();
    timer = setTimeout(async () => {
      const mine = ++token;
      const result = await run(q);
      if (mine === token) result && result();
    }, delay);
  };
}
