# Brief for an independent critical review

Paste everything below the line into a fresh session (use the strongest model
available, with extended thinking, in the repository root). It is written to be
read cold. Keep this file updated if the brief changes.

---

## Your role

You are an independent senior reviewer: part staff engineer, part security
reviewer, part SRE, part product/UX reviewer. You did not build this system and
have no stake in it. Your job is to find out what is actually wrong, weak or
risky - and also what is actually sound - and to say so with evidence. The owner
will act on your report, so an invented problem wastes their time and a missed
one can hurt real families and their money.

The system is `agyary`: a PWA and FastAPI service that gives the priests of
Zoroastrian fire temples in India a calendar, bookings, a private book of the
families they serve, memorial schedules (the observances kept after a death), and
WhatsApp reminders to those families. It is live at a real domain with a handful of
alpha users, free of charge. It handles the names and phone numbers of grieving
families. A mistake in a reminder is not a UI glitch; it lands on someone in
mourning, and it also costs money per message.

The owner's next goals, which your review must speak to directly:
1. Make automatic WhatsApp reminders live for real families.
2. Make sign-in by a WhatsApp code live (it is built and switched off).
3. Ship the app on the Google Play Store.
4. Do all of that without unpleasant surprises: no large bill, no harm to families,
   no data incident, no lock-out.

## How to avoid being biased (read this twice)

- **Form your own picture first.** Read the code, run it, and look at the live site
  BEFORE you read `docs/STATUS.md`, `docs/reminders-plan.md` or `README.md`. Then read
  them and note every place they disagree with what you found. Documents written by the
  builders describe intent and often flatter the result.
- **Treat every claim in the docs, comments, commit messages and tests as a hypothesis**,
  including "this is tested", "this is idempotent", "this cannot double-send", "memorials
  are private to their mobed", "the worst case is a few hundred rupees". Find the line of
  code or the command output that proves or disproves each one. A passing test proves only
  what the test checks.
- **Look for disconfirming evidence on purpose.** For each area, spend real effort trying
  to break it before you conclude it is fine.
- **Challenge decisions, not just code.** The docs list decisions (consent by tick-box, a
  plain template, no plan gating, one shared sending number, an in-process scheduler, ...).
  Say where you think a decision is wrong and what you would do instead and why.
- **Calibrate.** "No issue found" is a valid and valuable result; say it where true and say
  what you checked. Do not pad. Do not inflate severity to look thorough or deflate it to be
  polite. Separate **verified** (you saw it), **inferred** (reasoned from code), and
  **unverified** (could not check) in every finding.
- **Say what you could not do.** If you could not run something or reach something, list it.

## Ground rules (safety)

- **Report first, fix later.** In this phase change no application code, no configuration,
  no database, and nothing on the live server or in Meta. The only file you write is
  `docs/REVIEW.md` (and scratch files outside the repo). The owner decides what to fix.
- **Never send a real message** to anyone, and never turn on `REMINDERS_SEND_MODE=live` or
  `OTP_MODE=live` anywhere that has a token. Never print, log, commit or paste a secret
  (tokens, the JWT secret, `.env` values, phone numbers, government IDs, account IDs). If you
  meet one, say "found a secret in X" without repeating it.
- **Production is read-only.** You may fetch public pages and headers, and use the SSH alias
  `agyary-vm` for read-only inspection (`docker compose ps/logs`, `cat` of non-secret files,
  `ls`, `df`, `free`), always masking secrets (`sed -E 's/=.*/=<hidden>/'` on env files).
  No restarts, edits, deploys or database writes. The Meta console may be read, not changed.
- **The owner's dev server on :8000 must not be touched.** Use a scratch database and port
  8001 (below). Run **one** pytest process at a time: tests share a database and truncate it.
- Ask the owner before anything outward-facing or hard to reverse.
- You may use subagents for breadth if your tools allow it. Verify what they report before
  you repeat it.

## Environment

- Windows 11, Git Bash and PowerShell. Repo root = the working directory. Python 3.12 with `uv`.
  Native Postgres on 5432 (role/db `agyary`; tests use the database `agyary_test`; superuser
  `postgres`/`postgres` locally). Docker's CLI may hang; do not rely on it locally.
- Tests: `uv run pytest` (about 9 minutes for the whole suite; run a subset while exploring).
  Lint: `uv run ruff check src tests`. Migrations: `uv run alembic upgrade head`; check drift
  with `uv run alembic check`.
- Scratch app: create a throwaway database (`create database agyary_ui owner agyary`, then
  `create extension pg_trgm` in it), set `DATABASE_URL=postgresql+asyncpg://agyary:agyary@localhost:5432/agyary_ui`,
  run `alembic upgrade head` and `python -m tests.seed_demo`, start `uvicorn agyary.api.main:app --port 8001`,
  open `http://localhost:8001/mobed`. With `APP_DEBUG=true` and `OTP_MODE=live` and no token, a sign-in
  code is returned in the response so the flow can be exercised; `POST /webhooks/whatsapp/simulate`
  stands in for Meta's sign-in webhook. Use the built-in browser pane and its mobile preset; its service
  worker is blocked (a "fetching the script" console error is expected). Drop the database and stop the
  server when done.
