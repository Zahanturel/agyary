# Agyary Frontend & UX - Document 3

Design north star, from the survey: *"Any app or software easy to manage and understand to all which can track who's prayer is coming on which roj, 1 day before reminder to panthaky will solve most of problems."* -- Er. Adil Zaroliwala, Valsad.

Every screen is designed for the person least likely to understand it: the 55-year-old panthaky's wife who currently manages bookings with a notebook and phone calls.

---

## 1. PWA Screen Map

### Navigation Hierarchy

```
Login (OTP)
  │
  ├── Agyary Selector (if user has multiple agyaries)
  │
  └── Main App (bottom tab bar, 4 tabs)
        │
        ├── [Tab 1] Dashboard          ← default landing screen
        │     ├── Today's Schedule
        │     ├── Pending Approvals (inline)
        │     └── Quick Actions FAB
        │
        ├── [Tab 2] Calendar
        │     ├── Month View (Parsi primary)
        │     ├── Day View (tap a day)
        │     │     ├── Geh Slots (machis)
        │     │     └── Timed Events (bookings)
        │     └── Search (roj/mah name)
        │
        ├── [Tab 3] People
        │     ├── Customers tab
        │     │     ├── Customer list (search)
        │     │     └── Customer detail (booking history)
        │     └── Mobeds tab (admin only)
        │           ├── Mobed roster
        │           └── Mobed detail (schedule + earnings)
        │
        └── [Tab 4] More
              ├── Payments & Earnings
              │     ├── Agyary summary (admin)
              │     └── My earnings (mobed)
              ├── Bulk Ceremonies
              ├── Services (admin)
              ├── Settings
              │     ├── Agyary profile
              │     ├── Notification preferences
              │     ├── Printer setup
              │     └── Calendar system
              └── About / Help
```

### Who Sees What

| Screen | Panthaky | Caretaker | Mobed |
|---|---|---|---|
| Dashboard | Full: all bookings, approvals, all actions | Same as Panthaky | Filtered: own assignments only, earnings |
| Calendar | Full: all slots, all bookings, can create/edit | Same as Panthaky | Read-only: sees all bookings but can't create |
| People > Customers | Full access, can create/edit | Same as Panthaky | Read-only list |
| People > Mobeds | Full: roster, earnings, assignments | Same as Panthaky | Hidden tab |
| Payments | Agyary financial summary, mark received | Same as Panthaky | Own earnings only |
| Bulk Ceremonies | Full access | Full access | Read-only (see assigned batches) |
| Services | Create, edit, pricing | Same as Panthaky | Hidden |
| Settings | All settings | All settings | Own preferences only (reminder timing) |

Mobed PWA experience is intentionally minimal. Their primary interface is WhatsApp. The PWA is for checking their schedule and earnings.

---

## 2. Dashboard Design

### Panthaky / Caretaker Dashboard

One scrollable screen. No tabs. Everything important is visible without tapping.

```
┌─────────────────────────────────────────┐
│  Goti Adarian                     ⚙️    │  ← agyary name, settings gear
│  Roj Adar, Mah Aspandard          │  ← today's Parsi date
│  Saturday, 19 July 2026                 │  ← Gregorian date
├─────────────────────────────────────────┤
│                                         │
│  ⏳ PENDING APPROVAL (2)                │  ← orange badge, most urgent first
│                                         │
│  ┌─────────────────────────────────────┐│
│  │ MACHI                              ││
│  │ Jaidev Patel                       ││
│  │ Roj Bahman, Havan Geh (July 23)    ││
│  │ 3 names                            ││
│  │                                    ││
│  │  [✓ Approve]  [✕ Decline]         ││  ← inline action buttons
│  └─────────────────────────────────────┘│
│  ┌─────────────────────────────────────┐│
│  │ JASHAN (offsite)                   ││
│  │ Roshan Mistry                      ││
│  │ July 24, 10:00 AM                  ││
│  │ 123 Marine Drive, Flat 4B          ││
│  │                                    ││
│  │  [✓ Approve]  [✕ Decline]         ││
│  └─────────────────────────────────────┘│
│                                         │
├─────────────────────────────────────────┤
│                                         │
│  TODAY'S SCHEDULE                       │
│                                         │
│  Havan Geh                              │
│  ┌─────────────────────────────────────┐│
│  │ ● MACHI - Patel Family        ₹300 ││  ← green dot = confirmed
│  │   Er. Pervez assigned              ││
│  │   Payment: Received (UPI)          ││
│  └─────────────────────────────────────┘│
│                                         │
│  Rapithwin Geh                          │
│  ┌─────────────────────────────────────┐│
│  │ ● MACHI - Mistry Family       ₹300 ││
│  │   No mobed assigned                ││  ← yellow warning
│  │   Payment: Pending                 ││
│  └─────────────────────────────────────┘│
│                                         │
│  Ujiran Geh                             │
│  ┌─────────────────────────────────────┐│
│  │ ○ Available                        ││  ← grey, open slot
│  └─────────────────────────────────────┘│
│                                         │
│  Aiwisruthrem Geh                       │
│  ┌─────────────────────────────────────┐│
│  │ ○ Available                        ││
│  └─────────────────────────────────────┘│
│                                         │
│  Ushahin Geh                            │
│  ┌─────────────────────────────────────┐│
│  │ ○ Available                        ││
│  └─────────────────────────────────────┘│
│                                         │
│  ── Other Events ──                     │
│  ┌─────────────────────────────────────┐│
│  │ JASHAN 10:00 AM                    ││
│  │ Dastoor Family, offsite            ││
│  │ Er. Zahan assigned                 ││
│  └─────────────────────────────────────┘│
│                                         │
├─────────────────────────────────────────┤
│                                         │
│  TOMORROW                               │
│  Roj Avan, Mah Aspandard (July 20)      │
│  3 machis booked, 2 gehs available      │  ← summary line, tap to expand
│                                         │
└─────────────────────────────────────────┘

          [+ New Booking]                    ← FAB (floating action button)
                                              opens quick-create sheet

┌────────────────────────────────────────┐
│  [🏠]    [📅]    [👥]    [⋯]          │  ← bottom tab bar
│ Dashboard Calendar  People   More      │
└────────────────────────────────────────┘
```

**Color coding:**
- Green dot (●): confirmed/assigned
- Yellow dot: approved but no mobed assigned, or payment pending
- Grey circle (○): available slot
- Red dot: mobed_declined, needs attention
- Blue dot: recurring instance (auto-confirmed)

**Tap targets:**
- Tap a booking card → detail view (names, payment, notes, actions)
- Tap "Available" slot → opens machi creation pre-filled with that geh
- Tap "Tomorrow" summary → expands to show tomorrow's full schedule
- FAB (+) → bottom sheet with "New Machi" / "New Booking" / "Bulk Ceremonies"

### Mobed Dashboard

Stripped down. Only their assignments.

