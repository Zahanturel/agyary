"use strict";

/**
 * Where a fire temple is: a map with one pin (DECISIONS D10).
 *
 * Used when a fire temple is added (onboarding) and on "Edit location" from
 * Settings. Three ways to put the pin down, and a drag to put it exactly:
 *  - tap the map (or drag the pin);
 *  - "I'm at the agyari now": the phone's own location;
 *  - "Search address or area": OpenStreetMap, asked by our server, never by
 *    the page (api/routes/places.py);
 *  - "Find on Google": by name, also asked by our server, with the owner's
 *    key; shown only when the server says it has one.
 *
 * The map is Leaflet, kept in the app's own folder and loaded only when a
 * screen shows a map, with OpenStreetMap's tiles (the only outside address the
 * page may load images from; see the CSP in api/main.py). Every failure says
 * what happened: a map that cannot load, a location the phone will not give,
 * a search that does not answer.
 */

import { searchPlaces, googlePlaces, placesOptions } from "./api.js";
import { showError } from "./ui.js";
import { esc } from "./util.js";
import { flagProblems } from "./fielderrors.js";

const LEAFLET = "/mobed-app/vendor/leaflet/";
const TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors';
// India, whole, for a fire temple with no position yet.
const START = { center: [22.5, 79.0], zoom: 4 };
const CLOSE_ZOOM = 17;
const TOWN_ZOOM = 13;
// Beyond this the phone's fix is too rough to trust without a look.
const ROUGH_METRES = 100;

const MAP_FAILED = "The map could not load. Please check your signal and try again.";

let leafletLoading = null;
let googleAsked = null;

/** Whether the server offers "Find on Google". Asked once per visit. */
function googleOffered() {
  if (!googleAsked) {
    googleAsked = placesOptions().then((o) => !!(o && o.google)).catch(() => { googleAsked = null; return false; });
  }
  return googleAsked;
}

/** Leaflet's script and stylesheet, once, the first time a map is shown. */
export function loadLeaflet() {
  if (window.L) return Promise.resolve(window.L);
  if (!leafletLoading) {
    leafletLoading = new Promise((resolve, reject) => {
      if (!document.querySelector('link[data-leaflet]')) {
        const css = document.createElement("link");
        css.rel = "stylesheet";
        css.href = LEAFLET + "leaflet.css";
        css.dataset.leaflet = "1";
        document.head.appendChild(css);
      }
      const script = document.createElement("script");
      script.src = LEAFLET + "leaflet.js";
      script.onload = () => (window.L ? resolve(window.L) : reject(new Error(MAP_FAILED)));
      script.onerror = () => { script.remove(); reject(new Error(MAP_FAILED)); };
      document.head.appendChild(script);
    }).catch((e) => { leafletLoading = null; throw e; });
  }
  return leafletLoading;
}

/** Why the phone did not give its location, in words a mobed can act on. */
export function geolocationMessage(err) {
  switch (err && err.code) {
    case 1:   // PERMISSION_DENIED
      return "Mobed Diary was not allowed to use this phone's location. To use it, allow location for "
        + "this site in your browser's settings and try again, or put the pin on the map yourself.";
    case 2:   // POSITION_UNAVAILABLE
      return "Your phone could not find where it is just now. Try again outdoors or near a window, "
        + "or put the pin on the map yourself.";
    case 3:   // TIMEOUT
      return "Finding your location took too long. Please try again, or put the pin on the map yourself.";
    default:
      return "Your phone's location could not be used. Please put the pin on the map yourself.";
  }
}

// One map at a time: a screen drawn over the last one leaves its map behind
// with nothing to remove it, so the next mount does.
let current = null;

/**
 * Draw the picker into `root`.
 *  opts.initial   - { latitude, longitude, source } or null
 *  opts.suggest() - what to search for when the box is empty (name and city)
 *  opts.tall      - a taller map, for a page that is only the picker
 *  opts.noun      - what the pin is on, in the picker's words (default "the
 *                   fire temple"; a Doongerwadi's admin page says "the place")
 *  opts.hereLabel - the "where my phone is" button (default "I'm at the agyari now")
 * Returns { get(), setSaved(location), destroy() }. get() is the pin as
 * { latitude, longitude }, or null when there is none.
 */
