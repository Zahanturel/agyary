"""behdins per mobed: each mobed keeps their own record of a family

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-10-12 00:00:00.000000

docs/DECISIONS.md D2: a behdin is private to the mobed who keeps them. Until
now a behdin was one global row per phone number, shared by every mobed who
typed that number (``user_customers`` said who had them in their book), so a
colleague could read and change what another mobed recorded.

After this, ``customers`` is one row per mobed per family:
``owner_user_id`` says whose, the number is unique within one mobed's book
only, and the reminder consent moves from ``user_customers`` onto the row.
``user_customers`` goes. A STOP is the person's, so it is also remembered
against the number in ``reminder_opt_outs``.

Existing rows are split, not merged or guessed at. For each record, every
mobed who had it in their book or entered an event for it is an owner. The
earliest keeps the row; each other one gets a copy - same name, number,
saved names, fire temples and STOP - and their own events, memorials,
payments and notifications move to it. Nobody can see anything after this
that they could not see before. A record no mobed ever touched (an old
WhatsApp-bot booking) keeps a NULL owner and stays invisible.

Downgrade restores ``user_customers`` and the one-row-per-number rule, and
refuses if any number now has more than one record (there is no honest way
to merge them back).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("customers", sa.Column("owner_user_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        op.f("fk_customers_owner_user_id_users"), "customers", "users", ["owner_user_id"], ["id"]
    )
    op.add_column(
        "customers",
        sa.Column("reminders_enabled", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column("customers", sa.Column("reminders_enabled_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "reminder_opt_outs",
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("phone", name=op.f("pk_reminder_opt_outs")),
    )
    op.execute(
        """
        INSERT INTO reminder_opt_outs (phone, stopped_at)
        SELECT phone, max(reminders_stopped_at) FROM customers
         WHERE reminders_stopped_at IS NOT NULL
         GROUP BY phone
        """
    )

    # Copies share the number, so the old one-row-per-number rule goes first.
    op.drop_constraint("uq_customers_phone", "customers", type_="unique")

    conn = op.get_bind()
    owners = conn.execute(
        sa.text(
            """
            SELECT customer_id, user_id, min(since) AS since FROM (
                SELECT customer_id, user_id, created_at AS since FROM user_customers
                UNION ALL
                SELECT customer_id, created_by_user_id, created_at FROM machis
                 WHERE created_by_user_id IS NOT NULL
                UNION ALL
                SELECT customer_id, created_by_user_id, created_at FROM bookings
                 WHERE created_by_user_id IS NOT NULL
                UNION ALL
                SELECT customer_id, created_by_user_id, created_at FROM memorials
            ) t
            GROUP BY customer_id, user_id
            ORDER BY customer_id, min(since), user_id
            """
        )
    ).all()

    by_customer: dict[int, list[int]] = {}
    for customer_id, user_id, _since in owners:
        by_customer.setdefault(customer_id, []).append(user_id)

    def consent(customer_id: int, user_id: int):
        return conn.execute(
            sa.text(
                "SELECT reminders_enabled, reminders_enabled_at FROM user_customers"
                " WHERE customer_id = :c AND user_id = :u"
            ),
            {"c": customer_id, "u": user_id},
        ).first()

    for customer_id, users in by_customer.items():
        first, *others = users
        row = consent(customer_id, first)
        conn.execute(
            sa.text(
                "UPDATE customers SET owner_user_id = :u, reminders_enabled = :e,"
                " reminders_enabled_at = :at WHERE id = :c"
            ),
            {"u": first, "c": customer_id, "e": bool(row and row[0]), "at": row[1] if row else None},
        )
        for user_id in others:
            row = consent(customer_id, user_id)
            new_id = conn.execute(
                sa.text(
                    """
                    INSERT INTO customers (owner_user_id, name, phone, is_active, reminders_stopped_at,
                                           reminders_enabled, reminders_enabled_at, created_at, updated_at)
                    SELECT :u, name, phone, is_active, reminders_stopped_at, :e, :at, created_at, updated_at
                      FROM customers WHERE id = :c
                    RETURNING id
                    """
                ),
                {"u": user_id, "c": customer_id, "e": bool(row and row[0]), "at": row[1] if row else None},
            ).scalar_one()
            params = {"old": customer_id, "new": new_id, "u": user_id}
            for statement in (
                # What the record carries: saved names and the fire temples it is known at.
                """
                INSERT INTO customer_saved_names (customer_id, section, title, name, status, pair_group,
                                                  display_order, created_at, updated_at)
                SELECT :new, section, title, name, status, pair_group, display_order, created_at, updated_at
                  FROM customer_saved_names WHERE customer_id = :old
                """,
                """
                INSERT INTO agyary_customers (agyary_id, customer_id, first_booking_at, notes, is_active, created_at)
                SELECT agyary_id, :new, first_booking_at, notes, is_active, created_at
                  FROM agyary_customers WHERE customer_id = :old
                """,
                # Payments and notifications follow the events they belong to,
                # so they are moved before the events themselves.
                """
                UPDATE payments SET customer_id = :new
                 WHERE customer_id = :old
                   AND (booking_id IN (SELECT id FROM bookings WHERE customer_id = :old AND created_by_user_id = :u)
                        OR machi_id IN (SELECT id FROM machis WHERE customer_id = :old AND created_by_user_id = :u))
                """,
                """
                UPDATE notifications SET recipient_id = :new
                 WHERE recipient_type = 'customer' AND recipient_id = :old
                   AND (booking_id IN (SELECT id FROM bookings WHERE customer_id = :old AND created_by_user_id = :u)
                        OR machi_id IN (SELECT id FROM machis WHERE customer_id = :old AND created_by_user_id = :u)
                        OR memorial_observance_id IN (
                            SELECT o.id FROM memorial_observances o JOIN memorials m ON m.id = o.memorial_id
                             WHERE m.customer_id = :old AND m.created_by_user_id = :u))
                """,
                "UPDATE machis SET customer_id = :new WHERE customer_id = :old AND created_by_user_id = :u",
                "UPDATE bookings SET customer_id = :new WHERE customer_id = :old AND created_by_user_id = :u",
                "UPDATE memorials SET customer_id = :new WHERE customer_id = :old AND created_by_user_id = :u",
            ):
                conn.execute(sa.text(statement), params)

    op.create_unique_constraint("uq_customers_owner_phone", "customers", ["owner_user_id", "phone"])
    op.create_index("idx_customers_phone", "customers", ["phone"])

    op.drop_index("idx_user_customers_customer", table_name="user_customers")
    op.drop_table("user_customers")


def downgrade() -> None:
    conn = op.get_bind()
    shared = conn.execute(
        sa.text("SELECT count(*) FROM (SELECT phone FROM customers GROUP BY phone HAVING count(*) > 1) t")
    ).scalar_one()
    if shared:
        raise RuntimeError(
            f"Cannot downgrade: {shared} number(s) now have a record for more than one mobed, "
            "and there is no honest way to merge them back into one."
        )

    op.create_table(
        "user_customers",
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("customer_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("reminders_enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("reminders_enabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_user_customers_user_id"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"], ["customers.id"], name=op.f("fk_user_customers_customer_id"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("user_id", "customer_id", name=op.f("pk_user_customers")),
    )
    op.create_index("idx_user_customers_customer", "user_customers", ["customer_id"])
    op.execute(
        """
        INSERT INTO user_customers (user_id, customer_id, created_at, reminders_enabled, reminders_enabled_at)
        SELECT owner_user_id, id, created_at, reminders_enabled, reminders_enabled_at
          FROM customers WHERE owner_user_id IS NOT NULL AND is_active
        """
    )

    op.drop_index("idx_customers_phone", table_name="customers")
    op.drop_constraint("uq_customers_owner_phone", "customers", type_="unique")
    op.create_unique_constraint("uq_customers_phone", "customers", ["phone"])
    op.drop_table("reminder_opt_outs")
    op.drop_column("customers", "reminders_enabled_at")
    op.drop_column("customers", "reminders_enabled")
    op.drop_constraint(op.f("fk_customers_owner_user_id_users"), "customers", type_="foreignkey")
    op.drop_column("customers", "owner_user_id")
