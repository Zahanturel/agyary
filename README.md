# agyary

A calendar and booking tool for the priests (mobeds, and the panthaky) of
Zoroastrian fire temples (agyaries), with WhatsApp reminders to the families
they serve. It is a no-build PWA for the mobed, backed by a FastAPI service.

## What it does

- **Calendar and bookings.** A day, week and month calendar in the Parsi
  calendars (Shenshai, Kadmi, Fasli) next to the Gregorian one, per-fire-temple
  Machi Board, and a shared print-ready slip for each ceremony.
- **Behdins.** Each mobed keeps their own book of the families they look after,
  with saved names reused on every booking. A behdin is a person keyed by phone
  number; one mobed's book is never visible to a colleague.
- **Memorials.** From a date of death the app works out every observance a
  family keeps (the opening days, the 30th day, monthly, yearly, the Parabs) and
  puts them on the calendar. See [docs/memorial-plan.md](docs/memorial-plan.md).
- **Reminders.** The evening before a memorial prayer after the opening days, the
  family can be sent a short WhatsApp message - by hand through a `wa.me` link, or
  automatically. See [docs/reminders-plan.md](docs/reminders-plan.md).

## Where to start

- [docs/STATUS.md](docs/STATUS.md): the current state, what is live and what is switched off,
  runbooks, known gaps and what is left. Read this first.
- [docs/REVIEW-PROMPT.md](docs/REVIEW-PROMPT.md): the brief for an independent critical review.
- [docs/reminders-plan.md](docs/reminders-plan.md) and [docs/memorial-plan.md](docs/memorial-plan.md):
  the design decisions behind the two main features.

## Stack

Python 3.12, FastAPI, SQLAlchemy (async), Alembic, asyncpg, Postgres 16, managed
with [uv](https://github.com/astral-sh/uv). The front end is plain ES modules and
a service worker under `src/agyary/api/static/` - there is no build step.

## Layout

```
src/agyary/
  api/        the FastAPI app, its routers, rate limiting, and the PWA's static files
  core/       settings (config.py) and the database session
  models/     SQLAlchemy models
  calendar/   the Parsi calendar engine and the memorial schedule - pure functions, no database
  services/   the rules: memorials, reminders and their sender, sign-in, guardrails
  messaging/  booking core (named for a bot that no longer exists - see its docstring)
tests/        pytest against a real Postgres (agyary_test)
alembic/      migrations
deploy/       the server deploy script
docs/         design notes and plans
```

## Running it locally

```bash
uv sync
cp .env.example .env                       # then fill it in, see below
uv run alembic upgrade head
uv run python -m tests.seed_demo           # optional: a demo fire temple, mobeds and services
uv run python -m agyary.scripts.seed_fire_temples   # optional: 167 reference fire temples
uv run uvicorn agyary.api.main:app --reload
```

Open http://localhost:8000/mobed. In `.env`, set `JWT_SECRET_KEY` first
(`openssl rand -hex 32`); the app refuses to start without it. On a laptop also
set `APP_DEBUG=true`: it is off by default, and without it the browser will not
send the sign-in cookies back over plain http.

### Signing in

There are two ways, and the first is always available.

1. **Send us a code.** The app shows a code and opens WhatsApp with it ready to
   send; the mobed sends it from their own WhatsApp and the page signs them in by
   itself. Their number is proven by Meta and nothing is sent to them, so it
   costs nothing and there is nothing to enumerate.
2. **A code on WhatsApp** (off by default, `OTP_MODE=live`). They type their
   number and we send a six digit code, which the app reads from the clipboard.
   It sends a paid message to a number the caller names, so it is limited hard
   (see Guardrails) and needs an approved WhatsApp *Authentication* template,
   which Meta only allows once the business is verified.

On a laptop there is no WhatsApp to send from, so with `APP_DEBUG=true`
`POST /webhooks/whatsapp/simulate` with `{"code": ..., "phone": ...}` stands in
for Meta, and a sign-in code comes back in the response when no access token is
set. Both are refused whenever `APP_DEBUG` is false, and must be: they hand out a
session for any number the caller names. The simulate endpoint also answers only
a caller on the same machine, and the app refuses to start with `APP_DEBUG=true`
when `APP_ENV=production`.

## Configuration

Everything is read from the environment (`.env`); `.env.example` lists each
setting with its meaning. The ones that matter:

| Setting | What it does |
|---|---|
| `JWT_SECRET_KEY` | Signs sessions. Required. |
| `APP_DEBUG` | Off by default; `true` only on a laptop. The app refuses to start with it on when `APP_ENV=production`. |
| `SIGNUP_MODE`, `SIGNUP_ALLOWLIST` | Who may create an account. `invite` (default): only numbers in the allowlist, and admins; anyone with an account always signs in. `open`: any verified number. |
| `WHATSAPP_APP_SECRET`, `WHATSAPP_VERIFY_TOKEN` | Verify Meta's webhook. |
| `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID` | Needed to SEND anything (reminders, sign-in codes). Server only, never in git. |
| `REMINDERS_SEND_MODE` | `off` (default), `dry_run` (log what would go), or `live`. |
| `REMINDERS_ALLOWLIST` | In `live`, the only numbers messaged; `*` means everyone, empty means nobody. |
| `ADMIN_PHONES` | Numbers that see the Admin screen and receive alerts. |
| `OTP_MODE` | `off` (default) or `live` for sign-in by WhatsApp code. |

### Guardrails

Every message sent is paid, so sending is ringed with limits: a ceiling per day
and per month overall, per mobed and per fire temple (`REMINDERS_*_CAP`), a pause
switch for admins that survives a restart, and an automatic pause when Meta
reports an account-level problem or several sends fail in a row. A reminder over
a limit is not sent, its mobed is told so they can send it by hand, and the admins
are alerted. Meta's prepaid balance, with no auto top-up, is the outermost limit.
Details are in `src/agyary/services/guardrails.py`.

### Security

Sessions are short-lived JWTs with a sliding refresh cookie. Every endpoint that
sends or guesses at something is rate limited per address and per subject. The
webhook verifies Meta's signature and caps the body size. Responses carry a
Content-Security-Policy that allows only the app's own files (the app has no
inline script and no third-party host, which a test enforces), HSTS in
production, and the usual framing and sniffing headers. Secrets live only in the
server's `.env`, which is readable by its owner alone.

## Docker

```bash
docker compose up --build
```

The API is served at http://localhost:8000. The interactive docs (`/docs`) exist
only when `APP_DEBUG` is true.

## Deploying

Pushing to `master` runs the tests and, if they pass, deploys: a database backup,
a build, the migrations, the swap, and a health check
(`.github/workflows/deploy.yml`, `deploy/deploy.sh`). [DEPLOY.md](DEPLOY.md) and
[deploy/README.md](deploy/README.md) cover setting the server up the first time.

## Tests

```bash
uv run pytest
```

The tests use a real Postgres database called `agyary_test` and truncate it, so
run one pytest at a time.
