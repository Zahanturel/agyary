"""Deleting a mobed's account, and everything that is theirs (PV-2).

Google Play requires an app that creates accounts to let people delete them,
in the app and from the web, and India's DPDP Act gives the same right. A
mobed's book is private to them (docs/DECISIONS.md D2), so it all goes: their
behdins and saved names, the memorials they keep, the machis and bookings they
made (with their payments and names), their sign-in sessions, notices and
preferences, and the account itself. Rows that belong to someone else are kept;
any link from them to the departing account is cleared.

Three things outlast it, because deleting an account must not be a way to reset
what a number may send (SEC-02), and none of them says who the families were:
the fact that a message went out (the record is wiped of who and what, and it
still counts against the overall limits), the sign-in codes asked for (swept
after two days anyway), and for a while a one-way digest of the mobed's number.

One transaction, in an order that respects every foreign key: if any step
fails, nothing is deleted.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.core.config import Settings, get_settings
from agyary.models import DeletedAccount, User

# Each statement takes :u, the account being deleted. The temporary tables
# hold the ids that are this mobed's, so every later step is scoped to them.
_STEPS = [
    "CREATE TEMP TABLE gone_customers ON COMMIT DROP AS SELECT id FROM customers WHERE owner_user_id = :u",
    "CREATE TEMP TABLE gone_machis ON COMMIT DROP AS SELECT id FROM machis WHERE created_by_user_id = :u",
    "CREATE TEMP TABLE gone_bookings ON COMMIT DROP AS SELECT id FROM bookings WHERE created_by_user_id = :u",
    "CREATE TEMP TABLE gone_memorials ON COMMIT DROP AS SELECT id FROM memorials"
    " WHERE created_by_user_id = :u OR customer_id IN (SELECT id FROM gone_customers)",
    "CREATE TEMP TABLE gone_rules ON COMMIT DROP AS SELECT id FROM recurrence_rules"
    " WHERE source_machi_id IN (SELECT id FROM gone_machis) OR source_booking_id IN (SELECT id FROM gone_bookings)",
    "CREATE TEMP TABLE gone_batches ON COMMIT DROP AS SELECT id FROM bulk_batches WHERE created_by = :u",
    # Every message to those families, or about those events, or to this mobed.
    "CREATE TEMP TABLE gone_sends ON COMMIT DROP AS SELECT id FROM notifications WHERE"
    " memorial_observance_id IN (SELECT o.id FROM memorial_observances o"
    "   WHERE o.memorial_id IN (SELECT id FROM gone_memorials))"
    " OR machi_id IN (SELECT id FROM gone_machis) OR booking_id IN (SELECT id FROM gone_bookings)"
    " OR (recipient_type = 'customer' AND recipient_id IN (SELECT id FROM gone_customers))"
    " OR (recipient_type = 'user' AND recipient_id = :u)",
    # What never went out goes, so nothing more is sent for this account.
    "DELETE FROM notifications WHERE id IN (SELECT id FROM gone_sends)"
    " AND status IN ('pending', 'queued', 'failed')",
    # What did go out was paid for and counts against the overall limits, so the
    # row stays, with everything that says who or what wiped.
    "UPDATE notifications SET recipient_phone = '', recipient_id = 0, recipient_user_id = NULL,"
    " template_params = CAST('{}' AS jsonb), error_message = NULL, wa_message_id = NULL,"
    " machi_id = NULL, booking_id = NULL, memorial_observance_id = NULL,"
    " status = CASE WHEN status = 'sending' THEN 'sent' ELSE status END"
    " WHERE id IN (SELECT id FROM gone_sends)",
    "DELETE FROM payments WHERE machi_id IN (SELECT id FROM gone_machis)"
    " OR booking_id IN (SELECT id FROM gone_bookings) OR customer_id IN (SELECT id FROM gone_customers)",
    "UPDATE payments SET received_by = NULL WHERE received_by = :u",
    # Repeating and bulk-made events point at their rule or batch, and a rule at
    # the event it came from: unhook them, then the events can go.
    "UPDATE machis SET recurrence_rule_id = NULL WHERE recurrence_rule_id IN (SELECT id FROM gone_rules)",
    "UPDATE bookings SET recurrence_rule_id = NULL WHERE recurrence_rule_id IN (SELECT id FROM gone_rules)",
    "UPDATE machis SET bulk_batch_id = NULL WHERE bulk_batch_id IN (SELECT id FROM gone_batches)",
    "UPDATE bookings SET bulk_batch_id = NULL WHERE bulk_batch_id IN (SELECT id FROM gone_batches)",
    "UPDATE recurrence_rules SET source_machi_id = NULL WHERE source_machi_id IN (SELECT id FROM gone_machis)",
    "UPDATE recurrence_rules SET source_booking_id = NULL WHERE source_booking_id IN (SELECT id FROM gone_bookings)",
    "DELETE FROM machis WHERE id IN (SELECT id FROM gone_machis)",
    "DELETE FROM bookings WHERE id IN (SELECT id FROM gone_bookings)",
    "DELETE FROM recurrence_rules WHERE id IN (SELECT id FROM gone_rules)",
    "UPDATE recurrence_rules SET approved_by = NULL WHERE approved_by = :u",
    "DELETE FROM bulk_batches WHERE id IN (SELECT id FROM gone_batches)",
    # Someone else's events this mobed was only assigned to or named on.
    "UPDATE machis SET assigned_mobed_id = NULL WHERE assigned_mobed_id = :u",
    "DELETE FROM booking_mobeds WHERE user_id = :u",
    # The book itself.
    "DELETE FROM memorials WHERE id IN (SELECT id FROM gone_memorials)",
    "DELETE FROM agyary_customers WHERE customer_id IN (SELECT id FROM gone_customers)",
    "DELETE FROM customers WHERE id IN (SELECT id FROM gone_customers)",
    # Temple memberships, sign-in traces, and the account (its sessions,
    # notices and preferences go with it). login_otps stay: they are what the
    # code limits count, and they are swept after two days.
    "DELETE FROM agyary_users WHERE user_id = :u",
    "DELETE FROM wa_login_attempts WHERE claimed_phone = (SELECT phone FROM users WHERE id = :u)",
    "DELETE FROM users WHERE id = :u",
]


def phone_hmac(settings: Settings, phone: str) -> str:
    """One-way, so the record of deleted accounts holds no phone number."""
    return hmac.new(
        settings.jwt_secret_key.encode(), f"deleted-account:{phone}".encode(), hashlib.sha256
    ).hexdigest()


async def delete_account(db: AsyncSession, user: User) -> None:
    """Delete ``user`` and everything that is theirs. The caller commits."""
    digest = phone_hmac(get_settings(), user.phone)
    now = datetime.now(timezone.utc)
    for step in _STEPS:
        await db.execute(text(step), {"u": user.id} if ":u" in step else {})
    await db.execute(
        pg_insert(DeletedAccount).values(phone_hmac=digest, deleted_at=now)
        .on_conflict_do_update(index_elements=[DeletedAccount.phone_hmac], set_={"deleted_at": now})
    )
    await db.flush()


async def deleted_recently(db: AsyncSession, settings: Settings, phone: str, now: datetime) -> bool:
    """Whether an account with this number was deleted within the cooldown."""
    since = now - timedelta(days=settings.deleted_account_cooldown_days)
    found = await db.execute(
        select(DeletedAccount.phone_hmac).where(
            DeletedAccount.phone_hmac == phone_hmac(settings, phone), DeletedAccount.deleted_at > since,
        )
    )
    return found.first() is not None


async def sweep_deleted_accounts(db: AsyncSession, settings: Settings, now: datetime) -> None:
    """A digest is kept only as long as the cooldown needs it."""
    since = now - timedelta(days=settings.deleted_account_cooldown_days)
    await db.execute(delete(DeletedAccount).where(DeletedAccount.deleted_at <= since))
