# System status and handoff

Written 12 Oct 2026, updated 30 Oct 2026. It is a snapshot, not a
spec: anything here can be wrong or stale. Treat each claim as something to
check against the code and the live system, and trust the code where they differ.

Companion documents: [memorial-plan.md](memorial-plan.md) (the memorial schedule
and its rules), [reminders-plan.md](reminders-plan.md) (the reminders feature,
its cost model and decisions), and [../DEPLOY.md](../DEPLOY.md) and
[../deploy/README.md](../deploy/README.md) (first-time server setup).

**Nothing in this repository may contain** a real phone number, a Meta or
WhatsApp account/phone/app ID, a token, a government ID, or a street address.
Those live in the server's `.env`, in Meta's console, and with the owner. This
file refers to them by role.

---

## 1. What the product is

A calendar and booking tool for the priests (mobeds, and the panthaky who runs a
fire temple, an *agyari*) of Zoroastrian fire temples in India, with WhatsApp
reminders to the families they serve. The mobed uses a no-build PWA at `/mobed`.
Families (behdins) never log in; they only receive WhatsApp messages.

Users today: the owner and a handful of alpha mobeds. There is no paying customer
and no billing. Everything is free during the pilot; limits stand in for a
paywall (section 8).

The market is small: the seed list has 167 fire temples. The plan is tens of
paying temples at most, so the design values simplicity and low running cost over
scale.

## 2. Architecture

```
 Mobed's phone (PWA, vanilla ES modules + service worker)
        |  HTTPS
 Cloudflare (free plan, proxied DNS, Tunnel) --- caches static paths, see 9.4
        |
 Oracle Cloud VM (always-free, Ubuntu)  --  docker compose:
        |   app          one uvicorn process (FastAPI)  + the evening worker task
        |   db           Postgres 16
        |   cloudflared  the tunnel to Cloudflare (outbound only, no open ports)
        |
 Meta WhatsApp Cloud API  <-->  our webhook (/webhooks/whatsapp) and our sender
```

- **One process, no queue, no cache, no Redis.** The rate limiter is in memory.
  The evening worker is an `asyncio` task started in the app's lifespan. This is
  deliberate at this scale; a second app process would need the worker moved out.
- **Deploy** is `git push origin master`: GitHub Actions runs the tests, then SSHes
  to the VM, which backs up the database, builds, migrates with the new image,
  swaps the container and waits for `/health`. A failed migration leaves the old
  version serving. The app runs the code in its image, as a non-root user; `git pull`
  alone changes nothing that is live. To go back, see [INCIDENT.md](INCIDENT.md).
- **Time** is IST throughout the reminder logic. The server clock is UTC.

### 2.1 Code layout

```
src/agyary/
  api/        main.py (app, middleware, lifespan), rate_limit.py, routes/, static/ (the one PWA)
  core/       config.py (all settings), database.py
  models/     SQLAlchemy models (24 tables)
  calendar/   Parsi calendar engine + memorial schedule - pure functions, no DB
  services/   the rules (see below)
  messaging/  booking core; named for a bot that no longer exists (see its docstring)
tests/        29 files, 513 tests, real Postgres (agyary_test)
alembic/      20 migrations
```

Services: `memorials` (schedule, reminders list), `reminders` (consent, STOP,
in-app notifications, closing notices), `reminder_message` (the words),
`reminder_sender` (planning, sending, receipts), `reminder_worker` (the evening
loop), `guardrails` (caps, pause, alerts), `otp` (sign-in by WhatsApp code),
`wa_login` (sign-in by sending us a code), `mobed_auth` (tokens), `behdin_directory`,
`mobed_dashboard`, `phone`.

### 2.2 Data model (24 tables)

