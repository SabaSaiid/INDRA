"""
Phase 5 T5 step 3 — media retention under the DPDP Act 2023
(`scripts/retention.py`).

| what                                | kept for |
|-------------------------------------|----------|
| a citizen's original                | 90 days, unless its report is in a HUMAN_APPROVED event |
| the EXIF-free copy and thumbnail    | 180 days |
| a social post's private copy        | 30 days  |
| media of a withdrawn report         | deleted at once (this run finishes what the withdrawal could not) |

Only the files go: each row keeps its hashes and is stamped. T5's rows, the
boundaries, idempotence and a store that is down.
"""

import sys
from pathlib import Path

import pytest
from sqlalchemy import text

from app.workers import media_worker
from tests.media_support import fake_store, phone_jpeg  # noqa: F401  (fixture)
from tests.phase5_support import api, db, filed, make_event, media_rows, salted, upload_media  # noqa: F401

pytestmark = pytest.mark.integration

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import retention  # noqa: E402


@pytest.fixture(autouse=True)
def no_queue(monkeypatch):
    monkeypatch.setattr(media_worker, "enqueue", lambda media_id: None)


async def ready(api, n=1, docket=None) -> str:
    uid = await upload_media(api, phone_jpeg(n), n=n, docket=docket)
    assert (await media_worker.process_citizen_media(uid))["status"] == "ready"
    return uid


async def age(db, media_id, days):
    await db.execute(text("UPDATE report_media SET created_at = NOW() - make_interval(days => :d) "
                          "WHERE id = CAST(:id AS uuid)"), {"d": days, "id": media_id})
    await db.commit()


async def row(db, media_id):
    r = (await db.execute(text("SELECT * FROM report_media WHERE id = CAST(:id AS uuid)"),
                          {"id": media_id})).fetchone()
    await db.commit()
    return dict(r._mapping)


async def test_a_91_day_old_original_goes_and_its_copies_stay(api, db, salted, fake_store):
    old, fresh = await ready(api, 1), await ready(api, 2)
    await age(db, old, 91)
    await age(db, fresh, 89)
    assert await retention.run(dry_run=False) == 0

    gone, kept = await row(db, old), await row(db, fresh)
    assert gone["original_deleted_at"] is not None and gone["derivatives_deleted_at"] is None
    assert gone["object_key"] not in fake_store.keys() and gone["thumb_key"] in fake_store.keys()
    assert gone["sha256"] and gone["phash"] is not None  # the hashes stay
    assert kept["original_deleted_at"] is None and kept["object_key"] in fake_store.keys()


async def test_an_original_in_a_human_approved_event_is_kept(api, db, salted, fake_store):
    report = await filed(api, 1)
    uid = await ready(api, 1, docket=report["docket"])
    await make_event(db, status="HUMAN_APPROVED", report_ids=[report["id"]])
    await age(db, uid, 91)
    assert await retention.run(dry_run=False) == 0
    assert (await row(db, uid))["original_deleted_at"] is None


async def test_copies_go_after_180_days(api, db, salted, fake_store):
    uid = await ready(api)
    await age(db, uid, 181)
    await retention.run(dry_run=False)
    r = await row(db, uid)
    assert r["original_deleted_at"] and r["derivatives_deleted_at"]
    assert fake_store.keys() == []


async def test_media_a_withdrawal_could_not_delete_is_finished_here(api, db, salted, fake_store):
    report = await filed(api, 1)
    uid = await ready(api, 1, docket=report["docket"])
    await db.execute(text("UPDATE report_media SET status = 'withdrawn' WHERE id = CAST(:id AS uuid)"), {"id": uid})
    await db.commit()
    await retention.run(dry_run=False)
    r = await row(db, uid)
    assert r["original_deleted_at"] and r["derivatives_deleted_at"] and fake_store.keys() == []


async def test_social_copies_go_after_30_days(db, fake_store):
    import uuid

    from app.core.config import get_settings

    bucket = get_settings().S3_MEDIA_BUCKET
    for days, key in ((31, "social/old.jpg"), (29, "social/new.jpg")):
        rid = uuid.uuid4()
        await db.execute(text("""
            INSERT INTO raw_reports (id, source_type, raw_text, place_precision, platform)
            VALUES (:id, 'SOCIAL_MEDIA', 'Flooding #IMD', 'none', 'mastodon')
        """), {"id": rid})
        await db.execute(text("""
            INSERT INTO report_media (id, report_id, origin, kind, status, object_key, source_url, created_at)
            VALUES (gen_random_uuid(), :rid, 'social', 'image', 'ready', :key, :url,
                    NOW() - make_interval(days => :d))
        """), {"rid": rid, "key": key, "url": f"https://files.example/{key}", "d": days})
        fake_store.put_object(Bucket=bucket, Key=key, Body=b"x")
    await db.commit()
    await retention.run(dry_run=False)
    assert fake_store.keys("social/") == ["social/new.jpg"]


async def test_a_dry_run_and_a_second_run_delete_nothing(api, db, salted, fake_store, capsys):
    uid = await ready(api)
    await age(db, uid, 91)
    held = fake_store.keys()
    assert await retention.run(dry_run=True) == 0
    assert fake_store.keys() == held and "citizen originals: 1 past retention" in capsys.readouterr().out
    await retention.run(dry_run=False)
    capsys.readouterr()
    await retention.run(dry_run=False)
    out = capsys.readouterr().out
    assert "citizen originals: 0 past retention" in out and "deleted 1" not in out


async def test_a_store_that_is_down_fails_the_run_and_stamps_nothing(api, db, salted, fake_store):
    uid = await ready(api)
    await age(db, uid, 91)
    fake_store.down = True
    assert await retention.run(dry_run=False) == 1
    assert (await row(db, uid))["original_deleted_at"] is None
