"""
INDRA Platform — Async Database Engine (SQLAlchemy 2.0 + PostGIS)
"""

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text
import logging

from app.core.config import get_settings

logger = logging.getLogger("indra.database")


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
    pass


settings = get_settings()

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=(settings.ENVIRONMENT == "development"),
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)

async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db():
    """FastAPI dependency — yields an async database session."""
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db() -> None:
    """Run on startup — verify PostGIS extension is available."""
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
            await conn.execute(text("SELECT PostGIS_Version()"))
        logger.info("✓ PostGIS extension verified and database connected.")
    except Exception as e:
        err_type = type(e).__name__
        err_msg = str(e).split('\n')[0].strip()
        if "ConnectionRefusedError" in str(e) or "Connect call failed" in str(e) or "Operation not permitted" in str(e):
            logger.warning(
                f"⚠ Database connection failed (non-fatal): PostgreSQL at {settings.POSTGRES_HOST}:{settings.POSTGRES_PORT} unreachable ({err_msg})"
            )
        else:
            logger.warning(f"⚠ Database connection failed (non-fatal): {err_type} - {err_msg}")
