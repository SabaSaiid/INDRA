"""
INDRA Platform — The verification clock (Phase 4 T4)

"Now", for everything that decides whether evidence counts:

* whether an official warning is **in force** (effective ≤ now ≤ expires);
* whether the SACHET feed is **fresh** enough for "no warning" to mean anything;
* where an event's **evidence window** ends (never in the future: an hour after
  now is a forecast, not an observation);
* which events are **open** for late corroboration, and whose review claims
  have **expired**.

    from app.services import clock
    clock.now()                      # an aware UTC datetime

Every one of those reads this function, never `datetime.now()` directly, for two
reasons. The tests pin it (`clock.frozen(...)`), so "a warning issued at 10:20
raises the 10:00 event" is a test with fixed times rather than one that depends
on when it runs. And Phase 6 replays a real day, which only works if the whole
verification path can be told what time it is.

Wall-clock stamps that record *when something was written* (`updated_at`, the
audit ledger's `logged_at`) are not decisions and keep using the database's or
the system's own time.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Callable, Iterator, Optional

_now: Optional[Callable[[], datetime]] = None


def _system_now() -> datetime:
    return datetime.now(timezone.utc)


def now() -> datetime:
    """The current time, aware and in UTC."""
    value = (_now or _system_now)()
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def set_clock(fn: Optional[Callable[[], datetime]]) -> None:
    """Replace the clock; None restores the system clock."""
    global _now
    _now = fn


def reset() -> None:
    set_clock(None)


@contextmanager
def frozen(at: datetime) -> Iterator[None]:
    """Inside the block, now() is `at`."""
    previous = _now
    set_clock(lambda: at)
    try:
        yield
    finally:
        set_clock(previous)
