"""Domain value sets shared by the ORM models and the messaging layer.

Stored as plain VARCHAR + CHECK constraints (not native Postgres enums) so
adding a value is an in-place constraint swap, never a type migration.
"""

CALENDAR_SYSTEMS = ("shenshai", "kadmi", "fasli")

# What a mobed can choose. Fasli was taken out on 31 Oct 2026 (D5): nothing new is
# reckoned in it. It stays in CALENDAR_SYSTEMS, and in the engine, only so that
# anything already saved in it stays valid and readable (D8).
OFFERED_CALENDARS = ("shenshai", "kadmi")

# What a calendar can be *displayed* in, which includes Gregorian - unlike
# CALENDAR_SYSTEMS above, which is the set of Parsi systems a ceremony's
# Roj/Mah can be reckoned in and stamped onto the record with.
DISPLAY_CALENDAR_SYSTEMS = ("gregorian", *CALENDAR_SYSTEMS)
OFFERED_DISPLAY_SYSTEMS = ("gregorian", *OFFERED_CALENDARS)
DEFAULT_VISIBLE_CALENDAR_SYSTEMS = ("gregorian", "shenshai")
DEFAULT_SECONDARY_CALENDAR_SYSTEM = "shenshai"

# Languages the mobed-facing UI can render in. Deliberately separate from
# BEHDIN_LANGUAGES below: one is what a mobed reads on their own screen,
# the other is what a behdin receives over WhatsApp, and there is no reason
# a mobed reading English can't be messaging a Gujarati-speaking behdin.
DISPLAY_LANGUAGES = ("en", "gu")
DEFAULT_DISPLAY_LANGUAGE = "en"

# Agyari lifecycle. 'unclaimed' rows are seeded reference data (e.g. the
# worldwide fire-temple list) that no mobed has set up yet; 'active' means a
# real mobed has joined and vouched for / corrected its details. Kept separate
# from is_active (which is soft-delete / deactivation) so "exists as a seed
# entry" and "has been set up by a real person" stay different facts.
AGYARY_STATUSES = ("unclaimed", "active")

# Where a fire temple's position on the map came from (DECISIONS D10). "town" is
# the town-level starting position from the seed list (only the town, not the
# temple); "pin" was put on the map by a person - its mobed, panthaky or an admin.
LOCATION_TOWN, LOCATION_PIN = "town", "pin"
LOCATION_SOURCES = (LOCATION_TOWN, LOCATION_PIN)

# How a prayer request from a funeral place reaches a fire temple (DECISIONS D10,
# changed 21 Nov 2026; R3.1), set by its confirmed panthaky or the admin:
# "everyone" - every mobed on its list is asked on WhatsApp at Send (the default,
# and what was live before) - or "panthaky_first" - only the panthaky is told.
# The safety net in "panthaky_first": after this many minutes without the
# panthaky acting, all its mobeds are asked; none (NULL) is Never, the default.
REQUEST_MODE_EVERYONE, REQUEST_MODE_PANTHAKY_FIRST = "everyone", "panthaky_first"
REQUEST_MODES = (REQUEST_MODE_EVERYONE, REQUEST_MODE_PANTHAKY_FIRST)
REQUEST_ESCALATE_MINUTES = (15, 30, 60)

USER_ROLES = ("panthaky", "mobed", "caretaker")
# What an account is (DECISIONS D10): a mobed's (or panthaky's), or a Doongerwadi
# or prayer hall manager's. One kind per person. Every account from before this
# is a mobed's; a manager's sees none of a mobed's app (behdins, calendar,
# machis), and a mobed's none of a manager's.
ACCOUNT_MOBED, ACCOUNT_FUNERAL_MANAGER = "mobed", "funeral_manager"
ACCOUNT_KINDS = (ACCOUNT_MOBED, ACCOUNT_FUNERAL_MANAGER)
# A funeral place (D10): a Doongerwadi, a prayer hall (Worli, for cremation) or
# an aramgah. Only an admin adds one.
FUNERAL_DOONGERWADI, FUNERAL_PRAYER_HALL, FUNERAL_ARAMGAH = "doongerwadi", "prayer_hall", "aramgah"
FUNERAL_PLACE_KINDS = (FUNERAL_DOONGERWADI, FUNERAL_PRAYER_HALL, FUNERAL_ARAMGAH)
# What a person is at their funeral place. Only "manager" for now; staff later.
FUNERAL_MANAGER = "manager"
FUNERAL_PLACE_ROLES = (FUNERAL_MANAGER,)
# A death recorded at a funeral place (D10, Phase 2 Step 4). The title the
# departed is prayed with: the name titles of the rest of the app, Khud too
# (owner, 19 Nov 2026). Four days or one day of obsequies. How the death was
# given (D5): by its Gregorian date, or by Roj and Mah.
DEPARTED_TITLES = ("ervad", "osta", "osti", "behdin", "khud")
OBSEQUIES = ("four_days", "one_day")
DEATH_BY_DATE, DEATH_BY_ROJ_MAH = "date", "roj_mah"
DEATH_GIVEN_BY = (DEATH_BY_DATE, DEATH_BY_ROJ_MAH)
# A funeral record's request to one fire temple. "waiting" for an answer (one at a
# time per record); "accepted" or "declined" by someone asked (Step 5);
# "withdrawn" by the manager; "taken" is kept for Step 5's first-accept-wins (never
# used). "all_set" (R3.1, 21 Nov 2026): every place on the "Who will pray" board
# filled, so enough mobeds are going; requests from before keep their state (D8).
REQUEST_WAITING, REQUEST_ACCEPTED, REQUEST_DECLINED = "waiting", "accepted", "declined"
REQUEST_WITHDRAWN, REQUEST_TAKEN, REQUEST_ALL_SET = "withdrawn", "taken", "all_set"
REQUEST_STATUSES = (REQUEST_WAITING, REQUEST_ACCEPTED, REQUEST_DECLINED, REQUEST_WITHDRAWN, REQUEST_TAKEN,
                    REQUEST_ALL_SET)
