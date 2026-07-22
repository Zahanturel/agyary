# Agyary Management System - Complete Handoff Document v2

## Overview

A WhatsApp-native temple management system for Zoroastrian fire temples (agyaries). The app is the brain (scheduling, assignment, records), WhatsApp is the voice (notifications, approvals, customer communication). Built to make priests' and caretakers' lives easier, not to replace their workflows.

---

## Core Principles (Non-Negotiable)

- Dead simple. Users are not tech-savvy. Most are 25-50 year old mobeds/panthakys who use notebooks and phone calls today.
- Automate everything behind the scenes. Users see clean inputs and outputs, never machinery.
- WhatsApp is the communication layer, not a replacement for it. Don't build chat - they already use WhatsApp for that.
- The system enhances existing workflows, doesn't replace them.
- Approval-based, notification-heavy, but zero noise. Only relevant, on-point notifications.
- Minimize WhatsApp message count aggressively. Every outgoing template message costs 30-50 paisa. At 3 machis/day, a 10-message booking flow = ₹270-450/month per agyary. These mobeds won't pay 2% of profits.

---

## Tech Stack (Decided)

- **Backend:** Python 3.12 + FastAPI + SQLAlchemy (async) + Alembic + asyncpg
- **Database:** PostgreSQL 16
- **Frontend:** React PWA (not native, not Flutter). Tailwind for styling.
- **WhatsApp:** Meta Cloud API direct (no BSP like Gupshup/Wati). Free incoming, ~30-50 paisa per outgoing template message.
- **Hosting (interim):** Oracle Cloud free tier or local development on Dell Inspiron
- **Hosting (production, by Sept 2026):** Home server (Beelink SER8 / Ryzen 7 8845HS / 32GB DDR5 / 1TB or Mac Mini M4 24GB/512GB - decision pending) + Cloudflare Tunnel (free, handles SSL/DNS/DDoS, no static IP needed, works behind NAT)
- **Dependency management:** uv
- **Containerization:** Docker Compose
- **Name parsing:** Regex-based parser, NOT LLM. Titles (er./ervad, behdin, osti, osta, khud) are structured enough for pattern matching. Customer sends one message with all names, parser extracts, one confirmation message back. 2 messages instead of 8.

## Calendar Engine (BUILT - 75/75 tests passing)

Located in the existing `agyary` project scaffolded via Claude Code.

### Parsi Calendar Rules
- Three systems: Shenshai, Kadmi, Fasli
- Shenshai & Kadmi: 12 months x 30 days + 5 Gatha days = 365 days. No leap year. Drifts 1 day vs Gregorian every 4 years.
- Kadmi is exactly 30 days ahead of Shenshai.
- Fasli: same structure but adds 6th Gatha day in Gregorian leap years. Navroze fixed at March 21.

### Verified Anchor Point
- July 19, 2026 = Roj 9 (Adar), Mah 12 (Aspandard) in Shenshai
- July 19, 2026 = Roj 4 (Shahrevar), Mah 1 (Fravardin) in Kadmi
- Shenshai Navroze 2026 = August 15
- Kadmi Navroze 2026 = July 16

### 30 Roj Names (in order)
1-Hormazd, 2-Bahman, 3-Ardibehesht, 4-Shahrevar, 5-Aspandard, 6-Khordad, 7-Amardad, 8-Daepadar, 9-Adar, 10-Avan, 11-Khorshed, 12-Mohor, 13-Tir, 14-Gosh, 15-Dae-Pa-Meher, 16-Meher, 17-Srosh, 18-Rashne, 19-Fravardin, 20-Behram, 21-Ram, 22-Govad, 23-Dae-Pa-Din, 24-Din, 25-Ashishvangh, 26-Ashtad, 27-Asman, 28-Zamyad, 29-Mareshpand, 30-Aneran

### 12 Mah Names (in order)
1-Fravardin, 2-Ardibehesht, 3-Khordad, 4-Tir, 5-Amardad, 6-Shahrevar, 7-Meher, 8-Avan, 9-Adar, 10-Dae, 11-Bahman, 12-Aspandard

### 5 Gatha Days
Ahunavad, Ushtavad, Spentamad, Vohukhshathra, Vahishtoisht
(Fasli leap year adds a 6th with no traditional name)

