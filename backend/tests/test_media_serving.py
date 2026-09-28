"""
Phase 5 T5 step 2 as re-planned (webpage.MD §8.5, B8) — serving media to
officials (`app/api/media.py`, `app/services/media_signing.py`), what the
open lists may say about media, and B9's WebSocket heartbeat.

    POST /api/media/signed-urls   ANALYST+ · {ids, size: thumb|full, original?}
    GET  /api/media/{id}/file     anyone holding an unexpired signed URL

B8's table row for row. The photos and the video are uploaded through the
real routes and processed by the real worker into the in-memory store.
"""

import io
import json
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from PIL import Image
from sqlalchemy import text

from app.core.config import get_settings
from app.services import audit
from app.services.media_signing import media_url_valid, sign_media_url
from app.workers import media_worker
from tests.media_support import (  # noqa: F401  (fixture)
    encode, exif_bytes, fake_store, make_video, needs_ffmpeg, phone_jpeg, scene,
)
from tests.phase5_support import (  # noqa: F401  (fixtures)
    PATNA, api, db, filed, media_rows, salted, tokens, upload_media,
)

SECRET = "test-media-secret"


@pytest.fixture(autouse=True)
def signing(monkeypatch):
    monkeypatch.setattr(get_settings(), "MEDIA_URL_SECRET", SECRET)
    monkeypatch.setattr(get_settings(), "PUBLIC_API_BASE", "")
    monkeypatch.setattr(media_worker, "enqueue", lambda media_id: None)


def _path(url: str) -> str:
    parts = urlparse(url)
    return f"{parts.path}?{parts.query}"


async def _ready_photo(api, n=1, **exif) -> str:
    exif = exif or {"taken": "2026:09:23 06:10:00", "offset": "+05:30", "lat": PATNA[0], "lng": PATNA[1],
                    "make": "Apple", "model": "iPhone 15"}
    uid = await upload_media(api, phone_jpeg(n, **exif), n=n)
    assert (await media_worker.process_citizen_media(uid))["status"] == "ready"
    return uid


async def _urls(api, tokens, ids, **body):
    return await api.post("/api/media/signed-urls", json={"ids": ids, **body}, headers=tokens["analyst"])


# ── Signing, pure ──────────────────────────────────────────────────────────────

def test_a_signed_url_expires_and_cannot_be_altered():
    url = sign_media_url("m1", "thumb", now=1_000_000, ttl_s=600)
    q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    assert urlparse(url).path == "/api/media/m1/file" and q["size"] == "thumb" and q["exp"] == "1000600"
    assert media_url_valid("m1", "thumb", 1000600, q["sig"], now=1_000_000)
    assert media_url_valid("m1", "thumb", 1000600, q["sig"], now=1_000_600)         # the last second
    assert not media_url_valid("m1", "thumb", 1000600, q["sig"], now=1_000_601)     # expired
    assert not media_url_valid("m1", "full", 1000600, q["sig"], now=1_000_000)      # another size
    assert not media_url_valid("m2", "thumb", 1000600, q["sig"], now=1_000_000)     # another file
    assert not media_url_valid("m1", "thumb", 1000601, q["sig"], now=1_000_000)     # a later expiry
    flipped = ("0" if q["sig"][5] != "0" else "1").join((q["sig"][:5], q["sig"][6:]))
    assert not media_url_valid("m1", "thumb", 1000600, flipped, now=1_000_000)
    assert not media_url_valid("m1", "banner", 1000600, q["sig"], now=1_000_000)


def test_a_public_base_is_prefixed(monkeypatch):
    monkeypatch.setattr(get_settings(), "PUBLIC_API_BASE", "https://indra.example/")
    assert sign_media_url("m1", "full", now=0, ttl_s=1).startswith("https://indra.example/api/media/m1/file?")


def test_without_a_secret_nothing_validates(monkeypatch):
    monkeypatch.setattr(get_settings(), "MEDIA_URL_SECRET", "")
    assert not media_url_valid("m1", "thumb", int(time.time()) + 60, "0" * 64)


@pytest.mark.parametrize(
    "header, expected",
    [(None, None), ("bytes=0-1023", (0, 1023)), ("bytes=100-", (100, 4999)), ("bytes=-100", (4900, 4999)),
     ("bytes=4000-9999", (4000, 4999)), ("bytes=5000-", "invalid"), ("bytes=9-3", "invalid"),
     ("bytes=-0", "invalid"), ("bytes=0-1,5-9", "invalid"), ("items=0-1", "invalid"), ("bytes=-", "invalid")],
)
def test_parse_range(header, expected):
    from app.api.media import parse_range

    assert parse_range(header, 5000) == expected


# ── B8's table ─────────────────────────────────────────────────────────────────

@pytest.mark.integration
async def test_signed_urls_need_an_analyst(api, db, tokens):
    body = {"ids": ["00000000-0000-0000-0000-000000000000"]}
    assert (await api.post("/api/media/signed-urls", json=body)).status_code == 401
    assert (await api.post("/api/media/signed-urls", json=body, headers=tokens["citizen"])).status_code == 403
    assert (await api.post("/api/media/signed-urls", json=body, headers=tokens["analyst"])).status_code == 200


