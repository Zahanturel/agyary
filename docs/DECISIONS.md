# Owner decisions

The owner's answers, recorded so every session works from the same ones. These are
decisions, not suggestions: do not reopen them. Where a decision needs a safeguard to
be safe, the safeguard is listed and is not optional.

Recorded 12 Oct 2026, in answer to the independent review's questions (section 7).

---

## D1. Who may become a mobed

**Anyone whose phone number is verified may sign up as a mobed.** Verification is by the
sign-in code sent over WhatsApp (D3), or by the existing "send us a code" flow. Later, when the
Machi and Mobed apps are merged, a panthaky will approve the mobeds of their temple.

**This is in force now** (12 Oct 2026): the server runs `SIGNUP_MODE=open` and `OTP_MODE=live`.
It is the owner's decision and the invite-only mode that Phase 0 shipped is NOT a standing
requirement; do not switch sign-up back to invite-only without the owner asking. (An earlier
version of this file made open sign-up wait for other fixes. The owner rejected that ordering.)

The hardening below is **work to do next, in this order**, because open sign-up makes it matter
more. It is not a precondition for sign-up being open:
1. **AZ-3 first**: typing a known number must not attach a mobed to another mobed's behdin
   (D2). This is the largest remaining exposure.
2. A new account must not be able to make our WhatsApp account message strangers with its own
   text. Validate free text that reaches a template (temple name, service names, the departed's
   name): bounded length, no links, no @-handles, no long digit runs. At most one automatic
   reminder per recipient number per day. Low automatic-sending limits for brand-new accounts
   that rise as the account ages or is vouched for. The global, per-mobed and per-temple caps stay.
3. A bot check (Cloudflare Turnstile, free) on the code-request step, plus the per-number,
   per-address and new-number limits already in place.
4. Joining a temple stays unrestricted, and must never grant access to other people's behdins.

## D2. Behdins are private to the mobed who created them

A mobed sees only their own behdins, their names, saved names, history, bookings, memorials
and slips. Nothing about a behdin is visible to another mobed, including one at the same
temple, and typing a phone number that another mobed already has must not reveal or attach
to that mobed's record. Later, when a panthaky can assign work to a mobed, only the assigned
behdin becomes visible, and only to that mobed. That is a future feature; build nothing for
it now, but do not design it out.

Consequences for the design: per-mobed behdin data (name, saved names) belongs to the
mobed's own record, not to a global one keyed by phone. A STOP reply stays global per phone
(a person who says stop is stopped for everyone), and nobody may clear it except by the
"they asked me to" confirmation.

## D3. Roll out with sign-in by a code on WhatsApp

Sign-in by a six digit WhatsApp code goes live (`OTP_MODE=live`); the `login_code`
Authentication template is approved. The "send us a code" flow stays as the other way in
and is fixed (the phishing weakness found by the review).

The review advised against enabling it. The owner has decided to, and it is **live as of 12 Oct
2026**. The review's conditions are follow-up work, not preconditions:
- the template keeps the security recommendation text;
- per-address limits are kept in the database, not only in memory;
- a bot check on the request step for numbers that have no account yet (D1);
- the daily and new-number caps stay, and the pause switch covers it;
- state plainly that WhatsApp users who have adopted usernames may have no phone number
  Meta will send to; they need another route (the review's AU-4).

## D4. Automatic reminders are available to every mobed for now

Everyone gets both: sending by hand through the mobed's own WhatsApp, and automatic
sending. This is a pilot with a handful of invited mobeds. Later, when payments exist,
automatic sending becomes a premium feature and is switched off for non-paying users. So:
keep automatic sending behind one clearly named per-account switch from the start, so that
turning it off for the free tier later is a configuration change, not a rewrite.

"Available to all" does not remove the safeguards in D1, the spend caps, the consent
requirement, the pause switch, or the rule that the opening ten days are never reminded.

**Live as of 13 Oct 2026** (`REMINDERS_SEND_MODE=live`, `REMINDERS_ALLOWLIST=*`). This
followed a test send to the owner's own number: sent, delivered and read, and a STOP reply was
honoured. Every family a mobed has recorded consent for is now reminded automatically the
evening before, unless that mobed's account switch is off.

## D5. Calendar facts (settled with a mobed; do not reopen)

- **Month 10 is named "Dae-Pa-Adar"** in this app (not "Dae"). Roj 8 is also named
  "Dae-Pa-Adar". The spelling is as in `calendar/engine.py`; keep it.
- **There is exactly one Parab per month.** For month 10 it is Roj 8, "Dae-Pa-Adar". The
  other three Creator days of that month are not Parabs for this app. The code already does
  this. The review's finding DM-1 disagreed with sources; the owner's rule wins. Mark DM-1
  closed (owner decision, no change), and do not raise it again.
- **A death before sunrise belongs to the previous Parsi day.** The way the app handles this
  is to give the mobed the choice to state the death by **Roj and Mah (and year)** as well as
  by Gregorian date: the memorial form and API must accept either. The mobed knows which Parsi
  day it was. This replaces any idea of working it out from a time of death. It resolves DM-4.
  Keep showing the death's Roj and Mah on the review step so the mobed confirms it.

## D6. Warmth, and leaving cleanly (14 Oct 2026)

- A family's first STOP gets one short, kind reply naming their mobed: "You will not receive any
  more reminders from <mobed>. May you and your family be in peace." Never a second one. It is a
  paid text reply (about the utility rate since 1 Oct 2026), so it has its own daily cap and
  respects the pause switch.
- The reminder template gains one warm closing line and a "Stop reminders" button
  (`memorial_reminder_v2`), with no invitation wording, so it stays Utility. The current template
  keeps sending until the new one is approved; switching is a setting.
- A mobed can mark a reminder "I told them myself"; nothing is then sent automatically for it.
- A mobed can delete their account, and everything that is theirs goes with it, as Google Play
  requires.
- The Android app is a Trusted Web Activity named "Mobed Diary" (`com.gotiadarian.mobeddiary`).
  **Changed 14 Oct 2026:** it is shared directly with the mobeds (the signed APK, in a WhatsApp
  group the owner runs), not through Google Play for now. No Play fee, closed test or reviewer
  sign-in is needed. The app shows the live site, so updates reach everyone without a new APK;
  a new APK is only needed for the name, icon or Android-level changes. Play stays possible later
  (the listing material is kept), and Google's developer-verification rules for apps installed
  outside Play may require registering as a developer once they reach India.

## Not decided yet

Separate WhatsApp numbers for sign-in and reminders; price and payer; Gujarati reminders; the
privacy policy and the lawyer's answers; whether the repository goes public before the
security fixes are done (it should not).
