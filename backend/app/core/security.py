"""
INDRA Platform — JWT Security & Role-Based Access Control
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
import bcrypt
from pydantic import BaseModel

from app.core.config import get_settings
from app.models.enums import OperatorRole

settings = get_settings()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)


# ── Roles ──────────────────────────────────────────────────────────────────────
# Derived from the enum so the two can't drift. FIELD_RESPONDER is a valid role
# with no demo user yet.
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


# Demo users for SIH prototype (in production this would be a DB table)
DEMO_USERS = {
    "admin": {
        "password_hash": hash_password("admin123"),
        "role": "ADMIN",
        "agency": "NDMA",
        "operator_id": "OP-ADMIN-001",
    },
    "commander": {
        "password_hash": hash_password("commander123"),
        "role": "COMMANDER",
        "agency": "SDMA_BIHAR",
        "operator_id": "OP-CMD-001",
    },
    "analyst": {
        "password_hash": hash_password("analyst123"),
        "role": "ANALYST",
        "agency": "IMD",
        "operator_id": "OP-ANL-001",
    },
    "citizen": {
        "password_hash": hash_password("citizen123"),
        "role": "CITIZEN",
        "agency": "PUBLIC",
        "operator_id": "OP-CIT-001",
    },
}


class TokenData(BaseModel):
    sub: str
    role: str
    agency: str


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
