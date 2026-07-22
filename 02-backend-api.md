# Agyary Backend & API - Document 2

## Schema Updates from Document 1

The state machine refinement adds three new statuses. Update the CHECK constraints on both `machis` and `bookings`:

```sql
-- Replace the status CHECK on machis and bookings
CHECK (status IN (
    'requested',        -- awaiting panthaky approval
    'approved',         -- panthaky approved, no mobed assigned yet
    'assigned',         -- mobed assigned and accepted
    'mobed_declined',   -- mobed declined, needs reassignment
    'completed',        -- ceremony performed
    'cancelled',        -- cancelled by customer or panthaky
    'declined',         -- panthaky declined the request
    'rescheduled'       -- moved to new date, replacement booking created
))
```

Update the partial unique index on machis to exclude `rescheduled`:

```sql
CREATE UNIQUE INDEX uq_machis_slot
    ON machis (agyary_id, parsi_roj, parsi_mah, parsi_year, geh)
    WHERE status NOT IN ('cancelled', 'declined', 'rescheduled');
```

Add configurable reminder timing to `agyary_users`:

```sql
ALTER TABLE agyary_users ADD COLUMN reminder_minutes_before SMALLINT NOT NULL DEFAULT 30;
```

Add auth table:

```sql
CREATE TABLE auth_otps (
    phone       VARCHAR(20)  PRIMARY KEY,
    code_hash   VARCHAR(64)  NOT NULL,   -- SHA-256 of the 6-digit OTP
    expires_at  TIMESTAMPTZ  NOT NULL,
    attempts    SMALLINT     NOT NULL DEFAULT 0,  -- max 3 before lockout
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);
```

---

## Project Structure

```
agyary/
  backend/
    app/
      __init__.py
      main.py                    # FastAPI app, middleware, startup/shutdown
      config.py                  # Pydantic Settings, env vars
      database.py                # async engine, sessionmaker
      dependencies.py            # get_db, get_current_user, get_agyary_context
      models/                    # SQLAlchemy ORM models
        __init__.py
        agyary.py
        user.py
        customer.py
        service.py
        machi.py
        booking.py
        ceremony_name.py
        recurrence.py
        bulk_batch.py
        payment.py
        notification.py
        whatsapp.py
        conversation.py
      schemas/                   # Pydantic request/response schemas
        __init__.py
        auth.py
        agyary.py
        machi.py
        booking.py
        payment.py
        ...
      routers/                   # FastAPI routers (one per domain)
        __init__.py
        auth.py
        agyaries.py
        machis.py
        bookings.py
        services.py
        customers.py
        payments.py
        webhooks.py
        print.py
        recurrence.py
        bulk.py
      services/                  # Business logic layer
        __init__.py
        booking_service.py       # state machine transitions
        whatsapp_service.py      # send messages via Cloud API
        notification_service.py  # create + schedule notifications
        calendar_service.py      # Parsi calendar conversions
        payment_service.py       # UPI link generation
        recurrence_service.py    # generate recurring instances
        print_service.py         # render thermal printer images
      workers/                   # Background processes
        __init__.py
        notification_engine.py   # polls + sends notifications
        recurrence_generator.py  # daily cron for recurring bookings
        cleanup.py               # expire conversation states, old OTPs
      whatsapp/                  # WhatsApp-specific logic
        __init__.py
        handler.py               # webhook message router
        flows/                   # conversation flow handlers
          __init__.py
          welcome.py
          machi_booking.py
          service_booking.py
          my_bookings.py
          cancellation.py
        templates.py             # template name constants + param builders
        signature.py             # HMAC verification
    alembic/                     # migrations
    tests/
    Dockerfile
    pyproject.toml
  frontend/                      # React PWA (Document 3)
  docker-compose.yml
```

---

## Authentication

OTP via WhatsApp. No passwords, no OAuth. Priests don't want another login to remember.

### Flow

```
1. POST /api/auth/request-otp  { phone: "+919876543210" }
   → Generate 6-digit code
   → Hash with SHA-256, store in auth_otps (UPSERT by phone)
   → Send OTP via WhatsApp template message to that phone
   → Return { message: "OTP sent", expires_in: 300 }

2. POST /api/auth/verify-otp  { phone: "+919876543210", code: "482913" }
   → Look up auth_otps by phone
   → Check: not expired, attempts < 3, SHA-256(code) matches code_hash
   → If valid: look up user by phone in users table
   → If user not found: 404 (only registered users can log in, no self-signup)
   → Issue JWT access token (1h) + refresh token (30 days, httpOnly cookie)
   → Return { access_token, user: { id, name, phone, agyaries: [...] } }
   → Delete OTP row

3. POST /api/auth/refresh
   → Read refresh token from httpOnly cookie
   → Validate, issue new access + refresh pair
   → Return { access_token }
```

### JWT Payload

```json
{
  "sub": 42,           // user_id
  "name": "Er. Zahan",
  "iat": 1690000000,
  "exp": 1690003600    // 1 hour
}
```

Agyary context is NOT in the JWT. The user selects an agyary in the PWA, and the `agyary_id` is in the URL path. The API layer checks `agyary_users` to verify the user has access to that agyary before processing any request. This way, switching agyaries doesn't require re-authentication.

### Dependency: `get_current_user`

```python
async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db)
) -> User:
    payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    user = await db.get(User, payload["sub"])
    if not user or not user.is_active:
        raise HTTPException(401)
    return user
```

### Dependency: `get_agyary_context`

```python
async def get_agyary_context(
    agyary_id: int = Path(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> AgyaryContext:
    membership = await db.execute(
        select(AgyaryUser)
        .where(AgyaryUser.agyary_id == agyary_id, AgyaryUser.user_id == user.id, AgyaryUser.is_active == True)
    )
    mem = membership.scalar_one_or_none()
    if not mem:
        raise HTTPException(403, "No access to this agyary")
    return AgyaryContext(agyary_id=agyary_id, user=user, role=mem.role)
```

`role` from the context drives permission checks. Panthaky/caretaker can do everything. Mobed can view calendar and respond to assignments.

---

## API Endpoint Catalog

All endpoints under `/api`. Auth required unless noted. `{a}` = `agyary_id`.

### Auth

| Method | Path | Auth | Body / Params | Response | Notes |
|---|---|---|---|---|---|
| POST | `/auth/request-otp` | None | `{ phone }` | `{ message, expires_in }` | Sends WhatsApp OTP |
| POST | `/auth/verify-otp` | None | `{ phone, code }` | `{ access_token, user }` | Sets refresh cookie |
| POST | `/auth/refresh` | Cookie | - | `{ access_token }` | Refresh token rotation |
| GET | `/auth/me` | JWT | - | `{ id, name, phone, agyaries: [{ id, name, role }] }` | Current user profile |

### Agyaries

| Method | Path | Auth | Body / Params | Response | Notes |
|---|---|---|---|---|---|
| GET | `/agyaries` | JWT | - | `[{ id, name, city, calendar_system }]` | Only agyaries user belongs to |
| GET | `/agyaries/{a}` | JWT+ctx | - | Full agyary object | Includes settings, UPI ID |
| PUT | `/agyaries/{a}` | Admin | `{ name?, city?, calendar_system?, upi_id?, ... }` | Updated agyary | Panthaky/caretaker only |

### Users

| Method | Path | Auth | Body / Params | Response | Notes |
|---|---|---|---|---|---|
| GET | `/agyaries/{a}/users` | JWT+ctx | - | `[{ id, name, phone, role, is_active }]` | All users at this agyary |
| POST | `/agyaries/{a}/users` | Admin | `{ name, phone, role }` | Created user + junction | Creates user if new phone, adds to agyary |
| PUT | `/agyaries/{a}/users/{uid}` | Admin | `{ role?, is_active?, reminder_minutes_before? }` | Updated | Change role or deactivate |
| DELETE | `/agyaries/{a}/users/{uid}` | Admin | - | 204 | Soft delete from agyary (is_active=false) |

### Customers

| Method | Path | Auth | Body / Params | Response | Notes |
|---|---|---|---|---|---|
| GET | `/agyaries/{a}/customers` | JWT+ctx | `?q=patel&page=1&size=20` | Paginated list | Trigram search on name |
| GET | `/agyaries/{a}/customers/{cid}` | JWT+ctx | - | Customer + recent bookings | Last 10 machis + bookings |
| POST | `/agyaries/{a}/customers` | JWT+ctx | `{ name, phone }` | Created customer | Auto-creates agyary_customers junction |
| PUT | `/agyaries/{a}/customers/{cid}` | Admin | `{ name?, phone? }` | Updated | |

### Services

| Method | Path | Auth | Body / Params | Response | Notes |
|---|---|---|---|---|---|
| GET | `/agyaries/{a}/services` | JWT+ctx | - | `[{ id, name, default_price, min_mobeds, ... }]` | Active services only |
| POST | `/agyaries/{a}/services` | Admin | `{ name, default_price, min_mobeds, ... }` | Created service | Custom service |
| PUT | `/agyaries/{a}/services/{sid}` | Admin | `{ default_price?, ... }` | Updated | |
| DELETE | `/agyaries/{a}/services/{sid}` | Admin | - | 204 | Soft delete (is_active=false) |

### Calendar