### 5 Gehs (divisions of the day)
Havan (sunrise to noon), Rapithwin (noon to ~3pm), Uziran (~3pm to sunset), Aiwisruthrem (sunset to midnight), Ushahin (midnight to sunrise)

**CRITICAL: Ushahin Geh overnight timing.** A machi on "Roj Bahman, Ushahin Geh" where Roj Bahman starts at sunrise on July 23 means the ceremony physically happens at ~4 AM on July 24 Gregorian. The Panthaky (e.g., at Goti Adarian) goes and prays at 4am daily. The schema must store the actual ceremony datetime separately from the Parsi date anchor. Reminder scheduler and dashboard queries must use the physical ceremony datetime, not the Parsi-anchor date.

### Calendar Display Architecture
- User chooses primary calendar: Shenshai / Kadmi / Fasli
- Secondary calendar: Gregorian (always shown alongside)
- Default: Shenshai + Gregorian
- Configurable per agyary in settings
- Calendar UI: 6x5 Parsi grid (30 Rojs per Mah). Gregorian dates as small secondary text in each cell. NOT a Gregorian grid with Parsi labels - the system thinks in Rojs and Mahs.
- Gatha days: separate row between Mah 12 and Mah 1
- Swiping right from Mah 12 shows Gatha row, then Mah 1 of next year

### API Endpoints (working)
- GET /api/calendar/today?system=shenshai
- GET /api/calendar/convert?date=2026-07-19&system=kadmi

---

## WhatsApp Multi-Tenancy Architecture

One WhatsApp Business Account (WABA) via Meta Cloud API. Multiple phone numbers registered under it - one per agyary. All messages hit the same webhook endpoint. Backend routes by recipient number to correct agyary context. QR code at each agyary is a wa.me link to that agyary's number.

Scales to 100+ agyaries without additional WhatsApp accounts. No per-number monthly fee.

**Auth OTP:** Uses a dedicated system-level WABA phone number for OTPs, separate from agyary numbers. Auth is pre-agyary-selection so cannot use an agyary-specific number.

**Customer name collection:** First-time customers (unrecognized phone number) get asked for their name before booking flow begins. "Welcome! Before we begin, may we have your name?" Stored on customer record. WhatsApp profile name is unreliable (nicknames, abbreviations).

---

## Ceremony Name System

### Universal Structure

Every ceremony has names attached. The structure has two sections:

**Section 1 - Pair names:** Names in pairs. Can be departed (gujrela nu) or living (khushali nu). Multiple pairs allowed (except patet machi which is exactly 1 pair).

**Section 2 - Farmayeshne:** Single living names. The person/family paying and organizing the event. ALWAYS present as a section (not optional) for all services except machi.

### Machi-Specific Rules (Strict, No Mixing)

**Patet machi (for the departed):**
- Exactly 1 departed name pair. No more.
- No farmayeshne section.
- Example: `Er. Zahan, Er. Meherzad`

**Tandarosti machi (for the living):**
- Multiple single living names. ~15 max (soft limit, silently enforced).
- No departed pairs.
- Example:
```
Er. Zahan
Er. Meherzad
Khud Zhian
Osti Farzin
Behdin Delzeen
```

### All Other Services (Jashan, Afringan, Farokshi, Satum, Navjote, Wedding, Yazeshni, Vandidad)

Three purpose types, printed on the slip alongside the service name:

**Gujrela nu (for the departed):**
- Multiple departed name pairs required.
- Farmayeshne (living single names) always available.

**Khushali nu (for happiness of all souls):**
- Pair names can be living OR departed.
- Farmayeshne always available.

**Hama Anjuman (for the community):**
- Pair names optional (departed or living).
- Farmayeshne always available. The organizer's names go in prayers even in a community event.

### Name Titles
- **Khud** - child before navjote (any gender)
- **Osta** - boy after navjote
- **Osti** - girl after navjote
- **Ervad** - ordained priest
- **Behdin** - adult man or woman

All titles apply to both living and departed.

### Saved Name Sets (Per Customer)

Customers have saved name sets stored on their profile:
- Saved departed pairs
- Saved living names (farmayeshne)

When booking, WhatsApp flow shows: "Use your saved names? [first 2 names shown...] Yes / Edit / New set"

