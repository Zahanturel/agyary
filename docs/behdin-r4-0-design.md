# R4.0: identity and the app shell (design note, 25 Nov 2026)

Part of [behdin-app-plan.md](behdin-app-plan.md). Working name **Parsi** at `parsi.gotiadarian.com` (owner, 25 Nov 2026; a placeholder kept in one place in the
code; the icon is not chosen yet).

## Owner's answers (25 Nov 2026)

- One number is never both a mobed and a Doongerwadi manager (as today).
- Two separate apps with one sign-in: Mobed Diary stays the mobed's; the behdin app is the person's. Each menu has
  an "Open the other app" link for a person who holds that role. No role switch inside an app.
- The behdin app lives on its own subdomain (name to come). First screen: a home (today's Parsi date, the next
  prayer or memorial, answers to asks, notices); the calendar is a tab beside it.

## The roles model

**Every account is a person and a behdin.** What a person may *also* be is today's `users.account_kind`, which stays
the one place that says it:

| `account_kind` | Means | Mobed app | Behdin app | Needs approval |
|---|---|---|---|---|
| `behdin` (new) | an ordinary person | closed (asks "become a mobed?") | open | no |
| `mobed` | mobed or panthaky | open (when D9 access is on) | open | yes (D9) |
| `funeral_manager` | Doongerwadi manager | manager screens only | open | yes (D9) |

(Options considered: a `user_roles` table now, or a second flag on `users`. A table is the right shape once a
trustee can be a mobed too, but it would touch all 35 places that read `account_kind` for no gain today, since the
owner keeps mobed and manager exclusive. The kinds above are already enforced in one dependency each, so the table
can replace them later without changing the screens. Recommended: keep `account_kind`, add `behdin`.)

- A **new number signing in at the behdin app** becomes `behdin`, access `on`, no approval, no cap, whatever
  `SIGNUP_MODE` says (it governs the mobed app only). A new number at the mobed app is a mobed waiting for approval
  as today.
- A **behdin who wants to be a mobed** (or manager) asks from the mobed app: their kind becomes `mobed` with access
  `pending`, an admin approves (D9). They stay a behdin in the behdin app meanwhile and after. A mobed who is
  waiting or switched off still uses the behdin app (the D9 switch is the mobed side's only).
- **The admin's stop** for abuse: access `off` on a `behdin` account closes the behdin app for it. (Reports and
  blocking arrive with the chat, R4.3.)
- Names, memorials and history follow the person: they hang off the user id and the phone (the person-names pool
  already does), never off the kind.

## The API

- A new dependency `get_current_person`: signed in, active, any kind (a `behdin` with access `off` is refused).
  All `/api/behdin/*` routes use it; no behdin route uses `get_current_user`, and the other way round.
- `get_signed_in_user` and `get_current_user` (the mobed app) refuse `behdin` accounts with 403 plus the existing
  `X-Account-Kind` header, exactly as they refuse managers, so the mobed app can show "this is a behdin account".
- `/api/behdin/auth/wa/start|poll|refresh|logout` reuse the same WhatsApp sign-in; poll creates the account with
  kind `behdin` when there is none. `GET /api/behdin/me`: name, kind, roles list (`behdin` plus `mobed` or
  `manager` with their access), version.
- **Test**: a route-walk like `tests/test_funeral_managers.py`: every mobed route 403s for a behdin, every
  `/api/behdin` route works for any kind, and the manager and mobed rules are unchanged.

## The shell

- Served at `/behdin` on any host (so it also runs locally and on the scratch server); the subdomain is only a
  hostname that reaches the same server through the Cloudflare tunnel, with `/` redirecting to `/behdin`.
  Separate `behdin-manifest.json` (scope `/behdin`), `behdin-sw.js` (`behdin-shell-vNNN`), icons, install page.
- Code in `static/behdin/`, no build step, importing the shared modules (util, ui, the calendar drawing) from
  `/mobed-app/js/`. A test checks both service workers precache every shared file.
- Screens in R4.0: sign-in, name, the home (date and empty cards), a menu (name, text size, "Open Mobed Diary" for
  a mobed, sign out, delete account), "Become a mobed" explained (it is done in the mobed app).
- Account deletion and erasure (services/account.py, erasure.py) work for a `behdin` account as is; every later
  table with a person's data is added to both.

## Migration

One Alembic revision: the `account_kind` check constraint gains `behdin`. No data changes (every account that
exists stays a mobed or manager). Downgrade turns `behdin` accounts into nothing, so it refuses if any exist
(deleting data is not allowed, D8) with a clear message. Extend `tests/test_migrations_run.py`.

## Must not break

Every existing mobed and manager test; D9 approval; the admin Mobeds list (shows only mobeds and managers; behdins
are counted separately); `/health`, the mobed SW (its version changes only if a shared file changes).
