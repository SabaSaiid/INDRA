"""
INDRA Platform — Query-parameter helpers shared by the filtered list routes

Moved out of api/events.py in Phase 2 (T10) when report search and the exports
needed the same rules: a comma-separated list is checked against its allowed
values before any query runs, so a typo is a 422 naming the parameter rather
than a database error reported as an outage (BUG-061); `from`/`to` take an IST
day or an ISO 8601 timestamp; `q` matches literally.
"""

from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Iterable, List, Optional, Tuple

from fastapi import HTTPException

# India Standard Time has no daylight saving, so a fixed offset is exact and
# needs no timezone database.
IST = timezone(timedelta(hours=5, minutes=30))
MAX_RANGE_DAYS = 366


def invalid(param: str, msg: str, value: Any) -> HTTPException:
    """A 422 in FastAPI's own shape, so a bad `event_type` reads like a bad `limit`."""
    return HTTPException(
        status_code=422,
        detail=[{"type": "value_error", "loc": ["query", param], "msg": msg, "input": value}],
    )


def csv_values(
    param: str,
    raw: Optional[str],
    allowed: Iterable[str],
    normalise: Callable[[str], str] = str.upper,
) -> Optional[List[str]]:
    """A comma-separated parameter as a list of known values, or None if absent."""
    if raw is None:
        return None
    allowed = set(allowed)
    values = [normalise(v.strip()) for v in raw.split(",") if v.strip()]
    unknown = [v for v in values if v not in allowed]
    if unknown or not values:
        raise invalid(
            param, f"unknown value {unknown[0] if unknown else raw!r}; expected any of {sorted(allowed)}", raw
        )
    return list(dict.fromkeys(values))


def instant(param: str, raw: Optional[str], end: bool) -> Optional[Tuple[datetime, bool]]:
    """
    `from` / `to` as (instant, exclusive).

    A date (YYYY-MM-DD) is a whole day in IST: `from` starts at its first
    instant, and `to` includes it, so the bound is the next day's midnight,
    exclusive. A 23:30 IST event is on the day an Indian operator would say it
    was, not the UTC one. A timestamp is used as given; one without an offset
    is read as IST.
    """
    if raw is None:
        return None
    try:
        if len(raw) == 10:
            d = date.fromisoformat(raw)
            midnight = datetime(d.year, d.month, d.day, tzinfo=IST)
            return (midnight + timedelta(days=1), True) if end else (midnight, False)
        ts = datetime.fromisoformat(raw)
        return (ts if ts.tzinfo else ts.replace(tzinfo=IST)), False
    except ValueError:
        raise invalid(param, "expected a date (YYYY-MM-DD) or an ISO 8601 timestamp", raw)


def like_pattern(q: str) -> str:
    """A contains-pattern for ILIKE in which % and _ match only themselves."""
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def date_range(date_from: Optional[str], date_to: Optional[str], param: str = "from"):
    """
    (start, stop) from `from` and `to`, checked: from before to, and no longer
    than MAX_RANGE_DAYS. Each is (instant, exclusive) or None.
    """
    start = instant("from", date_from, end=False)
    stop = instant("to", date_to, end=True)
    if start and stop:
        # stop[1]: a date's bound is exclusive, so from may not reach it; a
        # timestamp's is inclusive, so from may equal it.
        if start[0] > stop[0] or (stop[1] and start[0] >= stop[0]):
            raise invalid(param, "from is later than to", date_from)
        if stop[0] - start[0] > timedelta(days=MAX_RANGE_DAYS):
            raise invalid(param, f"the range is longer than {MAX_RANGE_DAYS} days", date_from)
    return start, stop

