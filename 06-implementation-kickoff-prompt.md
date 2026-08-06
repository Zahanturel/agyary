We're implementing a redesign of this Agyary Management System. This is a real
scope of work, not a small patch — treat it accordingly: plan first, execute
in modules, review your own work, then report honestly on what's actually done.

## Read first, in this order

1. `Agyary Management System v2.md`, `01-system-architecture.md`,
   `02-backend-api.md`, `03-frontend-ux.md` — the original baseline. Some of
   this is now superseded (see below); it's still useful for things this
   redesign doesn't touch.
2. `04-mobed-model-and-auto-machi-booking-design.md` — first redesign pass.
   Its breaking-assumptions analysis (§0–§1: no-panthaky agyaries, the
   never-implemented mobed-assignment stage, the approval gate) is still
   accurate and worth understanding. **Its specific schema proposals
   (`can_manage`, `AgyaryInvite` table, a `needs_human` escalation status) are
   superseded — do not build those.**
3. `05-converged-design-notes.md` — **this is the authoritative spec for
   behavior.** Read it fully before planning anything. It explicitly flags
   what it supersedes from doc 04.
4. `behdin_flow.png` and `mobed_flow.png` — the canonical UX shape for the two
   user-facing flows. These are simplified for a non-technical stakeholder
   review, so they omit some detail that's in doc 05's prose (e.g. the exact
   alternatives offered on a taken machi slot) — doc 05 wins on any detail
   the diagrams don't show, but the diagrams win on step order and what's
   user-visible.
5. `src/agyary/` — the actual codebase. **Verify everything above against
   current code before planning.** Docs may describe things that don't exist
   yet (e.g. there is currently no PWA/frontend for mobeds at all — check),
   and some things assumed missing may already exist (e.g. `AuthOtp` already
   supports phone OTP, reuse it rather than rebuilding).

## Non-negotiables, called out because they're easy to miss or drift from

- No money/payment anywhere in this pass — no amount fields exposed, no UPI,
  nothing. This is a deliberate design decision (see doc 05), not laziness —
  don't opportunistically add it back because the schema has fields for it.
- Machi has exactly one shared function that decides "is this slot valid, is
  it free, claim it, what are the alternatives." Both the WhatsApp flow and
  any manual/PWA entry path call into it. Do not implement the slot check
  twice.
- Never say "mobed" in customer-facing (behdin-side) text. Show names, not
  roles. Audit every existing customer-facing string, not just new ones.
- Machi can never be booked in the past — reuse the existing same-day
  elapsed-geh logic in `messaging/flows/machi.py`, don't write a naive
  date-only check.
- Accept/decline on service requests must be idempotent and actionable from
  more than one entry point (WhatsApp button today, PWA later) — reuse the
  "already resolved?" guard pattern already in `messaging/flows/approval.py`.

## Plan

Before writing code, produce a written plan broken into modules with clear
boundaries and dependencies. Here's a starting decomposition based on the
docs — validate it against what you find in the actual codebase and adjust
before locking it in, don't treat it as gospel:

1. **Shared core / groundwork** (backend) — the shared machi slot-check
   function; the priest-personal-calendar-conflict check used by the
   services flow; whatever minimal, additive schema changes either of those
   actually requires (determine this from the current models, doc 05
   deliberately doesn't prescribe exact columns).
2. **WhatsApp: machi flow** — remove the approval gate for machi only
   (services keep theirs), wire into the shared core from module 1, ensure
   the alternatives-on-taken-slot path fires from the final confirm step too
   (currently only fires mid-flow).
3. **WhatsApp: services flow** — terminology audit, "choose who to book
   with" step, calendar-conflict flag (never blocks), immediate two-way
   contact info exchange at request time, idempotent accept/decline.
4. **Backend: mobed identity & PWA API** — onboarding (name, phone, OTP via
   existing `AuthOtp`, agyari search), join-additional-agyari, My Day query
   (merged across a mobed's agyaries, each entry tagged), Machi Board query
   (per-agyari, not merged), manual-add endpoint (routes through module 1's
   shared core), accept/decline endpoint.
5. **PWA frontend** — onboarding, My Day, add-event form, Machi Board view,
   slip view. No frontend currently exists for this — confirm that, and
   decide a sensible stack consistent with the existing FastAPI backend;
   document that decision rather than silently picking one.
6. **Slip + print** — the five fields only (agyari name, behdin name +
   contact, event, roj/mah/geh-or-time, names), no price, print-friendly.

Flag and resolve (or explicitly punt on, with a note) during planning:
current WhatsApp Business Platform list-message row limits, for the
"choose who to book with" step at agyaries with many priests — doc 05 notes
this was never actually verified.

## Execute

Work module by module. Checkpoint between modules rather than attempting
everything in one pass. It's fine — expected, even — if not everything gets
finished; a clear plan with honest progress beats a rushed attempt at
completeness.

## Review

For each completed module: does the behavior match doc 05 and the two
diagrams, do the non-negotiables above hold, are there tests, do existing
tests still pass, did anything outside the intended module change.

## Final report

When you stop (whether everything's done or not), list plainly: what was
built, module by module; what was explicitly deferred and why; any point
where you deviated from doc 05 or this plan, and why; what still needs a
human decision before it can proceed.
