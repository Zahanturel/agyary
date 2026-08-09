# Mobed Diary — app audit

State of the code as it actually is on `master` @ `f18ad1c`. Not what the
scope says; what the files do.

---

## 1. Route map

| Hash route | Screen | File |
|---|---|---|
| `#/login` | Sign in (phone + OTP) | `js/screens/login.js` |
| `#/onboarding` | Fire-temple search / join / create | `js/screens/onboarding.js` |
| `#/calendar` | **Home.** Day / Week / Month | `js/screens/calendar.js` |
| `#/menu` | You / Calendar / Behdins | `js/screens/menu.js` |
| `#/event/new` | 6-step new-event wizard | `js/screens/event.js` |
| `#/event/:kind/:id/edit` | Same wizard, prefilled | `js/screens/event.js` |
| `#/behdins` | Behdin list | `js/screens/behdins.js` |
| `#/behdins/:id` | Behdin detail | `js/screens/behdins.js` |
| `#/machi/:aid/:id` | Printable slip | `js/screens/slip.js` |
| `#/booking/:aid/:id` | Printable slip | `js/screens/slip.js` |

**No route:** `js/screens/invites.js` — file exists, unreachable.
**Anything unrecognised** → redirected to `#/calendar`.

---

## 2. Cold start

```mermaid
flowchart TD
    A[App opens] --> B["POST /auth/refresh<br/>(httpOnly cookie)"]
    B -->|valid| C[GET /auth/me]
    B -->|no cookie / expired| L["#/login"]
    C --> D[Load preferences + calendar options]
    D --> E{Member of a fire temple?}
    E -->|yes| F["#/calendar"]
    E -->|no| G["#/onboarding"]
```

The refresh cookie is **sliding, 180 days** — re-issued on every refresh
(`routes/mobed.py:177`). A mobed who opens the app even twice a year never
sees the login screen again.

---

## 3. Sign-in (current — this is what we're replacing)

```mermaid
flowchart TD
    A[Enter phone] --> B["POST /auth/otp/request"]
    B --> C{Rate limits<br/>10/IP, 3/phone per 5min}
    C -->|pass| D[Generate 6-digit code<br/>SHA-256 salted with phone]
    D --> E{WhatsApp configured?}
    E -->|no + debug| F[Code written to server log]
    E -->|no + prod| X[503 error]
    E -->|yes| G[Send as WhatsApp template]
    F --> H[Enter code + name]
    G --> H
    H --> I["POST /auth/otp/verify"]
    I -->|wrong| J[Burn attempt, 3 max<br/>then code destroyed]
    I -->|correct| K[Code deleted, user created/found]
    K --> M[Redeem any pending invites]
    M --> N[Access token + refresh cookie]
```

**Blocked:** the WhatsApp template send is written but has never worked —
a test WABA cannot create templates, and authentication messages are
billable. See scope §8.1/8.1a/8.1b.

---

## 4. Onboarding

```mermaid
flowchart TD
    A[Type a name or city] --> B["GET /agyaries/search"]
    B --> C{Found it?}
    C -->|yes, active| D["POST /agyaries/{id}/join"] --> H["#/my-day"]
    C -->|yes, unclaimed| E["POST join"] --> F[Confirm/correct details]
    F --> G["POST /agyaries/{id}/activate"] --> H
    C -->|no| I[Fill in new temple] --> J["POST /agyaries"] --> H
    H -.no such route.-> K["#/calendar"]
```

Any signed-in user can **create** a fire temple and **edit** an unclaimed
one. See finding #3.

---

## 5. Calendar (home)

```mermaid
flowchart TD
    A["#/calendar"] --> B[Day / Week / Month toggle]
    B --> C["GET /my-day<br/>(services, all temples)"]
    B --> D["GET /machi-board?mine=true<br/>(machis, current temple)"]
    C --> E[Merge + filter to visible range]
    D --> E
    E --> F[Render each date:<br/>Gregorian + primary Parsi reading]
    F --> G{Tap}
    G -->|an event| H["#/machi/... or #/booking/..."]
    G -->|a day in Month view| I[Switch to Day view]
    G -->|the + button| J["#/event/new"]
```

`mine=true` is hardcoded client-side (`api.js:100`) — the mobed app never
pulls the temple-wide board.

---

## 6. New event — the 6-step wizard

```mermaid
flowchart TD
    S1["1. Behdin"] --> S2["2. Service or Machi"]
    S2 --> S3["3. Date"]
    S3 --> S4["4. Time or Geh"]
    S4 --> S5["5. Names"]
    S5 --> S6["6. Confirm"]

    S1 -.-> B1["GET /behdins?q=<br/>search your own"]
    S1 -.-> B2["POST /behdins<br/>add new inline"]
    S1 -.-> B3["GET saved-names<br/>prefills step 5"]

    S2 -.-> C1["GET /services<br/>+ inline create"]

    S3 -.-> D1["GET convert-date<br/>Gregorian → Roj/Mah"]
    S3 -.-> D2["GET from-parsi<br/>Roj/Mah → Gregorian"]

    S6 -.-> E1["POST manual-add/machi"]
    S6 -.-> E2["POST manual-add/booking"]
```

**Date step:** Gregorian and Roj/Mah are two views of one value. Either is
editable; **neither is ever computed in the browser** — every change round-trips
to the server. Roj/Mah is read and written in the **mobed's primary calendar**
(`event.js:46`).

**Machi clash:**

```mermaid
flowchart TD
    A[Save machi] --> B{Geh free that day?}
    B -->|yes| C[Booked → slip]
    B -->|no| D["confirmed: false<br/>+ concrete alternatives"]
    D --> E[Other free Gehs same day]
    D --> F[Same Geh, next free days]
    E --> G[Tap one → applied to draft]
    F --> G
```