```
┌─────────────────────────────────────────┐
│  Er. Pervez Kias                  ⚙️    │
│  Roj Adar, Mah Aspandard               │
│  Saturday, 19 July 2026                 │
├─────────────────────────────────────────┤
│                                         │
│  TODAY                                  │
│                                         │
│  ┌─────────────────────────────────────┐│
│  │ MACHI - Havan Geh                  ││
│  │ Patel Family at Goti Adarian       ││
│  │ 3 names  [🖨️ Print]               ││  ← print slip button
│  │                                    ││
│  │  [Mark Complete]                   ││
│  └─────────────────────────────────────┘│
│                                         │
│  ┌─────────────────────────────────────┐│
│  │ JASHAN - 10:00 AM                  ││
│  │ Dastoor Family                     ││
│  │ 123 Marine Drive, Flat 4B          ││
│  │ 5 names  [🖨️ Print]               ││
│  │                                    ││
│  │  [Mark Complete]                   ││
│  └─────────────────────────────────────┘│
│                                         │
│  No more events today.                  │
│                                         │
├─────────────────────────────────────────┤
│                                         │
│  THIS MONTH                             │
│  Machis: 14  |  Jashans: 3  |  Other: 2│
│  Earned: ₹10,300                        │
│  Paid: ₹7,500  |  Pending: ₹2,800      │
│                                         │
└─────────────────────────────────────────┘
```

---

## 3. Calendar View

### Month View: Parsi-Primary Grid

The calendar shows one Parsi Mah at a time as a 6x5 grid (30 Rojs). NOT a Gregorian month grid with Parsi labels. Reason: the entire booking system runs on Parsi dates. Priests think in Rojs and Mahs. The Gregorian date is supplementary information.

```
┌─────────────────────────────────────────┐
│  ◀  Mah Aspandard (1396 YZ)  ▶         │  ← swipe or tap arrows to change Mah
│     June 20 - July 19, 2026            │  ← Gregorian range for reference
├─────────────────────────────────────────┤
│                                         │
│  Mon   Tue   Wed   Thu   Fri   Sat      │  ← Gregorian day-of-week header
│                                         │  (Parsi calendar has no weeks,
│                                         │   but the grid needs structure.
│                                         │   Align Roj 1 to its Gregorian DOW)
│                                         │
│  ┌─────┬─────┬─────┬─────┬─────┬─────┐ │
│  │     │     │  1  │  2  │  3  │  4  │ │  Roj numbers
│  │     │     │Horm │Bahm │Ardi │Shah │ │  Roj names (abbreviated)
│  │     │     │20/6 │21/6 │22/6 │23/6 │ │  Gregorian dates (small)
│  │     │     │     │ ●●  │     │ ●   │ │  dots = bookings that day
│  ├─────┼─────┼─────┼─────┼─────┼─────┤ │
│  │  5  │  6  │  7  │  8  │  9  │ 10  │ │
│  │Aspa │Khor │Amar │Daep │Adar │Avan │ │
│  │24/6 │25/6 │26/6 │27/6 │28/6 │29/6 │ │
│  │ ●●● │     │ ●   │     │●●●●●│ ●●  │ │  ← 5 dots = fully booked
│  ├─────┼─────┼─────┼─────┼─────┼─────┤ │
│  │ ... continuing through Roj 30 ...  │ │
│  └─────────────────────────────────────┘ │
│                                         │
│  ● Booked   ○ Available   ◉ Today       │  ← legend
│                                         │
│  [🔍 Search by Roj or Mah]             │  ← search bar at bottom
│                                         │
└─────────────────────────────────────────┘
```

**Grid layout logic:**
- Each Mah has exactly 30 cells (Roj 1-30)
- Roj 1 of the Mah starts at whatever Gregorian day-of-week it falls on
- The grid is NOT a 7-column week grid. It's a 6x5 grid reading left-to-right, top-to-bottom. The day-of-week header just provides orientation.
- Each cell shows: Roj number (large), Roj name (abbreviated, 4 chars), Gregorian date (small), and booking dots

Actually, rethinking this. A 6x5 grid (6 columns, 5 rows) for 30 days is clean and predictable. The day-of-week header is misleading because Roj 1 won't always start on Monday. Let me drop the DOW header and just use a pure 6x5 grid:

```
┌─────────────────────────────────────────┐
│  ◀  Mah Aspandard (1396 YZ)  ▶         │
│     June 20 - July 19, 2026            │
├─────────────────────────────────────────┤
│                                         │
│  ┌──────┬──────┬──────┬──────┬──────┬──────┐
│  │  1   │  2   │  3   │  4   │  5   │  6   │
│  │Hormaz│Bahman│Ardibe│Shahre│Aspand│Khorda│
│  │20 Jun│21 Jun│22 Jun│23 Jun│24 Jun│25 Jun│
│  │      │ ●●   │      │ ●    │ ●●●  │      │
│  ├──────┼──────┼──────┼──────┼──────┼──────┤
│  │  7   │  8   │  9   │ 10   │ 11   │ 12   │
│  │Amarda│Daepad│ Adar │ Avan │Khorsh│Mohor │
│  │26 Jun│27 Jun│28 Jun│29 Jun│30 Jun│ 1 Jul│
│  │ ●    │      │●●●●● │ ●●   │      │ ●    │
│  ├──────┼──────┼──────┼──────┼──────┼──────┤
│  │ 13   │ 14   │ 15   │ 16   │ 17   │ 18   │
│  │ Tir  │ Gosh │DaePaM│Meher │Srosh │Rashn │
│  │ 2 Jul│ 3 Jul│ 4 Jul│ 5 Jul│ 6 Jul│ 7 Jul│
│  │      │ ●    │      │ ●●   │ ●    │      │
│  ├──────┼──────┼──────┼──────┼──────┼──────┤
│  │ 19   │ 20   │ 21   │ 22   │ 23   │ 24   │
│  │Fravar│Behra │ Ram  │Govad │DaePaD│ Din  │
│  │ 8 Jul│ 9 Jul│10 Jul│11 Jul│12 Jul│13 Jul│
│  │ ●●   │      │ ●●●  │      │ ●    │      │
│  ├──────┼──────┼──────┼──────┼──────┼──────┤
│  │ 25   │ 26   │ 27   │ 28   │ 29   │ 30   │
│  │Ashish│Ashta │Asman │Zamya │Maresh│Anera │
│  │14 Jul│15 Jul│16 Jul│17 Jul│18 Jul│19 Jul│
│  │      │ ●●   │      │ ●●●● │ ●    │●●●●● │
│  └──────┴──────┴──────┴──────┴──────┴──────┘
│                                         │
│  ◉ Today (Roj 30)                       │
│  ● = booked geh    ○ = available geh    │
│                                         │
└─────────────────────────────────────────┘
```

**6x5 grid: 6 columns, 5 rows = 30 cells.** Exactly one Parsi Mah. Clean, predictable, no wasted cells. Each cell is tappable.

**Dots represent geh slots:** each dot is one booked geh. Max 5 dots per cell (all 5 gehs booked). Fewer dots = open slots. This gives an instant visual of how booked any given day is.

