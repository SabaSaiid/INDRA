"""
INDRA Platform — Report intake

What turns an accepted report into a stored one. Every route and feed that
brings reports in calls `store_report()`, so they are all stored, analysed and
queued for the pipeline the same way.

**No report is lost between "stored" and "published" (BUG-060).** The report
row and its Kafka message — a row in `outbox` — are written in one
transaction, so either both exist or neither does. After the commit the
message is published straight away if the process's producer is up; if it is
not, or the publish fails, the row stays unpublished and the outbox relay
(`workers/outbox_relay.py`) publishes it later, however long the outage.
Before this, a report accepted while Redpanda was down was stored, answered
202, and never processed at all.
"""

import hashlib
import hmac
import json
import logging
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.services import kafka
from app.services.credibility import compute_credibility
from app.services.text_processing import clean_text, detect_language, extract_metadata

logger = logging.getLogger("indra.services.ingest")

# How long a request may spend publishing its own report before it gives up
# and leaves the message to the relay. The citizen is waiting on this.
REQUEST_PUBLISH_TIMEOUT_SECONDS = 2.0

_warned_no_salt = False

# ── Dockets ────────────────────────────────────────────────────────────────────
# What a citizen is given to follow their report: "R-" and 8 characters of
# Crockford base32, e.g. R-7K3M9QX2. The alphabet leaves out I, L, O and U, so
# nothing read aloud or copied off a phone screen can be mistaken for another
# character. Random, not a counter: 40 bits, so nobody can guess a docket or
# walk through other people's reports by counting.
DOCKET_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
DOCKET_LENGTH = 8
DOCKET_RE = re.compile(r"^R-[0-9A-HJKMNP-TV-Z]{8}$")
# Crockford's reading of the characters it leaves out.
_CONFUSABLE = str.maketrans({"O": "0", "I": "1", "L": "1"})
# A collision is one in about a trillion per pair, and the unique constraint
# catches it; a fresh docket on retry settles it.
_DOCKET_ATTEMPTS = 3


def new_docket() -> str:
    return "R-" + "".join(secrets.choice(DOCKET_ALPHABET) for _ in range(DOCKET_LENGTH))


def normalise_docket(raw: str) -> Optional[str]:
    """
    The docket a citizen meant, from what they typed; None if it cannot be one.

    Case, spaces and hyphens are ignored, the "R" is optional, and O, I and L
    are read as 0, 1 and 1 — the misreadings the alphabet was chosen to absorb.
    """
    s = "".join((raw or "").split()).upper()
    if s.startswith("R-"):
        body = s[2:].replace("-", "")
    else:
        # Without the hyphen the prefix is only recognisable by length, because
        # R is also a docket character: "R7K3M9QX2" is R + 7K3M9QX2, while
        # "R7K3M9QX" is itself an 8-character body.
        s = s.replace("-", "")
        body = s[1:] if len(s) == DOCKET_LENGTH + 1 and s.startswith("R") else s
    candidate = "R-" + body.translate(_CONFUSABLE)
    return candidate if DOCKET_RE.match(candidate) else None


# What GET /api/reports/track/{docket} says, derived only from stored state.
APPROVED_REVIEW_STATUSES = {"HUMAN_APPROVED", "AUTO_PUBLISHED"}


def docket_status(duplicate_of, event_id, review_status, processed_at) -> str:
    """
    received          stored; the pipeline has not finished with it yet
    duplicate         suppressed as a copy of an earlier report
    not_yet_an_event  processed, but alone: nothing corroborates it (yet)
    part_of_event     linked to an event that is still in review or quarantine
    event_approved    linked to an event published by a human or automatically
    event_rejected    linked to an event a commander rejected
    """
    if duplicate_of is not None:
        return "duplicate"
    if event_id is not None:
        if review_status in APPROVED_REVIEW_STATUSES:
            return "event_approved"
        if review_status == "REJECTED":
            return "event_rejected"
        return "part_of_event"
    if processed_at is not None:
        return "not_yet_an_event"
    return "received"


class StoreError(Exception):
    """The report could not be stored. Nothing was written and nothing published."""


@dataclass
class StoredReport:
    id: uuid.UUID
    docket: Optional[str]
    queued: bool     # published to Kafka before store_report() returned


