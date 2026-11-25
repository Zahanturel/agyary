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
