"""
Phase 5 T2–T4 end to end — the media worker (`app/workers/media_worker.py`).

A photo or video goes up through the real upload routes into the in-memory
store, and `process_citizen_media` runs on it against indra_test, so the
earlier-media SQL (SHA-256 matches, and the pHash Hamming distance computed in
Postgres as `bit(64)`) runs on a real database. B7's two rows, T3's rules as
the worker applies them, the re-score of an event, the failure paths, and T4:
Mastodon attachments through the same checks, and the backfill.
"""

import asyncio
import json
import sys
import uuid
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text

from app.services import clock, pipeline
from app.workers import media_worker
from tests.media_support import (  # noqa: F401  (fixture)
    encode, exif_bytes, fake_store, make_video, needs_ffmpeg, phone_jpeg, scene,
)
from tests.phase5_support import (  # noqa: F401  (fixtures)
    PATNA, api, broadcasts, db, device, filed, media_rows, report_row, salted, upload_media,
)

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def no_queue(monkeypatch):
    """The routes hand files to the worker; here each test runs the worker itself."""
    monkeypatch.setattr(media_worker, "enqueue", lambda media_id: None)


@pytest.fixture(autouse=True)
def fixed_weather(monkeypatch):
    async def _weather(lat, lng):
        return 0.35, 15.6

    monkeypatch.setattr(pipeline, "weather_score", _weather)


def ist_now(minutes_ago: int = 0) -> str:
    """EXIF's local time, in IST, `minutes_ago` before now."""
    from datetime import timezone

    ist = timezone(timedelta(hours=5, minutes=30))
    return (clock.now() - timedelta(minutes=minutes_ago)).astimezone(ist).strftime("%Y:%m:%d %H:%M:%S")


upload = upload_media


async def one(db, media_id) -> dict:
    row = (await db.execute(text("SELECT * FROM report_media WHERE id = CAST(:id AS uuid)"),
                            {"id": media_id})).fetchone()
    await db.commit()
    return dict(row._mapping)


# ── B7: a phone photo ──────────────────────────────────────────────────────────

async def test_a_phone_photo_is_read_filed_and_announced(api, db, salted, fake_store, broadcasts):
    data = phone_jpeg(1, taken=ist_now(10), offset="+05:30", lat=PATNA[0] + 0.002, lng=PATNA[1],
                      make="samsung", model="SM-A546E")
    report = await filed(api, 1)
    uid = await upload(api, data, docket=report["docket"])

    media = await media_worker.process_citizen_media(uid)

    assert media["status"] == "ready" and media["flags"] == []
    row = await one(db, uid)
    assert row["status"] == "ready" and row["bytes"] == len(data) and len(row["sha256"]) == 64
    assert row["phash"] is not None and (row["width"], row["height"]) == (640, 480)
    assert row["exif_make"] == "samsung" and row["exif_lat"] == pytest.approx(PATNA[0] + 0.002, abs=1e-5)
    day = row["created_at"].strftime("%Y/%m/%d")
    assert row["object_key"] == f"originals/{day}/{report['id']}/{row['sha256']}.jpg"
    assert fake_store.body(row["object_key"]) == data
    assert row["derivative_key"] == f"derivatives/{report['id']}/{uid}/full.jpg"
    assert row["thumb_key"] == f"derivatives/{report['id']}/{uid}/thumb.jpg"
    assert fake_store.keys("incoming/") == []  # the upload copy is gone
    # The copies carry no EXIF.
    assert b"Exif" not in fake_store.body(row["derivative_key"])[:4096]
    ready = [m for m in broadcasts if m["type"] == "REPORT_MEDIA_READY"]
    assert len(ready) == 1 and ready[0]["report_id"] == report["id"]
    assert ready[0]["media"] == [{"id": uid, "kind": "image", "status": "ready", "flags": []}]
    raw = json.dumps(ready[0])
    assert "http" not in raw and report["docket"] not in raw


