"""Funeral records: a death recorded by a funeral place's manager (DECISIONS
D10, Phase 2 Step 4), to ask a fire temple for the prayers.

Only what is needed to arrange the prayers is kept (models/funeral_record.py);
cause of death, age, address, the certificate, ID numbers and how the body
goes are never asked for. Every piece of free text is checked like text that
mobeds will read in a notice (services/template_text.py: bounded, no link, no
@-handle, no long run of digits): it is shown to the people asked.

The death is given by its date or by its Roj and Mah (D5): a death before
sunrise belongs to the previous Parsi day, and the manager (or the family)
knows which it was. Either way both are kept, and the Roj and Mah are shown
for the manager to confirm.

A record belongs to its place: any manager of that place sees and edits it,
and so does an admin acting for that one place ("Act for this place", so the
owner can show and try the whole of it); nobody else. What the admin records
or sends says so (``recorded_by_admin``, ``sent_by_admin``). It can be changed until a fire temple has accepted it. Nothing is
deleted for its age (D8).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.calendar import CalendarSystem, gregorian_to_parsi
from agyary.messaging.availability import parsi_slot_fields
from agyary.models import (
    Agyary,
    FuneralPlace,
    FuneralRecord,
    FuneralRequest,
    FuneralRequestRecipient,
    User,
)
from agyary.models.enums import (
    ACCOUNT_FUNERAL_MANAGER,
    DEATH_BY_DATE,
    DEATH_BY_ROJ_MAH,
    DEPARTED_TITLES,
    GEH_NAMES,
    OBSEQUIES,
    OFFERED_CALENDARS,
    REQUEST_ACCEPTED,
    REQUEST_ALL_SET,
    REQUEST_TAKEN,
    REQUEST_WAITING,
)
from agyary.services import memorials, template_text
from agyary.services.phone import _validate_phone

logger = logging.getLogger(__name__)

TITLE_LABELS = {"ervad": "Ervad", "osta": "Osta", "osti": "Osti", "behdin": "Behdin", "khud": "Khud"}
assert set(TITLE_LABELS) == set(DEPARTED_TITLES)
OBSEQUIES_LABELS = {"four_days": "Four days", "one_day": "One day"}
assert set(OBSEQUIES_LABELS) == set(OBSEQUIES)

# The whole prayed name ("Behdin <name> <father's or husband's name>") becomes the
# memorial's departed name when a mobed accepts (Step 5), so it keeps that limit.
PRAYED_NAME_MAX = template_text.DEPARTED_MAX
CONTACT_NAME_MAX = 100
# The Geh-saarnu is prayed in daylight only (after sunrise, up to an hour before
# sunset): Havan, Rapithwin or Uziran.
DAY_GEHS = (1, 2, 3)
# A record is for a death of the last year, and its prayers follow within days.
OLDEST_DEATH_DAYS = 366
PRAYERS_WITHIN_DAYS = 30
MAX_MOBEDS = 20
# What a list shows at a time; older ones are asked for with ``before``.
PAGE = 50

# A request that has been accepted: the record is then the accepter's to use.
# All set (R3.1) is taken for good the same way: the record can no longer be
# changed or sent elsewhere.
ACCEPTED = (REQUEST_ACCEPTED, REQUEST_TAKEN, REQUEST_ALL_SET)


class RecordError(ValueError):
    """What is wrong with one field; ``field`` names it for the form to flag."""

    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field


def today_ist() -> date:
    return memorials.today_ist()


def _tidy(text: str | None) -> str:
    return " ".join(str(text or "").split())


def _text(value: str | None, field: str, what: str, max_len: int, *, required: bool = False) -> str | None:
    value = _tidy(value)
    if not value:
        if required:
            raise RecordError(field, f"Please enter the {what}.")
        return None
    try:
        return template_text.check(value, what, max_len=max_len)
    except ValueError as exc:
        raise RecordError(field, str(exc)) from exc


def prayed_name(title: str, name: str, parent: str | None) -> str:
    """The departed's name as it is prayed: "Behdin Rustom Jamshed"."""
    return " ".join(p for p in (TITLE_LABELS.get(title, ""), name, parent or "") if p)


