# The behdin app (the second app): plan, 25 Nov 2026

**Status: decided by the owner on 25 Nov 2026, nothing built yet.** It replaces the framing of
`docs/r4-behdin-design.md` (22 Nov), which was written around "families asking for services" and is too narrow:
use that document only for its research notes (prices, cancellation, DPDP, abroad, privacy risks).

## What it is

A **separate app for everyone**: any Parsi person, whether they ever ask for a prayer or not. Own name and icon,
same system and same accounts as the mobed app. Mobed Diary 1.0 (the mobed, panthaky and Doongerwadi side, tag
`v1.0`, 25 Nov 2026) stays as it is; this is the next system. The trust system comes after it.

## Decisions (owner, 25 Nov 2026)

1. **One person per phone number, with roles** (behdin, mobed, Doongerwadi manager, later trustee). Names, memorial
   dates and history follow the person. This changes today's one-kind-per-account rule.
2. **Open to everyone: no approval, no sign-up caps, no daily limits on accounts.** Checking happens where it
   matters: a mobed or panthaky accepts or rejects what is asked of them; later trustees do the same for
   applications. (Abuse is handled with reporting, blocking and the admin's switch, never by caps on joining.)
3. **Phase 1 is "completing the cycle"**: the person's own calendar, board and Parsi calendar (the same engine as
   the mobed side), and **asking an agyari for a service**: a jashan, afringan, farokshi, vendidad, memorials, and
   repeating ones: everything the mobed side has, from the person's side.
4. **The ask goes to the panthaky**, who reviews it on the same board where a Doongerwadi's requests go, and accepts
   or rejects it; a confirmation goes back.
5. **A person picks "my agyari"** (Atash Behrams listed first, nearest first) and can ask any other agyari for a
   single ask; they can change it at any time.
6. **Messages: a general chat between a person and the panthaky** (one conversation per pair, for anything),
   with the safeguards below.
7. **Notifications: ordinary in-app notifications and phone notifications by default. WhatsApp only for urgent or
   critical things, and only when BOTH sides have it on** (the person for themselves, the panthaky for their agyari);
   off by default on both sides. The mobed side gets a matching setting.
8. **Phase 2:** events people list themselves (football matches, agyari notices, salgrehs, gambhars) and a
   marketplace (kusti, sudreh and the like; trending and most-bought sorting). Start the marketplace as listings
   with a contact and no payments. A Report button and the admin's removal exist from the first listing.
9. **Phase 3:** the Parsi AI (ask anything about Parsi topics; answers from cited sources). It is the private
   `parsi-kg` project: nothing about it goes into this repository; the app only calls it when it exists.
10. **Money:** about Rs 3,000 a year per fire temple; a platform fee on payments of 10% up to Rs 50 per transaction
    (payments are not built; see `docs/payments-plan.md` for the RBI limits: each agyari its own merchant);
    Doongerwadis and trustees pay nothing for now.

## The chat's safeguards (built with it, not after)

- One conversation per (person, panthaky); the mobeds going to a service see only that service's messages.
- A panthaky can **mute** or **block** a person (they are told only "this agyari is not taking messages right now,
  please call"); a person can mute a panthaky; every message has Report.
- Rate limits per sender (messages a minute and a day), a maximum length, no links, numbers or @-handles from a
  person never met (as the Doongerwadi note rule, D1), and a first-message gate: until the panthaky has replied, a
  person may send at most three messages.
- A message is notified in the app and by phone notification, never on WhatsApp unless it is marked urgent by the
  panthaky and both sides have WhatsApp on.
- It is private to the two people: never shown to other mobeds or the admin screens; deleting an account removes
  that person's messages (D6); nothing is deleted by age (D8). A lawyer's check of "a message to a priest" is part
  of the legal review.

## Phase 1 build steps (small releases, each with the owner's yes before the push)

- **R4.0 Identity and the app shell.** Roles per account; sign-up through the behdin app creates an account that
  needs no approval (a mobed or manager role still needs the admin's approval, D9); the separate app (own
  address, name, icon, install page, service worker); sign-in as today (WhatsApp, no passwords). Tests: a person
  with several roles; the mobed rules unchanged; no route of one app reachable from the other without the role.
- **R4.1 My agyari and the calendar.** Choosing "my agyari"; the calendar, board and Parsi calendar from the mobed
  side, for the person's own things (their memorials, accepted asks); the departed-names pool (decided 24 Nov:
  one pool per number, readable only by that number's own account).
- **R4.2 Asking for a service.** The ask flow (what, for whom, when, where, names, a note), going to the panthaky
  on the existing board; accept, reject, "ask another agyari"; the confirmation; "My asks"; cancel. Repeating
  asks and memorial asks, as on the mobed side.
- **R4.3 The chat** with its safeguards.
- **R4.4 Notifications and the WhatsApp switches** (the person's, the panthaky's, the mobed side's setting).
- **Walk-through each release** in a browser on a scratch copy; one real-phone check; CI runs everything.

## Not decided yet

The app's name and icon; the address it lives at; whether the first screen is the calendar or a home with the next
prayer and the notifications; how a person who is already a mobed switches roles (a switch in the header or a
menu); what a person sees about an agyari before asking (services and usual prices are the panthaky's to set,
as the 22 Nov draft proposed); the data and consent wording for a person's own memorial dates.
