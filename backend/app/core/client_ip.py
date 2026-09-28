"""
INDRA Platform — The real client address (layer 8a, Phase 5 T8)

Behind Caddy (and, later, cloudflared) every request reaches uvicorn from
127.0.0.1, so the peer address alone would put every citizen in one rate-limit
bucket. The proxies say who the client was, in `CF-Connecting-IP` (Cloudflare)
and `X-Forwarded-For` (Caddy). **Those headers are trusted only when the
request itself comes from the machine**: anyone can send them straight to port
8000, and a header from the internet must never choose its own bucket.

    CF-Connecting-IP   when the peer is loopback (cloudflared)
    X-Forwarded-For    its last entry, when the peer is loopback (the address
                       the proxy itself saw; earlier entries are the client's
                       own claims)
    the peer address   otherwise
"""

from typing import Optional

from fastapi import Request

TRUSTED_PROXIES = {"127.0.0.1", "::1", "localhost"}


def client_ip(request: Request) -> str:
    peer: Optional[str] = request.client.host if request.client else None
    if peer in TRUSTED_PROXIES:
        cf = (request.headers.get("cf-connecting-ip") or "").strip()
        if cf:
            return cf
        forwarded = [p.strip() for p in (request.headers.get("x-forwarded-for") or "").split(",") if p.strip()]
        if forwarded:
            return forwarded[-1]
    return peer or "unknown"
