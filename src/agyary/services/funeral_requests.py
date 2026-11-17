"""Sending a funeral record to a fire temple (DECISIONS D10, Phase 2 Step 4).

Choosing the fire temple: "Suggested" lists every fire temple in the app with a
position, nearest first by straight-line distance from the funeral place,
within NEAR_KM; the family's preferred one goes first whatever its distance.
"Search all" finds any of them by name or town. Each says whether a request
would reach anyone: a confirmed panthaky, only mobeds, or nobody in the app yet
(services/panthaky.py, the same rule as who it is sent to).

Sending: only with the tick that the family agreed to share their name and
number with that fire temple. It goes to the fire temple's confirmed
panthakys, or if it has none whose access is on, to its mobeds whose access is
on (D9: nothing to an account that is not on); with nobody, it is refused and
the manager is told why - never sent to no one. One request waits per record at
a time; the manager can withdraw it and send to another fire temple.

Each person asked gets a notice in the app (the departed's prayed name, the
place and bungli, the prayers and their times) and a phone notification that
says only which place asks which fire temple. The family's name and number are
in neither: a mobed sees them only once they accept (Step 5).
"""

from __future__ import annotations

import logging
import math
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.core.config import Settings
from agyary.models import Agyary, FuneralPlace, FuneralRecord, FuneralRequest, FuneralRequestRecipient, User
from agyary.models.enums import GEH_NAMES, REQUEST_WAITING, REQUEST_WITHDRAWN
from agyary.services import funeral_records, mobed_access, mobed_dashboard, panthaky, reminders, web_push

logger = logging.getLogger(__name__)

NEAR_KM = 500
MAX_SUGGESTED = 100
SEARCH_LIMIT = 20
EARTH_RADIUS_KM = 6371.0


def km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Straight-line (great-circle) distance in km, by the haversine formula."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(h)))


def _has_position(x) -> bool:
    return x is not None and x.latitude is not None and x.longitude is not None


def _distance(place: FuneralPlace, agyary: Agyary) -> float | None:
    if not (_has_position(place) and _has_position(agyary)):
        return None
    return km(place.latitude, place.longitude, agyary.latitude, agyary.longitude)


async def _rows(
    db: AsyncSession, settings: Settings, place: FuneralPlace, agyaries: list[Agyary], preferred_id: int | None,
) -> list[dict]:
    reach = await panthaky.reach_of(db, settings, [a.id for a in agyaries])
    out = []
    for a in agyaries:
        d = _distance(place, a)
        out.append({
            "id": a.id, "name": a.name, "city": a.city, "address": a.address,
            "km": round(d, 1) if d is not None else None,
            # "town": only the town's position is known yet, so the distance is rough.
            "location_source": a.location_source,
            "reach": reach[a.id],
            "may_send": reach[a.id] != panthaky.REACH_NOBODY,
            "preferred": a.id == preferred_id,
        })
    return out


async def suggested(
    db: AsyncSession, settings: Settings, place: FuneralPlace, preferred_id: int | None = None,
) -> dict:
    """The fire temples to suggest for a record at ``place``: the family's
    preferred one first, then those within NEAR_KM, nearest first. With no
    position for the place there is nothing to measure from: only the
    preferred one, and ``place_has_position`` False (the app offers search)."""
    chosen: list[tuple[float, Agyary]] = []
    if _has_position(place):
        candidates = (
            await db.execute(
                select(Agyary).where(
                    Agyary.is_active.is_(True), Agyary.latitude.is_not(None), Agyary.longitude.is_not(None)
                )
            )
        ).scalars().all()
        for a in candidates:
            d = _distance(place, a)
            if d is not None and d <= NEAR_KM and a.id != preferred_id:
                chosen.append((d, a))
        chosen.sort(key=lambda pair: (pair[0], pair[1].name))
    agyaries = [a for _, a in chosen[:MAX_SUGGESTED]]
    if preferred_id is not None:
        preferred = await db.get(Agyary, preferred_id)
        if preferred is not None and preferred.is_active:
            agyaries.insert(0, preferred)
    return {
        "place_has_position": _has_position(place),
        "near_km": NEAR_KM,
        "agyaries": await _rows(db, settings, place, agyaries, preferred_id),
    }