| Method | Path | Auth | Body / Params | Response | Notes |
|---|---|---|---|---|---|
| GET | `/calendar/today` | None | `?system=shenshai` | `{ roj, mah, year, roj_name, mah_name, gregorian }` | Already built |
| GET | `/calendar/convert` | None | `?date=2026-07-23&system=shenshai` | `{ roj, mah, year, roj_name, mah_name }` | Already built |
| GET | `/calendar/range` | None | `?start=2026-07-01&end=2026-07-31&system=shenshai` | Array of date mappings | For calendar grid rendering |
| GET | `/calendar/geh-times` | None | `?date=2026-07-23` | `{ havan: { start, end }, rapithwin: ... }` | Approximate geh times for a date |

### Machis

| Method | Path | Auth | Body / Params | Response | Notes |
|---|---|---|---|---|---|
| GET | `/agyaries/{a}/machis` | JWT+ctx | `?date=2026-07-23` or `?start=...&end=...` | Array of machis with customer name, geh, status | Day view or range query |
| GET | `/agyaries/{a}/machis/{mid}` | JWT+ctx | - | Full machi with names, payment, mobed | Detail view |
| POST | `/agyaries/{a}/machis` | JWT+ctx | See below | Created machi | Manual entry from PWA |
| PUT | `/agyaries/{a}/machis/{mid}` | Admin | `{ notes?, amount? }` | Updated | Edit metadata |
| POST | `/agyaries/{a}/machis/{mid}/approve` | Admin | `{ mobed_id? }` | Updated machi | Optionally assign mobed inline |
| POST | `/agyaries/{a}/machis/{mid}/decline` | Admin | `{ reason? }` | Updated machi | |
| POST | `/agyaries/{a}/machis/{mid}/assign` | Admin | `{ mobed_id }` | Updated machi | Sends WhatsApp to mobed |
| POST | `/agyaries/{a}/machis/{mid}/complete` | JWT+ctx | - | Updated machi | Mobed or admin |
| POST | `/agyaries/{a}/machis/{mid}/cancel` | JWT+ctx | `{ reason? }` | Updated machi | Frees slot via partial index |
| POST | `/agyaries/{a}/machis/{mid}/reschedule` | Admin | `{ new_roj, new_mah, new_year, new_geh }` | `{ old_machi, new_machi }` | Old → rescheduled, creates new |
| GET | `/agyaries/{a}/machis/availability` | JWT+ctx | `?roj=2&mah=1&year=1396` | `{ gehs: [{ geh: 1, available: true }, ...] }` | Slot check |

**POST `/agyaries/{a}/machis` request body (manual entry):**

```json
{
  "customer_id": 42,                    // or customer_phone for auto-lookup/create
  "customer_phone": "+919876543210",    // alternative to customer_id
  "customer_name": "Jaidev Patel",      // used if creating new customer
  "parsi_roj": 2,
  "parsi_mah": 1,
  "parsi_year": 1396,
  "geh": 1,
  "gregorian_date": "2026-07-23",       // optional, computed from Parsi date if omitted
  "assigned_mobed_id": 7,               // optional
  "amount": 300,
  "names": [
    { "title": "ervad", "name": "Meherzad", "is_departed": false },
    { "title": "osti", "name": "Farzin", "is_departed": false }
  ],
  "notes": "Monthly satum",
  "auto_approve": true                  // for manual entry, skip requested state
}
```

When `auto_approve` is true (manual PWA entry by panthaky), the machi is created directly in `approved` or `assigned` status, skipping the request-approval flow. This powers the "2-tap machi" flow: the panthaky is entering a phone booking, so approval is implicit.

### Bookings

Same pattern as machis. Key differences noted.

| Method | Path | Auth | Body / Params | Response | Notes |
|---|---|---|---|---|---|
| GET | `/agyaries/{a}/bookings` | JWT+ctx | `?date=...` or `?start=...&end=...` or `?status=requested` | Array | Filter by status for pending queue |
| GET | `/agyaries/{a}/bookings/{bid}` | JWT+ctx | - | Full booking with mobeds, names | |
| POST | `/agyaries/{a}/bookings` | JWT+ctx | See below | Created booking | |
| POST | `/agyaries/{a}/bookings/{bid}/approve` | Admin | `{ mobed_ids: [7, 12] }` | Updated | Assign mobeds inline with approval |
| POST | `/agyaries/{a}/bookings/{bid}/assign` | Admin | `{ mobed_ids: [7], roles: { "7": "jyoti" } }` | Updated | For multi-mobed assignment |
| POST | `/agyaries/{a}/bookings/{bid}/mobed-response` | Mobed | `{ action: "accept" or "decline" }` | Updated | Called via WhatsApp callback URL |
| POST | `/agyaries/{a}/bookings/{bid}/complete` | JWT+ctx | - | Updated | |
| POST | `/agyaries/{a}/bookings/{bid}/cancel` | JWT+ctx | `{ reason? }` | Updated | |
| POST | `/agyaries/{a}/bookings/{bid}/reschedule` | Admin | `{ new_date_time, new_location? }` | `{ old, new }` | |

**POST `/agyaries/{a}/bookings` request body:**

```json
{
  "service_id": 3,
  "customer_id": 42,
  "date_time": "2026-07-23T10:00:00+05:30",
  "location": "123 Marine Drive, Flat 4B, Mumbai",   // if offsite
  "is_offsite": true,
  "amount": 1500,
  "mobed_ids": [7],
  "names": [
    { "title": "behdin", "name": "Roshan Patel", "is_departed": false },
    { "title": "ervad", "name": "Kaikhushru", "is_departed": true, "pair_group": 1 },
    { "title": "ervad", "name": "Hormazd", "is_departed": true, "pair_group": 1 }
  ],
  "auto_approve": true
}
```

### Names (Ceremony Names)

| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/agyaries/{a}/machis/{mid}/names` | JWT+ctx | Returns ordered name list |
| POST | `/agyaries/{a}/machis/{mid}/names` | JWT+ctx | Add name(s), body: `{ names: [...] }` |
| PUT | `/agyaries/{a}/machis/{mid}/names/{nid}` | JWT+ctx | Update single name |
| DELETE | `/agyaries/{a}/machis/{mid}/names/{nid}` | Admin | Remove name |

Same pattern under `/bookings/{bid}/names`.

### Recurrence

| Method | Path | Auth | Body / Params | Response | Notes |
|---|---|---|---|---|---|
| POST | `/agyaries/{a}/recurrence-rules` | Admin | `{ source_machi_id or source_booking_id, pattern, end_type, ... }` | Created rule | Panthaky approves by creating |
| GET | `/agyaries/{a}/recurrence-rules` | JWT+ctx | `?active=true` | Active rules with source info | |
| GET | `/agyaries/{a}/recurrence-rules/{rid}` | JWT+ctx | - | Rule + generated instances | |
| PUT | `/agyaries/{a}/recurrence-rules/{rid}` | Admin | `{ is_active?, end_date?, ... }` | Updated | Deactivate to stop generation |
| DELETE | `/agyaries/{a}/recurrence-rules/{rid}` | Admin | - | Deactivates | Does NOT delete generated instances |

### Bulk Batches

| Method | Path | Auth | Body / Params | Response | Notes |
|---|---|---|---|---|---|
| POST | `/agyaries/{a}/bulk-batches` | Admin | See below | Created batch + entries | Single transaction |
| GET | `/agyaries/{a}/bulk-batches` | JWT+ctx | `?date=2026-07-23` | Batches for date | |
| GET | `/agyaries/{a}/bulk-batches/{bid}` | JWT+ctx | - | Batch with all entries, progress | |
| POST | `/agyaries/{a}/bulk-batches/{bid}/entries` | Admin | `{ entries: [...] }` | Add more entries | Append to existing batch |
| PUT | `/agyaries/{a}/bulk-batches/{bid}/entries/{eid}/complete` | JWT+ctx | - | Marks entry complete, updates counter | |
| PUT | `/agyaries/{a}/bulk-batches/{bid}/entries/{eid}/undo-complete` | JWT+ctx | - | Reverts to approved | In case of mis-tap |
| GET | `/agyaries/{a}/bulk-batches/{bid}/print-data` | JWT+ctx | `?remaining_only=true` | Ordered print images | Returns image URLs |
| GET | `/agyaries/{a}/bulk-batches/{bid}/entries/{eid}/print-image` | JWT+ctx | - | Single slip as PNG | 384px or 576px wide |

### Payments

| Method | Path | Auth | Body / Params | Response | Notes |
|---|---|---|---|---|---|
| GET | `/agyaries/{a}/payments` | Admin | `?start=...&end=...&status=pending` | Paginated | Filter by status, date range |
| POST | `/agyaries/{a}/payments/{pid}/received` | Admin | `{ method, upi_transaction_ref? }` | Updated payment | Marks as received |
| POST | `/agyaries/{a}/payments/{pid}/refund` | Admin | `{ notes? }` | Updated payment | Status → refunded |
| GET | `/agyaries/{a}/payments/summary` | Admin | `?month=7&year=2026` | Financial summary | See query below |
| GET | `/agyaries/{a}/users/{uid}/earnings` | JWT+ctx | `?month=7&year=2026` | Mobed earnings breakdown | Mobed can see own, admin sees all |

### Print

| Method | Path | Auth | Body / Params | Response | Notes |
|---|---|---|---|---|---|
| GET | `/agyaries/{a}/machis/{mid}/print-image` | JWT+ctx | `?width=384` | PNG image | Rendered slip |
| GET | `/agyaries/{a}/bookings/{bid}/print-image` | JWT+ctx | `?width=384` | PNG image | |
| GET | `/agyaries/{a}/print/today` | JWT+ctx | `?type=machis` | Array of PNG URLs | All today's slips |

### WhatsApp Webhook

| Method | Path | Auth | Body / Params | Response | Notes |
|---|---|---|---|---|---|
| GET | `/webhooks/whatsapp` | None | `?hub.mode=subscribe&hub.verify_token=...&hub.challenge=...` | Challenge string | Meta verification |
| POST | `/webhooks/whatsapp` | Signature | Meta webhook payload | 200 OK (always) | HMAC-SHA256 verified |

### Notifications

| Method | Path | Auth | Body / Params | Response | Notes |
|---|---|---|---|---|---|
| GET | `/agyaries/{a}/notifications` | JWT+ctx | `?limit=20` | Recent notifications | For dashboard widget |
| GET | `/agyaries/{a}/notifications/failed` | Admin | - | Failed notifications | For retry/debugging |
| POST | `/agyaries/{a}/notifications/{nid}/retry` | Admin | - | Requeues notification | Resets status to pending |

---

## Booking State Machine

### States

```
requested       Customer submitted, awaiting panthaky decision.
approved        Panthaky approved. No mobed assigned yet (or mobed not required).
assigned        Mobed assigned and accepted. Ready for ceremony.
mobed_declined  Mobed backed out. Needs reassignment.
completed       Ceremony performed. Terminal.
cancelled       Cancelled by customer or panthaky. Terminal.
declined        Panthaky declined the request. Terminal.
rescheduled     Moved to new date. Replacement created. Terminal.
```

### Transition Diagram

```
                    ┌─────────────────────────────────┐
                    │           requested              │
                    └──────┬──────────┬───────┬────────┘
                           │          │       │
                      approve()  decline()  cancel()
                           │          │       │
                           ▼          ▼       ▼
                    ┌──────────┐  declined  cancelled
                    │ approved │  (terminal) (terminal)
                    └──┬───┬───┘
                       │   │
               assign()│   │complete()        cancel()
                       │   │ (panthaky         │
                       │   │  does it          │
                       │   │  himself)         │
                       ▼   ▼                   ▼
                ┌──────────┐              cancelled
                │ assigned │
                └──┬──┬──┬─┘
                   │  │  │
          complete()  │  mobed_declines()
                   │  │  │
                   │  │  ▼
                   │  │ ┌───────────────┐
                   │  │ │ mobed_declined │
                   │  │ └──┬────────┬───┘
                   │  │    │        │
                   │  │  assign()  cancel()
                   │  │    │        │
                   │  │    ▼        ▼
                   │  │  assigned  cancelled
                   │  │
                   │  reschedule()
                   │  │
                   ▼  ▼
              completed  rescheduled
              (terminal) (terminal, new booking created)
