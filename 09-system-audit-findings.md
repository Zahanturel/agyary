# Agyary system audit — findings

Adversarial pre-launch audit. Method: one flowchart per major flow (in
`audit-flowcharts/*.drawio`), tracing the **actual code**, then trying to
break each path on paper and — where a break was concrete — reproducing it
against the running test database. The code is treated as reality; where it
has drifted from docs 05/06/07, that drift is itself a finding.

Every finding below is anchored to the diagram + node it lives at. Findings
marked **VERIFIED** were reproduced by running code, not just read.

---

## Severity summary

| # | Sev | Flow | One line |
|---|-----|------|----------|
| **G1** | High | 7 Manual add | **VERIFIED** naive datetime → wrong IST time on every manual booking + a 500 crash on the 2nd overlapping one |
| **A1** | High | 1 Agyari creation | No way to create an agyari; the "search-empty" fallback doc 06 promised was never built |
| **F1** | High | 5 Services | Zero-priest agyari: request is created, behdin told "sent", but nobody is notified and it can never be accepted |
| **C1** | High | 2 Onboarding | **VERIFIED** empty `JWT_SECRET_KEY`, no default/guard → 500 on first PWA login; 5 mobed tests fail under the documented `uv run pytest` |
| **C2** | Med | 2 Onboarding | Seeded demo agyari has no WhatsApp number → onboarding 400s; the documented dev/demo PWA path can't be walked |
| **D1** | Med | 2 / 7 | "Join another agyari" is a doc-05 standing action; API exists, PWA has no UI for it |
| **G2** | Med | 7 Manual add | Add-form hardcodes name status=living / purpose=khushali_nu; a manual Patet machi records its departed pair as living |
| **B1** | Med | 4 Machi | `/chat` simulator can't render WhatsApp Flows; the Geh step is unpickable there, contradicting the README |
| **B2** | Med | 5 Services | Same simulator gap for service/priest pickers; priest step accepts only `priest_<id>`, no name |
| **E1** | Low | 3 Behdin entry | QR/referral entry from doc 05 isn't modeled; agyari is resolved purely by WhatsApp number (probably fine — needs confirming) |
| **H1** | Low | cross-cut | Money columns/helpers still present despite doc-05 "no money anywhere"; dormant but one render path would show `₹` |
| **H2** | Low | cross-cut | `max_machis_per_geh` / `require_mobed_acceptance` columns are vestigial vs the hardcoded one-per-geh, no-gate design |
| **T1** | — | testing | Two false-confidence test issues: the mobed suite doesn't run green as configured (C1), and the conflict test masks G1 by reusing one DB session |

Four of these need a decision only you can make (A1, F1, G2 scope, E1) — collected at the bottom. The rest are fixable defects.

---

## Flow 1 — Agyari creation  → `audit-flowcharts/01-agyari-creation.drawio`

### A1 (High) — the agyari-creation flow does not exist
The flowchart's decision node "Does any agyari match?" has a **No branch that
dead-ends**. `search_agyaries` (`mobed_dashboard.py`) only returns
already-registered agyaries; `POST /auth/request-otp` requires an existing
`agyary_id`. There is **no endpoint and no UI anywhere that creates an
`Agyary`** — the only creator is `scripts/seed_demo.py`.

