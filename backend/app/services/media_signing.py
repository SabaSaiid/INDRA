"""
INDRA Platform — Short-lived media URLs (layer 8a, Phase 5 T5, webpage.MD §8.5)

The plan's first design was a 302 to an S3 presigned URL. That URL cannot be
opened by a browser: the object store listens on 127.0.0.1:8333 only. So the
API signs its own URLs and streams the bytes itself:

    sig = HMAC-SHA256(MEDIA_URL_SECRET, "{media_id}:{size}:{exp}")
    /api/media/{media_id}/file?size={size}&exp={exp}&sig={sig}

The URL carries no token, so it works in an `<img src>` or `<video src>`,
which cannot send an Authorization header; it is minted only by a signed-in
ANALYST, COMMANDER or ADMIN and expires after MEDIA_URL_TTL_SECONDS (10 min).
Signatures are compared with `hmac.compare_digest`, in constant time.

`size` is `thumb`, `full` or `original`. Only `original` reaches the file with
its EXIF and GPS, and minting one writes an audit row.
"""

import hashlib
import hmac
import time
from typing import Optional

from app.core.config import get_settings

SIZES = ("thumb", "full", "original")


class SigningUnavailable(Exception):
    """MEDIA_URL_SECRET is not set: no URL can be signed or checked."""


def _secret() -> bytes:
    secret = get_settings().MEDIA_URL_SECRET
    if not secret:
        raise SigningUnavailable("MEDIA_URL_SECRET is not set")
    return secret.encode("utf-8")


def signature(media_id: str, size: str, exp: int) -> str:
    return hmac.new(_secret(), f"{media_id}:{size}:{int(exp)}".encode("utf-8"), hashlib.sha256).hexdigest()


def sign_media_url(media_id: str, size: str, now: Optional[float] = None, ttl_s: Optional[int] = None) -> str:
    """A URL to one media file at one size, valid for ttl_s seconds (default MEDIA_URL_TTL_SECONDS)."""
    settings = get_settings()
    exp = int(now if now is not None else time.time()) + int(ttl_s or settings.MEDIA_URL_TTL_SECONDS)
    sig = signature(media_id, size, exp)
    base = settings.PUBLIC_API_BASE.rstrip("/")
    return f"{base}/api/media/{media_id}/file?size={size}&exp={exp}&sig={sig}"


def media_url_valid(media_id: str, size: str, exp: int, sig: str, now: Optional[float] = None) -> bool:
    """True for an unexpired URL this deployment signed. Never raises on a bad input."""
    if size not in SIZES:
        return False
    if int(exp) < (now if now is not None else time.time()):
        return False
    try:
        want = signature(media_id, size, exp)
    except SigningUnavailable:
        return False
    return hmac.compare_digest(want, str(sig or ""))
