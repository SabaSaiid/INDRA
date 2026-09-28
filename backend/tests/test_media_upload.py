"""
Phase 5 T1 as re-planned (webpage.MD §8.3, B6) — resumable photo and video
uploads (`app/api/media.py`), and `scripts/cleanup_uploads.py`.

    POST /api/media/uploads                          start: {docket, mime, size_bytes}
    PUT  /api/media/uploads/{upload_id}/parts/{n}    the raw bytes of part n
    GET  /api/media/uploads/{upload_id}              which parts arrived
    POST /api/media/uploads/{upload_id}/complete     all parts in → processing

B6's table row for row, against the in-memory object store of
`media_support.FakeS3`, which records every part the API sends. A report is
filed through the real route by a numbered device first.
"""

import sys
from pathlib import Path

import pytest
from sqlalchemy import text

from app.services.media_types import CHUNK_SIZE
from app.workers import media_worker
from tests.media_support import fake_store, phone_jpeg  # noqa: F401  (fixture)
from tests.phase5_support import api, db, device, filed, media_rows, salted  # noqa: F401  (fixtures)

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
EXE = b"MZ\x90\x00" + bytes(12)
MP4_HEAD = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00"


@pytest.fixture(autouse=True)
def queued(monkeypatch):
    """What the upload route hands to the media worker, instead of processing it here."""
    handed = []
    monkeypatch.setattr(media_worker, "enqueue", lambda media_id: handed.append(str(media_id)))
    return handed


def padded(head: bytes, size: int) -> bytes:
    return head + bytes(size - len(head))


async def start(api, docket, n=1, mime="image/jpeg", size=3_000_000):
    return await api.post("/api/media/uploads", json={"docket": docket, "mime": mime, "size_bytes": size},
                          headers=device(n))


async def put(api, upload_id, part, body, n=1):
    return await api.put(f"/api/media/uploads/{upload_id}/parts/{part}", content=body,
                         headers={**device(n), "Content-Type": "application/octet-stream"})


async def _started(api, n=1, **kw):
    report = await filed(api, n)
    r = await start(api, report["docket"], n, **kw)
    assert r.status_code == 201, r.text
    return report, r.json()


# ── Start ──────────────────────────────────────────────────────────────────────

async def test_start_opens_a_session_for_the_filing_device(api, db, salted, fake_store):
    report, body = await _started(api)
    assert body["chunk_size"] == 5_242_880 and body["parts"] == 1 and body["kind"] == "image"
    assert body["upload_id"] == body["media_id"]
    rows = await media_rows(db, report["id"])
    assert len(rows) == 1
    row = rows[0]
    assert (row["status"], row["origin"], row["declared_size"], row["declared_mime"]) == (
        "uploading", "citizen", 3_000_000, "image/jpeg")
    assert row["incoming_key"] == f"incoming/{body['upload_id']}"
    assert row["s3_upload_id"] in fake_store.uploads


async def test_another_device_cannot_attach(api, db, salted, fake_store):
    report = await filed(api, 1)
    assert (await start(api, report["docket"], n=2)).status_code == 403
    r = await api.post("/api/media/uploads", json={"docket": report["docket"], "mime": "image/jpeg",
                                                   "size_bytes": 10})
    assert r.status_code == 403  # no X-Reporter-Id at all
    assert await media_rows(db) == []


async def test_a_report_with_no_owner_takes_no_media(api, db, fake_store, monkeypatch):
    """Stored without a reporter hash (no REPORTER_SALT): nobody can prove it is theirs."""
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "REPORTER_SALT", "")
    report = await filed(api, 1)
    monkeypatch.setattr(get_settings(), "REPORTER_SALT", "test-salt")
    assert (await start(api, report["docket"])).status_code == 403


async def test_an_unknown_docket_is_404(api, db, salted, fake_store):
    assert (await start(api, "R-00000000")).status_code == 404
    assert (await start(api, "not a docket")).status_code == 404


