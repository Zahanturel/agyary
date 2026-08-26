# Deploying the mobed PWA for an alpha test

Goal: a real, always-on `https://` URL you can share with a handful of alpha
mobeds, who install it by opening the link and tapping "Add to Home Screen" —
no server for them to run, no app-store review, no APK.

This app is a persistent FastAPI process + Postgres (plus, once the
WhatsApp/behdin side is unparked, background `asyncio` workers) — that rules
out static-only hosts (GitHub Pages) and serverless-function platforms
(Vercel), neither of which keep a process alive or host a long-lived
database. It also rules out "free tier" PaaS options that spin the app down
after 15 minutes idle or expire the database after 30 days (Render's free
tier does both) — fine for a five-minute demo, not for an alpha meant to hold
real test data over days or weeks.

**Recommended: Oracle Cloud's "Always Free" tier.** A real always-on VM,
genuinely $0/month forever (not a trial), that runs this repo's existing
`docker-compose.yml` completely unmodified. Some manual signup friction is
expected (see step 1) — that's Oracle, not this repo.

---

## 1. Get a VM (one-time, in your own Oracle Cloud account)

This step needs your own action — creating a cloud account and verifying a
card is not something that can be done on your behalf.

1. Sign up at [oracle.com/cloud/free](https://www.oracle.com/cloud/free/).
   Card verification is required even though the "Always Free" resources
   themselves are never billed.
2. Create a VM instance using an **Ampere (ARM) Always Free** shape (as of
   2026 the free allocation is 2 OCPU / 12 GB RAM — plenty for this app).
   Pick Ubuntu as the image.
3. If you hit "Out of host capacity" on first launch, that's a known, common
   Oracle free-tier issue in busy regions — try a different availability
   domain, or wait and retry. It isn't specific to this app.
4. In the VM's network security list (or the attached security group), open
   inbound ports `80` and `443` if you plan to terminate TLS yourself, or
   skip this if you're using a Cloudflare Tunnel (recommended below) — a
   tunnel makes outbound-only connections, so nothing needs to be opened.
5. Note the VM's public IP and SSH in.

## 2. Install Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# log out and back in for the group change to take effect
```

Docker Compose v2 ships as the `docker compose` subcommand with modern
Docker installs — confirm with `docker compose version`.

## 3. Get the code and configure it

```bash
git clone <this-repo-url> agyary
cd agyary
cp .env.example .env
```

Edit `.env`:
- **`JWT_SECRET_KEY`** — generate a real one: `openssl rand -hex 32`. The
  repo ships this empty, and the app now **refuses to start** until it is
  set. That is deliberate: an empty key doesn't disable auth, it signs every
  session token with the empty string, so anyone could mint a token for any
  user while the app looked perfectly healthy.
- **`APP_DEBUG`** — must be `false`. `POST /webhooks/whatsapp/simulate`
  exists so sign-in can be exercised on a laptop Meta cannot reach, and it
  grants a session for any phone number the caller names. It 404s when
  debug is off. Leaving debug on in production is a complete authentication
  bypass, not a verbosity setting.
- **`WHATSAPP_APP_SECRET`** — the Meta App's secret (App Settings → Basic).
  The webhook verifies every payload's HMAC against it and returns 503 while
  it is blank, rather than comparing against an empty key and accepting
  anything.
- **`WHATSAPP_VERIFY_TOKEN`** — a string you invent (`openssl rand -hex 16`).
  The same value goes into Meta's webhook configuration.
- **`WHATSAPP_SIGNIN_NUMBER`** — the dialable E.164 number the wa.me link
  points at. Note what is *not* here: no API token and no `phone_number_id`.
  This deployment only ever receives from Meta, so it needs no System User
  token and no approved message template.
- Leave `DATABASE_URL` as the `.env.example` default
  (`postgresql+asyncpg://agyary:agyary@db:5432/agyary`) — `docker-compose.yml`
  overrides it to the in-network Postgres hostname regardless, so the exact
  value here doesn't matter as long as it isn't a `localhost` DSN left over
  from local dev.
- `WHATSAPP_*` and `CLOUDFLARE_TUNNEL_TOKEN` stay blank for now; the tunnel
  token is filled in step 4.

## 4. Set up a Cloudflare Tunnel (free)

A tunnel gives you a real `https://` URL without opening any inbound ports
on the VM, and without buying/managing a TLS certificate yourself.

1. Sign up (or sign in) at [dash.cloudflare.com](https://dash.cloudflare.com)
   — free plan is enough. This requires a domain added to Cloudflare (you can
   use a cheap/free subdomain provider, or a domain you already own).
2. Go to **Zero Trust → Networks → Tunnels → Create a tunnel**, choose
   "Cloudflared", name it (e.g. `agyary-alpha`).
3. Add **two Public Hostnames**, both pointing at the same tunnel and the
   same service — `mobed.<your-domain>` and `machi.<your-domain>`, service
   type `HTTP`, service URL `app:8000`. That hostname is the `app` service
   name from `docker-compose.yml`, resolved over the Docker network the
   compose file already sets up, not `localhost`. Cloudflare creates the
   CNAME for each.

   Both hostnames are deliberately the same service. A tunnel ingress rule
   matches on hostname and path but cannot prepend one, so both arrive at
   `/`; the app reads the `Host` header and redirects to `/mobed` or
   `/machi` (see `app_path_for_host` in `api/main.py`). Nothing needs
   configuring in the dashboard for that, and nothing about the routing
   lives outside the repo.

4. The WhatsApp webhook is the same app on every hostname. Point Meta at
   `https://mobed.<your-domain>/webhooks/whatsapp` and subscribe it to the
   `messages` field. Nothing else needs subscribing.

   The number itself needs three things done to it in WhatsApp Manager, not
   two: added to the WABA, **ownership-verified** by SMS or call, and then
   **registered** (a 6-digit two-step-verification PIN). A number that is
   added and verified but never registered looks correct in the dashboard
   and silently receives no webhooks at all — which presents as sign-in
   hanging on "Waiting for your message...". Registration attempts are
   capped at 10 per number per 72 hours, so do not retry it blindly.
5. Copy the tunnel token shown during setup into `.env` as
   `CLOUDFLARE_TUNNEL_TOKEN`.

## 5. Bring it up

```bash
docker compose up -d
```

This starts `db` (Postgres), `app` (this FastAPI app), and `cloudflared`
(the tunnel) — all three already defined in `docker-compose.yml`, unmodified.

Run the one-time schema + seed setup inside the running `app` container:

```bash
docker compose exec app uv run alembic upgrade head
docker compose exec app uv run python -m agyary.scripts.seed_fire_temples
```

## 6. Verify, then share the link

```bash
curl https://mobed.<your-domain>/health
# {"status":"ok"}
```

Open `https://mobed.<your-domain>/mobed` yourself first — walk through
onboarding (name + phone), search/claim or create an agyari, book a machi,
and view/print its slip, to confirm the whole path works from outside your
own network before handing the link to anyone.

Then share the link. Ask each alpha mobed to open it and tap their browser's
"Add to Home Screen" — that's the entire install step; no app store, no
sideloading, no APK.

## Redeploying after a code change

```bash
git pull
docker compose up -d --build
docker compose exec app uv run alembic upgrade head   # only if new migrations exist
```

## Logs / troubleshooting

```bash
docker compose logs -f app          # this app's logs
docker compose logs -f cloudflared  # tunnel connection status
docker compose ps                   # confirm all three services are healthy
```

## Who is using it

```bash
docker compose exec app uv run python -m agyary.scripts.stats
```

Signups and the temple each mobed joined, which temples have members, what was
entered in the last seven days, and sign-in attempts in flight. Read-only, and
phone numbers are masked unless you add `--full`.

The **sign-in attempts** section is the one to watch during a launch. An
attempt row is created the moment somebody taps the button, and claimed only
when their WhatsApp message reaches the webhook. So a pile of unclaimed
attempts means the webhook is not delivering, and the usual causes in order
are: the number was ownership-verified but never **registered**, the Meta app
is still unpublished (an unpublished app receives no production webhooks at
all), or `WHATSAPP_APP_SECRET` is blank. Each of those presents identically —
sign-in hangs on "Waiting for your message..." with nothing in `docker compose
logs`, because the request never arrived.

## Resetting the database

Back up first, off the server, and check the backup restores before you destroy
anything. Every step below was rehearsed end to end.

```bash
# 0. See what you would be destroying.
docker compose exec app uv run python -m agyary.scripts.stats

# 1. Dump, with the date in the name.
docker compose exec -T db pg_dump -U agyary -d agyary -Fc \
  > ~/agyary-$(date +%Y%m%d-%H%M).dump
ls -lh ~/agyary-*.dump

# 2. Prove it is readable. A dump you have not listed is not a backup.
docker compose exec -T db pg_restore -l < ~/agyary-<stamp>.dump | grep -c "TABLE DATA"

# 3. Get it OFF this machine. A backup that only exists on the server it
#    protects is not a backup. From your laptop:
#      scp <user>@<server>:~/agyary-<stamp>.dump .

# 4. Stop the app so nothing holds locks or writes mid-wipe.
docker compose stop app

# 5. Wipe. This is the irreversible one.
docker compose exec -T db psql -U agyary -d agyary -c \
  "DROP SCHEMA public CASCADE; CREATE SCHEMA public; GRANT ALL ON SCHEMA public TO agyary;"

# 6. Rebuild the schema. NOTE: step 5 also dropped the pg_trgm extension,
#    which the trigram indexes on agyary and customer name need. The initial
#    migration recreates it (CREATE EXTENSION IF NOT EXISTS pg_trgm), which is
#    why the migration has to run before anything else touches the database.
docker compose start app
docker compose exec app uv run alembic upgrade head

# 7. Reseed the fire temples. NOT optional: without it the onboarding screen
#    has an empty list and a new mobed cannot pick a temple.
docker compose exec app uv run python -m agyary.scripts.seed_fire_temples

# 8. Confirm: 0 mobeds, 0 of 167 temples claimed.
docker compose exec app uv run python -m agyary.scripts.stats
```

To restore a dump into an empty database instead:

```bash
docker compose stop app
docker compose exec -T db psql -U agyary -d agyary -c \
  "DROP SCHEMA public CASCADE; CREATE SCHEMA public; GRANT ALL ON SCHEMA public TO agyary;"
docker compose exec -T db pg_restore -U agyary -d agyary < ~/agyary-<stamp>.dump
docker compose start app
```

The dump carries the `alembic_version` row with it, so a restore lands on the
revision it was taken at — no migration needed afterwards, and running one
would be wrong.
