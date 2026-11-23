# Owner decisions

The owner's answers, recorded so every session works from the same ones. These are
decisions, not suggestions: do not reopen them. Where a decision needs a safeguard to
be safe, the safeguard is listed and is not optional.

Recorded 12 Oct 2026, in answer to the independent review's questions (section 7).

---

## D1. Who may become a mobed

**Anyone whose phone number is verified may sign up as a mobed.** Verification is by the
sign-in code sent over WhatsApp (D3), or by the existing "send us a code" flow. Later, when the
Machi and Mobed apps are merged, a panthaky will approve the mobeds of their temple.

**Since 17 Nov 2026, signing up is not the same as being let in: an admin approves every new mobed
(D9).**

**This is in force now** (12 Oct 2026): the server runs `SIGNUP_MODE=open` and `OTP_MODE=live`.
It is the owner's decision and the invite-only mode that Phase 0 shipped is NOT a standing
requirement; do not switch sign-up back to invite-only without the owner asking. (An earlier
version of this file made open sign-up wait for other fixes. The owner rejected that ordering.)

The hardening below is **work to do next, in this order**, because open sign-up makes it matter
more. It is not a precondition for sign-up being open:
1. **AZ-3 first**: typing a known number must not attach a mobed to another mobed's behdin
   (D2). This is the largest remaining exposure.
2. A new account must not be able to make our WhatsApp account message strangers with its own
   text. Validate free text that reaches a template (temple name, service names, the departed's
   name): bounded length, no links, no @-handles, no long digit runs. At most one automatic
   reminder per recipient number per day. Low automatic-sending limits for brand-new accounts
   that rise as the account ages or is vouched for. The global, per-mobed and per-temple caps stay.
3. A bot check (Cloudflare Turnstile, free) on the code-request step, plus the per-number,
   per-address and new-number limits already in place.
4. Joining a temple stays unrestricted, and must never grant access to other people's behdins.

## D2. Behdins are private to the mobed who created them

A mobed sees only their own behdins, their names, saved names, history, bookings, memorials
and slips. Nothing about a behdin is visible to another mobed, including one at the same
temple, and typing a phone number that another mobed already has must not reveal or attach
to that mobed's record. Later, when a panthaky can assign work to a mobed, only the assigned
behdin becomes visible, and only to that mobed. That is a future feature; build nothing for
it now, but do not design it out.

Consequences for the design: per-mobed behdin data (name, saved names) belongs to the
mobed's own record, not to a global one keyed by phone. A STOP reply stays global per phone
(a person who says stop is stopped for everyone), and nobody may clear it except by the
"they asked me to" confirmation.

## D3. Roll out with sign-in by a code on WhatsApp

Sign-in by a six digit WhatsApp code goes live (`OTP_MODE=live`); the `login_code`
Authentication template is approved. The "send us a code" flow stays as the other way in
and is fixed (the phishing weakness found by the review).

