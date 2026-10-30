"""Sharing a memorial's schedule with the family: a PDF and a message.

The mobed can download the PDF, copy or open the message in WhatsApp on their
own device, or - when it is switched on - have it sent as a PDF from the shared
Mobed Diary number. That last route is a business-initiated message, so it
needs an approved template with a document header (settings.whatsapp_share_template),
the family's consent (the same flag the reminders use), and it respects the
pause switch, the allowlist and a small daily cap per mobed. It is off until
``MEMORIAL_SHARE_SEND_MODE=live``.

Pure rendering is separate from sending so that the PDF and the text can be
tested without a network.
"""

from __future__ import annotations

import io
import logging
from datetime import date, datetime, timezone

import httpx
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.calendar.engine import GATHA_NAMES, MAH_NAMES, ROJ_NAMES
from agyary.core.config import Settings
from agyary.models import Customer, Notification
from agyary.services import guardrails, reminders, template_text, wa_send

logger = logging.getLogger(__name__)

TYPE = "memorial_share"
NOTE_MAX = 300
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December")
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def long_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{WEEKDAYS[d.weekday()]}, {d.day} {MONTHS[d.month - 1]} {d.year}"


def short_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day} {MONTHS[d.month - 1][:3]} {d.year}"


def table_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{WEEKDAYS[d.weekday()][:3]}, {d.day} {MONTHS[d.month - 1][:3]} {d.year}"


def parsi_day(roj: int | None, mah: int | None, gatha_index: int | None = None) -> str:
    """"Roj Hormazd, Mah Fravardin" for a day, or the Gatha's name."""
    if gatha_index:
        name = GATHA_NAMES[gatha_index - 1] if 0 < gatha_index <= len(GATHA_NAMES) else f"Gatha {gatha_index}"
        return f"{name} (Gatha)"
    if not roj or not mah:
        return ""
    return f"Roj {ROJ_NAMES[roj - 1]}, Mah {MAH_NAMES[mah - 1]}"


def death_day(m: dict) -> str:
    """The day of death by Roj and Mah (or its Gatha)."""
    death = m["death"]
    if death["mah"] == 13:
        return parsi_day(None, None, death["roj"])
    return parsi_day(death["roj"], death["mah"])


def clean_note(note: str | None) -> str:
    """The mobed's short note, as one tidy line of bounded length."""
    return " ".join((note or "").split())[:NOTE_MAX]


def _prayers(o: dict) -> str:
    return ", ".join(s["name"] for s in o["services"] if s["name"])


def passed_away(m: dict) -> str:
    """When they died, for the family: the date and Roj and Mah - or, for someone
    who died more than a year ago and was entered by Roj and Mah alone, only the
    Roj and Mah (there is no date to give)."""
    if m.get("long_ago") or not m.get("death_date"):
        return f"Remembered on {death_day(m)}"
    return f"Passed away on {long_date(m['death_date'])} ({death_day(m)})"


def message_text(m: dict, *, agyary_name: str, mobed_name: str, note: str = "") -> str:
    """The message to send the family: who it is for, then every date."""
    note = clean_note(note)
    lines = [
        f"Memorial prayers for {m['departed_name']}",
        f"{agyary_name} - {mobed_name}",
        passed_away(m),
    ]
    if note:
        lines += ["", note]
    lines.append("")
    for o in m["observances"]:
        prayers = _prayers(o)
        lines.append(
            f"- {short_date(o['date'])}: {o['label']}"
            + (f" ({parsi_day(o['roj'], o['mah'], o['gatha_index'])})" if o["roj"] or o["gatha_index"] else "")
            + (f" - {prayers}" if prayers else "")
        )
    return "\n".join(lines)


def short_message(m: dict, *, agyary_name: str, mobed_name: str, note: str = "") -> str:
    """A few lines that always fit in a WhatsApp link or next to an attached PDF:
    who it is for, the mobed's note, and where the dates are."""
    note = clean_note(note)
    lines = [f"Memorial prayers for {m['departed_name']}", f"{agyary_name} - {mobed_name}"]
    if note:
        lines += ["", note]
    lines += ["", "All the dates are in the PDF."]
    return "\n".join(lines)


