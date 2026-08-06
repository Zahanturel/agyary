We're stopping forward progress to do something we skipped: a real, adversarial
audit of the entire Agyary system, start to finish, using proper flowcharts as
the working method — not another status report.

## Who I need you to be

Act like a senior systems analyst doing a pre-launch audit you'll personally
be blamed for if it's wrong — not like an assistant confirming work that was
already praised. Everything built so far got reviewed in pieces, conversationally,
and it already turned up real gaps the moment a human actually clicked through
it by hand (a name-onboarding step that assumed an agyari already exists with
no way to create one if it doesn't; a dev config defaulting to a hostname that
only resolves inside Docker; seed data with a wrong city; an auth table that
existed in the schema with no actual logic behind it). Those weren't found by
review, they were found by *use*. Your job is to find the next batch of these
by deliberately trying to break every flow on paper before anyone tries to
break it by hand again.

**Do not conclude a flow is "fine" because it matches the design docs.** The
docs describe intent. The code is reality. Where they've drifted — and they
already have, more than once — reality wins, and the drift itself is a
finding worth flagging, not something to silently paper over.

**If you're genuinely unsure whether something is a real gap or a non-issue,
stop and ask. Do not guess and move on, and do not default to "this is
probably fine" to keep momentum.** I would rather you interrupt me five times
with a real question than hand me a document that quietly assumed its way
past something you weren't sure about. I don't want agreement, I want someone
who will argue with a design decision if they think it's wrong, and say so
plainly rather than hedge it into mush.

## Read first

- `05-converged-design-notes.md` — authoritative design intent, supersedes
  `04-...design.md` where they conflict.
- `06-implementation-kickoff-prompt.md`, `07-predefined-input-decision.md` —
  what was actually asked to be built.
- The actual code in `src/agyary/` — this is what's real. Read it, don't
  assume the docs describe it accurately. Run the test suite. Try running
  the app yourself if you're able to (there's a `pgserver`-style or Docker
  Postgres path — check the README) rather than only reading source.
- Git history / diffs since the redesign started, if available, to see what
  actually changed versus what was planned.

## The method: flowcharts, not prose

For every major flow in this system, build a proper flowchart — the kind a
working systems engineer would draw on a whiteboard, using standard notation:

- **Oval** — start / end of a flow.
- **Parallelogram** — input or output (a message arrives, a code is sent, a
  slip is printed, data enters or leaves the system).
- **Rectangle** — a process step, described in plain functional language.
  "Check database" is the right level of detail. "Query the `whatsapp_messages`
  table where status = pending" is the wrong level of detail — that belongs
  in code, not in a flowchart meant to reveal logical gaps. If you catch
  yourself naming a table or column in a box, stop and rewrite it plainer.
- **Diamond** — a decision. Every diamond needs a clearly drawn incoming
  arrow, a Yes branch, a No branch, and if either branch loops back
  somewhere earlier in the flow, draw that loop-back arrow explicitly to
  the exact point it returns to — don't leave a branch dangling or implied.

**Keep every individual diagram simple, even if the whole system needs many
of them.** Don't cram everything into one page and don't force one giant
diagram with arrows crossing everywhere. Split by journey — one flowchart
per major flow, each one clean and easy to trace on its own — and where one
flow hands off into another (onboarding finishing and landing in My Day, a
service request handing off into accept/decline), connect them with a
clearly labeled reference rather than merging the diagrams. Big as a set,
simple one at a time. That's the actual goal — precise and complete, not
compressed for tidiness.

Produce these as real files — draw.io/diagrams.net XML (`.drawio`) if you're
able to generate valid files in that format, so I can open and edit them
directly; otherwise a clean, unambiguous equivalent I can still import or
redraw from without ambiguity about shapes or connections.

## What to actually flowchart — the whole system, not the highlights

Go end to end. At minimum:

1. **Agyari creation** — does a flow even exist for this yet? (As of right
   now, it may not — that's exactly the kind of gap this audit exists to
   catch, don't assume it got built just because we discussed it.)
2. **Mobed onboarding** — name/phone entry, OTP request and verify, agyari
   search, agyari creation fallback if search comes up empty, joining an
   additional agyari later.
3. **Behdin/customer entry via WhatsApp** — QR/referral landing, first-time
   name capture, main menu.
4. **Machi booking** — slot check, confirm, every alternative path when the
   slot's taken, what happens on repeated failure, landing on the shared
   Machi Board.
5. **Services booking** — event selection, date/time, names, choosing a
   priest, the calendar-conflict flag, the request being sent, accept/decline
   from both WhatsApp and the app, contact info exchange, landing on My Day.
6. **Mobed "My Day" / manual add / Machi Board** — including what a mobed
   sees with zero events, with events across multiple agyaries, and what a
   manual walk-in entry does end to end.
7. **Notifications and the WhatsApp Flows plumbing** — message out, message
   in, Flow completion, encryption round-trip, what happens on failure or
   timeout at each step.
8. **Slip and print.**
9. Anything else you find in the actual code that constitutes a distinct
   user-facing or system-facing flow and isn't covered above — the code is
   the source of truth for what "the whole system" actually includes, not
   this list.

## While you build each diagram, keep a running list of what's actually wrong

The flowcharting is the method, the gap list is the point. For every flow,
as you draw it, actively try to break it — and write down, next to the
diagram it belongs to, anything that's:

- **Incomplete** — a decision with no defined path for one of its outcomes,
  a process step that assumes something exists with no flow that creates it.
- **Flawed** — a decision that resolves the wrong way, a loop with no exit,
  two flows that can both mutate the same thing with no coordination between
  them.
- **Assumed, not verified** — anything the design docs asserted that you
  haven't actually confirmed against the running code or a real test.
- **Drifted** — anywhere the implemented code no longer matches doc 05/06/07,
  whether or not the drift seems harmless.

Don't soften these into a "looks mostly good, minor notes" summary at the
end. If you find five real problems, the deliverable says there are five
real problems, specifically, with the exact diagram and node they live at.

## Output

- One `.drawio` (or equivalent) file per major flow, named clearly.
- One written findings document, organized by flow, listing every gap found
  — severity, what's actually wrong, and what you'd need from me to resolve
  it if it's a decision only I can make.
- Anything you were genuinely unsure about while building these — surfaced
  as an explicit question to me, not resolved by assumption.