def reporter_hash_for(client_id: Optional[str]) -> Optional[str]:
    """
    A stable pseudonym for one client: HMAC-SHA256 of its random id, keyed with
    REPORTER_SALT, as 64 hex characters.

    The same id always gives the same hash, which is what lets Phase 5 build a
    reputation per reporter; the id itself is never stored, so the database
    cannot be used to find a device. Keyed rather than a bare sha256, so that
    someone holding a leaked hash and the source code still cannot test
    candidate ids against it without the deployment's key.

    None for a missing or blank id — "we do not know who sent this", which must
    never become a shared identity — and None when no key is configured.
    """
    global _warned_no_salt

    if client_id is None or not client_id.strip():
        return None
    salt = get_settings().REPORTER_SALT
    if not salt:
        if not _warned_no_salt:
            logger.warning(
                "REPORTER_SALT is not set — reports are stored without a reporter "
                "pseudonym. Generate one with `openssl rand -hex 32`."
            )
            _warned_no_salt = True
        return None
    return hmac.new(salt.encode(), client_id.strip().encode(), hashlib.sha256).hexdigest()


def analyse(raw_text: str, report_id) -> Optional[dict]:
    """
    Layer-3 extraction for one report: cleaned text, language, depth, keywords.

    Rules and dictionaries only — no model. `raw_text` is never modified; this is
    stored alongside it in raw_reports.analysis.

    **Best-effort by design.** Any failure returns None so the caller stores the
    report with analysis NULL and still answers 202. Losing a disaster report
    because a regex raised would be a far worse bug than not knowing how deep the
    water was, so the whole thing is wrapped. Content severity re-extracts from
    raw_text at scoring time and therefore does not depend on this succeeding.
    """
    try:
        meta = extract_metadata(raw_text)
        return {
            "cleaned_text": clean_text(raw_text),
            "language": detect_language(raw_text),
            "depth_cm": meta["depth_cm"],
            "depth_basis": meta["depth_basis"],
            "keywords": meta["keywords"],
            "places": meta["places"],
            "url_count": meta["url_count"],
            "phone_count": meta["phone_count"],
            "extracted_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.warning(
            f"Analysis failed for report {report_id}, storing it without one: {e}"
        )
        return None


def _h3_cell(lat: float, lng: float) -> Optional[str]:
    try:
        import h3

        return h3.latlng_to_cell(lat, lng, get_settings().H3_HEX_RESOLUTION)
    except Exception:
        return None


# observed_at falls back to NOW(), which inside one statement is the same
# instant created_at defaults to — so an omitted observed_at is stored exactly
# equal to the time the report was received.
_INSERT_REPORT = text("""
    INSERT INTO raw_reports (id, source_type, raw_text, latitude, longitude, geom_point, h3_res8,
                             district, state, media_url, credibility_score, analysis, submitted_by,
                             observed_at, reporter_hash, citizen_hazard, docket,
                             platform, external_id, source_meta)
    VALUES (
        :id, :source_type, :raw_text, :lat, :lng,
        ST_SetSRID(ST_MakePoint(:lng, :lat), 4326),
        :h3_cell, :district, :state, :media_url, :credibility, CAST(:analysis AS jsonb), :submitted_by,
        COALESCE(CAST(:observed_at AS timestamptz), NOW()), :reporter_hash, :citizen_hazard, :docket,
        :platform, :external_id, CAST(:source_meta AS jsonb)
    )
""")

_INSERT_OUTBOX = text("""
    INSERT INTO outbox (topic, key, payload)
    VALUES (:topic, :key, CAST(:payload AS jsonb))
    RETURNING id
""")


def encode_message(payload: Dict[str, Any]) -> bytes:
    return json.dumps(payload).encode("utf-8")


