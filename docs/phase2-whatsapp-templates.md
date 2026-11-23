# Phase 2: WhatsApp templates (drafts for the owner)

Mobed Diary's own number sends a few WhatsApp messages about a Doongerwadi's prayer request (D10).
Each needs a Meta-approved template; sending stays switched off (`FUNERAL_WHATSAPP_MODE=off`) until
they are approved.

**Since R3.1 (built 21-22 Nov 2026, live with the owner's push):** the request is confirmed only
when enough mobeds are going ("Confirmed" in the app; called "all set" in the code), and then
everyone is told at once. The templates that go are **4 v2** (asking the mobeds) and **5 to 8**
(Confirmed). Templates **1, 2 and 3** are **not sent for requests since R3.1; kept for history**
(they went when someone tapped Accept, which is gone).

**Owner's word review (23 Nov 2026, DECISIONS D11):** templates 5, 6 and 8 say "For anything
else, please contact [contact]" (the panthaky, else the first mobed going), and template 5 closes
"May the ruvan of the late [departed] attain Garothman Behesht." None of 4 v2 and 5 to 8 had been
submitted, so they are submitted in these words.

Category for all: **Utility** (about a service the person is part of; no offer, no invitation, no
"thank you for using" lines). Language: English (Gujarati later, as for the reminders). Meta's
rules respected: no blank at the very start or end, no two blanks side by side, short.

**Numbers in blanks.** The app's own rule (services/template_text.py) refuses phone numbers in text
people type, so our number cannot be used to spread numbers. Here numbers come only from a verified
account (a sign-in number), a number cleaned by services/phone.py that a panthaky or manager
entered for a specific person, never from free text. Names still pass the usual checks. A blank
that holds several people is filled by the server, e.g. "Ervad A (+91 98xxxxxx01), Ervad B
(+91 98xxxxxx02)". A blank the record does not have is sent as "not fixed yet".

Words in **[brackets]** are the blanks. Owner's wording notes (18 Nov 2026): utility only, no
"thank you for using Mobed Diary"; the mobed's message thanks them for their service; the family's
message never says "funeral" and uses the person's name; "[mobed's name] of [agyari]" and the
mobed's number are right.

**Each template's name is a setting** in the server's `.env` (the name below is the default), so a
template approved under another name needs no code change, only the setting.

---

## The R3.1 templates (to submit)

The wording is exactly as in `docs/phase2-requests-redesign.md`, "Template drafts".

### 4 v2. To the agyari's mobeds, asking who can pray: `prayer_request_mobeds_v2`

Setting: `WHATSAPP_PRAYER_REQUEST_TEMPLATE` (default `prayer_request_mobeds_v2`). It replaces
template 4 (owner, 21 Nov 2026).

> A prayer request has come to **[agyari]** for **[departed]** at **[place]**. Geh-saarnu:
> **[day and geh]**. Uthamna: **[day and time]**. Please reply to tell **[panthaky's name]**
> whether you can take it. If you can, you will get the details once enough mobeds are going,
> and your name and number will be shared with the family.

Blanks, in this order: 1 agyari, 2 departed, 3 place, 4 Geh-saarnu (day and geh), 5 Uthamna (day
and time), 6 the panthaky's name (the one who asks, else the agyari's first confirmed panthaky,
else the agyari's own name when it has no panthaky in the app). The same six blanks as template 4.

Quick-reply buttons, **in this order**: **Yes, I can pray** / **Not this time** (the app reads the
first button as yes and the second as no).

Who gets it: the agyari's approved mobeds in the app whose access is on, and the mobeds the
panthaky added by hand with the tick that they agreed to get these messages; not its confirmed
panthakys, not whoever sent the request; never a number that replied STOP. Each is asked once per
request.

When: at Send, if the agyari's way is **Everyone at once**; when the panthaky taps **Ask everyone**
on the board; when the **safety net** fires in **Come to me first**; and to a mobed on the
**waiting list** when a place opens again (with buttons of their own for that question).

Why v2: a mobed who says Yes now waits for the others before getting the details, and their
number goes to the family; the message says both before they answer. Until v2 is approved the
server can name the old template (`WHATSAPP_PRAYER_REQUEST_TEMPLATE=prayer_request_mobeds`): the
blanks fit either.

### 5. To the family: `prayers_all_set_family`

Setting: `WHATSAPP_ALL_SET_FAMILY_TEMPLATE` (default `prayers_all_set_family`).

> The prayers for **[departed]** will be offered by **[mobeds with numbers]** of **[agyari]**.
> Geh-saarnu: **[day and geh]**. Uthamna: **[day and time]**. For anything else, please contact
> **[contact]**. May the ruvan of the late **[departed]** attain Garothman Behesht.

Blanks, in this order: 1 departed, 2 the mobeds going with their numbers, 3 agyari, 4 Geh-saarnu,
5 Uthamna, 6 the contact (the panthaky with their number; at an agyari with no confirmed panthaky
in the app, the first mobed going with their number), 7 departed again (the same words as 1: each
blank is numbered once). No button.

Who gets it: the family's contact, only if the Doongerwadi's tick recorded the family's agreement
to hear from Mobed Diary; a STOP from the family is honoured.

When: when it is **Confirmed**; and again, with the new names, when it is confirmed again after
someone going backed out and the place was filled.

### 6. To each mobed going: `prayer_details_mobed_v3`

Setting: `WHATSAPP_ALL_SET_DETAILS_TEMPLATE` (default `prayer_details_mobed_v3`).

> You will pray for **[departed]** at **[place]**. Geh-saarnu: **[day and geh]**. Uthamna:
> **[day and time]**. The family's contact is **[family name]**, **[family number]**. Mobeds
> going: **[mobeds with numbers]**. For anything else, please contact **[contact]**. Thank you for
> your service.

Blanks, in this order: 1 departed, 2 place, 3 Geh-saarnu, 4 Uthamna, 5 the family's name, 6 the
family's number, 7 the mobeds going with their numbers, 8 the contact (as in template 5).

Quick-reply button: **I can't go any more** (owner, 21 Nov 2026: a mobed going can back out from
here; their place opens and the next on the waiting list is asked).

