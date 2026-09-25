"""
BUG-009 — every endpoint that changes state requires a token.

Until 22 Sep only the review and provenance endpoints were guarded. Anyone
could create a team, dispatch one to an event, or rewrite any operator's
profile by naming them in `?user=`. The dashboard already fetches a JWT for
its selected persona, so the gate costs it a header.

The first test walks the app's routes rather than listing them, so a mutation
added later without a guard fails here instead of shipping open.
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.database import async_session
from tests.conftest import TEST_ACCOUNTS, wipe_event_tables
from tests.test_review_api import api, make_event, tokens  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}

# The only mutations that are anonymous on purpose: logging in, and a citizen
# filing a report — the whole point of the citizen channel is that it needs no
# account. Anything added to this set needs a reason next to it.
ANONYMOUS_BY_DESIGN = {
    ("POST", "/api/auth/token"),
    ("POST", "/api/reports/submit"),
}


def _mutating_routes():
    """
    Every (method, path) that changes state, read from the OpenAPI schema.

    Not from `app.routes`: FastAPI 0.141 wraps each included router in an
    `_IncludedRouter`, so walking the top-level routes finds none of the API.
    The schema lists every endpoint with its full prefix whatever the version.
    """
    from app.main import app

    for path, operations in app.openapi()["paths"].items():
        for method in sorted(operations):
            if method.upper() in MUTATING:
                yield method.upper(), path


def _concrete(path: str) -> str:
    """Fill every path parameter with a syntactically valid value."""
    import re

    return re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path)


def test_the_route_walk_finds_the_known_mutations():
    """Guard the guard: if the walk found nothing, the next test would pass vacuously."""
    found = set(_mutating_routes())
    assert ("PATCH", "/api/events/{event_id}/review") in found
    assert ("POST", "/api/teams") in found
    assert ("PATCH", "/api/teams/{team_id}/assign") in found
    assert ("PATCH", "/api/profile/me") in found
    assert ("POST", "/api/reports/official") in found


@pytest.mark.parametrize(
    "method,path",
    [pytest.param(m, p, id=f"{m} {p}") for m, p in _mutating_routes() if (m, p) not in ANONYMOUS_BY_DESIGN],
)
async def test_every_mutating_route_refuses_an_anonymous_caller(api, method, path):  # noqa: F811
    r = await api.request(method, _concrete(path), json={})

    assert r.status_code == 401, f"{method} {path} answered {r.status_code}: {r.text}"


# ── Teams ─────────────────────────────────────────────────────────────────────

TEAM = {
    "team_code": "TEST-SDRF-01",
    "name": "SDRF Test Unit",
    "agency": "sdrf",
    "city": "Patna",
    "state": "Bihar",
    "lead_name": "Test Lead",
    "members_count": 18,
}


@pytest_asyncio.fixture
async def clean_teams():
    async def wipe():
        async with async_session() as db:
            await db.execute(text("DELETE FROM teams WHERE team_code LIKE 'TEST-%'"))
            await db.commit()

    await wipe()
    yield
    await wipe()


@pytest.mark.parametrize("who, expected", [("citizen", 403), ("analyst", 403), ("commander", 201), ("admin", 201)])
async def test_creating_a_team_needs_a_commander_or_admin(api, tokens, clean_teams, who, expected):  # noqa: F811
    r = await api.post("/api/teams", json=TEAM, headers=tokens[who])

    assert r.status_code == expected, r.text


async def test_a_duplicate_team_code_is_409_not_500(api, tokens, clean_teams):  # noqa: F811
    assert (await api.post("/api/teams", json=TEAM, headers=tokens["commander"])).status_code == 201

    r = await api.post("/api/teams", json=TEAM, headers=tokens["commander"])

    assert r.status_code == 409
    assert "TEST-SDRF-01" in r.json()["detail"]


async def test_an_unknown_agency_is_422_not_a_database_error(api, tokens, clean_teams):  # noqa: F811
    r = await api.post("/api/teams", json={**TEAM, "agency": "SPACE_FORCE"}, headers=tokens["commander"])

    assert r.status_code == 422


async def test_a_team_without_a_size_is_422_not_twelve(api, tokens, clean_teams):  # noqa: F811
    """A missing members_count was stored as 12 responders nobody reported."""
    team = {k: v for k, v in TEAM.items() if k != "members_count"}

    r = await api.post("/api/teams", json=team, headers=tokens["commander"])

    assert r.status_code == 422


@pytest_asyncio.fixture
async def team_and_event(api, tokens, clean_teams):  # noqa: F811
    async with async_session() as db:
        await wipe_event_tables(db)
        event_id = await make_event(db)
    r = await api.post("/api/teams", json=TEAM, headers=tokens["commander"])
    assert r.status_code == 201
    yield r.json()["id"], event_id
    async with async_session() as db:
        await db.execute(text("DELETE FROM teams WHERE team_code LIKE 'TEST-%'"))
        await db.commit()
        await wipe_event_tables(db)


async def test_analyst_cannot_dispatch_a_team(api, tokens, team_and_event):  # noqa: F811
    team_id, event_id = team_and_event

    r = await api.patch(f"/api/teams/{team_id}/assign", json={"event_id": event_id}, headers=tokens["analyst"])

    assert r.status_code == 403


async def test_commander_dispatches_and_recalls_a_team(api, tokens, team_and_event):  # noqa: F811
    team_id, event_id = team_and_event

    r = await api.patch(f"/api/teams/{team_id}/assign", json={"event_id": event_id}, headers=tokens["commander"])
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "DEPLOYED"
    assert r.json()["assigned_by"] == "commander"

    async with async_session() as db:
        row = (
            await db.execute(
                text("SELECT status, assigned_event_id FROM teams WHERE id = CAST(:t AS uuid)"),
                {"t": team_id},
            )
        ).first()
    assert row[0] == "DEPLOYED"
    assert str(row[1]) == event_id

    r = await api.patch(f"/api/teams/{team_id}/assign", json={"event_id": None}, headers=tokens["commander"])
    assert r.status_code == 200
    assert r.json()["status"] == "AVAILABLE"


async def test_dispatching_a_team_that_does_not_exist_is_404(api, tokens, team_and_event):  # noqa: F811
    """It used to answer 200 'successfully dispatched'."""
    _, event_id = team_and_event

    r = await api.patch(f"/api/teams/{uuid.uuid4()}/assign", json={"event_id": event_id}, headers=tokens["commander"])

    assert r.status_code == 404
    assert r.json()["detail"] == "Team not found"


async def test_dispatching_to_an_event_that_does_not_exist_is_404(api, tokens, team_and_event):  # noqa: F811
    team_id, _ = team_and_event

    r = await api.patch(
        f"/api/teams/{team_id}/assign", json={"event_id": str(uuid.uuid4())}, headers=tokens["commander"]
    )

    assert r.status_code == 404
    assert r.json()["detail"] == "Event not found"


async def test_a_malformed_event_id_is_422(api, tokens, team_and_event):  # noqa: F811
    team_id, _ = team_and_event

    r = await api.patch(f"/api/teams/{team_id}/assign", json={"event_id": "not-a-uuid"}, headers=tokens["commander"])

    assert r.status_code == 422


# ── Profile ───────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def restore_profiles():
    async with async_session() as db:
        before = (
            await db.execute(text("SELECT username, callsign, duty_status FROM user_profiles"))
        ).all()
    yield
    async with async_session() as db:
        for username, callsign, duty in before:
            await db.execute(
                text(
                    "UPDATE user_profiles SET callsign = :c, duty_status = CAST(:d AS duty_status_enum) "
                    "WHERE username = :u"
                ),
                {"c": callsign, "d": duty, "u": username},
            )
        await db.commit()


async def _callsign(username: str) -> str:
    async with async_session() as db:
        return (
            await db.execute(text("SELECT callsign FROM user_profiles WHERE username = :u"), {"u": username})
        ).scalar()


async def test_a_token_edits_its_own_profile_and_ignores_user_param(api, tokens, restore_profiles):  # noqa: F811
    """`?user=admin` used to choose whose profile was written."""
    admin_before = await _callsign("admin")

    r = await api.patch("/api/profile/me?user=admin", json={"callsign": "TEST-CALL"}, headers=tokens["commander"])

    assert r.status_code == 200, r.text
    assert r.json()["username"] == "commander"
    assert await _callsign("commander") == "TEST-CALL"
    assert await _callsign("admin") == admin_before


async def test_duty_status_is_validated_and_case_insensitive(api, tokens, restore_profiles):  # noqa: F811
    bad = await api.patch("/api/profile/me", json={"duty_status": "ON_HOLIDAY"}, headers=tokens["analyst"])
    assert bad.status_code == 422

    ok = await api.patch("/api/profile/me", json={"duty_status": "standby"}, headers=tokens["analyst"])
    assert ok.status_code == 200
    assert ok.json()["duty_status"] == "STANDBY"


async def test_reading_a_profile_needs_a_token(api):  # noqa: F811
    """With no token /me used to answer with the commander's profile."""
    assert (await api.get("/api/profile/me")).status_code == 401
    assert (await api.get("/api/profile/me?user=commander")).status_code == 401
    assert (await api.get("/api/profile/me", headers={"Authorization": "Bearer not-a-jwt"})).status_code == 401


async def test_a_token_reads_its_own_profile(api, tokens):  # noqa: F811
    r = await api.get("/api/profile/me", headers=tokens["analyst"])

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["username"] == "analyst"
    assert body["operator_id"] == TEST_ACCOUNTS["analyst"][3]


async def test_activity_names_its_user(api):  # noqa: F811
    assert (await api.get("/api/profile/activity")).status_code == 422
    assert (await api.get("/api/profile/activity?user=analyst")).status_code == 200
    assert (await api.get("/api/profile/activity?user=nobody-here")).status_code == 404


async def test_there_is_no_server_side_preference_store(api, tokens):  # noqa: F811
    assert (await api.get("/api/profile/preferences")).status_code == 404
    assert (await api.patch("/api/profile/preferences", json={}, headers=tokens["citizen"])).status_code == 404
