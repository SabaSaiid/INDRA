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
    # The key for raw_reports.reporter_hash, an HMAC of the client's random
    # X-Reporter-Id. No default on purpose: a key in the source would let anyone
    # with the repo test candidate ids against a leaked hash. Empty means
    # reporter_hash stays NULL (services/ingest.py logs that once).
    REPORTER_SALT: str = ""

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

    # ── Object storage (layer 7, Phase 2 T1) ───────────────────────────────
    # SeaweedFS's S3 API in docker-compose.yml, spoken to with boto3, so any
    # S3-compatible store works by changing these values alone. Non-critical:
    # with the store down or unconfigured, reports are still accepted and
    # /healthz says degraded. Empty keys (or the .env.example placeholders)
    # mean "not configured", and nothing tries to connect.
    S3_ENDPOINT_URL: str = "http://localhost:8333"
    S3_REGION: str = "us-east-1"
    S3_ACCESS_KEY: str = ""
    S3_SECRET_KEY: str = ""
    S3_LAKE_BUCKET: str = "indra-lake"
    S3_MEDIA_BUCKET: str = "indra-media"
    S3_TIMEOUT_SECONDS: float = 5.0

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
    # ── Dedup gates ────────────────────────────────────────────────────────
    # Moved out of services/dedup.py on 20 Sep with their values unchanged, so
    # they can be tuned with evidence later instead of being edited in code.
    #
    # DEDUP_COSINE_THRESHOLD is deliberately strict. A report marked duplicate
    # is suppressed and never counts as corroboration, so dedup exists to catch
    # the same message sent again, not a second citizen describing the same
    # flood in their own words -- that is a witness. Measured 22 Sep with the
    # production model: resubmissions 0.91-0.99, independent witnesses
    # 0.81-0.91. 0.88 catches every resubmission measured and keeps most
    # witnesses; lowering it discards witnesses (BUG-013,
    # tests/test_dedup_corroboration.py pins both sides).
    DEDUP_COSINE_THRESHOLD: float = 0.88
    DEDUP_GPS_DELTA_KM: float = 1.0
    DEDUP_TIME_DELTA_MINUTES: int = 15
    DEDUP_LEVENSHTEIN_THRESHOLD: float = 0.75

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

    # ── Station poller (layer 1: the one scheduled external feed) ──────────
    # Every interval, Open-Meteo 24 h accumulated precipitation for the demo
    # cities is written to station_readings. Off means no task is started and the table
    # stays empty; the weather factor then fetches live per event, exactly as it
    # did before Day 6.
    STATION_POLLER_ENABLED: bool = True
    STATION_POLL_INTERVAL_SECONDS: int = 600

    # ── SACHET poller (layer 1: official agency warnings) ──────────────────
    # NDMA's national CAP feed — the only public route to IMD and CWC warnings
    # (IMD's own API requires an IP whitelist; CWC publishes none). Off means no
    # task is started and agency_alerts stays empty; nothing else changes,
    # because corroboration treats an absent alert as no evidence, not as a
    # contradiction.
    SACHET_POLLER_ENABLED: bool = True
    SACHET_RSS_URL: str = "https://sachet.ndma.gov.in/cap_public_website/rss/rss_india.xml"
    SACHET_CAP_URL: str = "https://sachet.ndma.gov.in/cap_public_website/FetchXMLFile"
    SACHET_TIMEOUT_SECONDS: float = 10.0
    # 5 min. The index is ETag-cached, so a tick with no new alerts is one
    # conditional request that returns 304 and parses nothing.
    SACHET_POLL_INTERVAL_SECONDS: int = 300
    # Cold start has ~99 alerts all new at once. Cap the burst; the remainder
    # arrives on the next tick rather than hammering a disaster agency's feed.
    # Lowered from 25/0.2s after the live feed began answering 403 to the
    # polygon endpoint partway through a cold start: NDMA throttles a client
    # that asks too fast, and a 235 KB polygon per alert is not a small ask.
    # 10 alerts a tick at 1 s spacing fills 99 alerts in ten ticks (~50 min)
    # without ever being refused.
    SACHET_MAX_FETCHES_PER_TICK: int = 10
    SACHET_FETCH_DELAY_SECONDS: float = 1.0
    # One live Gujarat district ring measured 235 KB. Past this the ring is
    # decimated and the row records that it was.
    SACHET_MAX_POLYGON_POINTS: int = 2000
    # How fresh and how near a stored reading must be for the weather factor to
    # prefer it over a live fetch.
    #
    # 180 minutes, not the 30 the day plan assumed. Age is measured on the end of
    # the reading's 24-hour accumulation window, and Open-Meteo publishes its
    # hourly buckets about two hours behind: measured live on 21 Sep, a poll made
    # at 19:50 UTC returned a series ending 18:00 UTC, a lag of 1 h 50 m. At 30
    # minutes every genuine reading would have been rejected and the stored path
    # would never once have been taken -- a feature that silently does nothing.
    #
    # Three hours is defensible on its own terms: the stored value answers "how
    # much rain fell here over the last day", and a window that closed two hours
    # ago still answers it. A reading older than that is stale enough that a
    # live fetch is worth the wait.
    STATION_READING_MAX_AGE_MINUTES: int = 180
    STATION_READING_MAX_DISTANCE_KM: float = 25.0

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

    # ── CORS ───────────────────────────────────────────────────────────────
    # Until 20 Sep this was allow_origins=["*"] in main.py, combined with
    # allow_credentials=True -- a pair the CORS spec forbids, and which Starlette
    # papers over by echoing whatever Origin it is sent. Any page on the internet
    # could therefore read this API with the user's credentials attached.
    #
    # Comma-separated in .env. The default is the dashboard's dev origins and
    # nothing else; a real deployment sets its own.
    CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"

    @property
    def cors_origins(self) -> list[str]:
        """CORS_ORIGINS split into a list, blanks dropped."""
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    model_config = {
        "env_file": (str(_REPO_ROOT / ".env"), str(_BACKEND_DIR / ".env")),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


@lru_cache()
def get_settings() -> Settings:
    return Settings()
