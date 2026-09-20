"""
INDRA Platform — Core Configuration
Loads all environment variables via pydantic-settings.
"""

from pathlib import Path

from pydantic_settings import BaseSettings
from pydantic import field_validator
from functools import lru_cache

# `.env` lives at the repo root, but uvicorn is started from `backend/` (see
# start.sh), so a bare "env_file": ".env" resolved against the working directory
# and never found it — every value came from the defaults below. Anchor both
# locations to this file instead; a `backend/.env`, if present, wins.
_BACKEND_DIR = Path(__file__).resolve().parents[2]
_REPO_ROOT = _BACKEND_DIR.parent


class Settings(BaseSettings):
    """Central configuration sourced from .env / environment variables."""

    # ── General ────────────────────────────────────────────────────────────
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"

    # ── Backend API ────────────────────────────────────────────────────────
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000
    SECRET_KEY: str = "indra_super_secret_jwt_key_sih2026"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRY_HOURS: int = 8

    # ── PostgreSQL + PostGIS ───────────────────────────────────────────────
    POSTGRES_USER: str = "indra_user"
    POSTGRES_PASSWORD: str = "indra_password"
    POSTGRES_DB: str = "indra_db"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5433
    DATABASE_URL: str = "postgresql+asyncpg://indra_user:indra_password@localhost:5433/indra_db"

    @field_validator("DATABASE_URL", mode="after")
    @classmethod
    def normalize_database_url(cls, v: str) -> str:
        if v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+asyncpg://", 1)
        if v.startswith("postgresql://") and not v.startswith("postgresql+asyncpg://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v


    # ── Redis ──────────────────────────────────────────────────────────────
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_URL: str = "redis://localhost:6379/0"

    # ── Kafka / Redpanda ───────────────────────────────────────────────────
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:19092"
    KAFKA_REPORTS_TOPIC: str = "indra.raw.reports"
    KAFKA_EVENTS_TOPIC: str = "indra.verified.events"

    # ── AI & Verification Thresholds ───────────────────────────────────────
    # AUTO_PUBLISH_THRESHOLD is deliberately high: publishing a disaster without
    # a human in the loop is the most expensive mistake this system can make.
    #
    # HUMAN_REVIEW_THRESHOLD was lowered 0.70 -> 0.60 on 20 Sep. It is the gate
    # that decides whether an event reaches an operator at all, and at 0.70 a
    # genuinely corroborated cluster carrying an official dispatch scored ~0.62
    # and was binned as QUARANTINED without anyone seeing it. Under
    # coverage-aware scoring the reachable range for a real multi-source cluster
    # is roughly 0.54-0.70, so 0.70 sat above almost everything the system can
    # actually produce. The asymmetry is the argument: a quarantined real flood
    # is invisible, while an escalated weak signal costs an operator ten seconds.
    AUTO_PUBLISH_THRESHOLD: float = 0.90
    HUMAN_REVIEW_THRESHOLD: float = 0.60
    DBSCAN_EPS_KM: float = 5.0
    DBSCAN_MIN_SAMPLES: int = 2
    H3_HEX_RESOLUTION: int = 8
    TIME_WINDOW_MINUTES: int = 120

    # ── Coordinates ────────────────────────────────────────────────────────
    # False (the default) rejects out-of-India coordinates with a 422. True
    # restores the old behaviour of snapping them to a gazetteer match or the
    # (22, 82) national centroid — which lets junk reports cluster into a fake
    # event there, so only turn it on for a scripted demo that depends on it.
    SNAP_OUT_OF_BOUNDS_COORDINATES: bool = False

    # ── External signals ───────────────────────────────────────────────────
    OPEN_METEO_API_URL: str = "https://api.open-meteo.com/v1/forecast"
    WEATHER_TIMEOUT_SECONDS: float = 3.0

    # ── ML kill switches ───────────────────────────────────────────────────
    # Off means the model is treated as offline (receipt says so), never a crash.
    CLASSIFIER_ENABLED: bool = True

    # ── Demo data ──────────────────────────────────────────────────────────
    # When a read endpoint finds no rows (or the DB is unreachable), serve the
    # hardcoded demo dataset instead of an empty result. Logged at WARNING
    # either way, so demo data can never pass silently for real data.
    DEMO_MODE: bool = False

    # ── Frontend ───────────────────────────────────────────────────────────
    FRONTEND_PORT: int = 3000

    model_config = {
        "env_file": (str(_REPO_ROOT / ".env"), str(_BACKEND_DIR / ".env")),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


@lru_cache()
def get_settings() -> Settings:
    return Settings()
