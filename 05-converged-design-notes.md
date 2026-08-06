# Converged design notes — supersedes 04's proposal in several places

This captures everything decided in the brainstorm that produced `behdin_flow` and
`mobed_flow`. It's the technical memory for build time, not something to show a
non-technical reviewer — that's what the two diagrams are for.

## Two front doors, split by user, not one interface for everyone

- **Mobeds get a PWA** (browser link, no install). This is the primary product —
  it has to be fully useful even if no behdin ever touches WhatsApp, because a
  real chunk of usage is walk-ins with zero digital touchpoint. The mobed logs
  those by hand after the fact.
- **Behdins keep WhatsApp**, one number per agyari, unchanged from the original
  architecture. There is no shared/central bot number and no in-chat agyari
  disambiguation — which agyari is just which chat you're in. Entry is via a
  QR code at the agyari or a referral link, so the agyari is already resolved
  before the conversation starts.
- The fuzzy "which agyari" name-resolution problem from earlier in this
  conversation only matters in one place now: a mobed typing their agyari's
  name into the PWA at onboarding. That's a search-as-you-type box, a much
  easier build than trying to solve it inside WhatsApp's list-message
  constraints.

## Money — deliberately absent, not deferred as an afterthought

No amount/price/payment anywhere in this build. Reasoning, not just caution:
the shared Machi board (every priest at an agyari can see it) is structurally
incompatible with tracking earnings on the same surface — visibility and
income-privacy are coupled. Ship free, let mobeds actually use it, take
their input on whether/how to add money later. Don't guess.

## Machi — fully automatic, no exceptions

- No mobed assignment, ever, not even optional/post-hoc. Handled IRL.
- Never bookable in the past. Same-day elapsed-geh logic (Ushahin crossing
  midnight into the next Gregorian morning) already exists in
  `messaging/flows/machi.py::_drop_elapsed_gehs` — reuse it, don't
  reimplement a naive date-only check on the PWA side.
- Slot uniqueness (one machi per geh/roj/mah/year/agyari) is non-negotiable
  and already correctly built as a race-safe partial unique index +
  `SlotTakenError` (`models/machi.py`, `messaging/booking_service.py`).
- **Architecture requirement, not a suggestion:** exactly one shared function
  owns "is this slot valid, is it free, claim it, what are the alternatives
  if not." Both the WhatsApp automatic flow and the PWA's manual walk-in
  entry call into it — neither talks to persistence directly for this
  decision. Same principle for the priest-personal-calendar-conflict check
  on the services side. Two independent implementations of the same
  contested-state check will drift; that's the exact class of bug this
  whole redesign exists to prevent.
- Behdin-facing flow (confirmed structure): pick Roj/Mah/Geh → free? confirm
  instantly, collect names, done. Not free? offer same-day/different-geh,
  same-geh/next-open-day, next-open-day, contact the agyari directly, or
  cancel. No escalation status, no notification-to-admins fallback — that
  whole mechanism from the earlier draft is cut. If nothing automatic
  resolves it, the customer just contacts the agyari directly, same as the
  existing `alt_contact` button.
- Machi Board: shared, per-agyari (not merged across a multi-agyari mobed's
  memberships), visible to every priest working there plus whoever's doing
  ops (caretaker or otherwise) — for names/contact/slip printing. Nobody
  claims it, nobody owns it personally.

## Services (everything that isn't machi) — request/accept, but personal not administrative

**This accept/decline gate REPLACES the old admin-role-gated `approval.py`
mechanism entirely — it does not stack on top of it.** Doc 04 §2.3 said the
services approval gate "stays exactly as it is" (admin-role-gated, via
`ADMIN_ROLES`/`is_admin_phone`) — that was correct when doc 04 was written,
before the mobed-personal-accept/decline model existed, and is superseded by
everything below. If both gates stacked, an agyari with no panthaky/caretaker
would still have zero admin members able to approve anything — the exact bug
this whole redesign exists to fix (doc 04 §1). The whole point of moving to
priest-personal accept/decline is that it works identically whether or not a
panthaky exists, because authority is "did the person I picked say yes," not
"did someone with a role say yes" — that only holds if it replaces the
admin gate, not if it sits underneath one. `approval.py`'s `ADMIN_ROLES` /
`is_admin_phone` approve-decline logic has **no remaining call site in this
design, for either machi or services** — treat it as fully retired. The only
thing worth carrying forward from it is the idempotency-guard *pattern*
("don't act twice on an already-resolved request"), built into the new
priest-personal accept/decline handler as new code, not a repurposing of
`approval.py` itself.

