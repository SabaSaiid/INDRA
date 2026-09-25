"""
POST /api/auth/token checks user_profiles, not a dict in the source.

Until 25 Sep the four accounts and their plain-text passwords were a dict in
app/core/security.py. They now sign in against user_profiles.password_hash
(migration 0019), which scripts/set_operator_password.py sets per deployment.

The first half replaces the database with a fake session, so it runs without
Docker; the integration half signs in to indra_test with TEST_ACCOUNTS.
"""

import uuid

import bcrypt
import httpx
import pytest
import pytest_asyncio
from jose import jwt
from sqlalchemy import text

from app.core import security
from app.core.config import get_settings
from app.core.database import get_db
from tests.conftest import TEST_ACCOUNTS

PASSWORD = "a-test-only-password"
# Cost 4: the check is the same bcrypt comparison, just cheaper to run.
HASH = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()

ROWS = {
    "commander": {
        "username": "commander", "role": "COMMANDER", "agency": "SDMA_BIHAR",
        "operator_id": "OP-CMD-001", "password_hash": HASH,
    },
    "no-password": {
        "username": "no-password", "role": "ANALYST", "agency": "IMD",
        "operator_id": "OP-ANL-999", "password_hash": None,
    },
}


class _Result:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return self

    def first(self):
        return self._row


class AccountsSession:
    """user_profiles holding ROWS."""

    async def execute(self, statement, params=None):
        return _Result(ROWS.get((params or {}).get("username")))


class BrokenSession:
    async def execute(self, *args, **kwargs):
        raise RuntimeError("connection refused")


def _api_with(session_cls):
    @pytest_asyncio.fixture
    async def _fixture():
        from app.main import app

        async def _db():
            yield session_cls()

        app.dependency_overrides[get_db] = _db
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
                yield c
        finally:
            app.dependency_overrides.pop(get_db, None)

    return _fixture


accounts_api = _api_with(AccountsSession)
broken_api = _api_with(BrokenSession)


def _login(api, username, password):
    return api.post("/api/auth/token", data={"username": username, "password": password})


# ── Without a database ────────────────────────────────────────────────────────

async def test_the_right_password_signs_in_with_the_accounts_claims(accounts_api):
    r = await _login(accounts_api, "commander", PASSWORD)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["username"] == "commander"
    assert body["role"] == "COMMANDER"
    assert body["agency"] == "SDMA_BIHAR"
    assert body["operator_id"] == "OP-CMD-001"
    assert body["expires_in"] == get_settings().JWT_EXPIRY_HOURS * 3600

    settings = get_settings()
    claims = jwt.decode(body["access_token"], settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    assert {k: claims[k] for k in ("sub", "role", "agency", "operator_id")} == {
        "sub": "commander", "role": "COMMANDER", "agency": "SDMA_BIHAR", "operator_id": "OP-CMD-001",
    }
    assert "exp" in claims
    assert security.verify_token(body["access_token"]).operator_id == "OP-CMD-001"


@pytest.mark.parametrize(
    "username, password",
    [
        pytest.param("nobody", PASSWORD, id="unknown-user"),
        pytest.param("no-password", PASSWORD, id="null-hash"),
        pytest.param("commander", "not-the-password", id="wrong-password"),
    ],
)
async def test_every_refusal_is_the_same_401(accounts_api, username, password):
    r = await _login(accounts_api, username, password)

    assert r.status_code == 401
    assert r.json() == {"detail": "Incorrect username or password"}
    assert r.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("username", ["nobody", "no-password"])
async def test_an_account_that_cannot_sign_in_still_costs_one_bcrypt_check(accounts_api, monkeypatch, username):
    """Otherwise a fast 401 would tell a caller which usernames exist."""
    checked = []

    def record(plain, hashed):
        checked.append(hashed)
        return False

    monkeypatch.setattr(security, "verify_password", record)

    assert (await _login(accounts_api, username, PASSWORD)).status_code == 401
    assert len(checked) == 1
    assert checked[0].startswith("$2")


async def test_a_database_error_is_503_not_a_wrong_password(broken_api):
    r = await _login(broken_api, "commander", PASSWORD)

    assert r.status_code == 503
    assert r.json() == {"detail": "Database unavailable"}


def test_a_token_from_before_the_operator_id_claim_still_verifies():
    token = security.create_access_token({"sub": "commander", "role": "COMMANDER", "agency": "SDMA_BIHAR"})

    data = security.verify_token(token)

    assert data.sub == "commander"
    assert data.operator_id == ""


def test_no_password_or_account_is_defined_in_the_source():
    assert not hasattr(security, "DEMO_USERS")


# ── Against indra_test ────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db_api():
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.integration
@pytest.mark.parametrize("username", list(TEST_ACCOUNTS))
async def test_each_account_signs_in_as_its_user_profiles_row(db_api, accounts, username):
    password, role, agency, operator_id = accounts[username]

    r = await _login(db_api, username, password)

    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["username"], body["role"], body["agency"], body["operator_id"]) == (
        username, role, agency, operator_id,
    )


@pytest.mark.integration
async def test_a_wrong_password_is_401_against_the_database(db_api, accounts):
    r = await _login(db_api, "commander", accounts["analyst"][0])

    assert r.status_code == 401


@pytest.mark.integration
async def test_an_account_with_no_password_set_cannot_sign_in(db_api, accounts):
    from app.core.database import async_session

    username = f"test-{uuid.uuid4().hex[:8]}"
    async with async_session() as db:
        await db.execute(
            text(
                "INSERT INTO user_profiles (username, full_name, role, agency, operator_id) "
                "VALUES (:u, 'Test Account', 'ANALYST', 'IMD', :op)"
            ),
            {"u": username, "op": f"OP-{username}"},
        )
        await db.commit()
    try:
        r = await _login(db_api, username, "any-password-at-all")
        assert r.status_code == 401
    finally:
        async with async_session() as db:
            await db.execute(text("DELETE FROM user_profiles WHERE username = :u"), {"u": username})
            await db.commit()
