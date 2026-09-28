"""
INDRA Platform — Copies that are safe to show (layer 7, Phase 5 T5 step 1)

A phone photo carries where it was taken to within a few metres, and for a
citizen reporting from home that is where they live. So what officials see by
default is never the original but a copy with **every metadata tag removed**:

* **a photo** → a JPEG at most 1,600 px on its long side, and a 320 px
  thumbnail. Pillow writes no EXIF unless it is handed some, so re-encoding is
  the removal. The camera's orientation tag is applied to the pixels first, so
  a portrait photo still stands up once the tag is gone.
* **a video** → a poster JPEG (the frame 1 s in), its thumbnail, and a copy
  with the metadata stripped and the audio and video copied as they are:

      ffmpeg -i in.mp4 -map 0:v -map 0:a? -map_metadata -1 -c copy out.mp4

  `-map_metadata -1` drops every container and stream tag, GPS and creation
  time included. `-map 0:v -map 0:a?` keeps only picture and sound, which also
  drops the separate metadata track an iPhone records its location in.
  `-c copy` re-encodes nothing, so it is fast and loses nothing.

The original stays private, for ANALYST and above, and every view of it is
audited (api/media.py).
"""

import subprocess
from io import BytesIO
from typing import Tuple

from app.services.media_extract import FFMPEG_TIMEOUT_S, UnreadableMedia, frame_times, grab_frame, open_image

FULL_LONG_SIDE = 1600
THUMB_LONG_SIDE = 320
JPEG_QUALITY_FULL = 85
JPEG_QUALITY_THUMB = 80


def _jpeg(image, long_side: int, quality: int) -> bytes:
    from PIL import ImageOps

    copy = ImageOps.exif_transpose(image)
    if copy.mode not in ("RGB", "L"):
        copy = copy.convert("RGB")
    copy.thumbnail((long_side, long_side))
    out = BytesIO()
    # No exif= argument: the saved file carries no EXIF block at all.
    copy.save(out, format="JPEG", quality=quality, optimize=True)
    return out.getvalue()


def image_derivatives(data: bytes) -> Tuple[bytes, bytes]:
    """(full JPEG ≤ 1,600 px, thumbnail JPEG ≤ 320 px), both without EXIF."""
    image = open_image(data)
    try:
        return (
            _jpeg(image, FULL_LONG_SIDE, JPEG_QUALITY_FULL),
            _jpeg(image, THUMB_LONG_SIDE, JPEG_QUALITY_THUMB),
        )
    finally:
        image.close()


def strip_video(src: str, dst: str) -> None:
    """Write `dst`: `src` with every metadata tag and data track removed, nothing re-encoded."""
    try:
        done = subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", src,
             "-map", "0:v", "-map", "0:a?",
             "-map_metadata", "-1", "-map_metadata:s:v", "-1", "-map_metadata:s:a", "-1",
             "-map_chapters", "-1",
             "-c", "copy", "-movflags", "+faststart", dst],
            capture_output=True, timeout=FFMPEG_TIMEOUT_S * 2, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise UnreadableMedia(f"ffmpeg strip: {type(e).__name__}: {e}") from e
    if done.returncode != 0:
        raise UnreadableMedia(f"ffmpeg strip: {done.stderr.decode('utf-8', 'replace')[:200]}")


def video_poster(src: str, duration_s) -> Tuple[bytes, bytes]:
    """(poster JPEG ≤ 1,600 px, thumbnail ≤ 320 px) from the frame 1 s in."""
    frame = open_image(grab_frame(src, frame_times(duration_s)[0]))
    try:
        return (
            _jpeg(frame, FULL_LONG_SIDE, JPEG_QUALITY_FULL),
            _jpeg(frame, THUMB_LONG_SIDE, JPEG_QUALITY_THUMB),
        )
    finally:
        frame.close()
