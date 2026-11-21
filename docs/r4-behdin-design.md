# R4: the behdin (family) side. Design draft

**Draft, 22 Nov 2026. Nothing is decided and nothing is built.** It gives the choices, a
recommendation for each, and the questions for the owner (section 10), in rounds of up to four.
Once answered, the answers go into `docs/DECISIONS.md`, mockups are made (section 9), and the
build plan (section 8) is fixed. D1 to D10 bind everything here.

---

## 1. Summary

R4 lets a family use Mobed Diary themselves. They sign in with WhatsApp, like mobeds, as a third
kind of account: "I am a family". They find the fire temples that take requests in the app,
Atash Behrams first. They see each temple's services and usual prices, and the mobeds who chose
to be shown. They ask for a service on a date. The request reaches the agyari's **Requests tab**,
on the same "Who will pray" board as a Doongerwadi's. When enough mobeds are going it is **All
set**: the family sees who is coming, and the mobeds going get the family's contact and the
family in their own book. No money changes hands in the app. In the first release a family's
request sends nothing from our WhatsApp number (only sign-in codes go, as for mobeds). A mobed's book stays private (D2): signing in with a number never
shows a family what any mobed holds about them.

**Recommended releases:**
- **R4.0**, the agyari side gets ready: an Atash Behram mark, "Services and prices", and two
  switches.
- **R4.1**, the first useful release: sign-in, find a temple, ask, follow, cancel, All set.
- **R4.2**: the family's own memorials, a mobed sharing a memorial, family members, changing a
  date.
- **R4.3**: families met at a Doongerwadi, WhatsApp confirmations on request, Gujarati.

---

## 2. Who behdins are

- **Families who keep prayers**: Jashan, Afringan, Farokshi, Baaj, Machi, Navjote, weddings.
  Memorials bring them back for years.
- **Often elderly**, alone or as a couple, on WhatsApp but new to apps. They need large text,
  few steps and few words.
- **Or their adult children abroad** (the UK, the US, Canada, Australia, the Gulf), who arrange
  prayers for parents in India from another time zone, on a number outside India.
- **Gujarati first for many**; the app is English only today.
- **Some will only ever use WhatsApp.** They must keep working exactly as today. The family app
  is an extra door, never the only one.
- **Families met at a Doongerwadi** (D10), on the worst day of their lives. Any first contact
  from us must be gentle and ask nothing of them.
- **One family, many people**: a widow, a son in Pune and a daughter in Toronto may all care
  about the same memorial.

---

## 3. What the app already has, and what is missing

**Can be reused:**
- `users.account_kind` (`mobed`, `funeral_manager`). A third kind, `family`, fits the pattern,
  with its own guard like `get_current_manager`. Sign-in, sessions, deletion and the D9 switch
  come with it.
- The per-agyari `services` catalog: name, `default_price`, `min_mobeds`, `offsite_capable`.
- `bookings.status = 'requested'` already means "a customer asked".
- The parked `agyaries.auto_booking_enabled`, read by nothing, could become "Take requests from
  families". Also there: `contact_phone` and the map pin.
- The Requests tab and the R3.1 board, All set, and "into each one's own book".
- The pure calendar engine (`calendar/memorial.py`), so a family's own dates need no mobed.
- The name editor, and the words "Gujrela nu (for the departed)", "Khushali nu (for happiness)"
  and "Hama Anjuman (for the community)".
- Web push for every account, and Erase a family.

**Missing:**
- **No prices anywhere.** The standard list is seeded without them, and no screen sets them.
- **No Atash Behram mark.** The seed list has types (81 Adarian, 54 Dadgah, 14 Prayer Hall, 8
  Atash Behram in India); `agyaries` has no column for them.
- **One number, one account, one kind** (`users.phone` is unique). See 5.11.
- **The privacy page says families do not use the app.** It must be rewritten, and the lawyer's
  open questions (LEG-11) matter more now.

---

## 4. How others do it (light research, 22 Nov 2026)

