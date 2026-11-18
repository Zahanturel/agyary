# Phase 2: WhatsApp templates (drafts for the owner)

For D10's 18 Nov 2026 amendment: when someone accepts a Doongerwadi's request with "Share my name
and number" ticked, Mobed Diary's own number sends messages. Each needs a Meta-approved template;
sending stays switched off until they are approved.

Category for all: **Utility** (about a service the person is part of; no offer, no invitation, no
"thank you for using" lines). Language: English (Gujarati later, as for the reminders). Meta's
rules respected: no blank at the very start or end, no two blanks side by side, short.

**Numbers in blanks.** The app's own rule (services/template_text.py) refuses phone numbers in text
people type, so our number cannot be used to spread numbers. Here numbers come only from a verified
account (a sign-in number), a number cleaned by services/phone.py that a panthaky or manager
entered for a specific person, never from free text. Names still pass the usual checks.

Words in **[brackets]** are the blanks. Owner's wording notes (18 Nov 2026): utility only, no
"thank you for using Mobed Diary"; the mobed's message thanks them for their service; the family's
message never says "funeral" and uses the person's name; "[mobed's name] of [agyari]" and the
mobed's number are right.

---

## 1. To the manager: `funeral_accepted_manager`

> The prayers for **[departed]** have been accepted by **[mobed's name]** of **[agyari]**.
> You can reach them on **[mobed's number]** by phone or WhatsApp.

## 2. To the mobed who will pray: `prayer_details_mobed`

> You will pray for **[departed]** at **[place]**. Bungli: **[bungli]**. Geh-saarnu:
> **[day and geh]**. Uthamna: **[day and time]**. The family's contact is **[family name]**,
> **[family number]**. Thank you for your service.

Sent to the panthaky (or mobed) who accepted in the app, and to each mobed who answers "Yes" to
message 4. A blank the record does not have is sent as "not fixed yet".

## 3. To the family: `prayers_mobed_family`

> The prayers for **[departed]** will be offered by **[mobed's name]** of **[agyari]**. You can
> reach them on **[mobed's number]**. May the ruvan of the departed attain Garothman Behesht.

(Owner, 18 Nov 2026: not "rest in peace", which is not a Zoroastrian idea. After the fourth dawn
the prayers support the soul's journey towards Garothman, the highest heaven (Karanjia, QA about
death and Dokhmenashini; Dastur Antia's guide to prayers for the departed); "attain Garothman
Behesht" is the community's own condolence wording.)

Sent only when the manager's tick recorded the family's agreement to hear from Mobed Diary (the
tick's words become: "The family agreed to share their name and number with this agyari, and to
get WhatsApp messages about the prayers from Mobed Diary"). A STOP from the family is honoured.

## 4. To the agyari's mobeds, asking who can pray: `prayer_request_mobeds` (owner's idea, 18 Nov)

> A prayer request has come to **[agyari]** for **[departed]** at **[place]**. Geh-saarnu:
> **[day and geh]**. Uthamna: **[day and time]**. Please reply to tell **[panthaky's name]** whether
> you can take it.

(Reworded 18 Nov 2026: Meta's check said the first wording, "Prayers are needed for... asks whether
you can pray", read as Marketing and would be rejected as Utility.)

Quick-reply buttons: **Yes, I can pray** / **Not this time**

No family details in this message. **Every "Yes" is shown to the panthaky, who picks who goes**
(owner, 18 Nov 2026). Only those picked get message 2 (the details). Those not picked get a
short free-form reply inside WhatsApp's 24-hour window ("Thank you. Enough mobeds are going this
time."), which needs no template. Payment stays with the panthaky, outside the app.

Who gets it: the agyari's approved mobeds in the app, plus mobeds the panthaky adds by name and
number, each added one only with the panthaky's tick that they agreed to get these WhatsApp
messages from Mobed Diary. A STOP from a mobed is honoured.

---

## Submitted to Meta (18 Nov 2026)

All four were created in WhatsApp Manager on the Mobed Diary account, Utility, English, exactly as
above. `funeral_accepted_manager` was approved within minutes; the other three were in review.

**No buttons on 1-3.** Meta refuses buttons that link straight to WhatsApp ("Direct links to
WhatsApp aren't allowed for buttons"), so the "Message them / the family / the mobed" buttons were
dropped; the number in the text is tappable in WhatsApp instead. Template 4 keeps its two
quick-reply buttons.

When all four are approved: set `FUNERAL_WHATSAPP_MODE=live` in the server's `.env` and restart
the app; then test with the owner's own numbers first.
