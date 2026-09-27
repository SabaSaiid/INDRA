"""
T7 (Day 3) — the auth enforcement matrix for the two decision endpoints.

Reads stay open: this file also pins that GET /api/events answers 200 whatever
token (or none) is sent. Since 22 Sep every other mutation is guarded too —
teams, dispatch, profile, preferences — and `test_mutation_auth.py` walks the
routes to keep it that way (BUG-009).
"""

import uuid
from datetime import timedelta

import pytest
import pytest_asyncio
from jose import jwt

from app.core.security import ROLES, create_access_token
from app.models.enums import OperatorRole
from tests.conftest import TEST_ACCOUNTS, wipe_event_tables
from tests.test_review_api import api, make_event, tokens  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration

REVIEW_BODY = {"action": "approve", "reason": "Verified with SDRF field team by phone"}


@pytest_asyncio.fixture
async def event_id():
    from app.core.database import async_session

    async with async_session() as db:
        await wipe_event_tables(db)
        try:
            yield await make_event(db)
        finally:
            await db.rollback()
            await wipe_event_tables(db)


def _expired():
    _, role, agency, operator_id = TEST_ACCOUNTS["commander"]
    return create_access_token(
        {"sub": "commander", "role": role, "agency": agency, "operator_id": operator_id},
        expires_delta=timedelta(seconds=-1),
    )


def _wrong_key():
    return jwt.encode(
        {"sub": "admin", "role": "ADMIN", "agency": "NDMA"}, "not-the-secret", algorithm="HS256"
    )


def _headers(who, tokens):
    if who == "none":
        return {}
    if who == "expired":
        return {"Authorization": f"Bearer {_expired()}"}
    if who == "wrong_key":
        return {"Authorization": f"Bearer {_wrong_key()}"}
    return tokens[who]


def _call(api, endpoint, event_id, headers):
    if endpoint == "review":
        return api.patch(f"/api/events/{event_id}/review", json=REVIEW_BODY, headers=headers)
    if endpoint == "provenance":
        return api.get(f"/api/events/{event_id}/provenance", headers=headers)
    return api.get("/api/events", headers=headers)


MATRIX = {
    #              none  expired wrong_key citizen analyst commander admin
    "review":     (401,  401,    401,      403,    403,    200,      200),
    "provenance": (401,  401,    401,      403,    200,    200,      200),
    "list":       (200,  200,    200,      200,    200,    200,      200),
}
CALLERS = ("none", "expired", "wrong_key", "citizen", "analyst", "commander", "admin")

CASES = [
    pytest.param(endpoint, who, expected, id=f"{endpoint}-{who}")
    for endpoint, row in MATRIX.items()
    for who, expected in zip(CALLERS, row)
]


@pytest.mark.parametrize("endpoint,who,expected", CASES)
async def test_auth_matrix(api, tokens, event_id, endpoint, who, expected):  # noqa: F811
    r = await _call(api, endpoint, event_id, _headers(who, tokens))

    assert r.status_code == expected, r.text


@pytest.mark.parametrize("who", ["expired", "wrong_key"])
async def test_bad_tokens_say_why(api, tokens, event_id, who):  # noqa: F811
    r = await _call(api, "provenance", event_id, _headers(who, tokens))

    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid or expired token"


async def test_missing_token_on_unknown_event_is_still_401_not_404(api):  # noqa: F811
    """Auth runs before the lookup, so an anonymous caller can't probe for ids."""
    r = await api.get(f"/api/events/{uuid.uuid4()}/provenance")

    assert r.status_code == 401


def test_roles_match_the_operator_role_enum():
    assert set(ROLES) == {r.value for r in OperatorRole}
