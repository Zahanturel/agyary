"""Transport-agnostic messaging layer.

All booking logic, ceremony selection and name parsing live behind one
entry point::

    handle_message(db, agyary_id, phone_number, text) -> list[OutgoingMessage]

Transports are thin adapters around it:

- The web chat simulator POSTs the typed text (or a tapped option's id) and
  renders the returned messages.
- The future WhatsApp adapter resolves the webhook's phone_number_id to an
  agyary_id, passes button/list reply ids as ``text``, and converts each
  OutgoingMessage into a Cloud API send (buttons -> interactive button
  message, sections -> interactive list message, otherwise plain text).
"""

from agyary.messaging.handler import handle_message
from agyary.messaging.types import Button, ListRow, ListSection, OutgoingMessage

__all__ = ["Button", "ListRow", "ListSection", "OutgoingMessage", "handle_message"]