- **People and places:** `users` (mobeds), `agyaries`, `agyary_users` (membership and
  role), `customers` (behdins: one record per mobed per family, `owner_user_id`, the
  number unique within one mobed's book; also holds the reminder consent),
  `reminder_opt_outs` (numbers that replied STOP), `agyary_customers`,
  `customer_saved_names`, `ceremony_names`, `user_preferences`.
- **Bookings:** `bookings`, `booking_mobeds`, `machis`, `services`, `recurrence_rules`,
  `bulk_batches`, `payments` (a ledger of UPI links the app does not touch money for).
- **Memorials:** `memorials`, `memorial_observances`, `memorial_observance_services`.
- **Messaging and notices:** `notifications` (the outbound WhatsApp queue; one row per
  reminder), `app_notifications` (what a mobed sees in the app), `wa_login_attempts`,
  `login_otps`, `app_settings` (the pause flag).

Privacy shape (D2): memorials and behdins are private to the mobed who made them; a
colleague at the same temple cannot read them, and typing a number a colleague has
makes a record of one's own. A STOP is the person's: it stops every mobed's record of
the number and is remembered in `reminder_opt_outs` for records made later; a mobed
lifts it ("they asked me to") for their own record only.

### 2.3 Key flows

**Sign-in, two ways.** (a) *Send us a code* (always on): the app shows a code and
opens WhatsApp with it prefilled; the mobed sends it from their own WhatsApp; Meta's
signed webhook tells us their number; the page polls and signs in. Nothing is sent
to them, it is free, and the number is proven by Meta. (b) *A code on WhatsApp*
(`OTP_MODE`, off): the caller types a number, we send a six digit code as an
Authentication template with a Copy code button, and the app reads it back from the
clipboard. Weaker (a typed number can be someone else's) and it spends money, so it
is heavily limited. A web page cannot read WhatsApp, and WebOTP/iPhone autofill are
SMS-only, so "Copy code" plus Paste is as automatic as it gets.

**Memorials.** From a date of death the engine (`calendar/memorial.py`) computes every
observance (opening days 1-10, 29th/30th, monthly, yearly, Parabs) in the family's
calendar. See `memorial-plan.md` for the rules; they were settled with a mobed and are
the domain heart of the app.

**Reminders.** The evening before a prayer after the opening days, about 19:00 IST, one
WhatsApp template message: which temple, when, what, for whom. Pipeline: the mobed ticks
"has agreed to receive reminders" for a behdin (in-person consent, recorded) -> the loop
plans tomorrow's reminders (`plan_tomorrow`, the only place the rules are applied) ->
`send_pending` posts each to Meta, one at a time, committing as it goes, re-checking
consent -> Meta's receipts update the row -> a reply of exactly STOP switches the
behdin off for every mobed and tells each in the app. Never sent in the first ten days
(the family is at the temple daily and grieving). One reminder per observance, enforced
by a partial unique index.

**In-app notifications.** A bell and a popup on open; anything unseen is shown once and
everything is kept 24 hours. Kinds: `reminder_stopped`, `reminder_failed`,
`reminders_sent`, `memorial_closing` (the evening before a memorial's last prayer),
`alert` (for admins).

**Guardrails** (`services/guardrails.py`): ceilings per day/month overall, per mobed and
per temple; a pause switch that survives restarts; auto-pause on account-level Meta
errors (invalid token, payment, throttling, template missing/paused) and after N failures
in a row; alerts to admins; an allowlist for `live`. Failed or blocked reminders are not
counted. Admin screen shows usage, an estimated cost, recent failures, and the switch.

## 3. What is live and what is off

| Capability | State | Gate |
|---|---|---|
| Mobed PWA: Machi, Calendar and Behdins tabs, bookings, memorials, slips | **Live** | none |
| Sign-in by sending us a code | **Live** | none |
| Manual reminders (a `wa.me` link the mobed taps) | **Live** | none |
| In-app notifications, closing notices, Reminders list/notice | **Live** | none |
| Admin screen, pause switch, spend caps, alerts | **Live** | `ADMIN_PHONES` set |
| Security headers (CSP, HSTS, permissions policy), webhook size cap | **Live** | none |
| Automatic WhatsApp reminders | **Live** (13 Oct 2026, owner decision D4) | `REMINDERS_SEND_MODE=live`, `REMINDERS_ALLOWLIST=*`. Each family still needs its mobed to record consent; each account has its own switch (`users.automatic_reminders`) |
| Sign-in by WhatsApp code | **Live** (owner decision D3, 12 Oct 2026) | `OTP_MODE=live`, template `login_code` approved. The bot check is enforced once `TURNSTILE_*` are set |
| STOP: one kind reply ("You will not receive any more reminders from ...") | **Live** | once per number; its own daily cap (`REMINDERS_STOP_ACK_DAILY_CAP`); respects the pause |
| "I told them myself" mark on a reminder | **Live** | the planner then sends nothing for it |
| Delete my account (in the app) and `/delete-account` | **Live** | none. What was sent stays counted, with who and what wiped; a one-way digest of the number stays for 30 days, so deleting cannot reset a number's limits |
| Erase a family from every mobed's book | **Admin screen** | `ADMIN_PHONES`. Procedure in [DATA-REQUESTS.md](DATA-REQUESTS.md) |
| Deleting old records | **Built, off** | `RETENTION_MODE=on`, once the owner has chosen the periods. It deletes for good |
| Warmer reminder template with a Stop button | **Ready, waiting for Meta** | submit `memorial_reminder_v2`; switch with `WHATSAPP_REMINDER_TEMPLATE` |
| Android app (Trusted Web Activity) | **Built, shared directly** (14 Oct 2026) | signed APK given to mobeds in a WhatsApp group; `/.well-known/assetlinks.json` lists the upload key, so it opens full-screen; not on Google Play (DECISIONS.md D6) |
| Web Push to mobeds | **Not started** | |

## 4. Configuration

All settings are in `core/config.py` and documented in `.env.example`. Defaults are safe:
sending is off. Settings that matter operationally:

| Setting | Default | Meaning |
|---|---|---|
| `REMINDERS_SEND_MODE` | `off` | `off`; `dry_run` (log only, writes nothing); `live` (sends, to the allowlist) |
| `REMINDERS_ALLOWLIST` | empty | numbers messaged in `live`; `*` = everyone; empty = nobody |
| `REMINDERS_SEND_HOUR` / `_CUTOFF_HOUR` | 19 / 21 | the IST evening window; unsent after the cutoff is given up on |
| `REMINDERS_DAILY_CAP` / `_MONTHLY_CAP` | 150 / 2000 | overall ceilings |
| `REMINDERS_PER_MOBED_DAILY_CAP` / `_PER_AGYARY_` | 40 / 100 | per mobed / per temple |
| `REMINDERS_BREAKER_FAILURES` | 5 | failures in a row that pause sending |
| `REMINDERS_STOP_ACK_DAILY_CAP` | 20 | kind replies to a first STOP, per day |
| `MEMORIAL_SHARE_SEND_MODE` | `off` | a schedule PDF from our number. Needs the family's agreement and the allowlist |
| `MEMORIAL_SHARE_DAILY_CAP` / `_GLOBAL_DAILY_CAP` | 20 / 100 | per mobed (a new account: lower) / everyone, per IST day. One schedule per number per day, whoever sends it |
| `DELETED_ACCOUNT_COOLDOWN_DAYS` | 30 | how long a number that deleted its account cannot send schedules from our number |
| `RETENTION_MODE` | `off` | `on` deletes old message records and erases quiet hidden behdins |
| `RETENTION_SEND_LOG_MONTHS` / `_HIDDEN_BEHDIN_MONTHS` | 13 / 24 | the periods, which must match the privacy policy |
| `ANDROID_PACKAGE_NAME` / `ANDROID_CERT_FINGERPRINTS` | the app / the upload key | what `/.well-known/assetlinks.json` lists; add Play's signing key after the first upload |
| `ADMIN_PHONES` | empty | admin screen, pause switch, alerts |
| `OTP_MODE` / `OTP_*` | `off` | sign-in by WhatsApp code and its limits |
| `WHATSAPP_ACCESS_TOKEN`, `_PHONE_NUMBER_ID` | empty | needed to send anything; server `.env` only |
| `APP_DEBUG` | false | `true` only on a laptop: it enables a sign-in bypass and `/docs`. Refused at startup when `APP_ENV=production` |
| `SIGNUP_MODE` / `SIGNUP_ALLOWLIST` | `invite` / empty | `invite`: new accounts only for invited numbers and admins; `open`: any verified number. Production runs `open` (owner decision D1) |

## 5. External dependencies and their state

- **Meta WhatsApp Business account.** A number is connected and webhooks are subscribed to
  `messages` (STOP replies and delivery receipts arrive on it). Billing is prepaid (no auto
  top-up, on purpose: the balance is the outermost spending limit). A System User token with
  messaging and management permissions is in the server `.env` and verified.
- **Templates.** `memorial_reminder` (Utility) was submitted 12 Oct 2026 and was still
  **pending** at the last check (many hours, no rejection reason). `login_code`
  (Authentication, Copy code, 5-minute expiry) was **refused at first**: the web form and the
  Graph API both answered error 10 / subcode 2388185, "does not have permission to create message
  template", flagged non-transient, before and for a while after business verification. A retry
  through the API at 16:44 UTC on 12 Oct 2026 (about ten hours after verification was submitted)
  **succeeded and the template was APPROVED immediately**. So the block cleared on its own, most
  likely a propagation delay after verification. The owner then switched sign-in by code on
  (`OTP_MODE=live`, DECISIONS.md D3), against the review's advice; its conditions are follow-up work.
- **Business verification.** Submitted 12 Oct 2026 using a Udyam registration (sole
  proprietorship); Meta matched the business to the public record by registration number and
  address. Meta estimated two business days; the API reported `verified` within about six hours.
  It raises sending limits and is a prerequisite for several features, but it did NOT by itself
  unlock the Authentication template.
- **Why the reminder template is so plain.** Meta's own pre-submission check classed any
  invitation ("We would be glad to have you there", "Please join us") as Marketing and said
  it would be rejected as Utility, and refused a shorter version for too many variables for
  its length. See `reminders-plan.md`.
- **Cloudflare** (free plan): full proxy, a Tunnel to the VM. The free plan rewrites
  `Cache-Control: no-cache` to a four hour cache unless its Browser Cache TTL is set to respect
  existing headers.
- **Oracle Cloud always-free VM**, **GitHub Actions** (test + deploy), **a Udyam registration**
  (a micro-enterprise; no GST).

A background watcher in the session that wrote this polled Meta every five minutes (and retried
creating `login_code` every 30 minutes); it will not survive that session. Check the statuses by
hand: `GET /{waba-id}/message_templates?fields=name,status,category,rejected_reason` with the
server's token, run on the server so the token never leaves it.

## 6. Runbooks

For anything going wrong (a leak, a bad deploy, a lost server, sending paused), see
[INCIDENT.md](INCIDENT.md). For a family's request about their data, see
[DATA-REQUESTS.md](DATA-REQUESTS.md).

**Deploy.** Merge to `master`. Watch the Actions run (`gh run watch`). Then verify like a
browser would: fetch changed static files WITHOUT a cache-buster, assert 200 first, compare
bytes against the local tree, read `cf-cache-status`/`Age`.

**Stop all outbound WhatsApp now.** Admin screen -> Pause all sending (takes effect within a
minute, survives restart). Or set `REMINDERS_SEND_MODE=off` and `OTP_MODE=off` in the server
`.env` and `docker compose up -d app`.

**Go live with reminders (in order; each step is reversible).**
1. Template approved (check Meta, or `GET /{waba}/message_templates?name=memorial_reminder`).
2. Server `.env`: `REMINDERS_SEND_MODE=dry_run`, allowlist empty; redeploy; read the log at 19:00 IST.
3. `REMINDERS_SEND_MODE=live`, allowlist = the owner's own test numbers only. Create a test
   memorial for a consenting test behdin whose 30th day is tomorrow, tick the consent box, and
   watch one real send end to end (planned -> sent -> delivered -> shows on the Reminders list).
4. Only after a clean evening: widen the allowlist, then `*`. Tell each mobed how consent works.

Done 13 Oct 2026. In step 3, one reminder went to the owner's own number: planned 1, sent 1,
failed 0; Meta reported sent, delivered, read. The owner replied STOP, and it was honoured: the
number was recorded, every record of it was switched off, the mobed was told in the app, and
nothing was sent back. The owner then went straight to `*` (D4). To run the test again, add a
test memorial for a consenting test behdin, and remove any STOP left on that number.

**Go live with sign-in by WhatsApp code.** Needs business verification, then create the
Authentication template `login_code` (Copy code, 5-minute expiry and validity), wait for approval,
set `OTP_MODE=live`. Test on a laptop first with `APP_DEBUG=true` and no token (the code is
returned in the response).

**Rotate the WhatsApp token.** Create a new System User token in Meta, replace the line in the
server `.env` (never paste it into chat or git), `docker compose up -d app`, confirm a Graph call
succeeds, revoke the old one. A clipboard trick that pipes `Get-Clipboard` over SSH failed once when
the clipboard held the command text instead of the token: check the length and the `EAA` prefix.

**Restore the database.** The deploy script keeps the last ten pre-deploy dumps in the VM user's
home directory (`pg_dump -Fc`), readable by that user only. Nightly encrypted copies go to R2 and
are kept for 30 days; `deploy/README.md` has the restore drill.

## 7. Decisions worth challenging

- **Consent is the mobed's attestation** (a tick-box, recorded with time), not a handshake by the
  family. Meta accepts documented in-person opt-in. It puts the responsibility on the mobed.
- **Plain template wording over warm wording** because Meta classified invitations as Marketing
  (7.5x the price and not approvable as Utility). Warmth is left to the mobed.
- **Opening days (1-10) are never reminded.** The family is in mourning and at the temple daily.
- **The "send us a code" sign-in is the primary one** and OTP is the optional second. The earlier
  design removed an outbound OTP on purpose (the number is proven rather than claimed; nothing to
  enumerate). OTP was added again at the owner's request.
- **No plan gating for now**; limits instead.
- **Reminders go from one shared number**, so the agyari's name is in the text and the number's
  quality rating is shared by every temple. A runaway temple could hurt all of them (hence the
  per-temple cap).
- **Free during the pilot**; pricing (about Rs 299/month per temple, guessed) is unvalidated.

## 8. Cost model

Utility template about Rs 0.115 + 18% GST per delivered message (third-party figures, verify on
Meta's rate card); Marketing about 7.5x. At the shipped caps the worst month is a few hundred
rupees (a test enforces it). Prepaid balance with no auto top-up is the hard ceiling. Hosting is
free (Oracle always-free, Cloudflare free).

## 9. Operating notes

1. **One app process.** The evening worker and the general rate limiter live in it; sign-in
   codes are limited in the database.
2. **Graph API version** defaults to `v23.0` (`WHATSAPP_GRAPH_VERSION`); Meta retires versions, so
   move forward before it expires.
3. **Templates are fixed once approved.** Changing the words means a new template and a setting
   change (`WHATSAPP_REMINDER_TEMPLATE`), never a deploy.
4. **Tests share one database** (`agyary_test`) and truncate it; run one pytest at a time. The suite
   builds its schema from the models, so `tests/test_migrations_run.py` is what proves the migrations.
5. **English only** for now; a Gujarati template is a product decision.
6. **The calendar rules** were settled with a mobed (DECISIONS.md D5); a second authority's review
   is welcome.

## 10. What is left (prioritised)

**A. Meta.** Submit `memorial_reminder_v2` (warm closing line, Stop button) as Utility; switch to it
by setting once approved.

**B. Android.** The signed APK is shared with mobeds directly (the project and upload key live
outside the repo). Google Play is deferred: if it is revisited, run the closed test (12 testers,
14 days), apply for production, and add Play's signing-key fingerprint to
`ANDROID_CERT_FINGERPRINTS`. Listing material is kept, git-ignored.

**C. Operations.** Scheduled off-site backups with a restore drill; the outside heartbeat and uptime
checks (`HEARTBEAT_URL`, `/health?deep=1`).

**D. Product backlog.** Web Push to mobeds; Gujarati; plans and billing when there is something to
charge for; an AI scheduling assistant (deferred, see `reminders-plan.md` ON HOLD).

## 11. Working notes for contributors

- **Tests:** `uv run pytest`. One run at a time (shared database). The full suite takes about 9 minutes.
- **Commits:** author is the owner, no `Co-Authored-By` trailers (see the owner's preference).
- **Line endings:** the repo is LF (`.gitattributes`); a Windows working tree may show CRLF warnings.
- **Escapes:** when writing code that contains `\n` through a heredoc on this Windows setup, the escape
  can be turned into a real newline. Use the editor's file tools and run `ruff` + the tests after.
- **Browser checks:** use a scratch database and a second port, never the owner's dev server on :8000;
  the pane blocks the service worker (a console "fetching the script" error is expected).
- **Secrets:** tokens only in the server `.env` (mode 600). Never in chat, git or logs.
- **Public repo:** the owner's real number and the Cloudflare zone ID were scrubbed from history; keep
  them out. A local `.git-scrub-rules.txt` (ignored) records the substitutions.

## 12. How we got here (for orientation)

Built across one long session, in this order: a due-list of reminders; the manual `wa.me` send;
consent + STOP + in-app notifications; the automatic sender and evening loop; the Meta setup
(payment, token, templates, webhook, business verification via Udyam); spend guardrails and the admin
screen; sign-in by WhatsApp code; security headers; this documentation. Notable corrections along the
way: reminders must never be sent in the opening days and must not ask the family to book anything
(the mobed already did); the template had to be made plain to be Utility; the first token paste
captured the command text and had to be repaired; two overlapping test runs deadlocked on the shared
database.
