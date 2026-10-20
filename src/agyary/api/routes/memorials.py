"""Memorials: the observances a family keeps for a departed person.

Business logic is services/memorials.py and the date counting is
calendar/memorial.py; this is the HTTP layer. Everything is private to the
mobed who made it - the behdin routes already enforce that for the behdin,
and the memorial reads filter on the caller's id themselves.
"""

from __future__ import annotations

from datetime import date, time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.api.routes.mobed import _require_behdin, _require_membership, get_current_user
from agyary.calendar.memorial import OPENING_5_TO_9, OPENING_ALL, OPENING_NONE, OPENING_TENTH, PARAB_ALL, PARAB_FRAVARDIN_TIR
from agyary.core.config import get_settings
from agyary.core.database import get_db
from agyary.models import Customer, Memorial, User
from agyary.services import guardrails, memorial_share, memorials

router = APIRouter(prefix="/api/mobed", tags=["memorials"])

MAX_FEED_RANGE_DAYS = 366
MAX_REMINDER_HORIZON_DAYS = 60


class SeriesIn(BaseModel):
    """A repeating series and how long it runs. ``count`` has no default on
    purpose: the mobed always chooses the length, so omitting it is an
    error rather than something quietly filled in."""

    count: int


class ParabsIn(BaseModel):
    which: Literal[PARAB_ALL, PARAB_FRAVARDIN_TIR]
    # Either how many years they run, or how many Parabs - one of the two.
    years: int | None = None
    count: int | None = None


class BirthdayIn(BaseModel):
    """The deceased's birthday: a date, or Roj and Mah (one or the other)."""

    birth_date: date | None = None
    roj: int | None = None
    mah: int | None = None
    years: int


class MemorialIn(BaseModel):
    departed_name: str
    # The death: a Gregorian date, or Roj and Mah (and Parsi year) in the family's
    # calendar - one or the other (D5). Mah 13 is a Gatha day, numbered by Roj.
    death_date: date | None = None
    death_roj: int | None = None
    death_mah: int | None = None
    death_year: int | None = None
    # The old 1-10 openings are still accepted; new memorials send none and pick
    # the Dasmi among the named days.
    opening: Literal[OPENING_ALL, OPENING_TENTH, OPENING_NONE, OPENING_5_TO_9] = OPENING_NONE
    day_counts: list[int] = []
    monthly: SeriesIn | None = None   # count = months
    yearly: SeriesIn | None = None    # count = years
    fravardin_roj: SeriesIn | None = None   # Roj Fravardin every month; count = months
    parabs: ParabsIn | None = None   # years = how many years they run
    birthday: BirthdayIn | None = None
    # Book nothing before this date; the counting still starts at the death.
    start_from: date | None = None
    # The calendar the family keeps. Left out, it is the mobed's primary.
    calendar: Literal["shenshai", "kadmi", "fasli"] | None = None


class CreateMemorialIn(MemorialIn):
    # The services every observance starts with; each can be changed later.
    service_ids: list[int]
    # Observances the mobed took out on the review screen (by code).
    exclude_codes: list[str] = []
    # Prayers changed for single dates on the review screen: date code -> the
    # service ids that date should have (instead of the chosen set).
    service_overrides: dict[str, list[int]] = {}


def _choice(p: MemorialIn) -> memorials.Choice:
    return memorials.Choice(
        departed_name=p.departed_name,
        death_date=p.death_date,
        death_roj=p.death_roj,
        death_mah=p.death_mah,
        death_year=p.death_year,
        opening=p.opening,
        day_counts=tuple(p.day_counts),
        monthly_months=p.monthly.count if p.monthly else None,
        yearly_years=p.yearly.count if p.yearly else None,
        fravardin_roj_months=p.fravardin_roj.count if p.fravardin_roj else None,
        parabs=p.parabs.which if p.parabs else None,
        parab_years=p.parabs.years if p.parabs else None,
        parab_count=p.parabs.count if p.parabs else None,
        calendar=p.calendar,
        start_from=p.start_from,
        birthday_date=p.birthday.birth_date if p.birthday else None,
        birthday_roj=p.birthday.roj if p.birthday else None,
        birthday_mah=p.birthday.mah if p.birthday else None,
        birthday_years=p.birthday.years if p.birthday else None,
    )


