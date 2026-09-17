"""
Guard: the suite must run against `indra_test`, never the dev database.

If an import ever moves above the DATABASE_URL override in conftest.py, the
engine is built against `indra_db` and every integration fixture would wipe
the dev data. This test fails first.
"""

from app.core.database import engine


def test_engine_points_at_the_test_database():
    assert engine.url.database == "indra_test"
