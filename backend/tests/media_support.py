"""
Phase 5 test support: photos, videos and an object store, all made in the test.

* **Pictures** are drawn with Pillow from a seed, so they have the structure a
  perceptual hash needs (a flat colour hashes to almost nothing) and the same
  seed always draws the same picture. EXIF is written with piexif.
* **Videos** are made with ffmpeg's built-in test source; tests that need one
  are skipped with a reason when ffmpeg is not installed.
* **FakeS3** is an in-memory stand-in for the boto3 client, injected with
  `objectstore.reset_for_tests(client=...)`, so the real `objectstore`
  functions run against it: multipart uploads, ranged reads and a store that
  can be "stopped".

Nothing here is a real photo of anything; every picture is synthetic.
"""

import hashlib
import io
import random
import shutil
import subprocess
import uuid
from typing import Dict, Optional, Tuple

import pytest

ffmpeg_missing = shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None
needs_ffmpeg = pytest.mark.skipif(ffmpeg_missing, reason="ffmpeg/ffprobe not installed (Phase 5 T0)")


# ── Pictures ───────────────────────────────────────────────────────────────────

def scene(seed: int, size: Tuple[int, int] = (640, 480)):
    """A deterministic picture: a sky gradient, a skyline and water, varied by seed."""
    from PIL import Image, ImageDraw

    rng = random.Random(seed)
    width, height = size
    image = Image.new("RGB", size)
    draw = ImageDraw.Draw(image)
    top = [rng.randint(60, 200) for _ in range(3)]
    for y in range(height):
        f = y / height
        draw.line([(0, y), (width, y)], fill=tuple(int(c * (1 - f) + 40 * f) for c in top))
    for _ in range(rng.randint(8, 16)):
        x0, y0 = rng.randint(0, width - 40), rng.randint(0, height - 40)
        x1, y1 = x0 + rng.randint(30, width // 2), y0 + rng.randint(30, height // 2)
        colour = tuple(rng.randint(0, 255) for _ in range(3))
        if rng.random() < 0.5:
            draw.rectangle([x0, y0, x1, y1], fill=colour)
        else:
            draw.ellipse([x0, y0, x1, y1], fill=colour)
    return image


def encode(image, fmt: str = "JPEG", quality: int = 90, exif: Optional[bytes] = None) -> bytes:
    out = io.BytesIO()
    kwargs = {"quality": quality} if fmt in ("JPEG", "WEBP", "HEIF") else {}
    if exif is not None:
        kwargs["exif"] = exif
    if fmt == "HEIF":
        from pillow_heif import register_heif_opener

        register_heif_opener()
    image.save(out, format=fmt, **kwargs)
    return out.getvalue()


def _dms(value: float):
    value = abs(value)
    degrees = int(value)
    minutes = int((value - degrees) * 60)
    seconds = round(((value - degrees) * 60 - minutes) * 60 * 10000)
    return ((degrees, 1), (minutes, 1), (seconds, 10000))


def exif_bytes(
    *,
    taken: Optional[str] = None,
    offset: Optional[str] = None,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    make: Optional[str] = None,
    model: Optional[str] = None,
    software: Optional[str] = None,
    orientation: Optional[int] = None,
) -> bytes:
    """An EXIF block as a phone writes one. `taken` is EXIF's "YYYY:MM:DD HH:MM:SS"."""
    import piexif

    zeroth: Dict[int, object] = {}
    exif: Dict[int, object] = {}
    gps: Dict[int, object] = {}
    if make:
        zeroth[piexif.ImageIFD.Make] = make
    if model:
        zeroth[piexif.ImageIFD.Model] = model
    if software:
        zeroth[piexif.ImageIFD.Software] = software
    if orientation:
        zeroth[piexif.ImageIFD.Orientation] = orientation
    if taken:
        exif[piexif.ExifIFD.DateTimeOriginal] = taken
    if offset:
        exif[piexif.ExifIFD.OffsetTimeOriginal] = offset
    if lat is not None and lng is not None:
        gps[piexif.GPSIFD.GPSLatitudeRef] = "N" if lat >= 0 else "S"
        gps[piexif.GPSIFD.GPSLatitude] = _dms(lat)
        gps[piexif.GPSIFD.GPSLongitudeRef] = "E" if lng >= 0 else "W"
        gps[piexif.GPSIFD.GPSLongitude] = _dms(lng)
    return piexif.dump({"0th": zeroth, "Exif": exif, "GPS": gps, "1st": {}, "thumbnail": None})


def phone_jpeg(seed: int = 1, quality: int = 90, **exif) -> bytes:
    """A JPEG with the EXIF given (none if no keyword is passed)."""
    return encode(scene(seed), "JPEG", quality, exif_bytes(**exif) if exif else None)


# ── Videos ─────────────────────────────────────────────────────────────────────

def make_video(
    path: str,
    *,
    seconds: float = 3.0,
    creation_time: Optional[str] = None,
    location: Optional[str] = None,
    size: str = "320x240",
    image_path: Optional[str] = None,
) -> str:
    """
    A small H.264 MP4 at `path`. `creation_time` is ISO 8601 ("2026-09-23T00:40:00Z");
    `location` is ISO 6709 ("+25.6000+085.1000/"). With `image_path` the video
    shows that picture throughout (a clip that reuses an old photo).
    """
    if image_path:
        source = ["-loop", "1", "-i", image_path]
        vf = ["-vf", f"scale={size.replace('x', ':')}"]
    else:
        source = ["-f", "lavfi", "-i", f"testsrc2=size={size}:rate=10"]
        vf = []
    meta = []
    if creation_time:
        meta += ["-metadata", f"creation_time={creation_time}"]
    if location:
        meta += ["-metadata", f"location={location}"]
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", *source, "-t", str(seconds), *vf,
         "-c:v", "libx264", "-pix_fmt", "yuv420p", *meta, path],
        check=True, capture_output=True, timeout=60,
    )
    return path


