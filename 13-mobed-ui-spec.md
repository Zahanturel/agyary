# Mobed Diary — UI / UX specification

Every screen, every control, and what happens when you touch it.

Sections marked **[SPECIFIED]** are what the product owner described
directly. Sections marked **[NOT SPECIFIED]** exist in the build but were
never described by him — they are open to redesign and should not be
treated as settled.

Design target: a phone. This is a PWA a mobed keeps on their home screen.

---

## 0. Shell

Present on every signed-in screen.

```
┌──────────────────────────────────────────┐
│  Er. Pervez · Goti Adarian          ☰    │   ← header (dark indigo)
├──────────────────────────────────────────┤
│                                          │
│              screen content              │   ← main, max 640px, centred
│                                          │
│                                    ( + ) │   ← floating add button
└──────────────────────────────────────────┘
```

- **Header, left:** the mobed's short name, then the fire temple name.
- **Header, right:** a **menu icon — three lines. Not the word
  "Settings".** [SPECIFIED] Opens the Menu screen.
- **No bottom tab bar.** [SPECIFIED — "no machi, no behdin no settings, at
  least not the way you have done it"] The calendar *is* the app;
  everything else lives behind the menu icon.
- **Floating add button**, bottom right. Its meaning is per-screen and its
  label says which: "Add an event" on the calendar. Hidden on screens
  where adding makes no sense.
- Login and first-run screens show no header controls and no add button.

---

## 1. Sign in

Two steps.

**Step 1 — phone.** A country-code box (defaults to +91, editable) beside a
number box. One button: *Send code*.

**Step 2 — code.** A six-digit input, wide letter-spacing, numeric keypad.
Auto-submits on the sixth digit — the code arrives in another app, so the
fewer taps back the better. Below it: a name field, needed only on a first
ever sign-in. Beneath that a live countdown — *"Code expires in 4:32"* —
and once it lapses, a *Send a new code* button appears in its place. A
*Use a different number* link returns to step 1.

Wrong codes show the server's own message, including how many attempts
remain. Running out invalidates the code and immediately offers a new one.

> Sign-in is under redesign — invite links are replacing OTP. The layout
> above holds regardless; only what gets entered changes.

---

## 2. Calendar — the home screen [SPECIFIED]

The only main screen. Shows **this mobed's own events**.

```
┌──────────────────────────────────────────┐
│ [ Day │ Week │ Month ]                   │  ← view toggle
│                                          │
│  ‹        Sun, Aug 9, 2026          ›    │  ← Gregorian, primary
│           Roj Aneran, Mah Aspandard      │    calendar beneath
│                                          │
│  [Today]                [Jump to a date] │
├──────────────────────────────────────────┤
│                                          │
│   ▏ 10:00 · Jashan                       │  ← an event
│   ▏ Behdin Jaidev Mistry      [Offsite]  │
│                                          │
│   ▏ Uziran Geh · Machi (patet)           │
│   ▏ Behdin Rustom Sethna                 │
│                                          │
└──────────────────────────────────────────┘
```

**Every date, everywhere, shows the Gregorian day first with the mobed's
primary Parsi calendar beneath it.** [SPECIFIED]

### Day view [SPECIFIED — "show todays events"]

That day's events in time order. Machis show their Geh where a service
shows a clock time. Empty: *"Nothing on this day."*

There is **no Geh slot grid** — a mobed does not need the fire temple's
machi board. A machi they are responsible for is one of their events.
[SPECIFIED]

### Week view [SPECIFIED — "divided by days and scrolable"]

The week, Monday to Sunday, as sections. Each day heading carries its
Gregorian date *and* its primary-calendar reading:

```
Mon, Aug 3, 2026   Roj Fravardin
  ▏ 09:00 · Satum
  ▏ Behdin Mehta

Tue, Aug 4, 2026   Roj Behram
  Nothing.
```

Tapping a day heading opens that day.

> Scroll behaviour deliberately not designed yet — the owner said he'd
> describe the scrolls once the functionality is in.

### Month view [SPECIFIED — "events shown in the day grid and clickable"]

A **Parsi-native grid: six columns, thirty Roj.** Not a Gregorian
week-aligned month — a Parsi month is always exactly thirty days, so it
needs no leading or trailing filler. The Gatha days appear as a
thirteenth "month".

```
┌───────┬───────┬───────┬───────┬───────┬───────┐
│Jul 11 │Jul 12 │Jul 13 │Jul 14 │Jul 15 │Jul 16 │
│Hormazd│Bahman │Ardibe.│Shahre.│Aspand.│Khordad│
│       │▪Jashan│       │       │       │       │
├───────┼───────┼───────┼───────┼───────┼───────┤
```

Each cell: Gregorian date on top, primary-calendar Roj name beneath, then
up to two event labels, then *"+N more"*. Today is outlined.

**Tapping a day** reveals that day in *every* calendar the mobed keeps
available — this is where Kadmi and Fasli live, on demand:

```
┌────────────────────────────────────────┐
│ Gregorian          Mon, Jul 20, 2026   │
│ Kadmi     Roj Aspandard, Mah Fravardin │
│ Shenshai      Roj Avan, Mah Aspandard  │
│ [Open this day]              [Close]   │
└────────────────────────────────────────┘
```

Four date labels stacked in every cell would be unreadable, so they are a
tap away instead. *Open this day* switches to Day view for it. [SPECIFIED
— "clcikable when clciked switches to day view for that day"]

### Navigation

`‹` and `›` step a day, a week, or a Parsi month. Swiping left or right
does the same. *Today* returns to today. *Jump to a date* opens a panel
offering either a date picker or Roj + Mah dropdowns — the Roj/Mah path
resolves the **next occurrence** server-side, since a Roj/Mah alone has no
year.

In Month view the title itself is tappable to jump to a given Mah and year.

---

## 3. Menu [SPECIFIED]

Behind the header icon. Three sections, in this order, then sign out.

### You

```
Name        [ Er. Pervez Kias        ]  [Save name]
Phone       +919800000002
Fire temple Goti Adarian
Address     Gamadia Colony, Tardeo, Mumbai
```

Name is editable. Phone is shown as a fact, not a disabled input — it's
the sign-in identity. Fire temple name and address are shown as
information. [SPECIFIED — "name phone number and agyari name addr"]

> The fire-temple line is the *only* place the agyari appears anywhere in
> this app. There is no joining, no temple-scoped anything.

### Calendar

```
Primary calendar   [ Shenshai ▾ ]      ← Shenshai | Kadmi | Fasli

Also available          shown when you tap a day
  ☑ Shenshai   ☐ Kadmi   ☐ Fasli

                                    [Save calendar]
```

The primary is what appears beneath every date and what Roj/Mah is entered
in. Default Shenshai. [SPECIFIED — "shown under every date -> primary
calendar", all four kept, mobed may prefer Kadmi or Fasli]

Changing it must change **every** rendered Parsi date — labels, month
navigation, the event form's Roj/Mah fields, and the printed slip.

### Behdins

```
┌────────────────────────────────────────┐
│ Manage your behdins            [+]  ›  │
│ Names, numbers and their saved names   │
└────────────────────────────────────────┘
```

The whole bar is tappable and opens the behdin list. The **`+` on its
right** adds a behdin without leaving the menu. [SPECIFIED — "Manage your
behdins text with some button on the right side to add behdin from there"]

### Sign out

A quiet ghost button at the bottom. Ends the session server-side.

---

## 4. Behdin list [SPECIFIED]

```
┌────────────────────────────────────────┐
│ Behdins                          [ + ] │  ← ONE add control
│ The behdins you look after.            │
│ [ Search by name or phone            ] │
│                                        │
│ ┌────────────────────────────────────┐ │
│ │ Behdin Jaidev Mistry               │ │
│ │ +919876500011                      │ │
│ └────────────────────────────────────┘ │
│ ┌────────────────────────────────────┐ │
│ │ Farida Patel                       │ │
│ │ +919930956740                      │ │
│ └────────────────────────────────────┘ │
└────────────────────────────────────────┘
```

- Rows show **name and number**, nothing else. [SPECIFIED]
- **Exactly one add control**, an icon in the card header. **No floating
  button as well.** [SPECIFIED — "only one place not both please"]
- Search filters by name or number as you type.
- Tapping a row opens that behdin.
- **These are only this mobed's behdins.** Never the fire temple's
  register — a behdin's name and number are their own, and a colleague has
  no business reading them. Enforced on the server, not filtered in the
  client.
- Empty: *"No behdins yet — add one above, or they appear here when you
  book for them."*

**Adding** opens a small inline form — name, then a country-code + number
pair — with *Add behdin* and *Cancel*. Enter submits. The same form is
used from the menu and from the event flow; there is one add-behdin UI,
not three. If the number is already on file it opens that person's record
rather than making a duplicate.

---

## 5. Behdin detail [SPECIFIED]

```
┌────────────────────────────────────────┐
│ Behdin Jaidev Mistry            [Back] │
│ Name          [ Behdin Jaidev Mistry ] │
│ WhatsApp no.  [+91] [ 9876500011     ] │
│ 📞 Call +919876500011                  │  ← tap to dial
│                        [Save details]  │
├────────────────────────────────────────┤
│ Saved names                            │
│ Reused whenever this behdin books.     │
│                                        │
│ Pairs                two names per pair│
│ ┌────────────────────────────────────┐ │
│ │ Pair                           ×   │ │
│ │ [Ervad ▾] [ Kaikhushru         ]   │ │
│ │ [Osti  ▾] [ Banoo              ]   │ │
│ └────────────────────────────────────┘ │
│              [+ Add pair]              │
│                                        │
│ Farmayeshne         one name per line  │
│ [Behdin ▾] [ Jaidev            ]  ×    │
│              [+ Add name]              │
│                        [Save names]    │
├────────────────────────────────────────┤
│ History                                │
│ Jashan · Roj Asman, Mah Aspandard...   │
└────────────────────────────────────────┘
```

- Name and number editable. [SPECIFIED]
- **The number is a `tel:` link — one tap opens the phone's dialler.**
  [SPECIFIED — "just one click and open call option on phone"]
- **Name pairs and farmayeshne, manageable here.** [SPECIFIED] A pair is
  exactly two people and they share a status; removing one removes the
  pair. Farmayeshne are single living names. Rows are added and removed
  locally and written on *Save names*.
- History lists what this mobed has done for them.

---

## 6. Add or edit an event [NOT SPECIFIED]

> The owner confirmed events are the point of the app but never described
> this screen. What follows is what exists, not what was asked for. It is
> the most likely candidate for redesign.

A six-step wizard with a progress bar — *Step 3 of 6 · Date*.

1. **Behdin** — search your own behdins, or add a new one inline.
2. **What** — a Service/Machi toggle; then a service picker, or nothing
   further for a machi.
3. **When** — a Gregorian date field and Roj + Mah dropdowns, **kept in
   sync**: editing either updates the other, always via the server, never
   computed in the browser. A *Pick from the calendar* button opens the
   same month grid as the calendar screen.
4. **Time or Geh** — a clock time for a service, one of the five Gehs for a
   machi. Then the purpose. For services that can be performed offsite, a
   toggle that reveals a location field.
5. **Names** — the same pairs + farmayeshne editor as the behdin screen,
   pre-filled from that behdin's saved names. A tickbox writes any edits
   back to their saved list. Machi + Tandarosti shows living names only,
   no pair section. Machi + Patet is exactly one departed pair.
6. **Confirm** — a summary, then *Book it*.

If a Geh is already taken, the conflict shows the free Gehs that same day
and the next days that Geh is free, each tappable to move the event there.

---

## 7. Slip [NOT SPECIFIED in this round]

A print-ready card: fire temple, event, when, behdin and contact, then the
names. Monospaced, dashed rules, no prices anywhere. *Print* uses the
browser's print dialog; everything but the slip is hidden on paper.

The date reads in **the mobed's own primary calendar** — they print, tear
off and use these themselves.

---

## Cross-cutting rules

1. **Gregorian first, primary calendar beneath.** Everywhere.
2. **Other calendars on demand**, never stacked into a cell.
3. **One add control per screen.** Never a button and a floating button.
4. **The word "event", never "booking".**
5. **A behdin's details belong to the mobed who holds them.**
6. **Icons, not words, in the header.**
7. **Nothing agyari-shaped** beyond the menu's information line.
8. Minimum 44px touch targets; one banner at a time; a save never scrolls
   you back to the top.
