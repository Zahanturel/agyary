Decision on question 3/4 (list-input handling), plus one addition — relay this
back and fold it into the plan before continuing.

## WhatsApp (behdin) side: use Flows, not free-text parsing

For any list that can exceed the interactive list message's real 10-row-total
cap, use a WhatsApp Flow with a predefined `Dropdown` — tap to select, no
free-text entry, no fuzzy-matching, no ambiguity between "5", "Bahman", and a
misspelling of either. This replaces the numbered-text-plus-parsing fallback
discussed earlier — don't build that parser.

This splits into two genuinely different amounts of work, don't treat it as
one uniform task:

- **Roj, Mah, Geh — static Flows.** These values never change. Bake them
  directly into the Flow JSON. No live endpoint, no encryption to implement.
  Cheap, do this first.
- **Priest picker and each agyari's Services list — dynamic Flows.** These
  are per-tenant and change over time, so they need a real data-exchange
  endpoint returning the current list, plus Meta's required encryption on
  that exchange. This is where the actual new engineering surface is — scope
  it as its own contained piece of work, don't let the encryption/versioning
  overhead bleed into the static cases above.

## PWA (mobed) side: same principle, much cheaper to apply

Apply the identical rule to the mobed's manual-entry screens in the app: any
field for a closed-vocabulary value (Roj, Mah, Geh, event type, or picking a
priest anywhere it's relevant there) must be a predefined selectable input
(a normal dropdown/select), never a free-text field. Same reasoning as the
WhatsApp side — a wrong Roj from a typo is a real mistake here, not a
cosmetic one, on either surface.

This is much cheaper on the PWA side — it's a plain web `<select>` or
dropdown component, backed by the same JSON API endpoints module 3/4 already
need to exist (no Flows, no encryption, this isn't WhatsApp).

## One requirement tying both together

Both sides must read from the **same canonical source** for these lists —
the WhatsApp Flow's static Roj/Mah/Geh options and the PWA dropdown's options
should not become two independently-hardcoded copies that can drift apart.
Same "one shared source, never duplicated" rule already applied to the machi
slot-check and the name-lookup — this is that same lesson a third time, keep
it consistent.