On confirmation, names are snapshotted onto the booking so the prayer record is immutable even if the customer edits their saved set later.

### Departed Name Pairing Rules
- Always in pairs: father-grandfather, mother-father, brother-sister, husband-wife, etc.
- No odd numbers for departed (TBD: confirm edge cases with Panthaky)
- Silent limit on total names per booking (exact limit TBD)

### Name Parsing (WhatsApp)

Regex-based, not LLM. Titles are structured enough (er./ervad, behdin, osti, osta, khud) for pattern matching. Customer sends one message with all names, parser extracts and structures them, one confirmation message back with formatted list. 2 messages total instead of 8.

### Thermal Printer Slip Format

```
JASHAN KHUSHALI
Roj Bahman | Mah Fravardin | Havan Geh
23 July 2026
─────────────────────
Booked by: Patel Family
─────────────────────
Er. Zahan, Er. Meherzad
Behdin Delzeen, Behdin Farzin
─────────────────────
Farmayeshne:
Behdin Jaidev
Osti Farzin
Khud Zhian
─────────────────────
```

For patet machi:
```
MACHI PATET
Roj Bahman | Mah Fravardin | Havan Geh
23 July 2026
─────────────────────
Er. Zahan, Er. Meherzad
─────────────────────
```

---

## Data Model

### Agyaries (tenant)
- name, city, address, calendar_system (shenshai/kadmi), contact_phone, whatsapp_number, qr_code_ref
- max_machis_per_geh (default 1, configurable)
- require_mobed_acceptance (boolean, default false - small agyaries just assign, large ones get Accept/Decline flow)
- behdin_language (default 'en', for WhatsApp message language)

### Users (operators)
- name, phone (WhatsApp), role per agyary (panthaky/mobed/caretaker)
- Many-to-many with agyaries (a mobed can work at multiple agyaries)
- Panthaky = admin role, Mobed = user role, Caretaker = admin role
- reminder_minutes_before (configurable per mobed, default 30)
- is_active flag per agyary assignment

### Customers (behdins)
- name, phone
- Many-to-many with agyaries (a family can book at multiple agyaries)
- Builds booking history over time
- Saved name sets: departed pairs + living names (farmayeshne), reusable across bookings

### Services (configurable per agyary)
- name, default_price, min_mobeds (integer, not boolean - yazeshni needs 2), typical_duration, offsite_capable (boolean)
- Standard list seeded on signup: Machi, Jashan, Navjote, Wedding, Afringan, Farokshi, Vandidad, Satum, Yazeshni
- Custom services saved permanently once created by an agyary

### Machis (separate table - slot-based)
- agyary_id, customer_id, parsi_date (roj + mah + year), geh (1-5), calendar_system
- gregorian_date (Parsi day anchor) + ceremony_datetime (actual physical time - critical for Ushahin Geh overnight)
- purpose: patet / tandarosti
- status: requested / approved / assigned / mobed_declined / completed / cancelled / rescheduled
- assigned_mobed_id (optional)
- names: structured list snapshotted from customer's saved sets
- recurrence_rule_id (if recurring)
- payment_status, payment_method, amount
- Max 1 machi per geh per day per agyary (enforced by partial unique index WHERE status NOT IN cancelled/declined)
- **Machis always use direct mobed assignment regardless of require_mobed_acceptance flag. The flag only gates booking mobed acceptance.**

