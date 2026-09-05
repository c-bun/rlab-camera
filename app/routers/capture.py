"""Capture page and capture/controls API."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse

from .. import config, db
from ..camera import get_camera

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    templates = request.app.state.templates
    camera = get_camera()
    return templates.TemplateResponse(
        request,
        "index.html",
        {"backend": camera.name},
    )


@router.get("/api/controls")
def get_controls() -> dict[str, Any]:
    camera = get_camera()
    return {
        "backend": camera.name,
        "controls": [c.to_dict() for c in camera.get_controls()],
    }


@router.post("/api/preview")
def preview(settings: dict[str, Any]) -> Response:
    # Live view: apply the same settings as a capture but return an in-memory JPEG
    # frame — no file on disk, no DB row. Called repeatedly at a low framerate.
    camera = get_camera()
    return Response(content=camera.preview(settings), media_type="image/jpeg")


@router.post("/api/capture")
def capture(settings: dict[str, Any]) -> dict[str, Any]:
    camera = get_camera()
    now = datetime.now(UTC)
    fmt = str(settings.get("image_format", "jpeg")).lower()
    ext = {"jpg": "jpg", "jpeg": "jpg", "png": "png", "tiff": "tiff", "tif": "tiff"}.get(fmt, "jpg")
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
    )
    return {"id": image_id, "filename": filename, **db.get_image(image_id)}
