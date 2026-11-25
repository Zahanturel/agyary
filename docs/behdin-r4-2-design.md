# R4.2: asking an agyari for a service (design note, 25 Nov 2026)

Part of [behdin-app-plan.md](behdin-app-plan.md); owner's answers in DECISIONS (R4.2 amendment). Research and
wording ideas: r4-behdin-design.md sections 5.3 to 5.5 (superseded framing, useful details).

## The flow

1. The person opens "Ask for a prayer" (from Home, from their agyari, or from a memorial) and picks an agyari: their
   own by default, or any other (R4.1's list). Only agyaries that take asks can be asked.
2. One question per screen: what (the agyari's services with the usual price or "Ask the agyari for the price"), what
   for (Gujrela nu / Khushali nu / Hama Anjuman), when (a date with Roj and Mah, then the geh or the time as the
   service needs), where (at the agyari, or at home where the service allows: area only), the names to pray
   (from their saved names), a note (max 200 characters, no links, numbers or @-handles), whether it repeats
   (once, or on a rhythm like the mobed side's repeating services), or, from a memorial, which of its dates.
3. Review: "Your name and number go to <agyari>'s panthaky only if they accept." Send.
4. The ask appears in "My asks" (Waiting, Accepted, Can't take it, Cancelled, No answer yet) and in the panthaky's
   Requests tab under "Asks from people", with the service, date, Roj/Mah, geh, area, names, note and the person's
   first name; never the number until accepted.
5. The panthaky accepts or rejects. Accept: the person becomes a record in the panthaky's own book (name and number
   shared with them only now), and the booking, repeating series or memorial is made in their diary as if they had
   entered it themselves; the person is told in the app. Reject: the person is told, with "Ask another agyari" (copies the
   ask). Nobody acts in 24 hours: the person is told "No answer yet", with "Ask another agyari". The person cancels
   any time before the day; the panthaky is told and the booking reads "Cancelled by the person" and stays (D8).

## Data (new, one migration; wiped by erasure.py and account.py)

`agyaries.takes_asks` (bool, default false); `service_asks` (person's user_id cascade, agyary_id, service_id, purpose,
date, geh or time, where, area, names, note, repeat rule or memorial id with chosen dates, status, timestamps,
decided_by, the booking/machi/memorial it became, copied_from_id); in-app notices for people (the existing notice
table, a `/api/behdin/notifications` route). Prices: `services.default_price` already exists; a Settings card sets it.

## Rules

D2: no number before accept. D6: deleting the account removes the person's asks and notices (the panthaky's diary entries
made at accept stay as that mobed's own records, with the person's number only if they consented by asking). D8: nothing
deleted by age. Rate limits per person (asks a day, open asks per person per agyari). Plain wording; the two apps never
name each other. No WhatsApp sent in R4.2 (R4.4 adds the switches): in-app notices and phone push only.

## Redesign changes, backend step 1 (25 Nov 2026)

- Wording: "ask" becomes "request" in every message and notice (Pending, Confirmed, Declined, Cancelled; "Reason: <text>"); API names are unchanged.
- Setting up first: `GET /api/mobed/agyaries/{id}/asks-setting` also returns the services that will be offered (the active ones of the diary's catalog) with their prices and `ready`; switching on is refused (409, "Enter a price for every service first.") until every offered service has a price. While on, a price cannot be cleared, an unpriced service cannot be switched on, and the last service cannot be switched off (409). Off is always allowed.
- People are shown only fire temples that take requests and have a confirmed panthaky whose access is on: `POST /api/behdin/agyaries/find {town?, q?, lat?, lng?}` (town first, then town, then name; a distance only for an exact pin and only when a position is sent) and `GET /api/behdin/agyaries/towns`. `POST /agyaries/nearby` is removed. A service with no price is never offered to people.
- A confirmed request follows the fire temple's diary (new status `cancelled_by_fire_temple`, new `changed_at`): deleting the booking, machi or memorial, or stopping a series, cancels it; changing the date, time or geh (or a memorial's dates) marks it changed. Each tells the person ("Cancelled by <fire temple>: <service> on <date>", "Changed by <fire temple>: <service>, now <date>"), in the app and by phone. One hook pair in `services/service_asks.py` (`fire_temple_removed`, `fire_temple_changed`) is called from each place. The request and `/me/calendar` read the date, time, geh and memorial dates from what the diary holds now; `/me/calendar` now includes confirmed requests (source "request").

## Redesign, backend step 2: a request of several prayers (25 Nov 2026)

One request = one fire temple + `items[]` + typed `names[]` + a status. The free note is gone (API, model and
column). Paths are unchanged (`/api/behdin/me/asks*`, `/api/mobed/agyaries/{id}/asks*`); `GET /api/behdin/agyaries/{id}/asking`
is replaced by `/offering`. Migration `a7c8d9e0f1b2` moves each old request into one item (a memorial keeps its old choices under
`legacy`, names become plain text) and drops the old columns; going back refuses while any request exists. The free note held
only what was copied onto the diary entry when confirmed, so nothing else is lost.

**Offering** `GET /api/behdin/agyaries/{id}/offering` (only meaningful for a listed fire temple; `takes_requests` false otherwise, with
`message` "Not taking requests yet" and no services):
`{id, name, city, kind, takes_requests, message, services:[{id, type:"service", name, price, by_geh}],
memorial:{type:"memorial", name:"Memorial", price:null, prayers:[...]}|null, gehs:[{geh,name}], repeats:{monthly:{max:120}, yearly:{max:60}}}`.
Services shown are the active ones with a price. The memorial item appears when the catalog has Afringan, Farokshi or Baaj; those
are the prayers a confirmed memorial is made of.

**Create** `POST /api/behdin/me/asks`:
`{agyary_id, names:["..."], items:[ item, ... ]}` (1 to 10 items), where an item is
`{service_id, date, time?, geh?, purpose?, recurring?, recurring_count?}` for a service (Machi needs `geh`, never a time;
any other service may leave `time` out; `recurring` is `"monthly"|"yearly"` and `recurring_count` 2..120 / 2..60 or none, exactly the
"+ Add" options and limits; no purpose question: default Gujrela nu, Tandarosti for Machi) or
`{type:"memorial", death_date, departed_name?, recurring?, recurring_count?}` (name may be left out: "(name not known)"; a repeat
needs its count). Limits: 5 requests a day, 3 pending per fire temple, 20 names of 80 letters.

**Person's request** (`POST/GET /me/asks`, `GET /me/asks/{id}`, `cancel`, `ask-another {agyary_id}`):
`{id, status, label, no_answer, changed, changed_at, names, items:[item view], total, total_is_estimate, reject_reason,
created_at, decided_at, copied_from_id, agyari:{id,name,city}, can_cancel, can_ask_another}`;
item view: `{id, type:"service"|"memorial", kind:"single"|"repeating"|"memorial", service:{id,name}|null, name, date, date_text,
parsi, geh, geh_name, time (null = open), time_open, repeat:{recurring,recurring_count}|null, memorial:{departed_name, name_known,
death_date, death_date_text, recurring, recurring_count, dates:[{code,label,date,date_text,parsi}]}|null, state, changed,
price, times, total, estimate}`. `price` is what the fire temple asked when the request was made; `total` of a repeat is price x count
(a repeat with no end counts once), `times` its count; a memorial has no price. `total` is the sum of the items still standing (null
when nothing is priced) and `total_is_estimate` is true when any item repeats or is a memorial. Once confirmed, each item's `date`,
`time`, `geh` (and a memorial's `dates`) are read from the diary entry it made.

**Panthaky** `GET /api/mobed/agyaries/{id}/asks` -> `{waiting, asks:[request view + person:{first_name}, customer_id]}` (same
request and item view; never a number); `POST .../asks/{ask_id}/accept` with optional `{times:{"<item id>":"HH:MM"}}` confirms the WHOLE
request in one transaction (one diary entry per item: booking, machi, repeating series or memorial; names are made the family's living
names on each entry; an item whose time was left open needs its time here, else 409 "Enter a time for <service> on <date>.", and any
refusal by the diary, such as a geh already held, leaves nothing made) and returns `{ask_id, customer_id, skipped, items:[{id,
booking_id, machi_id, memorial_id}], ask}`; `.../reject {reason?}` declines the whole request.

**Memorial on confirm:** the diary's own flow with its defaults: no opening, the named days Dasmu (10), Masiso (30) and Varsi (360), a
monthly or yearly series if the person chose one, the catalog's memorial prayers, nothing booked before today; the panthaky changes any of
it afterwards as for any memorial.

**Following the diary (per item):** an item whose booking, machi, memorial or series the fire temple deletes or stops is flagged
(`state: "cancelled_by_fire_temple"`). If it was the last standing item the request becomes `cancelled_by_fire_temple`; if others stand
the request stays confirmed, is marked `changed` ("Changed by <fire temple>: <service> on <date> cancelled") and the item is flagged.
A changed day, time, geh or memorial date flags the item `changed` and the request `changed`. Calendar and request views leave out gone items.
