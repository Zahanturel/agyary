# Phase 2 build plan (the Doongerwadi side)

What to build, in what order, and how each step is checked. The decisions are D10 in
`docs/DECISIONS.md`; the research and full design are in `docs/phase2-doongerwadi-research.md`
(section 8). Written 18 Nov 2026. Steps are done one after another, each by one helper (subagent)
working in this checkout, and each is checked before the next starts.

## The owner's answers for the build (18 Nov 2026)

- **Releases, each made of small commits** (one piece per commit, so a fix or a revert is easy):
  - **R1:** Step 1 (agyari locations) + Step 2 ("mobed or panthaky" claim).
  - **R2:** Step 3 (Doongerwadis and managers: sign-up, the owner's approval, admin counts).
  - **R3:** Steps 4-5 (record a death, send to an agyari, the Requests tab, accept).
  - **R4:** the behdin (family) side. To be discussed with the owner before anything is planned.
  - The owner is asked before each push.
- **Location:** a map to drop a pin (Leaflet with OpenStreetMap, free), **"I'm at the agyari now"**
  (the phone's own location puts the pin on the map), search by address or area (OpenStreetMap,
  free), and **"Find on Google"** by name (Google Places, the owner's own Google Cloud key). The
  key lives only in the server's `.env` and every Google call goes through our server; without a
  key the Google button is not shown. The owner makes the account and key, and sets a daily cap
  in Google Cloud so it cannot bill. Leaflet 1.9.4 is kept in the app's static folder (owner's
  yes to download it from cdnjs).
- **Who may set or move a pin:** any approved mobed or panthaky of that agyari, and the admin.
- **Requests** on the agyari side are **a fourth bottom tab** beside Machi, Calendar and Behdins,
  with the red count on it. (This changes D7's three tabs; record it in DECISIONS when built.)

## Beyond R3: the owner's ideas (18 Nov 2026, to discuss before planning)

Not decided and not planned; written down so nothing is lost. To be talked through with the owner
when R3 is done.

- **A behdin (family) app (R4):** families see the agyaries and mobeds in the system, choose them,
  and book services directly. Free for behdins.
- **Each fire temple lists the services it offers** (and prices), set up at sign-up. The app
  already has a per-agyari service catalog (`services`: name, default price, mobeds needed,
  duration), seeded from a standard list, so this is mostly a setup screen.
- **Payment requests from mobed to behdin**, in the app and outside it (WhatsApp, GPay / any UPI
  app), e.g. "this is your memorial, this is the bill". Works for families who never install the
  app, including those who come through a Doongerwadi.
- **A chat between behdin and mobed** in the app, with payments inside it.
- The paid / unpaid chip might go once payments are tracked by the app.

What is already in the code: `agyaries.upi_id` and `qr_code_url`, a `payments` table with
`upi_intent_link` and `upi_transaction_ref`, and `generate_upi_link()` in
`messaging/booking_service.py` (from the old WhatsApp bot).

Points to settle when it is discussed:
- **Money straight to the mobed's (or agyari's) own UPI ID** through a UPI link or QR is free and
  needs no licence: the money never passes through us. But a plain UPI link cannot tell the app the
  money arrived, so the mobed (or the family, with the UPI reference) still marks it paid. That is
  why the paid chip should stay until something confirms payments automatically.
- **Automatic confirmation** needs a payment gateway (Razorpay, Cashfree and the like): a fee per
  payment (about 2%), and each mobed or agyari signs up and does KYC with the gateway. **Collecting
  money ourselves and paying it out** would make us a payment aggregator under RBI rules: not
  something to take on.
- **Sending the bill to a family not in the app:** by hand from the mobed's own WhatsApp (free,
  works today) or from our WhatsApp number (needs an approved Utility template, costs per message,
  and the consent rules apply).
- **Chat** needs behdin accounts first (R4), plus notifications, privacy and abuse handling; until
  then WhatsApp is the chat.