**Today is highlighted** with a distinct background color (light blue or gold border).

### Gatha Days

After Roj 30 of Mah Aspandard (last month of the year), 5 Gatha days appear. These display as a separate row below the grid:

```
│  GATHA DAYS                             │
│  ┌──────┬──────┬──────┬──────┬──────┐   │
│  │  G1  │  G2  │  G3  │  G4  │  G5  │   │
│  │Ahunav│Ushtav│Spenta│Vohukh│Vahish│   │
│  │20 Jul│21 Jul│22 Jul│23 Jul│24 Jul│   │
│  │      │ ●    │      │      │      │   │
│  └──────┴──────┴──────┴──────┴──────┘   │
```

For Fasli leap years, a 6th Gatha cell appears.

### Day View

Tap any cell in the month grid to see the day view:

```
┌─────────────────────────────────────────┐
│  ← Back                                │
│                                         │
│  Roj Bahman (2), Mah Aspandard          │
│  Monday, 21 June 2026                   │
│                                         │
├─────────────────────────────────────────┤
│                                         │
│  MACHI SLOTS                            │
│                                         │
│  ┌─────────────────────────────────────┐│
│  │ Havan Geh                          ││
│  │ ● Patel Family - MACHI        ₹300 ││
│  │   Er. Pervez | Payment: ✓ UPI      ││
│  │   [View] [🖨️ Print]               ││
│  └─────────────────────────────────────┘│
│                                         │
│  ┌─────────────────────────────────────┐│
│  │ Rapithwin Geh                      ││
│  │ ● Mistry Family - MACHI       ₹300 ││
│  │   No mobed | Payment: pending      ││
│  │   [View] [Assign Mobed]            ││
│  └─────────────────────────────────────┘│
│                                         │
│  ┌─────────────────────────────────────┐│
│  │ Ujiran Geh                         ││
│  │ ○ Available                        ││
│  │   [+ Book Machi]                   ││  ← tap to create machi for this slot
│  └─────────────────────────────────────┘│
│                                         │
│  ┌─────────────────────────────────────┐│
│  │ Aiwisruthrem Geh                   ││
│  │ ○ Available                        ││
│  │   [+ Book Machi]                   ││
│  └─────────────────────────────────────┘│
│                                         │
│  ┌─────────────────────────────────────┐│
│  │ Ushahin Geh                        ││
│  │ ○ Available                        ││
│  │   [+ Book Machi]                   ││
│  └─────────────────────────────────────┘│
│                                         │
│  ── OTHER EVENTS ──                     │
│                                         │
│  ┌─────────────────────────────────────┐│
│  │ 10:00 AM - JASHAN                  ││
│  │ Dastoor Family (offsite)           ││
│  │ 123 Marine Drive, Flat 4B          ││
│  │ Er. Zahan | ✓ Paid                 ││
│  │ [View] [🖨️ Print]                 ││
│  └─────────────────────────────────────┘│
│                                         │
│  [+ Add Event]                          │
│                                         │
└─────────────────────────────────────────┘
```

All 5 geh slots always visible, even empty ones. The empty slots are invitations to book. Tap "+ Book Machi" on an available slot and the machi creation form opens pre-filled with that date and geh. This is one tap into the 2-tap flow.

### Calendar Search

The search bar at the bottom of the month view. Accepts:

- Roj name: "Bahman" → highlights all Roj 2 cells across visible months, jumps to next Roj Bahman
- Mah name: "Fravardin" → navigates to Mah Fravardin
- "Roj Bahman Mah Fravardin" → navigates directly to that cell
- Gregorian date: "July 23" → converts to Parsi and navigates
- Customer name: "Patel" → shows all days with Patel bookings highlighted

Search is a simple text input with autocomplete for Roj and Mah names.

### Month Navigation

- Swipe left/right on the grid to go to next/previous Mah
- Tap the Mah name in the header to open a Mah picker (list of 12 months + Gatha)
- Tap the year to open a year picker
- "Today" button (floating, bottom-right of calendar) snaps back to current date

---

## 4. The 2-Tap Machi Booking (Manual Entry)

This is the most used flow in the entire system. Phone rings. Operator picks up. Behdin says "I want a machi on Roj Bahman, Havan Geh." Operator needs to check availability, enter the booking, and confirm, all while on the phone. Target: under 10 seconds from app open to booking confirmed.

### Flow: Happy Path

**Tap 0: App is already open on Dashboard.**

The FAB (+) button is always visible. Or they tapped an available slot in the calendar.

**Tap 1: Tap FAB → Bottom sheet appears:**

```
┌─────────────────────────────────────────┐
│  Quick Create                           │
│                                         │
│  [🔥 New Machi]     [📋 New Booking]   │
│                                         │
│  [📦 Bulk Ceremonies]                   │
└─────────────────────────────────────────┘
```

Tap "New Machi".

**Screen: Machi Creation (single scrollable form)**

```
┌─────────────────────────────────────────┐
│  ← Cancel          New Machi    [Save]  │
├─────────────────────────────────────────┤
│                                         │
│  CUSTOMER                               │
│  ┌─────────────────────────────────────┐│
│  │ 🔍 Search by name or phone...      ││  ← typeahead search
│  ├─────────────────────────────────────┤│
│  │ Recent:                            ││
│  │  Patel Family  (+91 98765...)      ││  ← tap to select
│  │  Mistry Family (+91 98764...)      ││
│  │  Dastoor Family (+91 98763...)     ││
│  ├─────────────────────────────────────┤│
│  │  [+ New Customer]                  ││  ← only if not found
│  └─────────────────────────────────────┘│
│                                         │
│  DATE                                   │
│  ┌─────────────────────────────────────┐│
│  │ Roj: [▾ Bahman        ]            ││  ← dropdown, 30 Roj names
│  │ Mah: [▾ Aspandard     ]            ││  ← dropdown, 12 Mah names
│  │                                    ││
│  │ = Monday, 21 June 2026             ││  ← auto-computed Gregorian
│  │                                    ││
│  │ Or enter Gregorian: [📅]           ││  ← date picker alternative
│  └─────────────────────────────────────┘│
│                                         │
│  GEH                                    │
│  ┌─────────────────────────────────────┐│
│  │ ○ Havan        ✓ Available          ││  ← radio buttons
│  │ ○ Rapithwin    ✓ Available          ││     availability checked
│  │ ○ Ujiran       ✕ Booked            ││     live as Roj/Mah changes
│  │ ○ Aiwisruthrem ✓ Available          ││
│  │ ○ Ushahin      ✓ Available          ││
│  └─────────────────────────────────────┘│
│                                         │
│  NAMES (optional now, add later)        │
│  ┌─────────────────────────────────────┐│
│  │ [+ Add Names]                      ││  ← expands name entry
│  │ Or: [Use last booking's names]     ││  ← if returning customer
│  └─────────────────────────────────────┘│
│                                         │
│  AMOUNT                                 │
│  ┌─────────────────────────────────────┐│
│  │ ₹ [300]                  auto-fill ││  ← from service default_price
│  └─────────────────────────────────────┘│
│                                         │
│  ASSIGN MOBED (optional)                │
│  ┌─────────────────────────────────────┐│
│  │ [▾ Select mobed or leave blank   ] ││
│  └─────────────────────────────────────┘│
│                                         │
│  NOTES                                  │
│  ┌─────────────────────────────────────┐│
│  │ Monthly satum for departed...      ││
│  └─────────────────────────────────────┘│
│                                         │
│         [Save Machi]                    │  ← big green button
│                                         │
└─────────────────────────────────────────┘
```

