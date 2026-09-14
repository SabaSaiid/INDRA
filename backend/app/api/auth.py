"""
INDRA Platform — Authentication API
POST /api/auth/token — OAuth2 password flow, returns JWT with role/agency claims
"""

from fastapi import APIRouter, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from fastapi import Depends

from app.core.security import (
    DEMO_USERS,
    verify_password,
    create_access_token,
)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.post("/token")
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
):
    """
    OAuth2 password flow.
    Authenticates against demo user store and returns a JWT (HS256, 8h expiry)
    with claims: { sub, role, agency, iat, exp }
    """
    user = DEMO_USERS.get(form_data.username)
    if not user or not verify_password(form_data.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(
        data={
            "sub": form_data.username,
            "role": user["role"],
            "agency": user["agency"],
        }
    )

    return {
        "access_token": token,
        "token_type": "bearer",
        "role": user["role"],
        "agency": user["agency"],
    }