```

### Transition Table

| From | To | Trigger | Who | Side Effects |
|---|---|---|---|---|
| requested | approved | `approve()` | panthaky, caretaker | Notify customer: "Your request is confirmed." Create payment record. Send UPI link if amount set. |
| requested | declined | `decline()` | panthaky, caretaker | Notify customer with reason + alternatives. |
| requested | cancelled | `cancel()` | customer (WhatsApp), panthaky | Notify panthaky if customer-initiated. |
| approved | assigned | `assign(mobed_id)` | panthaky, caretaker | For bookings: send WhatsApp to mobed (Accept/Decline). For machis: direct assignment, send informational notification. |
| approved | completed | `complete()` | panthaky | For machis where panthaky performs the ceremony himself. No mobed involved. |
| approved | cancelled | `cancel()` | customer, panthaky | Refund if paid. Notify relevant parties. |
| assigned | completed | `complete()` | mobed, panthaky | Update mobed earnings. Notify customer if needed. |
| assigned | mobed_declined | `mobed_declines()` | mobed (WhatsApp) | Clear mobed assignment. Notify panthaky: "Er. X declined. Please reassign." |
| assigned | cancelled | `cancel()` | customer, panthaky | Notify assigned mobed. Refund if paid. |
| assigned | rescheduled | `reschedule(new_date)` | panthaky | Mark old as `rescheduled`. Create new booking with `approved` status. Link via notes. Notify customer with new date + accept/reject. |
| mobed_declined | assigned | `assign(mobed_id)` | panthaky | Same as approved → assigned. New mobed gets notified. |
| mobed_declined | cancelled | `cancel()` | panthaky | If no replacement mobed available. |

### Implementation: `BookingStateMachine`

```python
class BookingStateMachine:
    """Enforces valid state transitions for machis and bookings."""

    TRANSITIONS = {
        'requested':      {'approved', 'declined', 'cancelled'},
        'approved':       {'assigned', 'completed', 'cancelled'},
        'assigned':       {'completed', 'mobed_declined', 'cancelled', 'rescheduled'},
        'mobed_declined': {'assigned', 'cancelled'},
        # Terminal states have no outgoing transitions
        'completed':      set(),
        'cancelled':      set(),
        'declined':       set(),
        'rescheduled':    set(),
    }

    ROLE_PERMISSIONS = {
        # (from_status, to_status) -> set of allowed roles
        ('requested', 'approved'):       {'panthaky', 'caretaker'},
        ('requested', 'declined'):       {'panthaky', 'caretaker'},
        ('requested', 'cancelled'):      {'panthaky', 'caretaker', 'customer'},
        ('approved', 'assigned'):        {'panthaky', 'caretaker'},
        ('approved', 'completed'):       {'panthaky'},
        ('approved', 'cancelled'):       {'panthaky', 'caretaker', 'customer'},
        ('assigned', 'completed'):       {'panthaky', 'caretaker', 'mobed'},
        ('assigned', 'mobed_declined'):  {'mobed'},
        ('assigned', 'cancelled'):       {'panthaky', 'caretaker', 'customer'},
        ('assigned', 'rescheduled'):     {'panthaky', 'caretaker'},
        ('mobed_declined', 'assigned'):  {'panthaky', 'caretaker'},
        ('mobed_declined', 'cancelled'): {'panthaky', 'caretaker'},
    }

    @classmethod
    def transition(cls, current: str, target: str, role: str) -> None:
        if target not in cls.TRANSITIONS.get(current, set()):
            raise InvalidTransition(f"Cannot go from {current} to {target}")
        allowed_roles = cls.ROLE_PERMISSIONS.get((current, target), set())
        if role not in allowed_roles:
            raise PermissionDenied(f"Role {role} cannot trigger {current} -> {target}")
```

### Mobed Decline Flow (detailed)

For bookings (multi-mobed via `booking_mobeds`):

```python
async def mobed_declines_booking(booking_id: int, mobed_id: int, db: AsyncSession):
    booking = await db.get(Booking, booking_id)
    BookingStateMachine.transition(booking.status, 'mobed_declined', 'mobed')

    # Update this mobed's record in booking_mobeds
    stmt = (
        update(BookingMobed)
        .where(BookingMobed.booking_id == booking_id, BookingMobed.user_id == mobed_id)
        .values(status='declined')
    )
    await db.execute(stmt)

    # Check if ANY mobed is still assigned/accepted
    remaining = await db.execute(
        select(BookingMobed)
        .where(BookingMobed.booking_id == booking_id,
               BookingMobed.status.in_(['assigned', 'accepted']))
    )
    if not remaining.scalars().all():
        # All mobeds declined or no mobeds left
        booking.status = 'mobed_declined'
    # else: booking stays 'assigned' (other mobeds still on it)

    # Notify panthaky
    await create_notification(
        agyary_id=booking.agyary_id,
        type='mobed_declined',
        recipient=get_panthaky(booking.agyary_id),
        params={'mobed_name': mobed.name, 'service': booking.service.name, 'date': booking.date_time}
    )
    await db.commit()
```

For machis (single mobed):

```python
async def mobed_declines_machi(machi_id: int, mobed_id: int, db: AsyncSession):
    machi = await db.get(Machi, machi_id)
    assert machi.assigned_mobed_id == mobed_id

    BookingStateMachine.transition(machi.status, 'mobed_declined', 'mobed')
    machi.status = 'mobed_declined'
    machi.assigned_mobed_id = None

    await create_notification(
        agyary_id=machi.agyary_id,
        type='mobed_declined',
        recipient=get_panthaky(machi.agyary_id),
        params={'mobed_name': mobed.name, 'roj': machi.parsi_roj, 'mah': machi.parsi_mah}
    )
    await db.commit()
```

---

## WhatsApp Webhook Handler

### Webhook Verification (GET)

```python
@router.get("/webhooks/whatsapp")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    if hub_mode == "subscribe" and hub_verify_token == settings.WA_VERIFY_TOKEN:
        return Response(content=hub_challenge, media_type="text/plain")
    raise HTTPException(403)
