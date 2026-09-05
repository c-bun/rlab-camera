"""Capture page and capture/controls API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse

from ..camera import get_camera
from ..capture_service import perform_capture

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
    return perform_capture(settings)