@dataclass(frozen=True)
class DeathDay:
    """A death as a date and as its Roj, Mah and year (Mah 13 is a Gatha day,
    with the Gatha number as the Roj), and the words to show it in."""

    date: date
    given_by: str
    roj: int
    mah: int
    year: int
    calendar: str
    label: str

    def as_dict(self) -> dict:
        return {
            "date": self.date.isoformat(), "given_by": self.given_by, "roj": self.roj, "mah": self.mah,
            "year": self.year, "calendar": self.calendar, "label": self.label,
        }


def parsi_label(when: date, system: CalendarSystem) -> str:
    p = gregorian_to_parsi(when, system)
    if p.is_gatha:
        return f"{p.gatha_name} (Gatha day), Y{p.year}"
    return f"Roj {p.roj_name}, Mah {p.mah_name}, Y{p.year}"


def death_day(
    *, calendar: str, death_date: date | None, roj: int | None, mah: int | None, year: int | None,
    today: date | None = None,
) -> DeathDay:
    """The death from whichever way it was given (D5). By Roj and Mah without a
    year it is the most recent such day, today included. RecordError("death")
    if it cannot be, is after today, or is more than a year ago."""
    if calendar not in OFFERED_CALENDARS:
        raise RecordError("calendar", "Please choose Shenshai or Kadmi.")
    system = CalendarSystem(calendar)
    today = today or today_ist()
    if death_date is None and roj is None and mah is None and year is None:
        raise RecordError("death", "Please give the date of death, or its Roj and Mah.")
    choice = memorials.Choice(departed_name="", death_date=death_date, death_roj=roj, death_mah=mah, death_year=year)
    try:
        when = memorials.resolve_death(system, choice, today)
    except memorials.MemorialError as exc:
        raise RecordError("death", str(exc)) from exc
    if when > today:
        raise RecordError("death", "The death cannot be after today.")
    if when < today - timedelta(days=OLDEST_DEATH_DAYS):
        raise RecordError("death", "A funeral record is for a death within the last year.")
    p_roj, p_mah, p_year = parsi_slot_fields(gregorian_to_parsi(when, system))
    return DeathDay(
        date=when, given_by=DEATH_BY_DATE if death_date is not None else DEATH_BY_ROJ_MAH,
        roj=p_roj, mah=p_mah, year=p_year, calendar=calendar, label=parsi_label(when, system),
    )


def _prayer_day(value: date | None, death: date, field: str, what: str) -> date | None:
    if value is None:
        return None
    if value < death:
        raise RecordError(field, f"The {what} cannot be before the death.")
    if value > death + timedelta(days=PRAYERS_WITHIN_DAYS):
        raise RecordError(field, f"The {what} is more than {PRAYERS_WITHIN_DAYS} days after the death. "
                                 "Please check the date.")
    return value


