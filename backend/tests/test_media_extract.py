"""
Phase 5 T2 — what a photo or video says about itself
(`app/services/media_extract.py`), and T5 step 1's copies that are safe to
show (`app/services/media_derivatives.py`).

Every fixture is made here: pictures drawn with Pillow, EXIF written with
piexif, and small MP4s made with ffmpeg (those tests are skipped with a reason
when ffmpeg is missing). T2's table row for row, then the edge cases the code
decides: an EXIF time with no offset, a zero GPS fix, a decompression bomb, an
iPhone-style location tag.
"""

import io
from datetime import datetime, timezone

import pytest
from PIL import Image

from app.services.media_derivatives import image_derivatives, strip_video, video_poster
from app.services.media_extract import (
    UnreadableMedia,
    extract_image,
    extract_video,
    frame_times,
    gps_to_decimal,
    hamming,
    parse_exif_time,
    parse_iso6709,
    phash_of,
    sha256_file,
    to_signed64,
)
from tests.media_support import encode, exif_bytes, ffprobe_tags, make_video, needs_ffmpeg, phone_jpeg, scene


# ── T2's table: photos ─────────────────────────────────────────────────────────

def test_exif_time_with_offset_and_gps_are_read():
    """EXIF 2026-09-23 06:10 +05:30 and GPS 25.6, 85.1 → 00:40 UTC; lat 25.6, lng 85.1."""
    info = extract_image(phone_jpeg(taken="2026:09:23 06:10:00", offset="+05:30", lat=25.6, lng=85.1,
                                    make="samsung", model="SM-A546E"), "image/jpeg")
    assert info.exif_taken_at == datetime(2026, 9, 23, 0, 40, tzinfo=timezone.utc)
    assert info.exif_offset == "+05:30" and info.exif_offset_assumed is False
    assert info.exif_lat == pytest.approx(25.6, abs=1e-5)
    assert info.exif_lng == pytest.approx(85.1, abs=1e-5)
    assert (info.exif_make, info.exif_model) == ("samsung", "SM-A546E")
    assert info.has_metadata is True
    assert (info.width, info.height) == (640, 480)


def test_the_same_photo_resized_to_half_keeps_its_phash_within_4():
    original = extract_image(encode(scene(11)), "image/jpeg").phash
    half = extract_image(encode(scene(11).resize((320, 240))), "image/jpeg").phash
    assert hamming(original, half) <= 4


def test_a_different_photo_is_more_than_20_bits_away():
    a = extract_image(encode(scene(11)), "image/jpeg").phash
    b = extract_image(encode(scene(12)), "image/jpeg").phash
    assert hamming(a, b) > 20


def test_a_png_with_no_exif_has_every_exif_field_null():
    info = extract_image(encode(scene(5), "PNG"), "image/png")
    assert info.has_metadata is False
    for field in ("exif_taken_at", "exif_offset", "exif_lat", "exif_lng",
                  "exif_make", "exif_model", "exif_software"):
        assert getattr(info, field) is None, field
    assert info.phash is not None


def test_a_photoshop_edit_records_the_software():
    info = extract_image(phone_jpeg(software="Adobe Photoshop 25.1 (Windows)"), "image/jpeg")
    assert info.exif_software == "Adobe Photoshop 25.1 (Windows)"


def test_a_corrupt_jpeg_is_unreadable_not_a_crash():
    good = phone_jpeg()
    with pytest.raises(UnreadableMedia):
        extract_image(good[:200], "image/jpeg")
    with pytest.raises(UnreadableMedia):
        extract_image(b"\xff\xd8\xff" + b"\x00" * 500, "image/jpeg")


def test_an_iphone_heic_is_read():
    """pillow-heif decodes HEIC; its EXIF is read the same way as a JPEG's."""
    data = encode(scene(7), "HEIF", exif=exif_bytes(taken="2026:09:23 06:10:00", offset="+05:30"))
    info = extract_image(data, "image/heic")
    assert info.phash is not None and (info.width, info.height) == (640, 480)
    assert info.exif_taken_at == datetime(2026, 9, 23, 0, 40, tzinfo=timezone.utc)


# ── The decisions T2 left to the code ──────────────────────────────────────────

def test_an_exif_time_without_an_offset_is_read_as_ist_and_says_so():
    info = extract_image(phone_jpeg(taken="2026:09:23 06:10:00"), "image/jpeg")
    assert info.exif_taken_at == datetime(2026, 9, 23, 0, 40, tzinfo=timezone.utc)
    assert info.exif_offset == "+05:30" and info.exif_offset_assumed is True


