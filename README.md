# agyary

WhatsApp-based temple management system for Zoroastrian fire temples (agyaries).

## Stack

- Python 3.12, FastAPI, SQLAlchemy (async), Alembic, asyncpg
- Postgres 16
- [uv](https://github.com/astral-sh/uv) for dependency management

## Project layout

```
src/agyary/
  api/        FastAPI app, routers, static web-chat simulator
  core/       settings, database session
  models/     SQLAlchemy ORM models (full v2 schema)
  messaging/  transport-agnostic conversation layer:
              handle_message(db, agyary_id, phone, text) -> [OutgoingMessage]
              flows (machi/service booking, approvals, cancellations),
              regex name parser, Parsi/Gregorian date parser, geh times
  services/   business logic
  calendar/   Parsi (Zoroastrian) calendar engine — pure functions, no DB
```

The messaging layer is the WhatsApp bot without WhatsApp: the web chat UI
(`/chat`) and the future WhatsApp Cloud API webhook are both thin transport
adapters around `handle_message`.

## Local development

```bash
uv sync
cp .env.example .env          # set DATABASE_URL to your local Postgres
uv run alembic upgrade head   # create the schema
uv run python -m tests.seed_demo   # optional: demo agyary, mobeds, services
uv run uvicorn agyary.api.main:app --reload
```

Then open http://localhost:8000/chat — a two-pane WhatsApp simulator
(customer + panthaky) that drives the full booking flow: onboarding,
machi (patet/tandarosti), service bookings with purpose and name sections,
saved-name reuse, slot alternatives, approval, cancellation.

**The simulator is development-only.** It has no auth and takes the behdin's
phone number as a parameter, so it can read and act on any person's bookings.
It is registered only when `APP_DEBUG` is true; in production `/chat` and
`/api/chat/*` return 404.

## Mobed PWA

The priest-facing calendar tool lives at `/mobed` (a no-build vanilla PWA).
Tap "Sign in with WhatsApp" and send the pre-filled code to our number —
you never type a phone number, because we learn it from the message Meta
delivers. Then search for your agyari, and you land in a day/week calendar
(My Day) and a per-agyari Machi Board; both open a shared print-ready slip
with Edit.

Locally there is no WhatsApp to send from, so with `APP_DEBUG=true` you can
close the loop yourself — the code is on screen, and
`POST /webhooks/whatsapp/simulate` with `{"code": ..., "phone": ...}` stands
in for Meta. That endpoint 404s whenever `APP_DEBUG` is false, and it must:
it hands out a session for any number the caller names.

Set `JWT_SECRET_KEY` in `.env` first (`openssl rand -hex 32`) — the app won't
start without it. Then seed the worldwide fire-temple reference list
(167 temples, imported as `unclaimed` until a mobed claims and sets one up):

```bash
uv run python -m agyary.scripts.seed_fire_temples
```

Open http://localhost:8000/mobed.

## Docker

```bash
docker compose up --build
```

API is served at http://localhost:8000. Interactive docs at http://localhost:8000/docs.

## Deploying for an alpha test

See [DEPLOY.md](DEPLOY.md) for a full walkthrough of getting this onto a
free, always-on `https://` URL (Oracle Cloud + Cloudflare Tunnel) that alpha
mobeds install by opening a link and tapping "Add to Home Screen" — no
server for them to run.

## Tests

```bash
uv run pytest
```
