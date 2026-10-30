"""Phone numbers do not reach the logs, whatever wrote them (LOG-01)."""

from __future__ import annotations

import io
import logging

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from agyary.api import main
from agyary.core.log_safety import MaskNumbers, mask_numbers

PHONE = "+919944400921"


def _logged(emit) -> str:
    """What a handler with the filter writes for one logging call."""
    out = io.StringIO()
    handler = logging.StreamHandler(out)
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    handler.addFilter(MaskNumbers())
    log = logging.getLogger("test.log_safety")
    log.addHandler(handler)
    log.propagate = False
    try:
        emit(log)
    finally:
        log.removeHandler(handler)
    return out.getvalue()


def test_a_number_is_masked_but_a_date_and_a_count_are_not():
    assert mask_numbers(f"failed for {PHONE} on 2026-10-30, 3 of 12") == "failed for [number] on 2026-10-30, 3 of 12"


def test_a_number_passed_as_a_logging_argument_is_masked():
    assert PHONE not in _logged(lambda log: log.error("Could not send to %s", PHONE))


async def test_a_real_unique_violation_keeps_its_traceback_and_loses_the_number(db):
    """What Postgres itself writes: DETAIL: Key (phone)=(+91...) already exists.
    hide_parameters cannot touch this; the filter must."""
    insert = "INSERT INTO users (name, phone) VALUES ('x', :p)"
    await db.execute(text(insert), {"p": PHONE})
    with pytest.raises(IntegrityError) as caught:
        await db.execute(text(insert), {"p": PHONE})
    await db.rollback()
    assert PHONE in str(caught.value), "the test needs the number to be there to begin with"

    def emit(log):
        try:
            raise caught.value
        except IntegrityError:
            log.exception("Saving failed")

    written = _logged(emit)
    assert "Saving failed" in written and "Traceback" in written and "already exists" in written
    assert PHONE not in written and "[number]" in written


def test_the_app_masks_what_it_logs():
    handlers = logging.getLogger("agyary").handlers
    assert handlers and all(any(isinstance(f, MaskNumbers) for f in h.filters) for h in handlers)
    assert main.MaskNumbers is MaskNumbers