```

### Webhook Handler (POST)

```python
@router.post("/webhooks/whatsapp")
async def handle_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    # 1. Verify HMAC-SHA256 signature
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    expected = "sha256=" + hmac.new(
        settings.WA_APP_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(403)

    # 2. Always return 200 immediately (Meta requirement: respond within 5 seconds)
    # Process asynchronously via background task
    payload = await request.json()
    background_tasks.add_task(process_webhook_payload, payload, db)
    return Response(status_code=200)
```

### Payload Processing

```python
async def process_webhook_payload(payload: dict, db: AsyncSession):
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            phone_number_id = value.get("metadata", {}).get("phone_number_id")

            # Route to agyary
            agyary = await db.execute(
                select(Agyary).where(Agyary.wa_phone_number_id == phone_number_id)
            )
            agyary = agyary.scalar_one_or_none()
            if not agyary:
                logger.error(f"Unknown phone_number_id: {phone_number_id}")
                continue

            # Handle messages
            for message in value.get("messages", []):
                await handle_inbound_message(agyary, message, db)

            # Handle status updates (delivery receipts)
            for status in value.get("statuses", []):
                await handle_status_update(status, db)
```

### Inbound Message Routing

```python
async def handle_inbound_message(agyary: Agyary, message: dict, db: AsyncSession):
    sender_phone = message["from"]
    wa_message_id = message["id"]

    # Idempotency: skip if we've already processed this message
    existing = await db.execute(
        select(WhatsAppMessage).where(WhatsAppMessage.wa_message_id == wa_message_id)
    )
    if existing.scalar_one_or_none():
        return

    # Log message
    wa_msg = WhatsAppMessage(
        agyary_id=agyary.id,
        direction='inbound',
        wa_phone=sender_phone,
        wa_message_id=wa_message_id,
        wa_timestamp=datetime.fromtimestamp(int(message["timestamp"])),
        message_type=message["type"],
        content=message,
    )
    db.add(wa_msg)

    # Resolve or create customer
    customer = await get_or_create_customer(sender_phone, agyary, db)
    wa_msg.customer_id = customer.id

    # Load conversation state
    state = await db.execute(
        select(ConversationState)
        .where(ConversationState.agyary_id == agyary.id,
               ConversationState.phone == sender_phone)
    )
    state = state.scalar_one_or_none()

    # Check expiry
    if state and state.expires_at < datetime.utcnow():
        await db.delete(state)
        state = None

    # Route to flow handler
    msg_type = message["type"]

    if msg_type == "interactive":
        # Button reply or list selection
        interactive = message["interactive"]
        if interactive["type"] == "button_reply":
            button_id = interactive["button_reply"]["id"]
            await handle_button_reply(agyary, customer, button_id, state, db)
        elif interactive["type"] == "list_reply":
            selection_id = interactive["list_reply"]["id"]
            await handle_list_selection(agyary, customer, selection_id, state, db)

    elif msg_type == "text":
        text = message["text"]["body"]
        if state:
            # Continue active flow
            await continue_flow(agyary, customer, text, state, db)
        else:
            # No active flow: show welcome or parse intent
            await handle_freeform_text(agyary, customer, text, db)

    await db.commit()
```

### Button Reply Handler

Button IDs encode the action: `{action}_{entity}_{id}`.

```python
async def handle_button_reply(agyary, customer, button_id, state, db):
    parts = button_id.split("_", 2)
    action = parts[0]

    if action == "approve":
        # Panthaky approving a booking
        entity_type, entity_id = parts[1], int(parts[2])
        if entity_type == "machi":
            await approve_machi(entity_id, db)
        elif entity_type == "booking":
            await approve_booking(entity_id, db)

    elif action == "decline":
        entity_type, entity_id = parts[1], int(parts[2])
        await decline_ceremony(entity_type, entity_id, db)

    elif action == "accept":
        # Mobed accepting assignment
        entity_type, entity_id = parts[1], int(parts[2])
        await mobed_accepts(entity_type, entity_id, customer.phone, db)

    elif action == "mobed-decline":
        entity_type, entity_id = parts[1], int(parts[2])
        await mobed_declines(entity_type, entity_id, customer.phone, db)

    elif action == "slot":
        # Customer selecting an alternative slot
        geh = int(parts[2])
        await select_alternative_slot(agyary, customer, state, geh, db)

    elif action == "pay":
        # Customer choosing payment method
        method = parts[1]  # "upi" or "cash"
        entity_id = int(parts[2])
        await handle_payment_choice(agyary, customer, method, entity_id, db)
```

---

## Conversation Trees

### Welcome (no active state)

Customer sends any message to the agyary's WhatsApp number:

```
┌────────────────────────────────────────────────────────┐
│  Welcome to {agyary_name}!                             │
│                                                        │
│  What would you like to do?                            │
│                                                        │
│  [Choose an option ▾]                                  │
│    ├── Book a Machi                                    │
│    ├── Book a Service (Jashan, Navjote, etc.)          │
│    ├── My Bookings                                     │
│    └── Contact {panthaky_name}                         │
└────────────────────────────────────────────────────────┘
```

Sent as an interactive list message. No template needed (customer initiated, within 24h window).

### Machi Booking Flow

**Step 1: Date Selection** (state: `machi.select_date`)

```
When would you like the Machi?

You can enter:
- A Parsi date: "Roj Bahman" or "Roj Bahman Mah Fravardin"
- A Gregorian date: "July 23" or "23/7/2026"
- "Tomorrow" or "Next week"
```

Sent as a text message. Customer replies with free text. Parser handles:
- `"Roj Bahman"` → sets roj=2, asks for Mah
- `"Roj Bahman Mah Fravardin"` → sets roj=2, mah=1, proceeds to geh
- `"July 23"` or `"23/7"` → converts to Parsi, confirms conversion, proceeds to geh
- `"tomorrow"` → resolves to tomorrow's date, converts to Parsi
- Unparseable → "Sorry, I didn't understand. Please enter a date like 'Roj Bahman' or 'July 23'"

If only Roj provided, ask for Mah:

```
┌────────────────────────────────────────────────────────┐
│  Which Mah?                                            │
│                                                        │
│  [Select Mah ▾]                                        │
│    ├── 1. Fravardin                                    │
│    ├── 2. Ardibehesht                                  │
│    ├── 3. Khordad                                      │
│    ├── 4. Tir                                          │
│    ├── 5. Amardad                                      │
│    ├── 6. Shahrevar                                    │
│    ├── 7. Meher                                        │
│    ├── 8. Avan                                         │
│    ├── 9. Adar                                         │
│    └── 10. Dae / 11. Bahman / 12. Aspandard            │
└────────────────────────────────────────────────────────┘
```

(Interactive list, max 10 rows per section. Use 2 sections if needed.)

**Step 2: Geh Selection** (state: `machi.select_geh`)

System checks availability for all 5 gehs on that date.

```
┌────────────────────────────────────────────────────────┐
│  Roj Bahman, Mah Fravardin (July 23, 2026)             │
│                                                        │
│  Select a Geh:                                         │
│                                                        │
│  [Available Gehs ▾]                                    │
│    ├── Havan          Available                         │
│    ├── Ujiran         Available                         │
│    └── Aiwisruthrem   Available                         │
└────────────────────────────────────────────────────────┘
```

Only available gehs shown. If ALL gehs taken:

```
All Gehs are booked for Roj Bahman, Mah Fravardin.

[Try another date]  [Next available Roj]  [Contact us]
```

"Next available Roj" queries the next 3 dates with at least one open geh.

**If customer picks a geh that got taken between the check and their selection** (race condition): "Sorry, Havan Geh was just booked. Here are the remaining options:" + show updated availability.

**Step 3: Name Entry** (state: `machi.enter_names`)

```
Please enter the names for the Machi, one per line.

Format: Title Name
Example:
  Ervad Meherzad
  Osti Farzin
  Khud Zahan

Titles: Ervad, Behdin, Osta, Osti, Khud

For departed, add (D):
  Ervad Meherzad (D)

When done, send "done".
```

Parser extracts title + name + departed flag from each line. Stores in conversation state data. If title is missing, defaults to `behdin`. If `(D)` or `(departed)` is present, marks as departed.

Returning customers: if the customer has booked before with the same names, offer to reuse:

```
Use the same names as your last booking?

Ervad Meherzad, Osti Farzin, Khud Zahan

[Yes, same names]  [Enter new names]
```

**Step 4: Confirmation** (state: `machi.confirm`)

```
┌────────────────────────────────────────────────────────┐
│  Booking Summary                                       │
│                                                        │
│  Machi at {agyary_name}                                │
│  Roj Bahman, Mah Fravardin (July 23, 2026)             │
│  Havan Geh                                             │
│                                                        │
│  Names:                                                │
│  - Ervad Meherzad                                      │
│  - Osti Farzin                                         │
│  - Khud Zahan                                          │
│                                                        │
│  Amount: Rs. 300                                       │
│                                                        │
│  [Confirm]  [Edit]  [Cancel]                           │
└────────────────────────────────────────────────────────┘
```

On Confirm → machi created with status `requested`. State cleared. Customer gets:

```
Your Machi request has been sent to {agyary_name}.
You'll hear back shortly.
```

Panthaky gets approval notification (see Notification Engine).

### Alternative Slot Suggestion

When the requested geh is taken and the customer didn't get to see the geh list (e.g., they typed "Roj Bahman Havan Geh" in one message):

```
┌────────────────────────────────────────────────────────┐
│  Havan Geh is booked on Roj Bahman, Mah Fravardin.     │
│                                                        │
│  Same Roj, available Gehs:                             │
│    Ujiran, Aiwisruthrem, Ushahin                       │
│                                                        │
│  Same Geh (Havan), next available Rojs:                 │
│    Roj Ardibehesht (July 24)                           │
│    Roj Shahrevar (July 25)                             │
│    Roj Khordad (July 27)                               │
│                                                        │
│  [Choose another option ▾]                             │
│    ├── Ujiran (same day)                               │
│    ├── Aiwisruthrem (same day)                         │
│    ├── Ushahin (same day)                              │
│    ├── Havan - Roj Ardibehesht (July 24)               │
│    ├── Havan - Roj Shahrevar (July 25)                 │
│    ├── Havan - Roj Khordad (July 27)                   │
│    ├── Cancel booking                                  │
│    └── Contact {panthaky_name}                         │
└────────────────────────────────────────────────────────┘
```

### Panthaky Approval (via WhatsApp)

Panthaky receives (sent as interactive button message):

```
┌────────────────────────────────────────────────────────┐
│  New Machi Request                                     │
│                                                        │
│  Customer: Jaidev Patel                                │
│  Date: Roj Bahman, Mah Fravardin (July 23)             │
│  Geh: Havan                                            │
│  Names: Ervad Meherzad, Osti Farzin, Khud Zahan        │
│                                                        │
│  [Approve]  [Decline]                                  │
└────────────────────────────────────────────────────────┘
```

Button IDs: `approve_machi_123`, `decline_machi_123`.

### Mobed Assignment Notification

After panthaky approves and assigns a mobed (via PWA or WhatsApp):

```
┌────────────────────────────────────────────────────────┐
│  New Assignment                                        │
│                                                        │
│  Jashan at 123 Marine Drive, Flat 4B                   │
│  Roj Bahman, Mah Fravardin (July 23, 2026)             │
│  10:00 AM                                              │
│  Customer: Roshan Patel                                │
│                                                        │
│  [Accept]  [Decline]                                   │
└────────────────────────────────────────────────────────┘
```

For machis (informational, not accept/decline since panthaky handles it):

```
You have a Machi assigned:
Roj Bahman, Mah Fravardin (July 23)
Havan Geh
Customer: Jaidev Patel
```

Whether mobed acceptance is required depends on the agyary's workflow. For agyaries where the panthaky just assigns and the mobed shows up (most small agyaries), it's informational. For larger agyaries with freelance mobeds, use accept/decline. Configurable per agyary:

```sql
ALTER TABLE agyaries ADD COLUMN require_mobed_acceptance BOOLEAN NOT NULL DEFAULT false;
```

If false: assignment → status goes directly to `assigned`, mobed gets informational notification.
If true: assignment → mobed gets Accept/Decline buttons, status goes to `assigned` only on acceptance.

---

## Notification Engine

### Architecture

Separate worker process (`notification_engine.py`). Runs an async loop polling the notifications table.

```python
async def notification_engine():
    """Poll notifications table, send pending via WhatsApp Cloud API."""
    while True:
        async with get_session() as db:
            # Pick up batch of pending notifications
            notifications = await db.execute(
                select(Notification)
                .where(
                    Notification.status == 'pending',
                    Notification.scheduled_at <= func.now()
                )
                .order_by(Notification.scheduled_at)
                .limit(50)
                .with_for_update(skip_locked=True)  # prevent double-sending
            )

            for notif in notifications.scalars():
                try:
                    wa_response = await send_whatsapp_message(
                        phone_number_id=get_phone_number_id(notif.agyary_id),
                        to=notif.recipient_phone,
                        template_name=notif.template_name,
                        params=notif.template_params,
                    )
                    notif.status = 'sent'
                    notif.sent_at = datetime.utcnow()
                    notif.wa_message_id = wa_response["messages"][0]["id"]
                except WhatsAppRateLimitError:
                    # Back off, don't increment retry
                    await asyncio.sleep(60)
                except WhatsAppAPIError as e:
                    notif.retry_count += 1
                    if notif.retry_count >= 3:
                        notif.status = 'failed'
                        notif.error_message = str(e)
                    else:
                        # Exponential backoff: 1min, 5min, 25min
                        notif.scheduled_at = datetime.utcnow() + timedelta(
                            minutes=5 ** notif.retry_count
                        )

            await db.commit()

        await asyncio.sleep(10)  # poll every 10 seconds
```

### Notification Catalog

| Type | Trigger | Recipient | Template | Timing | Interactive |
|---|---|---|---|---|---|
| `booking_request` | Customer submits machi/booking | Panthaky (all at that agyary) | `booking_approval_request` | Immediate | Approve / Decline buttons |
| `booking_approved` | Panthaky approves | Customer | `booking_confirmation` | Immediate | Pay via UPI / Pay at agyary buttons |
| `booking_declined` | Panthaky declines | Customer | `booking_declined` | Immediate | Text with reason + "Book different date" button |
| `mobed_assigned` | Panthaky assigns mobed | Mobed | `mobed_assignment` | Immediate | Accept / Decline buttons (if agyary requires acceptance) |
| `mobed_accepted` | Mobed accepts | Customer + Panthaky | `booking_mobed_confirmed` | Immediate | Text only |
| `mobed_declined` | Mobed declines | Panthaky | `mobed_declined_alert` | Immediate | "Reassign" button (deep link to PWA) |
| `ceremony_reminder` | Scheduled | Mobed (or Panthaky if no mobed) | `ceremony_reminder` | Configurable, default 30 min before | Text with ceremony details + names summary |
| `payment_request` | After approval | Customer | `payment_link` | Immediate (with approval notification) | UPI link + "Pay at agyary" button |
| `recurring_generated` | System generates instance | Panthaky | `recurring_auto_confirmed` | Immediate after generation | Text only (informational, not approval) |
| `cancellation` | Customer or panthaky cancels | Other party + assigned mobed | `booking_cancelled` | Immediate | Text only |
| `reschedule_customer` | Panthaky reschedules | Customer | `booking_rescheduled` | Immediate | Accept new date / Pick different date / Cancel buttons |
| `daily_summary` | Daily cron (optional) | Panthaky | `daily_schedule_summary` | Configurable, default 6 AM | Text with today's ceremony count |

### Configurable Reminder Timing

Each mobed sets their preferred reminder time via the PWA:

```
PUT /api/agyaries/{a}/users/{uid}
{ "reminder_minutes_before": 45 }
```

When a ceremony is confirmed (status → `assigned` or `approved`), the system creates a reminder notification:

```python
async def schedule_reminder(ceremony, mobed, db):
    """Schedule a reminder notification for the assigned mobed."""
    # Get mobed's preference
    membership = await get_agyary_user(ceremony.agyary_id, mobed.id, db)
    minutes = membership.reminder_minutes_before  # default 30

    # Calculate ceremony start time
    ceremony_time = get_ceremony_start_time(ceremony)  # from geh or date_time
    reminder_time = ceremony_time - timedelta(minutes=minutes)

    # Don't schedule in the past
    if reminder_time < datetime.utcnow():
        return

    notification = Notification(
        agyary_id=ceremony.agyary_id,
        recipient_phone=mobed.phone,
        recipient_type='user',
        recipient_id=mobed.id,
        notification_type='ceremony_reminder',
        template_name='ceremony_reminder',
        template_params={
            'service': get_service_name(ceremony),
            'date': format_parsi_date(ceremony),
            'time': format_time(ceremony),
            'customer': ceremony.customer.name,
            'names_count': len(ceremony.names),
        },
        machi_id=ceremony.id if isinstance(ceremony, Machi) else None,
        booking_id=ceremony.id if isinstance(ceremony, Booking) else None,
        scheduled_at=reminder_time,
    )
    db.add(notification)
```

When a mobed updates their reminder preference, reschedule all their pending reminders:

```python
async def update_reminder_preference(agyary_id, user_id, new_minutes, db):
    membership = await get_agyary_user(agyary_id, user_id, db)
    old_minutes = membership.reminder_minutes_before
    membership.reminder_minutes_before = new_minutes

    # Reschedule pending reminders
    pending_reminders = await db.execute(
        select(Notification)
        .where(
            Notification.recipient_id == user_id,
            Notification.notification_type == 'ceremony_reminder',
            Notification.status == 'pending'
        )
    )
    for reminder in pending_reminders.scalars():
        # Shift by the difference
        delta = timedelta(minutes=old_minutes - new_minutes)
        reminder.scheduled_at += delta
    await db.commit()
```

### WhatsApp Template Message Parameters

Templates are registered in Meta Business Manager. Parameter format:

```python
# Example: booking_confirmation template
# Template body: "Your {{1}} at {{2}} is confirmed for {{3}}, {{4}}. {{5}}"
# Parameters:
{
    "1": "Machi",                              # service name
    "2": "Goti Adarian",                       # agyary name
    "3": "Roj Bahman, Mah Fravardin",          # Parsi date
    "4": "Havan Geh",                          # time/geh
    "5": "We look forward to seeing you."      # closing
}
```

For interactive messages within the 24h window (no template needed), use the Cloud API's interactive message format directly. These are free.

### Sending via WhatsApp Cloud API

```python
async def send_whatsapp_message(
    phone_number_id: str,
    to: str,
    template_name: str = None,
    params: dict = None,
    interactive: dict = None,
    text: str = None,
) -> dict:
    """Send a message via WhatsApp Cloud API."""
    url = f"https://graph.facebook.com/v21.0/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {settings.WA_SYSTEM_TOKEN}",
        "Content-Type": "application/json",
    }

    if template_name:
        body = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": "en"},
                "components": [{
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": v}
                        for v in params.values()
                    ]
                }]
            }
        }
    elif interactive:
        body = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": interactive,
        }
    elif text:
        body = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": text},
        }

    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=body, headers=headers)
        if response.status_code == 429:
            raise WhatsAppRateLimitError(response.json())
        response.raise_for_status()
        return response.json()