@pytest.mark.integration
async def test_two_thumbnails_signed_for_ten_minutes(api, db, tokens, salted, fake_store):
    ids = [await _ready_photo(api, 1), await _ready_photo(api, 2)]
    before = int(time.time())
    r = await _urls(api, tokens, ids + ["not-a-uuid"], size="thumb")
    assert r.status_code == 200
    body = r.json()
    assert set(body["urls"]) == set(ids) and body["expires_in"] == 600 and body["size"] == "thumb"
    assert body["unavailable"] == {} and body["external"] == {}
    for url in body["urls"].values():
        exp = int(parse_qs(urlparse(url).query)["exp"][0])
        assert before + 600 <= exp <= int(time.time()) + 600


@pytest.mark.integration
async def test_a_thumbnail_is_320_px_jpeg_with_no_gps(api, db, tokens, salted, fake_store):
    uid = await _ready_photo(api)
    url = (await _urls(api, tokens, [uid], size="thumb")).json()["urls"][uid]
    r = await api.get(_path(url))
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert r.headers["cache-control"].startswith("private") and r.headers["x-content-type-options"] == "nosniff"
    image = Image.open(io.BytesIO(r.content))
    assert max(image.size) <= 320
    assert not image.getexif() and b"Exif" not in r.content[:4096]


@pytest.mark.integration
async def test_the_full_copy_is_at_most_1600_px_and_carries_no_exif(api, db, tokens, salted, fake_store):
    big = encode(scene(3, size=(3000, 2000)), exif=exif_bytes(lat=PATNA[0], lng=PATNA[1], make="x"))
    uid = await upload_media(api, big)
    await media_worker.process_citizen_media(uid)
    url = (await _urls(api, tokens, [uid], size="full")).json()["urls"][uid]
    r = await api.get(_path(url))
    image = Image.open(io.BytesIO(r.content))
    assert r.status_code == 200 and image.size == (1600, 1067)
    assert not image.getexif()


@pytest.mark.integration
async def test_an_expired_or_altered_url_is_403(api, db, tokens, salted, fake_store):
    uid = await _ready_photo(api)
    old = sign_media_url(uid, "thumb", now=time.time() - 700)
    assert (await api.get(_path(old))).status_code == 403
    good = (await _urls(api, tokens, [uid], size="thumb")).json()["urls"][uid]
    sig = parse_qs(urlparse(good).query)["sig"][0]
    bad = good.replace(sig, ("0" if sig[0] != "0" else "1") + sig[1:])
    assert (await api.get(_path(bad))).status_code == 403
    # A thumb URL does not open the original.
    assert (await api.get(_path(good).replace("size=thumb", "size=original"))).status_code == 403
    assert (await api.get(f"/api/media/not-a-uuid/file?size=thumb&exp=1&sig=x")).status_code == 403


@needs_ffmpeg
@pytest.mark.integration
async def test_a_video_seeks_with_a_range(api, db, tokens, salted, fake_store, tmp_path):
    from pathlib import Path

    data = Path(make_video(str(tmp_path / "v.mp4"), seconds=3)).read_bytes()
    uid = await upload_media(api, data, mime="video/mp4")
    await media_worker.process_citizen_media(uid)
    url = (await _urls(api, tokens, [uid], size="full")).json()["urls"][uid]
    size = len(fake_store.body((await media_rows(db))[0]["derivative_key"]))
    r = await api.get(_path(url), headers={"Range": "bytes=0-1023"})
    assert r.status_code == 206 and len(r.content) == 1024
    assert r.headers["content-range"] == f"bytes 0-1023/{size}"
    assert r.headers["content-type"] == "video/mp4" and r.headers["accept-ranges"] == "bytes"
    tail = await api.get(_path(url), headers={"Range": "bytes=-10"})
    assert tail.status_code == 206 and tail.headers["content-range"] == f"bytes {size - 10}-{size - 1}/{size}"
    past = await api.get(_path(url), headers={"Range": f"bytes={size}-"})
    assert past.status_code == 416 and past.headers["content-range"] == f"bytes */{size}"
    thumb = (await _urls(api, tokens, [uid], size="thumb")).json()["urls"][uid]
    assert (await api.get(_path(thumb))).headers["content-type"] == "image/jpeg"


@pytest.mark.integration
async def test_an_original_is_linked_to_an_analyst_and_audited(api, db, tokens, salted, fake_store):
    uid = await _ready_photo(api)
    r = await _urls(api, tokens, [uid], original=True)
    assert r.status_code == 200 and r.json()["size"] == "original"
    got = await api.get(_path(r.json()["urls"][uid]))
    assert got.status_code == 200 and Image.open(io.BytesIO(got.content)).getexif()  # EXIF and GPS kept
    rows = [row for row in await audit.fetch_rows(db) if row["action_taken"] == "MEDIA_ORIGINAL_ACCESS"]
    await db.commit()
    assert len(rows) == 1
    assert rows[0]["operator_id"] == "OP-ANL-001"
    details = rows[0]["details"] if isinstance(rows[0]["details"], dict) else json.loads(rows[0]["details"])
    assert details["media_ids"] == [uid]


