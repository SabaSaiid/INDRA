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
    # Phase 2 T8. A message the pipeline fails on PIPELINE_MAX_ATTEMPTS times
    # goes here, with its error, and the stream moves on past it.
    # scripts/replay_dlq.py sends them back once the cause is fixed.
    KAFKA_DLQ_TOPIC: str = "indra.raw.reports.dlq"
    PIPELINE_MAX_ATTEMPTS: int = 3
    PIPELINE_RETRY_DELAY_SECONDS: float = 2.0

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
    # The report stream's archive (Phase 2 T9): its own consumer group writes
    # every message to the lake, one object per LAKE_FLUSH_SECONDS or
    # LAKE_FLUSH_BYTES. Needs the store configured; off otherwise.
    LAKE_ARCHIVE_ENABLED: bool = True
    LAKE_FLUSH_SECONDS: int = 60
    LAKE_FLUSH_BYTES: int = 5 * 1024 * 1024

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

    # ── Posts and headlines (Phase 2 T7, T8) ───────────────────────────────
    # Their own dedup path; citizen dedup above is untouched. A post sharing an
    # article another post or headline already shared within the link window is
    # a re-share; the same text (cosine ≥ DEDUP_COSINE_THRESHOLD) about the same
    # place within the text window is a copy. Either is `duplicate_of` the first.
    FEED_DEDUP_LINK_WINDOW_HOURS: int = 72
    FEED_DEDUP_TEXT_WINDOW_HOURS: int = 24
    # On since Phase 3 T9: posts and headlines cluster within their hazard
    # family (a Delhi heatwave headline joins heat reports, never a flood), a
    # news publisher counts as one witness, and an event made only of posts is
    # capped at PENDING_HUMAN_REVIEW. False holds every post out of clustering.
    SOCIAL_CLUSTERING_ENABLED: bool = True

    DBSCAN_EPS_KM: float = 5.0
    DBSCAN_MIN_SAMPLES: int = 2
    H3_HEX_RESOLUTION: int = 8
    TIME_WINDOW_MINUTES: int = 120

    # ── External signals ───────────────────────────────────────────────────
    OPEN_METEO_API_URL: str = "https://api.open-meteo.com/v1/forecast"
    WEATHER_TIMEOUT_SECONDS: float = 3.0

    # ── Station poller (layer 1: the one scheduled external feed) ──────────
    # Every interval, Open-Meteo 24 h accumulated precipitation for the points in
    # workers/station_poller.STATIONS is written to station_readings. Off means
    # no task is started and the table stays empty; the weather factor then
    # fetches live per event, exactly as it did before Day 6.
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
    # ── METAR poller (layer 1, Phase 2 T3: airport weather observations) ───
    # AWC's bulk cache of every METAR in the world, filtered to India's
    # aerodromes. No key. Off by default like every Phase 2 poller: the team
    # server turns it on in /opt/indra/.env. The file is ~260 KB and AWC
    # rewrites it every minute or so; If-Modified-Since makes an unchanged
    # file a 304.
    METAR_POLLER_ENABLED: bool = False
    METAR_POLL_INTERVAL_SECONDS: int = 600
    METAR_CACHE_URL: str = "https://aviationweather.gov/data/cache/metars.cache.csv.gz"
    METAR_TIMEOUT_SECONDS: float = 30.0

    # ── Mastodon poller (layer 1, Phase 2 T4: #IMD and weather hashtags) ───
    # The PS asks for posts "tagged with #IMD and other relevant weather
    # hashtags". Mastodon's public tag timelines need no account and no key.
    # Comma-separated; hashtags are matched regardless of case. Off by default.
    MASTODON_POLLER_ENABLED: bool = False
    MASTODON_INSTANCES: str = "mastodon.social"
    SOCIAL_HASHTAGS: str = (
        "IMD,IMDWeather,IMDAlert,RainAlert,heatwave,monsoon,MumbaiRains,DelhiRains,"
        "KeralaRains,ChennaiRains,BengaluruRains,fog,cyclone,flood,duststorm,thunderstorm"
    )
    MASTODON_POLL_INTERVAL_SECONDS: int = 300
    # Between two requests to the same instance: 16 tags take ~16 s a tick.
    MASTODON_REQUEST_DELAY_SECONDS: float = 1.0
    MASTODON_TIMEOUT_SECONDS: float = 10.0
    # Below this many requests left in the instance's rate-limit window, the
    # rest of the tick is skipped for that instance.
    MASTODON_MIN_RATELIMIT_REMAINING: int = 20

    @property
    def mastodon_instances(self) -> list[str]:
        return [i.strip().lower() for i in self.MASTODON_INSTANCES.split(",") if i.strip()]

    @property
    def social_hashtags(self) -> list[str]:
        # Case-insensitively unique, order kept.
        seen, out = set(), []
        for tag in self.SOCIAL_HASHTAGS.split(","):
            tag = tag.strip().lstrip("#")
            if tag and tag.lower() not in seen:
                seen.add(tag.lower())
                out.append(tag)
        return out

    # ── Google News poller (layer 1, Phase 2 T5: weather headlines) ────────
    # The RSS search feed, no key. Headline, link and publisher only; never the
    # article. Queries are comma-separated, in English and in Hindi. Off by
    # default.
    NEWS_POLLER_ENABLED: bool = False
    NEWS_RSS_URL: str = "https://news.google.com/rss/search"
    NEWS_QUERIES_EN: str = (
        "IMD warning,IMD heavy rain,heatwave India,dense fog India,dust storm India,"
        "thunderstorm lightning India,cloudburst,cyclone IMD,flood India,cold wave India"
    )
    NEWS_QUERIES_HI: str = "भारी बारिश,लू,कोहरा,आंधी"
    NEWS_POLL_INTERVAL_SECONDS: int = 900
    NEWS_REQUEST_DELAY_SECONDS: float = 2.0
    NEWS_TIMEOUT_SECONDS: float = 15.0
    # An item already older than this when first seen is stored as stale and
    # never clustered: it describes a day that is over.
    NEWS_STALE_AFTER_HOURS: int = 48

    @property
    def news_queries(self) -> list[tuple[str, str]]:
        """(language, query) pairs, English first."""
        out = []
        for lang, raw in (("en", self.NEWS_QUERIES_EN), ("hi", self.NEWS_QUERIES_HI)):
            out.extend((lang, q.strip()) for q in raw.split(",") if q.strip())
        return out

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