Who gets it: each mobed going who has a number (an app mobed, the panthaky if they pray, or a
mobed added by hand), only if their Mobed Diary access is on.

When: when it is **Confirmed**, once to each person: when it is confirmed again, only the one new
to it gets it.

### 7. To the panthaky: `prayers_all_set_panthaky`

Setting: `WHATSAPP_ALL_SET_PANTHAKY_TEMPLATE` (default `prayers_all_set_panthaky`).

> All mobeds are found for **[departed]** at **[place]**: **[mobeds with numbers]**.
> Geh-saarnu: **[day and geh]**. Uthamna: **[day and time]**. The family's contact is
> **[family name]**, **[family number]**.

Blanks, in this order: 1 departed, 2 place, 3 the mobeds going with their numbers, 4 Geh-saarnu,
5 Uthamna, 6 the family's name, 7 the family's number. No button.

Who gets it: the request's panthaky (the one whose book the family went into) when they are not
praying themselves (if they pray, they get template 6 instead).

When: the first time it is **Confirmed** only (not again when it is confirmed again; they see the
new names in the app). It says "All mobeds are found" also when the panthaky confirmed with fewer.

### 8. To the Doongerwadi: `funeral_accepted_manager_v2`

Setting: `WHATSAPP_ALL_SET_MANAGER_TEMPLATE` (default `funeral_accepted_manager_v2`).

> The prayers for **[departed]** will be offered by **[mobeds' names]** of **[agyari]**. For
> anything else, please contact **[contact]**.

Blanks, in this order: 1 departed, 2 the mobeds' names (no numbers), 3 agyari, 4 the contact (as
in template 5). No button.

Who gets it: the Doongerwadi's (or prayer hall's) managers whose access is on.

When: the first time it is **Confirmed** only (they see the new names in the app afterwards).

### Short replies (no template needed)

These are plain text, so WhatsApp lets them go only inside the 24 hours after the mobed's own
answer or tap; after that nothing is sent:

- to a Yes once enough are going (they are on the waiting list): "Thank you. Enough mobeds are
  going this time. If a place opens, we may ask you again."
- to someone who said Yes, when the request is withdrawn or declined (owner's words, 23 Nov
  2026): "Sahebji [first name], this prayer request has been closed, so you are not needed for
  now, but we will keep you updated. Thank you." ([first name] skips a title typed before the
  name, as the app's "Sahebji" does; with no name: "Sahebji, this prayer request has been
  closed, ...")
- to a tap on **I can't go any more**: "Thank you for letting us know. The panthaky has been
  told." (at an agyari with no panthaky in the app: "Thank you for letting us know.")

### Settled by the owner: an agyari with no panthaky (23 Nov 2026)

Templates 5, 6 and 8 named "the panthaky", which at an agyari with no confirmed panthaky in the
app read "not fixed yet". The owner chose "For anything else, please contact [contact]": the
panthaky's name and number, or with no confirmed panthaky in the app, the first mobed going (name
and number). The drafts above and the code (services/funeral_whatsapp.py, `contact_people`) say so.

### When to switch on