**The owner's later idea (18 Nov 2026): money through the platform, with a platform fee (about
10%), and automated accounting.**
- **The fee is always shown, never hidden.** India's Consumer Protection (E-Commerce) Rules 2020
  and the 2023 guidelines on dark patterns ban hidden charges and fees added at the last step; and
  in a small community a hidden cut on funeral prayers would cost trust. Two honest ways:
  - a **commission out of the mobed's payout** (the family pays exactly the mobed's price; the mobed
    agrees to the commission in writing when joining and sees it on every payout), or
  - a **small fee shown at checkout** before paying ("Booking fee").
  Either can sit alongside the agyari subscription.
- **We never hold the money.** Holding and paying out others' money needs RBI authorisation as a
  payment aggregator (out of reach). Instead a gateway's **split payments** (Razorpay Route,
  Cashfree split and the like): the family pays, the gateway splits instantly (mobed's share to the
  mobed's KYC'd bank account, the fee to ours) and tells our server, which also makes "paid"
  automatic.
- **Accounting:** a ledger of every payment, fee, payout and refund, reconciled daily against the
  gateway's settlement report; monthly reports, invoices, and a statement per mobed.
- **First, with a CA:** a registered business (LLP or private limited) and business bank account;
  GST registration (the platform fee is a taxable service; e-commerce operator rules such as GST
  section 52 and income-tax 194-O may apply; whether a mobed's religious services are GST-exempt
  is for the CA); terms of use and a fee agreement with mobeds and agyaries; refunds and disputes.

## Rules for every step

- **Live production app.** Put things where the owner said; if a spec is unclear, stop and ask.
  Never fail silently: every failed tap or request says what happened.
- **D2 holds everywhere:** a mobed's behdins, memorials and machis are never visible to anyone
  else. A Doongerwadi manager never learns which mobed has which family. A request's family
  number is shown only to the person who accepted it.
- **Access:** new endpoints use `get_current_user` (gated by D9) unless they are part of signing up.
  Nothing is sent to or under an account whose access is not "on".
- **UI conventions** (17 Nov UX pass): `showError` / `showInfo`, `flagProblems`, `screenFailed`,
  `flashError` / `flashInfo`, `openSheet`, one `.action-bar`, `toTop()` for a new step.
- **Migrations:** check constraints with `op.f()`; prove them with `tests/test_migrations_run.py`
  (the suite itself uses `create_all`).
- **Tests (owner, 18 Nov 2026: time and tokens):** each step runs only the test files it adds or
  touches and the nearest related ones. **No full-suite run on this computer** (18-19 minutes
  here): GitHub runs the whole suite on every push (about 7 minutes) and the deploy waits for it
  (`deploy` needs `test`), so a failure blocks the release and is fixed then. One pytest at a time
  (they share `agyary_test`).
- **Browser check: once per release**, covering all of that release's steps, not after each step.
  A scratch database and port 8001 (or 8011), never the owner's :8000 server.
  Clear the service worker and caches before checking JS. Signing in uses the debug-only simulate
  route.
- **Commits:** a local commit at the end of each step, in the owner's name, with no co-author
  line. **Never push** without the owner's yes for that push (a push to master deploys).
- **No WhatsApp messages from our number** for any of Phase 2.
- **Public repo:** no real people's names or numbers in code, tests or docs.

## The steps

### Step 1. Agyari locations

- `agyaries`: latitude, longitude, and where the position came from (`town` from the seed list, or
  `pin` set by a person). Migration.
- A one-off, idempotent script that fills the town-level positions for the seeded agyaries from
  `docs/phase2-doongerwadi/` (matched by name and city, only where empty). It is run on the server
  only with the owner's yes.
