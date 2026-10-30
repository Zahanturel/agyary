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
from agyary.models.login_otp import LoginOtp
from agyary.models.machi import Machi
from agyary.models.memorial import Memorial, MemorialObservance, MemorialObservanceService
from agyary.models.notification import Notification
from agyary.models.payment import Payment
from agyary.models.preferences import UserPreferences
from agyary.models.recurrence import RecurrenceRule
from agyary.models.service import Service
from agyary.models.user import AgyaryUser, DeletedAccount, User, UserSession
from agyary.models.wa_login import WaLoginAttempt

__all__ = [
    "Agyary",
    "AgyaryCustomer",
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
    "LoginOtp",
    "Machi",
    "Memorial",
    "MemorialObservance",
    "MemorialObservanceService",
    "Notification",
    "Payment",
    "RecurrenceRule",
    "ReminderOptOut",
    "Service",
    "User",
    "UserPreferences",
    "UserSession",
    "WaLoginAttempt",
]
