# R3.1: how a prayer request reaches an agyari (redesign)

The owner's idea of 21 Nov 2026, raised during the guided run of Phase 2, and the answers to
the questions that followed. The decisions are recorded in `docs/DECISIONS.md` (D10, "Changed
21 Nov 2026"). Not built yet: until it is, the 19 Nov rules stay live (the call-out at Send,
the first Yeses get the details, the panthaky accepts separately).

## Why

Today two things run side by side and do not meet. The panthaky taps Accept in the app (the
family goes into their book, the family is told *the panthaky* will pray), while the mobeds
answer Yes on WhatsApp and the first ones get the family's details. The family can be told the
wrong person, the panthaky has nothing to do when the WhatsApp call-out already found mobeds,
and a panthaky who would rather phone their mobeds has no way to do it from the app.

The owner's rule: **a request is confirmed only when enough mobeds are going, and at that moment
everyone is connected**: the family, the mobeds, the panthaky and the Doongerwadi.

The aim for the design: the fewest taps, nothing to look for, quick and satisfying to use
(a board that fills, one clear "All set"), and never a request that waits on one person
unless the panthaky chose that. No pressure tricks: these are funerals.

Patterns this borrows (well-known ways other apps solve "find N people fast"): on-call paging
(tell one person first, move on to the next after a set time), shift filling and volunteer
call-outs (ask everyone, the first N to say yes go, the rest are told it is covered), and
"call, then come back and record the outcome" from sales and support apps.

## The two ways (set by the panthaky)

**Settings -> Prayer requests** (confirmed panthakys only; the admin can set it too):

- **Everyone at once** (the default, and what is live today). The moment the Doongerwadi sends,
  every mobed on the agyari's Mobeds page who can be messaged gets the WhatsApp "Can you pray?"
  (template 4). The panthaky has the request in the app with the board already filling. If the
  mobeds fill it, the panthaky taps nothing: they get "All set".
- **Come to me first.** Only the panthaky is told (in the app and on their phone). On the
  request they choose how to find mobeds. Below it, the **safety net**:
  "If I haven't acted in: Never / 15 min / 30 min / 1 hour, ask all our mobeds on WhatsApp".
  **Never is the default** (owner): the panthaky turns it on themselves if they want it.

An agyari with no confirmed panthaky in the app is always "Everyone at once": the request goes
to its approved mobeds in the app, and each can tap "I'll pray" (the same as a WhatsApp Yes).
There, a mobed's "Not this time" answers only for them (owner, 21 Nov 2026, third round): the
request closes only when everyone asked has said no, and the Doongerwadi is then told "Nobody at
<agyari> can take it".

**App mobeds answer in the app too** (owner, third round): the agyari's mobeds who use Mobed
Diary get the request in their Requests tab (red count) and as a phone notification at the same
moment as the WhatsApp call-out, with **I can pray** / **Not this time**. Whichever answer comes
first, app or WhatsApp, counts; the other then reads as already answered. In "Come to me first"
they get nothing until the panthaky asks everyone (or the safety net does). Their card shows no
family details until All set.

**No answer for an hour** (owner, third round): if nobody at the agyari has done anything with a
request for 1 hour after it was sent, the Doongerwadi is told in the app and on their phone "No
answer yet from <agyari>", with **Send to another agyari** on the record. The request stays open
at that agyari until the Doongerwadi withdraws it. Told once per request.

## The board: "Who will pray"

One screen, the request's own page, the same in both ways. From the top:

1. **The request**: the departed's prayed name, the Doongerwadi, Geh-saarnu (day and geh),
   Uthamna (day and time). No family name or number until all set.
2. **"Who will pray: 1 of 2"** with a place per mobed wanted, each empty or showing a name and
   how it filled (WhatsApp Yes / by phone / I'll pray). It updates by itself while open.
3. **Actions** (one tap each):
   - **Ask everyone on WhatsApp** (greyed with the reason when WhatsApp is off, or already asked);
   - **I'll pray** (fills a place with the panthaky);
   - the **Mobeds list** under it: each mobed with **Call**, **WhatsApp** and **Going**, and
     their state (asked, said yes, said no, not asked).
4. **We can't take this** (a small link at the bottom; reason optional): the request is
   declined for this agyari and the Doongerwadi can send it elsewhere.

**The panthaky's first action takes the request** for the agyari (there is no separate Accept
button): Ask everyone, I'll pray, or marking someone Going.

**Calling from the app:** Call opens the phone's dialler. When the panthaky comes back to the
app, a sheet asks **"Is Ervad A going?"** with **Going** / **Not this time** / **No answer**.
One tap records it. (The app notices it is back on screen; nothing listens to the call.)

**WhatsApp from the app** opens the panthaky's own WhatsApp chat with that mobed and a short
message ready to edit (no family details), the same as today's "Message the family" button.

**Short near the time:** if places are still empty **4 hours before the Geh-saarnu** (owner,
21 Nov 2026; at once if the request comes later than that), the panthaky gets "Still 1 mobed
short for <name>" with the board. **Confirm with who's going** closes it with fewer than wanted.

**Taps, panthaky's side:**

