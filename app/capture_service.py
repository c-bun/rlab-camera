"""Shared single-capture logic used by both the manual capture route and the
timecourse scheduler job.

Kept out of the routers so the scheduler can take a capture without importing the
web layer. Thread-safe: it opens a fresh SQLite connection per call and the camera
backend serializes concurrent capture/preview access with its own lock, so the
scheduler thread and FastAPI's threadpool can both call in.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from . import config, db
from .camera import get_camera

_EXT = {"jpg": "jpg", "jpeg": "jpg", "png": "png", "tiff": "tiff", "tif": "tiff"}


def perform_capture(
    settings: dict[str, Any], *, experiment_id: int | None = None
) -> dict[str, Any]:
    """Take one capture, write the file, persist the row, and return the image dict.

    Mirrors what ``POST /api/capture`` used to do inline. When ``experiment_id`` is
    given the image is tagged to that timecourse run.
    """
    camera = get_camera()
    now = datetime.now(UTC)
    fmt = str(settings.get("image_format", "jpeg")).lower()
    ext = _EXT.get(fmt, "jpg")
    filename = f"{now.strftime('%Y%m%dT%H%M%S%f')}.{ext}"
    dest = config.IMAGES_DIR / filename

    # Include the capture timestamp in the settings the backend persists (and, for TIFF,
    # embeds as ImageJ metadata) so an exported file carries when it was taken.
    settings = {**settings, "captured_at": now.isoformat()}
    result = camera.capture(settings, dest)

    image_id = db.insert_image(
        filename=filename,
        captured_at=now.isoformat(),
        width=result.width,
        height=result.height,
        image_format=result.image_format,
        settings=result.applied_settings,
        experiment_id=experiment_id,
    )
    return {"id": image_id, "filename": filename, **db.get_image(image_id)}