### Bookings (all other services - time-based)
- customer_id, service_id, agyary_id
- date_time (Gregorian), end_time, parsi_date (stored alongside)
- ceremony_datetime (for overnight services like Vandidad)
- purpose: gujrela_nu / khushali_nu / hama_anjuman
- status: requested / approved / assigned / mobed_declined / completed / cancelled / rescheduled
- assigned_mobeds (plural via junction table - yazeshni needs 2+)
- location (if offsite - jashans at someone's home)
- names: structured list snapshotted
- payment_status, payment_method, amount
- notes

### Ceremony Names (per booking/machi)
- Polymorphic FK: machi_id OR booking_id (with CHECK constraint, exactly one non-null)
- section: 'pair' or 'farmayeshne'
- title: khud / osta / osti / ervad / behdin
- name: text
- status: living / departed
- pair_group: integer (groups pairs together)
- display_order: integer (controls print sequence)

### Recurrence Rules
- linked to a machi or booking
- pattern: "same_roj_every_mah" / "same_roj_mah_every_year" / custom
- duration: X months / X years / indefinite
- One-time approval from Panthaky, system auto-generates all future instances
- Auto-notifications as each instance approaches
- Check mobed is_active before copying assignment to generated instance. If inactive, create without mobed and notify Panthaky to assign manually.

### Bulk Batches
- For muktad/atash behram scenarios (50-100 ceremonies in hours)
- Batch grouping with progress counter
- Per-entry payment tracking
- Thermal printer prints slips in sequence

### Payments
- NOT a payment gateway / aggregator (would require RBI PA/PG authorization)
- System generates UPI intent link with the agyary's own UPI ID + exact amount pre-filled
- Customer pays directly to agyary's account
- Alternative: "Pay at agyary" for cash
- Panthaky marks payment as received in the app
- **Payment received handler MUST update parent machi/booking payment_status and payment_method in the same transaction.**
- Mobed view: "This month: 14 machis (₹X), 3 jashans (₹Y), total earned ₹W, paid ₹V, pending ₹P"
- Multi-agyary mobed: aggregate /users/{uid}/total-earnings endpoint across all agyaries
- Agyary view: total collections, per-mobed payments, outstanding customer payments

### Conversation States (WhatsApp)
- Stored in Postgres, not Redis (at this scale, extra infra not justified)
- UNIQUE constraint on (agyary_id, phone) enforces one active flow per customer
- No "session expired" message on timeout. Customer just gets fresh welcome menu when they message again.

---

## Workflows

### Machi Booking Flow (WhatsApp)
1. Behdin scans QR at agyary / opens WhatsApp chat
2. First-time: "Welcome! May we have your name?" -> store customer
3. Returning: "Welcome back [Name]!" with "Same as last booking" shortcut (shows recent booking pre-filled, one tap to rebook)
4. Service selection (interactive list message - handle >10 services with section splitting)
5. Selects Machi -> "Patet or Tandarosti?"
6. Date input (accepts both Parsi "Roj Bahman Mah Fravardin" and Gregorian "July 23"). Parser infers nearest future occurrence if Mah is already past in current Parsi year.
7. Geh selection (list of 5 Gehs)
8. System checks slot instantly
9. If available: name entry based on purpose
   - Patet: "Enter the departed name pair"
   - Tandarosti: "Enter living names, one per message, send 'done'"
   - OR: "Use saved names? [preview] Yes / Edit / New"
10. Confirmation summary -> "Your request has been sent."
11. If taken: Shows alternatives:
    - Same Geh, next 3 available Rojs (Parsi + Gregorian dates shown)
    - Same Roj, other available Gehs
    - Customer taps one
12. Panthaky gets notification: "[Customer] wants [patet/tandarosti] machi, Roj X, Geh Y" -> Approve / Decline
13. If approved: assigns mobed (direct assignment, no accept/decline flow for machis)
14. Customer gets: "Er. [Name] has confirmed your machi for Roj X, Geh Y. We look forward to seeing you."
15. UPI link sent or "pay at agyary" noted
16. 30 minutes before ceremony: reminder to assigned mobed (or Panthaky). Uses ceremony_datetime, not Parsi date anchor.
17. Thermal printer auto-prints slip

### General Service Booking Flow
Same pattern as machi but:
- Purpose: Gujrela nu / Khushali nu / Hama Anjuman
- Time-based (specific datetime), not slot-based
- Names: pair section + farmayeshne section, adapted by purpose
- Mobed assignment: may require Accept/Decline if require_mobed_acceptance is true
- For yazeshni: assigns 2+ mobeds
- Location field for offsite jashans

### Mobed Decline Recovery
- Panthaky approves and assigns mobed
- Mobed taps Decline
- Booking does NOT go to declined. Goes to mobed_declined state.
- Panthaky notified: "Er. [Mobed] declined. Reassign?" with mobed list
- Panthaky assigns new mobed
- Status returns to assigned
- Behdin is never notified about the internal reassignment

### Cancellation Flow
- Customer cancels: slot opens immediately (partial unique index handles this), Panthaky notified
- Refund handled directly between customer and agyary (we don't hold money)
- Rescheduling = cancel + new booking in one smooth WhatsApp flow

### Mobed-Initiated Reschedule
- Panthaky/mobed moves the booking
- Customer gets WhatsApp: "Your machi has been rescheduled to Roj X, Geh Y. If this doesn't work, tap here to pick another slot."
- Customer accepts or picks different slot

### Recurring Bookings
- One-time approval from Panthaky
- System auto-generates all future bookings via daily cron
- Before generating: check mobed is_active, check slot availability
- If slot conflict: skip that instance, notify Panthaky
- If mobed inactive: create without mobed, notify Panthaky to assign
- Panthaky gets notification as each instance approaches (not approval, just "Patel family recurring machi auto-confirmed")
- Individual instances can be cancelled/rescheduled independently without affecting series

### Bulk Ceremonies (Muktad / Atash Behram scale)
- 50-100 afringans in hours is normal at Atash Behrams
- Panthaky uses bulk creation flow: "Muktad batch - 87 afringans, date range, here's the list"
- Single-transaction batch creation with per-entry names and payment tracking
- Progress counter for completion tracking
- Thermal printer prints slips in sequence

---

## Thermal Printer Feature

Small Bluetooth thermal receipt printer (~₹2,000-3,000). Sits near prayer area.

**Connection:** Web Bluetooth from PWA. Server renders 1-bit monochrome PNGs at 384px (58mm paper) via Pillow. Font: Noto Sans (swap to Noto Sans Gujarati when Gujarati ships). Each slip is 2-5KB, fast over Bluetooth.

**Trigger:** Auto-print 30 minutes before ceremony (same as reminder), or bulk "print today's schedule" in morning, or on-demand per booking.

**Three print modes:**
1. Single slip (for individual bookings)
2. Today's full schedule (all ceremonies in Geh order)
3. Bulk sequence (50+ slips numbered in order for muktad)

---

## Survey Data Summary (19 responses, July 2026)

### Respondents
- 6 Panthakys, 12 Mobeds, 1 Caretaker/Manager
- Cities: Mumbai (~13), Surat (2-3), Valsad (1), Kalyan (1), Hyderabad (1)
- 18 Shenshai, 1 Kadmi (Dadyseth Agiyari)

### Machi Volume (per day)
- Range: ~0.3/day (Kalyan, 10/month) to 5+/day (Watcha Gandhi, Goti Adarian)
- Average: ~2.5/day across agyaries
- Goti Adarian (Zahan's agyary): fully booked, 5 machis/day, 365 days/year

### Services Offered (frequency in responses)
- Near-universal: Machi, Jashan, Afringan, Farokshi, Satum, Navjote, Wedding
- Common: Yazeshni (7/19), Vandidad (7/19)
- Rare/local: Navar and Maratab, Faresta, Uthamnu (shunj rat), Baj, Death rituals (Doongerwari)

### Current Booking Methods
- Phone calls: 17/19 (dominant)
- WhatsApp: 8/19
- Walk-ins: 6/19
- Record keeping: Notebooks (5), Rojmel book (1), Machi register (1), Excel for muktad only (1), Memory (implied by many)

### Pain Points
- Remembering recurring bookings: 3 mentions
- Keeping track of who booked what: 3 mentions
- Last-minute cancellations / miscommunications: 4 mentions
- Phone calls at odd hours: 1 mention
- Tracking payments, materials, stock: 1 mention
- Mobed unavailability for last-minute events: 1 mention

### System Interest
- Yes: 10/19 (53%)
- Maybe: 8/19 (42%)
- No: 0/19 (0%)

### Key Respondent Notes
- **Er. Hormuz Dadachanji (Watcha Gandhi, Mumbai):** Skeptic. "We had tried it earlier but it was not successful." Uses rojmel book + Excel for muktad. Message sent asking what they tried - response pending.
- **Er. Adil Zaroliwala (Valsad):** Product spec in his own words: "Any app or software easy to manage and understand to all which can track who's prayer is coming on which roj, 1 day before reminder to panthaky will solve most of problems."
- **Kerman Fatakia (Kalyan):** Laity data sync for broadcast messages -> v2 community engagement feature.
- **Marzban Pavri (Wadiaji Atash Behram):** Concern about full-time mobeds on daily wages. System should help mobeds track earnings.
- **Patrasp Bajan (Doongerwadi):** Death rituals only. Mobed coordination. Pinned for future, out of scope v1.

---

## Who Operates the System

- At Goti Adarian: Zahan's mother handles all booking management (not the Panthaky himself)
- Across agyaries: could be Panthaky, Panthaky's spouse, elderly caretaker, trust office assistant
- Primary users of the PWA: Panthakys and caretakers (admin view)
- Mobeds: primarily interact via WhatsApp notifications (accept/decline/reminders), can also view calendar and earnings in PWA
- Behdins (customers): WhatsApp only, never the PWA

---

## Revenue Model (deferred, under pressure)

- Original plan: markup baked into service prices (transparent to Panthaky)
- Survey reality: "these mobeds are chindi" - won't give 2% of profits
- Revenue model needs complete rethinking once system is live and value is proven
- Thermal printers potentially provided by the platform as part of onboarding
- WhatsApp message costs are a real constraint at 30-50 paisa per outgoing template

---

## Gujarati Language Support

- English primary for v1
- Gujarati needed for WhatsApp messages to older behdins (highest priority)
- Conversational Parsi-Gujarati, not literary. "2026 Gujarati that Parsis speak."
- Per-agyary behdin_language setting controls WhatsApp message language
- PWA stays English-only for v1
- Dual WhatsApp template registration (English + Gujarati) in Meta
- Print slip font: swap Noto Sans to Noto Sans Gujarati
- Name transliteration stays English regardless of language setting
- All Gujarati strings to be verified by community members before going live

---

## Audit Fixes (Apply Before Building)

### Critical
1. **Ushahin Geh overnight timing:** Store ceremony_datetime separately from gregorian_date on machis and bookings. Dashboard and reminder scheduler use ceremony_datetime. Ushahin machis happen at ~4AM next Gregorian day.
2. **Auth OTP sender:** Dedicated system-level WABA phone number for OTPs, separate from agyary numbers.
3. **Customer name collection:** Ask first-time customers for their name before booking flow begins.

### Important
4. **Payment denorm sync:** Payment received handler updates parent machi/booking payment_status in same transaction.
5. **Recurrence mobed check:** Check is_active before copying mobed assignment. If inactive, create without mobed, notify Panthaky.
6. **Parsi year inference:** When customer enters Roj/Mah and that Mah is past in current year, infer next year. If ambiguous, ask.
7. **require_mobed_acceptance scope:** Flag ONLY applies to bookings, NEVER machis. Machis always use direct assignment.
8. **Departed name pairing:** Auto-pair consecutive departed names in WhatsApp input. Panthaky can fix pairing in PWA if needed.

### Edge Cases
9. **Gatha navigation:** swipe from Mah 12 -> Gatha row -> Mah 1 next year
10. **Multi-agyary mobed earnings:** /users/{uid}/total-earnings cross-agyary endpoint
11. **Vandidad overnight:** parsi_roj/mah/year reflects ceremony start date
12. **Muktad max_machis_per_geh:** date-range override mechanism for v2
13. **WhatsApp 10-item limit:** dynamic section splitting for services list if >10

---

## Schema Deltas from Doc 1 (apply as Alembic migrations)

- 3 new statuses: assigned, mobed_declined, rescheduled
- reminder_minutes_before on agyary_users junction
- require_mobed_acceptance on agyaries
- behdin_language on agyaries
- ceremony_datetime on machis and bookings
- auth_otps table
- is_active on agyary_users junction

---

## Open Items / Pinned for Later

- [ ] Dadachanji response about failed previous attempt (message sent, awaiting reply)
- [ ] Departed name pair limit (confirm edge cases with Panthaky - odd numbers?)
- [ ] Doongerwadi / death ritual workflow (pinned, out of scope v1)
- [ ] Community engagement / newsletter feature (v2, Kerman Fatakia's request)
- [ ] Laity data synchronization (v2)
- [ ] Revenue model rethink (2% won't work, need alternative)
- [ ] Server hardware final decision (Beelink SER8 vs Mac Mini M4 24GB)
- [ ] Gujarati translation and verification
- [ ] Muktad mode / max_machis_per_geh date-range override (v2)
- [ ] Short/special machi (fewer recitations for out-of-town visitors)
- [ ] Inventory management module (deferred, not in v1)
