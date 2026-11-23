"""SQLAlchemy ORM models.

Importing this package registers every model on Base.metadata, which both
Alembic autogeneration and metadata.create_all depend on.
"""

from agyary.models.agyary import Agyary
from agyary.models.app_notification import AppNotification
from agyary.models.app_setting import AppSetting
from agyary.models.booking import Booking, BookingMobed
from agyary.models.bulk_batch import BulkBatch
from agyary.models.ceremony_name import CeremonyName
from agyary.models.customer import AgyaryCustomer, Customer, CustomerSavedName, ReminderOptOut
from agyary.models.funeral_book import FuneralBehdin
from agyary.models.funeral_place import FuneralPlace, FuneralPlaceManager
from agyary.models.funeral_record import FuneralRecord, FuneralRequest, FuneralRequestBook, FuneralRequestRecipient
from agyary.models.login_otp import LoginOtp
from agyary.models.machi import Machi
from agyary.models.memorial import Memorial, MemorialObservance, MemorialObservanceService
from agyary.models.notification import Notification
from agyary.models.payment import Payment
from agyary.models.prayer_callout import AgyaryMobedContact, PrayerCallout, PrayerCalloutAnswer
from agyary.models.person_name import PersonName
from agyary.models.preferences import UserPreferences
from agyary.models.push_subscription import PushSubscription
from agyary.models.recurrence import RecurrenceRule
from agyary.models.service import Service
from agyary.models.user import AgyaryUser, DeletedAccount, User, UserSession
from agyary.models.wa_login import WaLoginAttempt

__all__ = [
    "Agyary",
    "AgyaryCustomer",
    "AgyaryMobedContact",
    "AgyaryUser",
    "DeletedAccount",
    "AppNotification",
    "AppSetting",
    "Booking",
    "BookingMobed",
    "BulkBatch",
    "CeremonyName",
    "Customer",
    "CustomerSavedName",
    "FuneralBehdin",
    "FuneralPlace",
    "FuneralPlaceManager",
    "FuneralRecord",
    "FuneralRequest",
    "FuneralRequestBook",
    "FuneralRequestRecipient",
    "LoginOtp",
    "Machi",
    "Memorial",
    "MemorialObservance",
    "MemorialObservanceService",
    "Notification",
    "Payment",
    "PersonName",
    "PrayerCallout",
    "PrayerCalloutAnswer",
    "PushSubscription",
    "RecurrenceRule",
    "ReminderOptOut",
    "Service",
    "User",
    "UserPreferences",
    "UserSession",
    "WaLoginAttempt",
]
