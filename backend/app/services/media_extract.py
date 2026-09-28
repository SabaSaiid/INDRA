"""
INDRA Platform — What a photo or video says about itself (layer 3, Phase 5 T2)

For every stored photo and video INDRA reads:

* **SHA-256** — the file's exact identity. Two identical files, however they
  were named or sent, have the same one.
* **A 64-bit perceptual hash (pHash)** — unlike SHA-256 it barely changes when
  a photo is resized, re-compressed or lightly cropped, which is what makes it
  useful for spotting an old photo sent again. Two hashes are compared by
  Hamming distance: the number of the 64 bits that differ.
* **EXIF** — the capture time (`DateTimeOriginal`, with `OffsetTimeOriginal`
  when the camera wrote one), the GPS position in decimal degrees, and the
  camera's `Make`, `Model` and `Software`.
* **For a video**, from `ffprobe`: the duration, the dimensions, the
  `creation_time`, and the GPS an iPhone keeps in
  `com.apple.quicktime.location.ISO6709` (Android writes `location`). `ffmpeg`
  extracts a frame at 1 s, 25%, 50% and 75% of the way through, and each gets
  a pHash, so a video that reuses an old clip is caught by any of its frames.

**This is metadata and deduplication, not vision.** Nothing here looks at what
an image shows; `vision_analysis` stays offline in every receipt.

Everything is synchronous and CPU- or process-bound: the media worker calls it
in a worker thread (`asyncio.to_thread`), never on the event loop.
"""

import hashlib
import json
import logging
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("indra.services.media_extract")

# A camera that writes no offset is read as Indian time: INDRA only accepts
# reports from inside India, and the basis says the offset was assumed.
ASSUMED_OFFSET = "+05:30"

# Frames a video is hashed at: 1 s in, then 25%, 50% and 75% of its length.
FRAME_FRACTIONS = (0.25, 0.50, 0.75)
FIRST_FRAME_S = 1.0

FFPROBE_TIMEOUT_S = 20
FFMPEG_TIMEOUT_S = 30

# EXIF tag numbers (the EXIF 2.32 standard).
_EXIF_IFD = 0x8769
_GPS_IFD = 0x8825
_TAG_MAKE = 271
_TAG_MODEL = 272
_TAG_SOFTWARE = 305
_TAG_DATETIME = 306
_TAG_DATETIME_ORIGINAL = 36867
_TAG_OFFSET_ORIGINAL = 36881
_GPS_LAT_REF, _GPS_LAT, _GPS_LNG_REF, _GPS_LNG = 1, 2, 3, 4

# A picture larger than this is refused as unreadable rather than decoded: a
# "decompression bomb" (a tiny file that expands to gigabytes) is a known way
# to exhaust a server's memory through an image library.
MAX_PIXELS = 100_000_000

_heif_registered = False


class UnreadableMedia(Exception):
    """The file could not be decoded. The report is kept; the media is marked unreadable."""


@dataclass
class Extracted:
    kind: str
    mime: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    duration_s: Optional[float] = None
    phash: Optional[int] = None
    frame_phashes: List[int] = field(default_factory=list)
    exif_taken_at: Optional[datetime] = None
    exif_offset: Optional[str] = None
    exif_offset_assumed: bool = False
    exif_lat: Optional[float] = None
    exif_lng: Optional[float] = None
    exif_make: Optional[str] = None
    exif_model: Optional[str] = None
    exif_software: Optional[str] = None
    # True when the file carries any EXIF (or, for a video, any creation or
    # location tag) at all: `no_metadata` is about its absence (T3).
    has_metadata: bool = False

    def as_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        if self.exif_taken_at is not None:
            out["exif_taken_at"] = self.exif_taken_at.isoformat()
        return out


# ── Hashes ─────────────────────────────────────────────────────────────────────

