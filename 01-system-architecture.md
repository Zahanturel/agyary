# Agyary System Architecture - Document 1: Database & Infrastructure

## Multi-Tenancy Model

Shared-schema, single-database. Every row that belongs to a tenant carries `agyary_id`. No schema-per-tenant, no database-per-tenant. At 5 agyaries today and 100 tomorrow, this is the right call. Schema-per-tenant buys you isolation you don't need and costs you migration hell you can't afford.

WhatsApp enforces the tenancy boundary naturally. One WABA, multiple phone numbers, one per agyary. All webhooks hit the same endpoint. The backend reads `phone_number_id` from the webhook payload and resolves to `agyary_id` in one indexed lookup. Every downstream query is scoped by that `agyary_id`.

No RLS (Row-Level Security) for now. The API layer enforces tenant scoping. RLS is worth adding once you have third-party integrations or direct DB access from multiple services, neither of which is on the roadmap.

---

## Complete Postgres Schema

### Extension

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;  -- fuzzy name search
```

---

### 1. agyaries

The tenant table. Everything flows from here.

```sql
CREATE TABLE agyaries (
    id              BIGSERIAL PRIMARY KEY,
    name            VARCHAR(200)  NOT NULL,
    city            VARCHAR(100)  NOT NULL,
    address         TEXT,
    calendar_system VARCHAR(10)   NOT NULL DEFAULT 'shenshai'
                    CHECK (calendar_system IN ('shenshai', 'kadmi', 'fasli')),
    contact_phone   VARCHAR(20),

    -- WhatsApp Cloud API identifiers
    wa_phone_number    VARCHAR(20),   -- E.164 format (+919876543210)
    wa_phone_number_id VARCHAR(50),   -- Meta's internal phone_number_id, used for API calls
    wa_display_name    VARCHAR(100),  -- business profile display name

    -- Payment
    upi_id          VARCHAR(100),     -- agyary's UPI VPA for payment link generation

    -- QR
    qr_code_url     TEXT,             -- wa.me deep link or hosted QR image URL

    -- Operational
    max_machis_per_geh SMALLINT NOT NULL DEFAULT 1,

    is_active       BOOLEAN    NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX uq_agyaries_wa_phone_number_id
    ON agyaries (wa_phone_number_id) WHERE wa_phone_number_id IS NOT NULL;

CREATE INDEX idx_agyaries_city ON agyaries (city);
```

**Why `max_machis_per_geh` is configurable**: the handoff says hard limit of 1, and every agyary in the survey confirms this. But storing it as a column (default 1) costs nothing and avoids a code change if an Atash Behram ever runs two simultaneous machis during peak muktad. The unique constraint on machis enforces it at the DB level regardless.

---

### 2. users

Operators: panthakys, mobeds, caretakers. Anyone who logs into the PWA or receives assignment notifications.

```sql
CREATE TABLE users (
    id          BIGSERIAL PRIMARY KEY,
    name        VARCHAR(200)  NOT NULL,
    phone       VARCHAR(20)   NOT NULL UNIQUE,  -- E.164, doubles as WhatsApp ID
    is_active   BOOLEAN       NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE INDEX idx_users_phone ON users (phone);
```

**Why `phone` is UNIQUE globally**: a mobed's phone number identifies them across all agyaries. Percy Kias works at Cama Baugh and Banaji Limji but has one phone number. The junction table handles the many-to-many.

**Why no `role` column here**: role is per-agyary. A priest could theoretically be the panthaky at one small agyary and a regular mobed at another. Role lives on `agyary_users`.

---

### 3. agyary_users

Junction table. Defines who works where and in what capacity.

```sql
CREATE TABLE agyary_users (
    agyary_id   BIGINT      NOT NULL REFERENCES agyaries(id),
    user_id     BIGINT      NOT NULL REFERENCES users(id),
    role        VARCHAR(20) NOT NULL CHECK (role IN ('panthaky', 'mobed', 'caretaker')),
    is_active   BOOLEAN     NOT NULL DEFAULT true,
    joined_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (agyary_id, user_id)
);

CREATE INDEX idx_agyary_users_user ON agyary_users (user_id);
```

**Access control mapping**: panthaky and caretaker get admin permissions in the PWA (approve bookings, assign mobeds, view payments). Mobed gets read-only calendar + accept/decline assignments. This is enforced in the API layer, not the DB.

---

### 4. customers

Behdins. They never see the PWA, only interact via WhatsApp.

```sql
CREATE TABLE customers (
    id          BIGSERIAL PRIMARY KEY,
    name        VARCHAR(200)  NOT NULL,
    phone       VARCHAR(20)   NOT NULL UNIQUE,  -- E.164
    is_active   BOOLEAN       NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE INDEX idx_customers_phone ON customers (phone);
CREATE INDEX idx_customers_name_trgm ON customers USING gin (name gin_trgm_ops);
```

**Why separate from `users`**: different entity, different permissions, different interaction model. A mobed's mother might book machis (customer) at the same agyary where he's assigned (user). Same phone number appearing in both tables is fine since uniqueness is per-table. The alternative (single `people` table with role flags) creates messy permission logic and pollutes both query paths.

---

### 5. agyary_customers

Junction. Created automatically on first booking. Tracks the relationship between a family and their agyary(ies).

```sql
CREATE TABLE agyary_customers (
    agyary_id       BIGINT      NOT NULL REFERENCES agyaries(id),
    customer_id     BIGINT      NOT NULL REFERENCES customers(id),
    first_booking_at TIMESTAMPTZ,
    notes           TEXT,
    is_active       BOOLEAN     NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (agyary_id, customer_id)
);

CREATE INDEX idx_agyary_customers_customer ON agyary_customers (customer_id);
```

---

### 6. services

Per-agyary service catalog. Seeded from a standard list on onboarding, then customizable.

```sql
CREATE TABLE services (
    id                  BIGSERIAL PRIMARY KEY,
    agyary_id           BIGINT       NOT NULL REFERENCES agyaries(id),
    name                VARCHAR(100) NOT NULL,
    default_price       NUMERIC(10,2),
    min_mobeds          SMALLINT     NOT NULL DEFAULT 1,
    typical_duration_minutes INTEGER,
    offsite_capable     BOOLEAN      NOT NULL DEFAULT false,
    is_active           BOOLEAN      NOT NULL DEFAULT true,
    display_order       SMALLINT     NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE (agyary_id, name)
);
```

**Seed list** (created for each new agyary):

| name | min_mobeds | offsite_capable | notes |
|---|---|---|---|
| Machi | 1 | false | slot-based, handled by `machis` table not `bookings` |
| Jashan | 1 | true | at homes, offices, new cars |
| Afringan | 1 | true | inner prayers, bulk-ceremony candidate |
| Farokshi | 1 | true | |
| Satum | 1 | false | |
| Navjote | 1 | true | |
| Wedding | 1 | true | |
| Vandidad | 1 | false | overnight, inside temple |
| Yazeshni | 2 | false | Jyoti + Rathvi, hours long, inside temple only |

**Why `min_mobeds` instead of `requires_multiple_mobeds` boolean**: yazeshni needs exactly 2 (Jyoti + Rathvi). Other complex ceremonies might need 3+. An integer is more expressive and the API just checks `assigned_count >= service.min_mobeds` before confirming.

**Why `Machi` is in the services table even though machis have their own table**: the service record holds pricing/config metadata. The `machis` table holds the actual slot-based bookings. When a customer selects "Machi" via WhatsApp, the bot looks up the service for display info and pricing, then creates a row in `machis` (not `bookings`).

---

### 7. machis

The core table. Slot-based: one machi per geh per day per agyary. This is what 80% of the system is about.

```sql
CREATE TABLE machis (
    id                  BIGSERIAL PRIMARY KEY,
    agyary_id           BIGINT      NOT NULL REFERENCES agyaries(id),
    customer_id         BIGINT      NOT NULL REFERENCES customers(id),

    -- Parsi date (source of truth for the slot)
    parsi_roj           SMALLINT    NOT NULL,  -- 1-30 regular, 1-5 Gatha (mah=13), 1-6 Fasli leap
    parsi_mah           SMALLINT    NOT NULL,  -- 1-12 regular months, 13 = Gatha days
    parsi_year          INTEGER     NOT NULL,
    calendar_system     VARCHAR(10) NOT NULL,  -- inherited from agyary, stored for safety
    geh                 SMALLINT    NOT NULL CHECK (geh BETWEEN 1 AND 5),
                        -- 1=Havan, 2=Rapithwin, 3=Ujiran, 4=Aiwisruthrem, 5=Ushahin

    -- Gregorian mirror (for indexing, calendar UI, range queries)
    gregorian_date      DATE        NOT NULL,

    -- Assignment
    assigned_mobed_id   BIGINT      REFERENCES users(id),

    -- Status
    status              VARCHAR(20) NOT NULL DEFAULT 'requested'
                        CHECK (status IN (
                            'requested',   -- customer submitted, awaiting panthaky approval
                            'approved',    -- panthaky approved, slot locked
                            'declined',    -- panthaky declined
                            'completed',   -- ceremony performed
                            'cancelled'    -- customer or panthaky cancelled
                        )),

    -- Recurrence
    recurrence_rule_id  BIGINT      REFERENCES recurrence_rules(id),
    is_recurring_instance BOOLEAN   NOT NULL DEFAULT false,

    -- Bulk
    bulk_batch_id       BIGINT      REFERENCES bulk_batches(id),

    -- Payment (denormalized from payments table for calendar view)
    amount              NUMERIC(10,2),
    payment_status      VARCHAR(20) NOT NULL DEFAULT 'pending'
                        CHECK (payment_status IN ('pending', 'received', 'refunded')),
    payment_method      VARCHAR(20)
                        CHECK (payment_method IS NULL OR
                               payment_method IN ('upi', 'cash', 'bank_transfer', 'other')),
    notes               TEXT,

    -- Mobed earnings
    mobed_amount        NUMERIC(10,2),
    mobed_paid          BOOLEAN     NOT NULL DEFAULT false,
    mobed_paid_at       TIMESTAMPTZ,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- THE critical constraint: one machi per geh per day per agyary
-- Partial index excludes cancelled/declined so those slots can be re-booked
CREATE UNIQUE INDEX uq_machis_slot
    ON machis (agyary_id, parsi_roj, parsi_mah, parsi_year, geh)
    WHERE status NOT IN ('cancelled', 'declined');

-- Day view: "show me all machis for this Gregorian date at this agyary"
CREATE INDEX idx_machis_agyary_date
    ON machis (agyary_id, gregorian_date);

-- Mobed schedule: "show me all my machis this week"
CREATE INDEX idx_machis_mobed_date
    ON machis (assigned_mobed_id, gregorian_date)
    WHERE assigned_mobed_id IS NOT NULL;

-- Pending approvals: "show me all machis waiting for approval"
CREATE INDEX idx_machis_pending
    ON machis (agyary_id, status)
    WHERE status = 'requested';

-- Customer history
CREATE INDEX idx_machis_customer
    ON machis (customer_id, gregorian_date DESC);

-- Recurrence lookups
CREATE INDEX idx_machis_recurrence
    ON machis (recurrence_rule_id)
    WHERE recurrence_rule_id IS NOT NULL;

-- Bulk batch lookups
CREATE INDEX idx_machis_bulk
    ON machis (bulk_batch_id)
    WHERE bulk_batch_id IS NOT NULL;
```

**Why Parsi date components are stored as separate columns, not a composite type or JSONB**: you need to query "all machis on Roj Bahman across all months" (for recurring patterns) or "all machis in Mah Fravardin" (for monthly reports). Separate columns give you direct indexability. The Gregorian mirror is denormalized for calendar UI range queries.

**Why `calendar_system` is stored on each machi even though it's on the agyary**: if an agyary ever switches calendar systems (unlikely but possible during onboarding corrections), historical machis need to retain their original calendar context. Costs one varchar per row, prevents a class of subtle bugs.

**Why the slot uniqueness is a partial unique index**: when a customer cancels, the slot should open up immediately. A regular UNIQUE constraint would prevent re-booking cancelled slots. The partial index (`WHERE status NOT IN ('cancelled', 'declined')`) lets cancelled slots be re-used while still preventing double-booking of active slots.

---

### 8. bookings

All non-machi services. Time-based, not slot-based. Jashans, navjotes, weddings, afringans, etc.

```sql
CREATE TABLE bookings (
    id                  BIGSERIAL PRIMARY KEY,
    agyary_id           BIGINT      NOT NULL REFERENCES agyaries(id),
    service_id          BIGINT      NOT NULL REFERENCES services(id),
    customer_id         BIGINT      NOT NULL REFERENCES customers(id),

    -- Time (Gregorian is primary for time-based events)
    date_time           TIMESTAMPTZ NOT NULL,
    end_time            TIMESTAMPTZ,  -- estimated end, derived from service.typical_duration_minutes

    -- Parsi date (stored alongside for display)
    parsi_roj           SMALLINT    NOT NULL,
    parsi_mah           SMALLINT    NOT NULL,
    parsi_year          INTEGER     NOT NULL,
    calendar_system     VARCHAR(10) NOT NULL,

    -- Location (for offsite services like jashans at someone's home)
    location            TEXT,
    is_offsite          BOOLEAN     NOT NULL DEFAULT false,

    -- Status (same state machine as machis)
    status              VARCHAR(20) NOT NULL DEFAULT 'requested'
                        CHECK (status IN (
                            'requested', 'approved', 'declined', 'completed', 'cancelled'
                        )),

    -- Recurrence
    recurrence_rule_id  BIGINT      REFERENCES recurrence_rules(id),
    is_recurring_instance BOOLEAN   NOT NULL DEFAULT false,

    -- Bulk
    bulk_batch_id       BIGINT      REFERENCES bulk_batches(id),

    -- Payment (denormalized from payments table for calendar view)
    amount              NUMERIC(10,2),
    payment_status      VARCHAR(20) NOT NULL DEFAULT 'pending'
                        CHECK (payment_status IN ('pending', 'received', 'refunded')),
    payment_method      VARCHAR(20)
                        CHECK (payment_method IS NULL OR
                               payment_method IN ('upi', 'cash', 'bank_transfer', 'other')),
    notes               TEXT,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_bookings_agyary_date
    ON bookings (agyary_id, date_time);

CREATE INDEX idx_bookings_pending
    ON bookings (agyary_id, status)
    WHERE status = 'requested';

CREATE INDEX idx_bookings_customer
    ON bookings (customer_id, date_time DESC);

CREATE INDEX idx_bookings_service
    ON bookings (service_id, date_time);

CREATE INDEX idx_bookings_recurrence
    ON bookings (recurrence_rule_id)
    WHERE recurrence_rule_id IS NOT NULL;

CREATE INDEX idx_bookings_bulk
    ON bookings (bulk_batch_id)
    WHERE bulk_batch_id IS NOT NULL;
```

**Why bookings don't have a slot constraint**: services like jashans and navjotes don't have the 1-per-geh limit. Two navjotes can happen at the same agyary on the same day. Conflict detection (mobed double-booking) is handled in the application layer by checking `booking_mobeds` for time overlaps.

**Why `date_time` is TIMESTAMPTZ and not DATE + TIME**: TIMESTAMPTZ handles timezone correctly. All times stored in UTC, converted to IST at the API boundary. Since all agyaries are in India, IST is the only timezone, but storing UTC is still the correct practice.

---

### 9. booking_mobeds

Junction for assigning mobeds to bookings. Yazeshni needs 2 (Jyoti + Rathvi). Supports mobed earnings tracking per assignment.

```sql
CREATE TABLE booking_mobeds (
    booking_id  BIGINT      NOT NULL REFERENCES bookings(id) ON DELETE CASCADE,
    user_id     BIGINT      NOT NULL REFERENCES users(id),
    mobed_role  VARCHAR(30),         -- 'jyoti', 'rathvi' for yazeshni; NULL for single-mobed services
    status      VARCHAR(20) NOT NULL DEFAULT 'assigned'
                CHECK (status IN ('assigned', 'accepted', 'declined')),
    amount      NUMERIC(10,2),       -- this mobed's earning for this booking
    is_paid     BOOLEAN     NOT NULL DEFAULT false,
    paid_at     TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (booking_id, user_id)
);

CREATE INDEX idx_booking_mobeds_user
    ON booking_mobeds (user_id);
```

**Why machis don't use this table**: machis have a single `assigned_mobed_id` FK. A machi is always one priest. Adding a junction table for a guaranteed 1:1 relationship is wasted complexity. Bookings use the junction because yazeshni, group vandidads, etc. genuinely need multiple mobeds with distinct roles.

---

### 10. ceremony_names

Names recited during prayers. Linked to either a machi or a booking. This is the data that goes on the thermal printer slip.

```sql
CREATE TABLE ceremony_names (
    id              BIGSERIAL PRIMARY KEY,

    -- Polymorphic link: exactly one must be set
    machi_id        BIGINT      REFERENCES machis(id) ON DELETE CASCADE,
    booking_id      BIGINT      REFERENCES bookings(id) ON DELETE CASCADE,
    CHECK (num_nonnulls(machi_id, booking_id) = 1),

    -- Name data
    title           VARCHAR(20) NOT NULL
                    CHECK (title IN ('khud', 'osta', 'osti', 'ervad', 'behdin')),
                    -- khud = child before navjote
                    -- osta = boy after navjote
                    -- osti = girl after navjote
                    -- ervad = ordained priest
                    -- behdin = adult (man or woman)
    name            VARCHAR(200) NOT NULL,
    is_departed     BOOLEAN     NOT NULL DEFAULT false,

    -- Ordering and pairing
    display_order   SMALLINT    NOT NULL DEFAULT 0,
    pair_group      SMALLINT,   -- departed names grouped in pairs; NULL for living names

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_ceremony_names_machi
    ON ceremony_names (machi_id) WHERE machi_id IS NOT NULL;

CREATE INDEX idx_ceremony_names_booking
    ON ceremony_names (booking_id) WHERE booking_id IS NOT NULL;
```

**Why polymorphic with dual nullable FKs instead of `ceremony_type` + `ceremony_id`**: real foreign key constraints. With the `ceremony_type`/`ceremony_id` pattern, Postgres can't enforce referential integrity. With dual nullable FKs + `CHECK (num_nonnulls(...) = 1)`, you get actual FK constraints, cascading deletes, and the DB won't let you point to a non-existent ceremony.

**Why `pair_group`**: departed names are recited in pairs (father-grandfather, mother-father). Names sharing the same `pair_group` integer are printed together on the slip, separated by a comma. Living names have `pair_group = NULL`. The exact pairing rules are pending confirmation from the Dasturji (open item in handoff), but the schema supports whatever pairing logic gets decided.

**Title enum meanings**: these are traditional Zoroastrian honorifics that appear before the name on the prayer slip. The title determines how the name is announced during the ceremony. `khud` is specifically for uninitiated children, `osta`/`osti` for post-navjote youth, `ervad` for ordained priests, `behdin` for general community members.

---

### 11. recurrence_rules

Defines how a booking or machi repeats. The system generates future instances automatically based on these rules.

```sql
CREATE TABLE recurrence_rules (
    id              BIGSERIAL PRIMARY KEY,
    agyary_id       BIGINT      NOT NULL REFERENCES agyaries(id),

    -- Source ceremony (the original that spawns recurrences)
    source_machi_id  BIGINT     REFERENCES machis(id),
    source_booking_id BIGINT    REFERENCES bookings(id),
    CHECK (num_nonnulls(source_machi_id, source_booking_id) = 1),

    -- Pattern
    pattern         VARCHAR(30) NOT NULL
                    CHECK (pattern IN (
                        'same_roj_every_mah',       -- e.g., Roj Bahman every month
                        'same_roj_mah_every_year',  -- annual anniversary
                        'custom'                     -- for anything else, details in pattern_data
                    )),
    pattern_data    JSONB,      -- custom pattern details if needed

    -- Duration
    end_type        VARCHAR(20) NOT NULL DEFAULT 'indefinite'
                    CHECK (end_type IN ('indefinite', 'after_count', 'until_date')),
    end_count       INTEGER,    -- if end_type = 'after_count'
    end_date        DATE,       -- if end_type = 'until_date'

    -- Generation tracking
    last_generated_until DATE,  -- how far ahead instances have been generated
    generation_horizon_months SMALLINT NOT NULL DEFAULT 3,

    -- Approval
    approved_by     BIGINT      REFERENCES users(id),
    approved_at     TIMESTAMPTZ,

    is_active       BOOLEAN     NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_recurrence_active
    ON recurrence_rules (agyary_id, is_active)
    WHERE is_active = true;
```

**How recurrence generation works**: a background job runs daily. For each active rule, it generates instances up to `generation_horizon_months` ahead (default 3 months). Generated machis/bookings get `recurrence_rule_id` set and `is_recurring_instance = true`. The panthakygets a notification for each generated instance (informational, not approval, since the rule itself was already approved). Individual instances can be cancelled or rescheduled without affecting the rule.

**Why `same_roj_every_mah` is the most important pattern**: a family that does a monthly satum for a departed relative always wants it on the same Roj. "Roj Bahman, every Mah" is the natural Parsi way of expressing monthly recurrence. This maps directly to the calendar engine: increment Mah by 1, keep Roj fixed.

---

### 12. bulk_batches

Groups bulk ceremony bookings. The "50 afringans on muktad day" scenario.

```sql
CREATE TABLE bulk_batches (
    id              BIGSERIAL PRIMARY KEY,
    agyary_id       BIGINT      NOT NULL REFERENCES agyaries(id),
    service_id      BIGINT      NOT NULL REFERENCES services(id),

    -- Date
    gregorian_date  DATE        NOT NULL,
    parsi_roj       SMALLINT    NOT NULL,
    parsi_mah       SMALLINT    NOT NULL,
    parsi_year      INTEGER     NOT NULL,
    calendar_system VARCHAR(10) NOT NULL,

    -- Counts
    total_entries   INTEGER     NOT NULL DEFAULT 0,
    completed_count INTEGER     NOT NULL DEFAULT 0,

    -- Status
    status          VARCHAR(20) NOT NULL DEFAULT 'open'
                    CHECK (status IN ('open', 'in_progress', 'completed')),

    created_by      BIGINT      NOT NULL REFERENCES users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_bulk_batches_agyary_date
    ON bulk_batches (agyary_id, gregorian_date);
```

**Why bulk entries are full bookings, not a separate lightweight table**: bulk afringans still need customer tracking, names for the prayer slip, and payment tracking per entry. Making them full `bookings` rows with `bulk_batch_id` set means all existing queries (customer history, payment reports, thermal printing) work without special-casing. The batch table is just a grouping/progress-tracking wrapper. 87 rows in `bookings` is nothing for Postgres.

**Color coding for completion**: the `status` on each individual booking within the batch drives the UI color. Green = completed, default = pending. The `completed_count` on the batch itself is a denormalized counter updated via trigger or application logic, powering the progress bar ("43/87 completed").

---

### 13. payments

Tracks money flow from customer to agyary. NOT a payment gateway. The system generates UPI intent links and records whether payment was received.

```sql
CREATE TABLE payments (
    id                  BIGSERIAL PRIMARY KEY,
    agyary_id           BIGINT      NOT NULL REFERENCES agyaries(id),
    customer_id         BIGINT      NOT NULL REFERENCES customers(id),

    -- What this payment is for (exactly one)
    machi_id            BIGINT      REFERENCES machis(id),
    booking_id          BIGINT      REFERENCES bookings(id),
    CHECK (num_nonnulls(machi_id, booking_id) = 1),

    -- Money
    amount              NUMERIC(10,2) NOT NULL,
    method              VARCHAR(20) NOT NULL
                        CHECK (method IN ('upi', 'cash', 'bank_transfer', 'other')),
    status              VARCHAR(20) NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'received', 'refunded')),

    -- UPI details (when method = 'upi')
    upi_intent_link     TEXT,       -- upi://pay?pa=...&am=...
    upi_transaction_ref VARCHAR(100),

    -- Receipt
    received_at         TIMESTAMPTZ,
    received_by         BIGINT      REFERENCES users(id),  -- who marked it as received

    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_payments_agyary_status
    ON payments (agyary_id, status);

CREATE INDEX idx_payments_customer
    ON payments (customer_id);

CREATE INDEX idx_payments_machi
    ON payments (machi_id) WHERE machi_id IS NOT NULL;

CREATE INDEX idx_payments_booking
    ON payments (booking_id) WHERE booking_id IS NOT NULL;

CREATE INDEX idx_payments_date
    ON payments (agyary_id, created_at);
```

**Why NOT a payment gateway**: RBI PA/PG authorization is required to aggregate payments. This system generates a UPI intent link (`upi://pay?pa={agyary_upi_id}&pn={agyary_name}&am={amount}&cu=INR`) that the customer taps to pay directly to the agyary's own account. The system never touches the money. It just records whether the panthaky confirmed receipt.

**UPI intent link generation**: assembled from `agyaries.upi_id` + `payments.amount`. Sent as a clickable link in the WhatsApp booking confirmation message. Customer taps, UPI app opens pre-filled, customer authenticates and pays. The payment goes directly agyary-to-customer, no intermediary.

---

### 14. notifications

Outbound notification queue. The notification engine reads from this table, sends via WhatsApp Cloud API, and updates status.

```sql
CREATE TABLE notifications (
    id                  BIGSERIAL PRIMARY KEY,
    agyary_id           BIGINT      NOT NULL REFERENCES agyaries(id),

    -- Recipient
    recipient_phone     VARCHAR(20) NOT NULL,
    recipient_type      VARCHAR(10) NOT NULL CHECK (recipient_type IN ('user', 'customer')),
    recipient_id        BIGINT      NOT NULL,

    -- Content
    notification_type   VARCHAR(50) NOT NULL,
    -- Types: booking_request, booking_approved, booking_declined,
    --        mobed_assigned, mobed_accepted, mobed_declined,
    --        reminder_30min, payment_request, recurring_generated,
    --        cancellation, reschedule, bulk_summary
    template_name       VARCHAR(100) NOT NULL,
    template_params     JSONB       NOT NULL DEFAULT '{}',

    -- Reference (nullable, links to the ceremony this notification is about)
    machi_id            BIGINT      REFERENCES machis(id),
    booking_id          BIGINT      REFERENCES bookings(id),

    -- Scheduling
    scheduled_at        TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Delivery status
    status              VARCHAR(20) NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'queued', 'sent', 'delivered', 'read', 'failed')),
    sent_at             TIMESTAMPTZ,
    delivered_at        TIMESTAMPTZ,
    read_at             TIMESTAMPTZ,
    wa_message_id       VARCHAR(100),
    error_message       TEXT,
    retry_count         SMALLINT    NOT NULL DEFAULT 0,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Notification engine picks up pending notifications scheduled for now or earlier
CREATE INDEX idx_notifications_queue
    ON notifications (scheduled_at, status)
    WHERE status = 'pending';

CREATE INDEX idx_notifications_agyary
    ON notifications (agyary_id, created_at DESC);

CREATE INDEX idx_notifications_wa_message
    ON notifications (wa_message_id)
    WHERE wa_message_id IS NOT NULL;
```

**How the 30-minute reminder works**: when a machi is approved, the system creates a notification with `scheduled_at = gregorian_date + geh_start_time - 30 minutes`. The geh-to-time mapping is in application config (Havan starts at sunrise, Rapithwin at noon, etc., but exact times vary by season, so the mapping is approximate). The notification engine runs every minute, picks up notifications where `scheduled_at <= now() AND status = 'pending'`, sends them, and updates status.

**Why `retry_count`**: WhatsApp Cloud API can return transient errors (rate limits, temporary unavailability). The engine retries up to 3 times with exponential backoff. After 3 failures, status goes to `failed` and the panthaky sees it in the PWA dashboard.

---

### 15. whatsapp_messages

Audit log of all WhatsApp traffic. Both inbound (customer messages) and outbound (system messages, notifications). Used for debugging, compliance, and conversation context.

```sql
CREATE TABLE whatsapp_messages (
    id                  BIGSERIAL PRIMARY KEY,
    agyary_id           BIGINT      NOT NULL REFERENCES agyaries(id),
    direction           VARCHAR(10) NOT NULL CHECK (direction IN ('inbound', 'outbound')),

    -- Counterparty (the customer's phone)
    wa_phone            VARCHAR(20) NOT NULL,
    customer_id         BIGINT      REFERENCES customers(id),

    -- Meta API fields
    wa_message_id       VARCHAR(100),
    wa_timestamp        TIMESTAMPTZ,

    -- Content
    message_type        VARCHAR(20) NOT NULL,
    -- Types: text, template, interactive, button_reply, list_reply, image, document
    content             JSONB,              -- raw message payload
    template_name       VARCHAR(100),       -- for outbound templates

    -- Delivery status (outbound only)
    status              VARCHAR(20),        -- sent, delivered, read, failed

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_wa_messages_agyary_phone
    ON whatsapp_messages (agyary_id, wa_phone, created_at DESC);

CREATE INDEX idx_wa_messages_wa_id
    ON whatsapp_messages (wa_message_id)
    WHERE wa_message_id IS NOT NULL;

-- Partition by month once volume grows (not needed at 5 agyaries)
-- CREATE TABLE whatsapp_messages_2026_07 PARTITION OF whatsapp_messages
--     FOR VALUES FROM ('2026-07-01') TO ('2026-08-01');
```

**Why store the raw payload as JSONB**: WhatsApp message formats change. Interactive messages have button payloads, list selections, location data. Rather than modeling every possible message type as columns, store the raw payload and parse in application code. The structured fields (`message_type`, `template_name`, `status`) cover the common query patterns.

---

### 16. conversation_states

Tracks where a customer is in a WhatsApp conversation flow. When a customer is mid-booking (selected service, hasn't picked a date yet), the state lives here.

```sql
CREATE TABLE conversation_states (
    id              BIGSERIAL PRIMARY KEY,
    agyary_id       BIGINT      NOT NULL REFERENCES agyaries(id),
    phone           VARCHAR(20) NOT NULL,

    -- Flow tracking
    flow            VARCHAR(50) NOT NULL,   -- 'machi_booking', 'service_booking', 'cancellation', etc.
    step            VARCHAR(50) NOT NULL,   -- 'select_date', 'select_geh', 'enter_names', 'confirm', etc.
    data            JSONB       NOT NULL DEFAULT '{}',  -- accumulated data during the flow

    -- Expiry (stale conversations auto-expire)
    expires_at      TIMESTAMPTZ NOT NULL,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- One active conversation per customer per agyary
    UNIQUE (agyary_id, phone)
);

CREATE INDEX idx_conversation_states_expiry
    ON conversation_states (expires_at)
    WHERE expires_at < now();
```

**Why Postgres instead of Redis**: at our scale (5-100 agyaries, maybe 50 concurrent conversations at peak), Postgres handles this fine. One less infrastructure dependency. The `UNIQUE (agyary_id, phone)` constraint ensures a customer can only be in one flow at a time. Starting a new flow overwrites the old one (UPSERT). The expiry index lets a cleanup job delete stale states (default TTL: 30 minutes of inactivity).

**Why not just use in-memory state in the FastAPI process**: the server might restart, and conversation state would be lost. A customer who was mid-booking would have to start over. Postgres persistence survives restarts, deploys, and crashes.

---

## Relationship Diagram (textual)

```
agyaries ──────┬── agyary_users ──── users
               │                       │
               ├── agyary_customers    │
               │        │              │
               │   customers           │
               │     │    │            │
               ├── machis ─────────────┤ (assigned_mobed_id)
               │     │                 │
               ├── bookings            │
               │     │    └── booking_mobeds ── users
               │     │
               ├── services
               │
               ├── ceremony_names ←── machis | bookings
               │
               ├── recurrence_rules ←── machis | bookings (source)
               │
               ├── bulk_batches ←── machis | bookings (batch members)
               │
               ├── payments ←── machis | bookings
               │
               ├── notifications
               │
               ├── whatsapp_messages
               │
               └── conversation_states
```

Every table except `users` and `customers` is scoped to an agyary. Users and customers are global entities that participate in multiple agyaries through junction tables.

---

## WhatsApp Cloud API Integration

### Architecture

```
Customer phone
    │
    ▼
Meta WhatsApp Cloud API
    │
    ├── Webhook POST ──▶ https://agyary.example.com/api/webhooks/whatsapp
    │                          │
    │                          ▼
    │                    Webhook Handler
    │                          │
    │                    1. Verify signature (HMAC-SHA256 with app secret)
    │                    2. Extract phone_number_id from payload
    │                    3. Resolve agyary_id via agyaries.wa_phone_number_id
    │                    4. Log to whatsapp_messages
    │                    5. Load conversation_state (if exists)
    │                    6. Route to appropriate flow handler
    │                    7. Flow handler processes, updates state, queues response
    │                          │
    │                          ▼
    └── Send API ◀────── POST /v21.0/{phone_number_id}/messages
                         Authorization: Bearer {system_user_token}
```

### Key Config

| Setting | Value |
|---|---|
| API version | v21.0 (pin version, don't use latest) |
| Webhook verify token | Random 32-char string, stored in env |
| App secret | For webhook signature verification |
| System user token | Long-lived token, never expires unless revoked |
| Business verification | Required for >250 messages/day and template approval |

### Phone Number Registration

Each agyary registers a phone number under the shared WABA:
1. Buy a SIM or use an existing agyary phone number
2. Register via Meta Business Manager > WhatsApp Manager > Phone Numbers
3. Verify via SMS or voice call
4. Store the `phone_number_id` in `agyaries.wa_phone_number_id`
5. Set display name and business profile

Cost: incoming messages are free. Outgoing template messages cost ~30-50 paisa each. User-initiated conversation windows (24h after customer sends a message) allow free-form replies at no cost.

### Template Messages

Templates must be pre-approved by Meta. Submit via Business Manager or API. Required templates for v1:

| Template Name | Category | Purpose |
|---|---|---|
| `booking_confirmation` | UTILITY | "Your {service} at {agyary} is confirmed for {date}, {time/geh}" |
| `booking_request_received` | UTILITY | "We've received your request. You'll hear back shortly." |
| `booking_declined` | UTILITY | "Your request for {date} could not be accommodated. [alternatives]" |
| `mobed_assignment` | UTILITY | "You've been assigned: {service} at {location}, {date}. Accept / Decline" |
| `reminder_30min` | UTILITY | "Reminder: {service} for {customer} in 30 minutes. {names_summary}" |
| `payment_link` | UTILITY | "Payment of Rs.{amount} for {service}: [Pay via UPI] / Pay at agyary" |
| `welcome` | MARKETING | "Welcome to {agyary}. How can we help? [Book Machi] [Book Service] [Contact Us]" |
| `recurring_notification` | UTILITY | "Auto-confirmed: {customer} recurring {service}, {date}" |

Interactive message types used within 24h windows (no template needed):
- Button replies (up to 3 buttons): Approve/Decline, Accept/Decline, Yes/No
- List messages (up to 10 items): service selection, date alternatives, geh selection
- Quick reply buttons: for slot alternatives when requested slot is taken

---

## Cloudflare Tunnel Setup

### Why Cloudflare Tunnel

The production server is a home machine (Beelink SER8 or Mac Mini M4) behind a residential NAT. No static IP. ISP might use CGNAT. Port forwarding is unreliable and insecure. Cloudflare Tunnel solves all of this:

- Runs a lightweight daemon (`cloudflared`) on the server
- Creates an outbound-only encrypted connection to Cloudflare's edge
- Cloudflare terminates SSL, provides DNS, DDoS protection
- No inbound ports open on the home network
- Free tier covers everything we need

### Setup

```
Internet                    Cloudflare Edge              Home Network
                                                         (behind NAT)
                                                              │
Customer ──▶ agyary.example.com ──▶ Cloudflare ◀──tunnel──── cloudflared
                                    │                         │
Meta Webhook ──▶ /api/webhooks/* ──▶│                         ▼
                                    │                    Docker Compose
                                    │                    ┌─────────────┐
                                    │                    │  nginx      │
                                    │                    │  (reverse   │
                                    │                    │   proxy)    │
                                    │                    │     │       │
                                    │                    │  fastapi    │
                                    │                    │     │       │
                                    └────────────────────│  postgres   │
                                                         │  (local)    │
                                                         └─────────────┘
```

### Docker Compose Architecture

```yaml
# Simplified - full docker-compose.yml will be in the repo
services:
  cloudflared:
    image: cloudflare/cloudflared:latest
    command: tunnel run
    environment:
      - TUNNEL_TOKEN=${CLOUDFLARE_TUNNEL_TOKEN}
    restart: unless-stopped

  nginx:
    image: nginx:alpine
    # Reverse proxy: routes /api/* to fastapi, /* to static PWA files
    depends_on: [fastapi]
    restart: unless-stopped

  fastapi:
    build: ./backend
    environment:
      - DATABASE_URL=postgresql+asyncpg://agyary:${DB_PASSWORD}@postgres:5432/agyary
      - WHATSAPP_APP_SECRET=${WA_APP_SECRET}
      - WHATSAPP_VERIFY_TOKEN=${WA_VERIFY_TOKEN}
      - WHATSAPP_SYSTEM_TOKEN=${WA_SYSTEM_TOKEN}
    depends_on: [postgres]
    restart: unless-stopped

  postgres:
    image: postgres:16-alpine
    volumes:
      - pgdata:/var/lib/postgresql/data
    environment:
      - POSTGRES_DB=agyary
      - POSTGRES_USER=agyary
      - POSTGRES_PASSWORD=${DB_PASSWORD}
    restart: unless-stopped

  notification-worker:
    build: ./backend
    command: python -m app.workers.notification_engine
    # Runs the notification queue processor
    depends_on: [postgres]
    restart: unless-stopped

  recurrence-worker:
    build: ./backend
    command: python -m app.workers.recurrence_generator
    # Daily cron: generates recurring booking instances
    depends_on: [postgres]
    restart: unless-stopped

volumes:
  pgdata:
```

### Cloudflare Tunnel Config

```yaml
# ~/.cloudflared/config.yml (on the home server)
tunnel: <tunnel-id>
credentials-file: /root/.cloudflared/<tunnel-id>.json

ingress:
  - hostname: agyary.example.com
    service: http://nginx:80
  - hostname: api.agyary.example.com    # optional subdomain split
    service: http://fastapi:8000
  - service: http_status:404
```

### Reliability

- `cloudflared` auto-reconnects on network drops
- Docker `restart: unless-stopped` handles process crashes
- Cloudflare has automatic failover across their edge PoPs
- For the home server: UPS for power outages, `systemd` watchdog for Docker
- Monitoring: Cloudflare Tunnel dashboard shows connection status; simple healthcheck endpoint for uptime monitoring

---

## Thermal Printer Architecture

### Hardware

Bluetooth thermal receipt printer, 58mm or 80mm paper width. Budget: Rs.2,000-3,000. Connected to the panthaky's phone or a dedicated tablet at the agyary. Example models: any generic ESC/POS Bluetooth printer from Amazon India.

### Connection

```
PWA (on panthaky's phone/tablet)
    │
    ▼
Web Bluetooth API
    │
    ▼
Bluetooth thermal printer
```

The PWA pairs with the printer once via Web Bluetooth. Subsequent prints connect automatically. No server involvement in the actual printing. The server provides the data, the client renders and prints.

### Print Data Flow

```
1. Trigger: auto (30 min before ceremony) or manual (user taps "Print")
2. PWA calls GET /api/agyaries/{id}/machis/{machi_id}/print-data
   or GET /api/agyaries/{id}/bookings/{booking_id}/print-data
3. API returns structured JSON:
   {
     "parsi_date": {"roj": "Bahman", "mah": "Fravardin", "year": 1396},
     "gregorian_date": "2026-07-23",
     "geh": "Havan",
     "service": "Satum",
     "customer": "Patel Family",
     "names": [
       {"title": "Ervad", "name": "Meherzad", "is_departed": false},
       {"title": "Osti", "name": "Farzin", "is_departed": false},
       {"title": "Khud", "name": "Zahan", "is_departed": false}
     ],
     "departed_pairs": [
       [
         {"title": "Ervad", "name": "Zahan"},
         {"title": "Ervad", "name": "Meherzad"}
       ]
     ]
   }
4. PWA renders ESC/POS commands from this data
5. PWA sends to printer via Web Bluetooth
```

### Bulk Printing

For bulk scenarios (50+ afringans):

1. PWA calls `GET /api/agyaries/{id}/bulk-batches/{batch_id}/print-data`
2. API returns array of print data objects, ordered by `display_order`
3. PWA sends to printer sequentially
4. Each slip has a sequence number ("14 of 87") for the mobed to track progress
5. PWA can also print one-at-a-time: mobed taps "Print Next" after each ceremony

### Web Bluetooth Fallback

Web Bluetooth requires HTTPS (handled by Cloudflare) and a Chromium-based browser. If the device doesn't support Web Bluetooth (older phones, iOS Safari before 16.4), the fallback is:

1. Generate a downloadable slip as a small image/PDF
2. User prints via the OS print dialog to a Bluetooth-paired printer
3. Less elegant, but functional

### Auto-Print Trigger

The 30-minute reminder notification (already in the `notifications` table) triggers the PWA to show a "Print slip?" prompt. If the user has auto-print enabled in settings, the PWA prints without prompting. This is a client-side setting stored in the PWA's local storage, not in the database.

---

## Summary: Table Count and Row Estimates (at 10 agyaries, 1 year)

| Table | Estimated Rows/Year | Notes |
|---|---|---|
| agyaries | 10 | static |
| users | ~50 | 5 per agyary avg |
| agyary_users | ~60 | some mobeds at multiple |
| customers | ~2,000 | unique families |
| agyary_customers | ~3,000 | families at multiple |
| services | ~90 | 9 per agyary |
| machis | ~9,000 | 2.5/day x 365 x 10 |
| bookings | ~3,000 | jashans, navjotes, etc. |
| booking_mobeds | ~4,000 | ~1.3 per booking avg |
| ceremony_names | ~50,000 | ~4 names per ceremony |
| recurrence_rules | ~200 | |
| bulk_batches | ~100 | muktad season mostly |
| payments | ~12,000 | one per ceremony |
| notifications | ~50,000 | 4-5 per ceremony lifecycle |
| whatsapp_messages | ~100,000 | both directions |
| conversation_states | ~100 | concurrent, auto-expired |

Total: under 250K rows across all tables after a full year at 10 agyaries. Postgres handles this on a Raspberry Pi. At 100 agyaries it's still under 2.5M rows. No partitioning, no sharding, no read replicas needed for the foreseeable future.
