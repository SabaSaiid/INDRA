"""
INDRA Platform — Recycled and relocated media (layers 3 and 6, Phase 5 T3)

The classic fake in Indian disaster reporting is an old flood photo or video
forwarded again. Each rule below is published, sets a flag on the media and on
its report, and lowers the report's credibility, which feeds the Report
Density factor through `n_eff` (services/corroboration.py). **Nothing is
rejected automatically:** the report stays stored and shown, and the reason
goes to the human who decides.

| flag                | rule                                                                    | credibility × |
|---------------------|-------------------------------------------------------------------------|---------------|
| `duplicate_media`   | the same SHA-256 as media on an earlier report from a different reporter | — the two reports count as **one witness** in n_eff |
| `recycled_suspect`  | a pHash (or any video frame) within Hamming distance 8 of media stored more than 48 h before this report, citizen or social | 0.3 |
| `old_capture`       | EXIF capture time more than 48 h before `observed_at`                   | 0.4 |
| `future_capture`    | EXIF capture time more than 1 h after the report was received            | 0.7 (a wrong camera clock is common) |
| `location_mismatch` | EXIF GPS more than 25 km from the report's GPS                          | 0.5 |
| `no_metadata`       | no EXIF at all                                                          | none: WhatsApp and most apps strip it, so its absence is not evidence |
| `edited`            | EXIF `Software` names an editing app                                    | none, noted only |

The multipliers live with every other flag's in `report_flags.FLAGS`, so one
table says what every flag costs. A report with two recycled photos is
flagged once and pays once.

Pure: the media worker gathers the earlier matches from the database and
passes them in; nothing here reads a clock or does I/O.
"""

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from app.services.media_extract import hamming

# The published thresholds.
RECYCLED_MAX_HAMMING = 8
RECYCLED_MIN_AGE = timedelta(hours=48)
OLD_CAPTURE_AGE = timedelta(hours=48)
FUTURE_CAPTURE_SLACK = timedelta(hours=1)
LOCATION_MISMATCH_KM = 25.0

MEDIA_FLAGS = (
    "duplicate_media",
    "recycled_suspect",
    "old_capture",
    "future_capture",
    "location_mismatch",
    "no_metadata",
    "edited",
)

# Editing and filter apps whose name in EXIF `Software` means the file was
# worked on after the camera. Phone firmware strings ("HDR+ 1.0", "iOS 17.1",
# "G998BXXU5DWA1") are not editors and do not match.
EDITOR_NAMES = (
    "photoshop", "lightroom", "gimp", "snapseed", "picsart", "canva", "pixlr", "affinity",
    "photopea", "vsco", "facetune", "meitu", "inshot", "capcut", "photodirector", "paint.net",
    "fotor", "polarr", "remini", "photoroom", "picmonkey", "photoscape", "luminar",
)

IST = timezone(timedelta(hours=5, minutes=30))


