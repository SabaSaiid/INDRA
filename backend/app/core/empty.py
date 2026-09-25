"""
INDRA Platform — what a read endpoint answers when it has no rows to serve

Every read endpoint used to fall through to hardcoded data whenever its query
returned no rows *or* raised, with nothing logged on the empty path. An empty
database therefore looked fully populated, and a broken query looked exactly
like a working one — which is how `GET /api/events/{id}` stayed broken from
the start without anyone noticing. The hardcoded datasets were removed on
25 Sep; there is nothing left to fall back to.

`empty_or_503()` is the one place that decides the answer instead:

| Why we got here | Returns                          | Log     |
|-----------------|----------------------------------|---------|
| no rows         | the real empty result (`[]`)     | WARNING |
| DB error        | HTTP 503 — never a fake success  | WARNING |
"""

import logging
from typing import Any, Callable, Optional

from fastapi import HTTPException

logger = logging.getLogger("indra.core.empty")


def empty_or_503(
    endpoint: str,
    empty: Callable[[], Any],
    error: Optional[Exception] = None,
) -> Any:
    """
    Decide what an endpoint returns when it has no real data to serve.

    `empty` is a callable so each endpoint builds its own empty shape. It may
    raise — a detail endpoint raises 404 — instead of returning a value.
    """
    if error is not None:
        logger.warning(f"{endpoint}: database error — returning 503: {error}")
        raise HTTPException(status_code=503, detail="Database unavailable")

    logger.warning(f"{endpoint}: no rows — returning empty result")
    return empty()
