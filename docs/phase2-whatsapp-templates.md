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

## 2. To the mobed who will pray: `prayer_details_mobed_v2`

> You will pray for **[departed]** at **[place]**. Geh-saarnu: **[day and geh]**. Uthamna:
> **[day and time]**. The family's contact is **[family name]**, **[family number]**. Thank you for
> your service.

Six blanks, in this order: departed, place, Geh-saarnu, Uthamna, family name, family number. No
button. Sent to the panthaky (or mobed) who accepted in the app, and to each of the first mobeds who
answer "Yes" to message 4 (up to the number wanted). A blank the record does not have is sent as
"not fixed yet".

(Changed 19 Nov 2026, owner: the funeral record has no bungli any more, so the first version,
`prayer_details_mobed`, which had "Bungli: [bungli]" as its third blank, was resubmitted without
it as `prayer_details_mobed_v2`. The server's default for `WHATSAPP_PRAYER_DETAILS_TEMPLATE` is
the v2 name; a server `.env` that still names the old one must be changed, or the six blanks will
not fit the old template's seven.)

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

No family details in this message. **It goes at once when the Doongerwadi sends the request, and
the first Yeses go** (owner, 19 Nov 2026; this replaced "the panthaky picks who goes" of 18 Nov):
the first mobeds to answer "Yes", up to the record's "mobeds wanted" (2 if it gives none), get
message 2 (the details) automatically, and the panthaky is told in the app and on their phone
"<name> is going". A later "Yes" gets a short free-form reply ("Thank you. Enough mobeds are going
this time."). If the request is withdrawn or declined, each mobed who said "Yes" gets "This prayer
request was withdrawn." Both replies need no template, so they go only inside WhatsApp's 24-hour
window from the mobed's answer; after that nothing is sent. Payment stays with the panthaky,
outside the app.

Who gets it: the agyari's approved mobeds in the app whose access is on, plus mobeds the panthaky
adds by name and number, each added one only with the panthaky's tick that they agreed to get
these WhatsApp messages from Mobed Diary; not the agyari's confirmed panthakys (they have the
request in the app, and the message asks the mobeds to tell them), and not whoever sent the
request. A STOP from a mobed is honoured. Each mobed is asked once per request; the panthaky can
ask again by hand those not asked yet (someone added to the list since). The panthaky's name in the
last blank is the agyari's first confirmed panthaky, or the agyari's own name when it has none in
the app.

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
