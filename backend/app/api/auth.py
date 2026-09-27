"""
INDRA Platform — Authentication API
POST /api/auth/token — OAuth2 password flow, returns JWT with role/agency/operator_id claims
"""

import logging

from fastapi import APIRouter, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import authenticate, create_access_token

settings = get_settings()
logger = logging.getLogger("indra.api.auth")

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.post("/token")
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """
    OAuth2 password flow.
    Authenticates against user_profiles (bcrypt) and returns a JWT (HS256,
    JWT_EXPIRY_HOURS) with claims: { sub, role, agency, operator_id, iat, exp }.

    An unknown user, an account with no password set and a wrong password are
    the same 401, so the answer does not say which usernames exist. A database
    error is a 503: a login the platform could not check is not a wrong password.
    """
    try:
        account = await authenticate(db, form_data.username, form_data.password)
    except Exception as e:
        logger.warning(f"login lookup failed: {type(e).__name__}: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database unavailable",
        )
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(
        data={
            "sub": account["username"],
            "role": account["role"],
            "agency": account["agency"],
            "operator_id": account["operator_id"],
        }
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "role": account["role"],
        "agency": account["agency"],
        "operator_id": account["operator_id"],
        "username": account["username"],
        "expires_in": settings.JWT_EXPIRY_HOURS * 3600,
    }