Machi is blocked on Gatha days and is never offsite.

---

## 7. Behdins

```mermaid
flowchart TD
    A["#/behdins"] --> B["GET /behdins?q=<br/>scoped to YOU server-side"]
    B --> C[Rows: name + phone]
    C --> D["#/behdins/:id"]
    D --> E[Edit name / phone]
    D --> F["tel: link"]
    D --> G[Saved name pairs + farmayeshne]
    D --> H["GET /customers/:id/history<br/>only what YOU booked"]
```

Scoping is enforced in `services/behdin_directory.py` (`search_mine`,
`get_scoped`) — not in the client. A behdin who isn't yours returns **404,
not 403**, so you can't probe whether a person exists.

Two add entry points, one component (`behdin_add.js`): the `+` on this
screen, and the `+` on the menu's Behdins bar.

---

## 8. Menu

```mermaid
flowchart TD
    A["#/menu"] --> B["You: name (editable), phone,<br/>temple name + address (read-only)"]
    A --> C["Calendar: primary system<br/>+ which others stay available"]
    A --> D["Behdins bar → #/behdins<br/>+ shortcut to add"]
    A --> E["Sign out → POST /auth/logout"]
    C -->|save| F["PUT /me/preferences"]
    F --> G[Clear parsi caches<br/>every date re-derives]
```

---

## 9. API surface

**Used by the app:**

`/auth/otp/request` · `/auth/otp/verify` · `/auth/refresh` · `/auth/logout` ·
`/auth/me` (GET, PATCH) · `/me/preferences` (GET, PUT) ·
`/agyaries/search` · `/agyaries` · `/agyaries/{id}/join` · `/agyaries/{id}/activate` ·
`/my-day` · `/agyaries/{id}/machi-board` · `/agyaries/{id}/services` (GET, POST) ·
`/agyaries/{id}/behdins` (GET, POST, GET id, PATCH) · `/agyaries/{id}/behdins/{cid}/saved-names` ·
`/customers/{id}/history` · `/agyaries/{id}/manual-add/machi` · `/agyaries/{id}/manual-add/booking` ·
`/agyaries/{id}/machis/{id}` (detail, slip, PUT) · `/agyaries/{id}/bookings/{id}` (detail, slip, PUT) ·
`/reference/calendar-options` · convert-date / from-parsi

**Live but nothing calls them:**

| Endpoint | Note |
|---|---|
| `POST/GET/DELETE /agyaries/{id}/invites` | Finding #2 |
| `GET /pending-requests` | WhatsApp booking-request flow, off |
| `POST /bookings/{id}/accept` / `decline` | same |
| `GET /agyaries/{id}/bookable-gehs` | was the Geh slot board, removed |
| `GET /customers/search` | superseded by `/behdins` |
| `GET /agyaries/{id}/form-options` | superseded by `/services` |
| `PATCH /agyaries/{id}/services/{id}` | catalog editing, no UI |
| `/webhooks/whatsapp` | mounted; behdin bot routing behind it |

---

## 10. Findings — where changes are needed

| # | What | Where | Severity |
|---|---|---|---|
| 1 | **Sign-in doesn't work in production.** WhatsApp OTP needs a template a test WABA can't create, plus billing. Decision pending: inbound-WhatsApp sign-in. | `services/otp_delivery.py`, `routes/mobed.py:99` | **Blocker** |
| 2 | **Invite API is live with no UI.** Any signed-in mobed at a temple with no admin can issue `panthaky`/`caretaker` roles by curl. Scope §5 says invites are unreachable — that's true of the screen, not the endpoints. | `routes/mobed.py:473-553` | **High** |
| 3 | **Onboarding writes to the temple table.** Any user can `POST /agyaries` (create) or `activate` an unclaimed one — no verification that they work there. Scope §5 says fire-temple editing is unreachable; it isn't. | `routes/mobed.py:385,414` | **High** |
| 4 | **Phone numbers stored in plaintext** — mobeds' and behdins'. Needs encryption at rest + HMAC blind index, because behdins are looked up by phone. | `models/user.py:27`, customers table | **High** |
| 5 | `#/my-day` **is navigated to but has no route.** Four call sites bounce through not-found → `#/calendar`. Works by accident. | `session.js:45`, `onboarding.js:76,109,148`, `event.js:174` | Medium |
| 6 | **Scope §8.3 is stale.** It says the event form reads the temple's calendar system; it was fixed and now reads the mobed's primary. §4.1 row 7 already says so. The two contradict. | `11-mobed-app-scope.md:258` | Medium |
| 7 | **Scope §5 says the service catalog is unreachable, but the wizard creates services.** Step 2 has "+ Add a new service" wired to `POST /services`. Either the doc or the wizard is wrong. | `event.js:309`, scope §5 | Medium |
| 8 | **Machi purpose renders as a raw key** — "Machi (patet)" instead of "Machi (Patet — for the departed)". `MACHI_PURPOSE_DISPLAY` exists and is used everywhere else. | `calendar.js:44` | Low |
| 9 | **Calendar mixes scopes.** `/my-day` returns services across every temple; `machi-board` only the current one. Harmless while one mobed = one temple, wrong the moment that isn't true. | `calendar.js:49` | Low |
| 10 | **Dead references.** `invites.js` links back to `#/settings`, which doesn't exist. | `invites.js:57` | Low |

---

## 11. Not built at all

- Global daily send cap on OTP (scope §8.1b) — moot if OTP goes.
- The behdin-facing WhatsApp bot. Code is in `messaging/`; webhook is mounted
  but the app never surfaces any of it.
- Any agyari management surface. Deliberate — waiting on real panthakies.