async def test_a_heic_photo_is_processed_and_its_copies_are_jpeg(api, db, salted, fake_store, broadcasts):
    data = encode(scene(9), "HEIF", exif=exif_bytes(taken=ist_now(5), offset="+05:30"))
    uid = await upload(api, data, mime="image/heic")
    assert (await media_worker.process_citizen_media(uid))["status"] == "ready"
    row = await one(db, uid)
    assert row["mime"] == "image/heic" and row["object_key"].endswith(".heic")
    assert fake_store.body(row["derivative_key"])[:3] == b"\xff\xd8\xff"


async def test_a_corrupt_photo_is_rejected_as_unreadable_and_the_report_kept(api, db, salted, fake_store):
    report = await filed(api, 1)
    uid = await upload(api, b"\xff\xd8\xff\xe0" + bytes(5000), docket=report["docket"])
    assert await media_worker.process_citizen_media(uid) is None
    row = await one(db, uid)
    assert row["status"] == "rejected" and row["flags"] == ["unreadable"]
    assert row["reason"].startswith("unreadable:")
    assert (await report_row(db, report["id"]))["raw_text"]  # the report is untouched
    assert fake_store.keys() == []


# ── B7: a video ────────────────────────────────────────────────────────────────

@needs_ffmpeg
async def test_a_video_gets_its_duration_four_frames_a_poster_and_a_stripped_copy(
        api, db, salted, fake_store, broadcasts, tmp_path):
    from tests.media_support import ffprobe_tags

    path = make_video(str(tmp_path / "v.mp4"), seconds=6, creation_time="2026-09-23T00:40:00Z",
                      location="+25.5941+085.1376/")
    data = Path(path).read_bytes()
    uid = await upload(api, data, mime="video/mp4")
    media = await media_worker.process_citizen_media(uid)
    assert media["status"] == "ready" and media["duration_s"] == pytest.approx(6.0, abs=0.2)
    row = await one(db, uid)
    assert len(row["frame_phashes"]) == 4 and row["phash"] == row["frame_phashes"][0]
    assert (row["exif_lat"], row["exif_lng"]) == (25.5941, 85.1376)
    assert row["poster_key"].endswith("/poster.jpg") and row["thumb_key"].endswith("/thumb.jpg")
    assert row["derivative_key"].endswith("/video.mp4")
    stripped = tmp_path / "stripped.mp4"
    stripped.write_bytes(fake_store.body(row["derivative_key"]))
    tags = ffprobe_tags(str(stripped))
    assert "location" not in tags and "creation_time" not in tags
    assert [m for m in broadcasts if m["type"] == "REPORT_MEDIA_READY"][0]["media"][0]["duration_s"] > 5


@needs_ffmpeg
async def test_a_video_over_60_seconds_is_dropped_with_its_reason(api, db, salted, fake_store, tmp_path):
    path = make_video(str(tmp_path / "long.mp4"), seconds=61, size="160x120")
    report = await filed(api, 1)
    uid = await upload(api, Path(path).read_bytes(), docket=report["docket"], mime="video/mp4")
    assert await media_worker.process_citizen_media(uid) is None
    row = await one(db, uid)
    assert row["status"] == "rejected" and row["reason"] == "video is 61 s long; at most 60 s is accepted"
    assert (await report_row(db, report["id"])) is not None


# ── T3 through the worker ──────────────────────────────────────────────────────

async def test_the_same_file_from_a_second_device_is_one_witness(api, db, salted, fake_store):
    data = phone_jpeg(2, taken=ist_now(10), offset="+05:30")
    first = await upload(api, data, n=1)
    await media_worker.process_citizen_media(first)
    second_report = await filed(api, 2)
    second = await upload(api, data, n=2, docket=second_report["docket"])
    media = await media_worker.process_citizen_media(second)
    assert media["flags"] == ["duplicate_media"]
    report = await report_row(db, second_report["id"])
    assert "duplicate_media" in report["flags"]
    assert "different reporter" in report["analysis"]["flag_basis"]["duplicate_media"]
    # It costs no credibility; n_eff merges the two reporters instead.
    fresh = await report_row(db, (await filed(api, 3))["id"])
    assert report["credibility_score"] == fresh["credibility_score"]
    rows = await pipeline._cluster_reports(db, [report["id"], (await media_rows(db))[0]["report_id"]])
    from app.services.corroboration import effective_reporters

    assert effective_reporters(rows)["basis"]["merged_by_shared_media"] == 1


