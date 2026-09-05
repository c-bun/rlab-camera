"""Image listing, viewing, and download."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from PIL import Image

from .. import config, db

router = APIRouter(prefix="/api/images", tags=["images"])

# Long edge of the cached gallery thumbnail, in pixels.
_THUMB_MAX = 480


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
    media_type = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "tiff": "image/tiff",
        "tif": "image/tiff",
    }.get(image["image_format"], "application/octet-stream")
    return FileResponse(
        path,
        filename=image["filename"] if download else None,
        media_type=media_type,
    )


@router.get("/{image_id}/thumbnail")
def image_thumbnail(image_id: int) -> FileResponse:
    """A small JPEG preview of the capture, so formats browsers can't render inline
    (TIFF) still show in the gallery. Derived from the captured pixels — same settings,
    just downscaled — and cached to disk, regenerated if the source is newer."""
    image = db.get_image(image_id)
    if image is None:
        raise HTTPException(status_code=404, detail="image not found")
    src = config.IMAGES_DIR / image["filename"]
    if not src.exists():
        raise HTTPException(status_code=404, detail="image file missing on disk")

    thumb = config.THUMBS_DIR / f"{image_id}.jpg"
    if not thumb.exists() or thumb.stat().st_mtime < src.stat().st_mtime:
        config.ensure_dirs()
        with Image.open(src) as im:
            im = im.convert("RGB")
            im.thumbnail((_THUMB_MAX, _THUMB_MAX))
            im.save(thumb, format="JPEG", quality=80)
    return FileResponse(thumb, media_type="image/jpeg")
