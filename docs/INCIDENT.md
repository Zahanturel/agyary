# When something goes wrong

For the owner. Find the section that fits and follow it in order. Write down the time of each step
as you go: it is what you will need afterwards.

The legal time limits below are not yet confirmed. **They are for a lawyer to check.** If in doubt,
treat the shortest one as real.

## Something leaked, or someone got in

Do these in the first hour, in this order. Do not stop to investigate first.

1. **Stop the bleeding.**
   - Admin screen, **Pause all sending**. If the app is unreachable, set `REMINDERS_SEND_MODE=off` and
     `OTP_MODE=off` in the server's `.env`, then `docker compose up -d app`.
   - Revoke the leaked key at its source (Meta, Cloudflare, GitHub, R2).
   - Admin screen, **Sign a mobed out everywhere**, for any account involved.
2. **Write down** when it started, how you found out, what data, and whose.
3. **Keep the evidence.** Save the logs before anything restarts:
   `docker compose logs --no-color > ~/incident-YYYYMMDD.log`. Docker keeps only a few days.
4. **Call the lawyer.** The clocks that may apply:
   - CERT-In: report within **6 hours** of noticing certain incidents. Whether this covers a small
     sole proprietorship is a question for the lawyer. Ask on the same day.
   - DPDP Rule 7, from about May 2027: tell the Board and each person affected without delay, and
     report in full within **72 hours**.
5. **Rotate** every key the server holds, then deploy. This signs everyone out if the JWT key is one
   of them.
6. **Afterwards**, write a short note: what happened, why, and what changed so that it cannot happen
   the same way again.

## A deploy went wrong

Do this on the server as the deploy user, in `~/agyary`.

1. **See what is running:**
   ```bash
   git log -1 --oneline
   docker compose ps
   docker compose logs --tail 80 app
   ```
2. **If the bad deploy had no new migration,** go back to the last good commit:
   ```bash
   git checkout <last-good-sha> -- .
   docker compose build app && docker compose up -d app
   ```
   Wait until `docker compose ps` shows `healthy`.
3. **If it ran a migration:**
   1. New columns or indexes usually work with the old code. Try step 2 first.
   2. If not, stop the app: `docker compose stop app`.
   3. Go down to the revision the old code expects (see its `alembic/versions`):
      ```bash
      docker compose run --rm --no-deps app alembic downgrade <revision>
      ```
   4. Then do step 2.
   5. As a last resort, restore the pre-deploy dump, the newest `~/agyary-*-deploy.dump`, by following
      "To restore a dump" in `DEPLOY.md`.
4. **Then fix forward on a branch.** Never force-push `master`.

## The server is gone

Expect 1-2 hours with the encrypted copy of `.env`, and 3-6 hours without it.

1. **New VM** (`DEPLOY.md` sections 1-2): Ubuntu LTS, Docker, key-only SSH.
2. **Get the code:** `git clone`.
3. **Settings:** restore `.env` from the encrypted copy. Without a copy, make every key again: a Meta
   System User token, the Turnstile keys, a new R2 token, the Cloudflare tunnel token, and a new
   `JWT_SECRET_KEY`, which signs everyone out.
4. **Restore the data.** Copy the latest `daily/*.dump.age` from R2, decrypt it on the laptop with the
   age key, `scp` it across, then:
   ```bash
   docker compose up -d db
   docker compose exec -T db pg_restore -U agyary -d agyary < file.dump
   ```
5. **Start everything:** `docker compose up -d`. The tunnel reconnects by itself, so DNS does not
   change.
6. **Check:** `https://mobed.gotiadarian.com/health?deep=1` shows the database and worker ok, sign in,
   and send a test reminder in `dry_run`.
7. **GitHub:** update `VM_HOST` and `VM_KNOWN_HOSTS`.

## Sending has paused by itself

Five failures in a row, or an account error from Meta, pause all sending. Mobeds are told.

1. Read the reason on the Admin screen.
2. Fix the cause: the prepaid balance, an expired token, or a template Meta has paused.
3. Admin screen, **Resume sending**. Reminders past 21:00 IST are dropped, not sent late.

## Someone asks about their data

See [DATA-REQUESTS.md](DATA-REQUESTS.md).
