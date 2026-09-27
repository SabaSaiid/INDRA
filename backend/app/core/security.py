"""
INDRA Platform — JWT Security & Role-Based Access Control
"""

import asyncio
import secrets
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
import bcrypt
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.enums import OperatorRole

settings = get_settings()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)


# ── Roles ──────────────────────────────────────────────────────────────────────
# Derived from the enum so the two can't drift. FIELD_RESPONDER is a valid role
# no account holds yet.
ROLES = {role.value for role in OperatorRole}


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"), hashed_password.encode("utf-8")
        )
    except Exception:
        return False


# ── Accounts ───────────────────────────────────────────────────────────────────
# Accounts are the rows of user_profiles; a password is a bcrypt hash in its
# password_hash column, set by scripts/set_operator_password.py. NULL means the
# account cannot sign in. Nothing here holds a password.

ACCOUNT_SQL = text(
    """
    SELECT username, CAST(role AS text) AS role, agency, operator_id, password_hash
    FROM user_profiles
    WHERE username = :username
    """
)


@lru_cache()
def _dummy_hash() -> str:
    """A hash no password matches, compared when there is no real one."""
    return hash_password(secrets.token_urlsafe(32))


def _check(password: str, stored: Optional[str]) -> bool:
    return verify_password(password, stored or _dummy_hash())


async def authenticate(db: AsyncSession, username: str, password: str) -> Optional[dict]:
    """
    The account these credentials sign in as, or None.

    An unknown user and an account with no password still pay for one bcrypt
    comparison, against a dummy hash, so the response time does not tell a
    caller which usernames exist. bcrypt runs in a thread: it is ~0.2 s of CPU
    that would otherwise stall every request on the event loop. A database
    error propagates; the caller answers 503.
    """
    row = (await db.execute(ACCOUNT_SQL, {"username": username})).mappings().first()
    stored = row["password_hash"] if row else None
    matches = await asyncio.to_thread(_check, password, stored)
    if not (row and stored and matches):
        return None
    return {
        "username": row["username"],
        "role": row["role"],
        "agency": row["agency"],
        "operator_id": row["operator_id"],
    }


class TokenData(BaseModel):
    sub: str
    role: str
    agency: str
    # user_profiles.operator_id, the id the audit ledger records. Empty in a
    # token issued before the claim existed.
    operator_id: str = ""


def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(hours=settings.JWT_EXPIRY_HOURS)
    )
    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc)})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def verify_token(token: str) -> TokenData:
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        return TokenData(
            sub=payload.get("sub", ""),
            role=payload.get("role", ""),
            agency=payload.get("agency", ""),
            operator_id=payload.get("operator_id", ""),
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_operator(
    token: Optional[str] = Depends(oauth2_scheme),
) -> TokenData:
    """FastAPI dependency — extracts and validates the JWT bearer token."""
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return verify_token(token)


def require_roles(*allowed_roles: str):
    """Returns a dependency that enforces role-based access."""

    async def _guard(
        operator: TokenData = Depends(get_current_operator),
    ) -> TokenData:
        if operator.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required: {allowed_roles}",
            )
        return operator

    return _guard
