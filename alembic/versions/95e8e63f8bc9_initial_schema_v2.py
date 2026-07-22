"""initial schema v2

Revision ID: 95e8e63f8bc9
Revises: 
Create Date: 2026-07-21 21:03:29.000794

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '95e8e63f8bc9'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # pg_trgm is a trusted extension (PG13+), so the database owner may create
    # it; needed by idx_customers_name_trgm for fuzzy customer search.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table('agyaries',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('city', sa.String(length=100), nullable=False),
    sa.Column('address', sa.Text(), nullable=True),
    sa.Column('calendar_system', sa.String(length=10), server_default='shenshai', nullable=False),
    sa.Column('contact_phone', sa.String(length=20), nullable=True),
    sa.Column('wa_phone_number', sa.String(length=20), nullable=True),
    sa.Column('wa_phone_number_id', sa.String(length=50), nullable=True),
    sa.Column('wa_display_name', sa.String(length=100), nullable=True),
    sa.Column('upi_id', sa.String(length=100), nullable=True),
    sa.Column('qr_code_url', sa.Text(), nullable=True),
    sa.Column('max_machis_per_geh', sa.SmallInteger(), server_default='1', nullable=False),
    sa.Column('require_mobed_acceptance', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('behdin_language', sa.String(length=10), server_default='en', nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("behdin_language IN ('en', 'gu')", name=op.f('ck_agyaries_behdin_language')),
    sa.CheckConstraint("calendar_system IN ('shenshai', 'kadmi', 'fasli')", name=op.f('ck_agyaries_calendar_system')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_agyaries'))
    )
    op.create_index('idx_agyaries_city', 'agyaries', ['city'], unique=False)
    op.create_index('uq_agyaries_wa_phone_number_id', 'agyaries', ['wa_phone_number_id'], unique=True, postgresql_where=sa.text('wa_phone_number_id IS NOT NULL'))
    op.create_table('auth_otps',
    sa.Column('phone', sa.String(length=20), nullable=False),
    sa.Column('code_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('attempts', sa.SmallInteger(), server_default='0', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('phone', name=op.f('pk_auth_otps'))
    )
    op.create_table('customers',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('phone', sa.String(length=20), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_customers')),
    sa.UniqueConstraint('phone', name=op.f('uq_customers_phone'))
    )
    op.create_index('idx_customers_name_trgm', 'customers', ['name'], unique=False, postgresql_using='gin', postgresql_ops={'name': 'gin_trgm_ops'})
    op.create_table('users',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('phone', sa.String(length=20), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_users')),
    sa.UniqueConstraint('phone', name=op.f('uq_users_phone'))
    )
    op.create_table('agyary_customers',
    sa.Column('agyary_id', sa.BigInteger(), nullable=False),
    sa.Column('customer_id', sa.BigInteger(), nullable=False),
    sa.Column('first_booking_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['agyary_id'], ['agyaries.id'], name=op.f('fk_agyary_customers_agyary_id_agyaries')),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('fk_agyary_customers_customer_id_customers')),
    sa.PrimaryKeyConstraint('agyary_id', 'customer_id', name=op.f('pk_agyary_customers'))
    )
    op.create_index('idx_agyary_customers_customer', 'agyary_customers', ['customer_id'], unique=False)
    op.create_table('agyary_users',
    sa.Column('agyary_id', sa.BigInteger(), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('reminder_minutes_before', sa.SmallInteger(), server_default='30', nullable=False),
    sa.Column('joined_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("role IN ('panthaky', 'mobed', 'caretaker')", name=op.f('ck_agyary_users_role')),
    sa.ForeignKeyConstraint(['agyary_id'], ['agyaries.id'], name=op.f('fk_agyary_users_agyary_id_agyaries')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_agyary_users_user_id_users')),
    sa.PrimaryKeyConstraint('agyary_id', 'user_id', name=op.f('pk_agyary_users'))
    )
    op.create_index('idx_agyary_users_user', 'agyary_users', ['user_id'], unique=False)
    op.create_table('conversation_states',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('agyary_id', sa.BigInteger(), nullable=False),
    sa.Column('phone', sa.String(length=20), nullable=False),
    sa.Column('flow', sa.String(length=50), nullable=False),
    sa.Column('step', sa.String(length=50), nullable=False),
    sa.Column('data', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['agyary_id'], ['agyaries.id'], name=op.f('fk_conversation_states_agyary_id_agyaries')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_conversation_states')),
    sa.UniqueConstraint('agyary_id', 'phone', name='uq_conversation_states_agyary_phone')
    )
    op.create_index('idx_conversation_states_expiry', 'conversation_states', ['expires_at'], unique=False)
    op.create_table('customer_saved_names',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('customer_id', sa.BigInteger(), nullable=False),
    sa.Column('section', sa.String(length=20), nullable=False),
    sa.Column('title', sa.String(length=20), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('pair_group', sa.SmallInteger(), nullable=True),
    sa.Column('display_order', sa.SmallInteger(), server_default='0', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("section IN ('pair', 'farmayeshne')", name=op.f('ck_customer_saved_names_section')),
    sa.CheckConstraint("status IN ('living', 'departed')", name=op.f('ck_customer_saved_names_status')),
    sa.CheckConstraint("title IN ('khud', 'osta', 'osti', 'ervad', 'behdin')", name=op.f('ck_customer_saved_names_title')),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('fk_customer_saved_names_customer_id_customers'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_customer_saved_names'))
    )
    op.create_index('idx_customer_saved_names_customer', 'customer_saved_names', ['customer_id'], unique=False)
    op.create_table('recurrence_rules',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('agyary_id', sa.BigInteger(), nullable=False),
    sa.Column('source_machi_id', sa.BigInteger(), nullable=True),
    sa.Column('source_booking_id', sa.BigInteger(), nullable=True),
    sa.Column('pattern', sa.String(length=30), nullable=False),
    sa.Column('pattern_data', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('end_type', sa.String(length=20), server_default='indefinite', nullable=False),
    sa.Column('end_count', sa.Integer(), nullable=True),
    sa.Column('end_date', sa.Date(), nullable=True),
    sa.Column('last_generated_until', sa.Date(), nullable=True),
    sa.Column('generation_horizon_months', sa.SmallInteger(), server_default='3', nullable=False),
    sa.Column('approved_by', sa.BigInteger(), nullable=True),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("end_type IN ('indefinite', 'after_count', 'until_date')", name=op.f('ck_recurrence_rules_end_type')),
    sa.CheckConstraint("pattern IN ('same_roj_every_mah', 'same_roj_mah_every_year', 'custom')", name=op.f('ck_recurrence_rules_pattern')),
    sa.CheckConstraint('num_nonnulls(source_machi_id, source_booking_id) = 1', name=op.f('ck_recurrence_rules_exactly_one_source')),
    sa.ForeignKeyConstraint(['agyary_id'], ['agyaries.id'], name=op.f('fk_recurrence_rules_agyary_id_agyaries')),
    sa.ForeignKeyConstraint(['approved_by'], ['users.id'], name=op.f('fk_recurrence_rules_approved_by_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_recurrence_rules'))
    )
    op.create_index('idx_recurrence_active', 'recurrence_rules', ['agyary_id', 'is_active'], unique=False, postgresql_where=sa.text('is_active = true'))
    op.create_table('services',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('agyary_id', sa.BigInteger(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('default_price', sa.Numeric(precision=10, scale=2), nullable=True),
    sa.Column('min_mobeds', sa.SmallInteger(), server_default='1', nullable=False),
    sa.Column('typical_duration_minutes', sa.Integer(), nullable=True),
    sa.Column('offsite_capable', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
    sa.Column('display_order', sa.SmallInteger(), server_default='0', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['agyary_id'], ['agyaries.id'], name=op.f('fk_services_agyary_id_agyaries')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_services')),
    sa.UniqueConstraint('agyary_id', 'name', name='uq_services_agyary_name')
    )
    op.create_table('whatsapp_messages',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('agyary_id', sa.BigInteger(), nullable=False),
    sa.Column('direction', sa.String(length=10), nullable=False),
    sa.Column('wa_phone', sa.String(length=20), nullable=False),
    sa.Column('customer_id', sa.BigInteger(), nullable=True),
    sa.Column('wa_message_id', sa.String(length=100), nullable=True),
    sa.Column('wa_timestamp', sa.DateTime(timezone=True), nullable=True),
    sa.Column('message_type', sa.String(length=20), nullable=False),
    sa.Column('content', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('template_name', sa.String(length=100), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("direction IN ('inbound', 'outbound')", name=op.f('ck_whatsapp_messages_direction')),
    sa.ForeignKeyConstraint(['agyary_id'], ['agyaries.id'], name=op.f('fk_whatsapp_messages_agyary_id_agyaries')),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('fk_whatsapp_messages_customer_id_customers')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_whatsapp_messages'))
    )
    op.create_index('idx_wa_messages_agyary_phone', 'whatsapp_messages', ['agyary_id', 'wa_phone', sa.literal_column('created_at DESC')], unique=False)
    op.create_index('idx_wa_messages_wa_id', 'whatsapp_messages', ['wa_message_id'], unique=False, postgresql_where=sa.text('wa_message_id IS NOT NULL'))
    op.create_table('bulk_batches',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('agyary_id', sa.BigInteger(), nullable=False),
    sa.Column('service_id', sa.BigInteger(), nullable=False),
    sa.Column('gregorian_date', sa.Date(), nullable=False),
    sa.Column('parsi_roj', sa.SmallInteger(), nullable=False),
    sa.Column('parsi_mah', sa.SmallInteger(), nullable=False),
    sa.Column('parsi_year', sa.Integer(), nullable=False),
    sa.Column('calendar_system', sa.String(length=10), nullable=False),
    sa.Column('total_entries', sa.Integer(), server_default='0', nullable=False),
    sa.Column('completed_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('status', sa.String(length=20), server_default='open', nullable=False),
    sa.Column('created_by', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('open', 'in_progress', 'completed')", name=op.f('ck_bulk_batches_status')),
    sa.ForeignKeyConstraint(['agyary_id'], ['agyaries.id'], name=op.f('fk_bulk_batches_agyary_id_agyaries')),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_bulk_batches_created_by_users')),
    sa.ForeignKeyConstraint(['service_id'], ['services.id'], name=op.f('fk_bulk_batches_service_id_services')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_bulk_batches'))
    )
    op.create_index('idx_bulk_batches_agyary_date', 'bulk_batches', ['agyary_id', 'gregorian_date'], unique=False)
    op.create_table('bookings',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('agyary_id', sa.BigInteger(), nullable=False),
    sa.Column('service_id', sa.BigInteger(), nullable=False),
    sa.Column('customer_id', sa.BigInteger(), nullable=False),
    sa.Column('date_time', sa.DateTime(timezone=True), nullable=False),
    sa.Column('end_time', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ceremony_datetime', sa.DateTime(timezone=True), nullable=False),
    sa.Column('parsi_roj', sa.SmallInteger(), nullable=False),
    sa.Column('parsi_mah', sa.SmallInteger(), nullable=False),
    sa.Column('parsi_year', sa.Integer(), nullable=False),
    sa.Column('calendar_system', sa.String(length=10), nullable=False),
    sa.Column('purpose', sa.String(length=20), nullable=False),
    sa.Column('location', sa.Text(), nullable=True),
    sa.Column('is_offsite', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('status', sa.String(length=20), server_default='requested', nullable=False),
    sa.Column('recurrence_rule_id', sa.BigInteger(), nullable=True),
    sa.Column('is_recurring_instance', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('bulk_batch_id', sa.BigInteger(), nullable=True),
    sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=True),
    sa.Column('payment_status', sa.String(length=20), server_default='pending', nullable=False),
    sa.Column('payment_method', sa.String(length=20), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("payment_method IS NULL OR payment_method IN ('upi', 'cash', 'bank_transfer', 'other')", name=op.f('ck_bookings_payment_method')),
    sa.CheckConstraint("payment_status IN ('pending', 'received', 'refunded')", name=op.f('ck_bookings_payment_status')),
    sa.CheckConstraint("purpose IN ('gujrela_nu', 'khushali_nu', 'hama_anjuman')", name=op.f('ck_bookings_purpose')),
    sa.CheckConstraint("status IN ('requested', 'approved', 'assigned', 'mobed_declined', 'completed', 'cancelled', 'declined', 'rescheduled')", name=op.f('ck_bookings_status')),
    sa.CheckConstraint('parsi_mah BETWEEN 1 AND 13', name=op.f('ck_bookings_parsi_mah')),
    sa.CheckConstraint('parsi_roj BETWEEN 1 AND 30', name=op.f('ck_bookings_parsi_roj')),
    sa.ForeignKeyConstraint(['agyary_id'], ['agyaries.id'], name=op.f('fk_bookings_agyary_id_agyaries')),
    sa.ForeignKeyConstraint(['bulk_batch_id'], ['bulk_batches.id'], name=op.f('fk_bookings_bulk_batch_id_bulk_batches')),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('fk_bookings_customer_id_customers')),
    sa.ForeignKeyConstraint(['service_id'], ['services.id'], name=op.f('fk_bookings_service_id_services')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_bookings'))
    )
    op.create_index('idx_bookings_agyary_ceremony_datetime', 'bookings', ['agyary_id', 'ceremony_datetime'], unique=False)
    op.create_index('idx_bookings_agyary_date', 'bookings', ['agyary_id', 'date_time'], unique=False)
    op.create_index('idx_bookings_bulk', 'bookings', ['bulk_batch_id'], unique=False, postgresql_where=sa.text('bulk_batch_id IS NOT NULL'))
    op.create_index('idx_bookings_customer', 'bookings', ['customer_id', sa.literal_column('date_time DESC')], unique=False)
    op.create_index('idx_bookings_pending', 'bookings', ['agyary_id', 'status'], unique=False, postgresql_where=sa.text("status = 'requested'"))
    op.create_index('idx_bookings_recurrence', 'bookings', ['recurrence_rule_id'], unique=False, postgresql_where=sa.text('recurrence_rule_id IS NOT NULL'))
    op.create_index('idx_bookings_service', 'bookings', ['service_id', 'date_time'], unique=False)
    op.create_table('machis',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('agyary_id', sa.BigInteger(), nullable=False),
    sa.Column('customer_id', sa.BigInteger(), nullable=False),
    sa.Column('parsi_roj', sa.SmallInteger(), nullable=False),
    sa.Column('parsi_mah', sa.SmallInteger(), nullable=False),
    sa.Column('parsi_year', sa.Integer(), nullable=False),
    sa.Column('calendar_system', sa.String(length=10), nullable=False),
    sa.Column('geh', sa.SmallInteger(), nullable=False),
    sa.Column('gregorian_date', sa.Date(), nullable=False),
    sa.Column('ceremony_datetime', sa.DateTime(timezone=True), nullable=False),
    sa.Column('purpose', sa.String(length=20), nullable=False),
    sa.Column('assigned_mobed_id', sa.BigInteger(), nullable=True),
    sa.Column('status', sa.String(length=20), server_default='requested', nullable=False),
    sa.Column('recurrence_rule_id', sa.BigInteger(), nullable=True),
    sa.Column('is_recurring_instance', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('bulk_batch_id', sa.BigInteger(), nullable=True),
    sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=True),
    sa.Column('payment_status', sa.String(length=20), server_default='pending', nullable=False),
    sa.Column('payment_method', sa.String(length=20), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('mobed_amount', sa.Numeric(precision=10, scale=2), nullable=True),
    sa.Column('mobed_paid', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('mobed_paid_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("payment_method IS NULL OR payment_method IN ('upi', 'cash', 'bank_transfer', 'other')", name=op.f('ck_machis_payment_method')),
    sa.CheckConstraint("payment_status IN ('pending', 'received', 'refunded')", name=op.f('ck_machis_payment_status')),
    sa.CheckConstraint("purpose IN ('patet', 'tandarosti')", name=op.f('ck_machis_purpose')),
    sa.CheckConstraint("status IN ('requested', 'approved', 'assigned', 'mobed_declined', 'completed', 'cancelled', 'declined', 'rescheduled')", name=op.f('ck_machis_status')),
    sa.CheckConstraint('geh BETWEEN 1 AND 5', name=op.f('ck_machis_geh')),
    sa.CheckConstraint('parsi_mah BETWEEN 1 AND 13', name=op.f('ck_machis_parsi_mah')),
    sa.CheckConstraint('parsi_roj BETWEEN 1 AND 30', name=op.f('ck_machis_parsi_roj')),
    sa.ForeignKeyConstraint(['agyary_id'], ['agyaries.id'], name=op.f('fk_machis_agyary_id_agyaries')),
    sa.ForeignKeyConstraint(['assigned_mobed_id'], ['users.id'], name=op.f('fk_machis_assigned_mobed_id_users')),
    sa.ForeignKeyConstraint(['bulk_batch_id'], ['bulk_batches.id'], name=op.f('fk_machis_bulk_batch_id_bulk_batches')),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('fk_machis_customer_id_customers')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_machis'))
    )
    op.create_index('idx_machis_agyary_ceremony_datetime', 'machis', ['agyary_id', 'ceremony_datetime'], unique=False)
    op.create_index('idx_machis_agyary_date', 'machis', ['agyary_id', 'gregorian_date'], unique=False)
    op.create_index('idx_machis_bulk', 'machis', ['bulk_batch_id'], unique=False, postgresql_where=sa.text('bulk_batch_id IS NOT NULL'))
    op.create_index('idx_machis_customer', 'machis', ['customer_id', sa.literal_column('gregorian_date DESC')], unique=False)
    op.create_index('idx_machis_mobed_date', 'machis', ['assigned_mobed_id', 'gregorian_date'], unique=False, postgresql_where=sa.text('assigned_mobed_id IS NOT NULL'))
    op.create_index('idx_machis_pending', 'machis', ['agyary_id', 'status'], unique=False, postgresql_where=sa.text("status = 'requested'"))
    op.create_index('idx_machis_recurrence', 'machis', ['recurrence_rule_id'], unique=False, postgresql_where=sa.text('recurrence_rule_id IS NOT NULL'))
    op.create_index('uq_machis_slot', 'machis', ['agyary_id', 'parsi_roj', 'parsi_mah', 'parsi_year', 'geh'], unique=True, postgresql_where=sa.text("status NOT IN ('cancelled', 'declined', 'rescheduled')"))
    op.create_table('booking_mobeds',
    sa.Column('booking_id', sa.BigInteger(), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('mobed_role', sa.String(length=30), nullable=True),
    sa.Column('status', sa.String(length=20), server_default='assigned', nullable=False),
    sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=True),
    sa.Column('is_paid', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('assigned', 'accepted', 'declined')", name=op.f('ck_booking_mobeds_status')),
    sa.ForeignKeyConstraint(['booking_id'], ['bookings.id'], name=op.f('fk_booking_mobeds_booking_id_bookings'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_booking_mobeds_user_id_users')),
    sa.PrimaryKeyConstraint('booking_id', 'user_id', name=op.f('pk_booking_mobeds'))
    )
    op.create_index('idx_booking_mobeds_user', 'booking_mobeds', ['user_id'], unique=False)
    op.create_table('ceremony_names',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('machi_id', sa.BigInteger(), nullable=True),
    sa.Column('booking_id', sa.BigInteger(), nullable=True),
    sa.Column('section', sa.String(length=20), nullable=False),
    sa.Column('title', sa.String(length=20), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('status', sa.String(length=10), nullable=False),
    sa.Column('display_order', sa.SmallInteger(), server_default='0', nullable=False),
    sa.Column('pair_group', sa.SmallInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("section IN ('pair', 'farmayeshne')", name=op.f('ck_ceremony_names_section')),
    sa.CheckConstraint("status IN ('living', 'departed')", name=op.f('ck_ceremony_names_status')),
    sa.CheckConstraint("title IN ('khud', 'osta', 'osti', 'ervad', 'behdin')", name=op.f('ck_ceremony_names_title')),
    sa.CheckConstraint('num_nonnulls(machi_id, booking_id) = 1', name=op.f('ck_ceremony_names_exactly_one_parent')),
    sa.ForeignKeyConstraint(['booking_id'], ['bookings.id'], name=op.f('fk_ceremony_names_booking_id_bookings'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['machi_id'], ['machis.id'], name=op.f('fk_ceremony_names_machi_id_machis'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ceremony_names'))
    )
    op.create_index('idx_ceremony_names_booking', 'ceremony_names', ['booking_id'], unique=False, postgresql_where=sa.text('booking_id IS NOT NULL'))
    op.create_index('idx_ceremony_names_machi', 'ceremony_names', ['machi_id'], unique=False, postgresql_where=sa.text('machi_id IS NOT NULL'))
    op.create_table('notifications',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('agyary_id', sa.BigInteger(), nullable=False),
    sa.Column('recipient_phone', sa.String(length=20), nullable=False),
    sa.Column('recipient_type', sa.String(length=10), nullable=False),
    sa.Column('recipient_id', sa.BigInteger(), nullable=False),
    sa.Column('notification_type', sa.String(length=50), nullable=False),
    sa.Column('template_name', sa.String(length=100), nullable=False),
    sa.Column('template_params', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('machi_id', sa.BigInteger(), nullable=True),
    sa.Column('booking_id', sa.BigInteger(), nullable=True),
    sa.Column('scheduled_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('status', sa.String(length=20), server_default='pending', nullable=False),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('wa_message_id', sa.String(length=100), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('retry_count', sa.SmallInteger(), server_default='0', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("recipient_type IN ('user', 'customer')", name=op.f('ck_notifications_recipient_type')),
    sa.CheckConstraint("status IN ('pending', 'queued', 'sent', 'delivered', 'read', 'failed')", name=op.f('ck_notifications_status')),
    sa.ForeignKeyConstraint(['agyary_id'], ['agyaries.id'], name=op.f('fk_notifications_agyary_id_agyaries')),
    sa.ForeignKeyConstraint(['booking_id'], ['bookings.id'], name=op.f('fk_notifications_booking_id_bookings')),
    sa.ForeignKeyConstraint(['machi_id'], ['machis.id'], name=op.f('fk_notifications_machi_id_machis')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_notifications'))
    )
    op.create_index('idx_notifications_agyary', 'notifications', ['agyary_id', sa.literal_column('created_at DESC')], unique=False)
    op.create_index('idx_notifications_queue', 'notifications', ['scheduled_at', 'status'], unique=False, postgresql_where=sa.text("status = 'pending'"))
    op.create_index('idx_notifications_wa_message', 'notifications', ['wa_message_id'], unique=False, postgresql_where=sa.text('wa_message_id IS NOT NULL'))
    op.create_table('payments',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('agyary_id', sa.BigInteger(), nullable=False),
    sa.Column('customer_id', sa.BigInteger(), nullable=False),
    sa.Column('machi_id', sa.BigInteger(), nullable=True),
    sa.Column('booking_id', sa.BigInteger(), nullable=True),
    sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=False),
    sa.Column('method', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), server_default='pending', nullable=False),
    sa.Column('upi_intent_link', sa.Text(), nullable=True),
    sa.Column('upi_transaction_ref', sa.String(length=100), nullable=True),
    sa.Column('received_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('received_by', sa.BigInteger(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("method IN ('upi', 'cash', 'bank_transfer', 'other')", name=op.f('ck_payments_method')),
    sa.CheckConstraint("status IN ('pending', 'received', 'refunded')", name=op.f('ck_payments_status')),
    sa.CheckConstraint('num_nonnulls(machi_id, booking_id) = 1', name=op.f('ck_payments_exactly_one_parent')),
    sa.ForeignKeyConstraint(['agyary_id'], ['agyaries.id'], name=op.f('fk_payments_agyary_id_agyaries')),
    sa.ForeignKeyConstraint(['booking_id'], ['bookings.id'], name=op.f('fk_payments_booking_id_bookings')),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('fk_payments_customer_id_customers')),
    sa.ForeignKeyConstraint(['machi_id'], ['machis.id'], name=op.f('fk_payments_machi_id_machis')),
    sa.ForeignKeyConstraint(['received_by'], ['users.id'], name=op.f('fk_payments_received_by_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_payments'))
    )
    op.create_index('idx_payments_agyary_status', 'payments', ['agyary_id', 'status'], unique=False)
    op.create_index('idx_payments_booking', 'payments', ['booking_id'], unique=False, postgresql_where=sa.text('booking_id IS NOT NULL'))
    op.create_index('idx_payments_customer', 'payments', ['customer_id'], unique=False)
    op.create_index('idx_payments_date', 'payments', ['agyary_id', 'created_at'], unique=False)
    op.create_index('idx_payments_machi', 'payments', ['machi_id'], unique=False, postgresql_where=sa.text('machi_id IS NOT NULL'))

    # Circular FKs between recurrence_rules and machis/bookings must be added
    # after all three tables exist (op.create_table ignores use_alter FKs).
    op.create_foreign_key('fk_machis_recurrence_rule', 'machis', 'recurrence_rules', ['recurrence_rule_id'], ['id'])
    op.create_foreign_key('fk_bookings_recurrence_rule', 'bookings', 'recurrence_rules', ['recurrence_rule_id'], ['id'])
    op.create_foreign_key('fk_recurrence_rules_source_machi', 'recurrence_rules', 'machis', ['source_machi_id'], ['id'])
    op.create_foreign_key('fk_recurrence_rules_source_booking', 'recurrence_rules', 'bookings', ['source_booking_id'], ['id'])
    # ### end Alembic commands ###


def downgrade() -> None:
    # Drop the circular FKs first so the tables can be dropped in order.
    op.drop_constraint('fk_recurrence_rules_source_booking', 'recurrence_rules', type_='foreignkey')
    op.drop_constraint('fk_recurrence_rules_source_machi', 'recurrence_rules', type_='foreignkey')
    op.drop_constraint('fk_bookings_recurrence_rule', 'bookings', type_='foreignkey')
    op.drop_constraint('fk_machis_recurrence_rule', 'machis', type_='foreignkey')
    op.drop_index('idx_payments_machi', table_name='payments', postgresql_where=sa.text('machi_id IS NOT NULL'))
    op.drop_index('idx_payments_date', table_name='payments')
    op.drop_index('idx_payments_customer', table_name='payments')
    op.drop_index('idx_payments_booking', table_name='payments', postgresql_where=sa.text('booking_id IS NOT NULL'))
    op.drop_index('idx_payments_agyary_status', table_name='payments')
    op.drop_table('payments')
    op.drop_index('idx_notifications_wa_message', table_name='notifications', postgresql_where=sa.text('wa_message_id IS NOT NULL'))
    op.drop_index('idx_notifications_queue', table_name='notifications', postgresql_where=sa.text("status = 'pending'"))
    op.drop_index('idx_notifications_agyary', table_name='notifications')
    op.drop_table('notifications')
    op.drop_index('idx_ceremony_names_machi', table_name='ceremony_names', postgresql_where=sa.text('machi_id IS NOT NULL'))
    op.drop_index('idx_ceremony_names_booking', table_name='ceremony_names', postgresql_where=sa.text('booking_id IS NOT NULL'))
    op.drop_table('ceremony_names')
    op.drop_index('idx_booking_mobeds_user', table_name='booking_mobeds')
    op.drop_table('booking_mobeds')
    op.drop_index('uq_machis_slot', table_name='machis', postgresql_where=sa.text("status NOT IN ('cancelled', 'declined', 'rescheduled')"))
    op.drop_index('idx_machis_recurrence', table_name='machis', postgresql_where=sa.text('recurrence_rule_id IS NOT NULL'))
    op.drop_index('idx_machis_pending', table_name='machis', postgresql_where=sa.text("status = 'requested'"))
    op.drop_index('idx_machis_mobed_date', table_name='machis', postgresql_where=sa.text('assigned_mobed_id IS NOT NULL'))
    op.drop_index('idx_machis_customer', table_name='machis')
    op.drop_index('idx_machis_bulk', table_name='machis', postgresql_where=sa.text('bulk_batch_id IS NOT NULL'))
    op.drop_index('idx_machis_agyary_date', table_name='machis')
    op.drop_index('idx_machis_agyary_ceremony_datetime', table_name='machis')
    op.drop_table('machis')
    op.drop_index('idx_bookings_service', table_name='bookings')
    op.drop_index('idx_bookings_recurrence', table_name='bookings', postgresql_where=sa.text('recurrence_rule_id IS NOT NULL'))
    op.drop_index('idx_bookings_pending', table_name='bookings', postgresql_where=sa.text("status = 'requested'"))
    op.drop_index('idx_bookings_customer', table_name='bookings')
    op.drop_index('idx_bookings_bulk', table_name='bookings', postgresql_where=sa.text('bulk_batch_id IS NOT NULL'))
    op.drop_index('idx_bookings_agyary_date', table_name='bookings')
    op.drop_index('idx_bookings_agyary_ceremony_datetime', table_name='bookings')
    op.drop_table('bookings')
    op.drop_index('idx_bulk_batches_agyary_date', table_name='bulk_batches')
    op.drop_table('bulk_batches')
    op.drop_index('idx_wa_messages_wa_id', table_name='whatsapp_messages', postgresql_where=sa.text('wa_message_id IS NOT NULL'))
    op.drop_index('idx_wa_messages_agyary_phone', table_name='whatsapp_messages')
    op.drop_table('whatsapp_messages')
    op.drop_table('services')
    op.drop_index('idx_recurrence_active', table_name='recurrence_rules', postgresql_where=sa.text('is_active = true'))
    op.drop_table('recurrence_rules')
    op.drop_index('idx_customer_saved_names_customer', table_name='customer_saved_names')
    op.drop_table('customer_saved_names')
    op.drop_index('idx_conversation_states_expiry', table_name='conversation_states')
    op.drop_table('conversation_states')
    op.drop_index('idx_agyary_users_user', table_name='agyary_users')
    op.drop_table('agyary_users')
    op.drop_index('idx_agyary_customers_customer', table_name='agyary_customers')
    op.drop_table('agyary_customers')
    op.drop_table('users')
    op.drop_index('idx_customers_name_trgm', table_name='customers', postgresql_using='gin', postgresql_ops={'name': 'gin_trgm_ops'})
    op.drop_table('customers')
    op.drop_table('auth_otps')
    op.drop_index('uq_agyaries_wa_phone_number_id', table_name='agyaries', postgresql_where=sa.text('wa_phone_number_id IS NOT NULL'))
    op.drop_index('idx_agyaries_city', table_name='agyaries')
    op.drop_table('agyaries')
    # ### end Alembic commands ###
