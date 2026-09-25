"""
Guard: the suite must run against a local `indra_test`, never the dev database.

Integration fixtures truncate audit_logs, delete reports and events and
overwrite the accounts' password hashes. conftest.py therefore refuses, at
import and on every run, a database not named indra_test or indra_test_<suffix>,
one on another machine, and the one DATABASE_URL names. wipe_event_tables asks
Postgres which database it is on before it deletes anything.

If an import ever moves above the DATABASE_URL override in conftest.py, the
engine is built against the dev database; the first test fails first.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

from app.core.database import engine
from tests.conftest import TEST_DATABASE_NAME, TEST_DATABASE_URL, database_refusal, wipe_event_tables

BACKEND_DIR = Path(__file__).resolve().parents[1]

LOCAL = "postgresql+asyncpg://indra_user:indra_password@localhost:5433/"
DEV = LOCAL + "indra_db"


def test_engine_points_at_the_test_database():
    assert engine.url.database == make_url(TEST_DATABASE_URL).database
    assert TEST_DATABASE_NAME.match(engine.url.database)
    assert os.environ["DATABASE_URL"] == TEST_DATABASE_URL


@pytest.mark.parametrize(
    "test_url",
    [
        pytest.param(LOCAL + "indra_test", id="indra_test"),
        pytest.param(LOCAL + "indra_test_ci", id="indra_test_suffix"),
        pytest.param("postgresql+asyncpg://indra_user:indra_password@127.0.0.1:5433/indra_test", id="127.0.0.1"),
    ],
)
def test_a_local_test_database_is_accepted(test_url):
    assert database_refusal(test_url, DEV) == ""


@pytest.mark.parametrize(
    "test_url, reason",
    [
        pytest.param(DEV, "is not indra_test", id="indra_db"),
        pytest.param(LOCAL + "indra_prod", "is not indra_test", id="indra_prod"),
        pytest.param(LOCAL + "postgres", "is not indra_test", id="postgres"),
        pytest.param(LOCAL + "indra_testing", "is not indra_test", id="indra_testing"),
        pytest.param(LOCAL + "indra_test_", "is not indra_test", id="empty-suffix"),
        pytest.param(LOCAL + "indra_test_CI", "is not indra_test", id="uppercase-suffix"),
        pytest.param("postgresql+asyncpg://indra_user:x@13.232.10.20:5433/indra_test", "not this machine", id="remote"),
    ],
)
def test_anything_else_is_refused(test_url, reason):
    assert reason in database_refusal(test_url, DEV)


def test_a_remote_test_database_needs_the_explicit_opt_in():
    remote = "postgresql+asyncpg://indra_user:x@13.232.10.20:5433/indra_test"

    assert database_refusal(remote, DEV, allow_remote=True) == ""


@pytest.mark.parametrize(
    "dev_url",
    [
        pytest.param(LOCAL + "indra_test_dev", id="same-url"),
        pytest.param("postgresql://someone:else@127.0.0.1:5433/indra_test_dev", id="same-database-other-spelling"),
    ],
)
def test_the_database_the_backend_uses_is_refused_even_with_a_test_name(dev_url):
    assert "DATABASE_URL" in database_refusal(LOCAL + "indra_test_dev", dev_url)


def test_the_same_name_on_another_port_is_not_the_dev_database():
    assert database_refusal(LOCAL + "indra_test", "postgresql+asyncpg://u:p@localhost:5434/indra_test") == ""


def test_pytest_stops_before_collecting_anything_on_the_dev_database():
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--collect-only", "-p", "no:cacheprovider", "tests/test_test_database_guard.py"],
        cwd=BACKEND_DIR,
        env={**os.environ, "TEST_DATABASE_URL": "postgresql+asyncpg://indra_user:secret-pw@localhost:5433/indra_db"},
        capture_output=True,
        text=True,
        timeout=120,
    )

    out = r.stdout + r.stderr
    assert r.returncode != 0
    assert "refusing to run the suite against localhost:5433/indra_db" in out
    assert "secret-pw" not in out


class _Session:
    """A session on `database`, recording every statement it is sent."""

    def __init__(self, database):
        self.database = database
        self.sent = []

    async def execute(self, statement, params=None):
        self.sent.append(str(statement))
        database = self.database

        class _Result:
            def scalar(self):
                return database

        return _Result()

    async def commit(self):
        self.sent.append("COMMIT")


async def test_wiping_refuses_a_connection_that_is_not_on_a_test_database():
    session = _Session("indra_db")

    with pytest.raises(RuntimeError, match="refusing to touch 'indra_db'"):
        await wipe_event_tables(session)

    assert session.sent == ["SELECT current_database()"]


async def test_wiping_a_test_database_goes_ahead():
    session = _Session("indra_test")

    await wipe_event_tables(session)

    assert session.sent[0] == "SELECT current_database()"
    assert "TRUNCATE audit_logs" in session.sent
