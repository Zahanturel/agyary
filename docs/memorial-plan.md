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
- Parab = the day whose Roj is named like the Mah. Mah 10 is Dae-Dadar
  (22 Oct 2026; earlier Dae-Pa-Adar) and the Roj that shares the name is Roj 1
  (Hormazd), so that is its Parab.
  Offered as "all Parabs" or "Fravardin and
  Tir only" (some families book only those two). Each Parab comes round once
  a year, so it is a repeating series like the yearly one.
- Monthly, yearly and Parabs have NO default length. The mobed must choose
  how many months / years at creation; the API refuses a series without it.
  "N years" of Parabs is day 2 through the Nth anniversary (day 360*N + 1),
  i.e. each Parab exactly N times.
- Masiso, Bamsi, Chamsi and Varsi are month multiples, which is what the
  names mean: the monthly (30th day), two months (60th), six months (180th)
  and a year (360th), each on the SAME Roj. The Deci (29th, 59th, 179th,
  359th) is the day before each. Masiso is therefore the first monthly and
  Varsi the first yearly: when both are chosen the date is listed once, under
  the family's own name. (The opening is different: the 10th is the literal
  10th day with the death day as day 1.)
- One observance per date. When several land on the same day the highest
  wins: the opening days, then yearly (Varsi included), then monthly (Masiso,
  Bamsi, Chamsi included), then a Deci, then a Parab. A Parab hidden under a
  higher one is not shown elsewhere.
- A death on a Gatha day: that Gatha day is day 1 and the opening carries on
  from it. The monthly is then Roj Hormazd (Roj 1) of each Mah, from Mah 2 of
  the next year (so Masiso is Mah 2 Roj 1, Bamsi Mah 3 Roj 1), and the yearly
  is the SAME Gatha day each year (so Varsi is that Gatha day a year on). In
  a Fasli year without that Gatha (Fasli is no longer offered, D5; this matters
  only for a memorial already saved in it, and the sixth exists only in leap cycles) the
  last Gatha of that year is used. The Deci is always the actual day before.

**Died more than a year ago** (29 Oct 2026; most of a mobed's behdins are old people whose
monthly and yearly prayers have run for years)
- The form first asks "Did they pass away more than a year ago?". If yes, only the Roj and Mah of
  the death are given: no date and no Parsi year (the optional year field is gone from the form).
- The opening days and the named days (5th to 9th, Dasmi, the Decis, Masiso, Bamsi, Chamsi, Varsi)
  are over, so they are listed but lighter, marked "already passed", and cannot be ticked. What
  repeats stays: monthly, yearly, Roj Fravardin, Parabs, the birthday. Everything runs from today.
- The same greying applies to a recent death, day by day, as each named day goes by: the server says
  which have passed (`POST .../memorials/day-status`, `named_days_passed`).
- The death date stored for such a memorial is a stand-in (the latest such Roj and Mah at least 361
  days back, `memorials.died_over_a_year_ago` = true). It is never shown: the memorial page, the
  review, the WhatsApp message and the PDF say "passed away more than a year ago" / "Remembered on
  Roj X, Mah Y". The monthly and yearly days are labelled plainly "Monthly" / "Yearly", never
  "Month 14", because that count would be made up.
- Series can run for decades: up to 1200 months, 100 years, 1200 Parabs, 2500 observances in all.
  Quick picks (10, 25, 50, 100 years) fill the length in one tap. Memorials made earlier are left as
  they are.

**Calendar**
- A memorial is counted in the calendar the family keeps - chosen on the form,
  defaulting to the mobed's own primary calendar, stored with the memorial. It
  is NOT the fire temple's: the calendars disagree about which day is a Parab
  and where the Gatha days fall, and the mobed sees every date in their own.

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

1. **Gujarati spellings** (Dasmi, Deci, Masiso, Bamsi, Chamsi, Varsi, and the
   Parab names). Confirmed fine for now; all in `NAMED_DAYS`.
2. **Gatha-death monthly starting point.** The first monthly (Masiso) after a
   Gatha death is Mah 2 Roj 1 of the next year, about a month on. Mah 1 Roj 1
   would be only a few days after the death, so it was not used. Confirm.
3. **Optional time on ORDINARY bookings.** Parked, not needed now that
   memorial observances are their own rows. If wanted later: add
   `bookings.has_time` (default true), store 00:00 IST when untimed, and fix
   the sunrise anchor, conflict check, slip and My Day "upcoming" query.

## Build order

1. Engine (done) 2. Memorial tables + Baaj migration (done, verified on a
   scratch DB: upgrade, downgrade, no model drift)
3. Service layer + API + tests (done: preview, create, list, edit one
   observance, delete, calendar feed + closing notice, privacy)
4. UI (done, checked in the browser on a scratch copy): Behdins as a bottom
   tab (the Machi board, once a separate app, is now a tab of the same app), memorials on
   the behdin page, new-memorial form with a date preview before saving,
   memorial page with per-observance edit, green memorial category on the
   calendar, pinned solid "Memorial closes today" notice.
5. Retire the machi-only monthly/yearly dropdown (migrate existing rules)
