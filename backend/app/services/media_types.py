"""
INDRA Platform — What an uploaded file really is (layers 2 and 3, Phase 5 T1)

A file's name and the MIME type a browser declares are both claims the sender
controls. The first bytes of the file are not: every image and video format
starts with a fixed signature. So an upload is identified by its **magic
bytes**, checked on part 1 the moment it arrives, and anything that is not one
of the formats below is refused with 415. A renamed `.exe` is stopped after its
first 5 MB, not after 50.

| Type        | Signature                                                            |
|-------------|----------------------------------------------------------------------|
| JPEG        | `FF D8 FF`                                                           |
| PNG         | `89 50 4E 47 0D 0A 1A 0A`                                            |
| WebP        | `RIFF` … `WEBP` (bytes 0–3 and 8–11)                                 |
| HEIC / HEIF | bytes 4–11: `ftypheic`, `ftypheix`, `ftypmif1`, `ftypmsf1`, `ftyphevc` |
| MP4 / MOV   | bytes 4–7 `ftyp`, with the brand `isom`, `mp42`, `avc1`, `qt  `, `3gp…` |

The limits are Phase 5's, and the citizen site checks the same numbers in the
browser first (webpage.MD §5.2):

    an image up to 10 MB · a video up to 50 MB and 60 seconds ·
    at most 4 files and 80 MB per report

Pure: no I/O. The upload route and the media worker both call it.
"""

from dataclasses import dataclass
from typing import Optional

# ── Limits ─────────────────────────────────────────────────────────────────────
# Decimal megabytes, as a phone's gallery shows them: "10 MB" is 10,000,000.
MAX_IMAGE_BYTES = 10_000_000
MAX_VIDEO_BYTES = 50_000_000
MAX_FILES_PER_REPORT = 4
MAX_BYTES_PER_REPORT = 80_000_000
MAX_VIDEO_SECONDS = 60.0

# Each part of a resumable upload is exactly this long, except the last
# (webpage.MD §8.3). 5 MiB is also S3's minimum multipart part size, so every
# part the phone sends becomes one UploadPart into the object store.
CHUNK_SIZE = 5 * 1024 * 1024

# How many leading bytes the sniffer needs to see.
SNIFF_BYTES = 16

IMAGE = "image"
VIDEO = "video"

_HEIF_BRANDS = {b"heic", b"heix", b"mif1", b"msf1", b"hevc"}
# ISO base-media brands a phone or camera writes for an MP4 or QuickTime file.
# "3gp" brands carry a digit (3gp4, 3gp5, 3gp6), so they match on the prefix.
_VIDEO_BRANDS = {b"isom", b"iso2", b"mp41", b"mp42", b"avc1", b"qt  ", b"M4V ", b"MSNV"}


@dataclass(frozen=True)
class Sniffed:
    kind: str       # "image" | "video"
    mime: str       # the real type, from the bytes
    ext: str        # the extension INDRA stores it under


def sniff(head: bytes) -> Optional[Sniffed]:
    """
    What the file is, from its first bytes, or None if it is not a photo or
    video INDRA accepts. At least SNIFF_BYTES are needed for the ISO formats.
    """
    if head.startswith(b"\xff\xd8\xff"):
        return Sniffed(IMAGE, "image/jpeg", "jpg")
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return Sniffed(IMAGE, "image/png", "png")
    if len(head) >= 12 and head[0:4] == b"RIFF" and head[8:12] == b"WEBP":
        return Sniffed(IMAGE, "image/webp", "webp")
    if len(head) >= 12 and head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in _HEIF_BRANDS:
            return Sniffed(IMAGE, "image/heic", "heic")
        if brand == b"qt  ":
            return Sniffed(VIDEO, "video/quicktime", "mov")
        if brand in _VIDEO_BRANDS or brand.startswith(b"3gp"):
            return Sniffed(VIDEO, "video/mp4", "mp4")
    return None


def declared_kind(mime: Optional[str]) -> Optional[str]:
    """"image" or "video" from a declared MIME type; None for anything else (415)."""
    major = (mime or "").split("/", 1)[0].strip().lower()
    return major if major in (IMAGE, VIDEO) else None


def max_bytes(kind: str) -> int:
    return MAX_VIDEO_BYTES if kind == VIDEO else MAX_IMAGE_BYTES


def parts_for(size_bytes: int) -> int:
    """How many CHUNK_SIZE parts a file of this size is sent in (at least 1)."""
    return max(1, -(-int(size_bytes) // CHUNK_SIZE))


def expected_part_size(n: int, size_bytes: int) -> int:
    """The exact length part n (1-based) must have: CHUNK_SIZE, or the remainder for the last."""
    total = parts_for(size_bytes)
    if n < total:
        return CHUNK_SIZE
    return int(size_bytes) - CHUNK_SIZE * (total - 1)


def mb(n_bytes: int) -> str:
    """10_000_000 → "10 MB", for messages a citizen reads."""
    return f"{n_bytes / 1_000_000:g} MB"