async def test_a_photo_resaved_three_days_later_is_recycled_by_the_postgres_distance(
        api, db, salted, fake_store):
    first = await upload(api, encode(scene(21), quality=92), n=1)
    await media_worker.process_citizen_media(first)
    await db.execute(text("UPDATE report_media SET created_at = NOW() - interval '3 days' "
                          "WHERE id = CAST(:id AS uuid)"), {"id": first})
    await db.commit()

    later = await filed(api, 2)
    before = (await report_row(db, later["id"]))["credibility_score"]
    second = await upload(api, encode(scene(21).resize((600, 450)), quality=70), n=2, docket=later["docket"])
    media = await media_worker.process_citizen_media(second)

    assert "recycled_suspect" in media["flags"]
    report = await report_row(db, later["id"])
    assert report["credibility_score"] == round(before * 0.3, 4)
    reason = report["analysis"]["flag_basis"]["recycled_suspect"]
    assert reason.startswith("near-identical to an image first seen on ") and "(a citizen report)" in reason
    row = await one(db, second)
    assert row["flag_basis"]["recycled_suspect"] == reason


async def test_the_sql_distance_agrees_with_python(db, salted, api, fake_store):
    """near_matches computes Hamming distance as bit(64) in Postgres; check it against hamming()."""
    from app.services.media_extract import hamming

    uid = await upload(api, phone_jpeg(4), n=1)
    await media_worker.process_citizen_media(uid)
    await db.execute(text("UPDATE report_media SET created_at = NOW() - interval '9 days', "
                          "phash = -6148914691236517206 WHERE id = CAST(:id AS uuid)"), {"id": uid})
    await db.commit()
    stored = -6148914691236517206   # 0xAAAAAAAAAAAAAAAA, signed
    for flip in (0, 1, 8, 9):
        probe = stored ^ ((1 << flip) - 1)
        assert hamming(stored, probe) == flip
        found = await media_worker.near_matches(db, media_id=uuid.uuid4(), hashes=[probe], observed=clock.now())
        assert [m["distance"] for m in found] == ([flip] if flip <= 8 else []), flip
    await db.commit()


async def test_an_old_photo_lowers_the_report_and_counts_on_the_reporters_record(api, db, salted, fake_store):
    report = await filed(api, 1)
    before = (await report_row(db, report["id"]))["credibility_score"]
    uid = await upload(api, phone_jpeg(5, taken="2023:08:14 09:12:00", offset="+05:30"),
                       docket=report["docket"])
    media = await media_worker.process_citizen_media(uid)
    assert media["flags"] == ["old_capture"]
    row = await report_row(db, report["id"])
    assert row["credibility_score"] == round(before * 0.4, 4)
    assert row["analysis"]["flag_basis"]["old_capture"].startswith("taken 14 Aug 2023, 3 years before")
    flagged = (await db.execute(text("SELECT flagged FROM reporter_stats"))).scalar()
    await db.commit()
    assert flagged == 1


async def test_a_second_old_photo_on_the_same_report_does_not_charge_twice(api, db, salted, fake_store):
    report = await filed(api, 1)
    before = (await report_row(db, report["id"]))["credibility_score"]
    for seed in (5, 6):
        uid = await upload(api, phone_jpeg(seed, taken="2023:08:14 09:12:00"), docket=report["docket"])
        await media_worker.process_citizen_media(uid)
    assert (await report_row(db, report["id"]))["credibility_score"] == round(before * 0.4, 4)