@pytest.mark.parametrize(
    "value, offset, expected",
    [
        ("2026:09:23 06:10:00", "+05:30", datetime(2026, 9, 23, 0, 40, tzinfo=timezone.utc)),
        ("2026:09:23 06:10:00", "-04:00", datetime(2026, 9, 23, 10, 10, tzinfo=timezone.utc)),
        ("2026:09:23 06:10:00", "+0530", datetime(2026, 9, 23, 0, 40, tzinfo=timezone.utc)),
        (b"2026:09:23 06:10:00\x00", None, datetime(2026, 9, 23, 0, 40, tzinfo=timezone.utc)),
        ("0000:00:00 00:00:00", "+05:30", None),     # a camera clock never set
        ("not a date", None, None),
        (None, None, None),
    ],
)
def test_parse_exif_time(value, offset, expected):
    assert parse_exif_time(value, offset)[0] == expected


def test_southern_and_western_gps_are_negative():
    assert gps_to_decimal(((33, 1), (52, 1), (0, 1)), "S") == pytest.approx(-33.866667)
    assert gps_to_decimal(((151, 1), (12, 1), (0, 1)), b"W") == pytest.approx(-151.2)
    assert gps_to_decimal("garbage", "N") is None


def test_a_zero_gps_fix_is_no_position():
    """(0, 0) is a phone with no fix that wrote zeros, not a point in the Gulf of Guinea."""
    info = extract_image(phone_jpeg(lat=0.0, lng=0.0, make="x"), "image/jpeg")
    assert info.exif_lat is None and info.exif_lng is None


def test_a_decompression_bomb_is_unreadable(monkeypatch):
    from app.services import media_extract

    monkeypatch.setattr(media_extract, "MAX_PIXELS", 640 * 480 - 1)
    with pytest.raises(UnreadableMedia, match="more than accepted"):
        extract_image(encode(scene(1)), "image/jpeg")


def test_hashes_are_signed_64_bit_for_postgres_bigint():
    assert to_signed64(0xFFFFFFFFFFFFFFFF) == -1
    assert to_signed64(0x7FFFFFFFFFFFFFFF) == 2**63 - 1
    assert to_signed64(0x8000000000000000) == -(2**63)
    assert hamming(-1, 0) == 64 and hamming(5, 5) == 0 and hamming(0b1011, 0b0001) == 2
    ph = phash_of(scene(2))
    assert -(2**63) <= ph < 2**63


def test_sha256_of_a_file(tmp_path):
    path = tmp_path / "f.bin"
    path.write_bytes(b"abc")
    assert sha256_file(str(path)) == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", 3
    )


@pytest.mark.parametrize(
    "value, expected",
    [
        ("+25.6000+085.1000+050.000/", (25.6, 85.1)),
        ("+19.0760+072.8777/", (19.076, 72.8777)),
        ("-33.8667+151.2000/", (-33.8667, 151.2)),
        ("+00.0000+000.0000/", (None, None)),
        ("+95.0000+085.1000/", (None, None)),
        ("", (None, None)),
        (None, (None, None)),
    ],
)
def test_parse_iso6709(value, expected):
    assert parse_iso6709(value) == expected


def test_frame_times():
    assert frame_times(30.0) == [1.0, 7.5, 15.0, 22.5]
    assert frame_times(1.0) == [0.5, 0.25, 0.5, 0.75]   # a 1 s clip: its middle, not past its end
    assert frame_times(None) == [0.0]


# ── T2's table: videos ─────────────────────────────────────────────────────────

@needs_ffmpeg
def test_an_mp4_gives_its_duration_creation_time_and_four_frame_hashes(tmp_path):
    path = make_video(str(tmp_path / "clip.mp4"), seconds=4, creation_time="2026-09-23T00:40:00Z")
    info = extract_video(path, "video/mp4")
    assert info.duration_s == pytest.approx(4.0, abs=0.2)
    assert info.exif_taken_at == datetime(2026, 9, 23, 0, 40, tzinfo=timezone.utc)
    assert len(info.frame_phashes) == 4
    assert info.phash == info.frame_phashes[0]
    assert (info.width, info.height) == (320, 240)
    assert info.has_metadata is True
    # The muxer's own "Lavf…" encoder tag is not an editing app.
    assert info.exif_software is None


@needs_ffmpeg
def test_a_video_location_tag_gives_its_gps(tmp_path):
    path = make_video(str(tmp_path / "gps.mp4"), seconds=2, location="+25.6000+085.1000/")
    info = extract_video(path, "video/mp4")
    assert (info.exif_lat, info.exif_lng) == (25.6, 85.1)