The review advised against enabling it. The owner has decided to, and it is **live as of 12 Oct
2026**. The review's conditions are follow-up work, not preconditions:
- the template keeps the security recommendation text;
- per-address limits are kept in the database, not only in memory;
- a bot check on the request step for numbers that have no account yet (D1);
- the daily and new-number caps stay, and the pause switch covers it;
- state plainly that WhatsApp users who have adopted usernames may have no phone number
  Meta will send to; they need another route (the review's AU-4).

**Changed 30 Oct 2026 (owner):** the bot check's keys have been set since 16 Oct, so the bot check
is no longer follow-up work. A server without its keys refuses to send codes, and mobeds are told
to use the other WhatsApp sign-in. Changing a behdin's number also turns their reminders off until
the mobed asks again: an agreement belongs to the number it was given for.

## D4. Automatic reminders are available to every mobed for now

Everyone gets both: sending by hand through the mobed's own WhatsApp, and automatic
sending. This is a pilot with a handful of invited mobeds. Later, when payments exist,
automatic sending becomes a premium feature and is switched off for non-paying users. So:
keep automatic sending behind one clearly named per-account switch from the start, so that
turning it off for the free tier later is a configuration change, not a rewrite.

"Available to all" does not remove the safeguards in D1, the spend caps, the consent
requirement, the pause switch, or the rule that the opening ten days are never reminded.

**Live as of 13 Oct 2026** (`REMINDERS_SEND_MODE=live`, `REMINDERS_ALLOWLIST=*`). This
followed a test send to the owner's own number: sent, delivered and read, and a STOP reply was
honoured. Every family a mobed has recorded consent for is now reminded automatically the
evening before, unless that mobed's account switch is off.

## D5. Calendar facts (settled with a mobed; do not reopen)

- **Month 10 is named "Dae-Dadar"** in this app (changed 22 Oct 2026 by the owner; it was
  "Dae-Pa-Adar"). Roj 8 is still named "Dae-Pa-Adar" (and 15 "Dae-Pa-Meher", 23
  "Dae-Pa-Din"). The spelling is as in `calendar/engine.py`; keep it.
- **There is exactly one Parab per month.** For month 10 it is Roj 1 (Hormazd), the Roj that
  shares the name Dae-Dadar (changed 22 Oct 2026; it was Roj 8). The other Dae days of that
  month are not Parabs for this app. Memorials saved before the change keep the dates they
  already have. The review's finding DM-1 disagreed with sources; the owner's rule wins. Mark DM-1
  closed (owner decision, no change), and do not raise it again.
- **A death before sunrise belongs to the previous Parsi day.** The way the app handles this
  is to give the mobed the choice to state the death by **Roj and Mah (and year)** as well as
  by Gregorian date: the memorial form and API must accept either. The mobed knows which Parsi
  day it was. This replaces any idea of working it out from a time of death. It resolves DM-4.
  Keep showing the death's Roj and Mah on the review step so the mobed confirms it.

- **There is no sixth Gatha, and the app has no Fasli (31 Oct 2026).** Shenshai and Kadmi have five
  Gatha days and fall a day behind the Gregorian calendar every leap year. Fasli was the only calendar
  with a sixth day, so the owner removed it: nobody can choose it for anything new. Anything already
  saved in Fasli stays exactly as it is and stays readable (D8), which is why the engine still knows it.

## D6. Warmth, and leaving cleanly (14 Oct 2026)

- A family's first STOP gets one short, kind reply naming their mobed: "You will not receive any
  more reminders from <mobed>. Ushta te." (**Changed 23 Nov 2026**, D11: it ended "May you and
  your family be in peace.") Never a second one. It is a paid text reply (about the utility rate
  since 1 Oct 2026), so it has its own daily cap and respects the pause switch.
- The reminder template gains one warm closing line and a "Stop reminders" button
  (`memorial_reminder_v3`; Meta locked the name `_v2` for about three weeks after an earlier attempt, so it
  was submitted as _v3 on 23 Nov 2026), with no invitation wording, so it stays Utility. The current template
  keeps sending until the new one is approved; switching is a setting. (**Changed 23 Nov 2026**,
  D11: v2, not yet submitted, is in the owner's words, "Sahebji <family>, a reminder from <fire
  temple>: ... May the ruvan of the late <departed> attain Garothman Behesht.", with blanks of its
  own; docs/OWNER-TODO.md has the text to submit.)
- A mobed can mark a reminder "I told them myself"; nothing is then sent automatically for it.
- A mobed can delete their account, and everything that is theirs goes with it, as Google Play
  requires.
