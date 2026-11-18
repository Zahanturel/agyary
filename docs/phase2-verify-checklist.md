# Phase 2: what is built, and how to try it (owner's checklist)

Live as of 18 Nov 2026: R1 (99d3cea), R2 (425078f), R3 (ca2743e), app version v82.
Being built now, not live: Steps 5b and 5c (WhatsApp on accept, and the panthaky's call-out).

## What is built (live)

**R1: fire temples on the map, and "mobed or panthaky"**
- Settings -> Location -> **Edit location**: a map to put the fire temple's pin; "I'm at the agyari
  now" (phone's location); search an address or area; "Find on Google" (only once the Google key is
  on the server). Any approved mobed of that temple, or you, can move the pin.
- Adding a new fire temple at sign-up has the same map.
- Sign-up asks **"Are you a mobed here, or the panthaky?"**. Mobeds who joined earlier see "Are you
  the panthaky of X? Tell us" in Settings. It is only a claim until **you confirm** it on
  Admin -> Mobeds ("Confirm as panthaky" / "Not the panthaky" / later "Remove as panthaky").
  Settings shows "You are: Mobed / Panthaky".

**R2: Doongerwadis and their managers**
- **Admin -> Doongerwadis**: add / change / turn off a Doongerwadi, prayer hall or aramgah (name,
  kind, town, address, run by, map pin).
- A **new** account first chooses "I am a mobed or panthaky" or "I work at a Doongerwadi or prayer
  hall". A manager picks their place and waits; you approve them on **Admin -> Mobeds** (same
  Approve / on-off switch; in-app notice and phone notification "A new Doongerwadi manager is
  waiting").
- A manager has their own home, no Machi / Calendar / Behdins, and cannot open anything of a mobed's.
- Admin -> "In the app": counts of mobeds, panthakys, fire temples in use, Doongerwadis, managers.

**R3: a death, sent to an agyari, accepted**
- Manager: **Record a death** (prayed name with title, father's or husband's name, by date or by
  Roj and Mah, four days or one, bungli, Geh-saarnu day and geh, Uthamna day and time, mobeds
  wanted, the family's fire temple, one family contact). Then **choose the agyari**: Suggested
  (nearest first, km) or Search all; the tick "The family agreed to share their name and number with
  this agyari"; **Send**. They see each request's state; can withdraw and send to another.
- Who gets it: that agyari's **confirmed panthakys**; if it has none, **all its approved mobeds**.
  They get an in-app notice and a phone notification (lock screen: "A request for prayers").
- Mobeds: a fourth tab **Requests** with a red count. No family details until accepting.
  **Accept** (tick "Share my name and number", on by default) adds the family to their own
  Behdins (reminders off), puts the Geh-saarnu and Uthamna on their calendar, and opens the
  memorial form filled in. Then: **Message the family on WhatsApp** (from their own WhatsApp, text
  ready to edit) and **Call**. **Decline** with an optional reason.
- Manager: "Accepted by <name> of <agyari>", with their number, Call and WhatsApp only if they
  ticked share; a notice on accept or decline.
- Settings: **Notifications on this phone** for everyone (not only you).
- Admin -> Erase a number now also clears that number from Doongerwadi records.

## Before you try it: three things that decide whether it works

1. **Phone notifications** reach only phones where that person turned on Settings -> **Notifications
   on this phone**. Use the app in **Chrome**: the Android app we shared was built with notifications
   off, so it may not show them. Everyone else still sees the in-app notice and the red count.
2. **Who at Goti Adarian gets the request:** if Goti Adarian has a **confirmed panthaky**, only the
   panthaky(s) get it. If you want **every mobed there** to get it, confirm nobody as panthaky for
   this test (all approved mobeds then get it). Each must be approved and on.
3. **Records are kept for good (D8).** Use a clearly test name (e.g. "Behdin Test Run") unless it
   is a real death the family agreed to. Tell me afterwards and I can remove test records on the
   server.

## Trying it alone (v84, 18 Nov 2026): "Act for this place"

Without a manager's phone: Admin -> Doongerwadis -> **Act for this place** opens that place's
manager screens with a strip "You are acting for <place> as admin". Record a death, send it to
Goti Adarian, then accept it yourself on the Requests tab as its confirmed panthaky. The record
says "Recorded by the admin". The WhatsApp templates (all four submitted 18 Nov) have no
"Message them" buttons: Meta refuses buttons that link to WhatsApp, so the number in the text is
tappable instead.

## Trying the whole run (Surat Doongerwadi -> Goti Adarian)

On each phone first: reload the app once (to get v82), then Settings -> Notifications on this phone.

1. **You:** Admin -> Doongerwadis -> Add: name (e.g. "Surat Doongerwadi"), kind Doongerwadi, town
   Surat, run by (e.g. Surat Parsi Panchayat), the pin (on the map, or "I'm there now" when there).
   [ ] It appears in the list.
2. **The Surat manager**, on their phone: open mobed.gotiadarian.com/mobed in Chrome, sign in with
   WhatsApp, choose **"I work at a Doongerwadi or prayer hall"**, pick Surat Doongerwadi.
   [ ] They see the waiting screen.  [ ] You get "A new Doongerwadi manager is waiting".
3. **You:** Admin -> Mobeds -> approve them.  [ ] They see "You're in" and their home.
4. **Goti Adarian:** make sure its pin is set (any of its mobeds: Settings -> Edit location), and
   that the people who should get it are approved and on (and, if you want only the panthaky to
   get it, confirm them as panthaky).
5. **Manager:** Record a death -> fill it in -> Save -> choose **Goti Adarian** (Suggested or Search
   all) -> tick -> Send.  [ ] The record says "Waiting at Goti Adarian".
6. **Each person at Goti Adarian:**  [ ] phone notification (if turned on)  [ ] in-app notice
   [ ] red count on Requests  [ ] the request shows no family name or number.
7. **One of them:** Accept (share ticked).  [ ] Family appears in their Behdins  [ ] Geh-saarnu and
   Uthamna on their calendar  [ ] memorial form filled in -> save it  [ ] "Message the family on
   WhatsApp" opens their WhatsApp with the text ready.
8. **Others asked:**  [ ] see "Accepted by <name>".
9. **Manager:**  [ ] "Accepted by <name> of Goti Adarian" with the number  [ ] notice.
10. Also try: Decline with a reason (manager sees it); Withdraw and send to another agyari.

## Still for you on the server / Meta

- [ ] Starting positions: `cd ~/agyary`, then
      `docker compose exec -T app python -m agyary.scripts.seed_fire_temple_locations` (dry run),
      then the same with `--write`.
- [ ] Google: `GOOGLE_PLACES_API_KEY=` in `.env`, then `docker compose up -d app`.
- [ ] Meta: submit the four templates in `docs/phase2-whatsapp-templates.md` (WhatsApp messages
      start only after they are approved and Steps 5b/5c are live and switched on).

## What remains to build

- **Steps 5b and 5c** (being built): WhatsApp on accept; "Our mobeds" list and the call-out.
- **Step 6**: STATUS.md, a security pass over everything new, a real-phone check of notifications.
- **Small follow-ups**: the name screen still says "slips" for managers; sign-up dates shown in UK
  time; a manager cannot change their place in the app; one decline closes a request for that
  agyari (could stay open until everyone answers).
- **Before real deaths at scale**: the lawyer's question on the departed's data (research doc).
- **Later (to discuss)**: the behdin app (R4); payments through a gateway with your fee.