async def search(
    db: AsyncSession, settings: Settings, place: FuneralPlace, q: str, preferred_id: int | None = None,
) -> list[dict]:
    """Any fire temple in the app by name or town (the sign-up search), with
    its distance from ``place`` where both have a position."""
    found = await mobed_dashboard.search_agyaries(db, q[:100], limit=SEARCH_LIMIT)
    return await _rows(db, settings, place, found, preferred_id)


# ---------------------------------------------------------------------------
# Sending, and withdrawing
# ---------------------------------------------------------------------------
KIND_REQUEST = "funeral_request"
KIND_CHANGED = "funeral_request_changed"
KIND_WITHDRAWN = "funeral_request_withdrawn"
# The Requests tab, which Step 5 builds.
REQUESTS_LINK = "#/requests"
NOTICE_TTL = timedelta(days=7)
KIND_WORDS = {"doongerwadi": "A Doongerwadi", "prayer_hall": "A prayer hall", "aramgah": "An aramgah"}


class SendError(ValueError):
    """A request that cannot go (or be withdrawn) now; the message is for the
    manager, ``status`` the HTTP answer."""

    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


NO_TICK = ("Please tick that the family agreed to share their name and number with this fire temple. "
           "Without it the request cannot be sent.")


def nobody_there(agyary: Agyary) -> str:
    return (f"Nobody at {agyary.name} uses Mobed Diary yet, so the request cannot reach them. "
            "Please choose another fire temple, or get in touch with them yourself.")


def _day(d: date) -> str:
    return f"{d:%a} {d.day} {d:%b}"


def _clock(t: time) -> str:
    return f"{t.hour % 12 or 12}:{t.minute:02d} {'am' if t.hour < 12 else 'pm'}"


def notice_text(record: FuneralRecord, place: FuneralPlace, agyary: Agyary) -> tuple[str, str]:
    """The in-app notice to the people asked: who is prayed for, where, which
    prayers and when. Never the family's name or number."""
    title = f"{KIND_WORDS.get(place.kind, 'A Doongerwadi')} asks for prayers"
    where = place.name + (f", {record.bungli}" if record.bungli else "")
    parts = [
        f"{funeral_records.prayed_name(record.departed_title, record.departed_name, record.departed_parent_name)}.",
        f"{where}.",
        f"{funeral_records.OBSEQUIES_LABELS.get(record.obsequies, '')}.",
    ]
    if record.geh_saarnu_date:
        parts.append(f"Geh-saarnu: {_day(record.geh_saarnu_date)}, {GEH_NAMES.get(record.geh_saarnu_geh)} geh.")
    if record.uthamna_date:
        at = f", {_clock(record.uthamna_time)}" if record.uthamna_time else ""
        parts.append(f"Uthamna: {_day(record.uthamna_date)}{at}.")
    if record.mobeds_wanted:
        parts.append(f"{record.mobeds_wanted} mobed{'s' if record.mobeds_wanted != 1 else ''} wanted.")
    parts.append(f"Asked of {agyary.name}. Open Requests to answer.")
    return title, " ".join(parts)


def push_text(place: FuneralPlace, agyary: Agyary, what: str = "asks") -> tuple[str, str]:
    """What a phone's lock screen shows: which place asks which fire temple,
    and nothing about the departed or the family."""
    body = {
        "asks": f"{place.name} asks {agyary.name} for prayers.",
        "changed": f"{place.name} changed its request to {agyary.name}.",
        "withdrawn": f"{place.name} withdrew its request to {agyary.name}.",
    }[what]
    return "A request for prayers", body


async def _tell(
    db: AsyncSession, settings: Settings, users: list[User], request: FuneralRequest, *, kind: str,
    title: str, body: str, push: tuple[str, str], now: datetime,
) -> None:
    """A notice in the app and on the phones of those of ``users`` whose
    access is on. A failed push is logged by web_push; the notice stays."""
    users = [u for u in users if u.is_active and mobed_access.has_access(settings, u)]
    for u in users:
        await reminders.notify(
            db, u.id, kind, title, body, link=REQUESTS_LINK, agyary_id=request.agyary_id, now=now, ttl=NOTICE_TTL,
        )
    if users:
        await web_push.send_to_users(
            db, settings, [u.id for u in users], title=push[0], body=push[1],
            url="/mobed" + REQUESTS_LINK, tag=f"funeral-request-{request.id}",
        )


async def asked(db: AsyncSession, request: FuneralRequest) -> list[User]:
    """Who this request was sent to (the accounts still there)."""
    return list(
        (await db.execute(
            select(User).join(FuneralRequestRecipient, FuneralRequestRecipient.user_id == User.id)
            .where(FuneralRequestRecipient.funeral_request_id == request.id).order_by(User.id)
        )).scalars().all()
    )