| | Today | R3.1 |
|---|---|---|
| Everyone at once, mobeds answer | Open, Accept, Accept on the sheet, memorial form | Nothing: "All set" arrives |
| Come to me first, ask on WhatsApp | (not possible) | Open the notification, Ask everyone |
| Come to me first, phone a mobed | (not possible) | Open, Call, back, Going |
| Come to me first, pray myself | (not possible) | Open, I'll pray |

## All set

**Automatically when the last place fills** (owner), or on "Confirm with who's going". Then, at
once:

- The request reads **All set**. Later WhatsApp Yeses get "Thank you. Enough mobeds are going
  this time. If a place opens, we may ask you again." (inside the 24 hours, as today) and no
  details; they are kept as **standbys** in the order they answered (below). App mobeds see
  "All set" on their card.
- **The family goes into the panthaky's own book and each praying app mobed's own book** (each
  private, D2; their own existing record of that number if they have one; reminders off, D4).
  The Geh-saarnu and Uthamna go on each one's calendar. The memorial is one tap away ("Make the
  memorial", filled in) on each one's request card: no form is forced open.
- In-app notices and a phone notification to the panthaky, each praying app mobed and the
  Doongerwadi: "All set: Ervad A and Ervad B are going for <prayed name>". The lock screen shows
  no family details.
- WhatsApp (when live, approved templates only, consent and STOP as today):

| To | What they learn | Template |
|---|---|---|
| The family | who will pray (names, numbers), the agyari, the times, the panthaky (name, number) | 5 `prayers_all_set_family` |
| Each mobed going | the departed, place, times, the family's contact, the mobeds going, the panthaky | 6 `prayer_details_mobed_v3` |
| The panthaky | the departed, place, times, who is going, the family's contact | 7 `prayers_all_set_panthaky` |
| The Doongerwadi's managers | the agyari, the mobeds' names, the panthaky (name, number) | 8 `funeral_accepted_manager_v2` |

Templates 1-3 stop being used; template 4 (the call-out) stays, or is replaced by 4 v2 (below).

**The Doongerwadi's side** reads "Waiting at Goti Adarian", then "Finding mobeds: 1 of 2",
then "All set" with the agyari, the panthaky's Call and WhatsApp, and the mobeds' names.

## Standbys and backing out (owner, 21 Nov 2026)

- **Standbys:** every Yes that comes after the places are full is kept, in the order it came,
  and shown on the board under "Standby". They get no details (the "Enough mobeds" reply only).
- **Backing out:** a mobed going can say they can no longer go: **"I can't go any more"** on
  their request card in the app, or the **"I can't go any more"** quick-reply button on their
  WhatsApp details message (template 6), or the panthaky marks it on the board for someone who
  phoned. The place reopens at once.
- **Then, by itself:** the first standby is asked again on WhatsApp (the call-out template, so
  it works outside the 24 hours too), and the panthaky is told "Ervad A can't go; we have asked
  Ervad B". If that standby says no, or has not answered in **30 minutes**, the next standby is
  asked, and so on. With no standby left, the panthaky is told: "Ervad A can't go and nobody is
  on standby: please find someone" with the board.
- **Filled again:** the new mobed gets the details (template 6), the family gets the all-set
  message again with the new names (template 5), and the panthaky and the Doongerwadi see the
  new names. The mobed who backed out is not messaged again.
- A request that was confirmed short can take standbys the same way when a place opens.

## The Mobeds page (in the panthaky's diary)

"Our mobeds" becomes **Mobeds**, a page of the panthaky's diary (Menu -> Mobeds):

- **In Mobed Diary:** the agyari's approved mobeds whose access is on, listed by themselves,
  **with their numbers** (owner, 21 Nov 2026), Call and WhatsApp buttons.
- **Added by me:** mobeds the panthaky adds by name and number, with the tick that they agreed
  to get WhatsApp messages from Mobed Diary about prayers (as today); Call, WhatsApp, Remove.
  "Import from contacts" inside the add form, as for behdins.
- A mobed who replied STOP shows "Replied STOP: not asked on WhatsApp", still callable.
- Only that agyari's confirmed panthakys (and the admin) see it. Mobeds of other agyaries stay
  invisible; a mobed's behdins are never shown (D2).

## Template drafts (for the owner to submit when R3.1 is built)

Utility, English, Meta's rules (no blank at the start or end, no two blanks side by side, short).
Blanks that hold several people are filled by the server, e.g. "Ervad A (+91 98xxxxxx01),
Ervad B (+91 98xxxxxx02)"; their numbers come only from sign-in numbers or numbers a panthaky
entered for that person (services/phone.py), never from free text.

**5. To the family: `prayers_all_set_family`**
> The prayers for **[departed]** will be offered by **[mobeds with numbers]** of **[agyari]**.
> Geh-saarnu: **[day and geh]**. Uthamna: **[day and time]**. For anything else, the panthaky is
> **[panthaky, number]**. May the ruvan of the departed attain Garothman Behesht.

