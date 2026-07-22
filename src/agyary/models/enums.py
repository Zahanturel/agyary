"""Domain value sets shared by the ORM models and the messaging layer.

Stored as plain VARCHAR + CHECK constraints (not native Postgres enums) so
adding a value is an in-place constraint swap, never a type migration.
"""

CALENDAR_SYSTEMS = ("shenshai", "kadmi", "fasli")

USER_ROLES = ("panthaky", "mobed", "caretaker")
ADMIN_ROLES = ("panthaky", "caretaker")

# Shared state machine for machis and bookings (doc 2 refinement of doc 1).
CEREMONY_STATUSES = (
    "requested",  # customer submitted, awaiting panthaky decision
    "approved",  # panthaky approved, no mobed assigned yet
    "assigned",  # mobed assigned (and accepted, where acceptance is required)
    "mobed_declined",  # mobed backed out, needs reassignment
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