def ffprobe_tags(path: str) -> Dict[str, str]:
    """Every format and stream tag ffprobe reports, lower-cased keys."""
    import json

    done = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
        check=True, capture_output=True, timeout=30,
    )
    probe = json.loads(done.stdout)
    tags: Dict[str, str] = {}
    for source in [probe.get("format") or {}, *(probe.get("streams") or [])]:
        for k, v in (source.get("tags") or {}).items():
            tags[k.lower()] = v
    return tags


# ── An object store in memory ──────────────────────────────────────────────────

def _client_error(code: str, status: int, op: str):
    from botocore.exceptions import ClientError

    return ClientError({"Error": {"Code": code, "Message": code},
                        "ResponseMetadata": {"HTTPStatusCode": status}}, op)


class FakeS3:
    """The subset of boto3's S3 client that services/objectstore.py calls."""

    def __init__(self):
        self.buckets = set()
        self.objects: Dict[Tuple[str, str], Tuple[bytes, str]] = {}
        self.uploads: Dict[str, Dict[str, object]] = {}
        self.down = False
        self.part_puts = 0

    def _up(self):
        if self.down:
            raise ConnectionError("the object store is stopped")

    # buckets
    def head_bucket(self, Bucket):
        self._up()
        if Bucket not in self.buckets:
            raise _client_error("404", 404, "HeadBucket")

    def create_bucket(self, Bucket):
        self._up()
        self.buckets.add(Bucket)

    # objects
    def put_object(self, Bucket, Key, Body, ContentType="application/octet-stream", **_):
        self._up()
        self.objects[(Bucket, Key)] = (bytes(Body), ContentType)
        return {"ETag": f'"{hashlib.md5(bytes(Body)).hexdigest()}"'}

    def head_object(self, Bucket, Key):
        self._up()
        if (Bucket, Key) not in self.objects:
            raise _client_error("404", 404, "HeadObject")
        body, ctype = self.objects[(Bucket, Key)]
        return {"ContentLength": len(body), "ContentType": ctype}

    def get_object(self, Bucket, Key, Range=None):
        self._up()
        if (Bucket, Key) not in self.objects:
            raise _client_error("NoSuchKey", 404, "GetObject")
        body, ctype = self.objects[(Bucket, Key)]
        total = len(body)
        if Range:
            first, _, last = Range.removeprefix("bytes=").partition("-")
            start, end = int(first), (int(last) if last else total - 1)
            chunk = body[start:end + 1]
            return {"Body": io.BytesIO(chunk), "ContentLength": len(chunk),
                    "ContentRange": f"bytes {start}-{end}/{total}", "ContentType": ctype}
        return {"Body": io.BytesIO(body), "ContentLength": total, "ContentType": ctype}

    def delete_object(self, Bucket, Key):
        self._up()
        self.objects.pop((Bucket, Key), None)

    def download_file(self, Bucket, Key, Filename):
        self._up()
        if (Bucket, Key) not in self.objects:
            raise _client_error("404", 404, "HeadObject")
        with open(Filename, "wb") as f:
            f.write(self.objects[(Bucket, Key)][0])

    def upload_file(self, Filename, Bucket, Key, ExtraArgs=None):
        self._up()
        with open(Filename, "rb") as f:
            self.objects[(Bucket, Key)] = (f.read(), (ExtraArgs or {}).get("ContentType", ""))

    def list_objects_v2(self, Bucket, Prefix="", MaxKeys=1000, **_):
        self._up()
        keys = sorted(k for b, k in self.objects if b == Bucket and k.startswith(Prefix))
        return {"Contents": [{"Key": k} for k in keys[:MaxKeys]], "IsTruncated": False}

    # multipart
    def _upload(self, UploadId, op):
        if UploadId not in self.uploads:
            raise _client_error("NoSuchUpload", 404, op)
        return self.uploads[UploadId]

    def create_multipart_upload(self, Bucket, Key, ContentType="application/octet-stream"):
        self._up()
        upload_id = uuid.uuid4().hex
        self.uploads[upload_id] = {"bucket": Bucket, "key": Key, "type": ContentType, "parts": {}}
        return {"UploadId": upload_id}

    def upload_part(self, Bucket, Key, UploadId, PartNumber, Body):
        self._up()
        upload = self._upload(UploadId, "UploadPart")
        upload["parts"][int(PartNumber)] = bytes(Body)
        self.part_puts += 1
        return {"ETag": f'"{hashlib.md5(bytes(Body)).hexdigest()}"'}

    def list_parts(self, Bucket, Key, UploadId, PartNumberMarker=0):
        self._up()
        upload = self._upload(UploadId, "ListParts")
        return {
            "Parts": [
                {"PartNumber": n, "ETag": f'"{hashlib.md5(b).hexdigest()}"', "Size": len(b)}
                for n, b in sorted(upload["parts"].items()) if n > int(PartNumberMarker)
            ],
            "IsTruncated": False,
        }

    def complete_multipart_upload(self, Bucket, Key, UploadId, MultipartUpload):
        self._up()
        upload = self._upload(UploadId, "CompleteMultipartUpload")
        body = b"".join(upload["parts"][p["PartNumber"]] for p in MultipartUpload["Parts"])
        self.objects[(Bucket, Key)] = (body, upload["type"])
        del self.uploads[UploadId]

    def abort_multipart_upload(self, Bucket, Key, UploadId):
        self._up()
        self._upload(UploadId, "AbortMultipartUpload")
        del self.uploads[UploadId]

    # helpers for tests
    def keys(self, prefix: str = ""):
        return sorted(k for _, k in self.objects if k.startswith(prefix))

    def body(self, key: str) -> bytes:
        return next(b for (_, k), (b, _) in self.objects.items() if k == key)


@pytest.fixture
def fake_store(monkeypatch):
    """The object store, in memory, for one test."""
    from app.core.config import get_settings
    from app.services import objectstore

    settings = get_settings()
    monkeypatch.setattr(settings, "S3_ACCESS_KEY", "test-access")
    monkeypatch.setattr(settings, "S3_SECRET_KEY", "test-secret")
    store = FakeS3()
    objectstore.reset_for_tests(client=store)
    yield store
    objectstore.reset_for_tests()
