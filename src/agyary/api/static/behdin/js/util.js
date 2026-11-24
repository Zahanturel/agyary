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

export const MAH_NAMES = ["Fravardin", "Ardibehesht", "Khordad", "Tir", "Amardad", "Shahrevar",
  "Meher", "Avan", "Adar", "Dae-Dadar", "Bahman", "Aspandard"];
export const ROJ_NAMES = ["Hormazd", "Bahman", "Ardibehesht", "Shahrevar", "Aspandard", "Khordad",
  "Amardad", "Dae-Pa-Adar", "Adar", "Avan", "Khorshed", "Mohor", "Tir", "Gosh",
  "Dae-Pa-Meher", "Meher", "Sarosh", "Rashne", "Fravardin", "Behram", "Ram",
  "Govad", "Dae-Pa-Din", "Din", "Ashishvangh", "Ashtad", "Asman", "Zamyad",
  "Mareshpand", "Aneran"];
export const GATHAS = ["Ahunavad", "Ushtavad", "Spentamad", "Vohukhshathra", "Vahishtoisht"];
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
  "October", "November", "December"];

export function monthName(m) { return MONTHS[m - 1]; }

/** "2026-11-25" from the parts (month 1 to 12). */
export function ymdOf(y, m, d) { return `${y}-${two(m)}-${two(d)}`; }

/** The same day moved by `n` days (calendar arithmetic only, no clock). */
export function addDays(ymd, n) {
  const [y, m, d] = ymd.split("-").map(Number);
  const t = new Date(Date.UTC(y, m - 1, d + n));
  return ymdOf(t.getUTCFullYear(), t.getUTCMonth() + 1, t.getUTCDate());
}

/** A Parsi day as the calendar API gives it, in words: "Roj Hormazd, Mah Fravardin". */
export function parsiWords(p) {
  if (!p) return "";
  if (p.is_gatha) return `${p.gatha_name || "Extra day"} (Gatha)`;
  return `Roj ${p.roj_name}, Mah ${p.mah_name}`;
}

/** "Wednesday 25/11/2026". */
export function longDay(ymd) { return `${weekdayOf(ymd)} ${gregShort(ymd)}`; }

/** The name in a calendar item for a departed ("Dasmu - Meherbai"): the server writes "(name not known)" when none was given. */
export function departedName(it) {
  const prefix = `${it.label} - `;
  const name = it.title.startsWith(prefix) ? it.title.slice(prefix.length) : it.title;
  return name === "(name not known)" ? "Name not known" : name;
}

export const KIND_LABELS = { atash_behram: "Atash Behram", adaran: "Adaran", dadgah: "Dadgah" };
export const EVENT_KINDS = [["birthday", "Birthday"], ["navjote", "Navjote"], ["anniversary", "Anniversary"], ["other", "Other"]];
export function eventKindLabel(kind) {
  const hit = EVENT_KINDS.find(([k]) => k === kind);
  return hit ? hit[1] : "Event";
}