def render_pdf(m: dict, *, agyary_name: str, mobed_name: str, note: str = "") -> bytes:
    """The schedule as a one-or-more page A4 PDF."""
    note = clean_note(note)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
        title=f"Memorial prayers - {m['departed_name']}", author=agyary_name,
    )
    base = getSampleStyleSheet()
    title = ParagraphStyle("t", parent=base["Title"], fontSize=20, leading=24, spaceAfter=2, alignment=0)
    sub = ParagraphStyle("s", parent=base["Normal"], fontSize=10.5, leading=14, textColor=colors.HexColor("#555555"))
    body = ParagraphStyle("b", parent=base["Normal"], fontSize=10.5, leading=15)
    cell = ParagraphStyle("c", parent=base["Normal"], fontSize=9.5, leading=12)
    bold = ParagraphStyle("cb", parent=cell, fontName="Helvetica-Bold")
    esc = lambda t: (t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")  # noqa: E731

    died = passed_away(m)

    story = [
        Paragraph("Memorial prayers", title),
        Paragraph(f"For the late <b>{esc(m['departed_name'])}</b>", body),
        Paragraph(esc(died), sub),
        Paragraph(f"{esc(agyary_name)} &middot; {esc(mobed_name)}", sub),
        Spacer(1, 5 * mm),
    ]
    if note:
        story += [Paragraph(esc(note), body), Spacer(1, 5 * mm)]

    rows = [[Paragraph("Date", bold), Paragraph("Day", bold), Paragraph("Observance", bold), Paragraph("Prayers", bold)]]
    for o in m["observances"]:
        rows.append([
            Paragraph(esc(table_date(o["date"])), cell),
            Paragraph(esc(parsi_day(o["roj"], o["mah"], o["gatha_index"])), cell),
            Paragraph(esc(o["label"]), cell),
            Paragraph(esc(_prayers(o)), cell),
        ])
    table = Table(rows, colWidths=[34 * mm, 58 * mm, 36 * mm, 46 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e9edf5")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c8cedb")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f8fb")]),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(table)
    story += [Spacer(1, 6 * mm),
              Paragraph(f"{len(m['observances'])} observance{'s' if len(m['observances']) != 1 else ''}. "
                        "Dates are by the calendar the family keeps.", sub)]
    doc.build(story)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Sending from the shared number
# ---------------------------------------------------------------------------
def send_enabled(settings: Settings) -> bool:
    return settings.memorial_share_send_mode == "live" and wa_send.can_send(settings)


def _text_problem(departed_name: str, mobed_name: str, agyary_name: str) -> str | None:
    """Why the words that fill the template's blanks cannot go out under our
    name (D1), or None. Checked here, at sending, so a name saved before the
    rules - or typed where they were not yet applied - is caught too."""
    for label, text, max_len in (
        ("the departed's name", departed_name, template_text.DEPARTED_MAX),
        ("your name", mobed_name, template_text.MOBED_NAME_MAX),
        ("the fire temple's name", agyary_name, template_text.TEMPLE_MAX),
    ):
        why = template_text.problem(text, max_len=max_len)
        if why:
            return (f"This cannot be sent from the Mobed Diary number: {label} {why}. "
                    "You can still send it from your own WhatsApp.")
    return None


async def blocked_reason(
    db: AsyncSession, settings: Settings, customer: Customer, user_id: int, now: datetime,
    *, departed_name: str, mobed_name: str, agyary_name: str,
) -> str | None:
    """Why this share cannot be sent from our number right now, in words for
    the mobed; None when it can."""
    if settings.memorial_share_send_mode != "live":
        return "Sending from the Mobed Diary number is not switched on yet."
    if not wa_send.can_send(settings):
        return "WhatsApp sending is not set up on this server."
    if await guardrails.paused_reason(db):
        return "All WhatsApp sending is paused at the moment."
    if not customer.reminders_enabled:
        return (f"{customer.name} has not agreed to receive WhatsApp messages from us. "
                "Turn that on in their page after asking them, or send it from your own WhatsApp.")
    # A STOP is the person's and wins over the agreement (D2), as it does for reminders.
    if customer.reminders_stopped_at is not None:
        return (f"{customer.name} replied STOP, so nothing more goes to them from our number. "
                "You can still send it from your own WhatsApp.")
    why = _text_problem(departed_name, mobed_name, agyary_name)
    if why:
        return why
    if not reminders.may_send_to(settings, customer.phone):
        return "This number is not on the list allowed to receive messages yet."
    start, end = guardrails.day_bounds(now)
    sent_today = (await db.execute(
        select(func.count()).select_from(Notification).where(
            Notification.notification_type == TYPE, Notification.recipient_type == "customer",
            Notification.template_params["mobed"].astext == str(user_id),
            Notification.created_at >= start, Notification.created_at < end,
            Notification.status != "failed",
        )
    )).scalar_one()
    if sent_today >= settings.memorial_share_daily_cap:
        return f"You have sent {settings.memorial_share_daily_cap} schedules today, which is the daily limit."
    return None


async def _upload_pdf(client: httpx.AsyncClient, settings: Settings, pdf: bytes, filename: str) -> str:
    """Hand the PDF to WhatsApp and return its media id."""
    url = f"https://graph.facebook.com/{settings.whatsapp_graph_version}/{settings.whatsapp_phone_number_id}/media"
    resp = await client.post(
        url, headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"},
        data={"messaging_product": "whatsapp", "type": "application/pdf"},
        files={"file": (filename, pdf, "application/pdf")},
    )
    if resp.status_code != 200:
        raise RuntimeError(_why(resp))
    return resp.json()["id"]


def _why(resp: httpx.Response) -> str:
    try:
        return str(resp.json()["error"]["message"])[:300]
    except (KeyError, ValueError, TypeError):
        return f"HTTP {resp.status_code}"


async def send_pdf(
    db: AsyncSession, settings: Settings, *, agyary_id: int, customer: Customer, user_id: int,
    memorial: dict, pdf: bytes, filename: str, mobed_name: str, agyary_name: str,
    client: httpx.AsyncClient | None = None,
) -> Notification:
    """Send the PDF to the family through the approved template and record it.
    Raises RuntimeError with a message for the mobed if WhatsApp refuses."""
    params = {"1": memorial["departed_name"], "2": mobed_name, "3": agyary_name, "mobed": str(user_id)}
    n = Notification(
        agyary_id=agyary_id, recipient_phone=customer.phone, recipient_type="customer",
        recipient_id=customer.id, notification_type=TYPE, template_name=settings.whatsapp_share_template,
        template_params=params, status="sending",
    )
    db.add(n)
    await db.flush()
    own = client is None
    client = client or httpx.AsyncClient(timeout=30)
    try:
        media_id = await _upload_pdf(client, settings, pdf, filename)
        url = f"https://graph.facebook.com/{settings.whatsapp_graph_version}/{settings.whatsapp_phone_number_id}/messages"
        resp = await client.post(
            url, headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"},
            json={
                "messaging_product": "whatsapp", "to": wa_send.to_number(customer.phone), "type": "template",
                "template": {
                    "name": settings.whatsapp_share_template,
                    "language": {"code": settings.whatsapp_template_language},
                    "components": [
                        {"type": "header", "parameters": [
                            {"type": "document", "document": {"id": media_id, "filename": filename}}]},
                        {"type": "body", "parameters": [
                            {"type": "text", "text": params[k]} for k in ("1", "2", "3")]},
                    ],
                },
            },
        )
        if resp.status_code != 200:
            raise RuntimeError(_why(resp))
        try:
            n.wa_message_id = resp.json()["messages"][0]["id"]
        except (KeyError, IndexError, ValueError):
            n.wa_message_id = None
        n.status = "sent"
        n.sent_at = datetime.now(timezone.utc)
    except httpx.HTTPError as exc:
        n.status, n.error_message = "failed", f"no answer: {exc.__class__.__name__}"
        await db.flush()
        raise RuntimeError("WhatsApp did not answer, so it may or may not have been sent.") from exc
    except RuntimeError as exc:
        n.status, n.error_message = "failed", str(exc)[:500]
        await db.flush()
        raise
    finally:
        if own:
            await client.aclose()
    await db.flush()
    return n