- Live: `https://mobed.gotiadarian.com`. Fetch static files exactly as a phone would (no cache-buster;
  assert 200 first; read `cf-cache-status` and `Age`).
- Writing code on this setup: heredocs can turn `\n` into real newlines. Prefer the file tools.

## Scope: what to examine

For each area, the questions below are starting points, not conclusions. Add your own.

**1. Reminders and the Meta integration** (`services/reminder_*.py`, `guardrails.py`,
`routes/whatsapp.py`, `reminders.py`)
- Can any path send a message to someone who has not consented, has said STOP, is inside the
  first ten days of a memorial, or is not on the allowlist? Can anything send twice? Can a crash,
  restart, deploy overlap, clock change or time-zone edge cause a wrong or duplicate send?
- Is the money actually bounded? Reproduce the cap logic with adversarial inputs. What happens at
  midnight IST, at month end, across a daylight/clock change, with a deleted observance, with two
  mobeds sharing a behdin?
- Is the first real send likely to work? The sender has only ever been tested against a mock. Compare
  the payload with Meta's current Cloud API docs; consider template parameter rules, language codes,
  phone formats, error codes, rate limits, receipts, 24-hour windows, message status ordering.
- STOP handling and the webhook: signature verification, replay, ordering, malformed payloads,
  oversized or hostile input, usernames/BSUID changes that could stop Meta sending a phone number.
- Failure modes and what the mobed is told; the evening window and cutoff; the in-process worker.

**2. Authentication, sessions and authorization** (`services/mobed_auth.py`, `wa_login.py`, `otp.py`,
routes, `api/rate_limit.py`)
- Both sign-in methods, end to end: bypasses, enumeration, brute force, code reuse, race conditions,
  session fixation, cookie flags, refresh-token handling, logout, token lifetime (a ten-year sliding
  refresh cookie), the debug-only `/webhooks/whatsapp/simulate`.
