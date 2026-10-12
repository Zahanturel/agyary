# Memorial reminders (the first paid feature)

Working notes, same style as `memorial-plan.md`. Decisions below are what we
agreed in discussion; ON HOLD is what is deliberately not built yet.

## What it is

A family is sent a short WhatsApp message a few days before an observance of
their memorial (Masiso, Varsi, a Parab...), naming the agyari, the departed,
the observance and the date. They can reply to request the ceremony or stop
the reminders. The panthaky of the agyari pays for it; mobeds on the free tier
keep the free version.

## Reality check

- The market is small: `fire_temples.json` lists 167 temples, and only the
  panthakies of some of them will ever pay. Plan for tens of paying agyaris,
  not thousands. So: lean. No payment-gateway integration up front, no
  automation we do not yet need.
- Meta's fee is NOT the constraint (see Cost). Opt-in friction and mobed
  adoption are.

## Settled

**Who pays, who sends**
- The subscription is per AGYARI, held by the panthaky. Free-tier mobeds get
  the free version only (steps 1-2 below).
- One shared sending number ("Mobed Diary"), so every message names the
  agyari in its own text. Replies are routed back by the id of the message
  being replied to, never by the sender's number alone.
- Memorials stay private to the mobed who made them (see `Memorial`). A
  reminder can be switched on only by that mobed, and only if their agyari has
  an active plan. The panthaky pays; they do not thereby read colleagues'
  memorials.

**The message** (one approved template, quick-reply buttons)

    <Agyari name>
    Reminder: <Varsi> of <Ardeshir Mehta> falls on <Roj Ava, Mah Tir>
    (<Thu 14 Nov>).
    [Request Afringan]  [Stop reminders]

- Factual and transactional on purpose. No "book now", no promotion: Meta
  bills a marketing-category template about 7.5x a utility one, and decides
  the category, not us.
- Date shown in the calendar the MEMORIAL was counted in, plus Gregorian,
  exactly as the memorial module already does.
- Default: one reminder, about five days ahead. A second nudge is an option,
  not a default (each message costs).
- Wording is reviewed by a mobed before it is submitted to Meta. Grieving
  families; tone matters more than cost.

**Consent (non-negotiable)**
- WhatsApp requires the recipient to have opted in. The mobed saying "they
  agreed" is not consent.
- Handshake: when a memorial is set up, the family is given a wa.me link that
  opens a chat with a prefilled "Yes, send me reminders for <name> from
  <agyari>". Their message is the consent, and it opens a 24-hour window in
  which our reply is free.
- Store: who, which memorial, which agyari, when, the message id. STOP, in any
  form, is honoured at once and recorded. No consent row, no send. Ever.

**Reply routing**
- A reply carries the id of the message it answers. We map that to the
  `notifications` row, hence to the agyari and memorial. "Request Afringan"
  creates a request the panthaky approves, via the approval flow that already
  exists. Nothing is auto-booked.

**Shared-number reputation**
- Meta rates one number's quality for everybody on it. One agyari's blocked
  messages hurt all. So: per-agyari daily send cap, STOP honoured instantly,
  and an admin view of quality rating and per-agyari block/STOP counts.

## Cost (verify against the Meta rate card in your own account)

Third-party figures, India, 2026: utility about 0.115 INR, marketing about
0.863 INR, plus 18% GST. A utility template sent inside an open 24-hour window
is free; so are free-form replies. Direct Cloud API, so no reseller markup.

Assuming about 1.5 reminders per active memorial per month (to be measured):

| Active memorials | Messages/mo | As utility | As marketing |
|---|---|---|---|
| 100 | 150 | ~Rs 20 | ~Rs 153 |
| 300 | 450 | ~Rs 61 | ~Rs 458 |
| 1,000 | 1,500 | ~Rs 204 | ~Rs 1,528 |

- Utility: negligible. Marketing at the high end would eat a Rs 499 plan, so
  every plan carries a monthly message bundle and a cap, whatever the category.
- Starting price to test: about Rs 299/month or Rs 2,999/year per agyari, with
  a bundle of a few hundred reminders. Collected manually (UPI) for the first
  few agyaris; no gateway until it hurts.
