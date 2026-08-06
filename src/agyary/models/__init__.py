"""SQLAlchemy ORM models.

Importing this package registers every model on Base.metadata, which both
Alembic autogeneration and metadata.create_all depend on.
"""

from agyary.models.agyary import Agyary
from agyary.models.auth import AuthOtp
from agyary.models.booking import Booking, BookingMobed
from agyary.models.bulk_batch import BulkBatch
from agyary.models.ceremony_name import CeremonyName
from agyary.models.conversation import ConversationState
from agyary.models.customer import AgyaryCustomer, Customer, CustomerSavedName
from agyary.models.invite import AgyaryInvite
from agyary.models.machi import Machi
from agyary.models.notification import Notification
from agyary.models.payment import Payment
from agyary.models.preferences import UserPreferences
from agyary.models.recurrence import RecurrenceRule
from agyary.models.service import Service
from agyary.models.user import AgyaryUser, User
from agyary.models.whatsapp import WhatsAppMessage

__all__ = [
    "Agyary",
    "AgyaryCustomer",
    "AgyaryInvite",
    "AgyaryUser",
    "AuthOtp",
    "Booking",
    "BookingMobed",
    "BulkBatch",
    "CeremonyName",
    "ConversationState",
    "Customer",
    "CustomerSavedName",
    "Machi",
    "Notification",
    "Payment",
    "RecurrenceRule",
    "Service",
    "User",
    "UserPreferences",
    "WhatsAppMessage",
]