def _km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in km."""
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _day(ts: datetime) -> str:
    """"23 Sep 2026", in Indian time, as a nodal officer reads a date."""
    return ts.astimezone(IST).strftime("%-d %b %Y")


def span_words(delta: timedelta) -> str:
    """A duration as a person says it: "14 minutes", "5 hours", "3 days", "3 years"."""
    seconds = abs(delta.total_seconds())
    minutes, hours, days = seconds / 60, seconds / 3600, seconds / 86400
    if days >= 365:
        n, unit = int(days // 365), "year"
    elif days >= 60:
        n, unit = int(days // 30), "month"
    elif hours >= 48:
        n, unit = int(days), "day"
    elif minutes >= 120:
        n, unit = int(hours), "hour"
    else:
        n, unit = max(1, int(round(minutes))), "minute"
    return f"{n} {unit}{'' if n == 1 else 's'}"


def is_editor(software: Optional[str]) -> bool:
    name = (software or "").lower()
    return any(editor in name for editor in EDITOR_NAMES)


def _source_words(match: Mapping[str, Any]) -> str:
    if match.get("origin") == "social":
        return (match.get("platform") or "social media").replace("mastodon", "Mastodon")
    return "a citizen report"


def media_flags(
    media: Mapping[str, Any],
    report: Mapping[str, Any],
    *,
    same_file: Sequence[Mapping[str, Any]] = (),
    near: Sequence[Mapping[str, Any]] = (),
) -> Tuple[List[str], Dict[str, str]]:
    """
    The T3 flags for one photo or video, in MEDIA_FLAGS order, and why.

    media      what media_extract read: exif_taken_at, exif_lat, exif_lng,
               exif_software, has_metadata, phash, frame_phashes
    report     its report: observed_at, created_at, latitude, longitude,
               place_precision, reporter_hash, id
    same_file  earlier media with the same SHA-256, each with the
               report_id, reporter_hash and created_at of its report
    near       earlier media, each with `phash`, `frame_phashes`, `first_seen`
               (when INDRA first stored it), `origin` and `platform`; the
               48 h age test and the distance are applied here
    """
    basis: Dict[str, str] = {}
    received = report.get("created_at")
    observed = report.get("observed_at") or received

    # duplicate_media: the same file, from someone else.
    mine = report.get("reporter_hash")
    for other in same_file:
        if other.get("report_id") == report.get("id"):
            continue
        theirs = other.get("reporter_hash")
        if mine is not None and theirs == mine:
            continue  # the same device sending its own photo again is not a second witness either way
        when = other.get("created_at")
        basis["duplicate_media"] = (
            "the same file as media on another report from a different reporter"
            + (f", received {_day(when)}" if isinstance(when, datetime) else "")
        )
        break

    # recycled_suspect: near-identical to something stored more than 48 h before.
    if observed is not None:
        cutoff = observed - RECYCLED_MIN_AGE
        mine_hashes = [h for h in [media.get("phash"), *(media.get("frame_phashes") or [])] if h is not None]
        best: Optional[Tuple[int, datetime, Mapping[str, Any]]] = None
        for other in near:
            first_seen = other.get("first_seen")
            if not isinstance(first_seen, datetime) or first_seen >= cutoff:
                continue
            theirs = [h for h in [other.get("phash"), *(other.get("frame_phashes") or [])] if h is not None]
            distance = min((hamming(a, b) for a in mine_hashes for b in theirs), default=None)
            if distance is None or distance > RECYCLED_MAX_HAMMING:
                continue
            if best is None or first_seen < best[1]:
                best = (distance, first_seen, other)
        if best is not None:
            distance, first_seen, other = best
            basis["recycled_suspect"] = (
                f"near-identical to an image first seen on {_day(first_seen)} ({_source_words(other)}); "
                f"{distance} of 64 hash bits differ"
            )

    taken = media.get("exif_taken_at")
    if isinstance(taken, datetime) and observed is not None:
        if taken < observed - OLD_CAPTURE_AGE:
            basis["old_capture"] = (
                f"taken {_day(taken)}, {span_words(observed - taken)} before the report"
            )
        elif received is not None and taken > received + FUTURE_CAPTURE_SLACK:
            basis["future_capture"] = (
                f"the camera says {span_words(taken - received)} after the report was received; "
                "often a wrong camera clock"
            )

    lat, lng = media.get("exif_lat"), media.get("exif_lng")
    r_lat, r_lng = report.get("latitude"), report.get("longitude")
    if (
        lat is not None and lng is not None and r_lat is not None and r_lng is not None
        and (report.get("place_precision") or "gps") == "gps"
    ):
        km = _km(float(lat), float(lng), float(r_lat), float(r_lng))
        if km > LOCATION_MISMATCH_KM:
            basis["location_mismatch"] = f"photo taken {km:.0f} km from where the report was filed"

    if not media.get("has_metadata"):
        basis["no_metadata"] = "no EXIF; most messaging apps remove it, so this is not held against the report"
    elif is_editor(media.get("exif_software")):
        basis["edited"] = f"saved by {media.get('exif_software')}; noted only"

    flags = [f for f in MEDIA_FLAGS if f in basis]
    return flags, {f: basis[f] for f in flags}


# ── The receipt's media line ───────────────────────────────────────────────────

VISION_OFFLINE_TEXT = (
    "image content is not analysed; media is checked for reuse and metadata only"
)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def media_summary(items: Iterable[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    What the receipt says about an event's photos and videos, or None when it
    has none. Each item: kind, status, flags, flag_basis, exif_taken_at and its
    report's observed_at. For example:

        "2 photos checked: 1 captured 14 minutes before the report; no reuse found"
    """
    items = list(items)
    if not items:
        return None
    ready = [m for m in items if m.get("status") == "ready"]
    waiting = sum(1 for m in items if m.get("status") in ("uploading", "processing"))
    photos = sum(1 for m in ready if m.get("kind") == "image")
    videos = sum(1 for m in ready if m.get("kind") == "video")

    counts: Dict[str, int] = {}
    for m in ready:
        for flag in m.get("flags") or []:
            counts[flag] = counts.get(flag, 0) + 1

    what = " and ".join(
        part for part in (_plural(photos, "photo") if photos else "",
                          _plural(videos, "video") if videos else "") if part
    ) or "no media"
    notes: List[str] = []
    fresh = [
        m for m in ready
        if isinstance(m.get("exif_taken_at"), datetime) and isinstance(m.get("observed_at"), datetime)
        and not ({"old_capture", "future_capture"} & set(m.get("flags") or []))
    ]
    if len(fresh) == 1:
        m = fresh[0]
        delta = m["observed_at"] - m["exif_taken_at"]
        side = "before" if delta.total_seconds() >= 0 else "after"
        notes.append(f"1 captured {span_words(delta)} {side} the report")
    elif fresh:
        notes.append(f"{len(fresh)} captured within 48 hours of the report")

    reuse = []
    for flag in ("recycled_suspect", "duplicate_media", "old_capture", "location_mismatch"):
        if counts.get(flag):
            reasons = [
                (m.get("flag_basis") or {}).get(flag) for m in ready if flag in (m.get("flags") or [])
            ]
            reason = next((r for r in reasons if r), flag)
            reuse.append(f"{counts[flag]} {reason}" if counts[flag] > 1 else reason)
    notes.extend(reuse if reuse else ["no reuse found"])
    if waiting:
        notes.append(f"{waiting} still processing")

    return {
        "line": f"{what} checked: " + "; ".join(notes),
        "checked": len(ready),
        "photos": photos,
        "videos": videos,
        "processing": waiting,
        "flags": counts,
        "rule": "SHA-256 and perceptual-hash reuse, EXIF capture time and place (Phase 5 T3); "
                "content is not analysed",
    }
