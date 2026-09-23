"""
INDRA Platform — Report intake

What turns an accepted report into a stored one. Shared by every route and feed
that brings reports in, so they are all stored the same way.
"""

import hashlib
import hmac
import logging
from typing import Optional

from app.core.config import get_settings

logger = logging.getLogger("indra.services.ingest")

_warned_no_salt = False


def reporter_hash_for(client_id: Optional[str]) -> Optional[str]:
    """
    A stable pseudonym for one client: HMAC-SHA256 of its random id, keyed with
    REPORTER_SALT, as 64 hex characters.

    The same id always gives the same hash, which is what lets Phase 5 build a
    reputation per reporter; the id itself is never stored, so the database
    cannot be used to find a device. Keyed rather than a bare sha256, so that
    someone holding a leaked hash and the source code still cannot test
    candidate ids against it without the deployment's key.

    None for a missing or blank id — "we do not know who sent this", which must
    never become a shared identity — and None when no key is configured.
    """
    global _warned_no_salt

    if client_id is None or not client_id.strip():
        return None
    salt = get_settings().REPORTER_SALT
    if not salt:
        if not _warned_no_salt:
            logger.warning(
                "REPORTER_SALT is not set — reports are stored without a reporter "
                "pseudonym. Generate one with `openssl rand -hex 32`."
            )
            _warned_no_salt = True
        return None
    return hmac.new(salt.encode(), client_id.strip().encode(), hashlib.sha256).hexdigest()
