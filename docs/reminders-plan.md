# Memorial reminders (the first paid feature)

Working notes, same style as `memorial-plan.md`. Decisions below are what we
agreed in discussion; ON HOLD is what is deliberately not built yet.

## What it is

The evening before a memorial prayer (Masiso, a monthly, Varsi, a Parab...),
about 7 pm IST, the family is sent one short WhatsApp message from the shared
number: which fire temple, when, what and for whom. The mobed turns this on
for a behdin after asking them in person; the behdin can stop it any time by
replying STOP. The panthaky of the agyari pays for it; mobeds on the free tier
keep the free version (the manual "Remind on WhatsApp" button).

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

**What is reminded, and when** (corrected after the first live test)
- The mobed has ALREADY booked the observances (creating the memorial is the
  booking), so a reminder never asks the family to book or arrange anything.
  It tells them what is happening, when, and that they are welcome.
- NEVER during the opening, days 1-10 (`OPENING_DAYS`). The family has just
  lost someone and is at the fire temple with the mobed every day; a text then
  is useless at best and an intrusion at worst. Reminders start with what
  follows: the 29th/30th day on, the monthly and yearly series, the Parabs.
- One reminder, the day before (`REMINDER_LEAD_DAYS = 1`). Each extra message
  costs money, and a booked date needs no week's notice.
- The family sees none of our vocabulary: no "observance", "day 31", "booking".

**The message** (one approved template)

    Reminder from <Agyari name>.

    Tomorrow, Thu 15 Oct (Roj Bahman, Mah Khordad): Afringan and Baaj for
    Ardeshir Mehta at 9:00 am.

    You are welcome to attend.

    To stop these reminders, reply STOP.

  The text submitted to Meta is `reminder_message.TEMPLATE_BODY`, with four
  numbered blanks: the temple, "Tomorrow, Thu 15 Oct", the Parsi date, and
  "Afringan and Baaj for Ardeshir Mehta at 9:00 am." (A template may not begin
  or end with a blank, nor put a newline inside one; both are tested.) The
  manual wa.me message is the same without the STOP line, since a reply to a
  message a mobed sends from their own WhatsApp goes to the mobed, not to us.

- "at 9:00 am" only when the mobed has set a time; it is optional and usually
  blank, so most messages have none. "Tomorrow" / "Today" appear only when true;
  a message built for a further-off date just shows the date.
- Factual and transactional on purpose. Meta bills a marketing-category
  template about 7.5x a utility one and decides the category, not us.
- Date in the calendar the MEMORIAL was counted in, plus Gregorian.
- No reply buttons for now (nothing to ask for). STOP is still required.
- Wording is reviewed by a mobed before it is submitted to Meta. Grieving
  families; tone matters more than cost.

**Consent (non-negotiable)** - decided: the mobed asks in person.
- WhatsApp requires the recipient to have opted in, and Meta accepts opt-in
  collected in person if it is documented. The mobed asks the behdin and ticks
  "has agreed to receive reminders" on the behdin's page
  (`user_customers.reminders_enabled`, with when). It is off by default and
  nothing is ever sent to someone it has not been turned on for. The agreement
  is with one mobed, which is why it lives on `user_customers`, not on the
  behdin. This replaces the earlier wa.me handshake idea, which would have put
  a step on grieving families.
