"""
INDRA Platform — METAR poller (layer 1, Phase 2 T3: airport weather)

Every METAR_POLL_INTERVAL_SECONDS, fetch AWC's bulk cache of every METAR in the
world, keep India's aerodromes (ICAO prefixes VA, VE, VI, VO), and store one
`station_readings` row per observation:

    feed              metar
    agency            AERODROME_METAR   — not IMD; see migration 0016
    station_code      the ICAO id (VIDP, VABB, …)
    station_name      from data/geo/india_metar_stations.csv; the ICAO id when
                      the station is not in that table yet
    temperature_c, dewpoint_c, wind_kmh, gust_kmh, visibility_m,
    weather_codes, convective_cloud, raw_observation
    rainfall_mm       NULL — a METAR carries no rainfall amount
    recorded_at       the observation time, not the time of the poll

This is **observed** weather, which Open-Meteo is not: an IMD observer's
thermometer and visibility estimate at the airport, not a model's value for a
grid cell. Phase 4 corroborates heatwaves, fog, dust storms and thunderstorms
against it; this phase only collects, so there is a history to test against.

Why the bulk file and not the per-station API: AWC recommends the cache files
for many stations, it is one request for all of India, and `If-Modified-Since`
makes a tick with nothing new a 304 that parses nothing.

**Idempotent.** An observation is unique on (station, time) through a partial
unique index, and rows are inserted with ON CONFLICT DO NOTHING: the file keeps
each station's latest report for a while, so most rows in one tick were
already stored by the last.

Never takes the app down: every tick is wrapped, a failure is one WARNING and a
failed heartbeat, and the next tick retries. Single process only, like every
poller (BUG-011).
"""

import asyncio
import csv
import logging
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.config import get_settings
from app.models.enums import Agency
from app.models.station_readings import StationReading
from app.services.metar import Observation, indian_observations, read_cache_rows

logger = logging.getLogger("indra.workers.metar_poller")

FEED = "metar"
USER_AGENT = "INDRA-SIH2026/1.0 (Team Sixth Sense; disaster situational awareness)"

STATIONS_CSV = (
    Path(__file__).resolve().parents[3] / "data" / "geo" / "india_metar_stations.csv"
)

# The file's Last-Modified from the last successful fetch. Kept in the
# heartbeat's cursor too, so a restart can still send If-Modified-Since.
_last_modified: Optional[str] = None
# Why the last tick failed, or None; read by run_tick for the heartbeat.
last_tick_error: Optional[str] = None
# The observations the last tick stored (new rows only): what late
# corroboration (Phase 4 T5) looks through for a fog, a thunderstorm or a
# threshold worth re-scoring open events for.
last_stored: List[Dict[str, object]] = []


def _reset_for_tests() -> None:
    global _last_modified, last_tick_error, last_stored
    _last_modified = None
    last_tick_error = None
    last_stored = []


def _optional_float(value: Optional[str]) -> Optional[float]:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


@lru_cache(maxsize=1)
def station_table() -> Dict[str, Dict[str, object]]:
    """
    ICAO id → {name, lat, lon, elevation_m, iata, civil}. Empty (with an ERROR)
    if unreadable.

    `civil` is True for a station with an IATA code, i.e. a passenger airport,
    whose observers are IMD's aerodrome meteorological office. Phase 4's
    evidence line says "IMD" only for those: some Indian METAR stations are
    military airfields (services/evidence.py).
    """
    try:
        with STATIONS_CSV.open(newline="", encoding="utf-8") as handle:
            return {
                row["icao"]: {
                    "name": row["name"],
                    "lat": float(row["lat"]),
                    "lon": float(row["lon"]),
                    "elevation_m": _optional_float(row.get("elevation_m")),
                    "iata": (row.get("iata") or "").strip() or None,
                    "civil": bool((row.get("iata") or "").strip()),
                }
                for row in csv.DictReader(handle)
            }
    except (OSError, KeyError, ValueError) as e:
        logger.error(
            f"METAR station table unreadable at {STATIONS_CSV} ({e}); stations will be "
            "named by ICAO id. Rebuild it with scripts/build_metar_stations.py"
        )
        return {}