1. Submit 4 v2 and 5 to 8 in WhatsApp Manager (Utility, English), exactly as above, with the
   buttons of 4 v2 and 6.
2. Wait until **all of 4 v2 and 5 to 8 are approved**.
3. In the server's `.env`: `FUNERAL_WHATSAPP_MODE=live`, then `docker compose up -d app`.
4. **First test with your own numbers only.** `REMINDERS_ALLOWLIST` is `*` on the server (it is
   shared with the reminders), so it lets everyone through: anyone on the test agyari's
   **Mobeds** list (its app mobeds and those added by hand), that Doongerwadi's **managers**, and
   the **family number** on the test record will really get messages. Check those lists first,
   so that only your own numbers are on them, before you send a test request.
5. Then try both ways (Everyone at once, Come to me first) with a test record, as in
   `docs/phase2-verify-checklist.md`.

The pause switch (Admin), STOP, the daily limits (`FUNERAL_WHATSAPP_DAILY_CAP`,
`FUNERAL_WHATSAPP_PER_AGYARI_DAILY_CAP`) and the account switch of each person (D9) all still
apply once it is live.

---

## History: the templates of 18-19 Nov 2026

### 1. To the manager: `funeral_accepted_manager` (not sent for requests since R3.1; kept for history)

Setting (kept, no longer read): `WHATSAPP_FUNERAL_MANAGER_TEMPLATE`.

> The prayers for **[departed]** have been accepted by **[mobed's name]** of **[agyari]**.
> You can reach them on **[mobed's number]** by phone or WhatsApp.

### 2. To the mobed who will pray: `prayer_details_mobed_v2` (not sent for requests since R3.1; kept for history)

Setting (kept, no longer read): `WHATSAPP_PRAYER_DETAILS_TEMPLATE`.

> You will pray for **[departed]** at **[place]**. Geh-saarnu: **[day and geh]**. Uthamna:
> **[day and time]**. The family's contact is **[family name]**, **[family number]**. Thank you for
> your service.

Six blanks, in this order: departed, place, Geh-saarnu, Uthamna, family name, family number. No
button. It went to the panthaky (or mobed) who accepted in the app, and (19-21 Nov 2026) to each of
the first mobeds who answered "Yes" to message 4.

(Changed 19 Nov 2026, owner: the funeral record has no bungli any more, so the first version,
`prayer_details_mobed`, which had "Bungli: [bungli]" as its third blank, was resubmitted without
it as `prayer_details_mobed_v2`.)

### 3. To the family: `prayers_mobed_family` (not sent for requests since R3.1; kept for history)

Setting (kept, no longer read): `WHATSAPP_PRAYERS_FAMILY_TEMPLATE`.

> The prayers for **[departed]** will be offered by **[mobed's name]** of **[agyari]**. You can
> reach them on **[mobed's number]**. May the ruvan of the departed attain Garothman Behesht.

(Owner, 18 Nov 2026: not "rest in peace", which is not a Zoroastrian idea. After the fourth dawn
the prayers support the soul's journey towards Garothman, the highest heaven (Karanjia, QA about
death and Dokhmenashini; Dastur Antia's guide to prayers for the departed); "attain Garothman
Behesht" is the community's own condolence wording.) Template 5 keeps this wish, as "May the
ruvan of the late [departed] ..." (owner, 23 Nov 2026).

### 4. To the agyari's mobeds, asking who can pray: `prayer_request_mobeds` (replaced by 4 v2)

> A prayer request has come to **[agyari]** for **[departed]** at **[place]**. Geh-saarnu:
> **[day and geh]**. Uthamna: **[day and time]**. Please reply to tell **[panthaky's name]** whether
> you can take it.

(Reworded 18 Nov 2026: Meta's check said the first wording, "Prayers are needed for... asks whether
you can pray", read as Marketing and would be rejected as Utility.)

Quick-reply buttons: **Yes, I can pray** / **Not this time**. Until R3.1 the first mobeds to say
"Yes" (up to the number wanted) got message 2 at once (owner, 19 Nov 2026). Since R3.1 nobody gets
the details at a Yes: they go to everyone when it is confirmed (template 6).

## Submitted to Meta (18 Nov 2026)

1-4 were created in WhatsApp Manager on the Mobed Diary account, Utility, English, exactly as
above. `funeral_accepted_manager` was approved within minutes; the other three were in review.

**No link buttons.** Meta refuses buttons that link straight to WhatsApp ("Direct links to
WhatsApp aren't allowed for buttons"), so the "Message them / the family / the mobed" buttons were
dropped; the number in the text is tappable in WhatsApp instead. Quick-reply buttons (4, 4 v2, 6)
are fine.