- STOP always wins. The webhook treats a reply that is exactly "stop" or
  "unsubscribe" (any case, light punctuation - not a sentence that merely
  contains the word) as final: it sets `customers.reminders_stopped_at` (the
  person's, so it holds for every mobed), switches reminders off for every mobed
  who had them on, and leaves each of them an in-app notification. A second
  STOP does nothing and tells nobody twice.
- Turning reminders back on for someone who stopped needs an explicit "they
  asked me to" confirmation (the API answers 409 until it is given).
- Consent is checked twice: when planning, and again immediately before each
  send, so a STOP that arrives in between still wins.

**Notifications in the app** (for the mobed, not the behdin)
- A mobed must not miss a family replying STOP or a reminder that failed, so
  `app_notifications` are put in front of them: a popup the moment the app
  opens (or resumes), listing only what they have not yet seen; a bell in the
  header keeps everything for 24 hours, then it lapses. They link to the
  relevant screen. Kinds so far: `reminder_stopped`, `reminder_failed`,
  `reminders_sent` (a summary after each evening's send).
- Not built yet: a notification for a memorial's last observance (today it is
  only the pinned notice on the calendar's last day).

**Replies**
- Nothing else is acted on: the message asks for nothing. Anything but STOP
  is ignored (ON HOLD below).

**Shared-number reputation**
- Meta rates one number's quality for everybody on it. One agyari's blocked
  messages hurt all. So: per-agyari daily send cap, STOP honoured instantly,
  and an admin view of quality rating and per-agyari block/STOP counts.

## Cost (verify against the Meta rate card in your own account)

Third-party figures, India, 2026: utility about 0.115 INR, marketing about
0.863 INR, plus 18% GST. A utility template sent inside an open 24-hour window
is free; so are free-form replies. Direct Cloud API, so no reseller markup.

Assuming about 1 reminder per active memorial per month (to be measured; fewer than before, since the opening days are never reminded):

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
4. Submit the utility template for approval: name `memorial_reminder`,
   language `en`, category Utility, body exactly `TEMPLATE_BODY` with sample
   values for the four blanks. Wording is for a mobed to read first.
5. Create a System User (Business Settings, Users, System users), give it the
   WhatsApp account, generate a token with `whatsapp_business_messaging`, and
   copy the number's Phone number ID. They go in the SERVER's `.env` only
   (`WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`); never in the repo.
6. Subscribe the webhook to the `messages` field if it is not already: delivery
   receipts and STOP replies both arrive there.
7. Check that sign-in still receives the sender's phone number as WhatsApp
   rolls out usernames (the console now has a Contact book panel mentioning
   them). Mobed sign-in learns the phone from the message; if some users
   arrive as a user-scoped id, sign-in breaks. Test before relying on it.

Keep the sending number, WABA id and tokens out of the tree and out of
history, same rule as the sign-in number.

## How it is built

- **Schema** (migration `b9c0d1e2f3a4`): `user_customers.reminders_enabled`
  (+ when), `customers.reminders_stopped_at`, `app_notifications`, and
  `notifications.memorial_observance_id` with a partial unique index so a
  reminder is sent at most once per observance. The existing `notifications`
  table (survived the bot teardown) is the outbox.
- **Wording** (`services/reminder_message.py`): one source for the manual
  message and the template, so a mobed sees exactly what would go out.
- **Consent and STOP** (`services/reminders.py`), HTTP in
  `api/routes/reminders.py`.
- **Planning and sending** (`services/reminder_sender.py`): `plan_tomorrow`
  is the only place the rules are applied (agreed, not stopped, past the
  opening, on the allowlist, under the cap); `send_pending` posts each row to
  Meta and commits it the moment Meta accepts it, one at a time, re-checking
  consent. Refusals (4xx) are final; outages are retried three times, then the
  mobed is told. Past the cutoff nothing is sent late. Delivery receipts move a
  message forward only (sent, delivered, read) and a failure tells the mobed once.
- **The loop** (`services/reminder_worker.py`, started from the app's lifespan
  only when sending is not `off`): every minute, plan from 19:00 IST, send until
  21:00. It holds no state, so a restart mid-evening carries on; one uvicorn
  worker runs, and the unique index makes an overlap during a deploy harmless.
- **Safety**: `REMINDERS_SEND_MODE` is `off` by default. `dry_run` plans and
  logs without writing anything. `live` sends only to `REMINDERS_ALLOWLIST`
  (`*` for everyone; empty means nobody). Per-agyari daily cap of 300.

## Build order

1. **Due list** - done. Per-mobed (memorials are private to their creator).
2. **Manual send** (wa.me, free) - done; stays as the free tier and as the
   fallback when an automatic send fails.
3. **Consent + STOP + in-app notifications** - done.
4. **Automatic sending** - built, switched OFF. Needs the Meta side (payment
   method, template approved, token and phone number ID in the server `.env`).
   Then: `dry_run` for an evening, then `live` with the allowlist set to our own
   numbers, then widen.
5. **Plans and the cost/revenue view**: `agyari_plan`, bundle enforcement, an
   admin page. Invoice by hand; revisit a gateway only if it hurts.
6. **Mobed push notifications** (Web Push, free) as a companion channel. Not
   part of the paid feature.

## Going live (the order matters)

1. Meta: payment method, two-factor, template approved, System User token.
2. Server `.env`: token, phone number ID, `REMINDERS_SEND_MODE=dry_run`,
   `REMINDERS_ALLOWLIST=` empty. Redeploy. Read the log at 7 pm.
3. `REMINDERS_SEND_MODE=live`, `REMINDERS_ALLOWLIST=<our own numbers>`. Make a
   memorial for a test behdin whose 30th day is tomorrow and tick the box.
4. Only after a clean evening: `REMINDERS_ALLOWLIST=*`.

## ON HOLD

1. **Conversational booking / AI scheduling and reply handling.** Reminders
   ask for nothing, so there are no reply buttons. A free-text bot is a
   separate, larger feature with its own PII and wrong-booking risk, to be
   weighed once reminders earn.
2. **A manual "reminded" mark.** Automatic sends now show on the list as sent;
   a reminder sent by hand through the wa.me button still has no mark.
3. **A notification for a memorial's last observance.** Today it is only the
   pinned notice on the calendar's last day.
4. **Native apps.** Keep the PWA. Android via a Trusted Web Activity (Play
   Store) and iOS via a Capacitor wrapper are possible later; neither gates
   this feature.
5. **Payment gateway / automated subscriptions.** Manual until volume asks.
6. **Moving sign-in to an outbound OTP.** Rejected for now: the inbound code
   is free, unphishable, and already built. Revisit only if the username
   change breaks it.
7. **Passkeys / long-lived sessions** to reduce sign-ins. Good, separate.
8. **Meta business verification** timing, until Udyam is sorted.
9. **Price.** Rs 299/month is a guess. Ask two panthakies what they pay for
   diaries or booking today before fixing it.
10. **Message volume.** 1.5 per memorial per month is an assumption; replace
   with measured numbers from the pilot.
