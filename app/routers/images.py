"""Image listing, viewing, and download."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from .. import config, db

router = APIRouter(prefix="/api/images", tags=["images"])


@router.get("")
def list_images(limit: int = 200) -> list[dict[str, Any]]:
    return db.list_images(limit=limit)


@router.get("/{image_id}")
def get_image(image_id: int) -> dict[str, Any]:
    image = db.get_image(image_id)
    if image is None:
        raise HTTPException(status_code=404, detail="image not found")
    return image


@router.get("/{image_id}/file")
def image_file(image_id: int, download: bool = False) -> FileResponse:
    image = db.get_image(image_id)
    if image is None:
        raise HTTPException(status_code=404, detail="image not found")
    path = config.IMAGES_DIR / image["filename"]
    if not path.exists():
        raise HTTPException(status_code=404, detail="image file missing on disk")
    return FileResponse(
        path,
        filename=image["filename"] if download else None,
        media_type="image/jpeg" if image["image_format"] in ("jpg", "jpeg") else "image/png",
    )