async def checked(db: AsyncSession, data: dict, *, today: date | None = None) -> dict:
    """The record's columns from what the manager entered, or RecordError for
    the first field that will not do. ``data`` has the API's field names."""
    title = data.get("departed_title")
    if title not in DEPARTED_TITLES:
        raise RecordError("departed_title", "Please choose the title: Behdin, Ervad, Osta, Osti or Khud.")
    name = _text(data.get("departed_name"), "departed_name", "departed's name", PRAYED_NAME_MAX, required=True)
    parent = _text(data.get("departed_parent_name"), "departed_parent_name", "father's or husband's name",
                   PRAYED_NAME_MAX)
    whole = prayed_name(title, name, parent)
    if len(whole) > PRAYED_NAME_MAX:
        raise RecordError("departed_name", f"The name as it is prayed is too long (at most {PRAYED_NAME_MAX} "
                                           "characters with the title and the father's or husband's name).")

    death = death_day(
        calendar=data.get("calendar") or "", death_date=data.get("death_date"), roj=data.get("death_roj"),
        mah=data.get("death_mah"), year=data.get("death_year"), today=today,
    )

    obsequies = data.get("obsequies")
    if obsequies not in OBSEQUIES:
        raise RecordError("obsequies", "Please choose four days or one day.")

    gs_date, gs_geh = data.get("geh_saarnu_date"), data.get("geh_saarnu_geh")
    if gs_date is None and gs_geh is not None:
        raise RecordError("geh_saarnu_date", "Please give the day of the Geh-saarnu too.")
    if gs_date is not None and gs_geh is None:
        raise RecordError("geh_saarnu_geh", "Please choose the geh of the Geh-saarnu.")
    if gs_geh is not None and gs_geh not in DAY_GEHS:
        raise RecordError("geh_saarnu_geh", "The Geh-saarnu is in daylight: choose Havan, Rapithwin or Uziran.")
    gs_date = _prayer_day(gs_date, death.date, "geh_saarnu_date", "Geh-saarnu")

    u_date, u_time = data.get("uthamna_date"), data.get("uthamna_time")
    if u_time is not None and u_date is None:
        raise RecordError("uthamna_date", "Please give the day of the Uthamna too.")
    u_date = _prayer_day(u_date, death.date, "uthamna_date", "Uthamna")

    wanted = data.get("mobeds_wanted")
    if wanted is not None and not 1 <= wanted <= MAX_MOBEDS:
        raise RecordError("mobeds_wanted", f"The number of mobeds is from 1 to {MAX_MOBEDS}.")

    preferred = data.get("preferred_agyary_id")
    if preferred is not None:
        agyary = await db.get(Agyary, preferred)
        if agyary is None or not agyary.is_active:
            raise RecordError("preferred_agyary_id", "That fire temple could not be found. Please choose it again.")

    contact = _text(data.get("family_contact_name"), "family_contact_name", "family contact's name",
                    CONTACT_NAME_MAX, required=True)
    raw_phone = _tidy(data.get("family_contact_phone"))
    if not raw_phone:
        raise RecordError("family_contact_phone", "Please enter the family contact's number.")
    try:
        phone = _validate_phone(raw_phone)
    except ValueError as exc:
        raise RecordError("family_contact_phone",
                          "Please enter the family contact's number with its country code.") from exc

    return {
        "departed_title": title, "departed_name": name, "departed_parent_name": parent,
        "death_date": death.date, "death_given_by": death.given_by, "death_roj": death.roj,
        "death_mah": death.mah, "death_year": death.year, "calendar_system": death.calendar,
        "obsequies": obsequies,
        "geh_saarnu_date": gs_date, "geh_saarnu_geh": gs_geh,
        "uthamna_date": u_date, "uthamna_time": u_time,
        "mobeds_wanted": wanted, "preferred_agyary_id": preferred,
        "family_contact_name": contact, "family_contact_phone": phone,
    }


# --- Whose records ----------------------------------------------------------------
# A record belongs to its place. Who may see it is decided by the route: a
# manager's own places, or the one place an admin acts for (api/routes/funeral.py,
# get_acting_manager); here it is always a list of place ids.

async def get_for_places(db: AsyncSession, place_ids: list[int], record_id: int) -> FuneralRecord | None:
    """The record, if it is at one of these places; else None (the API answers
    404 either way: another place's deaths are not to be probed)."""
    if not place_ids:
        return None
    return (
        await db.execute(
            select(FuneralRecord).where(FuneralRecord.id == record_id, FuneralRecord.funeral_place_id.in_(place_ids))
        )
    ).scalar_one_or_none()


