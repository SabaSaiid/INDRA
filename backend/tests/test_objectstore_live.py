"""
Phase 2 T1 — the object store, against a real SeaweedFS.

Needs `indra-objectstore` running (`docker compose up -d objectstore`) and the
S3 keys in .env; skipped otherwise, so the suite still runs where there is no
store. The store-down half of T1's table (`docker stop indra-objectstore` →
/healthz degraded, reports still 202) is a live drill against the running API,
recorded in the Phase 2 file; its unit form is in test_healthz.py.

Each test uses buckets of its own, so "startup against an empty store" is
really empty, and removes them afterwards.
"""

import os
import uuid

import pytest
import pytest_asyncio

from app.core.config import get_settings
from app.services import objectstore

pytestmark = pytest.mark.objectstore


def _reachable() -> bool:
    if not objectstore.configured():
        return False
    try:
        objectstore.reset_for_tests()
        objectstore._get_client().list_buckets()
        return True
    except Exception:
        return False


if not _reachable():
    pytest.skip("no object store at S3_ENDPOINT_URL", allow_module_level=True)


def _drop_bucket(name: str) -> None:
    client = objectstore._get_client()
    try:
        for page in client.get_paginator("list_objects_v2").paginate(Bucket=name):
            for obj in page.get("Contents", []):
                client.delete_object(Bucket=name, Key=obj["Key"])
        client.delete_bucket(Bucket=name)
    except Exception:
        pass


@pytest_asyncio.fixture
async def fresh_buckets(monkeypatch):
    suffix = uuid.uuid4().hex[:8]
    settings = get_settings()
    monkeypatch.setattr(settings, "S3_LAKE_BUCKET", f"test-lake-{suffix}")
    monkeypatch.setattr(settings, "S3_MEDIA_BUCKET", f"test-media-{suffix}")
    objectstore.reset_for_tests()
    yield objectstore.buckets()
    for name in objectstore.buckets():
        _drop_bucket(name)
    objectstore.reset_for_tests()


async def test_startup_creates_both_buckets_then_nothing(fresh_buckets):
    created = await objectstore.ensure_buckets()
    assert sorted(created) == sorted(fresh_buckets)

    objectstore.reset_for_tests()  # a second process start, not a cached answer
    assert await objectstore.ensure_buckets() == []

    names = {b["Name"] for b in objectstore._get_client().list_buckets()["Buckets"]}
    assert set(fresh_buckets) <= names


async def test_one_megabyte_round_trips_byte_for_byte(fresh_buckets):
    body = os.urandom(1024 * 1024)
    lake = fresh_buckets[0]
    await objectstore.put(lake, "t1/random.bin", body)
    assert await objectstore.get(lake, "t1/random.bin") == body
    assert await objectstore.exists(lake, "t1/random.bin") is True


async def test_a_missing_key_is_none_not_an_outage(fresh_buckets):
    await objectstore.ensure_buckets()
    lake = fresh_buckets[0]
    assert await objectstore.get(lake, "no/such/key") is None
    assert await objectstore.exists(lake, "no/such/key") is False


async def test_list_keys_under_a_prefix(fresh_buckets):
    lake = fresh_buckets[0]
    for i in range(3):
        await objectstore.put(lake, f"raw/source=test/{i}.txt", b"x")
    await objectstore.put(lake, "other/0.txt", b"x")
    assert await objectstore.list_keys(lake, "raw/source=test/") == [
        f"raw/source=test/{i}.txt" for i in range(3)
    ]


async def test_ping_answers_for_the_lake_bucket(fresh_buckets):
    await objectstore.ensure_buckets()
    assert await objectstore.ping() is True


async def test_healthz_reports_the_store_up(fresh_buckets, client):
    await objectstore.ensure_buckets()
    body = (await client.get("/healthz")).json()
    assert body["checks"]["object_store"]["status"] == "up"


async def test_wrong_keys_are_an_outage_not_a_crash(fresh_buckets, monkeypatch):
    monkeypatch.setattr(get_settings(), "S3_SECRET_KEY", "wrong-" + uuid.uuid4().hex)
    objectstore.reset_for_tests()
    with pytest.raises(objectstore.ObjectStoreUnavailable):
        await objectstore.ping()
