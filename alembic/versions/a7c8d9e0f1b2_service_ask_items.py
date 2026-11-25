"""R4.2 redesign: a request holds several items

``service_asks`` becomes the request (who, which fire temple, the names, where it stands) and the new
``service_ask_items`` holds each prayer of it: a service with its day and geh or (optional) time, an
optional repeat, or a memorial (the departed's name, the date of passing, an optional repeat). The
request is confirmed or declined as a whole; what a confirm made in the fire temple's diary is pointed
at from the item.

Every request already there becomes a request of ONE item, with what it had (a memorial's old choices
are kept under ``legacy`` so the old way of making it still works); the names, typed, become plain
strings; the free note is dropped (it was copied onto the event when confirmed and carries nothing else).

The downgrade takes people's requests off, and deleting data is not allowed (D8), so it refuses while
any request exists.

Revision ID: a7c8d9e0f1b2
Revises: f6a0b1c2d3e4
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a7c8d9e0f1b2"
down_revision: Union[str, None] = "f6a0b1c2d3e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PURPOSES = "'gujrela_nu', 'khushali_nu', 'hama_anjuman', 'patet', 'tandarosti'"
OLD_CHECKS = {
    "kind": "kind IN ('single', 'repeating', 'memorial')",
    "purpose": f"purpose IN ({PURPOSES})",
    "venue": "venue IN ('agyari', 'home')",
    "geh": "geh IS NULL OR geh BETWEEN 1 AND 5",
    "geh_or_time": "kind = 'memorial' OR num_nonnulls(geh, ceremony_time) = 1",
    "memorial_only": "kind = 'memorial' OR (memorial_choice IS NULL AND memorial_codes IS NULL)",
    "repeat_pattern": "(kind = 'repeating') = (repeat_pattern IS NOT NULL)",
    "repeat_pattern_value": "repeat_pattern IS NULL OR repeat_pattern IN ('monthly', 'yearly')",
}
OLD_FKS = {
    "service_id": ("services", "fk_service_asks_service_id_services", None),
    "result_booking_id": ("bookings", "fk_service_asks_result_booking_id_bookings", "SET NULL"),
    "result_machi_id": ("machis", "fk_service_asks_result_machi_id_machis", "SET NULL"),
    "result_memorial_id": ("memorials", "fk_service_asks_result_memorial_id_memorials", "SET NULL"),
}


def upgrade() -> None:
    op.create_table(
        "service_ask_items",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("ask_id", sa.BigInteger(), nullable=False),
        sa.Column("position", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("kind", sa.String(10), server_default="single", nullable=False),
        sa.Column("service_id", sa.BigInteger()),
        sa.Column("purpose", sa.String(20)),
        sa.Column("ceremony_date", sa.Date(), nullable=False),
        sa.Column("geh", sa.SmallInteger()),
        sa.Column("ceremony_time", sa.Time()),
        sa.Column("repeat_pattern", sa.String(10)),
        sa.Column("repeat_count", sa.SmallInteger()),
        sa.Column("memorial_choice", postgresql.JSONB()),
        sa.Column("unit_price", sa.Numeric(10, 2)),
        sa.Column("result_booking_id", sa.BigInteger()),
        sa.Column("result_machi_id", sa.BigInteger()),
        sa.Column("result_memorial_id", sa.BigInteger()),
        sa.Column("changed_at", sa.DateTime(timezone=True)),
        sa.Column("gone_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["ask_id"], ["service_asks.id"], ondelete="CASCADE",
                                name=op.f("fk_service_ask_items_ask_id_service_asks")),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"], name=op.f("fk_service_ask_items_service_id_services")),
        sa.ForeignKeyConstraint(["result_booking_id"], ["bookings.id"], ondelete="SET NULL",
                                name=op.f("fk_service_ask_items_result_booking_id_bookings")),
        sa.ForeignKeyConstraint(["result_machi_id"], ["machis.id"], ondelete="SET NULL",
                                name=op.f("fk_service_ask_items_result_machi_id_machis")),
        sa.ForeignKeyConstraint(["result_memorial_id"], ["memorials.id"], ondelete="SET NULL",
                                name=op.f("fk_service_ask_items_result_memorial_id_memorials")),
        sa.CheckConstraint("kind IN ('single', 'repeating', 'memorial')", name=op.f("ck_service_ask_items_kind")),
        sa.CheckConstraint(f"purpose IS NULL OR purpose IN ({PURPOSES})", name=op.f("ck_service_ask_items_purpose")),
        sa.CheckConstraint("geh IS NULL OR geh BETWEEN 1 AND 5", name=op.f("ck_service_ask_items_geh")),
        sa.CheckConstraint("geh IS NULL OR ceremony_time IS NULL", name=op.f("ck_service_ask_items_geh_or_time")),
        sa.CheckConstraint("kind = 'memorial' OR service_id IS NOT NULL", name=op.f("ck_service_ask_items_service")),
        sa.CheckConstraint("kind = 'memorial' OR memorial_choice IS NULL",
                           name=op.f("ck_service_ask_items_memorial_only")),
        sa.CheckConstraint("(kind = 'repeating') = (repeat_pattern IS NOT NULL)",
                           name=op.f("ck_service_ask_items_repeat_pattern")),
        sa.CheckConstraint("repeat_pattern IS NULL OR repeat_pattern IN ('monthly', 'yearly')",
                           name=op.f("ck_service_ask_items_repeat_pattern_value")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_service_ask_items")),
    )
    op.create_index("idx_service_ask_items_ask", "service_ask_items", ["ask_id"])

    # Every request already there becomes a request of one item.
    op.execute("""
        INSERT INTO service_ask_items (ask_id, position, kind, service_id, purpose, ceremony_date, geh,
            ceremony_time, repeat_pattern, repeat_count, memorial_choice, unit_price,
            result_booking_id, result_machi_id, result_memorial_id, changed_at, gone_at)
        SELECT a.id, 0, a.kind, a.service_id, CASE WHEN a.kind = 'memorial' THEN NULL ELSE a.purpose END,
            a.ceremony_date, a.geh, a.ceremony_time, a.repeat_pattern, a.repeat_count,
            CASE WHEN a.kind = 'memorial' THEN jsonb_build_object(
                'departed_name', a.memorial_choice -> 'choice' ->> 'departed_name',
                'death_date', coalesce(a.memorial_choice -> 'choice' ->> 'death_known',
                                       a.memorial_choice -> 'choice' ->> 'death_date'),
                'recurring', NULL, 'count', NULL,
                'legacy', jsonb_build_object('choice', a.memorial_choice -> 'choice', 'codes', a.memorial_codes))
            END,
            (SELECT s.default_price FROM services s WHERE s.id = a.service_id),
            a.result_booking_id, a.result_machi_id, a.result_memorial_id, a.changed_at,
            CASE WHEN a.status = 'cancelled_by_fire_temple' THEN a.cancelled_at END
        FROM service_asks a
    """)
    # The names, typed: plain strings (an older request kept them as a ceremony's names).
    op.execute("""
        UPDATE service_asks SET names = coalesce(
            (SELECT jsonb_agg(e ->> 'name') FROM jsonb_array_elements(names) e WHERE jsonb_typeof(e) = 'object'),
            '[]'::jsonb)
    """)

    for name in OLD_CHECKS:
        op.drop_constraint(op.f(f"ck_service_asks_{name}"), "service_asks", type_="check")
    for column, (_t, fk, _on) in OLD_FKS.items():
        op.drop_constraint(fk, "service_asks", type_="foreignkey")
    for column in ("service_id", "kind", "purpose", "geh", "ceremony_time", "venue", "area", "note",
                   "repeat_pattern", "repeat_count", "memorial_choice", "memorial_codes",
                   "result_booking_id", "result_machi_id", "result_memorial_id"):
        op.drop_column("service_asks", column)


def downgrade() -> None:
    bind = op.get_bind()
    held = bind.execute(sa.text("SELECT count(*) FROM service_asks")).scalar_one()
    if held:
        raise RuntimeError(
            "Cannot downgrade: people's requests to fire temples would be deleted (D8). "
            "Take them off by hand first if that is really wanted."
        )
    op.add_column("service_asks", sa.Column("service_id", sa.BigInteger(), nullable=False))
    op.add_column("service_asks", sa.Column("kind", sa.String(10), server_default="single", nullable=False))
    op.add_column("service_asks", sa.Column("purpose", sa.String(20), nullable=False))
    op.add_column("service_asks", sa.Column("geh", sa.SmallInteger()))
    op.add_column("service_asks", sa.Column("ceremony_time", sa.Time()))
    op.add_column("service_asks", sa.Column("venue", sa.String(10), server_default="agyari", nullable=False))
    op.add_column("service_asks", sa.Column("area", sa.String(100)))
    op.add_column("service_asks", sa.Column("note", sa.String(200)))
    op.add_column("service_asks", sa.Column("repeat_pattern", sa.String(10)))
    op.add_column("service_asks", sa.Column("repeat_count", sa.SmallInteger()))
    op.add_column("service_asks", sa.Column("memorial_choice", postgresql.JSONB()))
    op.add_column("service_asks", sa.Column("memorial_codes", postgresql.JSONB()))
    for column in ("result_booking_id", "result_machi_id", "result_memorial_id"):
        op.add_column("service_asks", sa.Column(column, sa.BigInteger()))
    for column, (table, fk, on) in OLD_FKS.items():
        op.create_foreign_key(fk, "service_asks", table, [column], ["id"], ondelete=on)
    for name, expr in OLD_CHECKS.items():
        op.create_check_constraint(op.f(f"ck_service_asks_{name}"), "service_asks", expr)
    op.drop_index("idx_service_ask_items_ask", table_name="service_ask_items")
    op.drop_table("service_ask_items")
