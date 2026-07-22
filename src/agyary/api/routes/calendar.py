from datetime import date

from fastapi import APIRouter, HTTPException, Query

from agyary.calendar import CalendarSystem, ParsiDate, gregorian_to_parsi

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


def _serialize(parsi_date: ParsiDate) -> dict:
    return {
        "calendar": parsi_date.calendar.value,
        "year": parsi_date.year,
        "gregorian_date": parsi_date.gregorian_date.isoformat(),
        "is_gatha": parsi_date.is_gatha,
        "mah": parsi_date.mah,
        "mah_name": parsi_date.mah_name,
        "roj": parsi_date.roj,
        "roj_name": parsi_date.roj_name,
        "gatha_index": parsi_date.gatha_index,
        "gatha_name": parsi_date.gatha_name,
        "display": str(parsi_date),
    }


@router.get("/today")
def today(system: CalendarSystem = Query(default=CalendarSystem.SHENSHAI)) -> dict:
    return _serialize(gregorian_to_parsi(date.today(), system))


@router.get("/convert")
def convert(
    date_: date = Query(alias="date"),
    system: CalendarSystem = Query(default=CalendarSystem.SHENSHAI),
) -> dict:
    try:
        return _serialize(gregorian_to_parsi(date_, system))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