async def test_an_exif_time_with_no_offset_says_it_was_read_as_ist(api, db, salted, fake_store):
    uid = await upload(api, phone_jpeg(3, taken=ist_now(10)))
    await media_worker.process_citizen_media(uid)
    assert (await one(db, uid))["flag_basis"]["offset_assumed"].endswith("read as IST")


# ── An event re-scored ─────────────────────────────────────────────────────────

async def _event_of_four(api, db):
    texts = ["Water entering ground floor shops near Kankarbagh main road",
             "Kankarbagh underpass completely submerged, cars stuck",
             "Knee deep water outside my house, drain overflowing",
             "Flooding on the road to Patna junction, buses diverted"]
    reports = []
    for n, t in enumerate(texts, start=1):
        reports.append(await filed(api, n, text_=t, lat=PATNA[0] + n * 0.0005))
        await pipeline.process_report(db, {"id": reports[-1]["id"]})
    event_id = (await report_row(db, reports[0]["id"]))["event_id"]
    assert event_id is not None
    return reports, str(event_id)


async def _event(db, event_id):
    row = (await db.execute(text("SELECT confidence_score, verification_receipt FROM verified_events "
                                 "WHERE id = CAST(:id AS uuid)"), {"id": event_id})).fetchone()
    await db.commit()
    return row


async def test_a_flagged_photo_rescores_its_event(api, db, salted, fake_store, broadcasts):
    reports, event_id = await _event_of_four(api, db)
    before, _ = await _event(db, event_id)
    uid = await upload(api, phone_jpeg(5, taken="2023:08:14 09:12:00"), n=1, docket=reports[0]["docket"])
    await media_worker.process_citizen_media(uid)

    after, receipt = await _event(db, event_id)
    assert after < before
    assert receipt["late_corroboration"]["trigger"] == f"media:{uid}"
    assert receipt["media"]["line"].startswith("1 photo checked: taken 14 Aug 2023")
    vision = next(f for f in receipt["factors"] if f["key"] == "vision_analysis")
    assert vision["evidence"].endswith("media is checked for reuse and metadata only")
    ledger = (await db.execute(text("SELECT count(*) FROM audit_logs WHERE event_id = CAST(:id AS uuid) "
                                    "AND CAST(action_taken AS text) = 'LATE_CORROBORATION'"),
                               {"id": event_id})).scalar()
    await db.commit()
    assert ledger == 1
    kinds = [m["type"] for m in broadcasts]
    assert "VERIFIED_EVENT" in kinds and kinds[-1] == "REPORT_MEDIA_READY"
    assert broadcasts[-1]["event_id"] == event_id


async def test_a_clean_photo_reaches_the_receipt_without_moving_a_number(api, db, salted, fake_store):
    """No score changes, so no ledger row; the receipt still says what was checked."""
    reports, event_id = await _event_of_four(api, db)
    before, old = await _event(db, event_id)
    uid = await upload(api, phone_jpeg(7, taken=ist_now(14), offset="+05:30",
                                       lat=PATNA[0] + 0.0005, lng=PATNA[1]), n=1, docket=reports[0]["docket"])
    await media_worker.process_citizen_media(uid)

    after, receipt = await _event(db, event_id)
    assert after == before
    assert receipt["media"]["line"].startswith("1 photo checked: 1 captured ")
    assert receipt["media"]["line"].endswith("; no reuse found")
    assert "late_corroboration" not in receipt
    old.pop("media", None)
    receipt.pop("media")
    for f in receipt["factors"] + old["factors"]:
        if f["key"] == "vision_analysis":
            f.pop("evidence")
    assert receipt == old  # nothing else in the receipt moved


# ── Failure paths ──────────────────────────────────────────────────────────────

