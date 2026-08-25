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
- **`WHATSAPP_OTP_PHONE_NUMBER_ID`** — the Meta phone number sign-in codes
  are sent from. Required in production: sign-in is phone + WhatsApp OTP, and
  with this unset `/api/mobed/auth/otp/request` returns 503 rather than
  accepting codes nobody can receive. In local development it can stay blank
  (the code is written to the log instead of sent).
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
   `messages` field.
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
