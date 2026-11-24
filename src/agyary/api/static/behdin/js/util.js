"use strict";

// The few small helpers the behdin app needs. The shared util.js of Mobed Diary also pulls in that
// app's own api and state, so these are written out here instead of imported.

export function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, c => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// A title typed before a name ("Er. Hormuz ...") is not the first name.
const NAME_PREFIXES = new Set(["er", "ervad", "mobed", "mobedji", "dasturji", "dr", "behdin",
  "osta", "osti", "khud", "mr", "mrs", "ms"]);

/** The first name, for greeting a person: a title before it is skipped. */
export function firstName(full) {
  const words = String(full || "").trim().split(/\s+/).filter(Boolean);
  let i = 0;
  while (i < words.length && NAME_PREFIXES.has(words[i].replace(/\./g, "").toLowerCase())) i += 1;
  return words[i] || words.join(" ");
}

const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const two = n => String(n).padStart(2, "0");

/** Today in India as "2026-11-25": the Parsi day is anchored there, whatever the phone's clock says. */
export function todayIst() {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit",
  }).format(new Date());
}

/** A day as day/month/year, the way every date shows in the app: "25/11/2026". */
export function gregShort(ymd) {
  const [y, m, d] = ymd.split("-").map(Number);
  return `${two(d)}/${two(m)}/${y}`;
}

export function weekdayOf(ymd) {
  const [y, m, d] = ymd.split("-").map(Number);
  return WEEKDAYS[new Date(Date.UTC(y, m - 1, d)).getUTCDay()];
}