**6. To each mobed going: `prayer_details_mobed_v3`**
> You will pray for **[departed]** at **[place]**. Geh-saarnu: **[day and geh]**. Uthamna:
> **[day and time]**. The family's contact is **[family name]**, **[family number]**. Mobeds
> going: **[mobeds with numbers]**. The panthaky is **[panthaky, number]**. Thank you for your
> service.

Quick-reply button: **I can't go any more** (owner, 21 Nov 2026: backing out, see above).

**7. To the panthaky: `prayers_all_set_panthaky`**
> All mobeds are found for **[departed]** at **[place]**: **[mobeds with numbers]**.
> Geh-saarnu: **[day and geh]**. Uthamna: **[day and time]**. The family's contact is
> **[family name]**, **[family number]**.

**8. To the Doongerwadi: `funeral_accepted_manager_v2`**
> The prayers for **[departed]** will be offered by **[mobeds' names]** of **[agyari]**. The
> panthaky is **[panthaky, number]**, by phone or WhatsApp.

**4 v2 (owner, 21 Nov 2026: yes, it replaces template 4): `prayer_request_mobeds_v2`**
> A prayer request has come to **[agyari]** for **[departed]** at **[place]**. Geh-saarnu:
> **[day and geh]**. Uthamna: **[day and time]**. Please reply to tell **[panthaky's name]**
> whether you can take it. If you can, you will get the details once enough mobeds are going,
> and your name and number will be shared with the family.

Why 4 v2: under R3.1 a mobed who says Yes waits for the others before getting the details, and
their number goes to the family; the message should say both before they answer.

## Settled with the owner (21 Nov 2026, second round)

1. Template 4 v2 replaces the approved call-out (template 4 keeps working until v2 is approved).
2. "Still short": 4 hours before the Geh-saarnu.
3. Backing out: standbys in the order they said Yes, asked again by themselves; the panthaky is
   told at each step, and asked to find someone when none is left (section above). The
   standby's 30 minutes to answer is the lead's default, not yet the owner's.
4. The Mobeds page is for panthakys only for now.

## Data changes

- `agyaries.request_mode` (`everyone` | `panthaky_first`, default `everyone`) and
  `agyaries.request_escalate_minutes` (null = Never; 15, 30, 60). Migration with `op.f()` checks.
- `funeral_requests`: a new state **all_set** after **waiting**; `taken_at` / `taken_by_user_id`
  (the panthaky's first action), `all_set_at`, `confirmed_short` (true when confirmed with fewer).
  Requests accepted before R3.1 keep their "accepted" state and read as they do today (D8).
- `prayer_callout_answers`: `how` (`whatsapp` | `phone` | `self` | `app`) and who recorded it, so
  a place filled by phone or "I'll pray" is a row like a WhatsApp Yes (a call-out row is made
  for the board if none exists). The check that a picked row said yes stays true. Also
  `backed_out_at` (and who marked it), and `reasked_at` for a standby asked again; standbys are
  the Yes rows not picked, in `answered_at` order.
- The family-in-book step runs for the panthaky and each praying app mobed at all set, through
  the existing accept code (one call per person, each in their own book).

## Build steps (one helper each, small commits, owner's yes before the push)

1. **Settings -> Prayer requests**: the two ways and the safety net; migration; admin can set
   it. Tests: only a confirmed panthaky (or admin) may change it; defaults.
2. **Routing at Send by the way chosen**, and the safety-net timer in the existing background
   loop (asks everyone once, if the panthaky has not acted). Tests: each way; timer fires once,
   never when Never; nothing under an account that is not on (D9).
3. **The Mobeds page**: app mobeds with numbers, added ones, Call / WhatsApp, import from
   contacts. Tests: only that agyari's confirmed panthakys; no other agyari's mobeds.
4. **The board** on the request: places, Ask everyone, I'll pray, Call / WhatsApp / Going, the
   "Is X going?" sheet on return, We can't take this, live refresh. The first action takes it.
   Tests: first action takes it once (two panthakys at once); Going by phone fills a place.
5. **All set**: automatic when full, Confirm with who's going, both books, calendars, memorial
   one tap away, notices and pushes, Enough-mobeds texts; templates 5-8 behind
   FUNERAL_WHATSAPP_MODE. Tests: the family number reaches no one before all set; each book
   gets its own record only (D2); exactly once under two Yeses at the same moment.
5b. **Standbys and backing out**: standbys in answer order, "I can't go any more" (app card,
   WhatsApp button, panthaky's mark), asking the next standby by itself with the 30-minute
   wait, the panthaky told at each step, the family told the new names. Tests: order kept;
   a standby's late Yes after someone else filled the place changes nothing; the backed-out
   mobed loses nothing else (their book keeps the family, D8).
6. **The Doongerwadi's side**: Finding mobeds n of N, All set with the panthaky and names.
7. **Old path retired**: the Accept button and the 19 Nov details-at-once go; old requests
   still read right. Docs: checklist, templates doc, STATUS.
8. **Templates**: the owner submits 5-8 (and 4 v2 if chosen) in WhatsApp Manager, with help.

Then one browser walk-through of both ways on a scratch database (:8011), and a live test
with the owner's own numbers only before any real agyari uses it.