def _iphone_mov(path: str) -> str:
    """A QuickTime file with the keys an iPhone writes (mdta: location, creation date, make, model)."""
    import subprocess

    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=10", "-t", "2",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "use_metadata_tags",
         "-metadata", "com.apple.quicktime.location.ISO6709=+25.5941+085.1376+050.000/",
         "-metadata", "com.apple.quicktime.creationdate=2026-09-23T06:10:00+0530",
         "-metadata", "com.apple.quicktime.make=Apple",
         "-metadata", "com.apple.quicktime.model=iPhone 15", path],
        check=True, capture_output=True, timeout=60,
    )
    return path


@needs_ffmpeg
def test_an_iphone_mov_gives_its_place_time_and_camera(tmp_path):
    path = _iphone_mov(str(tmp_path / "IMG_0001.MOV"))
    with open(path, "rb") as f:
        from app.services.media_types import sniff

        assert sniff(f.read(16)).mime == "video/quicktime"
    info = extract_video(path, "video/quicktime")
    assert (info.exif_lat, info.exif_lng) == (25.5941, 85.1376)
    assert info.exif_taken_at == datetime(2026, 9, 23, 0, 40, tzinfo=timezone.utc)
    assert (info.exif_make, info.exif_model) == ("Apple", "iPhone 15")


@needs_ffmpeg
def test_a_stripped_iphone_mov_keeps_no_apple_location_key(tmp_path):
    src = _iphone_mov(str(tmp_path / "in.mov"))
    dst = str(tmp_path / "out.mov")
    strip_video(src, dst)
    tags = ffprobe_tags(dst)
    assert not any(k.startswith("com.apple.quicktime") for k in tags), tags
    assert extract_video(dst, "video/quicktime").has_metadata is False


@needs_ffmpeg
def test_a_video_with_no_tags_has_no_metadata(tmp_path):
    info = extract_video(make_video(str(tmp_path / "bare.mp4"), seconds=2), "video/mp4")
    assert info.has_metadata is False and info.exif_taken_at is None


@needs_ffmpeg
def test_a_file_that_is_not_a_video_is_unreadable(tmp_path):
    path = tmp_path / "fake.mp4"
    path.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 200)
    with pytest.raises(UnreadableMedia):
        extract_video(str(path), "video/mp4")


# ── T5 step 1: the copies that are shown ───────────────────────────────────────

def _open(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


def test_image_copies_are_small_and_carry_no_exif():
    big = encode(scene(4, size=(4000, 3000)), exif=exif_bytes(
        taken="2026:09:23 06:10:00", offset="+05:30", lat=25.6, lng=85.1, make="Apple", model="iPhone 15"))
    assert _open(big).getexif()  # the original does carry it
    full, thumb = image_derivatives(big)
    full_img, thumb_img = _open(full), _open(thumb)
    assert full_img.format == thumb_img.format == "JPEG"
    assert max(full_img.size) == 1600 and max(thumb_img.size) == 320
    assert not full_img.getexif() and not thumb_img.getexif()
    assert b"Exif" not in full[:4096] and b"Exif" not in thumb[:4096]


def test_a_portrait_photo_still_stands_up_once_its_orientation_tag_is_gone():
    """Orientation 6 (rotate 90°): the pixels are turned before the tag is dropped."""
    landscape_pixels = encode(scene(4, size=(800, 600)), exif=exif_bytes(orientation=6, make="x"))
    full, _ = image_derivatives(landscape_pixels)
    assert _open(full).size == (600, 800)


def test_a_small_photo_is_not_enlarged():
    full, thumb = image_derivatives(encode(scene(4, size=(300, 200))))
    assert _open(full).size == (300, 200)
    assert _open(thumb).size == (300, 200)


@needs_ffmpeg
def test_a_stripped_video_has_no_location_and_no_creation_time(tmp_path):
    src = make_video(str(tmp_path / "in.mp4"), seconds=2, creation_time="2026-09-23T00:40:00Z",
                     location="+25.6000+085.1000/")
    tags = ffprobe_tags(src)
    assert "location" in tags and "creation_time" in tags  # the original has both
    dst = str(tmp_path / "out.mp4")
    strip_video(src, dst)
    stripped = ffprobe_tags(dst)
    assert "location" not in stripped
    assert "creation_time" not in stripped
    assert not any("location" in k or "iso6709" in k for k in stripped)
    # Nothing re-encoded: still a playable video of the same length.
    assert extract_video(dst, "video/mp4").duration_s == pytest.approx(2.0, abs=0.2)


@needs_ffmpeg
def test_a_video_poster_and_thumbnail(tmp_path):
    src = make_video(str(tmp_path / "in.mp4"), seconds=3, size="640x360")
    poster, thumb = video_poster(src, 3.0)
    assert _open(poster).size == (640, 360)
    assert max(_open(thumb).size) == 320
