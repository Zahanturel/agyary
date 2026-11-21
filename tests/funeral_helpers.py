"""What the funeral record and request tests share: a manager at a place, a
record's form filled in, and fire temples with people in them (Step 4)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from agyary.models import Agyary, AgyaryUser, FuneralPlace, FuneralPlaceManager, FuneralRecord, FuneralRequest, User
from agyary.services import funeral_answers, funeral_records
from tests.conftest import sign_in

MANAGER = "+919911100071"
FAMILY = "+919822200033"
# The Mumbai Doongerwadi's neighbourhood, near enough (not a real pin).
MUMBAI = (18.957, 72.806)


def auth(body: dict) -> dict:
    return {"Authorization": f"Bearer {body['access_token']}"}


async def place(db, name="Doongerwadi (test)", *, position=MUMBAI, kind="doongerwadi") -> FuneralPlace:
    p = FuneralPlace(name=name, kind=kind, city="Mumbai")
    p.latitude, p.longitude = position if position else (None, None)
    db.add(p)
    await db.flush()
    return p


async def manager(client, db, *, phone=MANAGER, name="Test Manager", at: FuneralPlace | None = None):
    """A manager's account, approved, at ``at`` (a new place if not given)."""
    body = await sign_in(client, phone, name)
    uid = body["user"]["id"]
    at = at or await place(db)
    db.add(FuneralPlaceManager(funeral_place_id=at.id, user_id=uid))
    await db.execute(update(User).where(User.id == uid).values(account_kind="funeral_manager", access="on"))
    await db.commit()
    return auth(body), at


def form(**changes) -> dict:
    """A record's form as the app sends it, for a death yesterday."""
    today = funeral_records.today_ist()
    body = {
        "departed_title": "behdin", "departed_name": "Rustom", "departed_parent_name": "Jamshed",
        "calendar": "shenshai", "death_date": (today - timedelta(days=1)).isoformat(),
        "obsequies": "four_days",
        "geh_saarnu_date": today.isoformat(), "geh_saarnu_geh": 1,
        "uthamna_date": (today + timedelta(days=2)).isoformat(), "uthamna_time": "16:00",
        "mobeds_wanted": 5, "family_contact_name": "Test Family", "family_contact_phone": FAMILY,
    }
    body.update(changes)
    return body


async def agyari(db, name: str, position: tuple[float, float] | None, *, city="Mumbai", status="active") -> Agyary:
    a = Agyary(name=name, city=city, status=status)
    if position:
        a.latitude, a.longitude, a.location_source = position[0], position[1], "pin"
    db.add(a)
    await db.flush()
    return a


async def member(db, agyary: Agyary, phone: str, role: str = "mobed", *, access="on", name=None) -> User:
    u = User(name=name or f"Er. Member {phone[-3:]}", phone=phone, access=access)
    db.add(u)
    await db.flush()
    db.add(AgyaryUser(agyary_id=agyary.id, user_id=u.id, role=role))
    await db.flush()
    return u


async def accepted_the_old_way(db, request_id: int, phone: str, *, share: bool = True, book: bool = True):
    """A request accepted the old way, before R3.1, as accepting left it: the
    Accept is gone since R3.1 step 7, but those requests stay (D8) and must
    still read right. The request accepted by the person with ``phone``, their
    name and number shared with the place or not, and (``book``) the family in
    their own book with the Geh-saarnu and Uthamna on their calendar
    (funeral_answers.put_in_book, which All set uses too). Returns what
    put_in_book did, or None."""
    user = (await db.execute(select(User).where(User.phone == phone))).scalar_one()
    request = await db.get(FuneralRequest, request_id, populate_existing=True)
    now = datetime.now(timezone.utc)
    request.status, request.decided_at = "accepted", now
    request.accepted_by_user_id = request.decided_by_user_id = user.id
    request.accepter_shared_contact = share
    done = None
    if book:
        record = await db.get(FuneralRecord, request.funeral_record_id)
        place = await db.get(FuneralPlace, record.funeral_place_id)
        agyary = await db.get(Agyary, request.agyary_id)
        done = await funeral_answers.put_in_book(db, user, agyary, record, place, today=funeral_records.today_ist())
    await db.commit()
    return done