async def list_for_places(db: AsyncSession, place_ids: list[int], *, before: int | None = None) -> list[FuneralRecord]:
    """The records of these places, newest first, a page at a time
    (``before``: the last id of the page before)."""
    if not place_ids:
        return []
    stmt = select(FuneralRecord).where(FuneralRecord.funeral_place_id.in_(place_ids))
    if before is not None:
        stmt = stmt.where(FuneralRecord.id < before)
    return list((await db.execute(stmt.order_by(FuneralRecord.id.desc()).limit(PAGE))).scalars().all())


async def requests_of(db: AsyncSession, record_ids: list[int]) -> dict[int, list[FuneralRequest]]:
    """Each record's requests, newest first."""
    out: dict[int, list[FuneralRequest]] = {i: [] for i in record_ids}
    if not record_ids:
        return out
    rows = (
        await db.execute(
            select(FuneralRequest).where(FuneralRequest.funeral_record_id.in_(record_ids))
            .order_by(FuneralRequest.sent_at.desc(), FuneralRequest.id.desc())
        )
    ).scalars().all()
    for r in rows:
        out[r.funeral_record_id].append(r)
    return out


def accepted(requests: list[FuneralRequest]) -> FuneralRequest | None:
    return next((r for r in requests if r.status in ACCEPTED), None)


def waiting(requests: list[FuneralRequest]) -> FuneralRequest | None:
    return next((r for r in requests if r.status == REQUEST_WAITING), None)


async def create(db: AsyncSession, user: User, place: FuneralPlace, values: dict) -> FuneralRecord:
    record = FuneralRecord(funeral_place_id=place.id, created_by_user_id=user.id, **values)
    db.add(record)
    await db.flush()
    logger.info("Funeral record %s made at funeral place %s by user %s", record.id, place.id, user.id)
    return record


class LockedError(ValueError):
    """The record cannot be changed now; the message is for the manager."""


async def update(db: AsyncSession, record: FuneralRecord, user: User, values: dict) -> bool:
    """Change a record that no fire temple has accepted yet. Returns whether
    anything changed (those asked by a waiting request are then told again)."""
    await db.refresh(record, with_for_update=True)
    if accepted((await requests_of(db, [record.id]))[record.id]):
        raise LockedError("A fire temple has accepted this request, so the record can no longer be changed here. "
                          "Please tell them of any change yourself.")
    changed = any(getattr(record, key) != value for key, value in values.items())
    if not changed:
        return False
    for key, value in values.items():
        setattr(record, key, value)
    record.updated_at = datetime.now(timezone.utc)
    await db.flush()
    logger.info("Funeral record %s changed by user %s", record.id, user.id)
    return True


# --- What the manager sees ---------------------------------------------------------

def _accepter(accepters: dict, q: FuneralRequest) -> tuple[str | None, str | None]:
    """Who accepted, and their number only if they let the place have it."""
    if q.status not in ACCEPTED or not q.accepted_by_user_id or q.accepted_by_user_id not in accepters:
        return None, None
    name, phone = accepters[q.accepted_by_user_id]
    return name, phone if q.accepter_shared_contact else None


def _hhmm(t: time | None) -> str | None:
    return t.strftime("%H:%M") if t else None


