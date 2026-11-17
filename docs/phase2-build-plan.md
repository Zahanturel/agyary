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
- **Tests:** one pytest run at a time (they share `agyary_test`). The full suite takes about 18
  minutes: run it in the background.
- **Browser check:** a scratch database and port 8001 (or 8011), never the owner's :8000 server.
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

### Step 6. Whole check, then the owner's push

- The full test suite; a security pass over every new endpoint (access, D2, ownership checks).
- A browser walk-through of both sides with a scratch database: manager signs up -> approved ->
  records a death -> sends -> panthaky gets the dot -> accepts -> behdin and memorial are there.
- Update `docs/STATUS.md`. Then ask the owner to push. After the deploy, check the live site.
- Offer a real-phone check of the notifications (push has never run on a real phone).