**Tap 2: Tap "Save Machi".**

Machi created with `auto_approve = true` (bypasses requested state since the operator is the authority). Status goes directly to `approved` or `assigned` if mobed is selected. Customer gets WhatsApp confirmation automatically.

**Total: 2 meaningful taps** (FAB + Save). Everything else is filling in the form, which is fast because:
- Customer search has typeahead with recent customers at the top
- Roj and Mah are dropdowns (no typing)
- Geh is radio buttons with live availability
- Amount auto-fills from service config
- Names and mobed are optional, can add later
- Notes are optional

### Flow from Calendar Day View (even faster)

Operator is already looking at a day. Taps "+ Book Machi" on an available geh slot.

The form opens pre-filled with: Roj, Mah, Year, AND the selected Geh. Only the customer needs to be selected. One-tap save.

### Name Entry (expanded)

When "+ Add Names" is tapped:

```
│  NAMES                                  │
│  ┌─────────────────────────────────────┐│
│  │ Title        Name                   ││
│  │ [▾ Ervad ] [____________________]  ││  ← title dropdown + name input
│  │ [▾ Osti  ] [____________________]  ││
│  │ [▾ Khud  ] [____________________]  ││
│  │                                    ││
│  │ [+ Add Name]   [+ Add Departed]    ││
│  └─────────────────────────────────────┘│
```

Title dropdown options: Ervad, Behdin, Osta, Osti, Khud

For departed names: "Add Departed" opens paired entry:

```
│  │ DEPARTED (pair)                    ││
│  │ [▾ Ervad ] [____________________]  ││  ← name 1
│  │ [▾ Ervad ] [____________________]  ││  ← name 2 (paired)
│  │ [+ Add Another Pair]              ││
```

Names auto-save when the machi is saved. They can be edited later from the machi detail view.

---

## 5. WhatsApp Conversation Trees for Behdins

All messages below are within the 24h customer-initiated window (free interactive messages, no template cost) unless marked as [TEMPLATE].

### First-Time Customer Greeting

Customer scans QR code or opens wa.me link and sends any message.

```
SYSTEM → Interactive List Message:

Header: "{agyary_name}"
Body: "Jai Sali! Welcome to {agyary_name}. How can we help you today?"

Action button: "Choose an option"
Sections:
  Section "Book":
    - id: "book_machi"    | title: "Book a Machi"
    - id: "book_service"  | title: "Book a Service"
  Section "Other":
    - id: "my_bookings"   | title: "My Bookings"
    - id: "contact"       | title: "Contact {panthaky_name}"
```

### Returning Customer Greeting

Customer who has booked before sends a message:

```
SYSTEM → Interactive List Message:

Header: "{agyary_name}"
Body: "Jai Sali, {customer_name}! Good to hear from you.
What would you like to do?"

Action button: "Choose an option"
Sections:
  Section "Quick Rebook":
    - id: "rebook_last"   | title: "Same as last booking"
                          | description: "Machi, Roj Bahman, Havan Geh"
  Section "Book":
    - id: "book_machi"    | title: "Book a Machi"
    - id: "book_service"  | title: "Book a Service"
  Section "Other":
    - id: "my_bookings"   | title: "My Bookings"
    - id: "contact"       | title: "Contact {panthaky_name}"
```

The "Same as last booking" shortcut pre-fills the most recent booking's service type, names, and opens the date/geh selector directly.

### Machi Booking: Date Input

```
SYSTEM → Text Message:

"When would you like the Machi?

You can type:
  A Parsi date — 'Roj Bahman' or 'Roj Bahman Mah Fravardin'
  A Gregorian date — 'July 23' or '23/7'
  Or just 'tomorrow'"
```

**Customer types: "Roj Bahman"**

System needs the Mah. Sends interactive list:

```
SYSTEM → Interactive List Message:

Body: "Roj Bahman. Which Mah?"

Action button: "Select Mah"
Sections:
  Section "Months":
    - id: "mah_1"  | title: "Fravardin"
    - id: "mah_2"  | title: "Ardibehesht"
    - id: "mah_3"  | title: "Khordad"
    - id: "mah_4"  | title: "Tir"
    - id: "mah_5"  | title: "Amardad"
    - id: "mah_6"  | title: "Shahrevar"
    - id: "mah_7"  | title: "Meher"
    - id: "mah_8"  | title: "Avan"
    - id: "mah_9"  | title: "Adar"
    - id: "mah_10" | title: "Dae"
  Section "More":
    - id: "mah_11" | title: "Bahman"
    - id: "mah_12" | title: "Aspandard"
```

(10-item limit per section, so split into two sections.)

**Customer types: "July 23"**

System converts and confirms:

```
SYSTEM → Button Message:

Body: "July 23, 2026 = Roj Shahrevar (4), Mah Fravardin.
Is that correct?"

Buttons:
  - id: "date_confirm" | title: "Yes, correct"
  - id: "date_retry"   | title: "No, different date"
```

### Machi Booking: Geh Selection

After date is confirmed:

```
SYSTEM → Interactive List Message:

Body: "Roj Bahman, Mah Fravardin (July 23, 2026)

Which Geh would you like?"

Action button: "Select Geh"
Sections:
  Section "Available":
    - id: "geh_1" | title: "Havan"        | description: "Available"
    - id: "geh_3" | title: "Ujiran"       | description: "Available"
    - id: "geh_4" | title: "Aiwisruthrem" | description: "Available"
    - id: "geh_5" | title: "Ushahin"      | description: "Available"
```

Booked gehs are excluded from the list entirely. No point showing what they can't book.

### Slot Not Available (Alternatives)

If the customer typed the full request ("Roj Bahman, Havan Geh") and Havan is taken:

```
SYSTEM → Interactive List Message:

Body: "Havan Geh is booked on Roj Bahman, Mah Fravardin.

Here are some alternatives:"

Action button: "Choose a slot"
Sections:
  Section "Same day, different Geh":
    - id: "alt_same_3" | title: "Ujiran Geh"       | description: "Roj Bahman (July 23)"
    - id: "alt_same_4" | title: "Aiwisruthrem Geh"  | description: "Roj Bahman (July 23)"
    - id: "alt_same_5" | title: "Ushahin Geh"       | description: "Roj Bahman (July 23)"
  Section "Same Geh (Havan), different day":
    - id: "alt_next_1" | title: "Roj Ardibehesht"   | description: "Havan Geh (July 24)"
    - id: "alt_next_2" | title: "Roj Shahrevar"      | description: "Havan Geh (July 25)"
    - id: "alt_next_3" | title: "Roj Khordad"        | description: "Havan Geh (July 27)"
  Section "Other":
    - id: "alt_cancel"  | title: "Cancel"
    - id: "alt_contact" | title: "Contact {panthaky_name}"
```

