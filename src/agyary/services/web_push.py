"""Web push: a notification on a phone even when Mobed Diary is closed.

For every account that is on (DECISIONS D9, D10): an admin's "a new mobed is
waiting", and a mobed's "a Doongerwadi asks for prayers". Each person turns it
on per phone from Settings (an admin also from the admin screen); the browser
asks the person, and
hands us an address at its push service (Google's for Chrome on Android,
Apple's for an iPhone home-screen app, Mozilla's for Firefox) and two keys.
We sign each send with our VAPID key and encrypt it with the device's keys.

Never in the way: a push that fails is logged and the in-app notice is still
there. A device the push service says is gone (404, 410) is forgotten. Sends
go only to the push services' own hosts, so this cannot be pointed at an
address of someone's choosing.
"""

from __future__ import annotations

import asyncio
import json
import logging
from urllib.parse import urlparse

from pywebpush import WebPushException, webpush
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agyary.core.config import Settings
from agyary.models import PushSubscription

logger = logging.getLogger(__name__)

# The push services browsers use. Anything else is refused at subscribe time.
PUSH_HOSTS = (
    "fcm.googleapis.com",            # Chrome, Edge on Android, Brave, Samsung Internet
    "updates.push.services.mozilla.com",
    "web.push.apple.com",            # Safari, and home-screen apps on iPhone and iPad
    ".notify.windows.com",           # Edge on Windows
)
# A notification nobody saw for a day is out of date; the in-app notice stays.
TTL_SECONDS = 24 * 60 * 60
TIMEOUT_SECONDS = 8


def configured(settings: Settings) -> bool:
    return bool(settings.vapid_public_key.strip() and settings.vapid_private_key.strip())


def allowed_endpoint(endpoint: str) -> bool:
    url = urlparse(endpoint)
    host = (url.hostname or "").lower()
    return url.scheme == "https" and any(
        host == h or (h.startswith(".") and host.endswith(h)) for h in PUSH_HOSTS
    )


async def save(db: AsyncSession, user_id: int, endpoint: str, p256dh: str, auth: str) -> PushSubscription:
    """Remember this device for this user. A device that was someone else's
    (one phone, a new sign-in) now belongs to whoever subscribed it last."""
    sub = (await db.execute(select(PushSubscription).where(PushSubscription.endpoint == endpoint))).scalar_one_or_none()
    if sub is None:
        sub = PushSubscription(user_id=user_id, endpoint=endpoint, p256dh=p256dh, auth=auth)
        db.add(sub)
    else:
        sub.user_id, sub.p256dh, sub.auth = user_id, p256dh, auth
    await db.flush()
    return sub


async def remove(db: AsyncSession, user_id: int, endpoint: str) -> int:
    result = await db.execute(
        delete(PushSubscription).where(PushSubscription.user_id == user_id, PushSubscription.endpoint == endpoint)
    )
    return result.rowcount or 0


async def devices(db: AsyncSession, user_id: int) -> int:
    return (await db.execute(
        select(func.count()).select_from(PushSubscription).where(PushSubscription.user_id == user_id)
    )).scalar_one()


def _send_one(settings: Settings, sub: dict, payload: str) -> int | None:
    """Send to one device; None if it went, else the push service's status
    (0 when there was no answer). Runs in a thread: pywebpush is blocking."""
    try:
        webpush(
            subscription_info={"endpoint": sub["endpoint"], "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}},
            data=payload,
            vapid_private_key=settings.vapid_private_key.strip(),
            vapid_claims={"sub": settings.vapid_subject},
            ttl=TTL_SECONDS,
            timeout=TIMEOUT_SECONDS,
            headers={"Urgency": "high"},
        )
        return None
    except WebPushException as exc:
        return exc.response.status_code if exc.response is not None else 0
    except Exception:  # noqa: BLE001 - a push must never break what triggered it
        logger.exception("Web push could not be sent")
        return 0


async def send_to_users(
    db: AsyncSession, settings: Settings, user_ids, *, title: str, body: str, url: str, tag: str,
) -> int:
    """Notify every device of these users. Returns how many devices it reached.
    Never raises."""
    if not configured(settings):
        return 0
    try:
        subs = [
            {"id": s.id, "endpoint": s.endpoint, "p256dh": s.p256dh, "auth": s.auth}
            for s in (await db.execute(
                select(PushSubscription).where(PushSubscription.user_id.in_(list(user_ids)))
            )).scalars()
        ]
        if not subs:
            return 0
        payload = json.dumps({"title": title, "body": body, "url": url, "tag": tag})
        results = await asyncio.gather(*(asyncio.to_thread(_send_one, settings, s, payload) for s in subs))
        gone = [s["id"] for s, status in zip(subs, results) if status in (404, 410)]
        for s, status in zip(subs, results):
            if status is not None and status not in (404, 410):
                logger.warning("Web push to subscription %s failed: %s", s["id"], status or "no answer")
        if gone:
            await db.execute(delete(PushSubscription).where(PushSubscription.id.in_(gone)))
            logger.info("Forgot %d push subscription(s) the push service says are gone", len(gone))
        return sum(1 for status in results if status is None)
    except Exception:  # noqa: BLE001
        logger.exception("Web push failed")
        return 0