# A mobed's access to the app, the owner's one switch per account (DECISIONS D9):
# a new sign-up waits for an admin's approval, and an admin can turn anyone off and on.
ACCESS_PENDING, ACCESS_ON, ACCESS_OFF = "pending", "on", "off"
USER_ACCESS = (ACCESS_PENDING, ACCESS_ON, ACCESS_OFF)
ADMIN_ROLES = ("panthaky", "caretaker")
# What a person says they are at a fire temple when they choose it (DECISIONS D10).
# Only a claim: it never changes ``role``. The owner decides on Admin -> Mobeds;
# confirming a panthaky claim is what sets role = panthaky.
ROLE_MOBED, ROLE_PANTHAKY = "mobed", "panthaky"
CLAIMED_ROLES = (ROLE_MOBED, ROLE_PANTHAKY)
# The owner's decision on a membership's panthaky role: "confirmed" (made
# panthaky), "declined" (not the panthaky, stays mobed), or "removed" (was
# panthaky, made mobed again).
CLAIM_CONFIRMED, CLAIM_DECLINED, CLAIM_REMOVED = "confirmed", "declined", "removed"
CLAIM_DECISIONS = (CLAIM_CONFIRMED, CLAIM_DECLINED, CLAIM_REMOVED)

# Shared state machine for machis and bookings (doc 2 refinement of doc 1).
CEREMONY_STATUSES = (
    "requested",  # customer submitted, awaiting panthaky decision (bookings) / legacy (machis)
    "approved",  # panthaky approved, no mobed assigned yet
    "assigned",  # mobed assigned (and accepted, where acceptance is required)
    "mobed_declined",  # mobed backed out, needs reassignment
    "confirmed",  # machi auto-booked (no human gate) - redesign v3, machis only
    "completed",  # terminal
    "cancelled",  # terminal
    "declined",  # terminal: panthaky declined the request
    "rescheduled",  # terminal: replacement ceremony created
)

# Statuses that release a machi's geh slot for re-booking.
SLOT_RELEASING_STATUSES = ("cancelled", "declined", "rescheduled")

PAYMENT_STATUSES = ("pending", "received", "refunded")
PAYMENT_METHODS = ("upi", "cash", "bank_transfer", "other")

MACHI_PURPOSES = ("patet", "tandarosti")
BOOKING_PURPOSES = ("gujrela_nu", "khushali_nu", "hama_anjuman")

NAME_SECTIONS = ("pair", "farmayeshne")
NAME_TITLES = ("khud", "osta", "osti", "ervad", "behdin")
NAME_STATUSES = ("living", "departed")

BOOKING_MOBED_STATUSES = ("assigned", "accepted", "declined")

RECURRENCE_PATTERNS = ("same_roj_every_mah", "same_roj_mah_every_year", "custom")
RECURRENCE_END_TYPES = ("indefinite", "after_count", "until_date")

BULK_BATCH_STATUSES = ("open", "in_progress", "completed")

# "sending": handed to Meta, no answer yet - never retried (at most once).
NOTIFICATION_STATUSES = ("pending", "queued", "sending", "sent", "delivered", "read", "failed")
# "family": a funeral record's family contact (recipient_id is the record);
# "contact": a mobed on a fire temple's own list (agyary_mobed_contacts), D10.
RECIPIENT_TYPES = ("user", "customer", "family", "contact")
# A mobed's answer to a panthaky's call-out on WhatsApp (D10): "yes" (Yes, I can
# pray) or "no" (Not this time); no answer yet is NULL.
CALLOUT_YES, CALLOUT_NO = "yes", "no"
CALLOUT_ANSWERS = (CALLOUT_YES, CALLOUT_NO)
# How a person on the board was asked and, once they answer, how the answer came
# (R3.1): a WhatsApp button, in the app, by phone (the panthaky marked it after a
# call), or "self" (the panthaky's own "I'll pray").
HOW_WHATSAPP, HOW_APP, HOW_PHONE, HOW_SELF = "whatsapp", "app", "phone", "self"
ANSWER_HOWS = (HOW_WHATSAPP, HOW_APP, HOW_PHONE, HOW_SELF)

MESSAGE_DIRECTIONS = ("inbound", "outbound")

BEHDIN_LANGUAGES = ("en", "gu")

# Geh numbering follows doc 1: index -> display name. The spellings are the
# owner's (word review, 23 Nov 2026): Rapithwan and Uzirin. Only the number is
# ever stored, so a spelling is a change here (and in the app's JS lists) alone.
GEH_NAMES = {
    1: "Havan",
    2: "Rapithwan",
    3: "Uzirin",
    4: "Aiwisruthrem",
    5: "Ushahin",
}


def sql_in(values: tuple[str, ...]) -> str:
    """Render a tuple of values as a SQL IN list for CHECK constraints."""
    return ", ".join(f"'{v}'" for v in values)