```

---

## Recurring Booking Generation

### Worker: `recurrence_generator.py`

Runs once daily via cron (or Docker `command` with sleep loop). Generates instances up to `generation_horizon_months` ahead.

```python
async def generate_recurring_instances():
    """Daily job: generate future instances for all active recurrence rules."""
    async with get_session() as db:
        rules = await db.execute(
            select(RecurrenceRule)
            .where(RecurrenceRule.is_active == True)
            .options(
                joinedload(RecurrenceRule.source_machi),
                joinedload(RecurrenceRule.source_booking),
            )
        )

        for rule in rules.scalars():
            horizon = date.today() + relativedelta(months=rule.generation_horizon_months)

            # Skip if already generated up to horizon
            if rule.last_generated_until and rule.last_generated_until >= horizon:
                continue

            # Check end condition
            if rule.end_type == 'until_date' and rule.end_date and rule.end_date < date.today():
                rule.is_active = False
                continue

            start_from = (rule.last_generated_until or date.today()) + timedelta(days=1)
            occurrences = compute_occurrences(rule, start_from, horizon)

            for occurrence_date in occurrences:
                try:
                    await create_recurring_instance(rule, occurrence_date, db)
                except SlotConflict as e:
                    # Slot taken: notify panthaky, skip this instance
                    await create_notification(
                        agyary_id=rule.agyary_id,
                        type='recurring_conflict',
                        recipient=get_panthaky(rule.agyary_id),
                        params={
                            'customer': get_customer_name(rule),
                            'date': format_parsi_date_from_gregorian(occurrence_date),
                            'conflict_reason': str(e),
                        }
                    )

            rule.last_generated_until = horizon
            await db.commit()
