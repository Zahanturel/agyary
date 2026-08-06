# Mobed-side v0 — ship this, WhatsApp/behdin side parked

We're deliberately shipping mobed-only. No behdin-facing WhatsApp work this pass —
that's parked pending a real decision on numbers/verification/pricing after talking
to trustees. Everything below is scoped to: give mobeds a working calendar tool and
a printer, nothing else, as fast as correctly possible.

## Read first

- `05-converged-design-notes.md` — still the authoritative behavior spec for
  machi/services logic, slip fields, shared-core discipline. Ignore its WhatsApp/
  Flows sections for this pass; everything else still applies.
- The actual code in `src/agyary/` — **a real backend for this already exists**,
  built in a previous pass. Don't replan from zero. Read `src/agyary/api/routes/
  mobed.py`, `src/agyary/services/mobed_auth.py`, `src/agyary/services/
  mobed_dashboard.py`, `src/agyary/api/static/mobed.html` before touching anything.
  Verify what's described below against current code — it may have drifted since
  this doc was written.

## What already exists — keep and reuse, do not rebuild

- `GET /agyaries/search` — trigram-backed agyari search. Reuse for onboarding.
- `POST /agyaries/{id}/join` — join an agyari.
- `GET /my-day` — merged-across-agyaries event list for the logged-in mobed.
- `GET /agyaries/{id}/machi-board` — per-agyari machi view.
- `POST /agyaries/{id}/manual-add/machi` and `.../manual-add/booking` — already
  route through the shared slot-check core per doc 05's non-negotiable. Confirm
  this is still true before changing anything nearby; don't let a refactor
  accidentally introduce a second code path.
- `GET /agyaries/{id}/machis/{id}/slip` and `.../bookings/{id}/slip` — slip data.
- `POST /bookings/{id}/accept` / `.../decline`.

All of this stays. The work below is additive/subtractive around it, not a rewrite.

## Rip out: OTP

`POST /auth/request-otp` and `POST /auth/verify-otp` (in `mobed.py`, backed by
`services/mobed_auth.py`) go away entirely for this pass. Decision, not an
oversight: we don't need phone-verified identity yet, we need agyari/mobed data
isolation, and OTP was solving a problem (proving phone ownership) we've decided
not to have right now.

Replace with: a mobed enters name + phone number once. Phone number is the
natural unique key for the `User`/mobed record (also the eventual key WhatsApp
will use later, so this isn't throwaway). No verification step. On successful
entry, issue the same session token/cookie the app already uses post-OTP today
— just skip the code-verification step that currently gates it. Returning
visits: existing session cookie carries them straight in; if it's gone (new
device, cleared storage), re-entering name + phone logs them back in, no
verification, same as the first time.

Accepted risk, stated plainly rather than hidden: someone who knows another
mobed's phone number could type it and see that mobed's calendar. At current
scale (you are personally onboarding every mobed) this is a real but acceptable
tradeoff. Revisit if/when onboarding stops being personal and starts being
self-serve at a scale where that risk stops being negligible.

Placeholder fix while touching this screen: the current name field placeholder
(`Er. Zahan Patel`) should just be a generic example, not a specific-looking
real name — something like `e.g. Er. Firstname Lastname` or just remove the
honorific and use `Full name`.

## Add: real agyari seed data, not demo-only

`audit-flowcharts/list_fire_temples.xls` has 167 real fire temples worldwide
(name, type, address, town, state/country, Roj/Mah/consecration year — columns
start at row index 4 after two header rows, some fields sparse, ~9 duplicate
names to dedupe before import). Load these into `agyaries` at a new status of
**unclaimed** — no `wa_phone_number_id`, not searchable-and-bookable until a
mobed claims one.

This requires one schema change: `Agyary` currently has only `is_active`
(boolean). Add a proper status distinction — `unclaimed` (seeded, no mobed yet),
`active` (claimed and set up). Don't overload `is_active` to mean both "exists"
and "has been set up by a real mobed" — those are different facts.

Also add now, schema-only, unused this pass: an `auto_booking_enabled` boolean
on `Agyary`, default false. This is the WhatsApp-behdin-self-service toggle from
the parked discussion — cheap to add the column now while doing other agyari
schema work, avoids a second migration later. Nothing reads or writes it yet.

## Add: first-mobed-activates-agyari flow

When a mobed searches and joins an agyari currently in `unclaimed` status,
insert one extra step before landing in the normal app: confirm/correct the
agyari's name, city/address, and current phone contact (the seed data is from
2012 and may be stale — a temple may have moved, closed, or changed contact
details). On submit, flip the agyari to `active`. This is the concrete
replacement for gap F1 — an agyari can't be functional for booking until a real
person has actually vouched for and set it up, and this step is also your
mechanism for building your own concrete, current-as-of-today database out of
the stale 2012 seed list.

If a mobed searches and finds nothing (agyari not in the seed list at all),
existing creation-fallback logic applies — same activation step, just starting
from a blank form instead of a pre-filled one.

## Rebuild: frontend, from list/card view to actual calendar view

Current `mobed.html` renders My Day and Machi Board as flat stacked cards, no
date navigation. That's not what we're shipping. Rebuild as:

- **My Day**: a real calendar view — day and week toggle, navigable by both
  Gregorian date and Roj/Mah/Year (same date, two ways of reading it, already
  computed elsewhere in the codebase — reuse, don't recompute). Each event on
  the calendar shows at minimum event name and booked-by name; tapping opens
  the full slip. A `+` control on the day/week view opens the existing add-event
  form.
- **Machi Board**: per-agyari (switchable via the existing agyari-switch UI if
  the mobed belongs to more than one), one day at a time, showing all five geh
  slots. Empty geh shows as empty/bookable; filled geh shows name + event,
  tapping opens the full slip.
- **Slip**: single shared view for both machi and booking slips (mostly already
  built), with two actions — **Edit** and **Print**. Edit returns to the
  add/edit form pre-filled; saving refreshes the slip in place; a back control
  returns to wherever the slip was opened from (calendar or Machi Board).
- **Edit must call the same shared slot-check core as create.** If a mobed
  edits a machi's day/geh, re-validate slot availability exactly as if it were
  a new booking — don't let edit be a raw update that can silently collide with
  another machi already on that slot.

Two pages total, plus the slip as a shared sub-view. No third page.

## Explicitly not in this pass

WhatsApp Flows, behdin-facing anything, the shared-vs-per-agyari number
question, business/pricing model, services-flow reordering (priest-first vs
service-first). Don't let any of these creep in because they're adjacent to
something you're touching — they're parked on purpose.

## Plan → execute → review → report

Same discipline as every prior pass: write a short module plan validated
against actual current code before starting, checkpoint between modules,
verify the shared slot-check core has exactly one call site for machi and one
for the booking-conflict check after all changes, confirm existing tests still
pass, then report plainly what shipped, what deviated from this doc and why,
and what's still open.
