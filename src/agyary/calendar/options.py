"""Roj / Mah / Geh option lists for closed-vocabulary pickers.

These back the PWA's <select> dropdowns via /reference/calendar-options.
They live here, next to the names themselves, so there is one list and
never two independently-hardcoded copies drifting apart.

Closed vocabularies are tap-to-select, never free text - a Roj typed by
hand is a Roj spelled six ways.
"""

from __future__ import annotations

from agyary.calendar import MAH_NAMES, ROJ_NAMES
from agyary.models.enums import GEH_NAMES


def roj_options() -> list[dict]:
    return [{"id": f"roj_{i + 1}", "title": name} for i, name in enumerate(ROJ_NAMES)]


def mah_options() -> list[dict]:
    return [{"id": f"mah_{i + 1}", "title": name} for i, name in enumerate(MAH_NAMES)]


def geh_options() -> list[dict]:
    return [{"id": f"geh_{geh}", "title": name} for geh, name in GEH_NAMES.items()]
