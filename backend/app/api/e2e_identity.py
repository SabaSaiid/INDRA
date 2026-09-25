"""
INDRA Platform — E2E backend identity
GET /api/e2e/identity — the database and Kafka names this E2E backend uses

Mounted only when ENVIRONMENT=e2e (app/main.py); on any other backend the path
is a 404. The Playwright suite asks it before a single spec runs and refuses a
backend whose database does not end in _e2e, so a mistyped E2E_API_URL cannot
aim the suite's sign-ins, reviews and reports at the dev or live stack.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.empty import empty_or_503

settings = get_settings()

router = APIRouter(prefix="/api/e2e", tags=["E2E"])


@router.get("/identity")
async def e2e_identity(db: AsyncSession = Depends(get_db)):
    """
    The database is Postgres's answer to current_database(), not the name in
    DATABASE_URL: it is the one the server is really writing to.
    """
    try:
        database = (await db.execute(text("SELECT current_database()"))).scalar()
    except Exception as e:
        return empty_or_503("e2e identity", lambda: None, error=e)
    return {
        "environment": settings.ENVIRONMENT,
        "database": database,
        "reports_topic": settings.KAFKA_REPORTS_TOPIC,
        "consumer_group": settings.KAFKA_CONSUMER_GROUP,
    }