export function mountLocationPicker(root, {
  initial = null, suggest = () => "", tall = false, noun = "the fire temple", hereLabel = "I'm at the fire temple now",
} = {}) {
  if (current) current.destroy();
  root.innerHTML = `
    <div class="loc-picker">
      <label for="lpQuery">Search address or area</label>
      <div class="loc-search">
        <input type="search" id="lpQuery" enterkeyhint="search" autocomplete="off" placeholder="Road, area or town">
        <button type="button" class="small" id="lpSearch">Search</button>
      </div>
      <div id="lpResults" class="loc-results"></div>
      <div class="loc-tools" id="lpTools">
        <button type="button" class="secondary small" id="lpHere">${esc(hereLabel)}</button>
        <button type="button" class="secondary small hidden" id="lpGoogle">Find on Google</button>
      </div>
      <div class="loc-map${tall ? " tall" : ""}" id="lpMap" role="region" aria-label="Map"></div>
      <p class="meta loc-status" id="lpStatus" role="status"></p>
    </div>`;
  const $ = (id) => root.querySelector("#" + id);
  const mapEl = $("lpMap");
  const statusEl = $("lpStatus");
  const resultsEl = $("lpResults");
  const query = $("lpQuery");

  let L = null, map = null, marker = null, pin = null, gone = false, searchToken = 0;
  let saved = initial && initial.latitude != null ? initial : null;

  const say = (text) => { statusEl.textContent = text; };
  const describeSaved = () => {
    if (!saved) say(`No pin yet. Tap the map where ${noun} is, search above, or use “${hereLabel}”.`);
    else if (saved.source === "town") say(`This pin is only the town, not ${noun} itself. Please move it onto ${noun}.`);
    else say(`The pin is on ${noun}. Drag it, or tap the map, to move it.`);
  };

  /** Put the pin at `lat, lon` and say why it is there. */
  function place(lat, lon, why, { zoomIn = false } = {}) {
    if (!map) return;
    const at = L.latLng(lat, lon).wrap();
    pin = { latitude: +at.lat.toFixed(6), longitude: +at.lng.toFixed(6) };
    if (!marker) {
      marker = L.marker(at, { draggable: true, autoPan: true, keyboard: true, title: noun.charAt(0).toUpperCase() + noun.slice(1), alt: "Pin" }).addTo(map);
      marker.on("dragend", () => {
        const p = marker.getLatLng().wrap();
        pin = { latitude: +p.lat.toFixed(6), longitude: +p.lng.toFixed(6) };
        say("Pin moved.");
      });
    } else {
      marker.setLatLng(at);
    }
    if (zoomIn) map.setView(at, Math.max(map.getZoom(), CLOSE_ZOOM));
    else map.panTo(at);
    say(why);
  }

  function showResults(list, q, from) {
    if (!list.length) {
      resultsEl.innerHTML = `<p class="meta">Nothing found for “${esc(q)}”. Try a nearby road or area, or put the pin on the map yourself.</p>`;
      return;
    }
    resultsEl.innerHTML = list.map((r, i) => `
      <div class="search-result" data-i="${i}">
        <div><strong>${esc(r.name)}</strong></div>
        <div class="addr">${esc(r.address)}</div>
      </div>`).join("") + `<p class="meta loc-from">Results from ${esc(from)}</p>`;
    resultsEl.querySelectorAll("[data-i]").forEach((row) => {
      row.onclick = () => {
        const r = list[+row.dataset.i];
        resultsEl.innerHTML = "";
        place(r.latitude, r.longitude, `Pin put at ${r.name}. Drag it onto ${noun} if it is not exactly there.`,
          { zoomIn: true });
        mapEl.scrollIntoView({ block: "center", behavior: "smooth" });
      };
    });
  }

  /** Run one of the searches with what is typed (or the fire temple's name and
   *  city). `ask(q)` returns { results }. */
  async function runSearch(btn, ask, from, emptyMessage) {
    const q = query.value.trim() || (suggest() || "").trim();
    if (q.length < 2) {
      flagProblems(root, [{ target: query, message: emptyMessage }]);
      return;
    }
    if (!query.value.trim()) query.value = q;
    const mine = ++searchToken;
    btn.disabled = true;
    resultsEl.innerHTML = `<p class="meta">Searching...</p>`;
    try {
      const r = await ask(q);
      if (gone || mine !== searchToken) return;
      showResults(r.results || [], q, from);
    } catch (e) {
      if (gone || mine !== searchToken) return;
      resultsEl.innerHTML = "";
      showError(e.message);
    } finally {
      btn.disabled = false;
    }
  }

  const searchBtn = $("lpSearch");
  searchBtn.onclick = () => runSearch(searchBtn, searchPlaces, "OpenStreetMap",
    "Please type an address or area to search for.");
  query.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); searchBtn.click(); }
  });

  const hereBtn = $("lpHere");
  hereBtn.onclick = () => {
    if (!map) return showError(MAP_FAILED);
    if (!window.isSecureContext) {
      return showError("This phone's location can only be used on Mobed Diary's secure (https) address. "
        + "Please put the pin on the map yourself.");
    }
    if (!navigator.geolocation) {
      return showError("This phone or browser cannot share its location. Please put the pin on the map yourself.");
    }
    hereBtn.disabled = true;
    const label = hereBtn.textContent;
    hereBtn.textContent = "Finding where you are...";
    const done = () => { hereBtn.disabled = false; hereBtn.textContent = label; };
    try {
      navigator.geolocation.getCurrentPosition((pos) => {
        done();
        if (gone) return;
        const metres = Math.round(pos.coords.accuracy || 0);
        const rough = !metres || metres > ROUGH_METRES;
        place(pos.coords.latitude, pos.coords.longitude,
          (metres ? `Pin put where your phone is, accurate to about ${metres} m.` : "Pin put where your phone is.")
          + (rough ? ` That is not very exact: please drag the pin onto ${noun} if it is off.` : ""),
          { zoomIn: true });
      }, (err) => {
        done();
        if (!gone) showError(geolocationMessage(err));
      }, { enableHighAccuracy: true, timeout: 20000, maximumAge: 0 });
    } catch (e) {
      done();
      showError(geolocationMessage(null));
    }
  };

  function startMap() {
    mapEl.innerHTML = `<p class="meta loc-map-msg">Loading the map...</p>`;
    loadLeaflet().then((lib) => {
      if (gone) return;
      L = lib;
      mapEl.innerHTML = "";
      L.Icon.Default.imagePath = LEAFLET + "images/";
      map = L.map(mapEl, { scrollWheelZoom: false, worldCopyJump: true });
      L.tileLayer(TILES, { maxZoom: 19, attribution: ATTRIBUTION }).addTo(map);
      if (saved) {
        map.setView([saved.latitude, saved.longitude], saved.source === "pin" ? CLOSE_ZOOM : TOWN_ZOOM);
        place(saved.latitude, saved.longitude, "");
        pin = null;   // nothing new until it is moved
        describeSaved();
      } else {
        map.setView(START.center, START.zoom);
        describeSaved();
      }
      map.on("click", (e) => place(e.latlng.lat, e.latlng.lng, "Pin put where you tapped. Drag it to the exact spot if needed."));
      // Drawn into a box that may only just have been laid out.
      setTimeout(() => map && map.invalidateSize(), 0);
    }).catch((e) => {
      if (gone) return;
      mapEl.innerHTML = `<div class="load-failed loc-map-msg" role="alert"><p><b></b></p>
        <button class="small" type="button" data-retry>Try again</button></div>`;
      mapEl.querySelector("b").textContent = e.message || MAP_FAILED;
      mapEl.querySelector("[data-retry]").onclick = startMap;
      say("");
    });
  }

  const googleBtn = $("lpGoogle");
  googleBtn.onclick = () => runSearch(googleBtn, googlePlaces, "Google",
    `Please type the name of ${noun} to find it on Google.`);
  // Only when the server has a key. Not knowing is the same as no: the button
  // stays hidden, and everything else works without it.
  googleOffered().then((yes) => { if (yes && !gone) googleBtn.classList.remove("hidden"); });

  startMap();

  const api = {
    /** The pin to save: one put down or moved here, else the one it opened with. */
    get() {
      if (pin) return pin;
      return saved ? { latitude: saved.latitude, longitude: saved.longitude } : null;
    },
    /** Whether the pin was put down or moved since it opened (or was last saved). */
    moved() { return !!pin; },
    /** After a save: this is now the fire temple's pin. */
    setSaved(location) {
      saved = location;
      pin = null;
      describeSaved();
    },
    destroy() {
      gone = true;
      if (map) { map.remove(); map = null; }
      if (current === api) current = null;
    },
  };
  current = api;
  return api;
}