def _when(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


async def serialize(db: AsyncSession, records: list[FuneralRecord]) -> list[dict]:
    """Records as their place's managers see them, family contact included,
    each with its requests (newest first) and what can be done with it now."""
    ids = [r.id for r in records]
    by_record = await requests_of(db, ids)
    requests = [q for qs in by_record.values() for q in qs]
    agyary_ids = {q.agyary_id for q in requests} | {r.preferred_agyary_id for r in records if r.preferred_agyary_id}
    agyaries = {
        a.id: a for a in (await db.execute(select(Agyary).where(Agyary.id.in_(agyary_ids)))).scalars()
    } if agyary_ids else {}
    people = {q.accepted_by_user_id for q in requests if q.accepted_by_user_id}
    accepters = {
        uid: (name, phone) for uid, name, phone in
        (await db.execute(select(User.id, User.name, User.phone).where(User.id.in_(people)))).all()
    } if people else {}
    # Who recorded and who sent: a manager, or the admin acting for the place
    # (an admin's account is never a manager's, so the kind of account says it).
    makers = {r.created_by_user_id for r in records} | {q.sent_by_user_id for q in requests}
    makers.discard(None)
    by_admin = {
        uid for uid, kind in (await db.execute(select(User.id, User.account_kind).where(User.id.in_(makers)))).all()
        if kind != ACCOUNT_FUNERAL_MANAGER
    } if makers else set()
    asked = dict(
        (await db.execute(
            select(FuneralRequestRecipient.funeral_request_id, func.count())
            .where(FuneralRequestRecipient.funeral_request_id.in_([q.id for q in requests]))
            .group_by(FuneralRequestRecipient.funeral_request_id)
        )).all()
    ) if requests else {}
    places = {
        p.id: p for p in (await db.execute(
            select(FuneralPlace).where(FuneralPlace.id.in_({r.funeral_place_id for r in records}))
        )).scalars()
    } if records else {}

    def agyari(aid: int | None) -> dict | None:
        a = agyaries.get(aid) if aid else None
        return {"id": a.id, "name": a.name, "city": a.city} if a else None

    out = []
    for r in records:
        qs = by_record[r.id]
        place = places.get(r.funeral_place_id)
        system = CalendarSystem(r.calendar_system)
        out.append({
            "id": r.id,
            "funeral_place": {"id": place.id, "name": place.name, "kind": place.kind, "is_active": place.is_active}
            if place else None,
            "departed_title": r.departed_title,
            "departed_name": r.departed_name,
            "departed_parent_name": r.departed_parent_name,
            "prayed_name": prayed_name(r.departed_title, r.departed_name, r.departed_parent_name),
            "death": {
                "date": r.death_date.isoformat(), "given_by": r.death_given_by, "roj": r.death_roj,
                "mah": r.death_mah, "year": r.death_year, "calendar": r.calendar_system,
                "label": parsi_label(r.death_date, system),
            },
            "obsequies": r.obsequies,
            "obsequies_label": OBSEQUIES_LABELS.get(r.obsequies, r.obsequies),
            "geh_saarnu": {
                "date": r.geh_saarnu_date.isoformat(), "geh": r.geh_saarnu_geh,
                "geh_name": GEH_NAMES.get(r.geh_saarnu_geh),
            } if r.geh_saarnu_date else None,
            "uthamna": {"date": r.uthamna_date.isoformat(), "time": _hhmm(r.uthamna_time)} if r.uthamna_date else None,
            "mobeds_wanted": r.mobeds_wanted,
            "preferred_agyari": agyari(r.preferred_agyary_id),
            "family_contact": {"name": r.family_contact_name, "phone": r.family_contact_phone},
            "created_at": _when(r.created_at),
            "recorded_by_admin": r.created_by_user_id in by_admin,
            "updated_at": _when(r.updated_at),
            # Changed until accepted; sent while nothing waits and nothing is accepted.
            "may_edit": accepted(qs) is None,
            "may_send": accepted(qs) is None and waiting(qs) is None and bool(place and place.is_active),
            "requests": [
                {
                    "id": q.id, "agyari": agyari(q.agyary_id), "status": q.status,
                    "sent_at": _when(q.sent_at), "decided_at": _when(q.decided_at),
                    "accepted_by": _accepter(accepters, q)[0],
                    # The accepter's number only if they ticked "Share my name and number" (Step 5).
                    "accepter_phone": _accepter(accepters, q)[1],
                    "decline_reason": q.decline_reason, "asked": asked.get(q.id, 0),
                    "sent_by_admin": q.sent_by_user_id in by_admin,
                }
                for q in qs
            ],
        })
    return out