```

### Occurrence Computation

```python
def compute_occurrences(
    rule: RecurrenceRule,
    start: date,
    end: date
) -> list[date]:
    """Compute Gregorian dates for each occurrence between start and end."""
    occurrences = []
    source = rule.source_machi or rule.source_booking
    calendar_system = source.calendar_system

    if rule.pattern == 'same_roj_every_mah':
        # Same Roj, increment Mah
        # Start from source's Parsi date, step forward by 1 Mah each time
        current_roj = source.parsi_roj
        current_mah = source.parsi_mah
        current_year = source.parsi_year

        while True:
            current_mah += 1
            if current_mah > 12:
                current_mah = 1
                current_year += 1
            # Handle Gatha days: if roj > 30, skip (can't recur into Gatha)

            greg_date = parsi_to_gregorian(current_roj, current_mah, current_year, calendar_system)
            if greg_date > end:
                break
            if greg_date >= start:
                occurrences.append(greg_date)

            # Check end conditions
            if rule.end_type == 'after_count' and len(occurrences) >= rule.end_count:
                break
            if rule.end_type == 'until_date' and greg_date >= rule.end_date:
                break

    elif rule.pattern == 'same_roj_mah_every_year':
        # Annual: same Roj + Mah, increment year
        current_year = source.parsi_year
        while True:
            current_year += 1
            greg_date = parsi_to_gregorian(
                source.parsi_roj, source.parsi_mah, current_year, calendar_system
            )
            if greg_date > end:
                break
            if greg_date >= start:
                occurrences.append(greg_date)
            if rule.end_type == 'after_count' and len(occurrences) >= rule.end_count:
                break

    return occurrences
```

### Creating a Recurring Instance

```python
async def create_recurring_instance(
    rule: RecurrenceRule,
    greg_date: date,
    db: AsyncSession,
):
    source = rule.source_machi or rule.source_booking
    parsi = gregorian_to_parsi(greg_date, source.calendar_system)

    if rule.source_machi_id:
        # Check slot availability
        existing = await db.execute(
            select(Machi)
            .where(
                Machi.agyary_id == rule.agyary_id,
                Machi.parsi_roj == parsi.roj,
                Machi.parsi_mah == parsi.mah,
                Machi.parsi_year == parsi.year,
                Machi.geh == source.geh,
                Machi.status.notin_(['cancelled', 'declined', 'rescheduled']),
            )
        )
        if existing.scalar_one_or_none():
            raise SlotConflict(f"Geh {source.geh} already booked on {greg_date}")

        new_machi = Machi(
            agyary_id=rule.agyary_id,
            customer_id=source.customer_id,
            parsi_roj=parsi.roj,
            parsi_mah=parsi.mah,
            parsi_year=parsi.year,
            calendar_system=source.calendar_system,
            geh=source.geh,
            gregorian_date=greg_date,
            assigned_mobed_id=source.assigned_mobed_id,  # same mobed
            status='approved',  # auto-approved, rule was pre-approved
            recurrence_rule_id=rule.id,
            is_recurring_instance=True,
            amount=source.amount,
            mobed_amount=source.mobed_amount,
        )
        db.add(new_machi)
        await db.flush()  # get ID

        # Copy ceremony names from source
        await copy_ceremony_names(source_machi_id=source.id, target_machi_id=new_machi.id, db=db)

        # Create payment record
        if new_machi.amount:
            db.add(Payment(
                agyary_id=rule.agyary_id,
                customer_id=source.customer_id,
                machi_id=new_machi.id,
                amount=new_machi.amount,
                method='upi',  # default, customer can change
                status='pending',
            ))

        # Notify panthaky (informational)
        await create_notification(
            agyary_id=rule.agyary_id,
            type='recurring_generated',
            recipient=get_panthaky(rule.agyary_id),
            params={
                'customer': source.customer.name,
                'date': f"Roj {parsi.roj_name}, Mah {parsi.mah_name}",
                'geh': GEH_NAMES[source.geh],
            }
        )

        # If mobed assigned, schedule reminder
        if new_machi.assigned_mobed_id:
            mobed = await db.get(User, new_machi.assigned_mobed_id)
            await schedule_reminder(new_machi, mobed, db)
```

### Cancelling One Instance vs. the Series

Cancelling a single recurring instance: just cancel that machi/booking. `recurrence_rule_id` stays set for audit trail. The rule continues generating future instances.

Cancelling the entire series:

```python
async def cancel_recurrence_series(rule_id: int, cancel_future: bool, db: AsyncSession):
    rule = await db.get(RecurrenceRule, rule_id)
    rule.is_active = False

    if cancel_future:
        # Cancel all future generated instances that haven't been completed
        await db.execute(
            update(Machi)
            .where(
                Machi.recurrence_rule_id == rule_id,
                Machi.status.in_(['approved', 'assigned']),
                Machi.gregorian_date > date.today(),
            )
            .values(status='cancelled')
        )
        await db.execute(
            update(Booking)
            .where(
                Booking.recurrence_rule_id == rule_id,
                Booking.status.in_(['approved', 'assigned']),
                Booking.date_time > datetime.utcnow(),
            )
            .values(status='cancelled')
        )

    await db.commit()
```

---

## Bulk Ceremony Flow

### Creation: 50+ Afringans in One Operation

The panthaky creates a batch via the PWA. The API accepts the entire batch in a single POST:

```
POST /api/agyaries/{a}/bulk-batches
```

```json
{
  "service_id": 3,
  "gregorian_date": "2026-07-23",
  "entries": [
    {
      "customer_name": "Patel Family",
      "customer_phone": "+919876543210",
      "amount": 200,
      "names": [
        { "title": "ervad", "name": "Kaikhushru", "is_departed": true, "pair_group": 1 },
        { "title": "ervad", "name": "Hormazd", "is_departed": true, "pair_group": 1 }
      ]
    },
    {
      "customer_name": "Mistry Family",
      "customer_phone": "+919876543211",
      "amount": 200,
      "names": [
        { "title": "behdin", "name": "Roshan", "is_departed": true, "pair_group": 1 },
        { "title": "behdin", "name": "Dinshaw", "is_departed": true, "pair_group": 1 }
      ]
    }
    // ... 85 more entries
  ]
}
```

### Processing (single transaction)

```python
async def create_bulk_batch(agyary_id: int, data: BulkBatchCreate, db: AsyncSession):
    # Convert date
    parsi = gregorian_to_parsi(data.gregorian_date, agyary.calendar_system)

    # Create batch
    batch = BulkBatch(
        agyary_id=agyary_id,
        service_id=data.service_id,
        gregorian_date=data.gregorian_date,
        parsi_roj=parsi.roj,
        parsi_mah=parsi.mah,
        parsi_year=parsi.year,
        calendar_system=agyary.calendar_system,
        total_entries=len(data.entries),
        created_by=current_user.id,
    )
    db.add(batch)
    await db.flush()

    for i, entry in enumerate(data.entries):
        # Get or create customer
        customer = await get_or_create_customer_by_phone_or_name(
            entry.customer_phone, entry.customer_name, agyary_id, db
        )

        # Create booking (auto-approved)
        booking = Booking(
            agyary_id=agyary_id,
            service_id=data.service_id,
            customer_id=customer.id,
            date_time=datetime.combine(data.gregorian_date, time(0, 0)),
            parsi_roj=parsi.roj,
            parsi_mah=parsi.mah,
            parsi_year=parsi.year,
            calendar_system=agyary.calendar_system,
            status='approved',
            bulk_batch_id=batch.id,
            amount=entry.amount,
            payment_status='pending',
        )
        db.add(booking)
        await db.flush()

        # Add ceremony names
        for j, name_data in enumerate(entry.names):
            db.add(CeremonyName(
                booking_id=booking.id,
                title=name_data.title,
                name=name_data.name,
                is_departed=name_data.is_departed,
                display_order=j,
                pair_group=name_data.pair_group,
            ))

        # Create payment record
        if entry.amount:
            db.add(Payment(
                agyary_id=agyary_id,
                customer_id=customer.id,
                booking_id=booking.id,
                amount=entry.amount,
                method='cash',  # bulk ceremonies are usually cash at the counter
                status='pending',
            ))

    await db.commit()
    return batch