Doc 06 explicitly lists "agyari creation fallback if search comes up empty" as
part of onboarding. It was never built. This is the exact archetype you flagged
("a name-onboarding step that assumed an agyari already exists with no way to
create one"). A mobed whose agyari isn't pre-seeded cannot onboard at all.

**Needs a decision** (see bottom): is agyari provisioning meant to be
self-service, or a deliberate out-of-band admin step? The docs imply the
former; the code does neither.

---

## Flow 2 — Mobed onboarding  → `audit-flowcharts/02-mobed-onboarding.drawio`

### C1 (High, VERIFIED) — empty JWT secret breaks login and the test suite
`Settings.jwt_secret_key` defaults to `""`; `.env` and `.env.example` both ship
it empty with only a "generate a real value" comment and **no dev default and
no startup guard**. At the "Issue access + refresh JWT" node,
`jwt.encode(..., "")` raises `InvalidKeyError: HMAC key must not be empty`.

- Reproduced: `uv run pytest` → **5 failures**, all in `test_mobed_api.py`,
  all this error. Setting `JWT_SECRET_KEY` → all 10 pass.
- Consequence in prod: a deploy that follows the README (`cp .env.example .env`,
  fill in) but misses this one value 500s on the **first** OTP verification —
  the first thing any mobed does.

Fix: fail fast at startup if empty outside debug, or ship a dev default. Either
is a small change I can make on request.

### C2 (Med) — the seeded demo agyari can't be onboarded to
`request_otp` requires `agyary.wa_phone_number_id`; if absent it 400s ("This
agyari hasn't connected WhatsApp yet") — the diagram's "Agyari has WhatsApp
connected?" No branch. `seed_demo.py` never sets `wa_phone_number_id`. So with a
freshly seeded DB the demo agyari can't complete onboarding. Together with C1
and the empty `WHATSAPP_FLOW_ID_*`, the documented dev/demo path for the PWA
cannot be walked by hand — which is how the earlier real bugs were caught.

### D1 (Med) — "join another agyari" has no PWA entry point
Doc 05: "Joining additional agyaries is a standing action from their own menu."
The API route `POST /agyaries/{id}/join` exists and works, but `mobed.html`
never calls it — `renderShellChrome` only offers a switcher over
**already-joined** agyaries. A mobed who works at two agyaries can only ever be
in the one they onboarded with, so the merged "My Day" and the Board switcher
are effectively single-tenant in practice. Incomplete, not wrong.

*(Minor: `.env` defines `DATABASE_URL` twice — an early `@db:5432` line and a
later `@localhost` override. The last wins, so it works, but the leftover
Docker-hostname line is the same class of trap already hit once.)*

---

## Flow 3 — Behdin entry  → `audit-flowcharts/03-behdin-entry.drawio`

### E1 (Low / question) — QR/referral entry isn't modeled
Doc 05 describes entry "via a QR code at the agyari or a referral link." In code
the agyari is resolved **only** by which WhatsApp number was messaged
(`phone_number_id` → `Agyary`). There's no QR generation, referral token, or
attribution. This is very likely fine (a QR that just encodes a `wa.me/<number>`
link needs no server support) — but it's an assumption, not something the code
demonstrates, so I'm flagging rather than silently passing it. The rest of this
flow (signature check, inbound dedup, first-time name capture) is sound.

---

## Flow 4 — Machi booking  → `audit-flowcharts/04-machi-booking.drawio`

The core is solid: one shared `book_machi_slot` owns validate/free/claim/
alternatives; the elapsed-geh past-check is reused; the race is handled by the
partial unique index + SAVEPOINT; the alternatives path fires from the final
confirm too (doc 06's specific ask). No correctness gap in the booking logic.

### B1 (Med) — the Geh step is unusable in the `/chat` simulator
At "Send Geh picker (WhatsApp Flow)" the message carries a `flow` and **no**
buttons/sections. But `chat.html`'s `addChips` renders only `buttons` and
`sections` — never `flow`. So in the simulator the behdin sees "Which Geh?" with
no tappable option and must *know* to type "Havan". The README still says `/chat`
"drives the full booking flow: … machi …". That's drift, and it blunts exactly
the by-hand testing that found the previous bugs. (`matched_option` does accept
typed geh names, so it's degraded, not dead.)

---

## Flow 5 — Services booking  → `audit-flowcharts/05-services-booking.drawio`

### F1 (High) — a zero-priest agyari silently swallows the request
Trace the "How many active priests? → 0" branch into "Priest chosen? → No":
`create_booking_request` makes the booking at `status=requested`, **no
`BookingMobed` row is created, and no notification is sent to anyone** (services
dropped the admin-notify path in the redesign — only the chosen priest is ever
told). The behdin gets "Your request has been sent." It can never be accepted:
`apply_booking_action`/`handle_pwa_booking_action` both require a `BookingMobed`
row. The request is orphaned behind a false confirmation.

The code comment calls this "out of scope for this redesign," but it's a live
false-positive to a real user. Machi's equivalent (no free slot) at least routes
to "contact the agyari"; services just say "sent." **Needs a decision** on the
intended behavior (block / queue / contact-fallback).

### B2 (Med) — service & priest pickers share B1's simulator gap, plus a name gap
Both are dynamic WhatsApp Flows (same unrenderable-in-`/chat` problem), and they
additionally need Flow registration + `WHATSAPP_FLOW_ID_*` + the encryption keys
(all empty in the repo). Worse for testing: `_step_select_priest` accepts **only**
`priest_<id>` — no name synonyms — so a multi-priest service booking can't be
completed by hand in the simulator without knowing internal user ids. The
single-priest and zero-priest short-circuits skip the Flow, so only the
multi-priest agyari is affected.

*(The immediate two-way contact exchange, the non-blocking conflict note, and the
idempotent accept/decline all match doc 05 and are covered by
`test_services_priest_flow.py`.)*

---

## Flow 6 — Accept / decline  → `audit-flowcharts/06-accept-decline.drawio`

**No gap found.** One idempotent core (`apply_booking_action`) shared by the
WhatsApp button and the PWA, each doing its own authorization first; the
"already resolved?" guard is present; the retired machi branch is kept only for
pre-cutover rows. Matches doc 05/06 and is exercised by
`test_pwa_accept_shares_idempotent_core_with_whatsapp`. Recorded as a strength on
the diagram so the audit is honest about what's actually right.

---

## Flow 7 — Mobed dashboard / manual add  → `audit-flowcharts/07-mobed-dashboard.drawio`

### G1 (High, VERIFIED) — manual booking uses a naive datetime: wrong time + a crash
The PWA add-form posts `"<date>T<time>:00"` with no timezone;
`ManualAddBookingIn.ceremony_datetime` accepts it naive, and nothing anchors it
to IST. Two concrete consequences, both reproduced against the test DB:

1. **Wrong time on every manual service booking.** A 10:00 walk-in was stored as
   `02:00+00:00` and read back / displayed as **07:30 IST** on this machine
   (server tz UTC+8); on a UTC server the same entry would read **15:30 IST**.
   The stored time depends on the *server's* timezone, because the naive value is
   converted by the OS clock, not by IST. It flows straight onto My Day and the
   printed slip. The WhatsApp services flow doesn't have this bug — it builds an
   explicit `tzinfo=IST` datetime.
2. **A 500 on the second overlapping booking.** `has_calendar_conflict` compares
   the naive incoming datetime against the tz-aware stored one:
   `TypeError: can't compare offset-naive and offset-aware datetimes`. The first
   booking passes only because the conflict loop is empty. Reproduced with a
   fresh session (the shape of a real second HTTP request).

   > The existing test `test_manual_add_booking_and_my_day_and_machi_board`
   > **passes** because it reuses one `expire_on_commit=False` session, so the
   > first booking's datetime stays naive in the identity map and never round-trips
   > through Postgres. Green test, latent crash. (See T1.)

Fix: coerce the incoming datetime to IST at the boundary (mirror the WhatsApp
flow's `tzinfo=IST`). Small change; I can make it and add a fresh-session
regression test on request.

### G2 (Med) — manual-add form drops purpose and name fidelity
The add-form hardcodes every name as `section:"pair", status:"living"` and every
service booking's `purpose:"khushali_nu"`. So:
- A manually-added **Patet** machi records its *departed* pair as `living`.
- Farmayeshne names and the real occasion are never captured for services.
- Doc 07 says closed-vocabulary fields (purpose is one) must be *selectable* on
  the PWA — here purpose isn't offered at all, it's silently fixed.

**Needs a decision** on how faithful a walk-in record must be for v1 (this may be
an acceptable simplification — but right now it's mislabeling data, not omitting
it).

*Machi manual-add is otherwise correct* — it routes through the same
`book_machi_slot` and builds IST-aware times from date+geh, so G1 does not affect
it.

---

## Flow 8 — Notifications + Flows plumbing  → `audit-flowcharts/08-notifications-flows.drawio`

**Strength.** The outbox send worker is genuinely durable: startup sweep +
periodic sweep + immediate enqueue all converge on a `SELECT … FOR UPDATE SKIP
LOCKED` claim, correct under unattended restarts and concurrency; the webhook
verifies signatures and dedups inbound by `wa_message_id`; retries back off and
cap at 3. No defect found here.

**Verification note (inherent, acknowledged in code).** The entire WhatsApp
Flows path — Flow-JSON validity, the encryption round-trip against real Meta,
`INIT` vs data-exchange action handling — cannot be exercised without a Meta
Business Account. Unit tests cover the crypto round-trip and an IV-flip
known-answer vector, but nothing end-to-end, and every `WHATSAPP_FLOW_ID_*` /
key is empty in the repo. This isn't a defect, but it means **every Flow-based
step (Roj/Mah/Geh, service picker, priest picker) is assumed-good, not
verified** — worth stating plainly given how much of the behdin experience now
routes through Flows.

---

## Flow 9 — Slip + print  → `audit-flowcharts/09-slip-print.drawio`

Matches doc 05: exactly five fields, no money, membership-scoped. One inherited
defect — the "when" line for a manually-added service booking prints G1's
corrupted time. Fix G1 and this clears.

---

## Cross-cutting drift

### H1 (Low) — money still lives in the code
Despite doc 05's "no amount/price/payment anywhere," the schema keeps `amount`,
`payment_status`, `payment_method`, `upi_id`, and the helpers `generate_upi_link`,
`create_pending_payment`, `machi_price`, `rupees` are still imported/live.
Currently harmless (every flow passes `amount=None`), but `my_bookings.py` would
render `Amount: ₹X (pending)` the moment any `amount` is non-null — a latent path
that contradicts the design. Recommend either deleting the dormant helpers or a
comment/test pinning `amount` to `None` end-to-end.

### H2 (Low) — vestigial config columns
`Agyary.max_machis_per_geh` and `require_mobed_acceptance` are dead against the
current design (slot uniqueness is hardcoded to one-per-geh via the partial
unique index; machi has no acceptance gate). Not harmful, but they imply
behavior that no longer exists — the kind of drift that misleads the next reader.

### T1 — test-confidence issues (matches "assumed, not verified")
- The mobed test suite (`test_mobed_api.py`) doesn't pass as the repo is
  configured (C1), so the whole PWA surface is effectively unverified in a plain
  `uv run pytest` run — the exact command the README gives.
- `test_manual_add_booking_and_my_day_and_machi_board` masks G1's crash by
  reusing one session. A regression test must use a fresh session (or assert the
  stored time equals the intended IST time) to actually cover it.

---

## What I need from you (decisions, not defects)

1. **Agyari creation (A1).** Should a mobed be able to create an agyari
   self-service during onboarding (and if so, with what fields and what trust —
   OTP only, like joining?), or is agyari provisioning deliberately an
   out-of-band step you'll do yourself? The docs imply self-service; nothing is
   built.
2. **Zero-priest services (F1).** When an agyari has no priest yet, should a
   service request be **blocked** ("no one is available to take this yet"),
   **queued** for whoever joins first, or fall back to machi's "contact the
   agyari directly" message? Today it false-confirms and orphans the request.
3. **Manual-add fidelity (G2).** For a walk-in the mobed logs after the fact, is
   a stripped record (living pair, khushali_nu) acceptable for v1, or should the
   add-form capture purpose + living/departed + farmayeshne like the WhatsApp
   flow? Right now it *mislabels* rather than simplifies.
4. **QR/referral (E1).** Is resolving the agyari purely by inbound WhatsApp
   number the intended model (QR just encodes a `wa.me` link), or was a
   referral/landing/attribution mechanism expected that isn't here?

I can fix the clear defects (C1, C2, D1, B1, B2, G1, G2's mislabeling, H1/H2,
T1) without a decision — say the word and I'll start with G1 and C1, the two
that break real usage.