- Menu is a hard split at the top level: "Book a Machi" vs. "See Other
  Services" — not unified into one picklist. Confirmed, not just proposed.
- Flow: pick a service (agyari's configurable list) → Roj/Mah/Time → names →
  choose who to book with, **shown by name only, never the word "mobed"**
  (a mobed's wife or someone else may be running the account — this applies
  to every customer-facing string, not just this one screen).
- Before sending, the system checks the chosen priest's own calendar. If
  they already have something then, the request still goes through — the
  priest's notification just gets an extra note ("you already have
  something at this time, please check the app"). The system never blocks
  the behdin at input time; conflict resolution is the priest's judgment
  call, same philosophy as the two-behdins-request-same-priest case below.
- Contact info flows **immediately, both directions, not gated on accept**:
  the priest gets the behdin's number in the request itself, the behdin
  gets the priest's number the moment they choose them. This is also how
  the "two behdins want the same priest at the same time" collision
  resolves — humans sort it out directly, the system doesn't need conflict
  logic for it.
- Accept/decline: notification only ever goes over WhatsApp (no PWA push —
  deliberately skipped, iOS PWA push is unreliable to build against and
  WhatsApp already does this job). The accept/decline **action** can happen
  from either surface (WhatsApp button or the app), which means it needs to
  be idempotent — reuse the exact guard pattern already in
  `messaging/flows/approval.py` ("was this already resolved?") rather than
  inventing a new one.
- On accept: auto-added to the priest's personal calendar ("My Day").

## Mobed / priest PWA

- Onboarding: name, phone number, WhatsApp OTP verification (reuses the
  existing `AuthOtp` model/precedent), search & select agyari.
- Joining additional agyaries is a standing action from their own menu, not
  onboarding-only. Reuses the same agyari search.
- "My Day": merged across every agyari a mobed belongs to, one chronological
  list, each entry tagged with which agyari it's at (their day doesn't care
  about our tenant boundaries, only we do). Roj/Mah + Gregorian date shown.
- Machi Board: per-agyari, switchable if they belong to more than one — not
  merged. Institutional/shared context, not personal.
- Manual add: agyari auto-filled if the mobed only belongs to one (don't
  make the 90% case pay for the 10% case), asked only if they belong to
  several.
- Name reuse/lookup needs to work from the mobed's side too, not just the
  customer's — many agyaries already have a physical register of family
  names. Same shared lookup both surfaces should hit, not two separate
  saved-name systems.
- Slip fields, confirmed: agyari name, behdin name + contact, event,
  Roj/Mah/Geh-or-time, names. No price, no money, anywhere on it.

## Deliberately deferred, not forgotten

- Shared event-catalog editability at scale (who can edit the service list
  when there are many peer mobeds) — left open on purpose. Ask real mobeds
  once this is live, decide then.
- Onboarding trust beyond phone OTP — decided: OTP only, nothing more, for
  v1. Revisit only if abuse actually shows up.
- WhatsApp list-message row limits for the "pick who to book with" step at
  a large atashbehram with many priests — never actually verified against
  current WhatsApp Business Platform limits. Check before assuming a flat
  list works at 15+ priests; may need a typed-name search fallback instead.
- Exact default service list a new agyari starts with, and the literal
  print layout of the slip — implementation detail, not a design question.

## What NOT to re-litigate

The original `04-mobed-model-and-auto-machi-booking-design.md` proposed
`can_manage`, `AgyaryInvite`, panthaky-vs-peer admin gating, and a
`needs_human` escalation status for machi. Most of that is superseded by
what's in this file — the two-front-door split and the "humans exchange
contact info and sort it out" pattern made a lot of that administrative
machinery unnecessary. Treat this file as current, that one as historical
context for *why* (the original breaking-assumptions analysis in its
§0–§1 still holds), not as the design to build against.