def _bad_request(exc: memorials.MemorialError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


async def _own_memorial(db: AsyncSession, agyary_id: int, memorial_id: int, user: User) -> Memorial:
    await _require_membership(db, agyary_id, user)
    memorial = await memorials.get_for_user(db, user.id, memorial_id)
    # 404 whether it is missing, someone else's, or at another temple: a
    # family's departed are not for a colleague to confirm the existence of.
    if memorial is None or memorial.agyary_id != agyary_id:
        raise HTTPException(status_code=404, detail="That memorial could not be found.")
    return memorial


async def _preview(db: AsyncSession, user: User, payload: MemorialIn) -> dict:
    try:
        choice = _choice(payload)
        system = await memorials.calendar_for(db, user.id, choice)
        schedule, (roj, mah, year), death_date = memorials.plan(system, choice)
    except memorials.MemorialError as exc:
        raise _bad_request(exc) from exc
    return {
        "calendar": system.value,
        "death": {"roj": roj, "mah": mah, "year": year},
        "death_date": death_date.isoformat(),
        "count": len(schedule),
        "start_from": choice.start_from.isoformat() if choice.start_from else None,
        "passed_not_booked": memorials.passed_before_start(system, choice),
        "observances": [
            {
                "code": o.code, "label": o.label, "day_number": o.day_number,
                "date": o.gregorian_date.isoformat(),
                "roj": o.roj, "mah": o.mah, "year": o.year, "gatha_index": o.gatha_index,
                # Monthly / yearly days, which Jashan is put on to begin with.
                "anniversary": memorials.is_anniversary(o.code),
            }
            for o in schedule
        ],
    }


@router.post("/agyaries/{agyary_id}/memorials/preview")
async def preview_new_memorial(
    agyary_id: int,
    payload: MemorialIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Every date this choice would produce, with nothing saved. Needs no
    behdin: the New behdin page shows the schedule before the behdin exists."""
    await _require_membership(db, agyary_id, user)
    return await _preview(db, user, payload)


@router.post("/agyaries/{agyary_id}/behdins/{customer_id}/memorials/preview")
async def preview_memorial(
    agyary_id: int,
    customer_id: int,
    payload: MemorialIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """The same, for a behdin who is already on file - the step where the
    mobed checks the schedule before confirming it."""
    await _require_behdin(db, agyary_id, customer_id, user)
    await _require_membership(db, agyary_id, user)
    return await _preview(db, user, payload)


@router.post("/agyaries/{agyary_id}/behdins/{customer_id}/memorials")
async def create_memorial(
    agyary_id: int,
    customer_id: int,
    payload: CreateMemorialIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    customer = await _require_behdin(db, agyary_id, customer_id, user)
    agyary = await _require_membership(db, agyary_id, user)
    try:
        memorial = await memorials.create_memorial(
            db, agyary, user.id, customer, _choice(payload), payload.service_ids,
            tuple(payload.exclude_codes),
            payload.service_overrides,
        )
    except memorials.MemorialError as exc:
        raise _bad_request(exc) from exc
    await db.commit()
    # Re-read so the response is exactly what a later GET would return.
    fresh = await memorials.get_for_user(db, user.id, memorial.id)
    return (await memorials.summaries(db, agyary_id, [fresh], detailed=True))[0]


@router.get("/agyaries/{agyary_id}/behdins/{customer_id}/memorials")
async def list_memorials(
    agyary_id: int,
    customer_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """This behdin's memorials: where each has got to, and what is next."""
    await _require_behdin(db, agyary_id, customer_id, user)
    found = await memorials.list_for_behdin(db, user.id, agyary_id, customer_id)
    return await memorials.summaries(db, agyary_id, found, detailed=False)


@router.get("/agyaries/{agyary_id}/memorials/{memorial_id}")
async def get_memorial(
    agyary_id: int,
    memorial_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    memorial = await _own_memorial(db, agyary_id, memorial_id, user)
    return (await memorials.summaries(db, agyary_id, [memorial], detailed=True))[0]


class UpdateObservanceIn(BaseModel):
    """Change one observance. Left out means unchanged; ``time`` and
    ``notes`` as an empty string mean clear it."""

    service_ids: list[int] | None = None
    time: str | None = None
    notes: str | None = None


def _parse_time(value: str) -> time:
    try:
        hh, mm = value.split(":")
        return time(int(hh), int(mm))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Please give the time like 09:30.") from exc


@router.patch("/agyaries/{agyary_id}/memorials/{memorial_id}/observances/{observance_id}")
async def update_observance(
    agyary_id: int,
    memorial_id: int,
    observance_id: int,
    payload: UpdateObservanceIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    memorial = await _own_memorial(db, agyary_id, memorial_id, user)
    observance = next((o for o in memorial.observances if o.id == observance_id), None)
    if observance is None:
        raise HTTPException(status_code=404, detail="That prayer day could not be found.")
    try:
        await memorials.update_observance(
            db, memorial, observance,
            service_ids=payload.service_ids,
            time_of_day=_parse_time(payload.time) if payload.time else None,
            clear_time=payload.time == "",
            notes=payload.notes,
            clear_notes=payload.notes == "",
        )
    except memorials.MemorialError as exc:
        raise _bad_request(exc) from exc
    await db.commit()
    names = await memorials._service_names(db, agyary_id)
    fresh = await memorials.get_for_user(db, user.id, memorial_id)
    done = next(o for o in fresh.observances if o.id == observance_id)
    return memorials.serialize_observance(done, names)


@router.delete("/agyaries/{agyary_id}/memorials/{memorial_id}")
async def delete_memorial(
    agyary_id: int,
    memorial_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    memorial = await _own_memorial(db, agyary_id, memorial_id, user)
    await memorials.delete_memorial(db, memorial)
    await db.commit()
    return {"deleted": True}


@router.get("/agyaries/{agyary_id}/memorial-feed")
async def memorial_feed(
    agyary_id: int,
    from_: date = Query(alias="from"),
    to: date = Query(),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """This mobed's memorial observances (and closing notices) between two
    dates, inclusive - what the calendar overlays on its days."""
    await _require_membership(db, agyary_id, user)
    if to < from_:
        raise HTTPException(status_code=400, detail="The end date is before the start date.")
    if (to - from_).days + 1 > MAX_FEED_RANGE_DAYS:
        raise HTTPException(status_code=400, detail=f"Range too wide (max {MAX_FEED_RANGE_DAYS} days)")
    return await memorials.calendar_feed(db, user.id, agyary_id, from_, to)


@router.get("/agyaries/{agyary_id}/memorial-reminders")
async def memorial_reminders(
    agyary_id: int,
    days: int = Query(default=14, ge=0, le=MAX_REMINDER_HORIZON_DAYS),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Which families this mobed should be reminded about soon: their own
    memorials' observances from today to ``days`` ahead, each flagged ``due``
    once inside the reminder lead time."""
    await _require_membership(db, agyary_id, user)
    items = await memorials.reminders_due(
        db, user.id, agyary_id, memorials.today_ist(), days
    )
    settings = get_settings()
    return {
        "lead_days": memorials.REMINDER_LEAD_DAYS,
        # Whether anything is sent on its own yet, so the screen never promises
        # an automatic reminder that is not going to happen ("auto" per item is
        # the planner's own answer), and when it goes.
        "delivery": settings.reminders_send_mode,
        "paused": await guardrails.paused_reason(db) is not None,
        "send_hour": settings.reminders_send_hour,
        "items": items,
    }


class RemindedIn(BaseModel):
    reminded: bool


@router.put("/agyaries/{agyary_id}/memorial-observances/{observance_id}/reminded")
async def mark_reminded(
    agyary_id: int,
    observance_id: int,
    payload: RemindedIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """The mobed told the family themselves (or takes that back). Nothing is
    then sent automatically for it. Only on the mobed's own memorials."""
    await _require_membership(db, agyary_id, user)
    obs = await memorials.mark_reminded(db, user.id, agyary_id, observance_id, payload.reminded)
    if obs is None:
        raise HTTPException(status_code=404, detail="That prayer day could not be found.")
    await db.commit()
    return {"reminded_by_hand_at": obs.reminded_by_hand_at.isoformat() if obs.reminded_by_hand_at else None}


# --- Sharing the schedule with the family ----------------------------------

async def _share_parts(db: AsyncSession, agyary_id: int, memorial_id: int, user: User):
    """The memorial as the screen shows it, the behdin it belongs to, and the
    fire temple's name - everything a share is built from."""
    agyary = await _require_membership(db, agyary_id, user)
    memorial = await _own_memorial(db, agyary_id, memorial_id, user)
    data = (await memorials.summaries(db, agyary_id, [memorial], detailed=True))[0]
    customer = await db.get(Customer, memorial.customer_id)
    return data, customer, agyary.name


@router.get("/agyaries/{agyary_id}/memorials/{memorial_id}/share")
async def share_info(
    agyary_id: int,
    memorial_id: int,
    note: str = Query(default="", max_length=600),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """What the Share box shows: the message text (to copy, or to open in the
    mobed's own WhatsApp), the behdin's number, and whether - and if not, why
    not - it can be sent from the shared number."""
    from datetime import datetime, timezone

    data, customer, agyary_name = await _share_parts(db, agyary_id, memorial_id, user)
    why = await memorial_share.blocked_reason(db, get_settings(), customer, user.id, datetime.now(timezone.utc))
    return {
        "text": memorial_share.message_text(data, agyary_name=agyary_name, mobed_name=user.name, note=note),
        "phone": customer.phone,
        "behdin_name": customer.name,
        "can_send": why is None,
        "cannot_send_because": why,
        "note_max": memorial_share.NOTE_MAX,
    }


def _pdf_filename(departed: str) -> str:
    safe = "".join(c if c.isalnum() else "-" for c in departed).strip("-") or "memorial"
    return f"Memorial-prayers-{safe}.pdf"


@router.get("/agyaries/{agyary_id}/memorials/{memorial_id}/schedule.pdf")
async def schedule_pdf(
    agyary_id: int,
    memorial_id: int,
    note: str = Query(default="", max_length=600),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    data, _customer, agyary_name = await _share_parts(db, agyary_id, memorial_id, user)
    pdf = memorial_share.render_pdf(data, agyary_name=agyary_name, mobed_name=user.name, note=note)
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{_pdf_filename(data["departed_name"])}"',
                 "Cache-Control": "no-store"},
    )


class ShareSendIn(BaseModel):
    note: str = ""


@router.post("/agyaries/{agyary_id}/memorials/{memorial_id}/share/send")
async def share_send(
    agyary_id: int,
    memorial_id: int,
    payload: ShareSendIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Send the PDF to the behdin from the shared number (a template with a
    document). Refused with the reason when it is off, paused, the family has
    not agreed, or the mobed is over the daily limit."""
    from datetime import datetime, timezone

    settings = get_settings()
    data, customer, agyary_name = await _share_parts(db, agyary_id, memorial_id, user)
    why = await memorial_share.blocked_reason(db, settings, customer, user.id, datetime.now(timezone.utc))
    if why:
        raise HTTPException(status_code=409, detail=why)
    pdf = memorial_share.render_pdf(data, agyary_name=agyary_name, mobed_name=user.name, note=payload.note)
    try:
        await memorial_share.send_pdf(
            db, settings, agyary_id=agyary_id, customer=customer, user_id=user.id, memorial=data, pdf=pdf,
            filename=_pdf_filename(data["departed_name"]), mobed_name=user.name, agyary_name=agyary_name,
        )
    except RuntimeError as exc:
        await db.commit()   # keep the failed attempt on record
        raise HTTPException(status_code=502, detail=f"WhatsApp did not accept it: {exc}") from exc
    await db.commit()
    return {"sent": True}