class FetchResult:
    """The outcome of one fetch: new content, unchanged (304), or failed."""

    def __init__(self, status: str, content: bytes = b"", last_modified: Optional[str] = None,
                 error: Optional[str] = None):
        self.status = status          # "ok" | "not_modified" | "failed"
        self.content = content
        self.last_modified = last_modified
        self.error = error


async def fetch_cache(client: httpx.AsyncClient, if_modified_since: Optional[str]) -> FetchResult:
    """The bulk cache file, or why not. Never raises."""
    settings = get_settings()
    headers = {"User-Agent": USER_AGENT}
    if if_modified_since:
        headers["If-Modified-Since"] = if_modified_since
    try:
        resp = await client.get(
            settings.METAR_CACHE_URL, headers=headers, timeout=settings.METAR_TIMEOUT_SECONDS
        )
    except Exception as e:
        return FetchResult("failed", error=f"METAR fetch failed: {type(e).__name__}: {e}")

    if resp.status_code == 304:
        return FetchResult("not_modified", last_modified=if_modified_since)
    if resp.status_code != 200:
        return FetchResult("failed", error=f"METAR cache returned HTTP {resp.status_code}")
    return FetchResult("ok", resp.content, resp.headers.get("Last-Modified") or None)


def _row_values(obs: Observation) -> Dict[str, object]:
    known = station_table().get(obs.station_code)
    # The table's position is the aerodrome reference point; the file's is the
    # same place to four decimals. Either will do; the table wins when present.
    lat = known["lat"] if known else obs.lat
    lng = known["lon"] if known else obs.lng
    return {
        "id": uuid.uuid4(),
        "station_code": obs.station_code,
        "station_name": (known["name"] if known else obs.station_code)[:120],
        "agency": Agency.AERODROME_METAR,
        "station_location": (
            f"SRID=4326;POINT({lng} {lat})" if lat is not None and lng is not None else None
        ),
        "rainfall_mm": None,
        "river_level_m": None,
        "anomaly_score": None,
        "recorded_at": obs.recorded_at,
        "feed": FEED,
        "temperature_c": obs.temperature_c,
        "dewpoint_c": obs.dewpoint_c,
        "wind_kmh": obs.wind_kmh,
        "gust_kmh": obs.gust_kmh,
        "visibility_m": obs.visibility_m,
        "weather_codes": obs.weather_codes,
        "convective_cloud": obs.convective_cloud,
        "raw_observation": obs.raw,
    }


async def store_observations(db, observations: List[Observation]) -> int:
    """
    Insert what is new; returns how many rows were written. Commits. The rows
    written are kept in `last_stored` for late corroboration.
    """
    global last_stored
    last_stored = []
    if not observations:
        return 0
    stmt = (
        pg_insert(StationReading)
        .values([_row_values(o) for o in observations])
        .on_conflict_do_nothing(
            index_elements=["station_code", "recorded_at"],
            index_where=text("feed = 'metar'"),
        )
        .returning(
            StationReading.station_code,
            StationReading.recorded_at,
            StationReading.weather_codes,
            StationReading.visibility_m,
            StationReading.gust_kmh,
            StationReading.wind_kmh,
            StationReading.temperature_c,
        )
    )
    rows = (await db.execute(stmt)).fetchall()
    await db.commit()
    last_stored = [
        {
            "station_code": r[0],
            "recorded_at": r[1],
            "weather_codes": list(r[2] or []),
            "visibility_m": r[3],
            "gust_kmh": r[4],
            "wind_kmh": r[5],
            "temperature_c": r[6],
        }
        for r in rows
    ]
    return len(rows)


def indian_rows_csv(content: bytes) -> bytes:
    """
    The cache file cut down to its header and India's rows, as CSV bytes: what
    the data lake keeps per tick (T9) rather than the whole world's 260 KB.
    """
    import gzip
    import io

    if content[:2] == b"\x1f\x8b":
        content = gzip.decompress(content)
    lines = content.decode("utf-8").splitlines(keepends=True)
    if not lines:
        return b""
    kept = [lines[0]]
    for line in lines[1:]:
        fields = next(csv.reader(io.StringIO(line)), [])
        if len(fields) > 1 and fields[1].strip().upper().startswith(("VA", "VE", "VI", "VO")):
            kept.append(line)
    return "".join(kept).encode("utf-8")