def sha256_file(path: str, chunk: int = 1024 * 1024) -> Tuple[str, int]:
    """(hex digest, size in bytes) of a file, read in chunks."""
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def to_signed64(value: int) -> int:
    """An unsigned 64-bit hash as the signed integer Postgres's bigint holds."""
    value &= (1 << 64) - 1
    return value - (1 << 64) if value >= (1 << 63) else value


def hamming(a: int, b: int) -> int:
    """How many of the 64 bits differ between two perceptual hashes."""
    return bin((int(a) ^ int(b)) & ((1 << 64) - 1)).count("1")


def phash_of(image) -> int:
    """The 64-bit perceptual hash of a Pillow image, as a signed int64."""
    import imagehash

    return to_signed64(int(str(imagehash.phash(image)), 16))


# ── Images ─────────────────────────────────────────────────────────────────────

def _register_heif() -> None:
    """Teach Pillow to open HEIC (iPhone photos), once. A missing plugin is logged, not fatal."""
    global _heif_registered
    if _heif_registered:
        return
    _heif_registered = True
    try:
        from pillow_heif import register_heif_opener

        register_heif_opener()
    except Exception as e:
        logger.warning(f"pillow-heif unavailable, HEIC photos will be unreadable: {e}")


def open_image(data: bytes):
    """A decoded Pillow image, or UnreadableMedia."""
    from PIL import Image

    _register_heif()
    try:
        image = Image.open(BytesIO(data))
        if image.width * image.height > MAX_PIXELS:
            raise UnreadableMedia(f"{image.width}×{image.height} pixels is more than accepted")
        image.load()
        return image
    except UnreadableMedia:
        raise
    except Exception as e:
        raise UnreadableMedia(f"{type(e).__name__}: {e}") from e


def _text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    text = str(value).strip("\x00 \t\r\n")
    return text or None


_OFFSET_RE = re.compile(r"^([+-])(\d{2}):?(\d{2})$")