async def send(
    db: AsyncSession, settings: Settings, manager: User, record: FuneralRecord, agyary: Agyary, *,
    family_agreed: bool, now: datetime | None = None,
) -> FuneralRequest:
    """Send ``record`` to ``agyary``. SendError says why not."""
    if not family_agreed:
        raise SendError(NO_TICK, status=400)
    now = now or datetime.now(timezone.utc)
    # Locked, so two taps (or two managers) cannot both send it.
    await db.refresh(record, with_for_update=True)
    place = await db.get(FuneralPlace, record.funeral_place_id)
    if not place.is_active:
        raise SendError(f"{place.name} is turned off in Mobed Diary at the moment. Please get in touch.")
    requests = (await funeral_records.requests_of(db, [record.id]))[record.id]
    if funeral_records.accepted(requests):
        raise SendError("A fire temple has already accepted this request.")
    open_one = funeral_records.waiting(requests)
    if open_one:
        at = await db.get(Agyary, open_one.agyary_id)
        raise SendError(f"This request is already waiting at {at.name}. To send it to another fire temple, "
                        "withdraw it there first.")
    if not agyary.is_active:
        raise SendError("That fire temple could not be found. Please choose it again.", status=404)
    recipients = await panthaky.request_recipients(db, settings, agyary.id)
    if not recipients:
        raise SendError(nobody_there(agyary))

    request = FuneralRequest(
        funeral_record_id=record.id, agyary_id=agyary.id, status=REQUEST_WAITING,
        family_share_agreed_at=now, sent_by_user_id=manager.id, sent_at=now,
    )
    db.add(request)
    await db.flush()
    for u in recipients:
        db.add(FuneralRequestRecipient(funeral_request_id=request.id, user_id=u.id, notified_at=now))
    await db.flush()
    title, body = notice_text(record, place, agyary)
    await _tell(db, settings, recipients, request, kind=KIND_REQUEST, title=title, body=body,
                push=push_text(place, agyary), now=now)
    logger.warning(
        "Funeral record %s sent to fire temple %s by manager %s (%d asked)",
        record.id, agyary.id, manager.id, len(recipients),
    )
    return request


async def withdraw(
    db: AsyncSession, settings: Settings, manager: User, request: FuneralRequest, *, now: datetime | None = None,
) -> FuneralRequest:
    """The manager takes back a waiting request; those asked are told."""
    now = now or datetime.now(timezone.utc)
    record = await db.get(FuneralRecord, request.funeral_record_id)
    await db.refresh(record, with_for_update=True)
    await db.refresh(request)
    if request.status != REQUEST_WAITING:
        raise SendError("This request is no longer waiting, so there is nothing to withdraw.")
    request.status = REQUEST_WITHDRAWN
    request.decided_at = now
    request.decided_by_user_id = manager.id
    await db.flush()
    place = await db.get(FuneralPlace, record.funeral_place_id)
    agyary = await db.get(Agyary, request.agyary_id)
    name = funeral_records.prayed_name(record.departed_title, record.departed_name, record.departed_parent_name)
    await _tell(
        db, settings, await asked(db, request), request, kind=KIND_WITHDRAWN,
        title="A request for prayers was withdrawn",
        body=f"{place.name} withdrew its request to {agyary.name} for {name}. Nothing more is needed for it.",
        push=push_text(place, agyary, "withdrawn"), now=now,
    )
    logger.warning("Funeral request %s withdrawn by manager %s", request.id, manager.id)
    return request


async def tell_of_change(
    db: AsyncSession, settings: Settings, record: FuneralRecord, *, now: datetime | None = None,
) -> int:
    """After a waiting record is changed, those asked get its details again.
    Returns how many were told."""
    request = funeral_records.waiting((await funeral_records.requests_of(db, [record.id]))[record.id])
    if request is None:
        return 0
    now = now or datetime.now(timezone.utc)
    place = await db.get(FuneralPlace, record.funeral_place_id)
    agyary = await db.get(Agyary, request.agyary_id)
    people = await asked(db, request)
    _, body = notice_text(record, place, agyary)
    await _tell(db, settings, people, request, kind=KIND_CHANGED, title="A request for prayers was changed",
                body=body, push=push_text(place, agyary, "changed"), now=now)
    return len(people)
