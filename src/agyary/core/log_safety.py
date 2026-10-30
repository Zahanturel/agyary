"""Keeping phone numbers out of the logs (LOG-01).

hide_parameters (core/database.py) keeps SQLAlchemy's list of bound values out
of an error's text, but not what the driver or Postgres write themselves: a
unique violation's "Key (phone)=(+91...)", or asyncpg quoting a bad argument.
So what reaches a log is masked as a last step, tracebacks included.
"""

from __future__ import annotations

import logging
import re

# What a stored number looks like: E.164, no spaces. Long ids are caught too,
# which costs nothing in a log.
_NUMBER = re.compile(r"\+?\d{10,15}")


def mask_numbers(text: str) -> str:
    return _NUMBER.sub("[number]", text)


class MaskNumbers(logging.Filter):
    """For a handler, not a logger: a logger's filter does not see what its
    children send up. Not for uvicorn's access handler, whose formatter needs
    the record's args as they came."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg, record.args = mask_numbers(record.getMessage()), None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = mask_numbers(record.exc_text)
        return True
