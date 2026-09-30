"""Shared single-capture logic used by both the manual capture route and the
timecourse scheduler job.

Kept out of the routers so the scheduler can take a capture without importing the
web layer. Thread-safe: it opens a fresh SQLite connection per call and the camera
backend serializes concurrent capture/preview access with its own lock, so the
scheduler thread and FastAPI's threadpool can both call in.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from . import config, db
from .camera import get_camera
from .illumination import get_illumination


def _slug(name: str) -> str:
    """Make an acquisition name safe for use in a filename."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_") or "acq"


def perform_capture(
    settings: dict[str, Any],
    *,
    experiment_id: int | None = None,
    acquisition: str | None = None,
    timepoint: int | None = None,
) -> dict[str, Any]:
    """Take one capture, write the file, persist the row, and return the image dict.

    Mirrors what ``POST /api/capture`` used to do inline. When ``experiment_id`` is
    given the image is tagged to that timecourse run; ``acquisition``/``timepoint`` say
    which of the run's acquisitions this frame is and at which timepoint.
    """
    camera = get_camera()
    illumination = get_illumination()
    now = datetime.now(UTC)
    stem = now.strftime("%Y%m%dT%H%M%S%f")
    if acquisition is not None:
        stem += f"_{_slug(acquisition)}"
    filename = f"{stem}.tiff"
    dest = config.IMAGES_DIR / filename

    # Include the capture timestamp (and, in a run, which acquisition/timepoint this is)
    # in the settings the backend persists (and, for TIFF, embeds as ImageJ metadata) so
    # an exported file carries when and as what it was taken.
    run_tags: dict[str, Any] = {}
    if acquisition is not None:
        run_tags["acquisition"] = acquisition
    if timepoint is not None:
        run_tags["timepoint"] = timepoint
    settings = {**settings, "captured_at": now.isoformat(), **run_tags}

    # Illumination is synced to the capture: light the panels and, with confirm=True, wait
    # for them to confirm they are actually on (render ack) BEFORE integrating the frame —
    # then turn them off only AFTER the capture returns (the finally runs even on error).
    # This ordering (on → confirm rendered → capture → off) is what keeps every frame lit;
    # during live view the preview loop keeps them lit separately (fire-and-forget).
    applied_illum = illumination.apply(settings, confirm=True)
    try:
        result = camera.capture(settings, dest)
    finally:
        illumination.off()
    # Record what the panels actually did. The mock camera rebuilds applied_settings from
    # its own control set (dropping illum_* keys), so merge here to persist on any backend.
    result.applied_settings.update(applied_illum)
    result.applied_settings.update(run_tags)  # likewise dropped by the mock camera

    image_id = db.insert_image(
        filename=filename,
        captured_at=now.isoformat(),
        width=result.width,
        height=result.height,
        image_format=result.image_format,
        settings=result.applied_settings,
        experiment_id=experiment_id,
        acquisition=acquisition,
        timepoint=timepoint,
    )
    return {"id": image_id, "filename": filename, **db.get_image(image_id)}