def parse_exif_time(value: Any, offset: Any = None) -> Tuple[Optional[datetime], Optional[str], bool]:
    """
    (UTC time, offset as written or assumed, whether the offset was assumed)
    from EXIF's "YYYY:MM:DD HH:MM:SS" and "+HH:MM". A date the camera never set
    ("0000:00:00 00:00:00") is None.
    """
    raw = _text(value)
    if not raw:
        return None, None, False
    try:
        local = datetime.strptime(raw[:19], "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None, None, False
    written = _text(offset)
    match = _OFFSET_RE.match(written or "")
    assumed = match is None
    if assumed:
        match = _OFFSET_RE.match(ASSUMED_OFFSET)
    sign, hh, mm = match.groups()
    delta = timedelta(hours=int(hh), minutes=int(mm))
    tz = timezone(delta if sign == "+" else -delta)
    return local.replace(tzinfo=tz).astimezone(timezone.utc), f"{sign}{hh}:{mm}", assumed


def _rational(value: Any) -> float:
    try:
        return float(value)
    except TypeError:
        numerator, denominator = value
        return float(numerator) / float(denominator)


def gps_to_decimal(dms: Any, ref: Any) -> Optional[float]:
    """EXIF's (degrees, minutes, seconds) and N/S/E/W as signed decimal degrees."""
    try:
        degrees, minutes, seconds = (_rational(v) for v in dms)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    decimal = degrees + minutes / 60.0 + seconds / 3600.0
    if (_text(ref) or "").upper() in ("S", "W"):
        decimal = -decimal
    return round(decimal, 6)


def read_exif(image) -> Dict[str, Any]:
    """The EXIF fields T2 keeps; every one None when the photo has no EXIF."""
    out: Dict[str, Any] = {
        "exif_taken_at": None, "exif_offset": None, "exif_offset_assumed": False,
        "exif_lat": None, "exif_lng": None,
        "exif_make": None, "exif_model": None, "exif_software": None,
        "has_metadata": False,
    }
    try:
        exif = image.getexif()
    except Exception:
        return out
    if not exif:
        return out
    out["has_metadata"] = True
    out["exif_make"] = _text(exif.get(_TAG_MAKE))
    out["exif_model"] = _text(exif.get(_TAG_MODEL))
    out["exif_software"] = _text(exif.get(_TAG_SOFTWARE))

    try:
        sub = exif.get_ifd(_EXIF_IFD)
    except Exception:
        sub = {}
    taken = sub.get(_TAG_DATETIME_ORIGINAL) or exif.get(_TAG_DATETIME)
    when, offset, assumed = parse_exif_time(taken, sub.get(_TAG_OFFSET_ORIGINAL))
    out["exif_taken_at"], out["exif_offset"], out["exif_offset_assumed"] = when, offset, assumed

    try:
        gps = exif.get_ifd(_GPS_IFD)
    except Exception:
        gps = {}
    if gps and _GPS_LAT in gps and _GPS_LNG in gps:
        lat = gps_to_decimal(gps[_GPS_LAT], gps.get(_GPS_LAT_REF))
        lng = gps_to_decimal(gps[_GPS_LNG], gps.get(_GPS_LNG_REF))
        # (0, 0) is a phone that had no fix and wrote zeros, not a point in the sea.
        if lat is not None and lng is not None and not (lat == 0.0 and lng == 0.0):
            out["exif_lat"], out["exif_lng"] = lat, lng
    return out


def extract_image(data: bytes, mime: Optional[str] = None) -> Extracted:
    """Everything T2 reads from one photo. Raises UnreadableMedia for a corrupt file."""
    image = open_image(data)
    try:
        info = Extracted(kind="image", mime=mime, width=image.width, height=image.height)
        for k, v in read_exif(image).items():
            setattr(info, k, v)
        info.phash = phash_of(image)
        return info
    finally:
        image.close()


# ── Videos ─────────────────────────────────────────────────────────────────────

def ffmpeg_available() -> bool:
    """Both ffprobe and ffmpeg are installed (Phase 5 T0: `apt install ffmpeg`)."""
    return shutil.which("ffprobe") is not None and shutil.which("ffmpeg") is not None


_ISO6709_RE = re.compile(r"([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)")


def parse_iso6709(value: Optional[str]) -> Tuple[Optional[float], Optional[float]]:
    """"+25.6000+085.1000+050.000/" → (25.6, 85.1). None, None when unreadable."""
    match = _ISO6709_RE.search(value or "")
    if not match:
        return None, None
    lat, lng = float(match.group(1)), float(match.group(2))
    if not (-90 <= lat <= 90 and -180 <= lng <= 180) or (lat == 0.0 and lng == 0.0):
        return None, None
    return round(lat, 6), round(lng, 6)


def _parse_creation_time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    ts = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    # 1904-01-01 and 1970-01-01 are what an unset QuickTime or MP4 clock reads.
    if ts.year < 1990:
        return None
    return ts.astimezone(timezone.utc)


def probe_video(path: str) -> Dict[str, Any]:
    """ffprobe's answer for one video, as the fields T2 keeps. UnreadableMedia on failure."""
    try:
        done = subprocess.run(
            ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
            capture_output=True, timeout=FFPROBE_TIMEOUT_S, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise UnreadableMedia(f"ffprobe: {type(e).__name__}: {e}") from e
    if done.returncode != 0:
        raise UnreadableMedia(f"ffprobe: {done.stderr.decode('utf-8', 'replace')[:200]}")
    try:
        probe = json.loads(done.stdout.decode("utf-8"))
    except ValueError as e:
        raise UnreadableMedia(f"ffprobe gave no JSON: {e}") from e

    fmt = probe.get("format") or {}
    video = next((s for s in probe.get("streams") or [] if s.get("codec_type") == "video"), None)
    if video is None:
        raise UnreadableMedia("no video stream")

    tags: Dict[str, str] = {}
    for source in (fmt.get("tags") or {}, video.get("tags") or {}):
        for k, v in source.items():
            tags.setdefault(k.lower(), v)

    try:
        duration = float(fmt.get("duration") or video.get("duration"))
    except (TypeError, ValueError):
        duration = None

    lat, lng = parse_iso6709(
        tags.get("com.apple.quicktime.location.iso6709") or tags.get("location")
        or tags.get("location-eng")
    )
    created = _parse_creation_time(
        tags.get("com.apple.quicktime.creationdate") or tags.get("creation_time")
    )
    width, height = video.get("width"), video.get("height")
    # A phone that recorded upright stores a rotation instead of swapping the sides.
    rotation = (video.get("tags") or {}).get("rotate")
    for side in video.get("side_data_list") or []:
        rotation = side.get("rotation", rotation)
    try:
        if rotation is not None and abs(int(float(rotation))) % 180 == 90:
            width, height = height, width
    except (TypeError, ValueError):
        pass

    return {
        "duration_s": round(duration, 3) if duration is not None else None,
        "width": int(width) if width else None,
        "height": int(height) if height else None,
        "exif_taken_at": created,
        "exif_lat": lat,
        "exif_lng": lng,
        "exif_make": _text(tags.get("com.apple.quicktime.make") or tags.get("make")),
        "exif_model": _text(tags.get("com.apple.quicktime.model") or tags.get("model")),
        # The phone's own software tag only. A container's `encoder` (Lavf…) is
        # what muxed the file, not an editing app, and would flag every clip.
        "exif_software": _text(tags.get("com.apple.quicktime.software")),
        "has_metadata": created is not None or lat is not None,
        "format_name": fmt.get("format_name"),
    }


def frame_times(duration_s: Optional[float]) -> List[float]:
    """1 s, then 25%, 50% and 75% of the duration (a very short clip: its middle)."""
    if not duration_s or duration_s <= 0:
        return [0.0]
    first = min(FIRST_FRAME_S, duration_s / 2.0)
    return [round(first, 3)] + [round(duration_s * f, 3) for f in FRAME_FRACTIONS]


def grab_frame(path: str, at_s: float) -> bytes:
    """One frame as PNG bytes, from `at_s` seconds in."""
    try:
        done = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", f"{at_s:.3f}", "-i", path,
             "-frames:v", "1", "-f", "image2", "-vcodec", "png", "pipe:1"],
            capture_output=True, timeout=FFMPEG_TIMEOUT_S, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise UnreadableMedia(f"ffmpeg: {type(e).__name__}: {e}") from e
    if done.returncode != 0 or not done.stdout:
        raise UnreadableMedia(f"ffmpeg frame at {at_s}s: {done.stderr.decode('utf-8', 'replace')[:200]}")
    return done.stdout


def extract_video(path: str, mime: Optional[str] = None) -> Extracted:
    """Everything T2 reads from one video. Raises UnreadableMedia, as for a photo."""
    probed = probe_video(path)
    info = Extracted(kind="video", mime=mime)
    for k in ("duration_s", "width", "height", "exif_taken_at", "exif_lat", "exif_lng",
              "exif_make", "exif_model", "exif_software", "has_metadata"):
        setattr(info, k, probed.get(k))
    if info.exif_taken_at is not None:
        info.exif_offset = "+00:00"

    hashes: List[int] = []
    for at in frame_times(info.duration_s):
        try:
            frame = open_image(grab_frame(path, at))
        except UnreadableMedia as e:
            logger.info(f"Frame at {at}s not hashed: {e}")
            continue
        try:
            hashes.append(phash_of(frame))
        finally:
            frame.close()
    if not hashes:
        raise UnreadableMedia("no frame could be extracted")
    info.frame_phashes = hashes
    # The frame 1 s in stands for the video where one hash is compared.
    info.phash = hashes[0]
    return info
