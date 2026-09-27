"""
INDRA Platform — the E2E backend's isolation guard

A backend started with ENVIRONMENT=e2e (./start.sh e2e-backend) serves the
Playwright suite, which signs in, reviews events and files reports. On the dev
database it would write those into real tables. On the dev report topic or
consumer group it would take real reports off the dev consumer, and the
pipeline skips a report whose row is not in its own database, so a live report
the E2E consumer received would never be verified.

So in e2e mode every one of those names must say e2e, or the app does not
start. Checked in app/main.py at import, before anything connects.
"""

import logging

from sqlalchemy.engine import make_url

logger = logging.getLogger("indra.core.e2e")

E2E_ENVIRONMENT = "e2e"
DATABASE_SUFFIX = "_e2e"
TOPIC_PREFIX = "indra.e2e."
GROUP_PREFIX = "indra-e2e-"
TOPIC_SETTINGS = ("KAFKA_REPORTS_TOPIC", "KAFKA_EVENTS_TOPIC", "KAFKA_DLQ_TOPIC")


def isolation_problems(settings) -> list[str]:
    """Why these settings are not an isolated E2E backend; empty when they are."""
    problems = []
    database = make_url(settings.DATABASE_URL).database or ""
    if not database.endswith(DATABASE_SUFFIX):
        problems.append(f"DATABASE_URL names {database!r}, not a database ending in {DATABASE_SUFFIX!r}")
    for name in TOPIC_SETTINGS:
        topic = getattr(settings, name)
        if not topic.startswith(TOPIC_PREFIX):
            problems.append(f"{name} is {topic!r}, not a topic starting {TOPIC_PREFIX!r}")
    if not settings.KAFKA_CONSUMER_GROUP.startswith(GROUP_PREFIX):
        problems.append(
            f"KAFKA_CONSUMER_GROUP is {settings.KAFKA_CONSUMER_GROUP!r}, not a group starting {GROUP_PREFIX!r}"
        )
    # The archiver's group and the lake bucket are not per-environment, so it
    # would write E2E messages into the real lake.
    if settings.LAKE_ARCHIVE_ENABLED:
        problems.append("LAKE_ARCHIVE_ENABLED is true; an E2E backend archives nothing")
    return problems


def assert_e2e_isolated(settings) -> None:
    """Raise RuntimeError if ENVIRONMENT is e2e and any name is not an E2E one."""
    if settings.ENVIRONMENT != E2E_ENVIRONMENT:
        return
    problems = isolation_problems(settings)
    if problems:
        message = "refusing to start an E2E backend: " + "; ".join(problems)
        logger.critical(message)
        raise RuntimeError(message)
