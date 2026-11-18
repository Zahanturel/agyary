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

Button (URL, dynamic): **Message them**, `https://wa.me/[mobed's number without +]`

## 2. To the mobed who will pray: `prayer_details_mobed`

> You will pray for **[departed]** at **[place]**. Bungli: **[bungli]**. Geh-saarnu:
> **[day and geh]**. Uthamna: **[day and time]**. The family's contact is **[family name]**,
> **[family number]**. Thank you for your service.

Button (URL, dynamic): **Message the family**, `https://wa.me/[family number without +]`

Sent to the panthaky (or mobed) who accepted in the app, and to each mobed who answers "Yes" to
message 4. A blank the record does not have is sent as "not fixed yet".

## 3. To the family: `prayers_mobed_family`

> The prayers for **[departed]** will be offered by **[mobed's name]** of **[agyari]**. You can
> reach them on **[mobed's number]**. May the departed soul rest in peace.

Button (URL, dynamic): **Message the mobed**, `https://wa.me/[mobed's number without +]`

Sent only when the manager's tick recorded the family's agreement to hear from Mobed Diary (the
tick's words become: "The family agreed to share their name and number with this agyari, and to
get WhatsApp messages about the prayers from Mobed Diary"). A STOP from the family is honoured.

## 4. To the agyari's mobeds, asking who can pray: `prayer_request_mobeds` (owner's idea, 18 Nov)

> Prayers are needed for **[departed]** at **[place]**. Geh-saarnu: **[day and geh]**. Uthamna:
> **[day and time]**. **[panthaky's name]** of **[agyari]** asks whether you can pray.

Quick-reply buttons: **Yes, I can pray** / **Not this time**

No family details in this message. **Every "Yes" is shown to the panthaky, who picks who goes**
(owner, 18 Nov 2026). Only those picked get message 2 (the details). Those not picked get a
short free-form reply inside WhatsApp's 24-hour window ("Thank you. Enough mobeds are going this
time."), which needs no template. Payment stays with the panthaky, outside the app.

Who gets it: the agyari's approved mobeds in the app, plus mobeds the panthaky adds by name and
number, each added one only with the panthaky's tick that they agreed to get these WhatsApp
messages from Mobed Diary. A STOP from a mobed is honoured.

---

## What the owner does

1. Read and change the wording above if wanted.
2. In WhatsApp Manager (Meta Business), create the templates with these names, category Utility,
   language English, with the URL / quick-reply buttons. Submit.
3. When Meta approves them, tell the session; starting to send is a setting, not a code change.