- The Android app is a Trusted Web Activity named "Mobed Diary" (`com.gotiadarian.mobeddiary`).
  **Changed 14 Oct 2026:** it is shared directly with the mobeds (the signed APK, in a WhatsApp
  group the owner runs), not through Google Play for now. No Play fee, closed test or reviewer
  sign-in is needed. The app shows the live site, so updates reach everyone without a new APK;
  a new APK is only needed for the name, icon or Android-level changes. Play stays possible later
  (the listing material is kept), and Google's developer-verification rules for apps installed
  outside Play may require registering as a developer once they reach India.

## D7. One app, and a machi is each mobed's own (29 Oct 2026)

- **Machi is a tab of the Mobed Diary, not an app of its own.** The bottom tabs are Machi,
  Calendar and Behdins, shown on every screen except Settings, sign-in and onboarding. The
  separate Machi app (machi.gotiadarian.com) never shipped and is gone, with its manifest and
  service worker. The Machi and Calendar tabs share one day and one Day/Month view, so switching
  between them never moves the date.
- **A mobed's machis are private, like their behdins (D2).** A machi slot is one geh, one day,
  one temple, *per mobed*: two mobeds at a temple may both hold the same geh and neither can tell.
  The board shows a mobed only their own machis, and a colleague's never makes a geh look taken.
  The panthaky (and caretaker) keep full authority over their temple for now and see every machi
  there; the roles-and-permissions module will replace that. Migration `a9b0c1d2e3f4`.
- **Half-filled forms are kept until saved, discarded or sign-out, and never applied unasked.**
  Opening a form with a saved draft asks "Continue from last time" or "Start a new one". Only
  content is kept (behdin, purpose, names); Roj and Mah are always worked out from the date, and a
  booking date that has already passed is not restored (the day being viewed is used, and the
  mobed is told). Signing out or deleting the account wipes every draft on the phone.

## D8. No record is ever lost (31 Oct 2026)

**Nothing is deleted because of its age.** There is no retention period and no automatic clean-up of
behdins, memorials, ceremony records or the record of messages sent. The audit proposed one (C5) and
the owner refused it; the code was removed, not left switched off, so that no setting can turn it on.

Records go only when someone asks: a mobed deleting something or their own account (D6), or a family
asking to be erased (docs/DATA-REQUESTS.md). Sweeping what is not a record stays: expired notices,
spent sign-in codes, and the digests of deleted accounts. Backups are copies, and still age out.

## D9. The owner approves every mobed, and can turn any of them off (17 Nov 2026)

**A new mobed can use the app only once an admin has approved them.** They sign in with WhatsApp and
choose their fire temple as before, and then see one screen saying they are waiting. Every admin is
told in the app ("A new mobed is waiting", kept for seven days) and approves them on Admin -> Mobeds.

**Every mobed has one switch, on or off, and that is the whole of their access.** The owner uses it to
give someone a free month and to stop it, and later for paying and not paying. There are no
per-feature switches or limits per mobed: off is no app at all, on is all of it.

- Off, or waiting: the mobed sees one screen saying so (with `SUPPORT_PHONE` to get in touch on, if
  set). They can still sign out and delete their account. Nothing they saved is touched (D8).
- Nothing goes out under an account that is not on: no automatic reminders (also not one planned
  before it was turned off), no daily report, no schedule from our number.
- Accounts that existed before this are on. An admin (`ADMIN_PHONES`) is always on and cannot be
  turned off, so the owner can never lock themselves out.
- Admins are also told on their phone, even when the app is closed (web push, 17 Nov 2026), once
  the server has its keys (`VAPID_*`, made once with `agyary.scripts.vapid_keys`) and the admin has
  turned it on for that phone on the admin screen. The lock screen shows the name and temple, not
  the number. It never holds up a sign-up: a failed push is logged and the in-app notice stays.

The owner chose this over keeping families' reminders going while their mobed is off.

## D10. Phase 2: the Doongerwadi side (18 Nov 2026)

Decided, not built. The research, the sources and the full design are in
`docs/phase2-doongerwadi-research.md` (section 8 is the design as decided).