- First 2-3 agyaris free as a pilot, with the cost tracked, to learn real
  messages-per-memorial.

## Meta account setup (gates sending, so it comes first)

Status from the console, Oct 2026: number connected, business UNVERIFIED,
quality rating blank (no outbound yet), no payment method shown, two-factor
off, no email on the profile.

1. Add a payment method (WhatsApp Manager, Payment configuration, India).
   Template sends fail without it.
2. Turn on two-factor for the business portfolio and add an email. This
   account can message grieving families under our name.
3. Business verification. No GST/Udyam yet: Udyam registration is free and
   online (Aadhaar + PAN), usually minutes to a day; Meta's review then takes
   days to a couple of weeks (both are my estimates, unverified). NOT a
   blocker for the pilot: an unverified account's limit (historically about
   250 unique recipients a day, now set per portfolio) is enough for a few
   agyaris. Verify before a wider launch.
4. Submit the utility template for approval (needs the final wording).
5. Check that sign-in still receives the sender's phone number as WhatsApp
   rolls out usernames (the console now has a Contact book panel mentioning
   them). Mobed sign-in learns the phone from the message; if some users
   arrive as a user-scoped id, sign-in breaks. Test before relying on it.

Keep the sending number, WABA id and tokens out of the tree and out of
history, same rule as the sign-in number.

## Data (sketch; names are provisional)

- Reuse `notifications`: it survived the bot teardown and already has
  template name and params, status, retry count and `wa_message_id`. Add the
  memorial observance it is about and the cost category once known.
- `reminder_consents`: customer, memorial, agyari, consented_at,
  consent_message_id, revoked_at.
- `agyari_plan`: agyari, plan, message bundle, period start/end, paid_until.
  Entered by hand at first.
- `message_ledger` (or columns on `notifications`): category and delivered
  status per send, so we can compare cost with revenue per agyari.
- No new scheduler concept: a periodic job queries upcoming
  `memorial_observances` inside the lead window, checks consent and plan,
  and enqueues a `notifications` row. Idempotent by (observance, recipient),
  so a retry or a restart cannot double-send.

## Build order

1. **Due list** (no WhatsApp): per-agyari "reminders due this week" view built
   from `memorial_observances`. Free tier.
2. **Manual send**: a prefilled wa.me message per reminder, tapped by the
   mobed. Costs us nothing. This is the probe: do mobeds use it?
3. **Consent handshake + STOP**: consent table, inbound handling in the
   webhook (which today only reads sign-in codes), reply routing.
4. **Automatic sending**: template, enqueue job, send worker, delivery-status
   webhook, retry with backoff, per-agyari cap. Pilot with 2-3 agyaris.
5. **Plans and the cost/revenue view**: `agyari_plan`, bundle enforcement,
   an admin page. Invoice by hand; revisit a gateway only if it hurts.
6. **Mobed push notifications** (Web Push, free) as a companion channel. Not
   part of the paid feature.

Steps 1-2 need none of the Meta setup. Steps 3+ do.

## ON HOLD

1. **Conversational booking / AI scheduling.** The reply buttons are the safe
   first step toward it. A free-text bot is a separate, larger feature with
   its own PII and wrong-booking risk, to be weighed once reminders earn.
2. **Native apps.** Keep the PWA. Android via a Trusted Web Activity (Play
   Store) and iOS via a Capacitor wrapper are possible later; neither gates
   this feature.
3. **Payment gateway / automated subscriptions.** Manual until volume asks.
4. **Moving sign-in to an outbound OTP.** Rejected for now: the inbound code
   is free, unphishable, and already built. Revisit only if the username
   change breaks it.
5. **Passkeys / long-lived sessions** to reduce sign-ins. Good, separate.
6. **Meta business verification** timing, until Udyam is sorted.
7. **Price.** Rs 299/month is a guess. Ask two panthakies what they pay for
   diaries or booking today before fixing it.
8. **Message volume.** 1.5 per memorial per month is an assumption; replace
   with measured numbers from the pilot.
