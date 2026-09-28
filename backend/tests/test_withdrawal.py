"""
Phase 5 T5 step 4 — a citizen takes their report back
(`DELETE /api/reports/{docket}`, `app/services/withdrawal.py`).

Only the device that filed it may withdraw it. The text and exact position
are redacted, its media deleted, it leaves its event, the event is re-scored,
and the ledger records it. The row stays as a tombstone so the docket still
answers "withdrawn" and the reporter's record is not wiped. T5's rows, plus
what the code decided: withdrawing twice, a store that is down, the outbox.
"""

import json

import pytest
from sqlalchemy import text

from app.services import audit, pipeline
from app.workers import media_worker
from tests.media_support import fake_store, phone_jpeg  # noqa: F401  (fixture)
from tests.phase5_support import (  # noqa: F401  (fixtures)
    PATNA, api, broadcasts, db, device, filed, make_event, media_rows, report_row, salted, tokens,
    upload_media,
)

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(media_worker, "enqueue", lambda media_id: None)

    async def _weather(lat, lng):
        return 0.35, 15.6

    monkeypatch.setattr(pipeline, "weather_score", _weather)


async def withdraw(api, docket, n=1):
    return await api.delete(f"/api/reports/{docket}", headers=device(n) if n else {})


async def test_the_filing_device_withdraws_and_everything_personal_goes(api, db, salted, fake_store):
    report = await filed(api, 1)
    uid = await upload_media(api, phone_jpeg(1, lat=PATNA[0], lng=PATNA[1], make="x"), docket=report["docket"])
    await media_worker.process_citizen_media(uid)
    assert fake_store.keys("originals/") and fake_store.keys("derivatives/")

    r = await withdraw(api, report["docket"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["status"], body["media_deleted"], body["already"]) == ("withdrawn", 1, False)

    row = await report_row(db, report["id"])
    assert row["raw_text"] == "[withdrawn]"
    for field in ("analysis", "source_meta", "latitude", "longitude", "geom_point", "h3_res8", "event_id"):
        assert row[field] is None, field
    assert row["place_precision"] == "none" and row["withdrawn_at"] is not None
    # The tombstone keeps the docket, the time and the pseudonym.
    assert row["docket"] == report["docket"] and row["reporter_hash"] and row["created_at"]
    media = (await media_rows(db, report["id"]))[0]
    assert media["status"] == "withdrawn" and media["original_deleted_at"] and media["derivatives_deleted_at"]
    assert fake_store.keys() == []
    outbox = (await db.execute(text("SELECT payload FROM outbox WHERE key = :k"), {"k": report["id"]})).scalar()
    assert outbox["raw_text"] == "[withdrawn]" and outbox["latitude"] is None
    rows = [r for r in await audit.fetch_rows(db) if r["action_taken"] == "REPORT_WITHDRAWN"]
    await db.commit()
    assert len(rows) == 1 and rows[0]["operator_id"] == "CITIZEN"


async def test_another_device_or_no_device_is_403(api, db, salted):
    report = await filed(api, 1)
    assert (await withdraw(api, report["docket"], n=2)).status_code == 403
    assert (await withdraw(api, report["docket"], n=None)).status_code == 403
    assert (await report_row(db, report["id"]))["withdrawn_at"] is None


async def test_an_unknown_docket_is_404(api, db, salted):
    assert (await withdraw(api, "R-00000000")).status_code == 404
    assert (await withdraw(api, "nonsense")).status_code == 404


async def test_withdrawing_twice_answers_the_same_and_changes_nothing(api, db, salted):
    report = await filed(api, 1)
    assert (await withdraw(api, report["docket"])).status_code == 200
    again = await withdraw(api, report["docket"])
    assert again.status_code == 200 and again.json()["already"] is True
    ledger = [r for r in await audit.fetch_rows(db) if r["action_taken"] == "REPORT_WITHDRAWN"]
    await db.commit()
    assert len(ledger) == 1


async def test_the_docket_answers_withdrawn_and_the_lists_drop_it(api, db, salted, fake_store):
    report = await filed(api, 1)
    await filed(api, 2)
    await withdraw(api, report["docket"])
    track = await api.get(f"/api/reports/track/{report['docket']}")
    assert track.status_code == 200 and track.json()["status"] == "withdrawn"
    ids = [x["id"] for x in (await api.get("/api/reports/recent")).json()]
    assert report["id"] not in ids and len(ids) == 1
    # And no more media can be attached to it.
    r = await api.post("/api/media/uploads", json={"docket": report["docket"], "mime": "image/jpeg",
                                                   "size_bytes": 1000}, headers=device(1))
    assert r.status_code == 409 and "withdrawn" in r.json()["detail"]


async def test_its_event_is_rescored_without_it(api, db, salted, broadcasts):
    texts = ["Water entering ground floor shops near Kankarbagh main road",
             "Kankarbagh underpass completely submerged, cars stuck",
             "Knee deep water outside my house, drain overflowing",
             "Flooding on the road to Patna junction, buses diverted"]
    reports = []
    for n, t in enumerate(texts, start=1):
        reports.append(await filed(api, n, text_=t, lat=PATNA[0] + n * 0.0005))
        await pipeline.process_report(db, {"id": reports[-1]["id"]})
    event_id = str((await report_row(db, reports[0]["id"]))["event_id"])
    before = (await db.execute(text("SELECT confidence_score FROM verified_events WHERE id = CAST(:i AS uuid)"),
                               {"i": event_id})).scalar()
    await db.commit()

    r = await withdraw(api, reports[3]["docket"], n=4)
    assert r.status_code == 200 and r.json()["event_rescored"] is True

    after, receipt = (await db.execute(
        text("SELECT confidence_score, verification_receipt FROM verified_events WHERE id = CAST(:i AS uuid)"),
        {"i": event_id})).fetchone()
    count = (await db.execute(text("SELECT count(*) FROM raw_reports WHERE event_id = CAST(:i AS uuid)"),
                              {"i": event_id})).scalar()
    await db.commit()
    assert count == 3 and after != before
    assert receipt["late_corroboration"]["trigger"] == f"withdrawal:{reports[3]['id']}"
    assert receipt["density_basis"]["reports"] == 3
    assert any(m["type"] == "VERIFIED_EVENT" for m in broadcasts)
    # Withdrawn for good: the pipeline never clusters it again.
    assert await pipeline.process_report(db, {"id": reports[3]["id"]}) is None


async def test_withdrawing_a_rejected_report_keeps_its_reporters_record(api, db, tokens, salted):
    report = await filed(api, 1)
    event_id = await make_event(db, report_ids=[report["id"]])
    r = await api.patch(f"/api/events/{event_id}/review", headers=tokens["commander"],
                        json={"action": "reject", "reason": "Checked with the district control room"})
    assert r.status_code == 200
    await withdraw(api, report["docket"])
    stats = (await db.execute(text("SELECT reports, rejected FROM reporter_stats"))).fetchone()
    await db.commit()
    assert tuple(stats) == (1, 1)


async def test_a_store_that_is_down_leaves_the_files_for_retention(api, db, salted, fake_store):
    report = await filed(api, 1)
    uid = await upload_media(api, phone_jpeg(1), docket=report["docket"])
    await media_worker.process_citizen_media(uid)
    fake_store.down = True
    r = await withdraw(api, report["docket"])
    assert r.status_code == 200 and r.json()["media_deleted"] == 0
    media = (await media_rows(db, report["id"]))[0]
    assert media["status"] == "withdrawn" and media["original_deleted_at"] is None
    assert (await report_row(db, report["id"]))["raw_text"] == "[withdrawn]"


async def test_an_upload_still_in_progress_is_aborted(api, db, salted, fake_store):
    report = await filed(api, 1)
    r = await api.post("/api/media/uploads", json={"docket": report["docket"], "mime": "image/jpeg",
                                                   "size_bytes": 1000}, headers=device(1))
    assert r.status_code == 201 and len(fake_store.uploads) == 1
    await withdraw(api, report["docket"])
    assert fake_store.uploads == {}
    assert (await media_rows(db, report["id"]))[0]["status"] == "withdrawn"


async def test_the_audit_row_names_the_event_it_left(api, db, salted):
    report = await filed(api, 1)
    event_id = await make_event(db, report_ids=[report["id"]])
    await withdraw(api, report["docket"])
    row = [r for r in await audit.fetch_rows(db) if r["action_taken"] == "REPORT_WITHDRAWN"][0]
    await db.commit()
    details = row["details"] if isinstance(row["details"], dict) else json.loads(row["details"])
    assert str(row["event_id"]) == event_id
    assert details["docket"] == report["docket"] and details["event_code"].startswith("INDRA-P5-")
    assert "leaves INDRA-P5-" in row["reason"]