- **Prices come before booking**, often all in: pandit apps include the samagri
  ([YatraDham](https://temple.yatradham.org/pujas);
  [Speedy Pandit](https://apps.apple.com/in/app/speedy-pandit/id6478028355)). So a blank price
  should read "Ask the agyari".
- **Cancellation rules are stated up front.** TTD makes paid sevas final, as its receipts say
  ([Gokshetra](https://gokshetra.com/tirumala-darshan-tickets-cancellation-seva-online-ttd-process));
  private apps allow cancelling up to a few days before (YatraDham). With no money in R4,
  cancelling can be free, as long as it says who is told.
- **Trust comes from official channels and proof.** In July 2026 TTD said it has no agents
  ([News On Air](https://newsonair.gov.in/ttd-urges-devotees-to-book-srivari-darshan-only-through-official-website/)).
  Puja apps send a video on WhatsApp afterwards
  ([Sri Mandir](https://apps.apple.com/app/id1637621461)). For us: list only the agyaries that
  chose to take requests, and let All set name real people.
- **Law.** India's DPDP Rules were notified on 14 Nov 2025
  ([SCC Online](https://www.scconline.com/blog/?p=371058)). Their duties start on dates up to 14
  May 2027
  ([Tribune](https://www.tribuneindia.com/news/business/govt-notifies-digital-personal-data-protection-rules-rollout-in-phases-specified-obligations-for-data-fiduciaries)).
  A child's data needs a parent's verifiable consent (Rule 10), so family accounts are for 18
  and over.

---

## 5. The questions, with options and a recommendation

### 5.1 Signing in

- **A. The same app, a third kind of account**: "I am a family (behdin)" on the first screen,
  then WhatsApp sign-in (the code, or "send us a message").
- **B. A separate family app**: a friendlier name, but a second app and APK to keep.
- **C. No account, a link on WhatsApp per request**: few steps, but every link is a paid message
  from our number, and there is nowhere to keep memorials.

**Recommended: A.** "Where do you work?" becomes "Who are you?". The server refuses family
accounts every mobed and manager route, and the reverse, as it does for managers. The person
ticks "I am 18 or over". The name "Mobed Diary" stays for now.

### 5.2 What a behdin sees

- **Fire temples**: only those that take requests from families (5.4) and have an approved mobed
  whose access is on. Three ways in: **Atash Behrams**, **Near me** (from the pins) and
  **Search**.
- **A temple's page**: address, pin, the public number if set, then **Services** (each with its
  usual price or "Ask the agyari", mobeds needed, "at home possible"), then the mobeds shown, then
  **Ask for a service**.
- **My mobeds**: only mobeds the family is connected with, through an All set or a shared
  memorial, with Call and WhatsApp.

Which mobeds are shown: (a) every approved mobed, (b) those who opt in, (c) none.
**Recommended: (b), names only, off by default.** Some mobeds will not want to be found, or to
be booked around their panthaky.

### 5.3 Asking for a service

A request is a wish; nothing is confirmed until the agyari fills it. One question per screen:
1. **What**: one of the agyari's services.
2. **For what**: Gujrela nu, Khushali nu or Hama Anjuman.
3. **When**: a date with its Roj and Mah shown, then the geh or time.
4. **Where**: at the agyari, or at home if the service allows it. For home, only the area now;
   the address goes to those going at All set.
5. **Names to pray**, from the family's own saved list.
6. **Who to call on the day**: me, or someone else, with a tick that they agreed. This lets a
   son abroad book for his mother in Mumbai.
7. **A mobed you would like** (optional), and a note of up to 200 characters, with no links,
   numbers or @-handles (D1).
8. **Review**, with one sentence above Send: "Your name and number go to <agyari>'s panthaky and
   the mobeds who pray, once it is all set." The price reads "Usual price ₹X, to confirm with the
   agyari".

### 5.4 How the request reaches the agyari

- **A. The Requests tab, on the R3.1 board.** It goes to the confirmed panthaky, or with none to
  the approved app mobeds, with the red count and a phone notification. There is one place per
  mobed needed (`min_mobeds`), filled by I'll pray, by marking Going after a call, or by the app
  mobeds. All set comes when every place is full.
- **B. A separate list with Accept and Decline**: simpler, but a second way of doing one thing.
- **C. Straight to the mobed the family chose**: quick, but it goes round the panthaky and fails
  if that mobed is away.

**Recommended: A.** A Jashan next month is not a funeral tomorrow, so three things differ from a
Doongerwadi's request:
- **It always goes to the panthaky first**, whatever "Everyone at once" says. With no panthaky,
  the app mobeds answer I can pray or Not this time, as in R3.1.
- **There is no WhatsApp call-out from our number.** The board's Call and WhatsApp still use the
  panthaky's own phone.
- **There is no "still short" alert.** Instead, if nobody acts in 24 hours, the family is told
  "No answer yet", with "Ask another agyari".

**Before it is taken**, the card "A family asks for a Jashan" shows the service, date, Roj, Mah,
geh, where (area only), the names, the mobed wished for, the note and the family's name. It
never shows their number. The number and any address come at All set, as in R3.1.

**An agyari takes requests only once its confirmed panthaky, or the admin, turns on "Take
requests from families"** (off by default). This keeps families away from temples whose prices
nobody checked, or that do not want requests.

**At All set**, as in R3.1 and as D2 foresaw (only the assigned behdin, only to that mobed):
- each going app mobed gets the booking in their own book (their own record of the number, or a
  new one), on their calendar with its slip, with the names copied in. Reminders stay off (D4).
  A Machi lands on their own board, with a warning first if that geh is taken;
- the family is told in the app and on their phone who will pray, with names and numbers, the
  panthaky, the date and the place;
- the panthaky and those going see the contact, with Call and WhatsApp.

### 5.5 Confirmations, changes and cancellations

- **"My requests"** is the one place that is always right: Waiting, Finding mobeds 1 of 2, All
  set, Can't take it, Cancelled. It is backed by in-app notices and push.
- **The family cancels** any time before the day, after a sheet: "Cancel the Jashan on <date>?
  <agyari> and the mobeds going will be told." Inside 24 hours the sheet adds "Please also call
  them". The mobed's booking reads "Cancelled by the family" and stays in their book (D8).
- **The agyari declines** with "We can't take this". The family gets **Ask another agyari**, with
  the request copied.
- **A mobed backs out** through the R3.1 5b path, in the app only. The family is told the new
  names.
- **Changing the date**: in R4.1, cancel and ask again; in R4.2, "Ask to change the date" and
  "Suggest another time".

### 5.6 Their own memorials, and the mobed's record

**A mobed's book is never merged with a family's account, and never shown to it (D2).** There
are three separate things:
- **The mobed's memorial**: private, as today.
- **The family's own memorial** (R4.2): name and date (or Roj and Mah), worked out by the same
  engine. The family gets phone notifications the evening before, never in the first ten days,
  and never on WhatsApp.
- **A shared memorial** (R4.2): the mobed taps **Share with the family in the app**. The family,
  signed in with that number, sees a read-only view: the name, the dates and prayers, the agyari
  and the mobed. Never notes, paid marks, history or other families. **Stop sharing** ends it.
  **Keep my own copy** makes it the family's.

Linking: (a) automatically by number, (b) only when the mobed shares, (c) the family asks and the
mobed accepts. **Recommended: (b)**, plus **Invite the family**, which opens the mobed's own
WhatsApp with a link (free, no template). (a) is AZ-3's danger: a number in three books would
show the family that three mobeds keep them, and what each wrote. (c) can come later.

### 5.7 Consent and STOP

- **Sending a request is the family's consent** to share with that agyari and those who pray, in
  one sentence above Send. A "call on the day" number needs a tick that the person agreed.
- **WhatsApp reminders stay the mobed's** (D4): consent in person, on the mobed's record. A family
  account never turns them on.
- **STOP stays global per number** (D2). The family's Settings has **Stop all WhatsApp messages
  from Mobed Diary**, which does what a STOP reply does.
- **Lifting one's own STOP**: today only a mobed can ("they asked me to"). **Recommended:** a
  person signed in with that very number may lift it. Each mobed's reminders then stay off until
  that mobed asks again. This changes D2's wording.

### 5.8 What stays on WhatsApp

- Sign-in codes.
- Everything families get today: reminders (D4), schedules, STOP and its one kind reply (D6), and
  the Doongerwadi's All set message.
- **The chat.** There is no chat in the app. After All set, Call and WhatsApp open the person's own
  phone.
- **Not in R4.1:** any message from our number caused by a family. That means no new templates,
  no cost, and nobody can make us message a stranger by typing a number. R4.3 may add an opt-in
  Utility confirmation ("Also tell me on WhatsApp"), with STOP, the pause switch, the caps and D9.

### 5.9 Notifications

- **The family** gets in-app notices and push for All set, can't take it, no answer, a place
  reopened, cancelled, and (R4.2) memorial evenings. The lock screen never names the departed.
- **On an iPhone**, push needs the app on the Home Screen; "My requests" stays the place to check.
- **The agyari** gets the Requests red count and a push, as for a Doongerwadi; a cancellation is a
  notice to everyone going.

### 5.10 Families abroad

- **Times are India time, labelled so**, with the phone's own time beside in grey when it
  differs. The day is the Parsi day in India.
- **Numbers outside India** are allowed. "Send us a message" is offered first: it is free to us
  and works wherever WhatsApp does. A code sent abroad costs more.
- **"Call on the day"** names someone in India. Push reminders follow the phone's own evening.

### 5.11 Several family members, and one number

- **A. Each person has their own account**, with nothing shared.
- **B. Add a family member**: invite by number. They sign in with their own WhatsApp and accept.
  Both then see the family's requests and memorials, and either can leave.
- **C. One shared login**: not possible, because the number is the identity.

**Recommended: A in R4.1, B in R4.2.** A mobed's number cannot also be a family account. A mobed
books for their own family in their own diary.

### 5.12 Erasure, and D8

- **Delete my account** (D6) removes the family's own things at once: the account, names,
  memorials, and their name and number on each request ("Erased"). Each mobed's record and
  booking stay, because they are the mobed's (D2). So does a STOP.
- **A tick: "Also remove us from every mobed's and Doongerwadi's book".** Sign-in has proven the
  number (DATA-REQUESTS step 1). The admin then runs Erase a family and tells the mobeds. It is
  not automatic, because it reaches upcoming bookings.
- **D8 holds:** nothing is deleted because of its age.

### 5.13 Access (D9)

- **A. You approve every family**: safe, but a family praying this week waits, and every family
  is work for you.
- **B. No approval, with limits and your switch.** **Recommended.**

The limits for B:
- at most 3 requests waiting at once, 2 at one agyari, and 5 new a day; lower in the first week;
- the bot check at sign-in, which is already live;
- a daily cap on new family accounts, with an alert to the admins;
- the panthaky's **Don't take requests from this family**. The family reads only "This agyari
  isn't taking requests in the app right now. Please call them";
- **Admin -> Families**, with the D9 switch. A family switched off loses its waiting requests.

Behdins are always free (D10).

### 5.14 The Doongerwadi's book of behdins

- **It stays private to that place** (D10). It is never shown to families, never linked to their
  accounts, and never used to invite anyone from our number, which would be marketing.
- **R4.3:** a new version of the family's All set template carries a link to the app. The family
  contact, signed in with that number, sees "Prayers for <departed>": only what the message
  already said. **Keep these dates** makes their own memorial. This happens only where the
  manager's tick recorded the family's agreement to hear from Mobed Diary.

### 5.15 Later, one line each

- **Parsi "Learn" cards**: a separate proposal; nothing in R4.
- **Payments**: see the payments plan. R4 shows prices, takes no money, and the paid chip stays
  the mobed's.

---

## 6. What mobeds and panthakys see differently

**New:** the family's card in the Requests tab. Bookings tagged "Asked in the app" or "Cancelled
by the family". On a memorial, Share with the family and Stop sharing; on a behdin, Invite the
family (R4.2). For the panthaky: Services and prices, Take requests from families, and Don't take
requests from this family. For each mobed: Show my name to families.

**Never:** whether a number has a family account (there is no lookup); the family's requests
elsewhere, own memorials or members; anything another mobed holds (D2); the number before All
set.

**A family never sees:** any mobed's book, notes or paid marks; other families; the Mobeds page; a
mobed's number before All set; which mobed keeps which family (D10); or the Doongerwadi's book.

---

## 7. Risks

1. **A leak between a mobed's book and a family's account**, by matching numbers. *Guard:* no
   automatic linking; sharing only by the mobed's tap. A test checks that a number held in three
   books shows the family nothing.
2. **Spam and abuse**: fake requests, or a family harassing a mobed. *Guard:* the 5.13 limits,
   the note's rules, agyari opt-in, the panthaky's block, your switch, and no WhatsApp caused by
   a family.
3. **Pretending to be a mobed or agyari.** Any approved mobed can create a temple, and names are
   free text. *Guard:* listing only after a confirmed panthaky or the admin turns it on; mobeds
   shown only by their choice, under their approved name, with later name changes shown to the
   admin.
4. **Wrong prices** cause disputes and blame. *Guard:* only the panthaky or the admin sets them,
   with "last checked <date>"; "to confirm with the agyari"; a blank reads "Ask the agyari".
5. **Elderly users** get lost or press Send by mistake. *Guard:* large text, one question per
   screen, review before Send, a sheet before Cancel, "My requests", and "call on the day" so a
   relative can help.
6. **Trust.** Mobeds may fear losing families or being bypassed; families may fear being watched.
   *Guard:* opt-ins, panthaky first, private books, plain words about who sees what. Start with
   one or two willing agyaries.
7. **Law**: a new privacy page and terms, 18 and over, and LEG-11 answered before real families
   sign up.

---

## 8. Build plan (releases of small commits, as in Phase 2)

The Phase 2 rules apply: one helper per step, one piece per commit, only the nearest tests here
(GitHub runs the full suite), one browser walk-through per release on a scratch database (:8011),
and the owner's yes before each push.

**R4.0 Get the agyari side ready** (families see nothing)
1. A `kind` on agyaries, with Atash Behram filled once from the seed list (a script run with the
   owner's yes). *Tests:* the migration; the script fills only empty rows.
2. **Services and prices**: price, mobeds needed, at home, shown or not, order, last checked.
   *Tests:* only a panthaky or the admin changes prices.
3. **Take requests from families** (the parked column) and **Show my name to families**. *Tests:*
   who may change them; off by default.
4. A privacy page and terms for families, drafted for the owner and the lawyer.

*Walk-through:* a panthaky sets prices and turns requests on; a mobed shows their name; a plain
mobed cannot change prices.

**R4.1 Families ask for a service**
1. Family sign-up: the third kind, 18+, access on, limits. *Tests:* no mobed or manager route,
   and the reverse; D9.
2. Fire temples and a temple's page. *Tests:* only opted-in agyaries with a mobed whose access is
   on; opted-in mobeds, names only.
3. The family's names and "call on the day".
4. Ask for a service, Review and Send. *Tests:* the note's rules; limits; a past date refused in
   plain words.
5. The agyari side: Requests tab, board, panthaky first, no WhatsApp, the 24-hour notice.
   *Tests:* routing; no number before All set; the first action takes it once.
6. All set into each going mobed's own book and calendar. *Tests:* D2; exactly once under two
   answers at the same moment; a Machi clash warning.
7. My requests, Cancel, Ask another agyari. *Tests:* everyone going told; booking kept (D8).
8. Family Settings (Stop all WhatsApp, Delete with the erase tick), Admin -> Families, the
   panthaky's block. *Tests:* deleting leaves mobeds' books untouched.

*Walk-through:* a family signs up and asks for a Jashan; the panthaky fills the board; All set
shows on both sides; a second request is cancelled; a number already in a mobed's book shows
nothing.

**R4.2 Memorials, sharing, family members**: the family's own memorials and push reminders; Share
with the family, Stop sharing, Keep my own copy, Invite the family; Ask for this prayer; Add a
family member; Ask to change the date and Suggest another time; lifting one's own STOP (if yes).
*Tests:* only what was shared, read-only; Stop sharing hides it at once. *Walk-through:* a mobed
shares, the family keeps a copy and books the next prayer, and a son abroad joins.

**R4.3 Doongerwadi families, WhatsApp on request, Gujarati**: the All set template with a link
(the owner submits it) and "Prayers for <departed>"; "Also tell me on WhatsApp"; Gujarati screens.

**Later:** payments, a chat (WhatsApp until then), and the Learn cards.

---

## 9. Mockups to make with the owner

1. **Who are you?**: the first screen, with the family button and the 18+ tick.
2. **Family home**: My requests, Fire temples, My mobeds, Memorials.
3. **Fire temples**: Atash Behrams, Near me, Search.
4. **A temple's page**: services and prices, mobeds, Ask for a service.
5. **Ask for a service**: one question per screen.
6. **Review and Send**, with the sharing sentence.
7. **My requests**: each state, Cancel, Ask another agyari.
8. **All set (family)**: who prays, Call and WhatsApp, India time and local time.
9. **The agyari's card**, before and after All set.
10. **Services and prices** (the panthaky).
11. **The two switches** in Settings.
12. **Share with the family**: the mobed's sheet and the family's view.
13. **Family Settings**: Stop all WhatsApp, Delete, family members.
14. **Admin -> Families**.

---

## 10. Questions for the owner

Each has a recommended answer.

### Round 1: the shape
1. Should families use **the same app**, signing in with WhatsApp, as a third kind of account?
   *Recommended: yes.*
2. Should families get in **without your approval**, with limits and your switch?
   *Recommended: yes.*
3. Should a family's request go to **the Requests tab and the "Who will pray" board**, always
   to the panthaky first (or with none, to its app mobeds), in the app and on the phone only?
   *Recommended: yes; no WhatsApp from our number in R4.1.*
4. Should **R4.1** be find, ask, follow and cancel, with memorials and family members in R4.2?
   *Recommended: yes, after R4.0.*

### Round 2: what families see
5. Should only agyaries whose panthaky (or you) turned on **"Take requests from families"** be
   listed? *Recommended: yes, off by default.*
6. Should only mobeds who turn on **"Show my name to families"** be shown, by name, with their
   number after All set? *Recommended: yes.*
7. Should **prices** be set only by the panthaky (or you), read "Usual price ₹X, to confirm with
   the agyari", and read "Ask the agyari" when blank? Is "price" the right word?
   *Recommended: yes; the word is yours.*
8. Should **Atash Behrams** be shown first, as their own group? *Recommended: yes.*

### Round 3: the booking
9. Should the panthaky see **the family's name, not the number**, before taking a request, with
   sending counting as the family's consent? *Recommended: yes.*
10. Should the family **cancel any time before the day** ("please also call them" inside 24
    hours), with a change meaning cancel and ask again until R4.2? *Recommended: yes.*
11. Should the family be told **"No answer yet" after 24 hours**, with Ask another agyari?
    *Recommended: yes.*
12. Should the **limits** be 3 waiting, 2 at one agyari and 5 new a day (lower in the first
    week), plus the panthaky's block? *Recommended: yes.*

### Round 4: memorials, consent, privacy
13. Should families keep **their own memorials** (R4.2), with phone notifications only, never
    in the first ten days and never WhatsApp? *Recommended: yes.*
14. Should a family see a mobed's memorial **only when that mobed shares it**, never by matching
    the number? *Recommended: yes.*
15. May a person signed in with their own number **lift their own STOP**, while each mobed's
    reminders stay off until that mobed asks again? (It changes D2's wording.)
    *Recommended: yes.*
16. Should **Delete my account** remove the family's own things at once, with a tick asking you
    to erase them from every book? *Recommended: yes.*

### Round 5: people, abroad, later
17. Should each person have **their own account** in R4.1, with **Add a family member** in R4.2?
    *Recommended: yes.*
18. Should **times be India time** with the phone's own beside, and "send us a message" come
    first for numbers abroad? *Recommended: yes.*
19. Later (R4.3), should the family's All set message **link to the app**, so they can see the
    prayers and keep the dates? *Recommended: yes, with a new template.*
20. Should accounts be **18 and over**, with **English** for R4.1 and Gujarati before families
    are invited widely? *Recommended: yes.*