async def test_25_hours_after_the_report_the_window_is_shut(api, db, salted, fake_store):
    report = await filed(api, 1)
    await db.execute(text("UPDATE raw_reports SET created_at = NOW() - interval '25 hours' "
                          "WHERE docket = :d"), {"d": report["docket"]})
    await db.commit()
    r = await start(api, report["docket"])
    assert r.status_code == 409 and "24 hours" in r.json()["detail"]


@pytest.mark.parametrize("mime, size", [("image/jpeg", 11_000_000), ("video/mp4", 51_000_000)])
async def test_a_file_over_its_limit_is_413(api, db, salted, fake_store, mime, size):
    report = await filed(api, 1)
    r = await start(api, report["docket"], mime=mime, size=size)
    assert r.status_code == 413
    assert "11 MB" in r.json()["detail"] or "51 MB" in r.json()["detail"]


async def test_a_fifth_file_is_413(api, db, salted, fake_store):
    report = await filed(api, 1)
    for _ in range(4):
        assert (await start(api, report["docket"], size=1000)).status_code == 201
    r = await start(api, report["docket"], size=1000)
    assert r.status_code == 413 and "at most 4 files" in r.json()["detail"]


async def test_files_adding_up_to_more_than_80_mb_are_413(api, db, salted, fake_store):
    report = await filed(api, 1)
    assert (await start(api, report["docket"], mime="video/mp4", size=50_000_000)).status_code == 201
    r = await start(api, report["docket"], mime="video/mp4", size=31_000_000)
    assert r.status_code == 413 and "80 MB" in r.json()["detail"]
    assert (await start(api, report["docket"], mime="video/mp4", size=30_000_000)).status_code == 201


async def test_a_rejected_file_no_longer_counts_towards_the_four(api, db, salted, fake_store):
    report = await filed(api, 1)
    ids = [(await start(api, report["docket"], size=1000)).json()["upload_id"] for _ in range(4)]
    assert (await put(api, ids[0], 1, padded(EXE, 1000))).status_code == 415
    assert (await start(api, report["docket"], size=1000)).status_code == 201


async def test_a_pdf_is_415(api, db, salted, fake_store):
    report = await filed(api, 1)
    assert (await start(api, report["docket"], mime="application/pdf", size=1000)).status_code == 415


async def test_a_12_mb_video_is_three_parts(api, db, salted, fake_store):
    _, body = await _started(api, mime="video/mp4", size=12_000_000)
    assert body["parts"] == 3 and body["kind"] == "video"


# ── Parts ──────────────────────────────────────────────────────────────────────

async def test_an_exe_is_refused_on_its_first_part(api, db, salted, fake_store):
    report, body = await _started(api, size=1000)
    upload = (await media_rows(db, report["id"]))[0]["s3_upload_id"]
    r = await put(api, body["upload_id"], 1, padded(EXE, 1000))
    assert r.status_code == 415
    assert upload not in fake_store.uploads  # the multipart upload aborted
    row = (await media_rows(db, report["id"]))[0]
    assert row["status"] == "rejected" and "not a photo or video" in row["reason"]
    # The upload is over: nothing more is accepted.
    assert (await put(api, body["upload_id"], 1, bytes(1000))).status_code == 409


async def test_a_video_sent_where_a_photo_was_declared_is_refused(api, db, salted, fake_store):
    report, body = await _started(api, size=1000)
    assert (await put(api, body["upload_id"], 1, padded(MP4_HEAD, 1000))).status_code == 415
    assert "a video, not a photo" in (await media_rows(db, report["id"]))[0]["reason"]


async def test_part_one_records_the_real_type(api, db, salted, fake_store):
    jpeg = phone_jpeg()
    report, body = await _started(api, size=len(jpeg))
    r = await put(api, body["upload_id"], 1, jpeg)
    assert r.status_code == 200 and r.json()["n"] == 1 and r.json()["etag"]
    assert (await media_rows(db, report["id"]))[0]["mime"] == "image/jpeg"


