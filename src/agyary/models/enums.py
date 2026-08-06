"""Domain value sets shared by the ORM models and the messaging layer.

Stored as plain VARCHAR + CHECK constraints (not native Postgres enums) so
adding a value is an in-place constraint swap, never a type migration.
"""

CALENDAR_SYSTEMS = ("shenshai", "kadmi", "fasli")

# What a calendar can be *displayed* in, which includes Gregorian - unlike
# CALENDAR_SYSTEMS above, which is the set of Parsi systems a ceremony's
# Roj/Mah can be reckoned in and stamped onto the record with.
DISPLAY_CALENDAR_SYSTEMS = ("gregorian", *CALENDAR_SYSTEMS)
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

USER_ROLES = ("panthaky", "mobed", "caretaker")
ADMIN_ROLES = ("panthaky", "caretaker")

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

NOTIFICATION_STATUSES = ("pending", "queued", "sent", "delivered", "read", "failed")
RECIPIENT_TYPES = ("user", "customer")

MESSAGE_DIRECTIONS = ("inbound", "outbound")

BEHDIN_LANGUAGES = ("en", "gu")

# Geh numbering follows doc 1: index -> display name (v2 spelling, "Uziran").
GEH_NAMES = {
    1: "Havan",
    2: "Rapithwin",
    3: "Uziran",
    4: "Aiwisruthrem",
    5: "Ushahin",
}


def sql_in(values: tuple[str, ...]) -> str:
    """Render a tuple of values as a SQL IN list for CHECK constraints."""
    return ", ".join(f"'{v}'" for v in values)
