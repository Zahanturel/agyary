"""Booking core, shared by whatever ends up talking to it.

This package started as the behdin-facing WhatsApp bot: conversation
flows, a text handler and a send worker. Those are gone. What is left is
the part that was never really about messaging at all - creating a
booking, holding a machi slot, working out which Gehs are free, and
formatting a Parsi date - and it is what the mobed app runs on.

The name is now a historical accident rather than a description. It stays
for the moment because renaming it touches every import in the app for no
behavioural gain; it is worth doing when something else brings us here.

- booking_service - create/update bookings, book_machi_slot, services
- availability     - which Gehs are free on a given Parsi day
- mobed_calendar   - a mobed's own calendar conflicts
- formatting       - Parsi date, Geh and name-block rendering
- geh_times        - Geh boundaries in IST
"""
