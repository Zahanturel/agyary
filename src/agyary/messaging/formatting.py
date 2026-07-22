"""Display helpers for chat messages and summaries."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from agyary.calendar import GATHA_NAMES, MAH_NAMES, ROJ_NAMES
from agyary.models.enums import GEH_NAMES

TITLE_DISPLAY = {
    "ervad": "Ervad",
    "behdin": "Behdin",
    "osta": "Osta",
    "osti": "Osti",
    "khud": "Khud",
}

PURPOSE_DISPLAY = {
    "patet": "Patet (for the departed)",
    "tandarosti": "Tandarosti (for the living)",
    "gujrela_nu": "Gujrela nu (for the departed)",
    "khushali_nu": "Khushali nu (for happiness)",
    "hama_anjuman": "Hama Anjuman (for the community)",
}

PURPOSE_SHORT = {
    "patet": "Patet",
    "tandarosti": "Tandarosti",
    "gujrela_nu": "Gujrela nu",
    "khushali_nu": "Khushali nu",
    "hama_anjuman": "Hama Anjuman",
}


def parsi_label(roj: int, mah: int) -> str:
    """"Roj Bahman, Mah Fravardin" - or the Gatha day name when mah == 13."""
    if mah == 13:
        gatha = GATHA_NAMES[roj - 1] if roj <= len(GATHA_NAMES) else f"Gatha {roj}"
        return f"Gatha {gatha}"
    return f"Roj {ROJ_NAMES[roj - 1]}, Mah {MAH_NAMES[mah - 1]}"


def gregorian_label(d: date) -> str:
    return d.strftime("%d %b %Y")


def date_label(roj: int, mah: int, gregorian: date) -> str:
    return f"{parsi_label(roj, mah)} ({gregorian_label(gregorian)})"


def geh_label(geh: int) -> str:
    return f"{GEH_NAMES[geh]} Geh"


def name_line(title: str, name: str) -> str:
    return f"{TITLE_DISPLAY.get(title, title.capitalize())} {name}"


def names_block(names: list[dict]) -> str:
    """Render state-data name dicts: pairs joined with commas, singles per line."""
    pair_names = [n for n in names if n["section"] == "pair"]
    farmayeshne = [n for n in names if n["section"] == "farmayeshne"]

    lines: list[str] = []
    grouped: dict[int | None, list[dict]] = {}
    for n in pair_names:
        grouped.setdefault(n.get("pair_group"), []).append(n)
    for group, members in grouped.items():
        if group is None:
            lines.extend(name_line(m["title"], m["name"]) for m in members)
        else:
            lines.append(", ".join(name_line(m["title"], m["name"]) for m in members))
    if farmayeshne:
        if lines:
            lines.append("")
        lines.append("Farmayeshne:")
        lines.extend(name_line(n["title"], n["name"]) for n in farmayeshne)
    return "\n".join(lines)


def rupees(amount: Decimal | float | int | str) -> str:
    value = Decimal(str(amount))
    if value == value.to_integral_value():
        return f"Rs. {value:.0f}"
    return f"Rs. {value:.2f}"
