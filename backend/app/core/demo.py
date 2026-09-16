"""
INDRA Platform — Demo-data fallback gate

Every read endpoint used to fall through to hardcoded demo data whenever its
query returned no rows *or* raised, with nothing logged on the empty path. An
empty database therefore looked fully populated, and a broken query looked
exactly like a working one — which is how `GET /api/events/{id}` stayed broken
from the start without anyone noticing.

`demo_fallback()` makes that a visible, deliberate choice:

| DEMO_MODE | Why we got here     | Returns                          | Log     |
|-----------|---------------------|----------------------------------|---------|
| true      | no rows / DB error  | the demo data                    | WARNING |
| false     | no rows             | the real empty result (`[]`)     | WARNING |
| false     | DB error            | HTTP 503 — never a fake success  | WARNING |
"""

import logging
from typing import Any, Callable, Optional, TypeVar

from fastapi import HTTPException

from app.core.config import get_settings

logger = logging.getLogger("indra.core.demo")

T = TypeVar("T")


def demo_fallback(
    endpoint: str,
    demo: Callable[[], T],
    empty: Callable[[], Any],
    error: Optional[Exception] = None,
) -> Any:
    """
    Decide what an endpoint returns when it has no real data to serve.

    `demo` and `empty` are callables so the (sometimes filtered) demo payload
    is only built when it is actually served. `empty` may raise — e.g. a detail
    endpoint raises 404 — instead of returning a value.
    """
    settings = get_settings()

    if settings.DEMO_MODE:
        reason = f"database error: {error}" if error is not None else "no rows"
        logger.warning(f"{endpoint}: serving demo data (DEMO_MODE=true, {reason})")
        return demo()

    if error is not None:
        logger.warning(f"{endpoint}: database error and DEMO_MODE=false — returning 503: {error}")
        raise HTTPException(status_code=503, detail="Database unavailable")

    logger.warning(f"{endpoint}: no rows (DEMO_MODE=false) — returning empty result")
    return empty()