### Name Entry via WhatsApp

After geh selection:

```
SYSTEM → Text Message:

"Please send the names for the Machi.

Type each name on a new line with a title:
  Ervad Meherzad
  Osti Farzin
  Khud Zahan

Titles: Ervad, Behdin, Osta, Osti, Khud

For departed names, add (D):
  Ervad Kaikhushru (D)

When you're done, type 'done'."
```

If returning customer with previous names:

```
SYSTEM → Button Message:

Body: "Your last booking had these names:
  Ervad Meherzad
  Osti Farzin
  Khud Zahan

Use the same?"

Buttons:
  - id: "names_same"  | title: "Yes, same names"
  - id: "names_new"   | title: "Enter new names"
  - id: "names_edit"  | title: "Edit these names"
```

### Booking Confirmation

```
SYSTEM → Button Message:

Body: "Here's your booking summary:

Machi at {agyary_name}
Roj Bahman, Mah Fravardin (July 23, 2026)
Havan Geh

Names:
  Ervad Meherzad
  Osti Farzin
  Khud Zahan

Amount: Rs. 300"

Buttons:
  - id: "confirm_booking" | title: "Confirm"
  - id: "edit_booking"    | title: "Edit"
  - id: "cancel_flow"     | title: "Cancel"
```

On confirm:

```
SYSTEM → Text Message:

"Your request has been sent to {agyary_name}.
You'll hear back shortly."
```

### Payment UPI Link

After panthaky approves (sent as template message, since this is business-initiated outside the 24h window):

```
[TEMPLATE: booking_confirmation]

SYSTEM → Button Message (template with CTA):

Body: "Er. {panthaky_name} has confirmed your Machi at {agyary_name} for
Roj Bahman, Mah Fravardin (July 23), Havan Geh.

We look forward to seeing you.

Amount: Rs. 300"

Buttons:
  - type: "url"  | title: "Pay Rs. 300 via UPI" | url: "upi://pay?pa=..."
  - type: "reply" | id: "pay_cash_{id}" | title: "Pay at agyary"
```

Note: UPI deep links work as URL buttons in WhatsApp. Tapping opens the customer's UPI app with amount pre-filled.

### Service Booking: Service Selection

```
SYSTEM → Interactive List Message:

Body: "Which service would you like to book?"

Action button: "Select service"
Sections:
  Section "Services":
    - id: "svc_jashan"   | title: "Jashan"
    - id: "svc_afringan"  | title: "Afringan"
    - id: "svc_farokshi"  | title: "Farokshi"
    - id: "svc_satum"     | title: "Satum"
    - id: "svc_navjote"   | title: "Navjote"
    - id: "svc_wedding"   | title: "Wedding"
    - id: "svc_vandidad"  | title: "Vandidad"
    - id: "svc_yazeshni"  | title: "Yazeshni"
```

After selection, flow continues with date/time input, then names, then confirmation. Same pattern as machi flow but with time instead of geh.

### My Bookings

Customer selects "My Bookings":

```
SYSTEM → Text Message:

"Your upcoming bookings:

1. Machi - Roj Bahman, Havan Geh (July 23)
   Status: Confirmed
   Amount: Rs. 300 (paid)

2. Jashan - July 28, 10:00 AM
   Status: Awaiting confirmation
   Amount: Rs. 1,500 (pending)

To cancel or reschedule, reply with the number (e.g., '1')."
```

Customer replies "1":

```
SYSTEM → Button Message:

Body: "Machi - Roj Bahman, Havan Geh (July 23)
What would you like to do?"

Buttons:
  - id: "reschedule_machi_123" | title: "Reschedule"
  - id: "cancel_machi_123"     | title: "Cancel"
  - id: "back_bookings"        | title: "Back"
```

### Cancellation

Customer taps "Cancel":

```
SYSTEM → Button Message:

Body: "Are you sure you want to cancel your Machi on
Roj Bahman, Havan Geh (July 23)?

If you've already paid, please collect your refund
directly from {agyary_name}."

Buttons:
  - id: "confirm_cancel_machi_123" | title: "Yes, cancel"
  - id: "keep_machi_123"           | title: "No, keep it"
```

On confirm:

```
SYSTEM → Text Message:

"Your Machi on Roj Bahman, Havan Geh (July 23) has been cancelled.

If you'd like to rebook, just send us a message anytime."
```

### Rescheduling

Customer taps "Reschedule":

```
SYSTEM → Text Message:

"When would you like to reschedule to?

Type a Parsi date (e.g., 'Roj Shahrevar') or Gregorian date (e.g., 'July 25')."
```

Then follows the same date → geh → confirm flow. On confirm, old booking is marked `rescheduled` and new one is created.

---

## 6. Notification Messages

Every notification template. Written to sound human, warm, professional. Not robotic.

### Panthaky: New Booking Request

```
[TEMPLATE: booking_approval_request]
Category: UTILITY

"New booking request at {agyary_name}:

{service_name}
{customer_name}
{date_display} ({gregorian_date})
{geh_or_time}
{name_count} names

Open the app to approve or decline."

+ Interactive buttons (within 24h window, sent as follow-up):
  [Approve]  [Decline]
```

### Customer: Booking Confirmed

```
[TEMPLATE: booking_confirmation]
Category: UTILITY

"Er. {panthaky_name} has confirmed your {service_name} at {agyary_name} for {date_display}, {geh_or_time}.

We look forward to seeing you.

Amount: Rs. {amount}"
```

### Customer: Booking Declined

```
[TEMPLATE: booking_declined]
Category: UTILITY

"We're sorry, your request for {service_name} on {date_display} at {agyary_name} could not be accommodated.

{reason}

You're welcome to try a different date. Just send us a message."
```

### Mobed: Assignment (with acceptance required)

```
[TEMPLATE: mobed_assignment]
Category: UTILITY

"You've been assigned a {service_name}:

{date_display} ({gregorian_date})
{geh_or_time}
{location_if_offsite}
Customer: {customer_name}

Please confirm your availability."

+ Interactive buttons:
  [Accept]  [Decline]
```

### Mobed: Assignment (informational, no acceptance required)

```
[TEMPLATE: mobed_assignment_info]
Category: UTILITY

"You have a {service_name} assigned:

{date_display} ({gregorian_date})
{geh_or_time}
Customer: {customer_name}"
```

### Customer: Mobed Confirmed

```
[TEMPLATE: booking_mobed_confirmed]
Category: UTILITY

"Your {service_name} at {agyary_name} on {date_display} will be performed by Er. {mobed_name}."
```

### Panthaky: Mobed Declined

