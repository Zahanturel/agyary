# R3.1: how a prayer request reaches an agyari (redesign)

The owner's idea of 21 Nov 2026, raised during the guided run of Phase 2, and the answers to
the questions that followed. The decisions are recorded in `docs/DECISIONS.md` (D10, "Changed
21 Nov 2026"). Built 21-22 Nov 2026 (steps 1-7), not live until the owner's push; until then
the 19 Nov rules stay live (the call-out at Send, the first Yeses get the details, the panthaky
accepts separately).

Words (owner's word review, 23 Nov 2026, D11): the screens say **Confirmed** for what this
design calls "All set", **Waiting list** for "standby", and "fire temple" for "agyari"; the code
keeps its names (`all_set`, `standbys`). The template drafts below are in the owner's words.

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

**The panthaky is asked on WhatsApp too** (owner, 24 Nov 2026, after the first real test): every
confirmed panthaky of the agyari (access on, not STOPped, on the allowlist like anyone) gets the same
template 4 with the same buttons, at the moment they are told in the app: in "Everyone at once" with
the mobeds; in "Come to me first" at once, and only they. **I can pray** there is their "I'll pray" on
the board (the same row, so a board tap and a WhatsApp tap by them are one yes; it takes the request);
**Not this time** is a no. A repeat tap, or Meta delivering twice, changes nothing.

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

Owner's word review (23 Nov 2026, D11): 5, 6 and 8 say "For anything else, please contact
**[contact]**": the panthaky with their number, or with no confirmed panthaky in the app, the
first mobed going with their number (in 6 sent to that first mobed, the next mobed going, else the
fire temple's own name with no number). Sent to a panthaky of the agyari (6, and 8 where the
number is theirs) no other person is named, only the fire temple's own name (owner, 24 Nov 2026).
The FAMILY (5) is always given the confirmed panthaky with their number, even when the family's
number is the panthaky's own, never the fire temple's name alone (owner, 24 Nov 2026).
In every WhatsApp text the departed is named by title and own name only, "Osti Aban", without the
father's or husband's name (owner, 24 Nov 2026); the app keeps both. 5 was to end "May the ruvan of the late [departed] ...";
dropped the same day because Meta's form classed it as Marketing (DECISIONS D11), so 5 ends
"Please contact [contact] for anything else."

Laid out in short lines with an empty line between parts (owner, 23 Nov 2026), labels bold in
WhatsApp; a `\` at the end of a line is a line break with no empty line. Details and the exact
form text: docs/phase2-whatsapp-templates.md.

**5. To the family: `prayers_all_set_family`**
> The prayers for **[departed]** will be offered by **[mobeds with numbers]** of **[agyari]**.
>
> Geh-saarnu: **[day and geh]**\
> Uthamna: **[day and time]**
>
> Please contact **[contact]** for anything else.

**6. To each mobed going: `prayer_details_mobed_v3`**
> You will pray for **[departed]** at **[place]**.
>
> Geh-saarnu: **[day and geh]**\
> Uthamna: **[day and time]**
>
> Family: **[family name]**, **[family number]**\
> Mobeds going: **[mobeds with numbers]**
>
> For anything else, please contact **[contact]**.
>
> Thank you for your service.

Quick-reply button: **I can't go any more** (owner, 21 Nov 2026: backing out, see above).

**7. To the panthaky: `prayers_all_set_panthaky`**
> The prayers for **[departed]** at **[place]** are confirmed.
>
> Mobeds going: **[mobeds with numbers]**
>
> Geh-saarnu: **[day and geh]**\
> Uthamna: **[day and time]**
>
> The family's contact: **[family name]**, **[family number]**
>
> You can see the full details in Mobed Diary.

**8. To the Doongerwadi: `funeral_accepted_manager_v2`**
> The prayers for **[departed]** will be offered by **[mobeds' names]** of **[agyari]**.
>
> For anything else, please contact **[contact]**.
>
> Thank you.

(7 and 8 reworded 23 Nov 2026 before submitting: Meta's form refuses a template that ends on a
blank, and refused 7 for too many blanks for its length. Same blanks, same order.)

**4 v2 (owner, 21 Nov 2026: yes, it replaces template 4): `prayer_request_mobeds_v2`**
> A prayer request has come to **[agyari]** for **[departed]** at **[place]**.
>
> Geh-saarnu: **[day and geh]**\
> Uthamna: **[day and time]**
>
> Please reply to tell **[panthaky's name]** whether you can take it.
>
> If you can, you will get the details once enough mobeds are going, and your name and number
> will be shared with the family.

Why 4 v2: under R3.1 a mobed who says Yes waits for the others before getting the details, and
their number goes to the family; the message should say both before they answer.

## Settled with the owner (21 Nov 2026, second round)

1. Template 4 v2 replaces the approved call-out (template 4 keeps working until v2 is approved).
2. "Still short": 4 hours before the Geh-saarnu.
3. Backing out: standbys in the order they said Yes, asked again by themselves; the panthaky is
   told at each step, and asked to find someone when none is left (section above). The
   standby's 30 minutes to answer is the lead's default, not yet the owner's.
4. The Mobeds page is for panthakys only for now.

## The lead's choices while building (the owner can change any of them)

- **"4 hours before the Geh-saarnu"** is counted from the start of its geh, in IST: Havan
  6:30 am, Rapithwan 12:30 pm, Uzirin 3:30 pm (the Geh-saarnu is prayed only in these day gehs).
  With no geh given, 6:30 am of that day; with no Geh-saarnu day, the Uthamna's day and time
  (or 6:30 am); with neither, no "still short" alert.
- **The Mobeds page shows numbers only of approved mobeds** (not of someone still waiting for
  the admin's approval, not the panthaky's own), as D10 says "approved mobeds ... with their
  numbers". Mobeds switched off or who replied STOP keep their number and Call / WhatsApp.
- **A panthaky switched off after a request reached them:** the safety net (if set) still asks
  everyone, since nobody else could act on it.
- **Red counts:** a panthaky's Requests count is the open requests nobody has taken yet; an
  app mobed's is the open requests they were asked and have not answered.
- **A Yes is not told the details at once any more:** the details go to everyone at All set.
- **A phone call can turn an earlier "no" into Going** (people change their mind on the phone);
  it never touches someone already going or a standby. Backing out is the 5b path.
- **"I'll pray" is for a confirmed panthaky** (an admin who is not one cannot fill a place).
- **At an agyari with no panthaky,** mobeds are not each told when another says yes; their
  card shows "1 of 2 going" instead.
- **Whose book at All set:** the panthaky who took the request; if nobody did (or an admin who is
  not a panthaky did, or the taker is now switched off), every confirmed panthaky it reached.
  A going app mobed whose access is off, or who left the agyari, gets no book (D9) but is still
  named in the messages.
- **"Still short" is told only before the prayers begin** (never for a request whose Geh-saarnu
  has begun or passed, such as an old test record left waiting).
- **Template 7** now says "are confirmed", which is true also when the panthaky confirmed with
  fewer (the first wording, "All mobeds are found", was not).
- **Standbys (step 5b):** one standby is asked per open place, in the order they said yes; one
  who gave no answer in 30 minutes is not asked again for a later place (a late answer to that
  re-ask still counts); the panthaky's own standby ("I'll pray" when full) is never re-asked; a
  standby nobody can reach (WhatsApp off and not in the app) is skipped and the panthaky told.
  Only the re-ask's own buttons answer a re-ask, not the first message's.
- **A reopened request** (someone backed out) can still be withdrawn by the Doongerwadi; "still
  short" is not told a second time.
- **The WhatsApp reply to "I can't go any more"** at an agyari with no panthaky in the app is
  "Thank you for letting us know." (without "the panthaky has been told").

## The lead's browser walk-through (22 Nov 2026, scratch database on :8011)

Walked as a panthaky who is also the admin, acting for a test Doongerwadi: Settings -> Prayer
requests (Come to me first, safety net shown only under it, Saved), Mobeds (the other app mobed
with number, Call, WhatsApp; "You" without buttons), record a death and Send (the sheet before
Send words Come to me first right), the Requests list ("Waiting for you", red count 1), the board
(0 of 2, open places, I'll pray, Ask everyone, the mobed with Call / WhatsApp / Going?), Call then
leaving and coming back (the "Is Er. ... going?" sheet appeared; Going filled a place "By phone"),
I'll pray (All set: 2 going; the family's contact, the message to the family, who is praying, In
your book, Make the memorial), the Doongerwadi's record (All set with the names and only the
panthaky's number), "No answer yet" (told correctly 3 hours after an unanswered send), and
Can't go (the place reopened, "Nobody is on standby: please find someone"). Every path worked.
The full migration chain ran on a fresh database. All 539 related tests passed (one file re-run
after a stalled run).

Fixed at once: the "Everyone at once" words in Settings now say "asked, in the app and on WhatsApp".

**Polish for later (not blocking):**
- After a place reopens, the panthaky's board hides the family's contact again, though the
  family is already in their book.
- The message to the family names only the sender; it could also name the other mobeds praying.
- The "Is X going?" sheet needs the phone to leave the app (a real call does); a WhatsApp chat on
  a desktop browser may not trigger it.
- Not walked in the browser (covered by tests and the helpers' screen checks): an app mobed's own
  card, standbys being asked again, the safety net firing, Everyone at once at Send, a decline,
  and a withdraw.

## Security pass (22 Nov 2026)

A read-only review of every Phase 2 and R3.1 route (60) found nothing critical or high. Its clear
findings are fixed in local commits (5a6be60 to 3e89137): a mobed taken off the Mobeds list can no
longer answer with an old WhatsApp button; hand-added mobeds are matched to accounts by number each
time; adding by hand no longer reveals an account's state; nobody waiting or switched off can be
given a place; the "withdrawn" text goes only to WhatsApp yeses; the Doongerwadi hears no mobed's
name before All set; the family number cannot change under a waiting request; erasure covers the
stored messages and hand-added mobeds; signing out also stops that phone's notifications; an app
mobed marked Going by phone gets the request in their tab; old accepted requests are closed for
answers. The one medium finding needing a decision (joining another agyari) went to the owner
(D10, 22 Nov 2026) and is being built.

**The lead's choice:** someone holding a place who is taken off the list, removed, or switched off
frees the place exactly as "Can't go" does (the standbys are asked).

## Joining needs the panthaky's confirmation (22 Nov 2026)

Built in local commits after the security pass (D10, owner 22 Nov 2026). Joining a fire temple stays
open (D1.4): the membership is there for Settings, machis and the mobed's own book as before, and
grants nobody's behdins. For prayer requests it counts only once confirmed and not taken off the list
(`panthaky.counts_for_requests`, the one rule every request path reads).

- **Who is confirmed:** every membership from before (migration `b6c7d8e9f0a5`); the fire temple a
  new sign-up chose, when the admin approves them; whoever adds a brand-new fire temple (nobody else
  is there to); someone the owner confirms as its panthaky; an admin, wherever they are a member.
  Anyone joining later, from Settings, waits.
- **Not confirmed (or taken off):** not a recipient of a request (at a fire temple with no panthaky,
  only confirmed mobeds count; with none, the Doongerwadi is told nobody is in the app), not asked by
  Ask everyone or the safety net, not on the board or the Mobeds list, cannot answer in the app (no
  red count), and never put in a book or named at All set.
- **Telling people:** a later join tells the fire temple's confirmed panthakys (in the app and on
  their phones, no number) "Er. A has joined <agyari>" / "Confirm them on Mobeds to send them prayer
  requests."; with no panthaky in the app, every admin, for Admin -> Mobeds. A mobed confirmed (or put
  back) is told "<agyari> has confirmed you: you will now get its prayer requests."
- **Mobeds page:** "Joined, waiting for you" (names only, no number) with Confirm and Not one of
  ours; "Take off the list" (asked first) on each app mobed but a panthaky; "Off the list" with Put
  back. A number the panthaky added by hand goes off the list with the app mobed of that number.
- **Admin -> Mobeds:** the same for fire temples with no confirmed panthaky (access on).
- **Freeing a held place:** taken off the list, a hand-added mobed Removed, or access switched off
  by the admin: their place is freed through the same code as Can't go (`standbys.free_places_of`),
  before the prayers begin; their own book keeps the family (D8).
- Routes: `POST /api/mobed/agyaries/{id}/members/{user_id}/confirm | off | on` (its confirmed
  panthakys or the admin; anyone else gets the list's 404) and `POST /api/mobed/admin/mobeds/{user_id}/requests`
  (`{agyary_id, action}`). Tests: `tests/test_join_confirmation.py`.

## Open for the owner (next session)

- **No panthaky in the app:** templates 5, 6 and 8 name "the panthaky"; at an agyari with none
  the blank reads "not fixed yet", which sounds odd. Choose before submitting the templates:
  reword those sentences (e.g. "For anything else, please contact [contact]", filled with the
  panthaky or else the agyari's name), or leave it.
- **The standby's 30 minutes** to answer before the next is asked (the lead's default).
- Every choice in the section above.
- **Joining needs the panthaky's confirmation (built 22-23 Nov, choices to confirm):** a sign-up
  still waiting for the admin shows in the panthaky's "Joined, waiting for you" by name, with no
  notice; a mobed taken off the list is not told (only confirming or putting back tells them);
  turning an account off and on again does not re-confirm a fire temple joined meanwhile; a
  panthaky can never be taken off; erasing a number does not free a place they held.
- **New words since the review page was made** (security fixes and joining): add them to the
  review page before going through it, so every text is checked (D11).
- **Not walked in a browser yet:** the security fixes and the joining screens (Mobeds page
  "Joined, waiting for you", Admin -> Mobeds): one walk-through before R3.1 is pushed.

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
