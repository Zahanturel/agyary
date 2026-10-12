# Owner decisions

The owner's answers, recorded so every session works from the same ones. These are
decisions, not suggestions: do not reopen them. Where a decision needs a safeguard to
be safe, the safeguard is listed and is not optional.

Recorded 12 Oct 2026, in answer to the independent review's questions (section 7).

---

## D1. Who may become a mobed

**Anyone whose phone number is verified may sign up as a mobed**, for now. Verification
is by the sign-in code on WhatsApp (see D3) or by the existing "send us a code" flow.
Later, when the Machi and Mobed apps are merged, a panthaky will approve the mobeds of
their temple.

Safeguards that must ship with open sign-up (they are what make it safe):
- Every cross-account read and write found by the review is closed first (the checks for
  who owns a behdin, a slip, a machi and a record). Open sign-up is not acceptable without
  them: any stranger will be able to create an account.
- A new account must not be able to make our WhatsApp account message strangers with its
  own text. Free text that reaches a template (temple name, service names, the departed's
  name) is validated: bounded length, no links, no @-handles, no long digit runs. At most
  one automatic reminder per recipient number per day.
- New accounts start with low automatic-sending limits that rise as the account ages or is
  vouched for (for example a handful a day for the first week). The existing global,
  per-mobed and per-temple caps stay.
- Joining a temple is not blocked today (anyone may join any temple). Joining must not
  grant access to other people's behdins; see D2.
- Sign-up abuse protection: the code-request step gets a bot check (Cloudflare Turnstile is
  free) and the existing per-number, per-address and new-number limits.

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

The review advised against enabling it. The owner has decided to, so the review's
conditions apply and are part of "done":
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

## Not decided yet

Separate WhatsApp numbers for sign-in and reminders; price and payer; Gujarati reminders; the
privacy policy and the lawyer's answers; whether the repository goes public before the
security fixes are done (it should not).