```
[TEMPLATE: mobed_declined_alert]
Category: UTILITY

"Er. {mobed_name} has declined the {service_name} on {date_display}.

Please assign another mobed.

Open the app to reassign."
```

### Mobed/Panthaky: Ceremony Reminder

```
[TEMPLATE: ceremony_reminder]
Category: UTILITY

"Reminder: {service_name} in {minutes} minutes.

{date_display}, {geh_or_time}
Customer: {customer_name}
{name_count} names

{location_if_offsite}"
```

### Customer: Payment Link

```
[TEMPLATE: payment_link]
Category: UTILITY

"Payment for your {service_name} at {agyary_name}:

Amount: Rs. {amount}

Tap below to pay, or pay at the agyary."

+ URL button: "Pay Rs. {amount} via UPI" → upi://pay?...
+ Reply button: "Pay at agyary"
```

### Panthaky: Recurring Auto-Confirmed

```
[TEMPLATE: recurring_auto_confirmed]
Category: UTILITY

"Auto-confirmed recurring booking:

{customer_name} - {service_name}
{date_display}, {geh_or_time}

Names carried forward from original booking."
```

### Customer: Cancellation Notice

```
[TEMPLATE: booking_cancelled]
Category: UTILITY

"Your {service_name} at {agyary_name} on {date_display} has been cancelled.

{refund_note}

If you'd like to rebook, send us a message anytime."
```

Where `{refund_note}` is either:
- "If you've paid, please collect your refund at the agyary." (cash)
- "If you've paid via UPI, your refund will be processed by the agyary." (UPI)
- "" (empty if not yet paid)

### Customer: Rescheduled

```
[TEMPLATE: booking_rescheduled]
Category: UTILITY

"Your {service_name} at {agyary_name} has been moved to {new_date_display}, {new_geh_or_time}.

If this doesn't work, send us a message and we'll find another slot."
```

### Panthaky: Daily Summary (optional, if enabled)

```
[TEMPLATE: daily_schedule_summary]
Category: UTILITY

"Good morning! Today at {agyary_name}:

{machi_count} Machis
{booking_count} other events
{pending_count} pending approvals

Open the app for details."
```

---

## 7. Thermal Printer Slip Layouts

### Image Rendering Specifications

- **Width**: 384 pixels (58mm paper at 203 DPI) or 576 pixels (80mm paper)
- **Color depth**: 1-bit monochrome (black on white)
- **Font**: Noto Sans Regular (Latin), Noto Sans Gujarati (future)
- **Header font size**: 24px (Roj/Mah/Geh line)
- **Body font size**: 20px (names)
- **Small font size**: 16px (Gregorian date, notes)
- **Line height**: 28px for body, 32px for headers
- **Padding**: 16px all sides
- **Separator**: 1px dashed line, full width minus padding

### Machi Slip

```
+------------------------------------+
|                                    |
|  Roj Bahman | Mah Fravardin        |  ← 24px bold
|  Monday, 23 July 2026             |  ← 16px
|  Havan Geh                         |  ← 20px
|                                    |
|  --------------------------------  |  ← dashed separator
|                                    |
|  MACHI                             |  ← 20px bold
|  Booked by: Patel Family           |  ← 20px
|                                    |
|  --------------------------------  |
|                                    |
|  Ervad Meherzad                    |  ← 20px, living names
|  Osti Farzin                       |
|  Khud Zahan                        |
|                                    |
|  --------------------------------  |
|                                    |
|  Ervad Kaikhushru, Ervad Hormazd   |  ← 20px, departed pair
|  Behdin Roshan, Behdin Dinshaw     |  ← another departed pair
|                                    |
+------------------------------------+
```

### General Booking Slip

```
+------------------------------------+
|                                    |
|  Roj Bahman | Mah Fravardin        |
|  Monday, 23 July 2026             |
|  10:00 AM                          |  ← time instead of Geh
|                                    |
|  --------------------------------  |
|                                    |
|  JASHAN (offsite)                  |
|  Booked by: Dastoor Family         |
|  123 Marine Drive, Flat 4B         |  ← location for offsite
|                                    |
|  --------------------------------  |
|                                    |
|  Behdin Roshan Dastoor             |
|  Behdin Meher Dastoor              |
|                                    |
|  --------------------------------  |
|                                    |
|  Note: Please bring extra sukhad   |  ← notes, if any
|                                    |
+------------------------------------+
```

### Bulk Ceremony Slip (sequence)

Each slip in a bulk batch gets a sequence number:

```
+------------------------------------+
|                                    |
|  Roj Bahman | Mah Fravardin        |
|  Monday, 23 July 2026             |
|                                    |
|  --------------------------------  |
|                                    |
|  AFRINGAN           [ 14 of 87 ]   |  ← sequence number, right-aligned
|  Booked by: Patel Family           |
|                                    |
|  --------------------------------  |
|                                    |
|  Ervad Kaikhushru, Ervad Hormazd   |  ← departed pairs
|                                    |
|  --------------------------------  |
|                                    |
|  Payment: Rs. 200 (pending)        |  ← payment status on bulk slips
|                                    |
+------------------------------------+

  ← small gap, then next slip starts →

+------------------------------------+
|                                    |
|  Roj Bahman | Mah Fravardin        |
|  Monday, 23 July 2026             |
|                                    |
|  --------------------------------  |
|                                    |
|  AFRINGAN           [ 15 of 87 ]   |
|  Booked by: Mistry Family          |
|  ...                               |
```

**Bulk print ordering**: slips print in the order the entries were created (which is the order the panthaky entered them). The mobed picks up slips sequentially, performs the ceremony, and moves to the next. The PWA can reorder entries via drag-and-drop before printing.

**Between slips**: the printer feeds a small gap (8px blank, then a cut mark or dashed line). If the printer supports auto-cut, each slip is auto-cut. Otherwise, the mobed tears at the dashed line.

---

## 8. Gujarati Handling

### Language Strategy

| Surface | v1 Language | Future | Notes |
|---|---|---|---|
| PWA interface | English | English (no change) | Operators read English fine, per survey |
| WhatsApp → Behdins | English | Gujarati option | Oldest behdins may need Gujarati |
| WhatsApp → Mobeds | English | English | Priests read English |
| WhatsApp → Panthaky | English | English | Admins read English |
| Thermal printer slips | English | Gujarati option | Names may need Gujarati script |
| Roj/Mah names | English transliteration | Keep English | Standardized, no ambiguity |

### Implementation Plan

**Phase 1 (v1)**: Everything in English. Parsi terms (Roj names, Mah names, Geh names, titles) are English transliterations as defined in the handoff document.

**Phase 2 (post-launch)**: Add Gujarati for outbound WhatsApp messages to behdins. This is the highest-impact change because elderly behdins in Mumbai/Surat read Gujarati more comfortably than English.

### Gujarati Translation Boundary

Per-agyary setting: `language_preference` on `agyaries` table.

```sql
ALTER TABLE agyaries ADD COLUMN behdin_language VARCHAR(10) NOT NULL DEFAULT 'en'
    CHECK (behdin_language IN ('en', 'gu'));
```