async def test_a_withdrawal_during_processing_flags_nothing_and_removes_the_copies(
        api, db, salted, fake_store, monkeypatch):
    report = await filed(api, 1)
    uid = await upload(api, phone_jpeg(5, taken="2023:08:14 09:12:00"), docket=report["docket"])
    real = media_worker.near_matches

    async def withdrawn_meanwhile(session, **kw):
        from app.core.database import async_session

        async with async_session() as other:
            await other.execute(text("UPDATE report_media SET status = 'withdrawn' WHERE id = CAST(:id AS uuid)"),
                                {"id": uid})
            await other.commit()
        return await real(session, **kw)

    monkeypatch.setattr(media_worker, "near_matches", withdrawn_meanwhile)
    assert await media_worker.process_citizen_media(uid) is None
    assert (await one(db, uid))["status"] == "withdrawn"
    assert (await report_row(db, report["id"]))["flags"] == []
    assert fake_store.keys() == []


async def test_a_store_down_leaves_the_file_for_the_sweep(api, db, salted, fake_store):
    uid = await upload(api, phone_jpeg(1))
    fake_store.down = True
    assert await media_worker.process_citizen_media(uid) is None
    assert (await one(db, uid))["status"] == "processing"
    fake_store.down = False
    assert (await media_worker.process_citizen_media(uid))["status"] == "ready"


async def test_three_failures_mark_a_file_rejected(api, db, salted, fake_store, monkeypatch):
    uid = await upload(api, phone_jpeg(1))

    def broken(data, mime=None):
        raise RuntimeError("disk full")

    monkeypatch.setattr(media_worker, "extract_image", broken)
    for attempt in (1, 2):
        await media_worker.process_citizen_media(uid)
        assert (await one(db, uid))["status"] == "processing", attempt
    await media_worker.process_citizen_media(uid)
    row = await one(db, uid)
    assert row["status"] == "rejected" and row["reason"].startswith("processing failed 3 times")


async def test_the_sweep_finds_what_the_queue_missed(api, db, salted, fake_store, monkeypatch):
    uid = await upload(api, phone_jpeg(1))
    monkeypatch.setattr(media_worker, "_queue", asyncio.Queue())
    assert await media_worker.sweep() == 1
    assert media_worker._queue.get_nowait() == ("citizen", uid)


def test_the_ready_message_carries_no_url_and_no_docket():
    message = media_worker.media_ready_message("r1", None, [
        {"id": "m1", "kind": "video", "status": "ready", "flags": ["old_capture"], "duration_s": 12.0}])
    assert message == {"type": "REPORT_MEDIA_READY", "report_id": "r1", "event_id": None,
                       "media": [{"id": "m1", "kind": "video", "status": "ready", "flags": ["old_capture"],
                                  "duration_s": 12.0}]}


# ── T4: Mastodon attachments ───────────────────────────────────────────────────

async def social_post(db, *, media, days_ago=0.0, author="author-a") -> str:
    rid = str(uuid.uuid4())
    at = clock.now() - timedelta(days=days_ago)
    await db.execute(
        text("""
            INSERT INTO raw_reports (id, source_type, raw_text, source_meta, observed_at, created_at,
                                     platform, place_precision, reporter_hash, credibility_score, flags)
            VALUES (CAST(:id AS uuid), 'SOCIAL_MEDIA', 'Heavy rain and flooding #IMD', CAST(:meta AS jsonb),
                    :at, :at, 'mastodon', 'none', :author, 0.4, '{}')
        """),
        {"id": rid, "meta": json.dumps({"media": media, "url": f"https://mastodon.social/web/statuses/{rid}"}),
         "at": at, "author": author},
    )
    await db.commit()
    return rid