- The location picker (see the owner's answers above) when a fire temple is created, and an
  "Edit location" for an existing one, open to its approved mobeds and panthakys and the admin.
- "Find on Google": a server route that calls Google Places with the server's key, rate-limited,
  for signed-in users only; the button shows only when the key is set. A separate commit.
- Tests: the migration runs; the seed script fills only empty rows; only allowed people can move
  a pin.

### Step 2. "Mobed or panthaky" at sign-up

- At sign-up, after choosing the fire temple: "I am a mobed / I am the panthaky here".
- Stored as a **claim** (a new column on `agyary_users`). The real `role` is unchanged until the
  owner confirms it on Admin -> Mobeds. A confirmed claim sets `role = panthaky`.
- Admin -> Mobeds shows the claim and has "Confirm as panthaky".
- Tests: a claim never grants panthaky powers (D7 machi visibility) before confirmation.

### Step 3. Funeral places and their managers

- Tables: funeral places (name, kind: doongerwadi / prayer hall / aramgah, town, location, who runs
  it) and managers (user to place).
- Admin: a "Doongerwadis" page to add and edit funeral places; the Mumbai Doongerwadi and the Worli
  Prayer Hall are added by the owner by hand.
- Sign-up: a manager chooses "I work at a Doongerwadi or prayer hall", picks their place, and waits.
  Admin -> Mobeds (or a sibling page) shows them for approval, with the same on/off switch (D9).
- Managers cannot reach anything a mobed has (behdins, calendar, machis): tests prove it.
- Admin overview: counts of mobeds, panthakys, fire temples in use, funeral places and managers.

### Step 4. Recording a death and sending the request (manager side)

- The funeral record form (fields in the research doc, section 6): prayed name with title, date
  with Roj and Mah (D5), four days or one, bungli, Geh-saarnu day and geh, Uthamna day and time,
  family's preferred agyari, one family contact.
- Choose the agyari: "Suggested" (nearest first, within 500 km, by straight-line distance from the
  funeral place) and "Search all".
- The tick "The family agreed to share their name and number with this agyari". No tick, no send.
- Recipients: the agyari's confirmed panthakys; if none, its approved mobeds whose access is on.
- In-app notice plus web push. Web push is made available to every user (today it is admin-only),
  with "Notifications on this phone" in Settings.
- The manager's list of records with each request's state (waiting, accepted by X, declined).
  They can send to another agyari.

### Step 5. The request on the agyari side

- A "Requests" place with a red dot and a count (where: see questions).
- Before accepting: prayed name, funeral place and bungli, prayers and times. No family number.
- Accept: makes the behdin in the accepter's own book (or uses their own existing record of that
  number), opens the memorial form already filled in (name, date, Roj and Mah) for them to check
  and save, and puts the Geh-saarnu and Uthamna on their calendar. Reminders stay off.
- Decline, with an optional reason. The manager is told in the app.
- When several people were asked, the first to accept takes it; the others see "taken".
- Tests: D2 isolation (no other book is read), the number only after accept, first accept wins.

### Step 5b. Automatic WhatsApp on accept (right after R3)

- Templates 1-3 of `docs/phase2-whatsapp-templates.md`, sent when the accepter ticked "Share my
  name and number"; the family's only with their agreement recorded by the manager's tick (new
  wording). Off until Meta approves (a setting), with STOP, pause switch, caps and D9.

### Step 5c. The panthaky's WhatsApp call-out (right after R3)

- An agyari's list of mobeds: its approved app mobeds, plus mobeds the panthaky adds by name and
  number with a consent tick (like behdins, private to that agyari's panthakys).
- On a request, "Ask our mobeds on WhatsApp": template 4 with Yes / Not this time buttons; the
  webhook records each answer; the panthaky sees every Yes and picks who goes; those picked get
  template 2 (details); the rest get a short free-form "enough mobeds are going" reply.
- Payment stays with the panthaky. Off until the templates are approved.

### Step 6. Whole check, then the owner's push

- The full test suite; a security pass over every new endpoint (access, D2, ownership checks).
- A browser walk-through of both sides with a scratch database: manager signs up -> approved ->
  records a death -> sends -> panthaky gets the dot -> accepts -> behdin and memorial are there.
- Update `docs/STATUS.md`. Then ask the owner to push. After the deploy, check the live site.
- Offer a real-phone check of the notifications (push has never run on a real phone).
