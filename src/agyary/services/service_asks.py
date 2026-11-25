"""A person asks an agyari for a service (R4.2, 25 Nov 2026; docs/behdin-r4-2-design.md).

The person asks in the Parsi app; the agyari's confirmed panthaky answers on the Requests tab.
Before an accept the panthaky reads the ask with the person's FIRST name and nothing that
identifies them: the number and the full name are shared only when they accept (D2). Accepting
makes the booking, the machi, the repeating series or the memorial in the panthaky's own diary by
calling the diary's own services (``mobed_dashboard.manual_add_*``, ``memorials.create_memorial``),
exactly as if the panthaky had entered it; no rule of those is written again here.

What a person reads never names the other app: every message here is plain words about the ask.
In-app notices to a person carry the kind prefix ``person_ask_`` so that the two apps' notice
lists never show each other's (the shared table is told apart by kind).

No WhatsApp is sent from here (R4.4 adds the switches): in-app notices and phone push only.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.calendar import CalendarSystem, gregorian_to_parsi
from agyary.core.config import Settings
from agyary.messaging import booking_service
from agyary.messaging.availability import drop_elapsed_gehs, parsi_slot_fields
from agyary.messaging.formatting import PURPOSE_SHORT, numeric_date, parsi_label
from agyary.messaging.geh_times import IST
from agyary.models import (
    Agyary,
    AppNotification,
    Booking,
    Machi,
    MemorialObservance,
    RecurrenceRule,
    Service,
    ServiceAsk,
    User,
)
from agyary.models.enums import (
    ASK_ACCEPTED,
    ASK_CANCELLED,
    ASK_CANCELLED_BY_TEMPLE,
    ASK_REJECTED,
    ASK_WAITING,
    BOOKING_PURPOSES,
    GEH_NAMES,
    MACHI_PURPOSES,
    NAME_SECTIONS,
    NAME_STATUSES,
    NAME_TITLES,
)
from agyary.services import (
    behdin_directory,
    behdin_me,
    memorials,
    mobed_dashboard,
    panthaky,
    reminders,
    template_text,
    web_push,
)
from agyary.services.name_words import first_name

logger = logging.getLogger(__name__)

# What a person may ask, and how much.
MAX_ASKS_A_DAY = 5
MAX_WAITING_PER_AGYARI = 3
MAX_NAMES = 20
NAME_MAX = template_text.DEPARTED_MAX
NOTE_MAX = 200
AREA_MAX = 100
REASON_MAX = 100
DAYS_AHEAD = 400
MAX_REPEATS = {"monthly": 120, "yearly": 60}
MAX_PRICE = Decimal("1000000")

# 24 hours without an answer, told once; asks older than this are never told (no burst after an outage).
NO_ANSWER_AFTER = timedelta(hours=24)
NO_ANSWER_WITHIN = timedelta(days=14)
# Notices to a person stay for a month (they are the answer to something they asked).
PERSON_NOTICE_TTL = timedelta(days=30)
# What the panthaky is told lasts as long as the Requests tab's other notices do.
PANTHAKY_NOTICE_TTL = timedelta(days=2)

PERSON_KIND = "person_ask_"
KIND_ACCEPTED, KIND_REJECTED, KIND_NO_ANSWER = "person_ask_accepted", "person_ask_rejected", "person_ask_no_answer"
KIND_NEW, KIND_CANCELLED = "ask_new", "ask_cancelled"
KIND_TEMPLE_CANCELLED, KIND_TEMPLE_CHANGED = "person_ask_cancelled_by_temple", "person_ask_changed"
REQUESTS_LINK = "#/requests"
PERSON_ASKS_LINK = "#/asks"

NOT_TAKING = "Not taking requests yet"
NO_SUCH_AGYARI = "That fire temple could not be found."
NO_SUCH_ASK = "That request could not be found."

LABELS = {"waiting": "Pending", "accepted": "Confirmed", "rejected": "Declined", "cancelled": "Cancelled",
          ASK_CANCELLED_BY_TEMPLE: "Cancelled by the fire temple"}
CHANGED_LABEL = "Changed"
NO_ANSWER_LABEL = "No answer yet"


class AskError(Exception):
    """A rejected ask or answer; the message is plain words, safe to show, and never names the other app."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def today_ist() -> date:
    return datetime.now(IST).date()


def is_slot_service(service: Service) -> bool:
    """Machi is booked by its geh; every other service by a time of day."""
    return service.name.strip().lower() == "machi"


# ---------------------------------------------------------------------------
# Who can be asked
# ---------------------------------------------------------------------------
async def can_take(db: AsyncSession, settings: Settings, agyary: Agyary) -> bool:
    """The agyari switched asks on, is open, and has a confirmed panthaky who can answer
    (their access on): otherwise an ask would wait for nobody."""
    return bool(
        agyary.is_active and agyary.takes_asks and await panthaky.panthakys_of(db, settings, agyary.id)
    )


