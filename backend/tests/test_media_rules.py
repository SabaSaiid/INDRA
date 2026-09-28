"""
Phase 5 T3 — recycled and relocated media (`app/services/media_rules.py`),
what each flag costs (`report_flags.FLAGS`), the receipt's media line, and
the two n_eff rules Phase 5 adds (`services/corroboration.py`): one file is
one witness, and a bot is at most half of one.

The rules are pure: the earlier matches are passed in, as the media worker
gathers them from the database (that SQL is tested in test_media_worker.py).
The hashes come from real pictures drawn and re-saved here, so "a re-save is
still a pHash match" is measured, not assumed.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.services.corroboration import BOT_MAX_WITNESS, effective_reporters
from app.services.media_extract import extract_image, extract_video
from app.services.media_rules import (
    LOCATION_MISMATCH_KM,
    MEDIA_FLAGS,
    RECYCLED_MAX_HAMMING,
    VISION_OFFLINE_TEXT,
    is_editor,
    media_flags,
    media_summary,
    span_words,
)
from app.services.report_flags import FLAGS, adjust_credibility
from tests.media_support import encode, make_video, needs_ffmpeg, phone_jpeg, scene

PATNA = (25.5941, 85.1376)
MUMBAI = (19.0760, 72.8777)
NOW = datetime(2026, 9, 23, 6, 0, tzinfo=timezone.utc)


def report(**over):
    base = {
        "id": uuid.uuid4(), "reporter_hash": "r1", "latitude": PATNA[0], "longitude": PATNA[1],
        "place_precision": "gps", "observed_at": NOW - timedelta(minutes=5), "created_at": NOW,
    }
    return {**base, **over}


def media(**over):
    base = {"exif_taken_at": None, "exif_lat": None, "exif_lng": None, "exif_software": None,
            "has_metadata": True, "phash": 0, "frame_phashes": []}
    return {**base, **over}


def extracted(data: bytes):
    info = extract_image(data, "image/jpeg")
    return info.as_dict() | {"exif_taken_at": info.exif_taken_at}


# ── T3's table ─────────────────────────────────────────────────────────────────

def test_a_fresh_phone_photo_taken_nearby_has_no_flags():
    """EXIF 10 min before the report, GPS 300 m away → nothing."""
    ist = timezone(timedelta(hours=5, minutes=30))
    taken = (NOW - timedelta(minutes=10)).astimezone(ist).strftime("%Y:%m:%d %H:%M:%S")
    m = extracted(phone_jpeg(taken=taken, offset="+05:30", lat=PATNA[0] + 0.0027, lng=PATNA[1], make="x"))
    flags, basis = media_flags(m, report())
    assert flags == [] and basis == {}


def test_the_same_file_from_a_second_reporter_is_duplicate_media():
    first = {"report_id": uuid.uuid4(), "reporter_hash": "r2", "created_at": NOW - timedelta(hours=1)}
    flags, basis = media_flags(media(), report(), same_file=[first])
    assert flags == ["duplicate_media"]
    assert "different reporter" in basis["duplicate_media"]
    assert FLAGS["duplicate_media"] is None  # it costs nothing: n_eff merges the two instead


def test_the_same_device_sending_its_own_file_again_is_not_a_duplicate():
    mine = {"report_id": uuid.uuid4(), "reporter_hash": "r1", "created_at": NOW - timedelta(hours=1)}
    assert "duplicate_media" not in media_flags(media(), report(), same_file=[mine])[0]


def test_a_photo_resaved_at_70_percent_three_days_later_is_recycled():
    first = extracted(encode(scene(21), quality=92))
    again = extracted(encode(scene(21).resize((600, 450)), quality=70))
    seen = NOW - timedelta(days=3)
    near = [{"phash": first["phash"], "frame_phashes": [], "first_seen": seen, "origin": "citizen"}]
    flags, basis = media_flags(again, report(), near=near)
    assert "recycled_suspect" in flags
    assert basis["recycled_suspect"].startswith("near-identical to an image first seen on 20 Sep 2026 (a citizen report)")
    assert "of 64 hash bits differ" in basis["recycled_suspect"]


def test_recycled_names_mastodon_and_the_earliest_sighting():
    near = [
        {"phash": 0, "first_seen": NOW - timedelta(days=2, hours=1), "origin": "citizen"},
        {"phash": 1, "first_seen": NOW - timedelta(days=5), "origin": "social", "platform": "mastodon"},
    ]
    _, basis = media_flags(media(phash=0), report(), near=near)
    assert "first seen on 18 Sep 2026 (Mastodon)" in basis["recycled_suspect"]


def test_exif_dated_14_aug_2023_is_old_capture():
    m = extracted(phone_jpeg(taken="2023:08:14 09:12:00", offset="+05:30"))
    flags, basis = media_flags(m, report())
    assert "old_capture" in flags
    assert basis["old_capture"] == "taken 14 Aug 2023, 3 years before the report"


def test_exif_gps_in_mumbai_for_a_report_in_patna_is_location_mismatch():
    m = extracted(phone_jpeg(lat=MUMBAI[0], lng=MUMBAI[1], make="x"))
    flags, basis = media_flags(m, report())
    assert flags == ["location_mismatch"]
    assert basis["location_mismatch"].startswith("photo taken 14") and basis["location_mismatch"].endswith(
        "km from where the report was filed")


def test_no_exif_is_noted_and_costs_nothing():
    m = extracted(encode(scene(8), "PNG"))
    flags, basis = media_flags(m, report())
    assert flags == ["no_metadata"]
    assert "not held against the report" in basis["no_metadata"]
    assert adjust_credibility(0.57, flags) == 0.57


@needs_ffmpeg
def test_a_video_whose_middle_frame_matches_a_2024_image_is_recycled(tmp_path):
    """A clip built around an old photo: its frames hash like that photo."""
    old = scene(31)
    old_path = tmp_path / "old.png"
    old.save(old_path)
    old_hash = extracted(encode(old))["phash"]
    clip = extract_video(make_video(str(tmp_path / "clip.mp4"), seconds=4, size="640x480",
                                    image_path=str(old_path)), "video/mp4")
    m = clip.as_dict() | {"exif_taken_at": clip.exif_taken_at}
    near = [{"phash": old_hash, "frame_phashes": [], "origin": "citizen",
             "first_seen": datetime(2024, 7, 2, 10, 0, tzinfo=timezone.utc)}]
    flags, basis = media_flags(m, report(), near=near)
    assert "recycled_suspect" in flags
    assert "2 Jul 2024" in basis["recycled_suspect"]


# ── The boundaries ─────────────────────────────────────────────────────────────

def test_recycled_needs_hamming_8_or_less():
    seen = NOW - timedelta(days=3)
    at_8 = [{"phash": 0b11111111, "first_seen": seen}]
    at_9 = [{"phash": 0b111111111, "first_seen": seen}]
    assert RECYCLED_MAX_HAMMING == 8
    assert "recycled_suspect" in media_flags(media(phash=0), report(), near=at_8)[0]
    assert "recycled_suspect" not in media_flags(media(phash=0), report(), near=at_9)[0]


def test_recycled_needs_the_earlier_sighting_more_than_48_hours_before():
    observed = report()["observed_at"]
    just_inside = [{"phash": 0, "first_seen": observed - timedelta(hours=48)}]
    just_past = [{"phash": 0, "first_seen": observed - timedelta(hours=48, seconds=1)}]
    assert "recycled_suspect" not in media_flags(media(phash=0), report(), near=just_inside)[0]
    assert "recycled_suspect" in media_flags(media(phash=0), report(), near=just_past)[0]


def test_any_video_frame_can_match():
    near = [{"phash": -1, "frame_phashes": [12345], "first_seen": NOW - timedelta(days=9)}]
    assert "recycled_suspect" in media_flags(media(phash=0, frame_phashes=[999, 12345]), report(), near=near)[0]


def test_old_capture_is_more_than_48_hours_before_the_observation():
    observed = report()["observed_at"]
    at_48 = media(exif_taken_at=observed - timedelta(hours=48))
    past_48 = media(exif_taken_at=observed - timedelta(hours=48, minutes=1))
    assert media_flags(at_48, report())[0] == []
    assert media_flags(past_48, report())[0] == ["old_capture"]


def test_future_capture_is_more_than_an_hour_after_the_report_was_received():
    """Measured from receipt: a photo taken after the flood was seen but before filing is normal."""
    received = report()["created_at"]
    assert media_flags(media(exif_taken_at=received + timedelta(hours=1)), report())[0] == []
    flags, basis = media_flags(media(exif_taken_at=received + timedelta(hours=3)), report())
    assert flags == ["future_capture"]
    assert basis["future_capture"].startswith("the camera says 3 hours after the report was received")


def test_location_mismatch_is_more_than_25_km():
    assert LOCATION_MISMATCH_KM == 25.0
    # 0.2245° of latitude ≈ 24.96 km; 0.2255° ≈ 25.07 km.
    inside = media(exif_lat=PATNA[0] + 0.2245, exif_lng=PATNA[1])
    outside = media(exif_lat=PATNA[0] + 0.2255, exif_lng=PATNA[1])
    assert media_flags(inside, report())[0] == []
    assert media_flags(outside, report())[0] == ["location_mismatch"]


def test_a_district_centroid_is_not_a_position_to_measure_from():
    far = media(exif_lat=MUMBAI[0], exif_lng=MUMBAI[1])
    assert media_flags(far, report(place_precision="district"))[0] == []
    assert media_flags(far, report(latitude=None, longitude=None))[0] == []


@pytest.mark.parametrize(
    "software, edited",
    [("Adobe Photoshop 25.1", True), ("Snapseed 2.0", True), ("PicsArt", True), ("GIMP 2.10.36", True),
     ("HDR+ 1.0.540104767zd", False), ("iOS 17.1", False), ("G998BXXU5DWA1", False), (None, False)],
)
def test_edited_names_an_editor_not_phone_firmware(software, edited):
    assert is_editor(software) is edited
    flags, _ = media_flags(media(exif_software=software), report())
    assert ("edited" in flags) is edited
    assert adjust_credibility(0.57, flags) == 0.57


def test_flags_are_in_the_published_order():
    near = [{"phash": 0, "first_seen": NOW - timedelta(days=400)}]
    same = [{"report_id": uuid.uuid4(), "reporter_hash": "r9", "created_at": NOW - timedelta(days=400)}]
    m = media(exif_taken_at=datetime(2023, 8, 14, tzinfo=timezone.utc),
              exif_lat=MUMBAI[0], exif_lng=MUMBAI[1], exif_software="Photoshop")
    flags, basis = media_flags(m, report(), same_file=same, near=near)
    assert flags == ["duplicate_media", "recycled_suspect", "old_capture", "location_mismatch", "edited"]
    assert list(basis) == flags
    assert set(flags) <= set(MEDIA_FLAGS)


# ── What each flag costs ───────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "flags, expected",
    [
        (["recycled_suspect"], round(0.57 * 0.3, 4)),
        (["old_capture"], round(0.57 * 0.4, 4)),
        (["future_capture"], round(0.57 * 0.7, 4)),
        (["location_mismatch"], round(0.57 * 0.5, 4)),
        (["recycled_suspect", "old_capture"], round(0.57 * 0.3 * 0.4, 4)),
        (["recycled_suspect", "old_capture", "location_mismatch"], 0.05),  # the floor
        (["no_metadata", "edited", "duplicate_media"], 0.57),
    ],
)
def test_each_media_flag_costs_its_published_multiplier(flags, expected):
    assert adjust_credibility(0.57, flags) == expected


@pytest.mark.parametrize("words, delta", [
    ("14 minutes", timedelta(minutes=14)), ("1 minute", timedelta(seconds=20)),
    ("5 hours", timedelta(hours=5, minutes=10)), ("3 days", timedelta(days=3, hours=2)),
    ("2 months", timedelta(days=65)), ("3 years", timedelta(days=3 * 365 + 40)),
])
def test_span_words(words, delta):
    assert span_words(delta) == words
    assert span_words(-delta) == words


# ── The receipt's media line ───────────────────────────────────────────────────

def test_two_photos_one_captured_14_minutes_before():
    observed = NOW - timedelta(minutes=5)
    items = [
        {"kind": "image", "status": "ready", "flags": [], "exif_taken_at": observed - timedelta(minutes=14),
         "observed_at": observed},
        {"kind": "image", "status": "ready", "flags": ["no_metadata"], "exif_taken_at": None,
         "observed_at": observed},
    ]
    summary = media_summary(items)
    assert summary["line"] == "2 photos checked: 1 captured 14 minutes before the report; no reuse found"
    assert (summary["checked"], summary["photos"], summary["videos"]) == (2, 2, 0)
    assert summary["flags"] == {"no_metadata": 1}
    assert "content is not analysed" in summary["rule"]


def test_the_line_gives_the_reason_for_reuse_and_what_is_still_processing():
    items = [
        {"kind": "image", "status": "ready", "flags": ["recycled_suspect", "old_capture"],
         "flag_basis": {"recycled_suspect": "near-identical to an image first seen on 20 Sep 2026 (Mastodon)",
                        "old_capture": "taken 14 Aug 2023, 3 years before the report"},
         "exif_taken_at": datetime(2023, 8, 14, tzinfo=timezone.utc), "observed_at": NOW},
        {"kind": "video", "status": "processing", "flags": []},
    ]
    assert media_summary(items)["line"] == (
        "1 photo checked: near-identical to an image first seen on 20 Sep 2026 (Mastodon); "
        "taken 14 Aug 2023, 3 years before the report; 1 still processing"
    )


def test_no_media_no_line():
    assert media_summary([]) is None


def test_vision_stays_offline_and_says_what_is_checked_instead():
    assert VISION_OFFLINE_TEXT == "image content is not analysed; media is checked for reuse and metadata only"


# ── n_eff: one file is one witness; a bot at most half ─────────────────────────

def _r(credibility, reporter, *, sha=(), flags=()):
    return {"id": uuid.uuid4(), "reporter_hash": reporter, "source_type": "CITIZEN_APP",
            "credibility": credibility, "flags": list(flags), "media_sha256": list(sha)}


def test_two_reporters_sending_the_same_file_count_once():
    alone = effective_reporters([_r(0.6, "a"), _r(0.6, "b")])
    shared = effective_reporters([_r(0.6, "a", sha=["f1"]), _r(0.6, "b", sha=["f1"])])
    assert alone["n_eff"] == 2.0
    assert shared["n_eff"] == 1.0
    assert shared["basis"]["merged_by_shared_media"] == 1
    assert shared["basis"]["distinct_reporters"] == 2


def test_a_forward_chain_merges_transitively():
    """a and b share f1, b and c share f2: one sighting, not two."""
    chain = [_r(0.6, "a", sha=["f1"]), _r(0.6, "b", sha=["f1", "f2"]), _r(0.6, "c", sha=["f2"]),
             _r(0.6, "d", sha=["f3"])]
    result = effective_reporters(chain)
    assert result["n_eff"] == 2.0
    assert result["basis"]["merged_by_shared_media"] == 2


def test_a_group_counts_as_its_best_member():
    """The citizen who took the photo still counts in full beside the bot that re-shared it."""
    result = effective_reporters([_r(0.6, "citizen", sha=["f1"]),
                                  _r(0.2, "bot", sha=["f1"], flags=["bot_account"])])
    assert result["n_eff"] == 1.0


def test_a_bot_counts_at_most_half_a_witness():
    assert BOT_MAX_WITNESS == 0.5
    result = effective_reporters([_r(0.9, "bot", flags=["bot_account"]), _r(0.6, "person")])
    assert result["n_eff"] == 1.5
    assert result["basis"]["bot_reporters"] == 1
    # A weak bot keeps its own, lower weight: min(0.5, 0.15 / 0.6).
    assert effective_reporters([_r(0.15, "bot", flags=["bot_account"])])["n_eff"] == 0.25


def test_the_basis_names_both_rules():
    rule = effective_reporters([_r(0.6, "a")])["basis"]["rule"]
    assert "reporters sharing a file count once" in rule and "a bot at most 0.5" in rule
