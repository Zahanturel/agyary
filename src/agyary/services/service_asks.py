"""A person's request to a fire temple (R4.2, 25 Nov 2026; redesigned the same day; docs/behdin-r4-2-design.md).

A request is one fire temple, several items (each a prayer with its own day, a time that may be left open,
an optional repeat; or a memorial) and the names to pray. The fire temple's confirmed panthaky confirms or
declines the WHOLE request on the Requests tab. Before a confirm the panthaky reads it with the person's
FIRST name and nothing that identifies them: the number and the full name are shared only when they
confirm (D2). Confirming makes one entry in the panthaky's own diary per item (a booking, a machi, a
repeating series or a memorial) in ONE transaction, by calling the diary's own services
(``mobed_dashboard.manual_add_*``, ``memorials.create_memorial``) exactly as if the panthaky had entered
them; no rule of those is written again here.

What a person reads never names the other app: every message here is plain words about the request.
In-app notices to a person carry the kind prefix ``person_ask_`` so that the two apps' notice lists never
show each other's (the shared table is told apart by kind).

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
from agyary.messaging.formatting import numeric_date, parsi_label
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
    ServiceAskItem,
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
from agyary.services.funeral_records import NAME_NOT_KNOWN
from agyary.services.name_words import first_name

logger = logging.getLogger(__name__)

# What a person may ask, and how much.
MAX_ASKS_A_DAY = 5
MAX_WAITING_PER_AGYARI = 3
MAX_ITEMS = 10
MAX_NAMES = 20
NAME_MAX = template_text.DEPARTED_MAX
REASON_MAX = 100
DAYS_AHEAD = 400
OLDEST_DEATH_DAYS = 36500
# The repeats of "+ Add": monthly (same Roj every Mah) or yearly (same Roj and Mah every year).
MAX_REPEATS = mobed_dashboard.MAX_REPEAT_COUNT
MAX_PRICE = Decimal("1000000")

# What a memorial is made of when the panthaky confirms one: the diary's own defaults. The prayers are
# the memorial prayers of the catalog (the first of these that the fire temple offers), the days the
# usual named ones (Dasmu, Masiso, Varsi), and a monthly or yearly series if the person chose one.
MEMORIAL_PRAYERS = ("afringan", "farokshi", "baaj")
MEMORIAL_DAYS = (10, 30, 360)
MEMORIAL_NAME = "Memorial"

# 24 hours without an answer, told once; requests older than this are never told (no burst after an outage).
NO_ANSWER_AFTER = timedelta(hours=24)
NO_ANSWER_WITHIN = timedelta(days=14)
# Notices to a person stay for a month (they are the answer to something they asked).
PERSON_NOTICE_TTL = timedelta(days=30)
# What the panthaky is told lasts as long as the Requests tab's other notices do.
PANTHAKY_NOTICE_TTL = timedelta(days=2)

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
    """A rejected request or answer; the message is plain words, safe to show, and never names the other app."""

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


def _price(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


# ---------------------------------------------------------------------------
# What a fire temple offers
# ---------------------------------------------------------------------------
async def can_take(db: AsyncSession, settings: Settings, agyary: Agyary) -> bool:
    """The fire temple switched requests on, is open, and has a confirmed panthaky who can answer
    (their access on): otherwise a request would wait for nobody."""
    return bool(
        agyary.is_active and agyary.takes_asks and await panthaky.panthakys_of(db, settings, agyary.id)
    )


async def _offered_services(db: AsyncSession, agyary_id: int) -> list[Service]:
    """The services a person can pick: those the panthaky listed (``offered_to_people``, off until they do)
    that are still in the diary's catalog. A price is optional (owner, 27 Nov 2026): one without is shown
    with no price and settled with the panthaky in conversation."""
    return [s for s in await booking_service.list_services(db, agyary_id, exclude_machi=False)
            if s.offered_to_people]


def _memorial_prayers(offered: list[Service]) -> list[Service]:
    """The memorial prayers the fire temple offers: those of MEMORIAL_PRAYERS in its catalog. A memorial
    is made of them when the panthaky confirms. None offered: no memorial item."""
    by_name = {s.name.strip().lower(): s for s in offered}
    return [by_name[n] for n in MEMORIAL_PRAYERS if n in by_name]


async def offering_view(db: AsyncSession, settings: Settings, agyary: Agyary) -> dict:
    """What a person can pick at a fire temple: its priced services and, if it offers memorial prayers,
    the Memorial item. Nothing private; nothing at all when the fire temple is not taking requests."""
    takes = await can_take(db, settings, agyary)
    out = {
        "id": agyary.id, "name": agyary.name, "city": agyary.city, "kind": agyary.kind,
        "takes_requests": takes, "message": None if takes else NOT_TAKING,
        "services": [], "memorial": None,
        "gehs": [{"geh": n, "name": name} for n, name in GEH_NAMES.items()],
        "repeats": {k: {"max": v} for k, v in MAX_REPEATS.items()},
    }
    if takes:
        offered = await _offered_services(db, agyary.id)
        for s in offered:
            out["services"].append({
                "id": s.id, "type": "service", "name": s.name, "price": _price(s.default_price),
                "by_geh": is_slot_service(s),
            })
        prayers = _memorial_prayers(offered)
        if prayers:
            out["memorial"] = {"type": "memorial", "name": MEMORIAL_NAME, "price": None,
                               "prayers": [p.name for p in prayers]}
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


def clean_names(names: Any) -> list[str]:
    """The names to pray, typed: plain text, each following the rules for a name that is read out
    (no links, no @-handles, no long numbers)."""
    if names in (None, []):
        return []
    if not isinstance(names, list) or len(names) > MAX_NAMES:
        raise AskError(f"Please give up to {MAX_NAMES} names.")
    out = []
    for n in names:
        if not isinstance(n, str):
            raise AskError("Please check the names.")
        out.append(_clean_text(n, "each name", NAME_MAX, required=True))
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


def _repeat(raw: dict) -> tuple[str, int | None] | None:
    """The repeat of "+ Add": ``recurring`` monthly or yearly and ``recurring_count`` (2 up to 120 monthly
    or 60 yearly, counting the first; left out it has no end)."""
    pattern, count = raw.get("recurring"), raw.get("recurring_count")
    if pattern in (None, ""):
        if count is not None:
            raise AskError("Choose how it repeats: every month or every year.")
        return None
    if pattern not in MAX_REPEATS:
        raise AskError("Choose how it repeats: every month or every year.")
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


def _check_repeat_day(agyary: Agyary, day: date, slot: bool, pattern: str) -> None:
    """A repeat cannot start on a Gatha day (the diary's own rule, said up front)."""
    try:
        _roj, mah, _year = booking_service.slot_keys(agyary, day)
        mobed_dashboard.refuse_repeating_gatha(pattern, mah, "machi" if slot else "event")
    except mobed_dashboard.BookingInputError as exc:
        raise AskError(str(exc)) from exc
    except (ValueError, OverflowError) as exc:
        raise AskError("That is not a day in the Parsi calendar. Please choose another.") from exc


async def _clean_item(db: AsyncSession, agyary: Agyary, raw: Any, offered: dict[int, Service], position: int) -> dict:
    """One item of a request, checked, as the fields of a ServiceAskItem."""
    if not isinstance(raw, dict):
        raise AskError("Please check the request.")
    out: dict[str, Any] = {"position": position, "geh": None, "ceremony_time": None, "repeat_pattern": None,
                           "repeat_count": None, "memorial_choice": None, "unit_price": None, "purpose": None}
    repeat = _repeat(raw)
    if raw.get("type") == "memorial":
        if not _memorial_prayers(list(offered.values())):
            raise AskError("A memorial is not offered here.")
        died = _day(raw.get("death_date"), "date of passing")
        today = today_ist()
        if died > today:
            raise AskError("The date of passing cannot be in the future.")
        if died < today - timedelta(days=OLDEST_DEATH_DAYS):
            raise AskError("Please check the date of passing.")
        if repeat and repeat[1] is None:
            raise AskError("Choose how many times a memorial repeats.")
        out.update(kind="memorial", service_id=None, ceremony_date=died, memorial_choice={
            "departed_name": _clean_text(raw.get("departed_name"), "the name", NAME_MAX),
            "death_date": died.isoformat(),
            "recurring": repeat[0] if repeat else None, "count": repeat[1] if repeat else None})
        return out
    service = offered.get(raw.get("service_id")) if type(raw.get("service_id")) is int else None
    if service is None:
        raise AskError("That service is not offered here.")
    slot = is_slot_service(service)
    day = _day(raw.get("date"))
    purpose = raw.get("purpose") or ("tandarosti" if slot else "gujrela_nu")
    if purpose not in (MACHI_PURPOSES if slot else BOOKING_PURPOSES):
        raise AskError("Please check the request.")
    if slot:
        geh = raw.get("geh")
        if type(geh) is not int:
            raise AskError(f"Choose a geh for {service.name}.")
        _check_when(day, geh=geh, at=None)
        out["geh"] = geh
    else:
        at = _time(raw["time"]) if raw.get("time") not in (None, "") else None   # the time may be left open
        _check_when(day, geh=None, at=at)
        out["ceremony_time"] = at
    if repeat:
        _check_repeat_day(agyary, day, slot, repeat[0])
        out["repeat_pattern"], out["repeat_count"] = repeat
    out.update(kind="repeating" if repeat else "single", service_id=service.id, purpose=purpose,
               ceremony_date=day, unit_price=service.default_price)
    return out


async def create(
    db: AsyncSession, settings: Settings, user: User, body: dict, *, copied_from_id: int | None = None,
) -> ServiceAsk:
    """Check everything and keep the request, waiting. Nothing is booked: nothing is claimed in the fire
    temple's diary until its panthaky confirms, so a geh is checked only to be a real one still to come.
    The caller commits (``told_new`` after that)."""
    agyary = await db.get(Agyary, body.get("agyary_id")) if type(body.get("agyary_id")) is int else None
    if agyary is None or not agyary.is_active:
        raise AskError(NO_SUCH_AGYARI, 404)
    if not await can_take(db, settings, agyary):
        raise AskError(f"{NOT_TAKING}.")
    raw_items = body.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise AskError("Choose what to book.")
    if len(raw_items) > MAX_ITEMS:
        raise AskError(f"Up to {MAX_ITEMS} prayers in one request.")
    await _check_limits(db, user.id, agyary.id)
    offered = {s.id: s for s in await _offered_services(db, agyary.id)}
    names = clean_names(body.get("names"))
    items = [await _clean_item(db, agyary, raw, offered, i) for i, raw in enumerate(raw_items)]
    dated = [i["ceremony_date"] for i in items if i["kind"] != "memorial"]
    ask = ServiceAsk(
        user_id=user.id, agyary_id=agyary.id, names=names, status=ASK_WAITING, copied_from_id=copied_from_id,
        ceremony_date=min(dated) if dated else today_ist() + timedelta(days=30),
    )
    db.add(ask)
    await db.flush()
    for fields in items:
        db.add(ServiceAskItem(ask_id=ask.id, **fields))
    await db.flush()
    await db.refresh(ask)
    return ask


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


async def items_of(db: AsyncSession, ask_ids: list[int]) -> dict[int, list[ServiceAskItem]]:
    out: dict[int, list[ServiceAskItem]] = {i: [] for i in ask_ids}
    if ask_ids:
        for item in (await db.execute(
                select(ServiceAskItem).where(ServiceAskItem.ask_id.in_(ask_ids))
                .order_by(ServiceAskItem.ask_id, ServiceAskItem.position, ServiceAskItem.id)
                .execution_options(populate_existing=True))).scalars():
            out[item.ask_id].append(item)
    return out


async def live_of(db: AsyncSession, ask: ServiceAsk, item: ServiceAskItem) -> dict | None:
    """When a confirmed item happens, read from what it made in the fire temple's diary (not from the
    copy kept at asking), so a change there shows at once. None when the request is not confirmed, the
    item was removed, or what it made cannot be read (then the stored copy stands)."""
    if ask.status != ASK_ACCEPTED or item.gone_at is not None:
        return None
    if item.result_booking_id:
        b = await db.get(Booking, item.result_booking_id, populate_existing=True)
        if b is not None:
            local = b.ceremony_datetime.astimezone(IST)
            return {"date": local.date(), "time": local.time().replace(second=0, microsecond=0), "geh": None}
    if item.result_machi_id:
        m = await db.get(Machi, item.result_machi_id, populate_existing=True)
        if m is not None:
            return {"date": m.gregorian_date, "time": None, "geh": m.geh}
    if item.result_memorial_id:
        rows = (await db.execute(
            select(MemorialObservance.code, MemorialObservance.label, MemorialObservance.gregorian_date)
            .where(MemorialObservance.memorial_id == item.result_memorial_id)
            .order_by(MemorialObservance.gregorian_date, MemorialObservance.day_number))).all()
        if rows:
            return {"date": rows[0][2], "time": None, "geh": None,
                    "dates": [{"code": c, "label": lab, "date": d.isoformat()} for c, lab, d in rows]}
    return None


def _money(item: ServiceAskItem) -> dict:
    """An item's price and what it comes to: a repeat is the price for each time, times how many (an
    estimate; without an end only the first time is counted). A memorial has no price."""
    price = _price(item.unit_price)
    times = (item.repeat_count or 1) if item.kind == "repeating" else 1
    total = None if price is None else round(price * times, 2)
    return {"price": price, "times": times if item.kind == "repeating" else None, "total": total,
            "estimate": item.kind in ("repeating", "memorial")}


def serialize_item(item: ServiceAskItem, service_name: str | None, system: CalendarSystem, live: dict | None,
                   ask_status: str) -> dict:
    day, at, geh = item.ceremony_date, item.ceremony_time, item.geh
    if live:
        day, at, geh = live["date"], live["time"], live["geh"]
    out = {
        "id": item.id, "type": "memorial" if item.kind == "memorial" else "service", "kind": item.kind,
        "service": {"id": item.service_id, "name": service_name} if item.service_id else None,
        "name": MEMORIAL_NAME if item.kind == "memorial" else service_name,
        "date": day.isoformat(), "date_text": numeric_date(day), "parsi": _parsi(day, system),
        "geh": geh, "geh_name": GEH_NAMES.get(geh) if geh else None,
        "time": _hhmm(at), "time_open": item.kind != "memorial" and geh is None and at is None,
        "repeat": ({"recurring": item.repeat_pattern, "recurring_count": item.repeat_count}
                   if item.repeat_pattern else None),
        "memorial": None,
        "state": ASK_CANCELLED_BY_TEMPLE if item.gone_at is not None else ask_status,
        "changed": item.changed_at is not None and item.gone_at is None,
        **_money(item),
    }
    if item.kind == "memorial":
        saved = item.memorial_choice or {}
        out["memorial"] = {
            "departed_name": saved.get("departed_name") or NAME_NOT_KNOWN,
            "name_known": bool(saved.get("departed_name")),
            "death_date": saved.get("death_date"),
            "death_date_text": numeric_date(item.ceremony_date),
            "recurring": saved.get("recurring"), "recurring_count": saved.get("count"),
            "dates": [],
        }
        if live and live.get("dates"):
            out["memorial"]["dates"] = [
                {**d, "date_text": numeric_date(date.fromisoformat(d["date"])),
                 "parsi": _parsi(date.fromisoformat(d["date"]), system)} for d in live["dates"]]
    return out


def _totals(items: list[ServiceAskItem]) -> dict:
    live_items = [i for i in items if i.gone_at is None]
    prices = [m["total"] for m in map(_money, live_items) if m["total"] is not None]
    return {"total": round(sum(prices), 2) if prices else None,
            "total_is_estimate": any(i.kind in ("repeating", "memorial") for i in live_items)}


def label_of(ask: ServiceAsk) -> str:
    if ask.status == ASK_ACCEPTED and ask.changed_at is not None:
        return CHANGED_LABEL
    if ask.status == ASK_WAITING and ask.no_answer_alert_at is not None:
        return NO_ANSWER_LABEL
    return LABELS[ask.status]


async def _context(db: AsyncSession, asks: list[ServiceAsk]):
    """The services' and fire temples' names, and the items, for these requests."""
    items = await items_of(db, [a.id for a in asks])
    service_ids = {i.service_id for rows in items.values() for i in rows if i.service_id}
    services = dict((await db.execute(
        select(Service.id, Service.name).where(Service.id.in_(service_ids)))).all()) if service_ids else {}
    agyaries = {a.id: a for a in (await db.execute(
        select(Agyary).where(Agyary.id.in_({a.agyary_id for a in asks})))).scalars()} if asks else {}
    return items, services, agyaries


async def _request_view(db: AsyncSession, ask: ServiceAsk, items: list[ServiceAskItem], services: dict,
                        system: CalendarSystem) -> dict:
    views = []
    for item in items:
        live = await live_of(db, ask, item)
        views.append(serialize_item(item, services.get(item.service_id), system, live, ask.status))
    return {
        "id": ask.id, "status": ask.status, "label": label_of(ask),
        "no_answer": ask.status == ASK_WAITING and ask.no_answer_alert_at is not None,
        "changed": ask.changed_at is not None and ask.status == ASK_ACCEPTED,
        "changed_at": ask.changed_at.isoformat() if ask.changed_at else None,
        "items": views, "names": list(ask.names or []), **_totals(items),
        "reject_reason": ask.reject_reason,
        "created_at": ask.created_at.isoformat() if ask.created_at else None,
        "decided_at": ask.decided_at.isoformat() if ask.decided_at else None,
        "copied_from_id": ask.copied_from_id,
    }


async def _person_views(db: AsyncSession, asks: list[ServiceAsk], system: CalendarSystem) -> list[dict]:
    items, services, agyaries = await _context(db, asks)
    out = []
    for ask in asks:
        view = await _request_view(db, ask, items[ask.id], services, system)
        agyary = agyaries.get(ask.agyary_id)
        view.update(
            agyari={"id": ask.agyary_id, "name": agyary.name if agyary else None, "city": agyary.city if agyary else None},
            can_cancel=ask.status == ASK_WAITING or (ask.status == ASK_ACCEPTED and ask.ceremony_date > today_ist()),
            can_ask_another=ask.status in (ASK_REJECTED, ASK_CANCELLED, ASK_CANCELLED_BY_TEMPLE)
            or view["no_answer"],
        )
        out.append(view)
    return out


async def list_for_person(db: AsyncSession, user_id: int, system: CalendarSystem, limit: int = 100) -> list[dict]:
    asks = list((await db.execute(
        select(ServiceAsk).where(ServiceAsk.user_id == user_id)
        .order_by(ServiceAsk.created_at.desc(), ServiceAsk.id.desc()).limit(limit)
    )).scalars())
    return await _person_views(db, asks, system)


async def get_for_person(db: AsyncSession, user_id: int, ask_id: int, *, lock: bool = False) -> ServiceAsk | None:
    """Only the person's own: someone else's id is simply not found. ``lock`` holds the row until the
    change is committed, so two answers at once cannot both go through."""
    stmt = select(ServiceAsk).where(ServiceAsk.id == ask_id, ServiceAsk.user_id == user_id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return (await db.execute(stmt)).scalar_one_or_none()


async def person_view(db: AsyncSession, ask: ServiceAsk, system: CalendarSystem) -> dict:
    return (await _person_views(db, [ask], system))[0]


async def panthaky_views(db: AsyncSession, asks: list[ServiceAsk], system: CalendarSystem) -> list[dict]:
    """The panthaky's reading: the person's FIRST name, never the number (or the whole name).
    ``customer_id`` is their own record of the person once they have confirmed."""
    items, services, _agyaries = await _context(db, asks)
    names = dict((await db.execute(
        select(User.id, User.name).where(User.id.in_({a.user_id for a in asks})))).all()) if asks else {}
    out = []
    for ask in asks:
        view = await _request_view(db, ask, items[ask.id], services, system)
        view.update(person={"first_name": first_name(names.get(ask.user_id))}, customer_id=ask.result_customer_id)
        out.append(view)
    return out


async def list_for_agyary(db: AsyncSession, agyary_id: int, system: CalendarSystem, limit: int = 100) -> list[dict]:
    """Waiting requests first (the oldest first: it has waited longest), then the answered ones, newest first."""
    waiting = list((await db.execute(
        select(ServiceAsk).where(ServiceAsk.agyary_id == agyary_id, ServiceAsk.status == ASK_WAITING)
        .order_by(ServiceAsk.created_at, ServiceAsk.id).limit(limit)
    )).scalars())
    done = list((await db.execute(
        select(ServiceAsk).where(ServiceAsk.agyary_id == agyary_id, ServiceAsk.status != ASK_WAITING)
        .order_by(ServiceAsk.updated_at.desc(), ServiceAsk.id.desc()).limit(limit)
    )).scalars())
    return await panthaky_views(db, waiting + done, system)


async def for_agyary(db: AsyncSession, agyary_id: int, ask_id: int, *, lock: bool = False) -> ServiceAsk | None:
    """A request made to this fire temple. ``lock`` holds the row until the answer is committed, so two
    panthakys answering at once cannot both go through."""
    stmt = select(ServiceAsk).where(ServiceAsk.id == ask_id, ServiceAsk.agyary_id == agyary_id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    return (await db.execute(stmt)).scalar_one_or_none()


async def waiting_count(db: AsyncSession, agyary_id: int) -> int:
    return (await db.execute(select(func.count()).select_from(ServiceAsk).where(
        ServiceAsk.agyary_id == agyary_id, ServiceAsk.status == ASK_WAITING))).scalar_one()


# ---------------------------------------------------------------------------
# Telling people
# ---------------------------------------------------------------------------
async def _item_name(db: AsyncSession, item: ServiceAskItem) -> str:
    if item.kind == "memorial":
        return MEMORIAL_NAME
    return (await db.get(Service, item.service_id)).name


async def _summary(db: AsyncSession, ask: ServiceAsk) -> str:
    """"Jashan on 28/11/2026", and "+2 more" when there are more prayers."""
    items = (await items_of(db, [ask.id]))[ask.id]
    if not items:
        return "Request"
    first = items[0]
    out = f"{await _item_name(db, first)} on {numeric_date(first.ceremony_date)}"
    return out + (f" +{len(items) - 1} more" if len(items) > 1 else "")


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
    """A new request: every confirmed panthaky of the fire temple is told, with the person's first name and
    the first prayer (no number, no full name). Called after the request is committed."""
    person = await db.get(User, ask.user_id)
    await _tell_panthakys(db, settings, ask, KIND_NEW, "New request",
                          f"{first_name(person.name) or 'Someone'}: {await _summary(db, ask)}.")


# ---------------------------------------------------------------------------
# The person cancels, or asks another fire temple
# ---------------------------------------------------------------------------
CANCEL_NOTE = "Cancelled by the person."


async def cancel(db: AsyncSession, settings: Settings, ask: ServiceAsk) -> None:
    """The person cancels, any time before the day. A waiting request just stops waiting. A confirmed one
    is cancelled in the panthaky's diary as "by the person" and KEPT (D8): nothing is deleted. A memorial
    made from it stays in the panthaky's book as it is (its dates carry no cancelled state); the
    panthaky is told and can take it out."""
    if ask.status not in (ASK_WAITING, ASK_ACCEPTED):
        raise AskError("This request has already been answered or cancelled.", 409)
    if ask.status == ASK_ACCEPTED and ask.ceremony_date <= today_ist():
        raise AskError("Too late to cancel here. Speak to the fire temple.")
    was_accepted = ask.status == ASK_ACCEPTED
    items = (await items_of(db, [ask.id]))[ask.id]
    if was_accepted:
        for item in items:
            if item.gone_at is None:
                await _cancel_in_diary(db, item)
    summary = await _summary(db, ask)
    ask.status, ask.cancelled_at = ASK_CANCELLED, _now()
    await db.flush()
    await db.commit()
    person = await db.get(User, ask.user_id)
    memorial_made = any(i.kind == "memorial" and i.result_memorial_id for i in items)
    await _tell_panthakys(
        db, settings, ask, KIND_CANCELLED, "Request cancelled",
        f"{first_name(person.name) or 'Someone'}: {summary}."
        + (" Marked Cancelled by the person." if was_accepted else "")
        + (" Remove their memorial if not needed." if was_accepted and memorial_made else ""))


async def _cancel_in_diary(db: AsyncSession, item: ServiceAskItem) -> None:
    now = _now()
    if item.result_booking_id:
        booking = await db.get(Booking, item.result_booking_id)
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
    if item.result_machi_id:
        machi = await db.get(Machi, item.result_machi_id)
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
    """Copy a request that was declined, cancelled or never answered to another fire temple. A request
    nobody answered is withdrawn from the first one, so two cannot both say yes."""
    open_no_answer = ask.status == ASK_WAITING and ask.no_answer_alert_at is not None
    if ask.status not in (ASK_REJECTED, ASK_CANCELLED, ASK_CANCELLED_BY_TEMPLE) and not open_no_answer:
        raise AskError("Only a declined, cancelled or unanswered request can go to another fire temple.", 409)
    if type(agyary_id) is not int:
        raise AskError("Please choose a fire temple.")
    if agyary_id == ask.agyary_id and ask.status == ASK_WAITING:
        raise AskError("Please choose a different fire temple.")
    target = await db.get(Agyary, agyary_id)
    if target is None or not target.is_active:
        raise AskError(NO_SUCH_AGYARI, 404)
    items = (await items_of(db, [ask.id]))[ask.id]
    offered = {s.name.strip().lower(): s for s in await _offered_services(db, agyary_id)}
    body_items = []
    for item in items:
        if item.kind == "memorial":
            saved = item.memorial_choice or {}
            body_items.append({"type": "memorial", "departed_name": saved.get("departed_name"),
                               "death_date": item.ceremony_date, "recurring": saved.get("recurring"),
                               "recurring_count": saved.get("count")})
            continue
        old = await db.get(Service, item.service_id)
        match = offered.get(old.name.strip().lower())
        if match is None:
            raise AskError(f"That fire temple does not offer {old.name}.")
        body_items.append({"service_id": match.id, "date": item.ceremony_date, "geh": item.geh,
                           "time": item.ceremony_time, "purpose": item.purpose,
                           "recurring": item.repeat_pattern, "recurring_count": item.repeat_count})
    new = await create(db, settings, user, {"agyary_id": agyary_id, "items": body_items, "names": list(ask.names or [])},
                       copied_from_id=ask.id)
    if open_no_answer:
        ask.status, ask.cancelled_at = ASK_CANCELLED, _now()
        await db.flush()
    return new


# ---------------------------------------------------------------------------
# The panthaky answers
# ---------------------------------------------------------------------------
async def may_answer(db: AsyncSession, user: User, agyary_id: int) -> bool:
    """Only a confirmed panthaky of the fire temple answers (the entries are made in their own diary). The
    admin may read and switch requests on, but is not the one whose diary a confirm would fill."""
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
    await _tell_person(
        db, settings, ask, KIND_REJECTED, "Request declined",
        f"{agyary.name}: {await _summary(db, ask)}." + (f" Reason: {why}" if why else ""))


def _ceremony_names(names: list[str]) -> list[dict] | None:
    """The typed names as a ceremony's names (living names of the family: the panthaky can change them in
    the diary). None when there are none, so the person's saved names are used as in "+ Add"."""
    if not names:
        return None
    return [{"section": "farmayeshne", "title": "behdin", "name": n, "status": "living", "pair_group": None}
            for n in names]


def _times_given(times: Any) -> dict[int, time]:
    if times in (None, {}):
        return {}
    if not isinstance(times, dict):
        raise AskError("Please check the times.")
    out = {}
    for key, value in times.items():
        try:
            out[int(key)] = _time(value)
        except (ValueError, TypeError, AskError) as exc:
            raise AskError("Please check the times.") from exc
    return out


async def accept(db: AsyncSession, settings: Settings, ask: ServiceAsk, user: User, times: Any = None) -> dict:
    """Confirm the whole request: in ONE transaction the person becomes a record in the panthaky's own book
    (their name and number are shared with this panthaky now, and not before), one entry is made in the
    panthaky's own diary per item by the diary's own service, and the request is marked confirmed with
    what it made. ``times`` gives the time of day for items the person left open ({item id: "HH:MM"}).
    Anything the diary refuses (a geh already held, a day gone by, a time still open) leaves everything
    as it was and says so in plain words."""
    if ask.status != ASK_WAITING:
        raise AskError("This request has already been answered or cancelled.", 409)
    agyary = await db.get(Agyary, ask.agyary_id)
    person = await db.get(User, ask.user_id)
    if person is None or not person.is_active:
        raise AskError("This person is no longer in the app. Decline the request.", 409)
    if ask.ceremony_date < today_ist():
        raise AskError("That day has passed. Decline the request.", 409)
    given = _times_given(times)
    items = (await items_of(db, [ask.id]))[ask.id]
    names = _ceremony_names(list(ask.names or []))
    customer_id = None
    skipped: list[date] = []
    try:
        for item in items:
            made, customer_id, more = await _confirm_item(db, agyary, user, person, ask, item, names, given)
            skipped += more
    except (mobed_dashboard.BookingInputError, memorials.MemorialError) as exc:
        raise AskError(str(exc)) from exc
    ask.status, ask.decided_at, ask.decided_by_user_id = ASK_ACCEPTED, _now(), user.id
    ask.result_customer_id = customer_id
    await db.flush()
    summary = await _summary(db, ask)
    await db.commit()
    await _tell_person(db, settings, ask, KIND_ACCEPTED, "Request confirmed", f"{agyary.name}: {summary}.")
    return {"ask_id": ask.id, "customer_id": customer_id, "skipped": [d.isoformat() for d in skipped],
            "items": [{"id": i.id, "booking_id": i.result_booking_id, "machi_id": i.result_machi_id,
                       "memorial_id": i.result_memorial_id} for i in items]}


async def _confirm_item(db, agyary: Agyary, user: User, person: User, ask: ServiceAsk, item: ServiceAskItem,
                        names: list[dict] | None, given: dict[int, time]):
    """Make one item's entry in the panthaky's diary. Returns (entry, the person's record id, skipped dates)."""
    if item.kind == "memorial":
        memorial = await _confirm_memorial(db, agyary, user, person, item)
        item.result_memorial_id = memorial.id
        return memorial, memorial.customer_id, []
    service = await booking_service.get_service_by_id(db, agyary.id, item.service_id)
    if service is None:
        raise AskError("A service of this request is no longer offered. Decline the request.", 409)
    if item.ceremony_date < today_ist():
        raise AskError(f"The day of {service.name} has passed. Decline the request.", 409)
    if is_slot_service(service):
        roj, mah, year = booking_service.slot_keys(agyary, item.ceremony_date)
        result = await mobed_dashboard.manual_add_machi(
            db, agyary, user.id, behdin_phone=person.phone, behdin_name=person.name,
            roj=roj, mah=mah, year=year, geh=item.geh, gregorian=item.ceremony_date, purpose=item.purpose,
            names=names, recurring=item.repeat_pattern, recurring_count=item.repeat_count,
        )
        if result.machi is None:
            raise AskError(
                f"You already hold that geh on {numeric_date(item.ceremony_date)}. Decline the request, "
                "or ask the person to choose another day.", 409)
        item.result_machi_id = result.machi.id
        return result.machi, result.machi.customer_id, list(result.skipped)
    at = item.ceremony_time or given.get(item.id)
    if at is None:
        raise AskError(f"Enter a time for {service.name} on {numeric_date(item.ceremony_date)}.", 409)
    result = await mobed_dashboard.manual_add_booking(
        db, agyary, user.id, behdin_phone=person.phone, behdin_name=person.name,
        service_id=service.id, ceremony_dt_local=datetime.combine(item.ceremony_date, at),
        purpose=item.purpose, names=names, location=None, is_offsite=False,
        recurring=item.repeat_pattern, recurring_count=item.repeat_count,
    )
    if result is None:
        raise AskError("A service of this request is no longer offered. Decline the request.", 409)
    item.ceremony_time = at
    item.result_booking_id = result.booking.id
    return result.booking, result.booking.customer_id, []


async def _confirm_memorial(db, agyary: Agyary, user: User, person: User, item: ServiceAskItem):
    """The memorial, made as the diary's own flow makes one, with its defaults: the usual named days
    (Dasmu, Masiso, Varsi), a monthly or yearly series if the person chose one, the memorial prayers of
    the catalog, nothing booked before today. (An older request keeps the choices it was made with.)"""
    saved = item.memorial_choice or {}
    customer, _created = await behdin_directory.create_or_link(
        db, agyary.id, user.id, name=person.name, phone=person.phone)
    legacy = saved.get("legacy")
    if legacy:
        choice = behdin_me.choice_from_ask(legacy["choice"])
        service = await booking_service.get_service_by_id(db, agyary.id, (await _legacy_service(db, item)))
        prayers = [service] if service else []
        system = await memorials.calendar_for(db, user.id, choice)
        schedule, _death, _date = memorials.plan(system, choice, memorials.today_ist())
        keep = set(legacy.get("codes") or [])
        leave_out = tuple(o.code for o in schedule if o.code not in keep)
    else:
        prayers = _memorial_prayers(await _offered_services(db, agyary.id))
        count, pattern = saved.get("count"), saved.get("recurring")
        choice = memorials.Choice(
            departed_name=saved.get("departed_name") or NAME_NOT_KNOWN,
            death_date=date.fromisoformat(saved["death_date"]), day_counts=MEMORIAL_DAYS,
            monthly_months=count if pattern == "monthly" else None,
            yearly_years=count if pattern == "yearly" else None,
            start_from=today_ist(),
        )
        leave_out = ()
    if not prayers:
        raise AskError("No memorial prayer is offered now. Decline the request.", 409)
    try:
        return await memorials.create_memorial(db, agyary, user.id, customer, choice, [p.id for p in prayers], leave_out)
    except memorials.MemorialError as exc:
        text = str(exc)
        raise AskError(text + " Decline the request." if "Nothing is left" in text else text, 409) from exc


async def _legacy_service(db: AsyncSession, item: ServiceAskItem) -> int | None:
    """The service an older memorial request was made with (kept on the ask's item as its service)."""
    return item.service_id


# ---------------------------------------------------------------------------
# What the fire temple's diary says now (a request follows its result)
# ---------------------------------------------------------------------------
def _live_words(item: ServiceAskItem, live: dict | None) -> str:
    if live is None:
        return numeric_date(item.ceremony_date)
    out = numeric_date(live["date"])
    if live.get("time"):
        out += " " + live["time"].strftime("%H:%M")
    if live.get("geh"):
        out += f", {GEH_NAMES[live['geh']]}"
    return out


async def _items_pointing_at(db: AsyncSession, *, booking_ids=(), machi_ids=(), memorial_ids=()):
    conds = []
    if booking_ids:
        conds.append(ServiceAskItem.result_booking_id.in_(list(booking_ids)))
    if machi_ids:
        conds.append(ServiceAskItem.result_machi_id.in_(list(machi_ids)))
    if memorial_ids:
        conds.append(ServiceAskItem.result_memorial_id.in_(list(memorial_ids)))
    if not conds:
        return []
    return list((await db.execute(
        select(ServiceAskItem, ServiceAsk).join(ServiceAsk, ServiceAsk.id == ServiceAskItem.ask_id)
        .where(ServiceAsk.status == ASK_ACCEPTED, ServiceAskItem.gone_at.is_(None), or_(*conds))
        .with_for_update()
    )).all())


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
    series, a memorial). The item is flagged gone. A request whose items are ALL gone becomes "Cancelled by
    the fire temple"; one with items still standing stays confirmed, marked Changed, with the item flagged.
    Either way the person is told. Called BEFORE the diary row goes, from every place that deletes or
    stops one. Returns how many items."""
    rows = await _items_pointing_at(db, booking_ids=booking_ids, machi_ids=machi_ids, memorial_ids=memorial_ids)
    touched: dict[int, tuple[ServiceAsk, list[tuple[ServiceAskItem, dict | None]]]] = {}
    for item, ask in rows:
        live = await live_of(db, ask, item)
        item.gone_at = _now()
        touched.setdefault(ask.id, (ask, []))[1].append((item, live))
    await db.flush()
    for ask, gone in touched.values():
        agyary = await db.get(Agyary, ask.agyary_id)
        standing = (await db.execute(select(func.count()).select_from(ServiceAskItem).where(
            ServiceAskItem.ask_id == ask.id, ServiceAskItem.gone_at.is_(None)))).scalar_one()
        item, live = gone[0]
        name = await _item_name(db, item)
        if standing == 0:
            ask.status, ask.cancelled_at = ASK_CANCELLED_BY_TEMPLE, _now()
            await db.flush()
            await _tell_person_in_txn(
                db, ask, KIND_TEMPLE_CANCELLED, "Request cancelled",
                f"Cancelled by {agyary.name}: {name} on {_live_words(item, live)}")
        else:
            ask.changed_at = _now()
            await db.flush()
            await _tell_person_in_txn(
                db, ask, KIND_TEMPLE_CHANGED, "Request changed",
                f"Changed by {agyary.name}: {name} on {_live_words(item, live)} cancelled")
    return len(rows)


async def fire_temple_changed(db: AsyncSession, *, booking_id=None, machi_id=None, memorial_id=None) -> int:
    """The fire temple changed the date, time or geh of what a confirmed request made: the item and the
    request record it (``changed_at``) and the person is told what it is now. Called AFTER the change is flushed."""
    rows = await _items_pointing_at(
        db, booking_ids=[booking_id] if booking_id else (), machi_ids=[machi_id] if machi_id else (),
        memorial_ids=[memorial_id] if memorial_id else ())
    for item, ask in rows:
        live = await live_of(db, ask, item)
        item.changed_at = ask.changed_at = _now()
        agyary = await db.get(Agyary, ask.agyary_id)
        name = await _item_name(db, item)
        await db.flush()
        await _tell_person_in_txn(
            db, ask, KIND_TEMPLE_CHANGED, "Request changed",
            f"Changed by {agyary.name}: {name}, now {_live_words(item, live)}")
    return len(rows)


async def calendar_items(db: AsyncSession, user_id: int, start: date, end: date, system: CalendarSystem) -> list[dict]:
    """The person's confirmed requests that fall between two days, read from what the fire temple's diary
    holds now. An item the fire temple removed is not here; nor is a request the person cancelled."""
    asks = list((await db.execute(
        select(ServiceAsk).where(ServiceAsk.user_id == user_id, ServiceAsk.status == ASK_ACCEPTED)
        .order_by(ServiceAsk.id))).scalars())
    if not asks:
        return []
    items, services, agyaries = await _context(db, asks)
    out = []

    def add(ask, item, when, at=None, geh=None, label=None):
        if not start <= when <= end:
            return
        parsi = behdin_me.parsi_of(when, system)
        roj, mah = behdin_me._roj_mah(parsi)
        name = agyaries[ask.agyary_id].name if ask.agyary_id in agyaries else ""
        what = MEMORIAL_NAME if item.kind == "memorial" else services.get(item.service_id, "")
        out.append({
            "kind": "request", "source": "request", "id": ask.id, "item_id": item.id,
            "title": f"{what} - {name}" + (f" ({label})" if label else ""),
            "date": when.isoformat(), "time": _hhmm(at), "geh": geh,
            "parsi_roj": roj, "parsi_mah": mah, "parsi": parsi,
        })

    for ask in asks:
        for item in items[ask.id]:
            if item.gone_at is not None:
                continue
            if item.result_booking_id:
                first = await db.get(Booking, item.result_booking_id, populate_existing=True)
                rows = [first] if first is not None else []
                if first is not None and first.recurrence_rule_id:
                    rows = list((await db.execute(select(Booking).where(
                        Booking.recurrence_rule_id == first.recurrence_rule_id, Booking.status != "cancelled"))).scalars())
                for b in rows:
                    local = b.ceremony_datetime.astimezone(IST)
                    add(ask, item, local.date(), local.time().replace(second=0, microsecond=0))
            elif item.result_machi_id:
                first = await db.get(Machi, item.result_machi_id, populate_existing=True)
                rows = [first] if first is not None else []
                if first is not None and first.recurrence_rule_id:
                    rows = list((await db.execute(select(Machi).where(
                        Machi.recurrence_rule_id == first.recurrence_rule_id, Machi.status != "cancelled"))).scalars())
                for m in rows:
                    add(ask, item, m.gregorian_date, geh=m.geh)
            elif item.result_memorial_id:
                for _code, lab, when in (await db.execute(
                        select(MemorialObservance.code, MemorialObservance.label, MemorialObservance.gregorian_date)
                        .where(MemorialObservance.memorial_id == item.result_memorial_id))).all():
                    add(ask, item, when, label=lab)
    return out


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
    """Take this request for "No answer yet", once, while it is still waiting: committed before anyone is told."""
    claimed = (await db.execute(
        update(ServiceAsk)
        .where(ServiceAsk.id == ask_id, ServiceAsk.status == ASK_WAITING, ServiceAsk.no_answer_alert_at.is_(None))
        .values(no_answer_alert_at=now).returning(ServiceAsk.id)
    )).scalar_one_or_none()
    await db.commit()
    return claimed is not None


async def no_answer(db: AsyncSession, now: datetime, settings: Settings) -> int:
    """Tell, once, each person whose request nobody answered in 24 hours; the request stays waiting and they
    can ask another fire temple. Returns how many it told."""
    done = 0
    for ask_id in await _no_answer_due(db, now):
        if not await _claim_no_answer(db, ask_id, now):
            continue
        done += 1
        try:
            ask = await db.get(ServiceAsk, ask_id, populate_existing=True)
            agyary = await db.get(Agyary, ask.agyary_id)
            await _tell_person(db, settings, ask, KIND_NO_ANSWER, NO_ANSWER_LABEL,
                               f"{agyary.name}: {await _summary(db, ask)}.")
        except Exception:   # noqa: BLE001 - it is claimed (at most once); the next request still goes
            logger.exception("Telling that nobody answered request %s failed after it was claimed", ask_id)
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
async def _offered(db: AsyncSession, agyary_id: int) -> list[Service]:
    """The services the fire temple has listed for people."""
    return list((await db.execute(
        select(Service).where(Service.agyary_id == agyary_id, Service.is_active.is_(True),
                              Service.offered_to_people.is_(True))
        .order_by(Service.display_order, Service.id))).scalars())


async def read_switch(db: AsyncSession, agyary: Agyary) -> dict:
    """The switch, the services that will be offered with their prices, and whether it can be switched
    on (``ready``: every offered service has a price)."""
    offered = await _offered(db, agyary.id)
    return {
        "takes_asks": bool(agyary.takes_asks), "ready": True,
        "services": [{"id": s.id, "name": s.name, "price": _price(s.default_price)} for s in offered],
    }


async def change_switch(db: AsyncSession, agyary: Agyary, value: Any) -> dict:
    """On or off at any time: listing services, with or without prices, is the panthaky's choice."""
    if type(value) is not bool:
        raise AskError("Choose on or off.")
    agyary.takes_asks = value
    return await read_switch(db, agyary)


def _service_price_row(s: Service) -> dict:
    return {"id": s.id, "name": s.name, "offered": s.offered_to_people, "offsite_capable": s.offsite_capable,
            "default_price": _price(s.default_price)}


async def list_prices(db: AsyncSession, agyary_id: int) -> list[dict]:
    rows = (await db.execute(
        select(Service).where(Service.agyary_id == agyary_id, Service.is_active.is_(True))
        .order_by(Service.display_order, Service.id))).scalars()
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
    db: AsyncSession, agyary: Agyary, service: Service, *, fields: set[str], price: Any, offered: Any,
) -> dict:
    """The price (optional) and whether the service is listed for people; either may change at any time.
    Listing never touches the diary's own catalog (``is_active``)."""
    new_price = checked_price(price) if "default_price" in fields else service.default_price
    if "offered" in fields and type(offered) is not bool:
        raise AskError("Choose on or off.")
    service.default_price = new_price
    if "offered" in fields:
        service.offered_to_people = offered
    return _service_price_row(service)


async def add_service(db: AsyncSession, agyary: Agyary, name: Any) -> dict:
    """A service of the panthaky's own, listed for people at once. It is also in the diary's catalog
    (that is one list), where a name already there is reused, not doubled."""
    text = " ".join(name.split()) if isinstance(name, str) else ""
    if not text:
        raise AskError("Please enter the service's name.")
    try:
        template_text.check(text, "service name", max_len=template_text.SERVICE_MAX)
    except ValueError as exc:
        raise AskError(str(exc)) from exc
    existing = (await db.execute(select(Service).where(
        Service.agyary_id == agyary.id, func.lower(Service.name) == text.lower()))).scalar_one_or_none()
    if existing is not None:
        if existing.is_active and existing.offered_to_people:
            raise AskError(f"{existing.name} is already in your list.", 409)
        existing.is_active = existing.offered_to_people = True
        return _service_price_row(existing)
    service = Service(agyary_id=agyary.id, name=text, offsite_capable=False, display_order=999,
                      is_active=True, offered_to_people=True)
    db.add(service)
    await db.flush()
    return _service_price_row(service)