async def store_report(
    db: AsyncSession,
    *,
    source_type: str,
    raw_text: str,
    latitude: float,
    longitude: float,
    district: Optional[str] = None,
    state: Optional[str] = None,
    media_url: Optional[str] = None,
    submitted_by: Optional[str] = None,
    observed_at: Optional[datetime] = None,
    reporter_hash: Optional[str] = None,
    citizen_hazard: Optional[str] = None,
    platform: Optional[str] = None,
    external_id: Optional[str] = None,
    source_meta: Optional[Dict[str, Any]] = None,
    issue_docket: bool = True,
) -> StoredReport:
    """
    Store one report and its outbox message in a single transaction, then try
    to publish the message at once. Raises StoreError if nothing could be
    stored; otherwise the report is safe whether or not the publish worked.

    Coordinates must already be validated: the caller decides what an
    unacceptable location means (the HTTP routes answer 422). A docket is
    issued unless the caller says otherwise — reports people submit get one;
    posts a feed collects have nobody to give it to.
    """
    report_id = uuid.uuid4()
    credibility = compute_credibility(source_type, raw_text)
    h3_cell = _h3_cell(latitude, longitude)
    analysis = analyse(raw_text, report_id)

    # The message is exactly what ingest has always published, and nothing
    # more: report_consumer broadcasts it verbatim to every connected browser as
    # NEW_REPORT, so the docket, the reporter hash and source_meta must never be
    # added to it. The pipeline re-reads the stored row by id for everything
    # else.
    payload = {
        "id": str(report_id),
        "source_type": source_type,
        "raw_text": raw_text,
        "latitude": latitude,
        "longitude": longitude,
        "h3_res8": h3_cell,
        "credibility_score": credibility,
        "media_url": media_url,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    topic = get_settings().KAFKA_REPORTS_TOPIC

    row = {
        "id": str(report_id),
        "source_type": source_type,
        "raw_text": raw_text,
        "lat": latitude,
        "lng": longitude,
        "h3_cell": h3_cell,
        "district": district,
        "state": state,
        "media_url": media_url,
        "credibility": credibility,
        "analysis": json.dumps(analysis) if analysis is not None else None,
        "submitted_by": submitted_by,
        "observed_at": observed_at,
        "reporter_hash": reporter_hash,
        "citizen_hazard": citizen_hazard,
        "platform": platform,
        "external_id": external_id,
        "source_meta": json.dumps(source_meta) if source_meta is not None else None,
    }

    for attempt in range(1, _DOCKET_ATTEMPTS + 1):
        docket = new_docket() if issue_docket else None
        try:
            outbox_id = await _insert(db, report_id, topic, payload, {**row, "docket": docket})
            break
        except IntegrityError as e:
            await _rollback_quietly(db)
            if docket and "uq_raw_reports_docket" in str(e) and attempt < _DOCKET_ATTEMPTS:
                logger.warning(f"Docket {docket} already taken; issuing another (attempt {attempt})")
                continue
            logger.error(f"Report {report_id} could not be stored: {type(e).__name__}: {e}")
            raise StoreError(str(e)) from e
        except Exception as e:
            await _rollback_quietly(db)
            logger.error(f"Report {report_id} could not be stored: {type(e).__name__}: {e}")
            raise StoreError(str(e)) from e

    queued = await publish_now(db, outbox_id, topic, str(report_id), payload)
    return StoredReport(id=report_id, docket=docket, queued=queued)


async def _insert(db, report_id, topic, payload, row) -> int:
    """The report and its message, committed together. Returns the outbox id."""
    await db.execute(_INSERT_REPORT, row)
    outbox_id = (await db.execute(_INSERT_OUTBOX, {
        "topic": topic,
        "key": str(report_id),
        "payload": json.dumps(payload),
    })).scalar_one()
    await db.commit()
    return outbox_id


async def _rollback_quietly(db) -> None:
    try:
        await db.rollback()
    except Exception:
        pass


async def publish_now(
    db: AsyncSession, outbox_id: int, topic: str, key: str, payload: Dict[str, Any]
) -> bool:
    """
    Publish one just-stored message, if the producer is up. True if it is now
    published; False leaves it to the relay. Never raises.

    The row is locked with SKIP LOCKED first, the same lock the relay takes, so
    the request and the relay never publish the same row: whichever gets the
    lock publishes, and the other moves on.
    """
    publisher = kafka.get_publisher()
    if not publisher.ready:
        return False

    try:
        row = (await db.execute(
            text("SELECT published_at FROM outbox WHERE id = :id FOR UPDATE SKIP LOCKED"),
            {"id": outbox_id},
        )).fetchone()
        if row is None or row[0] is not None:
            # Locked: the relay has it this instant. Published: the relay was
            # quicker. Either way it is not this request's to send.
            await db.rollback()
            return row is not None

        await publisher.publish(
            topic, encode_message(payload), key.encode("utf-8"),
            timeout=REQUEST_PUBLISH_TIMEOUT_SECONDS,
        )
        await db.execute(
            text("UPDATE outbox SET published_at = NOW() WHERE id = :id"),
            {"id": outbox_id},
        )
        await db.commit()
        return True
    except Exception as e:
        logger.warning(
            f"Outbox row {outbox_id} not published now; the relay will retry it: "
            f"{type(e).__name__}: {e}"
        )
        try:
            await db.rollback()
        except Exception:
            pass
        return False
