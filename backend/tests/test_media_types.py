"""
Phase 5 T1 — what an uploaded file really is, and how big it may be
(`app/services/media_types.py`).

The type comes from the file's first bytes, never its name or declared type:
T1's signature table row for row, plus the limits and the 5 MiB part
arithmetic the resumable upload (webpage.MD §8.3, B6) is built on. The upload
routes themselves are tested in test_media_upload.py.
"""

import pytest

from app.services.media_types import (
    CHUNK_SIZE,
    MAX_BYTES_PER_REPORT,
    MAX_FILES_PER_REPORT,
    MAX_IMAGE_BYTES,
    MAX_VIDEO_BYTES,
    MAX_VIDEO_SECONDS,
    declared_kind,
    expected_part_size,
    max_bytes,
    mb,
    parts_for,
    sniff,
)
from tests.media_support import encode, scene


def _iso(brand: bytes) -> bytes:
    """The first 16 bytes of an ISO base-media file: a box size, `ftyp`, the brand."""
    return b"\x00\x00\x00\x18ftyp" + brand + b"\x00\x00\x00\x00"


# ── T1's signature table ───────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "head, kind, mime, ext",
    [
        (b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01", "image", "image/jpeg", "jpg"),
        (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR", "image", "image/png", "png"),
        (b"RIFF\x24\x00\x00\x00WEBPVP8 ", "image", "image/webp", "webp"),
        (_iso(b"heic"), "image", "image/heic", "heic"),
        (_iso(b"heix"), "image", "image/heic", "heic"),
        (_iso(b"mif1"), "image", "image/heic", "heic"),
        (_iso(b"msf1"), "image", "image/heic", "heic"),
        (_iso(b"hevc"), "image", "image/heic", "heic"),
        (_iso(b"isom"), "video", "video/mp4", "mp4"),
        (_iso(b"mp42"), "video", "video/mp4", "mp4"),
        (_iso(b"avc1"), "video", "video/mp4", "mp4"),
        (_iso(b"3gp4"), "video", "video/mp4", "mp4"),
        (_iso(b"3gp5"), "video", "video/mp4", "mp4"),
        (_iso(b"qt  "), "video", "video/quicktime", "mov"),
    ],
)
def test_each_signature_is_recognised(head, kind, mime, ext):
    found = sniff(head)
    assert (found.kind, found.mime, found.ext) == (kind, mime, ext)


@pytest.mark.parametrize(
    "head",
    [
        b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00",  # a Windows .exe
        b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj",                       # a PDF
        b"PK\x03\x04\x14\x00\x06\x00\x08\x00\x00\x00!\x00",            # a zip / .docx
        b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff",              # a GIF: not accepted
        b"RIFF\x24\x00\x00\x00WAVEfmt ",                                # RIFF, but a WAV
        _iso(b"M4A "),                                                  # ISO, but audio
        b"<html><body>hi</b",
        b"",
        b"\xff\xd8",                                                    # too short for JPEG's 3 bytes
    ],
)
def test_anything_else_is_not_a_photo_or_video(head):
    assert sniff(head) is None


def test_an_exe_renamed_to_jpg_is_refused_by_its_bytes():
    """The name plays no part: sniff only ever sees the bytes."""
    exe = b"MZ" + bytes(14)
    assert sniff(exe) is None
    assert declared_kind("image/jpeg") == "image"  # the phone's claim, refused later by the bytes


@pytest.mark.parametrize("fmt, mime", [("JPEG", "image/jpeg"), ("PNG", "image/png"),
                                       ("WEBP", "image/webp"), ("HEIF", "image/heic")])
def test_real_files_written_by_pillow_are_recognised(fmt, mime):
    """Not hand-made headers: a file an encoder actually wrote, HEIC included."""
    assert sniff(encode(scene(3), fmt)[:16]).mime == mime


# ── Declared type and limits ───────────────────────────────────────────────────

@pytest.mark.parametrize(
    "declared, kind",
    [("image/jpeg", "image"), ("image/heic", "image"), ("IMAGE/PNG", "image"),
     ("video/mp4", "video"), ("video/quicktime", "video"),
     ("application/pdf", None), ("application/octet-stream", None), ("", None), (None, None)],
)
def test_declared_kind(declared, kind):
    assert declared_kind(declared) == kind


def test_the_published_limits():
    assert MAX_IMAGE_BYTES == 10_000_000
    assert MAX_VIDEO_BYTES == 50_000_000
    assert MAX_FILES_PER_REPORT == 4
    assert MAX_BYTES_PER_REPORT == 80_000_000
    assert MAX_VIDEO_SECONDS == 60.0
    assert max_bytes("image") == 10_000_000
    assert max_bytes("video") == 50_000_000


def test_limits_read_as_a_phone_shows_them():
    assert mb(10_000_000) == "10 MB"
    assert mb(11_000_000) == "11 MB"
    assert mb(80_000_000) == "80 MB"


# ── Parts (B6) ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "size, parts",
    [(1, 1), (3_000_000, 1), (CHUNK_SIZE, 1), (CHUNK_SIZE + 1, 2), (12_000_000, 3),
     (50_000_000, 10)],
)
def test_parts_for(size, parts):
    assert CHUNK_SIZE == 5_242_880
    assert parts_for(size) == parts


def test_each_part_has_an_exact_length():
    # A 12,000,000-byte video: two full parts, then the rest.
    assert expected_part_size(1, 12_000_000) == 5_242_880
    assert expected_part_size(2, 12_000_000) == 5_242_880
    assert expected_part_size(3, 12_000_000) == 12_000_000 - 2 * 5_242_880 == 1_514_240
    # A one-part photo is its whole size; an exact multiple ends on a full part.
    assert expected_part_size(1, 3_000_000) == 3_000_000
    assert expected_part_size(2, 2 * CHUNK_SIZE) == CHUNK_SIZE