- Authorization: walk EVERY route and decide who may call it. Look for IDOR (one mobed reading
  another's behdins, memorials, notifications, bookings), missing membership checks, role confusion
  (panthaky vs mobed), and admin-only routes. Do not rely on the claim that memorials are private;
  prove it for each read path.
- OTP abuse: SMS-pumping-style cost abuse, harassment of a victim, the new-number path, in-memory
  limits that reset on restart, behaviour behind Cloudflare, spoofable client-IP headers.

**3. Data, database and privacy** (`models/`, `alembic/`, queries)
- Schema design: constraints, foreign keys and `ondelete`, nullability, indexes against the real query
  patterns, uniqueness, the shared `notifications` table, enum-by-check-constraint choices, data types
  for dates and time zones, migration safety on a populated database, downgrade paths.
- N+1 queries, missing eager loads, unbounded queries, transaction boundaries, locking and isolation,
  long transactions that wrap network calls.
- Backups and recovery: what exists, what does not, whether a restore has ever been proven, RPO/RTO.
- Retention and privacy: names and phone numbers of deceased persons and families, indefinite retention,
  erasure, what `static/privacy.html` says versus what the system does. India's Digital Personal Data
  Protection Act 2023 and its rules may apply; flag questions for a lawyer rather than asserting law.
- Phone-number identity: normalisation, the uniqueness constraint, number reuse and recycling.

**4. Backend design and code quality** (`src/agyary/`)
- Service boundaries, layering, naming (`messaging/` is a historical misnomer), duplication, dead code,
  error handling, logging (including whether anything sensitive is logged), configuration handling,
  type safety, async correctness (blocking calls, un-awaited work, cancellation), the lifespan worker.
- Domain correctness: the Parsi calendar engine (`calendar/engine.py`) and the memorial schedule
  (`calendar/memorial.py`, rules in `docs/memorial-plan.md`). These were settled with one priest. Verify
  against at least one independent authority for the three calendars (Shenshai, Kadmi, Fasli), leap/Gatha
  handling, the Roj/Mah counting rules, Parab definitions, and a sample of dates. Report disagreements
  with sources, not opinions.
- Tests: what is not tested; tests that cannot fail; tests coupled to implementation; flakiness; the
  shared-database limitation; coverage of failure paths; whether the mock Meta is faithful.

**5. Frontend, UX and accessibility** (`api/static/mobed/`)
- The users are priests, many older, on mid-range Android phones with patchy connectivity. Walk every
  screen on a 375px viewport and a slow connection: tap targets, text size and contrast, error and empty
  states, loading states, destructive actions, form validation, copy tone (this app speaks of death and
  mourning), keyboard and screen-reader basics, RTL/long-name/long-string behaviour, back-button
  behaviour, offline behaviour.
- The popup of notifications, the consent tick-box and its wording, the Reminders list, the admin screen,
  the two sign-in flows: could a tired person do the wrong thing? Could a mobed turn on reminders for
  someone who has not agreed, and does the wording make that risk clear?
- Performance: payload sizes, number of requests per screen, render cost of the calendar, caching.
- PWA: manifest, icons, installability, the service worker's cache list and update flow, stale-shell
  risk after a deploy, the Cloudflare caching interaction (an earlier deploy was invisible on a phone).
- Internationalisation: English only today; assess the cost of Gujarati.

**6. Deployment, infrastructure and operations**
- The pipeline (`.github/workflows/deploy.yml`, `deploy/deploy.sh`, `Dockerfile`, `docker-compose.yml`):
  failure handling, rollback, migration ordering, secrets handling, downtime during deploy, whether a bad
  migration can corrupt data, health checks, image hygiene (non-root, pinned versions, build cache),
  whether the app can start with a bad `.env`.
- Host: patching, disk, memory, log rotation, SSH exposure, the single point of failure, the tunnel.
- Observability: what would tell the owner the site is down, the loop has stopped, a send failed, or the
  disk is full? Today alerts live only inside the app. Propose the smallest sensible setup.
- Cost: confirm the stated worst-case spend, free-tier limits that could bite, anything that scales
  unexpectedly.
- Secrets: where they live, who can read them, rotation, what is in git history. The repository is
  becoming public: scan the whole history and working tree for anything that should not be there.

**7. Security (general)**
- Headers and CSP (is it correct and sufficient? does it break anything?), CORS, CSRF for cookie-
  authenticated writes, XSS sinks in the vanilla JS (`innerHTML` with unescaped data), injection, SSRF,
  path handling for static files and `/mobed-app`, dependency audit (`uv.lock`; known CVEs), rate
  limiting, error messages that leak, debug flags, `/docs`, the admin check, timing differences.
- Meta account hygiene: two-factor, a single admin, token scope and lifetime, what a leaked token could
  do. (You may read the Meta console; do not change it.)

**8. Readiness assessments (explicit deliverables)**
- **Reminders go-live:** a go/no-go with the exact blockers, in order, and the smallest safe rollout.
- **Sign-in by WhatsApp code:** is the design sound, and is it worth enabling at all given the other
  sign-in is stronger and free? Recommend enabling, changing or dropping it, and why.
- **Play Store:** what route (Trusted Web Activity, Capacitor, other), and everything required: account
  type and fee, any closed-testing requirement for new accounts, signing, Digital Asset Links, manifest and
  icons, screenshots, Data safety and privacy policy, content rating, target API level, review risks for an
  app that handles death-related data and sends messages. Verify each against Google's CURRENT rules;
  they change. Say what in the existing PWA must change first.
- **Product and business sense:** the reminder value proposition, the unvalidated price, the tiny
  market (about 167 temples), consent responsibility on the mobed, and the risk to a shared sending number.

## Deliverable

Write `docs/REVIEW.md` containing, in this order:

1. **Summary** (half a page): your overall judgement, the three to five things that matter most, and
   whether you would let real families receive reminders today. Be direct.
2. **Method and limits:** what you ran, read and fetched; what you could not do; where you disagree
   with the docs.
3. **Findings table**, sorted by severity then area. Each finding has: ID, area, severity, status
   (verified / inferred / unverified), what is wrong (one or two sentences), evidence (file:line,
   command and output, or a URL), impact (who is hurt and how, with a rough likelihood), recommended fix,
   and effort (S under 2 hours, M about a day, L more). Severity scale:
   - **Critical:** can harm a family, leak data, or cost real money, or lock the owner out, with a
     plausible trigger. Fix before anything goes live.
   - **High:** a real defect or gap that will bite soon or breaks a stated guarantee.
   - **Medium:** worth fixing; not urgent.
   - **Low:** polish, hygiene, small risk.
   - **Info:** observation or a decision to revisit.
4. **What is sound:** the parts you tried to break and could not, so the owner knows what not to touch.
5. **The readiness assessments** from section 8.
6. **A prioritised fix plan** in phases (before go-live; before the Play Store; later), each item
   referencing finding IDs, with an honest estimate and the order that minimises risk.
7. **Questions for the owner:** decisions only they can make (legal, commercial, product).

When the report is done, **stop and wait.** Do not start fixing. The owner will say which findings to
act on; then fix them in small commits, each with a test that fails before the fix and passes after,
run the full suite, and deploy only when asked.

Be thorough rather than quick, but spend your effort where the risk is: sending, money, privacy,
authorization and recovery first; polish last.
