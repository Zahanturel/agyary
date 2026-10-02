# Memorials (behdin management, core module)

Working notes. Decisions are settled with the mobed; the ON HOLD list is what
is deliberately not built yet and why.

## What it is

A behdin may have one or more **memorials**: a departed person, the death
date (Roj / Mah / Year + calendar system), the observances the family chose,
and how long each repeating series runs. The observances become ordinary
bookings on the calendar, tagged with the memorial.

## Settled

**Counting** (engine: `src/agyary/calendar/memorial.py`, tested)
- The day of death is day 1.
- Opening days (1-10, and the 10th on its own) are LITERAL calendar days,
  Gatha days included.
- Everything else is counted by Roj and Mah only; Gatha days are not counted.
  29th/30th, 59th/60th, 179th/180th, 359th/360th, monthly (day 31, 61, ...),
  yearly (day 361, 721, ...).
- Choices offered: opening = "days 1 to 10" or "10th only" (days 1-4 are not
  a separate option); then any of the named days; monthly; yearly; Parabs.
- Parab = the Roj named like the Mah. Offered as "all Parabs" or "Fravardin
  and Tir only" (some families book only those two).
- Repeating series (monthly, yearly, Parabs) have NO default length. The
  mobed must choose one at creation; the API must refuse a series without it.
- Dates already past are kept on the calendar (a diary, no payments yet).

**What an observance is**
- NOT a booking. Each observance is a row of its own (`memorial_observances`)
  carrying any subset of Afringan, Farokshi, Baaj, an optional time and a
  note. A booking has one service, a mobed to accept it and a slip; none of
  that applies, and the mobeds say they barely use slips. So `bookings` is
  untouched.
- The service set is chosen once at creation and applied to every
  observance; each one is editable individually afterwards.
- "Baaj" is in the default service catalog (next to Farokshi) and was
  backfilled into existing fire temples. "Afringan" keeps its name.
- Time is optional and normally blank. Focus is the recurring schedule;
  time and slips are not a priority (mobeds keep their own name books).

**Closing notice**
- On the last observance's day, a pinned, differently-coloured item at the
  top of the day view and marked in the month grid: no upcoming bookings
  after this; the memorial is closed. Its own category, always on top, no
  fixed time. On-screen only (no WhatsApp). Then the memorial is `completed`.

**Structure**
- Behdins become a top-level module, not buried in the menu.
- Behdin page becomes the hub: details, saved names, memorials (next due,
  progress), history.
- Wording changes across the app are OUT OF SCOPE for now, except the new
  notices.

## ON HOLD

1. **Death on a Gatha day.** Has special rules the mobed must confirm first.
   The engine refuses it (`ValueError`) rather than guess.
2. **Dae Parab.** No Roj is called plain "Dae" (Dae-Pa-Adar, Dae-Pa-Meher and
   Dae-Pa-Din are other days). Which Roj is Dae's Parab is unconfirmed. It is
   left OUT of "all Parabs" for now, so "all" is currently 11 of 12 Mahs.
   Must be settled before "all Parabs" is shown to a mobed.
3. **Gujarati spellings** (Dasmi, Deci, Masiso, Bamsi, Chamsi, Varsi). Ours to
   establish; provisional, all in `NAMED_DAYS`.
4. **Day 30 convention.** Implemented as the Roj BEFORE the monthly Roj
   (death day = day 1, counted by Roj and Mah). Confirm this matches how
   Masiso is actually observed.
5. **Parab on the same day as another observance** (e.g. a monthly landing on
   a Parab) currently stays two entries. Decide at the database step whether
   to merge into one booking.
6. **Optional time on ORDINARY bookings.** Parked, not needed now that
   memorial observances are their own rows. If wanted later: add
   `bookings.has_time` (default true), store 00:00 IST when untimed, and fix
   the sunrise anchor, conflict check, slip and My Day "upcoming" query.

## Build order

1. Engine (done) 2. Memorial tables + Baaj migration (done, verified on a
   scratch DB: upgrade, downgrade, no model drift)
3. Service layer + API + tests (done: preview, create, list, edit one
   observance, delete, calendar feed + closing notice, privacy)
5. UI: nav, behdin hub, memorial flow, closing notice
6. Retire the machi-only monthly/yearly dropdown (migrate existing rules)