When `behdin_language = 'gu'`, all WhatsApp messages TO BEHDINS at that agyary are sent using Gujarati template variants. Meta allows multiple language versions of the same template.

**Per-customer override is not needed for v1.** The agyary-level setting captures the dominant language preference. If a specific customer needs English at a Gujarati agyary, the panthaky can note it, but this is a v2 feature.

### Gujarati Template Registration

Each WhatsApp template is registered twice in Meta Business Manager:

```
Template: booking_confirmation
  Language: en
  Body: "Er. {1} has confirmed your {2} at {3} for {4}, {5}. We look forward to seeing you."

  Language: gu
  Body: "એર. {1} એ {3} ખાતે તમારી {2} ની {4}, {5} ના રોજ પુષ્ટિ કરી છે. અમે તમને મળવાની રાહ જોઈએ છીએ."
```

**All Gujarati strings must be verified by community members before going live.** This is conversational Parsi-Gujarati, not literary Gujarati. "2026 Gujarati that Parsis speak." (from handoff)

### Thermal Printer Gujarati

When Gujarati is enabled for slips, the server-side image renderer swaps the font:

```python
if agyary.behdin_language == 'gu':
    font_path = FONT_PATH_GUJARATI  # NotoSansGujarati-Regular.ttf
else:
    font_path = FONT_PATH           # NotoSans-Regular.ttf
```

Since we render as images (not ESC/POS text), Gujarati "just works." No code page configuration on the printer. The image bytes are the same to the printer whether it's Latin or Gujarati glyphs.

**Name transliteration**: names entered in English transliteration (e.g., "Meherzad") stay in English on slips even in Gujarati mode. Only structural text (headers like "Roj", "Mah", "Geh", "Booked by") switches to Gujarati. Names are proper nouns; transliterating them into Gujarati script is error-prone and adds no value for the mobed reading the slip.

---

## 9. Empty States and Error States

### Dashboard: No Bookings Today

```
┌─────────────────────────────────────────┐
│                                         │
│  TODAY'S SCHEDULE                       │
│                                         │
│       📅                                │
│  No bookings today.                     │
│                                         │
│  All 5 Gehs are available.             │
│                                         │
│  [+ Book a Machi]                       │
│                                         │
└─────────────────────────────────────────┘
```

### Dashboard: No Pending Approvals

The "Pending Approval" section simply doesn't appear. No placeholder, no "0 pending" message. Absence is the message.

### Calendar: Empty Day

The day view still shows all 5 geh slots as "Available" with "+ Book Machi" on each. An empty day is an invitation, not a dead end.

### People: No Customers Yet

```
┌─────────────────────────────────────────┐
│                                         │
│       👥                                │
│  No customers yet.                      │
│                                         │
│  Customers are added automatically      │
│  when they book via WhatsApp, or you    │
│  can add them manually.                 │
│                                         │
│  [+ Add Customer]                       │
│                                         │
└─────────────────────────────────────────┘
```

### Payments: No Earnings This Month (Mobed View)

```
┌─────────────────────────────────────────┐
│                                         │
│  THIS MONTH                             │
│                                         │
│  No completed ceremonies this month.    │
│  Earnings will appear here as you       │
│  complete assigned events.              │
│                                         │
└─────────────────────────────────────────┘
```

### WhatsApp Bot: System Error

When the backend throws an unhandled exception while processing a customer message:

```
SYSTEM → Text Message:

"Sorry, something went wrong on our end. Please try again in a few minutes.

If the problem continues, contact {panthaky_name} directly at {contact_phone}."
```

Never expose technical details. Never say "Error 500" or "Server unavailable." The behdin doesn't know what a server is and shouldn't have to.

### WhatsApp Bot: Invalid Input

When the customer types something the parser can't understand:

```
SYSTEM → Text Message:

"Sorry, I didn't understand that.

{context_specific_help}

Or type 'menu' to start over."
```

`{context_specific_help}` varies by conversation state:
- During date entry: "Please enter a date like 'Roj Bahman' or 'July 23'."
- During name entry: "Please enter names one per line, like 'Ervad Meherzad'. Type 'done' when finished."
- During geh selection: "Please select a Geh from the list above."
- No active state: "Send any message to see the main menu."

### WhatsApp Bot: Conversation Timeout

If the customer doesn't respond for 30 minutes (conversation state expires):

No message sent. Silence is better than "Your session has expired" (which sounds like a bank website). When the customer sends their next message, they get the welcome menu fresh. If they were mid-booking, they start over, which is fine because starting a machi booking takes 30 seconds.

### WhatsApp Bot: Agyary Not Recognized

If a message arrives for a phone_number_id not in the agyaries table:

No customer-facing message (the customer wouldn't understand "unknown agyary"). Log the error server-side for debugging. This would only happen during setup if a phone number wasn't properly registered.

### PWA: Network Offline

```
┌─────────────────────────────────────────┐
│  ⚠️ You're offline                      │
│  Showing cached data. Changes will      │
│  sync when you're back online.          │
└─────────────────────────────────────────┘
```

The service worker caches the last-loaded dashboard and calendar data. The user can still browse but can't create or modify bookings. Read-only mode with a clear banner.

### PWA: API Error (500, timeout)

```
┌─────────────────────────────────────────┐
│                                         │
│  Something went wrong.                  │
│  Please try again.                      │
│                                         │
│  [Retry]                                │
│                                         │
└─────────────────────────────────────────┘
```

A single retry button. If retry also fails, show: "If the problem continues, contact support." No technical error codes.

### PWA: Slot Already Taken (409 Conflict)

When the user tries to save a machi but the slot was just booked by someone else:

```
┌─────────────────────────────────────────┐
│                                         │
│  This Geh was just booked.              │
│                                         │
│  Available Gehs for Roj Bahman:         │
│  ○ Ujiran                               │
│  ○ Aiwisruthrem                         │
│  ○ Ushahin                              │
│                                         │
│  [Select a different Geh]  [Cancel]     │
│                                         │
└─────────────────────────────────────────┘
```

The form stays open with the data intact. Only the geh needs to change. No data loss.

---

## 10. Onboarding Flow

New agyary setup. Done by the system admin (Zahan initially) with the panthaky present.

### Step 1: Create Agyary Profile

```
┌─────────────────────────────────────────┐
│  Set Up Your Agyary                     │
│  Step 1 of 6                            │
├─────────────────────────────────────────┤
│                                         │
│  Agyary Name                            │
│  [Goti Adarian                       ]  │
│                                         │
│  City                                   │
│  [Mumbai                             ]  │
│                                         │
│  Address (optional)                     │
│  [Gamadia Colony, Tardeo              ] │
│                                         │
│  Contact Phone                          │
│  [+91 98765 43210                    ]  │
│                                         │
│  UPI ID (for payment links)             │
│  [gotiadarian@sbi                    ]  │
│                                         │
│           [Next →]                      │
│                                         │
└─────────────────────────────────────────┘
```

### Step 2: Choose Calendar System

```
┌─────────────────────────────────────────┐
│  Calendar System                        │
│  Step 2 of 6                            │
├─────────────────────────────────────────┤
│                                         │
│  Which calendar does your agyary use?   │
│                                         │
│  ◉ Shenshai (most common)              │
│    Today: Roj 9, Mah 12                │
│                                         │
│  ○ Kadmi                                │
│    Today: Roj 4, Mah 1                  │
│                                         │
│  ○ Fasli                                │
│    Today: Roj ?, Mah ?                  │
│                                         │
│  This determines how Parsi dates        │
│  are displayed throughout the app.      │
│                                         │
│      [← Back]          [Next →]         │
│                                         │
└─────────────────────────────────────────┘
```

Shows today's Parsi date for each system so the user can verify they're picking the right one. 18 of 19 survey respondents use Shenshai, so it's the default.

### Step 3: Review Default Services

```
┌─────────────────────────────────────────┐
│  Services                               │
│  Step 3 of 6                            │
├─────────────────────────────────────────┤
│                                         │
│  We've added the standard services.     │
│  Set your prices and remove any your    │
│  agyary doesn't offer.                  │
│                                         │
│  ☑ Machi             ₹[300  ]          │
│  ☑ Jashan            ₹[1500 ]          │
│  ☑ Afringan          ₹[200  ]          │
│  ☑ Farokshi          ₹[200  ]          │
│  ☑ Satum             ₹[300  ]          │
│  ☑ Navjote           ₹[5000 ]          │
│  ☑ Wedding           ₹[10000]          │
│  ☐ Vandidad          ₹[     ]          │  ← unchecked = not offered
│  ☐ Yazeshni          ₹[     ]          │
│                                         │
│  [+ Add Custom Service]                 │
│                                         │
│  Prices can be changed later in         │
│  Settings.                              │
│                                         │
│      [← Back]          [Next →]         │
│                                         │
└─────────────────────────────────────────┘
```

### Step 4: Add the Panthaky (First User)

```
┌─────────────────────────────────────────┐
│  Panthaky                               │
│  Step 4 of 6                            │
├─────────────────────────────────────────┤
│                                         │
│  Who manages bookings at this agyary?   │
│  (This is usually the Panthaky or       │
│  a family member.)                      │
│                                         │
│  Name                                   │
│  [Er. Hormuz Dadachanji              ]  │
│                                         │
│  Phone (WhatsApp)                       │
│  [+91 98765 43210                    ]  │
│                                         │
│  Role                                   │
│  ◉ Panthaky                             │
│  ○ Caretaker                            │
│                                         │
│  This person will receive booking       │
│  requests and manage the calendar.      │
│                                         │
│  You can add more mobeds and            │
│  caretakers later.                      │
│                                         │
│      [← Back]          [Next →]         │
│                                         │
└─────────────────────────────────────────┘
```

### Step 5: Connect WhatsApp

```
┌─────────────────────────────────────────┐
│  WhatsApp Setup                         │
│  Step 5 of 6                            │
├─────────────────────────────────────────┤
│                                         │
│  Connect a WhatsApp number so           │
│  customers can book via WhatsApp.       │
│                                         │
│  This is done in Meta Business          │
│  Manager. We'll guide you through       │
│  it.                                    │
│                                         │
│  WhatsApp Phone Number                  │
│  [+91 98765 43210                    ]  │
│                                         │
│  Phone Number ID (from Meta)            │
│  [__________________________________ ]  │
│                                         │
│  [📖 Setup Guide]                       │  ← opens help doc
│                                         │
│  ☐ Skip for now (add later in Settings) │
│                                         │
│      [← Back]          [Next →]         │
│                                         │
└─────────────────────────────────────────┘
```

This step can be skipped. The PWA works without WhatsApp (manual entry only). WhatsApp can be connected later.

### Step 6: Generate QR Code

```
┌─────────────────────────────────────────┐
│  Your QR Code                           │
│  Step 6 of 6                            │
├─────────────────────────────────────────┤
│                                         │
│  ┌─────────────────────┐                │
│  │                     │                │
│  │    [QR CODE IMAGE]  │                │
│  │                     │                │
│  │   wa.me/919876...   │                │
│  │                     │                │
│  └─────────────────────┘                │
│                                         │
│  Print this QR code and place it at     │
│  the agyary entrance. Customers scan    │
│  it to start booking via WhatsApp.      │
│                                         │
│  [📥 Download QR Code]                  │
│  [🖨️ Print QR Code]                    │
│                                         │
│  (Skipped if WhatsApp was not set up)   │
│                                         │
│         [Finish Setup ✓]                │
│                                         │
└─────────────────────────────────────────┘
```

After "Finish Setup", the user lands on the dashboard with a one-time welcome banner:

```
┌─────────────────────────────────────────┐
│  Welcome to {agyary_name}!              │
│                                         │
│  Your agyary is set up. Here's what     │
│  to do next:                            │
│                                         │
│  1. Add your mobeds (People tab)        │
│  2. Book your first machi (tap +)       │
│  3. Place the QR code at the agyary     │
│                                         │
│  [Got it ✕]                             │
└─────────────────────────────────────────┘
```

### Onboarding: Total Steps

6 screens. Each screen has 2-4 fields. The entire setup takes under 5 minutes. No screen requires technical knowledge except Step 5 (WhatsApp Phone Number ID from Meta), which is skippable and can be done later with admin help.

---

## PWA Technical Notes

### Service Worker

- Cache strategy: Network-first for API calls, cache-first for static assets
- Offline: show cached dashboard and calendar, disable create/edit, show offline banner
- Background sync: queue failed mutations (approve, complete, cancel) and replay on reconnect

### Install Prompt

After 3rd visit, the PWA prompts "Add to Home Screen." On Android, this installs as a standalone app with no browser chrome. On iOS, the user needs to manually add via Safari share menu.

### Performance Targets

- First Contentful Paint: < 2 seconds on 4G
- Dashboard load: < 1 second (calendar data preloaded)
- Machi creation form to submission: < 3 seconds including API round-trip
- Total app size (JS + CSS + assets): < 500KB gzipped

### Authentication Persistence

JWT stored in memory (not localStorage for XSS safety). Refresh token in httpOnly secure cookie. On app reopen, the refresh token silently gets a new access token. The user never sees a login screen unless the refresh token has expired (30 days).

### Responsive Breakpoints

- Primary target: mobile phone (360-414px width). This is the panthaky's phone.
- Secondary: tablet (768px+) for when an agyary has a dedicated tablet at the counter.
- Desktop: not a priority but should not break. Fallback to centered mobile layout.

### Printing Integration

Web Bluetooth API for direct thermal printer connection. Setup flow:

1. Settings → Printer Setup → "Connect Printer"
2. Browser shows Bluetooth device picker
3. User selects their thermal printer
4. PWA pairs and stores the device ID in memory
5. Subsequent prints auto-reconnect

Fallback for devices without Web Bluetooth: "Download Slip" button saves a PNG that can be printed via the OS print dialog.
