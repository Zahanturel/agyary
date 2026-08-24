# Handoff — Mobed Diary

Read these first, in order:

1. `11-mobed-app-scope.md` — what the app is and is not. The contract.
2. `13-mobed-ui-spec.md` — every screen and control, described. It marks
   which parts the owner specified directly and which are unreviewed
   implementation open to redesign.

This file is the state of play and the things a previous session got
wrong.

---

## The product

**Mobed Diary.** A Zoroastrian priest (mobed) manages **their own events**
in one place. Free tier of a planned tiered architecture. A paid agyari
(fire temple) management system may follow, but only after real panthakies
have been consulted — it is not to be designed speculatively.

**Each mobed is an individual user.** A mobed row is linked to a fire
temple in the database for that future system. That link is **not a
product concept**: it appears as an information line in the menu (temple
name and address) and nowhere else. There is no joining, no temple-scoped
grouping, no shared surface, nothing addressed "to" a temple.

**Vocabulary:** the user-facing word is **event**, never "booking". The
models are still `Booking` and `Machi`; that is persistence, not UI.

---

## Stack and layout

- FastAPI + SQLAlchemy async + Postgres. `uv` for everything.
- Alembic migrations in `alembic/versions/`.
- Frontend: vanilla ES modules, **no build step**, at
  `src/agyary/api/static/mobed/` — `index.html`, `app.css`, `js/`.
  Served by a `StaticFiles` mount at `/mobed-app`; `/mobed` is the shell.
- Hash router (`js/router.js`). Five screens, no tab bar.
- 274 tests, `uv run pytest`. Lint: `uv run ruff check src tests`.
- Local Postgres on 5432 (native, not Docker): `agyary`, `agyary_test`.

Commits for this work: `b6a44a4` … `0b89243`.

---

## What is built and working

| Area | State |
|---|---|
| Sign-in | Phone + WhatsApp OTP. Works locally — the code is written to the server log when WhatsApp is unconfigured. |
| Calendar | Day/Week/Month, the mobed's own events. Home screen. |
| Primary calendar | Shenshai/Kadmi/Fasli, per-user. Verified across all ten surfaces in scope §4.1. |
| Events | Six-step wizard: behdin → service or machi → date (Gregorian ⇄ Roj/Mah, synced) → time or Geh → names → confirm. Geh clashes show real alternative slots. |
| Behdins | Scoped to the owning mobed via `user_customers`. Add, edit, saved name pairs/farmayeshne, tap-to-call. |
| Menu | You / Calendar / Behdins. Behind a header icon. |
| Slips | Printable, and rendered in the reader's primary calendar. |
| Management screens | In the tree, **no routes** — invites, service catalog, temple editing. |

---

## The task in front of you

**Replace WhatsApp OTP sign-in with signed invite links**, because OTP
costs money per message and needs a dedicated SIM, a payment method,
template approval and business verification. See scope §7 and §8.

Agreed so far: single-use **and** capped multi-use links; random secret,
stored only as a hash; expiring; revocable.

**Not yet designed, and the thing to settle first:** who issues a link, now
that mobeds are individual users with no temple grouping. A previous
session assumed "any member of a fire temple can invite for that temple"
and was corrected — that model does not exist here. Ask before building.

The existing `agyary_invites` table is temple-and-role shaped and is
probably the wrong shape for this. Do not force it to fit.

Related open items:

- **Does the fire-temple search/join onboarding stay in the UI at all?**
  It exists (`js/screens/onboarding.js`) but is not one of the five
  screens in the scope, and conflicts with the individual-user model. The
  menu does still show temple name and address, which the spec asks for.
- **Encrypt phone numbers at rest.** Wanted. Note that behdins are looked
  up *by* phone constantly, so it needs an HMAC blind index for lookup
  plus the encrypted value for display, and a key in `.env` whose loss
  makes every number unreadable.
- **Global daily send cap on `/auth/otp/request`**, if OTP survives. It is
  billable, and the current limits are per-IP only. Scope §8.1b.
- **OTP template send is written but unverified** — a test WABA cannot
  create templates. `scripts/whatsapp_smoke_test.py` proved the token,
  phone number ID, endpoint and envelope against the live API using
  `hello_world`. Only the Authentication template and its copy-code button
  component remain unverified.

---

## Corrections a previous session needed. Do not repeat them.

1. **Do not over-build.** Several rounds were lost to shipping more than
   was asked. If it is not in the scope doc, it does not ship. If the
   scope is wrong, change the doc first and get agreement, then build.
2. **Behdin names and phone numbers are third parties' personal data.**
   They are scoped to the mobed who registered or served them, enforced
   server-side on every read. Never temple-wide. A list filtered in the
   client is not a permission.
3. **Nothing agyari-shaped in the UI.** See above. This was got wrong
   twice.
4. **Verify, don't assert.** "Does it change everywhere?" is answered by
   walking every surface in a real browser, not by reasoning that it
   should. Doing that found two genuine bugs the reasoning had missed.
5. **Flag community-facing copy, don't guess it.** Role names and
   religious terminology belong to this community; write the functional
   text and mark anything uncertain for review rather than inventing it.
   `js/screens/invites.js` has a worked example of the convention.
6. **Do not stop the dev server** as cleanup. The user works against
   `localhost:8000` live, and the service worker hides an outage behind a
   stale cached shell, which looks like a broken app rather than a
   stopped server.
7. **Treat this as real software development.** Write the decision down,
   get agreement, then implement, then verify. The user has said this
   explicitly and more than once.

---

## Running it

```bash
uv run uvicorn agyary.api.main:app --reload --port 8000
```

Then `localhost:8000/mobed`. Sign-in codes appear in that terminal. The
seeded panthaky is `+919800000001`; a plain mobed is `+919800000002`.

`JWT_SECRET_KEY` must be set or the app refuses to start. `.env` already
has a WhatsApp test token (expires ~24h from 10 Aug 2026) and phone number
ID — regenerate rather than trusting it.