def web(files):
    """An httpx client whose server answers from `files` (url → bytes), 404 otherwise."""
    def handler(request):
        body = files.get(str(request.url))
        return httpx.Response(200, content=body) if body is not None else httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_an_image_seen_on_a_post_five_days_earlier_is_recycled(db, fake_store, broadcasts):
    photo = encode(scene(40))
    files = {"https://files.example/old.jpg": photo, "https://files.example/new.jpg": photo}
    old = await social_post(db, media=[{"type": "image", "url": "https://files.example/old.jpg"}], days_ago=5)
    new = await social_post(db, media=[{"type": "image", "url": "https://files.example/new.jpg"}],
                            author="author-b")
    async with web(files) as client:
        assert await media_worker.process_social_post(old, client=client) == {
            "downloaded": 1, "skipped": 0, "failed": 0}
        assert (await media_worker.process_social_post(new, client=client))["downloaded"] == 1

    newest = (await media_rows(db, new))[0]
    assert "recycled_suspect" in newest["flags"] and "duplicate_media" in newest["flags"]
    assert "(Mastodon)" in newest["flag_basis"]["recycled_suspect"]
    assert "no_metadata" not in newest["flags"]  # platforms strip EXIF from everything
    assert newest["origin"] == "social" and newest["source_url"] == "https://files.example/new.jpg"
    assert newest["object_key"].startswith("social/") and newest["derivative_key"] is None
    report = await report_row(db, new)
    assert report["credibility_score"] == round(0.4 * 0.3, 4)
    assert (await media_rows(db, old))[0]["flags"] == []


async def test_a_large_attachment_and_a_404_are_skipped_and_the_rest_processed(db, fake_store):
    files = {"https://files.example/huge.jpg": b"\xff\xd8\xff" + bytes(10_000_000),
             "https://files.example/ok.jpg": encode(scene(41))}
    post = await social_post(db, media=[
        {"type": "image", "url": "https://files.example/huge.jpg"},
        {"type": "image", "url": "https://files.example/gone.jpg"},
        {"type": "image", "url": "https://files.example/ok.jpg"},
    ])
    async with web(files) as client:
        counts = await media_worker.process_social_post(post, client=client)
    assert counts == {"downloaded": 1, "skipped": 2, "failed": 0}
    rows = {r["source_url"].rsplit("/", 1)[1]: r for r in await media_rows(db, post)}
    assert rows["huge.jpg"]["status"] == "rejected" and "larger than 10 MB" in rows["huge.jpg"]["reason"]
    assert rows["gone.jpg"]["status"] == "rejected" and rows["gone.jpg"]["reason"] == "HTTP 404"
    assert rows["ok.jpg"]["status"] == "ready"


def test_what_is_fetched_for_a_post():
    got = media_worker.social_attachments({"media": [
        {"type": "image", "url": "https://x/a.jpg"},
        {"type": "video", "url": "https://x/v.mp4", "preview_url": "https://x/v.jpg"},
        {"type": "audio", "url": "https://x/a.mp3"},
        "junk",
    ]})
    assert [(a["source_url"], a["kind"], a["role"]) for a in got] == [
        ("https://x/a.jpg", "image", "image"),
        ("https://x/v.jpg", "image", "preview"),
        ("https://x/v.mp4", "video", "video"),
    ]
    assert got[0]["limit"] == 10_000_000 and got[2]["limit"] == 50_000_000


async def test_the_backfill_run_twice_downloads_nothing_the_second_time(db, fake_store, monkeypatch):
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import backfill_social_media

    files = {f"https://files.example/{i}.jpg": encode(scene(50 + i)) for i in range(3)}
    for i in range(3):
        await social_post(db, media=[{"type": "image", "url": f"https://files.example/{i}.jpg"},
                                     {"type": "video", "url": f"https://files.example/{i}.mp4"}],
                          days_ago=3 - i)
    fetched = []

    def handler(request):
        fetched.append(str(request.url))
        body = files.get(str(request.url))
        return httpx.Response(200, content=body) if body is not None else httpx.Response(404)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient",
                        lambda **kw: real_client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(media_worker, "social_attachments", media_worker.social_attachments)

    assert await backfill_social_media.run(dry_run=False, limit=None, delay=0, images_only=True) == 0
    assert sorted(fetched) == sorted(files)  # images only: no .mp4 requested
    assert len([r for r in await media_rows(db) if r["status"] == "ready"]) == 3
    fetched.clear()
    assert await backfill_social_media.run(dry_run=False, limit=None, delay=0, images_only=True) == 0
    assert fetched == []