```

### Completion Tracking

Each entry in the batch is an individual booking. The mobed marks them complete one by one.

```
PUT /api/agyaries/{a}/bulk-batches/{bid}/entries/{eid}/complete
```

The batch's `completed_count` is maintained via trigger or application logic:

```python
async def complete_bulk_entry(batch_id: int, entry_id: int, db: AsyncSession):
    booking = await db.get(Booking, entry_id)
    assert booking.bulk_batch_id == batch_id
    assert booking.status == 'approved'

    booking.status = 'completed'

    # Update batch counter
    batch = await db.get(BulkBatch, batch_id)
    batch.completed_count += 1
    if batch.completed_count >= batch.total_entries:
        batch.status = 'completed'
    else:
        batch.status = 'in_progress'

    await db.commit()
```

The PWA shows the batch as a list with color coding:
- Default background: pending
- Green: completed
- The progress bar reads "43 / 87 completed"

### Thermal Printing for Bulk

**Server-side image rendering** for each slip:

```python
from PIL import Image, ImageDraw, ImageFont

PRINTER_WIDTH_58MM = 384   # pixels at 203 DPI
PRINTER_WIDTH_80MM = 576
FONT_PATH = "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"
FONT_PATH_GUJARATI = "/usr/share/fonts/truetype/noto/NotoSansGujarati-Regular.ttf"

def render_ceremony_slip(
    ceremony_data: dict,
    width: int = PRINTER_WIDTH_58MM,
    seq_number: int = None,
    total: int = None,
) -> bytes:
    """Render a ceremony slip as a PNG image sized for thermal printer."""

    # Use a clean sans-serif font, large enough to be absolutely readable
    font_header = ImageFont.truetype(FONT_PATH, 24)
    font_body = ImageFont.truetype(FONT_PATH, 20)
    font_small = ImageFont.truetype(FONT_PATH, 16)
    line_height = 28
    padding = 16

    # Calculate image height dynamically
    lines = []
    lines.append(("header", f"Roj {ceremony_data['roj_name']} | Mah {ceremony_data['mah_name']}"))
    lines.append(("small", ceremony_data['gregorian_date']))
    if ceremony_data.get('geh_name'):
        lines.append(("small", f"{ceremony_data['geh_name']} Geh"))
    lines.append(("separator", ""))
    lines.append(("header", ceremony_data['service_name']))
    lines.append(("body", f"Booked by: {ceremony_data['customer_name']}"))
    lines.append(("separator", ""))

    # Living names
    for name in ceremony_data.get('living_names', []):
        lines.append(("body", f"  {name['title'].capitalize()} {name['name']}"))

    # Departed names (paired)
    if ceremony_data.get('departed_pairs'):
        lines.append(("separator", ""))
        for pair in ceremony_data['departed_pairs']:
            pair_text = ", ".join(f"{n['title'].capitalize()} {n['name']}" for n in pair)
            lines.append(("body", f"  {pair_text}"))

    # Sequence number for bulk
    if seq_number is not None:
        lines.append(("separator", ""))
        lines.append(("small", f"{seq_number} of {total}"))

    # Calculate height
    height = padding * 2
    for line_type, _ in lines:
        if line_type == "separator":
            height += 12
        elif line_type == "header":
            height += 32
        else:
            height += line_height

    # Render
    img = Image.new('1', (width, height), color=1)  # 1-bit monochrome, white bg
    draw = ImageDraw.Draw(img)
    y = padding

    for line_type, text in lines:
        if line_type == "separator":
            draw.line([(padding, y + 6), (width - padding, y + 6)], fill=0, width=1)
            y += 12
        elif line_type == "header":
            draw.text((padding, y), text, font=font_header, fill=0)
            y += 32
        elif line_type == "small":
            draw.text((padding, y), text, font=font_small, fill=0)
            y += line_height
        else:
            draw.text((padding, y), text, font=font_body, fill=0)
            y += line_height

    # Convert to PNG bytes
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()
```

**Why render as image, not ESC/POS text commands**:
1. Font rendering is server-controlled. Every printer shows the exact same output regardless of built-in fonts.
2. Gujarati support drops in by switching `FONT_PATH` to `NotoSansGujarati-Regular.ttf`. No ESC/POS Gujarati code page headaches.
3. Text size and layout are tunable and previewable. The slip can be previewed on screen in the PWA before printing.
4. Monochrome 1-bit PNG at 384px wide is ~2-5KB per slip. Fast to transfer over Bluetooth even for 87 slips.

**PWA sends image to printer**: the printer receives the PNG as a raster image via ESC/POS bitmap commands. The PWA's print module converts PNG → ESC/POS raster format → Bluetooth serial write.

**Bulk print modes**:
1. "Print All Remaining" → fetches all pending slips via `GET /bulk-batches/{bid}/print-data?remaining_only=true`, sends to printer in sequence
2. "Print Next" → fetches next uncompleted entry's slip, prints one
3. "Print Specific" → tap an entry, tap print icon

---

## Payment Tracking

### UPI Intent Link Generation

```python
def generate_upi_link(
    upi_id: str,       # agyary's UPI VPA, e.g., "gotiadarian@sbi"
    payee_name: str,    # agyary name
    amount: Decimal,
    description: str,   # "Machi - Roj Bahman, Havan Geh"
    ref_id: str = None, # payment ID for reconciliation
) -> str:
    """Generate a UPI intent link for direct payment to agyary."""
    params = {
        "pa": upi_id,
        "pn": payee_name,
        "am": str(amount),
        "cu": "INR",
        "tn": description,
    }
    if ref_id:
        params["tr"] = ref_id  # transaction reference

    return "upi://pay?" + urlencode(params)
```

This link is sent in the WhatsApp booking confirmation. Customer taps it, their UPI app opens with amount pre-filled, they authenticate and pay. Money goes directly to the agyary's account.

The system has no way to automatically confirm UPI payment receipt (that would require payment gateway integration). The panthaky marks it manually:

```
POST /api/agyaries/{a}/payments/{pid}/received
{ "method": "upi", "upi_transaction_ref": "UTR123456789" }
```

### Mobed Earnings Query

```sql
-- Monthly earnings for a specific mobed at an agyary
-- Combines machis (single mobed) + bookings (via booking_mobeds)

WITH machi_earnings AS (
    SELECT
        'machi' AS type,
        COUNT(*) FILTER (WHERE m.status = 'completed') AS count_completed,
        COALESCE(SUM(m.mobed_amount) FILTER (WHERE m.status = 'completed'), 0) AS earned,
        COALESCE(SUM(m.mobed_amount) FILTER (WHERE m.mobed_paid = true), 0) AS paid,
        COALESCE(SUM(m.mobed_amount) FILTER (
            WHERE m.status = 'completed' AND m.mobed_paid = false
        ), 0) AS pending
    FROM machis m
    WHERE m.agyary_id = :agyary_id
      AND m.assigned_mobed_id = :mobed_id
      AND m.gregorian_date >= :month_start
      AND m.gregorian_date < :month_end
),
booking_earnings AS (
    SELECT
        s.name AS service_name,
        COUNT(*) FILTER (WHERE b.status = 'completed') AS count_completed,
        COALESCE(SUM(bm.amount) FILTER (WHERE b.status = 'completed'), 0) AS earned,
        COALESCE(SUM(bm.amount) FILTER (WHERE bm.is_paid = true), 0) AS paid,
        COALESCE(SUM(bm.amount) FILTER (
            WHERE b.status = 'completed' AND bm.is_paid = false
        ), 0) AS pending
    FROM booking_mobeds bm
    JOIN bookings b ON b.id = bm.booking_id
    JOIN services s ON s.id = b.service_id
    WHERE b.agyary_id = :agyary_id
      AND bm.user_id = :mobed_id
      AND b.date_time >= :month_start
      AND b.date_time < :month_end
    GROUP BY s.name
)
SELECT * FROM machi_earnings
UNION ALL
SELECT * FROM booking_earnings;
```

Response shape:

```json
{
  "mobed": "Er. Pervez Kias",
  "period": "July 2026",
  "breakdown": [
    { "type": "Machi", "completed": 14, "earned": 4200, "paid": 3000, "pending": 1200 },
    { "type": "Jashan", "completed": 3, "earned": 4500, "paid": 4500, "pending": 0 },
    { "type": "Afringan", "completed": 8, "earned": 1600, "paid": 0, "pending": 1600 }
  ],
  "total": { "completed": 25, "earned": 10300, "paid": 7500, "pending": 2800 }
}
```

### Agyary Financial Summary Query

```sql
-- Monthly summary for the agyary
SELECT
    CASE
        WHEN p.machi_id IS NOT NULL THEN 'Machi'
        ELSE s.name
    END AS service_type,
    COUNT(*) AS total_bookings,
    SUM(p.amount) AS total_amount,
    SUM(p.amount) FILTER (WHERE p.status = 'received') AS collected,
    SUM(p.amount) FILTER (WHERE p.status = 'pending') AS outstanding,
    COUNT(*) FILTER (WHERE p.method = 'upi') AS upi_count,
    COUNT(*) FILTER (WHERE p.method = 'cash') AS cash_count