def _price(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


async def asking_view(db: AsyncSession, settings: Settings, agyary: Agyary) -> dict:
    """What a person sees of an agyari when about to ask: nothing private."""
    takes = await can_take(db, settings, agyary)
    out = {
        "id": agyary.id, "name": agyary.name, "city": agyary.city, "kind": agyary.kind,
        "takes_asks": takes, "message": None if takes else NOT_TAKING,
        "services": [],
        "gehs": [{"geh": n, "name": name} for n, name in GEH_NAMES.items()],
    }
    if takes:
        for s in await booking_service.list_services(db, agyary.id, exclude_machi=False):
            if s.default_price is None:
                continue          # a service without a price is not offered to people
            out["services"].append({
                "id": s.id, "name": s.name, "usual_price": _price(s.default_price),
                "offsite_capable": s.offsite_capable, "by_geh": is_slot_service(s),
            })
    return out


# ---------------------------------------------------------------------------
# Checking what the person sent
# ---------------------------------------------------------------------------
def _clean_text(value: Any, what: str, limit: int, *, required: bool = False) -> str | None:
    text = " ".join(str(value or "").split())
    if not text:
        if required:
            raise AskError(f"Please enter {what}.")
        return None
    if len(text) > limit:
        raise AskError(f"Please keep {what} to {limit} letters or fewer.")
    why = template_text.problem(text, max_len=limit)
    if why:
        raise AskError(f"Please check {what}: it {why}.")
    return text


def clean_names(names: Any) -> list[dict]:
    """The names to pray, in the shape a ceremony's names have. Each one follows the rules for a
    name that is read out (no links, no @-handles, no long numbers)."""
    if names in (None, []):
        return []
    if not isinstance(names, list) or len(names) > MAX_NAMES:
        raise AskError(f"Please give up to {MAX_NAMES} names.")
    out = []
    for n in names:
        if not isinstance(n, dict):
            raise AskError("Please check the names.")
        section, title, status = n.get("section"), n.get("title"), n.get("status")
        if section not in NAME_SECTIONS or title not in NAME_TITLES or status not in NAME_STATUSES:
            raise AskError("Please check the names.")
        text = _clean_text(n.get("name"), "each name", NAME_MAX, required=True)
        group = n.get("pair_group")
        if group is not None and (type(group) is not int or not 0 <= group <= 99):
            raise AskError("Please check the names.")
        out.append({"section": section, "title": title, "name": text, "status": status, "pair_group": group})
    return out


def _day(value: Any, what: str = "date") -> date:
    if isinstance(value, datetime):
        raise AskError(f"Please choose a {what}.")
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise AskError(f"Please choose a {what}.") from exc


def _time(value: Any) -> time:
    if isinstance(value, time):
        return value.replace(second=0, microsecond=0, tzinfo=None)
    try:
        t = time.fromisoformat(str(value))
    except ValueError as exc:
        raise AskError("Please choose a time of day.") from exc
    return t.replace(second=0, microsecond=0, tzinfo=None)


def _check_when(day: date, *, geh: int | None, at: time | None) -> None:
    today = today_ist()
    if day < today:
        raise AskError("That day has already passed. Please choose another.")
    if day > today + timedelta(days=DAYS_AHEAD):
        raise AskError("Please choose a day within the next year.")
    if geh is not None:
        if geh not in GEH_NAMES:
            raise AskError("Please choose a geh.")
        if day == today and geh not in drop_elapsed_gehs(list(GEH_NAMES), day):
            raise AskError("That geh has already begun today. Please choose another.")
    if at is not None and datetime.combine(day, at, tzinfo=IST) <= datetime.now(IST):
        raise AskError("That time has already passed. Please choose another.")


def _repeat(value: Any) -> tuple[str, int | None] | None:
    if value in (None, False):
        return None
    if not isinstance(value, dict) or value.get("pattern") not in MAX_REPEATS:
        raise AskError("Please choose how it repeats: every month or every year.")
    pattern, count = value["pattern"], value.get("count")
    if count is not None and (type(count) is not int or not 2 <= count <= MAX_REPEATS[pattern]):
        raise AskError(f"A repeat can run between 2 and {MAX_REPEATS[pattern]} times in all.")
    return pattern, count


async def _check_limits(db: AsyncSession, user_id: int, agyary_id: int) -> None:
    since = _now() - timedelta(days=1)
    today_count = (await db.execute(
        select(func.count()).select_from(ServiceAsk).where(ServiceAsk.user_id == user_id, ServiceAsk.created_at > since)
    )).scalar_one()
    if today_count >= MAX_ASKS_A_DAY:
        raise AskError(f"Up to {MAX_ASKS_A_DAY} requests a day. Try again tomorrow.", 429)
    waiting = (await db.execute(
        select(func.count()).select_from(ServiceAsk).where(
            ServiceAsk.user_id == user_id, ServiceAsk.agyary_id == agyary_id, ServiceAsk.status == ASK_WAITING)
    )).scalar_one()
    if waiting >= MAX_WAITING_PER_AGYARI:
        raise AskError(
            f"{MAX_WAITING_PER_AGYARI} requests are already pending here. Wait for an answer or cancel one.", 429)


async def create(
    db: AsyncSession, settings: Settings, user: User, body: dict, *, copied_from_id: int | None = None,
    reuse: ServiceAsk | None = None,
) -> ServiceAsk:
    """Check everything and keep the ask, waiting. Nothing is booked: nothing is claimed in the
    agyari's diary until its panthaky accepts, so a geh is checked only to be a real one still to come.
    The caller commits (``told_new`` after that). ``reuse`` is an earlier ask of this person's that a memorial
    ask is copied from: its own copy of the memorial is used again (never one sent in a body)."""
    agyary = await db.get(Agyary, body.get("agyary_id")) if type(body.get("agyary_id")) is int else None
    if agyary is None or not agyary.is_active:
        raise AskError(NO_SUCH_AGYARI, 404)
    if not await can_take(db, settings, agyary):
        raise AskError(f"{NOT_TAKING}.")
    service = (
        await booking_service.get_service_by_id(db, agyary.id, body["service_id"])
        if type(body.get("service_id")) is int else None
    )
    if service is None:
        raise AskError("That service is not offered here.")
    await _check_limits(db, user.id, agyary.id)

    slot = is_slot_service(service)
    memorial = body.get("memorial")
    repeat = _repeat(body.get("repeat"))
    if memorial and repeat:
        raise AskError("A memorial's dates cannot also be repeated. Please choose one.")
    kind = "memorial" if memorial else "repeating" if repeat else "single"

    venue = body.get("where") or "agyari"
    if venue not in ("agyari", "home"):
        raise AskError("Please choose where: at the fire temple or at home.")
    area = None
    if venue == "home":
        if slot or not service.offsite_capable:
            raise AskError("This can only be done at the fire temple.")
        area = _clean_text(body.get("area"), "the area", AREA_MAX, required=True)
    note = _clean_text(body.get("note"), "the note", NOTE_MAX)
    names = clean_names(body.get("names"))

    fields: dict[str, Any] = {"memorial_choice": None, "memorial_codes": None, "geh": None, "ceremony_time": None}
    if memorial:
        if not isinstance(memorial, dict) or (reuse is None and type(memorial.get("memorial_id")) is not int):
            raise AskError("Please choose a memorial.")
        if reuse is not None:
            made = _still_to_come(reuse)
        else:
            try:
                made = await behdin_me.memorial_for_ask(db, user.id, memorial["memorial_id"], memorial.get("codes"))
            except behdin_me.PersonError as exc:
                raise AskError(str(exc), 404 if "could not be found" in str(exc) else 400) from exc
        codes = [d["code"] for d in made["dates"]]
        if service.name.strip().lower() == "jashan" and not all(memorials.is_anniversary(c) for c in codes):
            raise AskError("Jashan is for the monthly and yearly days only. Choose another prayer, "
                           "or only those days.")
        day = date.fromisoformat(made["dates"][0]["date"])
        purpose = "gujrela_nu"
        fields.update(memorial_choice=made, memorial_codes=codes)
    else:
        day = _day(body.get("date"))
        purpose = body.get("purpose")
        if purpose not in (MACHI_PURPOSES if slot else BOOKING_PURPOSES):
            raise AskError("Please choose what it is for.")
        if slot:
            geh = body.get("geh")
            if type(geh) is not int:
                raise AskError("Please choose a geh.")
            _check_when(day, geh=geh, at=None)
            fields["geh"] = geh
        else:
            at = _time(body.get("time"))
            _check_when(day, geh=None, at=at)
            fields["ceremony_time"] = at
        if repeat:
            await _check_repeat_day(db, agyary, day, slot, repeat[0])

    ask = ServiceAsk(
        user_id=user.id, agyary_id=agyary.id, service_id=service.id, kind=kind, purpose=purpose,
        ceremony_date=day, venue=venue, area=area, names=names, note=note,
        repeat_pattern=repeat[0] if repeat else None, repeat_count=repeat[1] if repeat else None,
        status=ASK_WAITING, copied_from_id=copied_from_id, **fields,
    )
    db.add(ask)
    await db.flush()
    await db.refresh(ask)
    return ask


def _still_to_come(earlier: ServiceAsk) -> dict:
    """An earlier ask's copy of a memorial, with the dates that have gone by taken off."""
    today = today_ist().isoformat()
    dates = [d for d in earlier.memorial_choice["dates"] if d["date"] >= today]
    if not dates:
        raise AskError("All of those dates have already passed.")
    return {"choice": earlier.memorial_choice["choice"], "dates": dates}


async def _check_repeat_day(db: AsyncSession, agyary: Agyary, day: date, slot: bool, pattern: str) -> None:
    """A repeat cannot start on a Gatha day (the diary's own rule, said up front)."""
    try:
        _roj, mah, _year = booking_service.slot_keys(agyary, day)
        mobed_dashboard.refuse_repeating_gatha(pattern, mah, "machi" if slot else "event")
    except mobed_dashboard.BookingInputError as exc:
        raise AskError(str(exc)) from exc
    except (ValueError, OverflowError) as exc:
        raise AskError("That is not a day in the Parsi calendar. Please choose another.") from exc


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------
def _hhmm(t: time | None) -> str | None:
    return None if t is None else t.strftime("%H:%M")


def _parsi(day: date, system: CalendarSystem) -> str | None:
    try:
        roj, mah, _year = parsi_slot_fields(gregorian_to_parsi(day, system))
    except (ValueError, OverflowError):
        return None
    return parsi_label(roj, mah)


def _what(ask: ServiceAsk, service_name: str, system: CalendarSystem) -> dict:
    """The part of an ask that both sides read the same way."""
    out = {
        "id": ask.id, "kind": ask.kind, "status": ask.status,
        "no_answer": ask.status == ASK_WAITING and ask.no_answer_alert_at is not None,
        "service": {"id": ask.service_id, "name": service_name},
        "purpose": ask.purpose, "purpose_label": PURPOSE_SHORT.get(ask.purpose, ask.purpose),
        "date": ask.ceremony_date.isoformat(), "date_text": numeric_date(ask.ceremony_date),
        "parsi": _parsi(ask.ceremony_date, system),
        "geh": ask.geh, "geh_name": GEH_NAMES.get(ask.geh) if ask.geh else None,
        "time": _hhmm(ask.ceremony_time),
        "where": ask.venue, "area": ask.area, "names": list(ask.names or []), "note": ask.note,
        "repeat": {"pattern": ask.repeat_pattern, "count": ask.repeat_count} if ask.repeat_pattern else None,
        "memorial": None,
        "reject_reason": ask.reject_reason,
        "created_at": ask.created_at.isoformat() if ask.created_at else None,
        "decided_at": ask.decided_at.isoformat() if ask.decided_at else None,
    }
    if ask.kind == "memorial" and ask.memorial_choice:
        out["memorial"] = {
            "departed_name": ask.memorial_choice["choice"]["departed_name"],
            "dates": [{**d, "date_text": numeric_date(date.fromisoformat(d["date"])),
                       "parsi": _parsi(date.fromisoformat(d["date"]), system)}
                      for d in ask.memorial_choice["dates"]],
        }
    return out


def label_of(ask: ServiceAsk) -> str:
    if ask.status == ASK_ACCEPTED and ask.changed_at is not None:
        return CHANGED_LABEL
    if ask.status == ASK_WAITING and ask.no_answer_alert_at is not None:
        return NO_ANSWER_LABEL
    return LABELS[ask.status]


async def _names_of(db: AsyncSession, asks: list[ServiceAsk]) -> tuple[dict[int, str], dict[int, Agyary]]:
    services = {}
    agyaries = {}
    if asks:
        services = dict((await db.execute(
            select(Service.id, Service.name).where(Service.id.in_({a.service_id for a in asks})))).all())
        agyaries = {a.id: a for a in (await db.execute(
            select(Agyary).where(Agyary.id.in_({a.agyary_id for a in asks})))).scalars()}
    return services, agyaries


def serialize_for_person(ask: ServiceAsk, service_name: str, agyary: Agyary | None, system: CalendarSystem,
                         live: dict | None = None) -> dict:
    out = _what(ask, service_name, system)
    can_cancel = ask.status == ASK_WAITING or (ask.status == ASK_ACCEPTED and ask.ceremony_date > today_ist())
    out.update(
        label=label_of(ask),
        agyari={"id": ask.agyary_id, "name": agyary.name if agyary else None, "city": agyary.city if agyary else None},
        can_cancel=can_cancel,
        can_ask_another=out["status"] in (ASK_REJECTED, ASK_CANCELLED, ASK_CANCELLED_BY_TEMPLE) or out["no_answer"],
        copied_from_id=ask.copied_from_id,
        changed=ask.changed_at is not None and ask.status == ASK_ACCEPTED,
        changed_at=ask.changed_at.isoformat() if ask.changed_at else None,
    )
    if live:
        _apply_live(out, live, system)
    return out


async def list_for_person(db: AsyncSession, user_id: int, system: CalendarSystem, limit: int = 100) -> list[dict]:
    asks = list((await db.execute(
        select(ServiceAsk).where(ServiceAsk.user_id == user_id)
        .order_by(ServiceAsk.created_at.desc(), ServiceAsk.id.desc()).limit(limit)
    )).scalars())
    services, agyaries = await _names_of(db, asks)
    return [serialize_for_person(a, services.get(a.service_id, ""), agyaries.get(a.agyary_id), system, await live_of(db, a))
            for a in asks]


async def get_for_person(db: AsyncSession, user_id: int, ask_id: int, *, lock: bool = False) -> ServiceAsk | None:
    """Only the person's own: someone else's id is simply not found. ``lock`` holds the row until the
    change is committed, so two answers at once cannot both go through."""
    stmt = select(ServiceAsk).where(ServiceAsk.id == ask_id, ServiceAsk.user_id == user_id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return (await db.execute(stmt)).scalar_one_or_none()


async def person_view(db: AsyncSession, ask: ServiceAsk, system: CalendarSystem) -> dict:
    services, agyaries = await _names_of(db, [ask])
    return serialize_for_person(ask, services.get(ask.service_id, ""), agyaries.get(ask.agyary_id), system,
                                await live_of(db, ask))


def serialize_for_panthaky(ask: ServiceAsk, service_name: str, first: str, system: CalendarSystem) -> dict:
    """The panthaky's reading: the person's FIRST name, never the number (or the whole name).
    ``customer_id`` is their own record of the person once they have accepted."""
    out = _what(ask, service_name, system)
    out.update(label=label_of(ask), person={"first_name": first}, customer_id=ask.result_customer_id)
    return out


async def list_for_agyary(db: AsyncSession, agyary_id: int, system: CalendarSystem, limit: int = 100) -> list[dict]:
    """Waiting asks first (the oldest first: it has waited longest), then the answered ones, newest first."""
    waiting = list((await db.execute(
        select(ServiceAsk).where(ServiceAsk.agyary_id == agyary_id, ServiceAsk.status == ASK_WAITING)
        .order_by(ServiceAsk.created_at, ServiceAsk.id).limit(limit)
    )).scalars())
    done = list((await db.execute(
        select(ServiceAsk).where(ServiceAsk.agyary_id == agyary_id, ServiceAsk.status != ASK_WAITING)
        .order_by(ServiceAsk.updated_at.desc(), ServiceAsk.id.desc()).limit(limit)
    )).scalars())
    asks = waiting + done
    services, _ = await _names_of(db, asks)
    names = dict((await db.execute(
        select(User.id, User.name).where(User.id.in_({a.user_id for a in asks})))).all()) if asks else {}
    return [serialize_for_panthaky(a, services.get(a.service_id, ""), first_name(names.get(a.user_id)), system)
            for a in asks]


async def for_agyary(db: AsyncSession, agyary_id: int, ask_id: int, *, lock: bool = False) -> ServiceAsk | None:
    """An ask made to this agyari. ``lock`` holds the row until the answer is committed, so two
    panthakys answering at once cannot both go through."""
    stmt = select(ServiceAsk).where(ServiceAsk.id == ask_id, ServiceAsk.agyary_id == agyary_id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return (await db.execute(stmt)).scalar_one_or_none()


async def waiting_count(db: AsyncSession, agyary_id: int) -> int:
    return (await db.execute(select(func.count()).select_from(ServiceAsk).where(
        ServiceAsk.agyary_id == agyary_id, ServiceAsk.status == ASK_WAITING))).scalar_one()


# ---------------------------------------------------------------------------
# What the fire temple's diary says now (a request follows its result)
# ---------------------------------------------------------------------------
async def live_of(db: AsyncSession, ask: ServiceAsk) -> dict | None:
    """When a confirmed request happens, read from what it made in the fire temple's diary (not from the
    copy kept at asking), so a change there shows at once. None when it is not confirmed or what it
    made cannot be read (then the stored copy stands)."""
    if ask.status != ASK_ACCEPTED:
        return None
    if ask.result_booking_id:
        b = await db.get(Booking, ask.result_booking_id, populate_existing=True)
        if b is not None:
            local = b.ceremony_datetime.astimezone(IST)
            return {"date": local.date(), "time": local.time().replace(second=0, microsecond=0), "geh": None}
    if ask.result_machi_id:
        m = await db.get(Machi, ask.result_machi_id, populate_existing=True)
        if m is not None:
            return {"date": m.gregorian_date, "time": None, "geh": m.geh}
    if ask.result_memorial_id:
        rows = (await db.execute(
            select(MemorialObservance.code, MemorialObservance.label, MemorialObservance.gregorian_date)
            .where(MemorialObservance.memorial_id == ask.result_memorial_id)
            .order_by(MemorialObservance.gregorian_date, MemorialObservance.day_number))).all()
        if rows:
            return {"date": rows[0][2], "time": None, "geh": None,
                    "dates": [{"code": c, "label": lab, "date": d.isoformat()} for c, lab, d in rows]}
    return None


def _apply_live(out: dict, live: dict, system: CalendarSystem) -> None:
    out["date"], out["date_text"] = live["date"].isoformat(), numeric_date(live["date"])
    out["parsi"] = _parsi(live["date"], system)
    out["time"], out["geh"] = _hhmm(live["time"]), live["geh"]
    out["geh_name"] = GEH_NAMES.get(live["geh"]) if live["geh"] else None
    if live.get("dates") and out.get("memorial"):
        out["memorial"]["dates"] = [
            {**d, "date_text": numeric_date(date.fromisoformat(d["date"])),
             "parsi": _parsi(date.fromisoformat(d["date"]), system)} for d in live["dates"]]


def _live_words(ask: ServiceAsk, live: dict | None) -> str:
    if live is None:
        return numeric_date(ask.ceremony_date)
    out = numeric_date(live["date"])
    if live.get("time"):
        out += " " + live["time"].strftime("%H:%M")
    if live.get("geh"):
        out += f", {GEH_NAMES[live['geh']]}"
    return out


async def _asks_pointing_at(db: AsyncSession, *, booking_ids=(), machi_ids=(), memorial_ids=()) -> list[ServiceAsk]:
    conds = []
    if booking_ids:
        conds.append(ServiceAsk.result_booking_id.in_(list(booking_ids)))
    if machi_ids:
        conds.append(ServiceAsk.result_machi_id.in_(list(machi_ids)))
    if memorial_ids:
        conds.append(ServiceAsk.result_memorial_id.in_(list(memorial_ids)))
    if not conds:
        return []
    return list((await db.execute(
        select(ServiceAsk).where(ServiceAsk.status == ASK_ACCEPTED, or_(*conds)).with_for_update()
    )).scalars())


async def _tell_person_in_txn(db: AsyncSession, ask: ServiceAsk, kind: str, title: str, body: str) -> None:
    """The in-app notice goes in the same transaction as the change; the phone push is sent at once
    (it never raises)."""
    from agyary.core.config import get_settings

    await reminders.notify(db, ask.user_id, kind, title, body, link=f"{PERSON_ASKS_LINK}/{ask.id}",
                           ttl=PERSON_NOTICE_TTL)
    await web_push.send_to_users(db, get_settings(), [ask.user_id], title=title, body=body,
                                 url=f"/behdin{PERSON_ASKS_LINK}/{ask.id}", tag=f"ask-{ask.id}")


async def fire_temple_removed(db: AsyncSession, *, booking_ids=(), machi_ids=(), memorial_ids=()) -> int:
    """The fire temple deleted or stopped what confirmed requests made (a booking, a machi, a repeating
    series, a memorial): each such request becomes "Cancelled by the fire temple" and its person is told.
    Called BEFORE the diary row goes, from every place that deletes or stops one. Returns how many."""
    asks = await _asks_pointing_at(db, booking_ids=booking_ids, machi_ids=machi_ids, memorial_ids=memorial_ids)
    for ask in asks:
        live = await live_of(db, ask)
        ask.status, ask.cancelled_at = ASK_CANCELLED_BY_TEMPLE, _now()
        agyary = await db.get(Agyary, ask.agyary_id)
        service = await db.get(Service, ask.service_id)
        await db.flush()
        await _tell_person_in_txn(
            db, ask, KIND_TEMPLE_CANCELLED, "Request cancelled",
            f"Cancelled by {agyary.name}: {service.name} on {_live_words(ask, live)}")
    return len(asks)


async def fire_temple_changed(db: AsyncSession, *, booking_id=None, machi_id=None, memorial_id=None) -> int:
    """The fire temple changed the date, time or geh of what a confirmed request made: the request
    records it (``changed_at``) and its person is told what it is now. Called AFTER the change is flushed."""
    asks = await _asks_pointing_at(
        db, booking_ids=[booking_id] if booking_id else (), machi_ids=[machi_id] if machi_id else (),
        memorial_ids=[memorial_id] if memorial_id else ())
    for ask in asks:
        live = await live_of(db, ask)
        ask.changed_at = _now()
        agyary = await db.get(Agyary, ask.agyary_id)
        service = await db.get(Service, ask.service_id)
        await db.flush()
        await _tell_person_in_txn(
            db, ask, KIND_TEMPLE_CHANGED, "Request changed",
            f"Changed by {agyary.name}: {service.name}, now {_live_words(ask, live)}")
    return len(asks)


async def calendar_items(db: AsyncSession, user_id: int, start: date, end: date, system: CalendarSystem) -> list[dict]:
    """The person's confirmed requests that fall between two days, read from what the fire temple's diary
    holds now. A request the fire temple cancelled is not here; nor is one the person cancelled."""
    asks = list((await db.execute(
        select(ServiceAsk).where(ServiceAsk.user_id == user_id, ServiceAsk.status == ASK_ACCEPTED)
        .order_by(ServiceAsk.id))).scalars())
    if not asks:
        return []
    services, agyaries = await _names_of(db, asks)
    items = []

    def add(ask, when, at=None, geh=None, label=None):
        if not start <= when <= end:
            return
        parsi = behdin_me.parsi_of(when, system)
        roj, mah = behdin_me._roj_mah(parsi)
        name = agyaries[ask.agyary_id].name if ask.agyary_id in agyaries else ""
        items.append({
            "kind": "request", "source": "request", "id": ask.id,
            "title": f"{services.get(ask.service_id, '')} - {name}" + (f" ({label})" if label else ""),
            "date": when.isoformat(), "time": _hhmm(at), "geh": geh,
            "parsi_roj": roj, "parsi_mah": mah, "parsi": parsi,
        })

    for ask in asks:
        if ask.result_booking_id:
            first = await db.get(Booking, ask.result_booking_id, populate_existing=True)
            rows = [first] if first is not None else []
            if first is not None and first.recurrence_rule_id:
                rows = list((await db.execute(select(Booking).where(
                    Booking.recurrence_rule_id == first.recurrence_rule_id, Booking.status != "cancelled"))).scalars())
            for b in rows:
                local = b.ceremony_datetime.astimezone(IST)
                add(ask, local.date(), local.time().replace(second=0, microsecond=0))
        elif ask.result_machi_id:
            first = await db.get(Machi, ask.result_machi_id, populate_existing=True)
            rows = [first] if first is not None else []
            if first is not None and first.recurrence_rule_id:
                rows = list((await db.execute(select(Machi).where(
                    Machi.recurrence_rule_id == first.recurrence_rule_id, Machi.status != "cancelled"))).scalars())
            for m in rows:
                add(ask, m.gregorian_date, geh=m.geh)
        elif ask.result_memorial_id:
            for code, lab, when in (await db.execute(
                    select(MemorialObservance.code, MemorialObservance.label, MemorialObservance.gregorian_date)
                    .where(MemorialObservance.memorial_id == ask.result_memorial_id))).all():
                add(ask, when, label=lab)
    return items


# ---------------------------------------------------------------------------
# Telling people
# ---------------------------------------------------------------------------
def _when_words(ask: ServiceAsk) -> str:
    if ask.kind == "memorial":
        return "from " + numeric_date(ask.ceremony_date)
    return "on " + numeric_date(ask.ceremony_date)


async def _tell_person(db: AsyncSession, settings: Settings, ask: ServiceAsk, kind: str, title: str, body: str) -> None:
    """An in-app notice for the person, and a phone push. Called after the change is committed."""
    await reminders.notify(db, ask.user_id, kind, title, body, link=f"{PERSON_ASKS_LINK}/{ask.id}",
                           ttl=PERSON_NOTICE_TTL)
    await db.commit()
    await web_push.send_to_users(db, settings, [ask.user_id], title=title, body=body,
                                 url=f"/behdin{PERSON_ASKS_LINK}/{ask.id}", tag=f"ask-{ask.id}")
    await db.commit()


async def _tell_panthakys(db: AsyncSession, settings: Settings, ask: ServiceAsk, kind: str, title: str, body: str) -> None:
    people = await panthaky.panthakys_of(db, settings, ask.agyary_id)
    for u in people:
        await reminders.notify(db, u.id, kind, title, body, link=REQUESTS_LINK, agyary_id=ask.agyary_id,
                               ttl=PANTHAKY_NOTICE_TTL)
    await db.commit()
    if people:
        await web_push.send_to_users(db, settings, [u.id for u in people], title=title, body=body,
                                     url="/mobed" + REQUESTS_LINK, tag=f"service-ask-{ask.id}")
        await db.commit()


async def told_new(db: AsyncSession, settings: Settings, ask: ServiceAsk) -> None:
    """A new ask: every confirmed panthaky of the agyari is told, with the person's first name and the
    service (no number, no full name). Called after the ask is committed."""
    person = await db.get(User, ask.user_id)
    service = await db.get(Service, ask.service_id)
    first = first_name(person.name) or "Someone"
    await _tell_panthakys(
        db, settings, ask, KIND_NEW, "New request",
        f"{first}: {service.name} {_when_words(ask)}.")


# ---------------------------------------------------------------------------
# The person cancels, or asks another agyari
# ---------------------------------------------------------------------------
async def cancel(db: AsyncSession, settings: Settings, ask: ServiceAsk) -> None:
    """The person cancels, any time before the day. A waiting ask just stops waiting. An accepted one
    is cancelled in the panthaky's diary as "by the person" and KEPT (D8): nothing is deleted. A memorial
    that was made from an ask stays in the panthaky's book as it is (its dates carry no cancelled state);
    the panthaky is told and can take it out."""
    if ask.status not in (ASK_WAITING, ASK_ACCEPTED):
        raise AskError("This request has already been answered or cancelled.", 409)
    if ask.status == ASK_ACCEPTED and ask.ceremony_date <= today_ist():
        raise AskError("Too late to cancel here. Speak to the fire temple.")
    was_accepted = ask.status == ASK_ACCEPTED
    if was_accepted:
        await _cancel_in_diary(db, ask)
    ask.status, ask.cancelled_at = ASK_CANCELLED, _now()
    await db.flush()
    await db.commit()
    person = await db.get(User, ask.user_id)
    service = await db.get(Service, ask.service_id)
    await _tell_panthakys(
        db, settings, ask, KIND_CANCELLED, "Request cancelled",
        f"{first_name(person.name) or 'Someone'}: {service.name} {_when_words(ask)}."
        + (" Marked Cancelled by the person." if was_accepted and ask.kind != "memorial" else "")
        + (" Remove their memorial if not needed." if was_accepted and ask.kind == "memorial" else ""))


CANCEL_NOTE = "Cancelled by the person."


async def _cancel_in_diary(db: AsyncSession, ask: ServiceAsk) -> None:
    now = _now()
    if ask.result_booking_id:
        booking = await db.get(Booking, ask.result_booking_id)
        if booking is not None:
            rows = [booking]
            if booking.recurrence_rule_id:
                rule = await db.get(RecurrenceRule, booking.recurrence_rule_id)
                if rule is not None:
                    rule.is_active = False
                rows = list((await db.execute(select(Booking).where(
                    Booking.recurrence_rule_id == booking.recurrence_rule_id,
                    Booking.ceremony_datetime > now))).scalars())
                if booking not in rows:
                    rows.append(booking)
            for b in rows:
                if b.status not in ("cancelled", "completed"):
                    b.status = "cancelled"
                    b.notes = f"{b.notes}\n{CANCEL_NOTE}" if b.notes else CANCEL_NOTE
    if ask.result_machi_id:
        machi = await db.get(Machi, ask.result_machi_id)
        if machi is not None:
            rows = [machi]
            if machi.recurrence_rule_id:
                rule = await db.get(RecurrenceRule, machi.recurrence_rule_id)
                if rule is not None:
                    rule.is_active = False
                rows = list((await db.execute(select(Machi).where(
                    Machi.recurrence_rule_id == machi.recurrence_rule_id,
                    Machi.ceremony_datetime > now))).scalars())
                if machi not in rows:
                    rows.append(machi)
            for m in rows:
                if m.status not in ("cancelled", "completed"):
                    m.status = "cancelled"
                    m.notes = f"{m.notes}\n{CANCEL_NOTE}" if m.notes else CANCEL_NOTE
    await db.flush()


async def ask_another(db: AsyncSession, settings: Settings, user: User, ask: ServiceAsk, agyary_id: Any) -> ServiceAsk:
    """Copy an ask that was turned down, cancelled or never answered to another fire temple. An ask
    nobody answered is withdrawn from the first one (and its panthaky told), so two cannot both say yes."""
    open_no_answer = ask.status == ASK_WAITING and ask.no_answer_alert_at is not None
    if ask.status not in (ASK_REJECTED, ASK_CANCELLED) and not open_no_answer:
        raise AskError("Only a declined, cancelled or unanswered request can go to another fire temple.", 409)
    if type(agyary_id) is not int:
        raise AskError("Please choose a fire temple.")
    if agyary_id == ask.agyary_id and ask.status != ASK_CANCELLED:
        raise AskError("Please choose a different fire temple.")
    target = await db.get(Agyary, agyary_id)
    if target is None or not target.is_active:
        raise AskError(NO_SUCH_AGYARI, 404)
    old_service = await db.get(Service, ask.service_id)
    match = (await db.execute(select(Service).where(
        Service.agyary_id == agyary_id, func.lower(Service.name) == old_service.name.strip().lower(),
        Service.is_active.is_(True)))).scalars().first()
    if match is None:
        raise AskError("That fire temple does not offer this service.")
    body: dict[str, Any] = {
        "agyary_id": agyary_id, "service_id": match.id, "where": ask.venue, "area": ask.area,
        "names": list(ask.names or []), "note": ask.note,
    }
    if ask.kind == "memorial":
        body["memorial"] = {"copy": True}
    else:
        body.update(purpose=ask.purpose, date=ask.ceremony_date,
                    geh=ask.geh, time=ask.ceremony_time)
        if ask.repeat_pattern:
            body["repeat"] = {"pattern": ask.repeat_pattern, "count": ask.repeat_count}
    new = await create(db, settings, user, body, copied_from_id=ask.id, reuse=ask if ask.kind == "memorial" else None)
    if open_no_answer:
        ask.status, ask.cancelled_at = ASK_CANCELLED, _now()
        await db.flush()
    return new


# ---------------------------------------------------------------------------
# The panthaky answers
# ---------------------------------------------------------------------------
async def may_answer(db: AsyncSession, user: User, agyary_id: int) -> bool:
    """Only a confirmed panthaky of the agyari answers (the booking is made in their own diary). The
    admin may read and switch asks on, but is not the one whose diary an accept would fill."""
    from agyary.services import prayer_callout

    return await prayer_callout.is_confirmed_panthaky(db, agyary_id, user.id)


async def reject(db: AsyncSession, settings: Settings, ask: ServiceAsk, user: User, reason: Any) -> None:
    if ask.status != ASK_WAITING:
        raise AskError("This request has already been answered or cancelled.", 409)
    if reason is not None and not isinstance(reason, str):
        raise AskError("Please check the reason.")
    why = _clean_text(reason, "the reason", REASON_MAX)
    ask.status, ask.reject_reason = ASK_REJECTED, why
    ask.decided_at, ask.decided_by_user_id = _now(), user.id
    await db.flush()
    await db.commit()
    agyary = await db.get(Agyary, ask.agyary_id)
    service = await db.get(Service, ask.service_id)
    await _tell_person(
        db, settings, ask, KIND_REJECTED, "Request declined",
        f"{agyary.name}: {service.name} {_when_words(ask)}." + (f" Reason: {why}" if why else ""))


async def accept(db: AsyncSession, settings: Settings, ask: ServiceAsk, user: User) -> dict:
    """Accept: in ONE transaction the person becomes a record in the panthaky's own book (their name and
    number are shared with this panthaky now, and not before), the booking, machi, repeating series or
    memorial is made in the panthaky's own diary by the diary's own service, and the ask is marked
    accepted with what it made. Anything the diary refuses (a geh already held, a day gone by) leaves
    everything as it was and says so in plain words."""
    if ask.status != ASK_WAITING:
        raise AskError("This request has already been answered or cancelled.", 409)
    agyary = await db.get(Agyary, ask.agyary_id)
    person = await db.get(User, ask.user_id)
    service = await booking_service.get_service_by_id(db, ask.agyary_id, ask.service_id)
    if person is None or not person.is_active:
        raise AskError("This person is no longer in the app. Decline the request.", 409)
    if service is None:
        raise AskError("This service is no longer offered. Decline the request.", 409)
    if ask.ceremony_date < today_ist():
        raise AskError("That day has passed. Decline the request.", 409)
    names = list(ask.names or []) or None
    made: dict[str, Any] = {}
    skipped: list[date] = []
    try:
        if ask.kind == "memorial":
            made["memorial"] = await _accept_memorial(db, agyary, user, person, service, ask)
            customer_id = made["memorial"].customer_id
        elif is_slot_service(service):
            roj, mah, year = booking_service.slot_keys(agyary, ask.ceremony_date)
            result = await mobed_dashboard.manual_add_machi(
                db, agyary, user.id, behdin_phone=person.phone, behdin_name=person.name,
                roj=roj, mah=mah, year=year, geh=ask.geh, gregorian=ask.ceremony_date, purpose=ask.purpose,
                names=names, recurring=ask.repeat_pattern, recurring_count=ask.repeat_count,
            )
            if result.machi is None:
                raise AskError(
                    f"You already hold that geh on {numeric_date(ask.ceremony_date)}. Decline the request, "
                    "or ask the person to choose another day.", 409)
            made["machi"], customer_id, skipped = result.machi, result.machi.customer_id, list(result.skipped)
            _note(made["machi"], ask)
        else:
            when = datetime.combine(ask.ceremony_date, ask.ceremony_time)
            result = await mobed_dashboard.manual_add_booking(
                db, agyary, user.id, behdin_phone=person.phone, behdin_name=person.name,
                service_id=service.id, ceremony_dt_local=when, purpose=ask.purpose, names=names,
                location=ask.area if ask.venue == "home" else None, is_offsite=ask.venue == "home",
                recurring=ask.repeat_pattern, recurring_count=ask.repeat_count,
            )
            if result is None:
                raise AskError("This service is no longer offered. Decline the request.", 409)
            made["booking"], customer_id = result.booking, result.booking.customer_id
            _note(made["booking"], ask)
    except (mobed_dashboard.BookingInputError, memorials.MemorialError) as exc:
        raise AskError(str(exc)) from exc
    ask.status, ask.decided_at, ask.decided_by_user_id = ASK_ACCEPTED, _now(), user.id
    ask.result_customer_id = customer_id
    ask.result_booking_id = made["booking"].id if "booking" in made else None
    ask.result_machi_id = made["machi"].id if "machi" in made else None
    ask.result_memorial_id = made["memorial"].id if "memorial" in made else None
    await db.flush()
    await db.commit()
    await _tell_person(
        db, settings, ask, KIND_ACCEPTED, "Request confirmed",
        f"{agyary.name}: {service.name} {_when_words(ask)}.")
    return {"ask_id": ask.id, "customer_id": customer_id, "booking_id": ask.result_booking_id,
            "machi_id": ask.result_machi_id, "memorial_id": ask.result_memorial_id,
            "skipped": [d.isoformat() for d in skipped]}


def _note(ceremony: Booking | Machi, ask: ServiceAsk) -> None:
    """The person's note goes onto the event, in the panthaky's own diary."""
    if ask.note:
        ceremony.notes = f"Note from the person: {ask.note}"


async def _accept_memorial(db, agyary: Agyary, user: User, person: User, service: Service, ask: ServiceAsk):
    choice = behdin_me.choice_from_ask(ask.memorial_choice["choice"])
    customer, _created = await behdin_directory.create_or_link(
        db, agyary.id, user.id, name=person.name, phone=person.phone)
    system = await memorials.calendar_for(db, user.id, choice)
    schedule, _death, _date = memorials.plan(system, choice, memorials.today_ist())
    codes = list(ask.memorial_codes or [])
    if not codes or not set(codes) <= {o.code for o in schedule}:
        raise AskError("This memorial's dates could not be worked out. Decline the request.", 409)
    leave_out = tuple(o.code for o in schedule if o.code not in set(codes))
    memorial = await memorials.create_memorial(db, agyary, user.id, customer, choice, [service.id], leave_out)
    return memorial


# ---------------------------------------------------------------------------
# The one-minute loop: "No answer yet"
# ---------------------------------------------------------------------------
async def _no_answer_due(db: AsyncSession, now: datetime) -> list[int]:
    return list((await db.execute(
        select(ServiceAsk.id).where(
            ServiceAsk.status == ASK_WAITING, ServiceAsk.no_answer_alert_at.is_(None),
            ServiceAsk.created_at <= now - NO_ANSWER_AFTER, ServiceAsk.created_at > now - NO_ANSWER_WITHIN,
            ServiceAsk.ceremony_date >= now.astimezone(IST).date())
        .order_by(ServiceAsk.created_at, ServiceAsk.id)
    )).scalars())


async def _claim_no_answer(db: AsyncSession, ask_id: int, now: datetime) -> bool:
    """Take this ask for "No answer yet", once, while it is still waiting: committed before anyone is told."""
    claimed = (await db.execute(
        update(ServiceAsk)
        .where(ServiceAsk.id == ask_id, ServiceAsk.status == ASK_WAITING, ServiceAsk.no_answer_alert_at.is_(None))
        .values(no_answer_alert_at=now).returning(ServiceAsk.id)
    )).scalar_one_or_none()
    await db.commit()
    return claimed is not None


async def no_answer(db: AsyncSession, now: datetime, settings: Settings) -> int:
    """Tell, once, each person whose ask nobody answered in 24 hours; the ask stays waiting and they
    can ask another fire temple. Returns how many it told."""
    done = 0
    for ask_id in await _no_answer_due(db, now):
        if not await _claim_no_answer(db, ask_id, now):
            continue
        done += 1
        try:
            ask = await db.get(ServiceAsk, ask_id, populate_existing=True)
            agyary = await db.get(Agyary, ask.agyary_id)
            service = await db.get(Service, ask.service_id)
            await _tell_person(
                db, settings, ask, KIND_NO_ANSWER, NO_ANSWER_LABEL,
                f"{agyary.name}: {service.name} {_when_words(ask)}.")
        except Exception:   # noqa: BLE001 - it is claimed (at most once); the next ask still goes
            logger.exception("Telling that nobody answered ask %s failed after it was claimed", ask_id)
            await db.rollback()
    return done


# ---------------------------------------------------------------------------
# The person's notices
# ---------------------------------------------------------------------------
def person_notices_clause():
    """SQL: the notices a person sees in the Parsi app (and only those: the other app's are kept apart by kind)."""
    return AppNotification.kind.like("person\\_%", escape="\\")


# ---------------------------------------------------------------------------
# The panthaky's switch, and the services and their usual prices
# ---------------------------------------------------------------------------
NEEDS_PRICES = "Enter a price for every service first."


async def _offered(db: AsyncSession, agyary_id: int) -> list[Service]:
    """The services the fire temple will offer: the active ones of its diary's catalog."""
    return list((await db.execute(
        select(Service).where(Service.agyary_id == agyary_id, Service.is_active.is_(True))
        .order_by(Service.display_order, Service.id))).scalars())


def _ready(offered: list[Service]) -> bool:
    """At least one service, and every one has a price (0 is a price; nothing entered is not)."""
    return bool(offered) and all(s.default_price is not None for s in offered)


async def read_switch(db: AsyncSession, agyary: Agyary) -> dict:
    """The switch, the services that will be offered with their prices, and whether it can be switched
    on (``ready``: every offered service has a price)."""
    offered = await _offered(db, agyary.id)
    return {
        "takes_asks": bool(agyary.takes_asks), "ready": _ready(offered),
        "services": [{"id": s.id, "name": s.name, "price": _price(s.default_price)} for s in offered],
    }


async def change_switch(db: AsyncSession, agyary: Agyary, value: Any) -> dict:
    """On only when set up (a price for every offered service); off is always allowed."""
    if type(value) is not bool:
        raise AskError("Choose on or off.")
    if value and not _ready(await _offered(db, agyary.id)):
        raise AskError(NEEDS_PRICES, 409)
    agyary.takes_asks = value
    return await read_switch(db, agyary)


def _service_price_row(s: Service) -> dict:
    return {"id": s.id, "name": s.name, "is_active": s.is_active, "offsite_capable": s.offsite_capable,
            "default_price": _price(s.default_price)}


async def list_prices(db: AsyncSession, agyary_id: int) -> list[dict]:
    rows = (await db.execute(
        select(Service).where(Service.agyary_id == agyary_id).order_by(Service.display_order, Service.id))).scalars()
    return [_service_price_row(s) for s in rows]


def checked_price(value: Any) -> Decimal | None:
    """None clears the usual price; otherwise a number from 0 up to a sane ceiling, to the paisa."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise AskError("Please enter the price as a number.")
    try:
        price = Decimal(str(value).strip())
    except InvalidOperation as exc:
        raise AskError("Please enter the price as a number.") from exc
    if not price.is_finite():
        raise AskError("Please enter the price as a number.")
    if price < 0 or price > MAX_PRICE:
        raise AskError(f"Please enter a price from 0 to {int(MAX_PRICE):,}.")
    return price.quantize(Decimal("0.01"))


async def change_service(
    db: AsyncSession, agyary: Agyary, service: Service, *, fields: set[str], price: Any, active: Any,
) -> dict:
    """While the fire temple takes requests every offered service keeps its price and the last
    one stays on: those changes are refused (409) until requests are switched off."""
    new_price = checked_price(price) if "default_price" in fields else service.default_price
    if "is_active" in fields and type(active) is not bool:
        raise AskError("Choose on or off.")
    now_active = active if "is_active" in fields else service.is_active
    if agyary.takes_asks:
        if now_active and new_price is None:
            raise AskError("A price is needed while taking requests.", 409)
        if service.is_active and not now_active and len(await _offered(db, agyary.id)) <= 1:
            raise AskError("Keep at least one service on while taking requests.", 409)
    service.default_price, service.is_active = new_price, now_active
    return _service_price_row(service)