- **Pilot: the Mumbai Doongerwadi and the Worli Prayer Hall** (for families who choose cremation),
  both from the start. **Funeral places are free**; agyaries are the paying customers; behdins are
  always free. The admin creates funeral places; nobody can add one themselves.
- **A Doongerwadi manager signs up like a mobed** (WhatsApp), chooses their funeral place, and waits:
  the owner sees them on the admin side with name and number and approves them. The D9 switch
  applies to them. Only managers use the Doongerwadi end for now; staff accounts and a family
  version come later.
- **Every agyari gets a location**, a pin picked on a map when its address is added or edited. The
  agyaries already in the app start from town-level positions (the research's section 5).
- **No fixed list of "near" agyaries.** The manager sees a "Suggested" list sorted nearest first
  (within 500 km) and can search every agyari in the app. The family's preferred agyari goes first.
- **Before a request goes, the manager ticks that the family agreed** to share their name and number
  with that agyari. No tick, no request.
- **The request goes to the chosen agyari's panthaky.** If it has no panthaky in the app, it goes to
  all its approved mobeds. It shows in a Requests place with a red dot and a count, and as a phone
  notification. The family's number is shown only once a request is accepted.
- **Accepting sets everything up in the accepter's own book**: the behdin (or their own existing
  record of that number), the memorial with the name, date, Roj and Mah, and the four days on their
  calendar. D2 holds: nobody's book is looked into, and the Doongerwadi never learns which mobed has
  which family.
- **Reminders keep their rule** (D4): a behdin from the Doongerwadi arrives with reminders off, and
  the mobed turns them on only after asking the family in person.
- **Sign-up asks "mobed or panthaky".** Safeguard, not optional: the answer is a claim until the owner
  confirms it at approval, because the panthaky role already lets a person see every machi at their
  temple (D7) and the app never lets anyone grant themselves that role. Roles' rights and limits,
  temples with several panthakys, and access by each agyari's payment are for Version 3, to be
  discussed in depth; until then the per-person switch (D9) stays.
- **Funeral records follow D8**: kept until someone asks for them to go.
- **What is not recorded:** cause of death, age, address, the death certificate or a photo of it, ID
  numbers, and how the body goes. The app takes no side on cremation.
- **Spellings in the app:** Doongerwadi, Dokhma, Bungli, Geh-saarnu, Uthamna, Chahrum, Sachkar,
  Paydast, Aramgah.
- **No WhatsApp messages from our number** for any of this in Phase 2. **Changed 18 Nov 2026
  (owner):** when someone accepts a request, a tick "Share my name and number" (on by default) lets
  Mobed Diary's number send three Utility messages: to the manager (who accepted, name and
  number), to the accepter (the funeral details and the family contact) and to the family (who will
  pray, name and number). Safeguards, not optional: approved Meta templates only, sending switched
  off until they are approved; the family is messaged only if the manager's tick also recorded the
  family's agreement to hear from Mobed Diary; STOP, the pause switch, the caps and D9 (nothing
  under an account that is not on) apply. Alongside, buttons that open the person's own WhatsApp
  (the manager: Call / WhatsApp the accepter; the accepter: the family's chat with a short message
  ready to edit) work without any template.
- **The panthaky's WhatsApp call-out (owner, 18 Nov 2026; built right after R3):** each agyari has
  a list of its mobeds: its approved mobeds in the app, plus mobeds the panthaky adds by name and
  number, each with the panthaky's tick that they agreed to get WhatsApp messages from Mobed Diary.
  On a request, the panthaky can send them all a template asking "can you pray?" with Yes / Not
  this time buttons (no family details). Every Yes is shown to the panthaky, who picks who goes;
  only those picked get the details (family contact and times). Payment stays with the panthaky,
  outside the app. Same safeguards as above (approved templates, STOP, pause switch, caps, D9).