FROM payments p
LEFT JOIN bookings b ON b.id = p.booking_id
LEFT JOIN services s ON s.id = b.service_id
WHERE p.agyary_id = :agyary_id
  AND p.created_at >= :month_start
  AND p.created_at < :month_end
GROUP BY service_type
ORDER BY total_amount DESC;
```

---

## Error Handling & Failure Modes

### 1. Double-Booking Race Condition

Two customers request the same machi slot simultaneously (same roj, mah, year, geh at the same agyary).

**Defense**: the partial unique index `uq_machis_slot` on machis.

```python
async def create_machi(data: MachiCreate, db: AsyncSession):
    machi = Machi(**data.dict())
    db.add(machi)
    try:
        await db.flush()
    except asyncpg.UniqueViolationError:
        await db.rollback()
        # Slot was taken between availability check and insert
        alternatives = await get_alternative_slots(data.agyary_id, data.parsi_roj, data.parsi_mah, data.geh, db)
        raise SlotConflictError(
            message=f"Geh {GEH_NAMES[data.geh]} is already booked",
            alternatives=alternatives,
        )
```

The partial index handles this at the database level. No application-level locks, no distributed locking, no Redis. Postgres MVCC ensures exactly one INSERT succeeds for any given slot.

### 2. WhatsApp API Rate Limits

Meta enforces per-phone-number limits:

| Tier | Business-Initiated Limit | Requirement |
|---|---|---|
| Unverified | 250 / 24h | Just need a phone number |
| Tier 1 | 1,000 / 24h | Business verification |
| Tier 2 | 10,000 / 24h | Good quality rating + volume |
| Tier 3 | 100,000 / 24h | Sustained good quality |

Customer-initiated conversations (within 24h window) are unlimited.

**Mitigation**:

```python
class WhatsAppRateLimiter:
    """Track sends per phone_number_id, back off when approaching limit."""

    def __init__(self):
        self.counts: dict[str, int] = {}  # phone_number_id -> sends in current 24h
        self.reset_at: dict[str, datetime] = {}

    async def check_and_send(self, phone_number_id: str, send_fn):
        count = self.counts.get(phone_number_id, 0)
        limit = await get_rate_limit_for(phone_number_id)  # from config

        if count >= limit * 0.9:  # 90% threshold
            logger.warning(f"Approaching rate limit for {phone_number_id}: {count}/{limit}")

        if count >= limit:
            raise WhatsAppRateLimitError("Daily limit reached, retry tomorrow")

        result = await send_fn()
        self.counts[phone_number_id] = count + 1
        return result
```

At 5 agyaries with ~5 machis/day each, total daily messages (confirmations + reminders + approvals) are ~75-100. Well within unverified limits. Get business verification early to have headroom.

### 3. Webhook Delivery Failures

Meta's webhook retry policy:
- Retries failed deliveries (non-200 response) with exponential backoff
- Gives up after ~7 days of failures
- Sends a special "webhook error" notification to the WABA admin

**Our webhook must return 200 within 5 seconds.** If processing takes longer, the flow is:

```python
@router.post("/webhooks/whatsapp")
async def handle_webhook(request: Request, background_tasks: BackgroundTasks):
    body = await request.body()
    verify_signature(body, request.headers)

    # Return 200 IMMEDIATELY
    payload = json.loads(body)
    background_tasks.add_task(process_webhook_payload, payload)
    return Response(status_code=200)
```

If the background task fails (crash, exception), the message is already logged in `whatsapp_messages` (logged before processing). Worst case: we received the message but didn't respond. The customer can resend.

### 4. Server Restart Mid-Conversation

**Not a problem.** Conversation states live in Postgres (`conversation_states` table). On restart:
- Active conversations resume from their saved state
- Customer's next message loads the state and continues the flow
- The 30-minute expiry on states handles abandoned conversations

If the server was down for >30 minutes, active conversations expire. Customer starts fresh. This is acceptable because >30-minute downtime is itself an incident.

### 5. Notification Engine Crash

The engine uses `SELECT ... FOR UPDATE SKIP LOCKED` to pick up notifications. If it crashes mid-batch:
- Notifications it picked up but didn't send: status is still `pending` (the UPDATE to `sent` happens after successful send, in the same transaction)
- On restart, the engine picks them up again
- Already-sent notifications: status is `sent`, so they won't be re-sent
- The `wa_message_id` on the notification provides idempotency for deduplication

### 6. WhatsApp Webhook Deduplication

Meta can send the same webhook multiple times (at-least-once delivery). The handler must be idempotent:

```python
# Check if message already processed
existing = await db.execute(
    select(WhatsAppMessage).where(WhatsAppMessage.wa_message_id == wa_message_id)
)
if existing.scalar_one_or_none():
    return  # Already processed, skip
```

The `wa_message_id` is unique per message. Duplicate webhooks produce duplicate `wa_message_id`s. The handler checks for existence before processing.

### 7. Network Partition (Cloudflare Tunnel Down)

If the tunnel drops:
- Inbound webhooks queue at Meta (retried for up to 7 days)
- PWA shows offline banner via service worker
- PWA can cache calendar data and show read-only view
- User actions (approve, assign) queued locally, synced on reconnect

The home server should have monitoring:

```yaml
# docker-compose healthcheck
services:
  fastapi:
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 5s
      retries: 3
  cloudflared:
    healthcheck:
      test: ["CMD", "cloudflared", "tunnel", "info"]
      interval: 60s
```

Plus an external uptime monitor (UptimeRobot, free tier) pinging the public URL.

### 8. Database Connection Pool Exhaustion

```python
# database.py
engine = create_async_engine(
    DATABASE_URL,
    pool_size=10,        # 10 connections for the API
    max_overflow=5,      # 5 extra under load
    pool_timeout=30,     # wait 30s for a connection before erroring
    pool_recycle=3600,   # recycle connections hourly (prevents stale connections)
)
```

At 100 agyaries, peak concurrent requests might hit 20-30. Pool size of 10+5 handles this. The notification worker and recurrence worker each use their own smaller pool (2 connections each).

### 9. Handling Invalid/Malicious WhatsApp Messages

The webhook handler catches all exceptions and never crashes:

```python
async def handle_inbound_message(agyary, message, db):
    try:
        # ... processing logic
    except Exception as e:
        logger.exception(f"Error processing message {message.get('id')}: {e}")
        # Log the error but don't crash. Don't respond to the customer
        # about internal errors. The message is already logged for debugging.
```

Input validation on customer-provided data (names, dates):
- Names: strip HTML, limit to 200 chars, reject if empty
- Dates: validate Parsi date components are in valid ranges (roj 1-30, mah 1-13)
- Phone numbers: normalize to E.164, reject if invalid format
- All text inputs: no SQL injection risk (SQLAlchemy parameterized queries), but sanitize for XSS if displayed in PWA

---

## Background Workers Summary

| Worker | Runs | Frequency | Purpose |
|---|---|---|---|
| `notification_engine` | Continuous | Every 10 seconds | Send pending WhatsApp notifications |
| `recurrence_generator` | Daily | Once at 2 AM IST | Generate recurring booking instances |
| `cleanup` | Daily | Once at 3 AM IST | Expire old conversation states, delete old OTPs, archive old whatsapp_messages |

All workers are separate Docker containers sharing the same codebase but running different entrypoints. They connect to the same Postgres instance with smaller connection pools.

```yaml
# docker-compose.yml (worker services)
notification-worker:
  build: ./backend
  command: python -m app.workers.notification_engine
  environment: *backend-env
  depends_on: [postgres]
  restart: unless-stopped

recurrence-worker:
  build: ./backend
  command: >
    bash -c "while true; do
      python -m app.workers.recurrence_generator;
      sleep 86400;
    done"
  environment: *backend-env
  depends_on: [postgres]
  restart: unless-stopped

cleanup-worker:
  build: ./backend
  command: >
    bash -c "while true; do
      python -m app.workers.cleanup;
      sleep 86400;
    done"
  environment: *backend-env
  depends_on: [postgres]
  restart: unless-stopped
```