async def poll_once(db, client: Optional[httpx.AsyncClient] = None) -> Tuple[int, int]:
    """
    One tick: (rows_written, indian_observations_in_file).

    (0, 0) with no error is a 304: nothing changed since the last fetch.
    Sets `last_tick_error` when the tick failed as a whole.
    """
    global _last_modified, last_tick_error
    last_tick_error = None

    settings = get_settings()
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=settings.METAR_TIMEOUT_SECONDS)

    try:
        fetched = await fetch_cache(client, _last_modified)
        if fetched.status == "not_modified":
            logger.debug("METAR cache unchanged (304)")
            return 0, 0
        if fetched.status == "failed":
            last_tick_error = fetched.error
            logger.warning(fetched.error)
            return 0, 0

        try:
            rows = read_cache_rows(fetched.content)
        except ValueError as e:
            # Last-Modified is not remembered, so the next tick fetches it again
            # instead of being told 304 about a file that never parsed.
            last_tick_error = f"METAR cache unreadable: {e}"
            logger.warning(last_tick_error)
            return 0, 0

        observations = indian_observations(rows)
        written = await store_observations(db, observations)
        _last_modified = fetched.last_modified

        # The lake keeps India's rows as fetched, not the world's 260 KB (T9).
        # Never raises; the readings are already stored either way.
        from app.services import lake

        await lake.put_raw(
            FEED, indian_rows_csv(fetched.content), "text/csv",
            metadata={"stations": len(observations), "last_modified": fetched.last_modified},
        )
        return written, len(observations)
    except Exception as e:
        try:
            await db.rollback()
        except Exception:
            pass
        last_tick_error = f"METAR poll tick failed: {type(e).__name__}: {e}"
        logger.warning(last_tick_error)
        return 0, 0
    finally:
        if own_client:
            await client.aclose()


async def run_tick(session_factory=None) -> Tuple[int, int]:
    """One scheduled tick: poll, then record the heartbeat. Returns poll_once's result."""
    global _last_modified
    from app.services.feed_status import get_cursor, record_tick

    if session_factory is None:
        from app.core.database import async_session as session_factory

    if _last_modified is None:
        # After a restart, resume from the heartbeat's cursor.
        _last_modified = (await get_cursor(FEED)).get("last_modified")

    try:
        async with session_factory() as db:
            written, seen = await poll_once(db)
    except Exception as e:
        await record_tick(FEED, ok=False, error=f"{type(e).__name__}: {e}")
        raise

    if last_tick_error is None and seen:
        logger.info(f"METAR poll stored {written} new observations ({seen} Indian in file)")
    await record_tick(
        FEED,
        ok=last_tick_error is None,
        items=written,
        error=last_tick_error,
        cursor={"last_modified": _last_modified} if _last_modified else None,
    )

    # Phase 4 T5: an airport reporting fog, a thunderstorm, dust, a squall,
    # heavy rain or a threshold after an event was scored re-scores the open
    # events within 50 km. Never raises.
    if get_settings().LATE_CORROBORATION_ENABLED:
        from app.services import late_corroboration

        triggers = late_corroboration.metar_triggers(last_stored if written else [])
        if triggers or late_corroboration.pending():
            await late_corroboration.rescore_open_events(triggers, session_factory)
    return written, seen


async def start_metar_poller() -> None:
    """The lifespan task. Polls at once, then every interval."""
    settings = get_settings()
    if not settings.METAR_POLLER_ENABLED:
        logger.info("METAR poller disabled (METAR_POLLER_ENABLED=false)")
        return

    from app.core.database import async_session

    logger.info(
        f"✓ METAR poller started — Indian aerodromes from AWC every "
        f"{settings.METAR_POLL_INTERVAL_SECONDS}s"
    )
    while True:
        try:
            await run_tick(async_session)
        except asyncio.CancelledError:
            logger.info("METAR poller shutting down...")
            raise
        except Exception as e:
            logger.warning(f"METAR poll failed (non-fatal): {type(e).__name__}: {e}")

        try:
            await asyncio.sleep(settings.METAR_POLL_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            logger.info("METAR poller shutting down...")
            raise