- **Template wording (owner, 18 Nov 2026):** utility only, no "thank you for using Mobed Diary";
  the mobed's details message ends "Thank you for your service"; the family's message never says
  "funeral" and uses the person's name. Drafts: `docs/phase2-whatsapp-templates.md`.
- **Changed 19 Nov 2026 (owner, after trying it):**
  - The departed's title offers **Khud** too, like the rest of the app.
  - **No bungli field** on a funeral record. Message 2 is resubmitted without it as
    `prayer_details_mobed_v2`.
  - **The call-out goes at Send, not after the panthaky accepts.** When the Doongerwadi sends a
    request, the WhatsApp request (template 4) goes at once to all of that agyari's mobeds (its
    approved app mobeds plus the panthaky's list, consent ticks and STOP as before). The panthaky
    still gets the request in the app. **The first Yeses, up to the number of mobeds wanted, go**:
    they get the details (message 2) automatically; later Yeses get "Enough mobeds are going this
    time" inside the 24-hour window; the panthaky is told who is going. This replaces "the
    panthaky picks". Payment stays with the panthaky.
  - **The Doongerwadi manager keeps a book of behdins** (families): name, number (typed, or
    imported from the phone's contacts inside the name/number form) and their usual agyari, private
    to that funeral place. Recording a death picks the family from it and suggests their agyari.
- **Requests is a fourth bottom tab** for mobeds, beside Machi, Calendar and Behdins, with the
  red count of requests waiting for them (changes D7's three tabs).
- **Changed 21 Nov 2026 (owner, during the guided run): the panthaky chooses how requests reach
  their agyari, and nothing is confirmed until enough mobeds are going.** Design and build steps:
  `docs/phase2-requests-redesign.md` (release R3.1). Not built yet; until it is, the 19 Nov rules
  above stay live.
  - **Two ways, set once by the panthaky** (Settings -> Prayer requests): **Everyone at once** (the
    WhatsApp call-out goes at Send, as on 19 Nov) or **Come to me first** (only the panthaky is
    told; they ask everyone on WhatsApp with one tap, call or WhatsApp single mobeds from the app,
    or say "I'll pray"). An agyari whose panthaky has not chosen, or that has no panthaky in the
    app, is "Everyone at once".
  - **Safety net, off unless the panthaky turns it on:** in "Come to me first", the panthaky may
    set "if I haven't acted in 15 min / 30 min / 1 hour, ask all our mobeds on WhatsApp". The
    default is **Never**.
  - **One "Who will pray: n of N" board** on the request, the same in both ways. A place fills by
    a WhatsApp Yes, by "I'll pray", or by the panthaky marking a mobed "Going" after a call. The
    panthaky's first action takes the request for the agyari: there is no separate Accept.
    "We can't take this" declines.
  - **All set, automatically, when the places are full** (or when the panthaky taps "Confirm with
    who's going" if short). Only then does anyone get the family's contact, and then everyone is
    connected at once: the family gets the mobeds' and the panthaky's names and numbers with the
    times; each mobed going gets the family's contact, the place and times, the panthaky and the
    other mobeds going; the panthaky gets who is going and the family's contact; the Doongerwadi
    gets the agyari, the panthaky's contact and the mobeds' names. This replaces "the first Yeses
    get the details at once" and "the family number only to the one who accepted": the family
    agreed to share with that agyari, and these are the people praying for it.
  - **The family goes into the panthaky's own book and each praying app mobed's own book**
    (each private, D2; reminders off, D4), with the days on each one's calendar and the memorial
    one tap away.
  - **A "Mobeds" page in the panthaky's diary:** the agyari's approved mobeds in the app appear on
    it by themselves, with their numbers, and the panthaky adds others by name and number (with
    the consent tick, as for "Our mobeds"). Each has Call and WhatsApp buttons. Only that agyari's
    confirmed panthakys see it; mobeds of other agyaries stay invisible.
  - New WhatsApp templates are needed for the all-set messages; sending stays off until Meta
    approves them, with STOP, the pause switch, the caps and D9 as before.
  - **Answers of 21 Nov 2026 (second round):**
    - The call-out is replaced by **`prayer_request_mobeds_v2`**, which also says that the details
      come once enough mobeds are going and that a mobed's name and number go to the family.
    - **"Still short"**: the panthaky is told **4 hours before the Geh-saarnu** if places are still
      empty (at once if the request comes later than that).
    - **Standbys and backing out:** a mobed who says Yes after the places are full is told "Enough
      mobeds are going this time" and gets no details, but is **kept as a standby, in the order
      they answered**. If a mobed going backs out ("I can't go any more" in the app, a button on
      their WhatsApp details message, or the panthaky marking it), the place reopens, the first
      standby is asked again, and the panthaky is told "<name> can't go; we have asked <standby>".
      If that standby says no or does not answer in time, the next one is asked; when none is
      left, the panthaky is told to find someone. The family is told the new names once the place
      is filled again.
    - **The Mobeds page is for panthakys only** for now.
  - **Answers of 21 Nov 2026 (third round):**
    - **App mobeds answer in the app too.** The agyari's mobeds who use Mobed Diary get the request
      in their Requests tab and as a phone notification, and can tap "I can pray" or "Not this
      time" there as well as on WhatsApp; whichever answer comes first counts. In "Come to me
      first" they see it only once the panthaky asks everyone (or the safety net does).
    - **No panthaky in the app:** a mobed's "Not this time" answers only for them. The request stays
      open for the others; when everyone asked has said no, it closes and the Doongerwadi is told
      "Nobody at <agyari> can take it" so they can send it elsewhere. (This settles the old
      follow-up "should one decline close a request for the whole agyari".) A confirmed panthaky's
      "We can't take this" still closes it for the agyari.
    - **No answer for an hour:** if nobody at the agyari has done anything with a request for 1
      hour, the Doongerwadi is told "No answer yet from <agyari>" with "Send to another agyari".
      The request stays open there until the Doongerwadi withdraws it.
    - **If the panthaky's own account is switched off after a request reached them**, the safety
      net (if set) still asks everyone, since nobody else could act (lead's choice, step 2).
  - **Joining another agyari needs its panthaky's confirmation (owner, 22 Nov 2026, from the
    security pass).** Until now an approved mobed could join any agyari and at once receive its
    prayer requests (and, by taking a place, the family's contact in their book). From now: a
    mobed who joins an agyari gets its prayer requests, is asked in its call-outs and appears on
    its Mobeds page as one of its mobeds **only after that agyari's confirmed panthaky confirms
    them** on the Mobeds page (with no panthaky in the app, the admin confirms). The admin's
    approval of a new sign-up confirms the agyari they signed up at. Memberships from before stay
    confirmed. The panthaky can also take an app mobed off the list for requests. Joining itself
    stays open (D1.4) and still never grants anyone's behdins.

## D11. Words, greetings and names: a Parsi app (22 Nov 2026)

The owner found "Namaste" in a ready-to-send WhatsApp message (live since 18 Nov) and said: "I am
trying to make this a good Parsi app." Binding from now on:

- **A mobed is greeted "Sahebji" and their first name** ("Sahebji Hormuz, ..."): a title typed
  before the name (Er., Ervad, Dasturji, ...) is left out. Never "Namaste" or any other greeting
  that is not the community's own.
- **A behdin (family) is always shown and addressed by their own full name** as they gave it, not
  by a first and middle name ("Sahebji <full name>" in the family message).
- **Examples written for mobeds** (e.g. "Er. ..." as a sample name) belong on mobed and Doongerwadi
  screens only. The behdin side (R4) gets its own words and examples, thought through for families.
- **Behdins will use their own app: anything that touches their side is thought through properly
  and shown to the owner before it is built.**
- **The owner checks every text in the app** (messages, greetings, placeholders, names,
  notifications, screens): an inventory of all of them is made for the owner to confirm or change.
  Open from this review: how names are typed in (today a free text with the title in it, e.g. at
  sign-up "e.g. Er. ...", against the title choice plus name used for behdins), to settle with the
  inventory and R4.

### D11, the owner's word review (23 Nov 2026)

The lead reviewed every text in the app (2,135) and brought 38 for the owner; the owner's answers
(page "Words to fix") are binding:
- **Messages:** "Sahebji {first name}" opens the panthaky's WhatsApp to a mobed and the manager's
  ("Sahebji {first name}, this is {manager} of {Doongerwadi}, about the prayers for {departed}.");
  reminders read "Sahebji {family name}, a reminder from {mobed} of {fire temple}: ..." and every
  closing line reads **"May the ruvan of the late {departed} attain Garothman Behesht."** (reminders,
  the reminder template v2, the memorial share, the family message); a mobed whose yes is no longer
  needed gets "Sahebji {first name}, this prayer request has been closed, so you are not needed for
  now, but we will keep you updated. Thank you."; templates 5, 6 and 8 say "For anything else, please
  contact {contact}" (the panthaky, else the first mobed going).
- **D6 changed:** the one reply to a family's STOP ends **"Ushta te."** instead of "May you and your
  family be in peace."
- **Words:** Y.Z. 1396 (not Y1396); Lagan (not Wedding); Vendidad; Salgreh; Rapithwan and Uzirin;
  Dasmu and Chhamsi; "Passed away" (not Died); "Days of prayers" (not Obsequies); "Confirmed" (not
  All set); "Waiting list" (not Standby); "Outside the fire temple" (not Offsite); ₹ everywhere;
  "Add a behdin" on the manager's screens; plain words for every error a user can see.
- **The general word is "fire temple"** (it covers agiaries and Atash Behrams); the place's own name
  wherever the app knows it; "agyari" in on-screen text goes.
- **Examples:** "e.g. Rustom", "e.g. Er. Jehangir Mistry", "e.g. Zubin Mistry"; the sign-up example
  "e.g. Er. Pervez Kias" stays (owner: keep). The greeting skips only Parsi titles (no Shri / Smt, and
  "Dastur" is a surname; "Dasturji" is the title).
- **State names in the fire temple list:** Gujarat, Rajasthan, Madhya Pradesh, Uttar Pradesh, and
  **Telangana** for the three in Hyderabad and Secunderabad (the lead's correction of his own
  suggestion "Andhra Pradesh": Telangana since 2014).
- **Kept:** the role name "Caretaker" (panthaky, mobed and caretaker are the three roles; nothing in
  the app grants caretaker yet).
- **Changed 23 Nov 2026 (owner, on Meta's warning): no blessing in the two WhatsApp templates.**
  When the reminder template v2 was submitted, Meta's form said it reads as Marketing and "will be
  rejected" as Utility; Meta counts greetings and well-wishes as Marketing, and the four templates
  without the blessing were accepted. The family's template (5) and the reminder template v2
  therefore drop "May the ruvan of the late ... attain Garothman Behesht." and close with plain
  words: 5 ends "Please contact {contact} for anything else."; the reminder v2 ends "The prayers are
  already arranged; you need not reply." One blank fewer in each. The blessing stays everywhere else
  (the mobed's own reminder message, the family's wa.me message, the memorial share, the app). Both
  templates are laid out in short lines (owner, same day), and the reminder v2 has a 6-hour validity
  like the live reminder.
- **Owner, to do separately:** the Play description, the privacy policy and the app's other legal
  words must match the business model (agyaries pay, funeral places and families are free, payments
  later) "to avoid lawsuits", with the lawyer.

## Not decided yet

Separate WhatsApp numbers for sign-in and reminders; price and payer; Gujarati reminders; the
privacy policy and the lawyer's answers; whether the repository goes public before the
security fixes are done (it should not).

## Amendment, 24 Nov 2026: who can lift a STOP (D2, D4, D6)

Owner's decision. The behdin can still stop WhatsApp by replying STOP. **The panthaky can turn it back on**
("the behdin can stop, but once the panthaky starts it, it starts again"): from the Mobeds page (Turn WhatsApp
back on, for someone on the list who replied STOP) and when they confirm "they asked me to" on a behdin of
their own book; both clear the number's own STOP (`reminder_opt_outs`) as well as the record's. Every other
mobed's record of the number stays stopped until that mobed asks. A plain mobed's "they asked me to" still lifts
only their own record. The person can reply STOP again at any time. Turning reminders on for someone who replied
STOP is one sheet (the consent words and the warning, one confirm), not two prompts.

Not now: a number that sends "hi", "hello" or "start" being answered with what it can do. That is a flow for the
behdin app (R4: choose an agyari, book a machi, see events); it is designed with it.

## D12. Simplifying the Doongerwadi side (owner, 24 Nov 2026)

Decided while walking the Doongerwadi screens on the phone ("too complicated"):

- **Recording a death is four short steps, family first** (one group of questions per screen, Back, a review
  before Send, like New machi): 1 the family (name and number: from the place's book, Import from contacts, or
  typed); 2 the departed (title, name, father's or husband's name, date of death); 3 the prayers (days,
  Geh-saarnu, Uthamna, mobeds wanted); 4 which fire temple, then Send. The separate "family's fire temple"
  field and the separate "Ask a fire temple" screen go: step 4 is that choice.
- **Names that are not known are simply left empty** (the departed's name, the father's or husband's name); only
  the family's contact and the date are needed. Not a "Not known" tick.
- **Defaults:** four days; the date of death is today (editable); no time of death. Geh-saarnu and Uthamna start
  empty until the owner gives the usual rule.
- **No fire temple in mind: the Doongerwadi's manager chooses**, by their own knowledge and the fire temples'
  workload. The app never picks (not the one with most behdins: behdins are private to each mobed, D2), and
  never asks several at once. **The list is already there when the step opens, with no typing**: only the fire
  temples that have someone in Mobed Diary, the family's usual one first, nearest first where a pin exists and
  by town where not (today's Suggested list was empty because almost no fire temple has a pin yet, and the
  search shows nothing until a letter is typed). A search box stays above it.
- **Dates are written day/month/year, 24/11/2026, everywhere** in the app: screens, slips, notices, messages,
  PDFs (the weekday may go before it where there is room). Date boxes follow the phone's own setting.
- **Departed names for the family:** decided the same day, see the amendment below.

**Departed names for the family: decided 24 Nov 2026.** When a Doongerwadi manager records a death, the
departed's name and the father's or husband's name are saved as names of the departed for that family, newest
on top, so later bookings and slips offer them first. The owner chose a pool for the PERSON, keyed by phone
number: one number is one person with many roles (behdin, mobed, Doongerwadi manager, trustee), and their
names follow the person. The privacy rule, built exactly:

- Only the account that signs in with that number can read the pool. No other mobed, no manager (not the one
  who recorded the death) and no admin screen can read it, and nothing asks for it by phone number. Not even a
  count of it is shown to the admin before an erasure.
- A mobed gets names for a family only as **copies in their own book of behdins**, and only at All set for a
  request they are assigned to (they already see the departed's name for the prayers, so nothing new is shown).
  The pair goes on top of the family's saved names there; one already saved with the same names is not added
  twice, and All set running again changes nothing. A mobed who only types that number as a behdin sees none of it.
- One entry per death record: editing the record's names or number changes that entry, and emptying both names
  removes it. Nothing is written when both names are empty.
- It goes when that family is erased (docs/DATA-REQUESTS.md) or when that person deletes their account, and never
  because of its age (D8).
