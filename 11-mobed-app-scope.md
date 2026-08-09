# Mobed app — scope

Status: **agreed and implemented**, except §8.1 (OTP template), which waits
on the WhatsApp account.

This document is the definition of the mobed app. If something is not in
here, it does not ship in the mobed app. If something in here is wrong,
the fix is to change this document first.

---

## 1. What this app is for

A mobed manages **their own events** in one place. That is the whole
product. It is the free tier of a planned tiered architecture; an agyari
management system will follow, once actual panthakies have been consulted
about what they need.

**Vocabulary:** the user-facing word is **event**, never "booking".
Internally the models are still `Booking` and `Machi` — that is a
persistence detail and does not surface in the UI.

### Non-goals (explicitly not in this app)

- Agyari-wide views. A mobed does not need to see every machi at their
  fire temple. A machi they are responsible for is simply one of their
  events.
- Invites / role management, service-catalog editing, fire-temple detail
  editing. Code stays in the tree but is unreachable — no route, no
  navigation, no entry point.
- The behdin-facing WhatsApp bot (conversation flows, webhook, send
  worker). Not used yet.

---

## 2. Screens

There are five. No bottom tab bar.

### 2.1 Login

Phone number → 6-digit code → signed in. Unchanged from current
implementation.

### 2.2 Calendar — the home screen

The only main screen. Shows **this mobed's own events**.

| View | Contents |
|---|---|
| **Day** | That day's events |
| **Week** | The week's events, grouped by day, scrollable |
| **Month** | Day grid with events shown on the cells; tapping a day switches to Day view for that day |

- Day / Week / Month toggle.
- Every date shows the Gregorian day, with the mobed's **primary calendar**
  reading beneath it (§4).
- Add-event control on this screen.
- Top right: an **icon** (menu). Not the word "Settings".

### 2.3 Menu (behind the top-right icon)

Three sections:

1. **You** — name, phone number, agyari name + address.
2. **Calendar** — which calendar is primary (§4).
3. **Behdins** — a "Manage your behdins" bar with an add control on its
   right. Tapping the bar opens the behdin list.

### 2.4 Behdin list

- Rows: name and number.
- **Exactly one** add control — top-right or bottom-right, never both.
- Tapping a row opens that behdin.

### 2.5 Behdin detail

- Name.
- Number — tappable, opens the phone dialler (`tel:`).
- Name pairs and farmayeshne, editable here.

---

## 3. Events

A mobed creates and edits their own events. Two kinds:

- **Service** — has a time.
- **Machi** — has a Geh instead of a time, and a purpose of patet or
  tandarosti. The backend enforces one machi per Geh per day per fire
  temple; a clash returns concrete alternative slots, which the UI shows.

There is no Geh slot board. A machi is added the same way any event is.

---

## 4. Calendar systems

All four are supported: Gregorian, Shenshai, Kadmi, Fasli. Mobeds work
across all of them because behdins do.

- **Gregorian** is always the top-line date.
- **Primary calendar** is the Parsi system shown beneath every date and
  used for Roj/Mah entry. Defaults to **Shenshai**; the mobed can set it
  to Kadmi or Fasli.
- The remaining systems stay available on demand (tap a day to see that
  day in every system).

### 4.1 What "changes everywhere" must mean

Changing the primary calendar must change **every** surface that renders a
Parsi date. This is the verification matrix, and each row is to be checked
against a real running app for Shenshai, Kadmi and Fasli:

| # | Surface | Verified |
|---|---|---|
| 1 | Day view — the reading under the Gregorian date | yes |
| 2 | Week view — each day's reading | yes (was missing entirely; added) |
| 3 | Month grid — each cell's Roj/Gatha name | yes |
| 4 | Month title — Mah name and YZ year | yes |
| 5 | Month navigation — stepping follows the primary system's months | yes |
| 6 | Jump-to-date — the Roj/Mah pickers, and the date they resolve to | yes |
| 7 | New Event — the Roj/Mah fields and their sync with the date | yes (was reading the fire temple's system; fixed) |
| 8 | Event confirm screen — the Parsi reading shown | yes |
| 9 | Event detail / slip — the "when" line | yes (test + browser) |
| 10 | The tap-a-day panel — primary listed first | yes |

Walked in a real browser with the primary set to Kadmi, and the slip checked
across all three systems: the same event reads *Roj Hormazd, Mah Ardibehesht*
in Kadmi, *Roj Hormazd, Mah Fravardin* in Shenshai and *Roj Zamyad, Mah
Amardad* in Fasli. Also covered by an automated test that asserts the three
readings genuinely differ, so a slip that silently stopped following the
setting would fail the suite rather than the eye.

### 4.2 A decision this forces (needs your call — see §7)

`Agyary.calendar_system` is a *different thing* from the mobed's primary
calendar. It decides which system's Roj/Mah is **stamped onto the stored
record**, and exists so the historical record is stable. It is per fire
temple and is not a display setting.

So if a mobed sets Kadmi as primary and types "Roj Bahman, Mah Fravardin",
those are *Kadmi* Roj/Mah. The proposed handling:

- Roj/Mah entry is interpreted in the **mobed's primary** system.
- It is resolved to a **Gregorian date**, which is the value sent to the
  server.
- The server derives and stamps Roj/Mah in the **fire temple's** system,
  as it does today.

**Decided:** the printed slip follows the **mobed's primary calendar**, not
the stored reading. A mobed prints, tears and uses these slips themselves,
so the slip has to read the way they read. This makes the primary setting
genuinely change every surface, row 9 of the matrix included.

Implementation note: the slip endpoints currently render the stored
Roj/Mah. They will instead convert the event's Gregorian date into the
requesting mobed's primary system. The stored values are untouched — they
remain the stable historical record; only the rendering follows the reader.

---

## 5. What is removed from the current build

- Bottom tab bar.
- Separate "My day" and "Calendar" screens — merged into one.
- The Machi board Day-view Geh grid, and the agyari-wide machi fetch.
- Behdins as a top-level tab (moves into the menu).
- "Settings" as a word in the header (becomes an icon).
- Duplicate add-behdin controls (button *and* FAB) — one only.
- Invites, service catalog, fire-temple editing — unreachable.

---

## 6. Test plan

Automated where it can be, manual where it cannot:

1. Backend test suite stays green (currently 266).
2. The §4.1 matrix, walked in a real browser, for each of the three
   primary systems.
3. Event creation end to end: service with a time, and machi with a Geh
   including a deliberate slot clash.
4. Behdin: add from both entry points, edit, edit saved names, verify the
   `tel:` link.
5. Menu: every section present and correct; nothing management-shaped
   reachable by typing a URL.

---

## 7. Decisions taken

**Sign-in delivery.** WhatsApp is used for sign-in codes only. The
behdin-facing bot — conversation flows, inbound webhook, send worker —
stays off and unreachable. WhatsApp Business account to be set up.

**Slip reading.** Follows the mobed's primary calendar (§4.2).

## 8. Known work this creates

**8.1 OTP must be sent as a template, not text.** WhatsApp only permits
business-initiated messages through a pre-approved template. A mobed
signing in has not messaged us first, so no 24-hour service window is
open and a plain `type: "text"` send is rejected. An **Authentication**
category template is required (it also supports a one-tap copy-code
button). `services/otp_delivery.py` currently sends plain text and must
be changed to a template send once the template name and language are
known. Until then, local development is unaffected — the code is logged,
not sent.

**8.2 Slip rendering** — see §4.2 implementation note.

**8.3 Primary calendar plumbing.** The event form currently derives its
Roj/Mah from the *fire temple's* system rather than the mobed's primary.
That is row 7 of the matrix and is a real bug against this scope.
