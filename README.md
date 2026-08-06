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
  scripts/    seed_demo (demo agyary + panthaky + services)
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
uv run python -m agyary.scripts.seed_demo
uv run uvicorn agyary.api.main:app --reload
```

Then open http://localhost:8000/chat — a two-pane WhatsApp simulator
(customer + panthaky) that drives the full booking flow: onboarding,
machi (patet/tandarosti), service bookings with purpose and name sections,
saved-name reuse, slot alternatives, approval, cancellation.

## Mobed PWA (mobed-only v0)

The priest-facing calendar tool lives at `/mobed` (a no-build vanilla PWA).
Sign in with name + phone (no OTP in this pass), search for your agyari, and
you land in a day/week calendar (My Day) and a per-agyari Machi Board; both
open a shared print-ready slip with Edit.

Set `JWT_SECRET_KEY` in `.env` first (`openssl rand -hex 32`) — the PWA signs
its session token with it. Then seed the worldwide fire-temple reference list
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