@pytest.mark.integration
async def test_no_audit_row_no_original(api, db, tokens, salted, fake_store, monkeypatch):
    uid = await _ready_photo(api)

    async def broken(*a, **k):
        raise RuntimeError("ledger unavailable")

    monkeypatch.setattr(audit, "record", broken)
    r = await _urls(api, tokens, [uid], original=True)
    assert r.status_code == 503 and "could not be recorded" in r.json()["detail"]
    # Thumbnails need no ledger row.
    assert (await _urls(api, tokens, [uid], size="thumb")).status_code == 200


@pytest.mark.integration
async def test_media_not_ready_or_past_retention_is_listed_unavailable(api, db, tokens, salted, fake_store):
    waiting = await upload_media(api, phone_jpeg(1))
    done = await _ready_photo(api, 2)
    url = (await _urls(api, tokens, [done], size="thumb")).json()["urls"][done]
    await db.execute(text("UPDATE report_media SET derivatives_deleted_at = NOW() WHERE id = CAST(:id AS uuid)"),
                     {"id": done})
    await db.commit()
    body = (await _urls(api, tokens, [waiting, done], size="thumb")).json()
    assert body["urls"] == {}
    assert body["unavailable"][waiting] == "media is processing"
    assert "not held" in body["unavailable"][done]
    assert (await api.get(_path(url))).status_code == 404  # a URL minted before retention ran


@pytest.mark.integration
async def test_without_a_secret_serving_is_503(api, db, tokens, salted, fake_store, monkeypatch):
    uid = await _ready_photo(api)
    monkeypatch.setattr(get_settings(), "MEDIA_URL_SECRET", "")
    r = await _urls(api, tokens, [uid])
    assert r.status_code == 503 and "MEDIA_URL_SECRET" in r.json()["detail"]


@pytest.mark.integration
async def test_a_mastodon_attachment_is_linked_to_its_author_never_served(api, db, tokens, fake_store):
    import uuid

    from app.services import clock

    post = str(uuid.uuid4())
    await db.execute(
        text("""
            INSERT INTO raw_reports (id, source_type, raw_text, source_meta, observed_at, created_at, platform,
                                     place_precision, reporter_hash, credibility_score, flags)
            VALUES (CAST(:id AS uuid), 'SOCIAL_MEDIA', 'Flooding #IMD', CAST(:meta AS jsonb), :at, :at,
                    'mastodon', 'none', 'author-a', 0.4, '{}')
        """),
        {"id": post, "at": clock.now(),
         "meta": json.dumps({"media": [{"type": "image", "url": "https://files.example/p.jpg"}]})},
    )
    await db.commit()
    photo = encode(scene(42))
    handler = lambda request: httpx.Response(200, content=photo)  # noqa: E731
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await media_worker.process_social_post(post, client=client)
    mid = str((await media_rows(db, post))[0]["id"])

    body = (await _urls(api, tokens, [mid], size="full")).json()
    assert body["urls"][mid] == "https://files.example/p.jpg" and body["external"] == {mid: True}
    # Even a correctly signed URL does not serve INDRA's private copy.
    assert (await api.get(_path(sign_media_url(mid, "original")))).status_code == 404


@pytest.mark.integration
async def test_the_open_report_list_carries_media_ids_never_urls(api, db, salted, fake_store):
    uid = await _ready_photo(api)
    r = await api.get("/api/reports/recent")
    assert r.status_code == 200
    mine = [x for x in r.json() if x["media_count"]]
    assert len(mine) == 1
    assert mine[0]["media_kinds"] == ["image"] and mine[0]["media_ids"] == [uid]
    media_fields = {k: v for k, v in mine[0].items() if k.startswith("media")}
    assert "http" not in json.dumps(media_fields)
    others = [x for x in r.json() if not x["media_count"]]
    assert all(x["media_ids"] == [] and x["media_kinds"] == [] for x in others)


# ── B9: the WebSocket heartbeat ────────────────────────────────────────────────

def test_a_ping_gets_a_pong_and_anything_else_is_ignored():
    from starlette.testclient import TestClient

    from app.main import app

    client = TestClient(app)  # no `with`: the lifespan (pollers, Kafka) does not start
    with client.websocket_connect("/ws/events") as ws:
        ws.send_text(json.dumps({"type": "ping"}))
        assert ws.receive_json() == {"type": "pong"}
        ws.send_text("hello")                          # not JSON: ignored
        ws.send_text(json.dumps({"type": "subscribe"}))  # JSON, not a ping: ignored
        ws.send_text(json.dumps(["ping"]))
        ws.send_text(json.dumps({"type": "ping"}))
        assert ws.receive_json() == {"type": "pong"}   # the socket is still open