async def test_a_part_sent_twice_is_stored_once(api, db, salted, fake_store):
    _, body = await _started(api, mime="video/mp4", size=12_000_000)
    uid = body["upload_id"]
    assert (await put(api, uid, 1, padded(MP4_HEAD, CHUNK_SIZE))).status_code == 200
    part2 = bytes(range(256)) * (CHUNK_SIZE // 256)
    assert (await put(api, uid, 2, part2)).status_code == 200
    assert (await put(api, uid, 2, part2)).status_code == 200
    upload = next(iter(fake_store.uploads.values()))
    assert sorted(upload["parts"]) == [1, 2]
    assert fake_store.part_puts == 3


async def test_a_part_bigger_than_5_mib_is_413(api, db, salted, fake_store):
    _, body = await _started(api, mime="video/mp4", size=12_000_000)
    r = await put(api, body["upload_id"], 1, padded(MP4_HEAD, CHUNK_SIZE + 1))
    assert r.status_code == 413
    assert fake_store.part_puts == 0


async def test_a_part_of_the_wrong_length_or_number_is_422(api, db, salted, fake_store):
    _, body = await _started(api, mime="video/mp4", size=12_000_000)
    uid = body["upload_id"]
    assert (await put(api, uid, 1, padded(MP4_HEAD, 1000))).status_code == 422
    assert (await put(api, uid, 3, bytes(1000))).status_code == 422          # the last is 1,514,240
    assert (await put(api, uid, 0, bytes(10))).status_code == 422
    assert (await put(api, uid, 4, bytes(10))).status_code == 422
    assert (await put(api, uid, 3, bytes(1_514_240))).status_code == 200


async def test_only_the_filing_device_may_send_parts(api, db, salted, fake_store):
    _, body = await _started(api, size=1000)
    assert (await put(api, body["upload_id"], 1, bytes(1000), n=2)).status_code == 403
    assert (await api.get(f"/api/media/uploads/{body['upload_id']}", headers=device(2))).status_code == 403
    assert (await api.get("/api/media/uploads/not-a-uuid", headers=device(1))).status_code == 404


async def test_the_state_lists_the_parts_that_arrived(api, db, salted, fake_store):
    _, body = await _started(api, mime="video/mp4", size=12_000_000)
    uid = body["upload_id"]
    await put(api, uid, 1, padded(MP4_HEAD, CHUNK_SIZE))
    await put(api, uid, 3, bytes(1_514_240))
    r = await api.get(f"/api/media/uploads/{uid}", headers=device(1))
    assert r.status_code == 200
    assert r.json()["received_parts"] == [1, 3]
    assert (r.json()["status"], r.json()["parts"]) == ("uploading", 3)


# ── Complete ───────────────────────────────────────────────────────────────────

async def test_complete_with_a_part_missing_is_409_naming_it(api, db, salted, fake_store, queued):
    _, body = await _started(api, mime="video/mp4", size=12_000_000)
    uid = body["upload_id"]
    await put(api, uid, 1, padded(MP4_HEAD, CHUNK_SIZE))
    await put(api, uid, 3, bytes(1_514_240))
    r = await api.post(f"/api/media/uploads/{uid}/complete", headers=device(1))
    assert r.status_code == 409 and r.json()["missing_parts"] == [2]
    assert queued == []


async def test_complete_joins_the_parts_and_hands_the_file_to_the_worker(api, db, salted, fake_store, queued):
    report, body = await _started(api, mime="video/mp4", size=12_000_000)
    uid = body["upload_id"]
    parts = [padded(MP4_HEAD, CHUNK_SIZE), b"\x01" * CHUNK_SIZE, b"\x02" * 1_514_240]
    for n, part in enumerate(parts, start=1):
        assert (await put(api, uid, n, part)).status_code == 200
    r = await api.post(f"/api/media/uploads/{uid}/complete", headers=device(1))
    assert r.status_code == 202 and r.json() == {"media_id": uid, "status": "processing"}
    assert fake_store.body(f"incoming/{uid}") == b"".join(parts)
    assert fake_store.uploads == {}
    row = (await media_rows(db, report["id"]))[0]
    assert (row["status"], row["bytes"]) == ("processing", 12_000_000)
    assert queued == [uid]
    # Completing again answers the same, and hands nothing over twice.
    again = await api.post(f"/api/media/uploads/{uid}/complete", headers=device(1))
    assert again.status_code == 202 and again.json()["status"] == "processing"
    assert queued == [uid]
    state = (await api.get(f"/api/media/uploads/{uid}", headers=device(1))).json()
    assert state["received_parts"] == [1, 2, 3]
    # A finished upload takes no more parts.
    assert (await put(api, uid, 1, parts[0])).status_code == 409


async def test_a_complete_whose_row_update_was_lost_finishes_on_retry(api, db, salted, fake_store, queued):
    """The store joined the parts but the row still says uploading: complete again finishes it."""
    jpeg = phone_jpeg()
    report, body = await _started(api, size=len(jpeg))
    uid = body["upload_id"]
    await put(api, uid, 1, jpeg)
    from app.core.config import get_settings

    fake_store.complete_multipart_upload(Bucket=get_settings().S3_MEDIA_BUCKET, Key=f"incoming/{uid}",
                                         UploadId=(await media_rows(db, report["id"]))[0]["s3_upload_id"],
                                         MultipartUpload={"Parts": [{"PartNumber": 1}]})
    r = await api.post(f"/api/media/uploads/{uid}/complete", headers=device(1))
    assert r.status_code == 202 and queued == [uid]


# ── The store down ─────────────────────────────────────────────────────────────

async def test_a_stopped_store_is_503_and_the_report_is_unaffected(api, db, salted, fake_store):
    report = await filed(api, 1)
    fake_store.down = True
    r = await start(api, report["docket"])
    assert r.status_code == 503 and r.json()["detail"] == "media_store_unavailable"
    assert await media_rows(db, report["id"]) == []
    track = await api.get(f"/api/reports/track/{report['docket']}")
    assert track.status_code == 200 and track.json()["docket"] == report["docket"]


async def test_a_store_that_stops_mid_upload_is_503_and_the_part_can_be_resent(api, db, salted, fake_store):
    jpeg = phone_jpeg()
    _, body = await _started(api, size=len(jpeg))
    fake_store.down = True
    assert (await put(api, body["upload_id"], 1, jpeg)).status_code == 503
    fake_store.down = False
    assert (await put(api, body["upload_id"], 1, jpeg)).status_code == 200


# ── Abandoned uploads ──────────────────────────────────────────────────────────

async def test_cleanup_aborts_a_session_left_for_25_hours(api, db, salted, fake_store):
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import cleanup_uploads

    report, old = await _started(api, size=1000)
    _, fresh = await _started(api, n=2, size=1000)
    await db.execute(text("UPDATE report_media SET created_at = NOW() - interval '25 hours' "
                          "WHERE id = CAST(:id AS uuid)"), {"id": old["upload_id"]})
    await db.commit()
    assert len(fake_store.uploads) == 2

    assert await cleanup_uploads.run(dry_run=True) == 0
    assert len(fake_store.uploads) == 2  # a dry run changes nothing
    assert await cleanup_uploads.run(dry_run=False) == 0

    assert len(fake_store.uploads) == 1
    rows = {str(r["id"]): r for r in await media_rows(db)}
    assert (rows[old["upload_id"]]["status"], rows[old["upload_id"]]["reason"]) == ("rejected", "abandoned")
    assert rows[fresh["upload_id"]]["status"] == "uploading"
    assert await cleanup_uploads.run(dry_run=False) == 0  # idempotent


async def test_cleanup_with_the_store_down_changes_nothing_and_fails(api, db, salted, fake_store):
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import cleanup_uploads

    _, old = await _started(api, size=1000)
    await db.execute(text("UPDATE report_media SET created_at = NOW() - interval '25 hours'"))
    await db.commit()
    fake_store.down = True
    assert await cleanup_uploads.run(dry_run=False) == 1
    assert (await media_rows(db))[0]["status"] == "uploading"
