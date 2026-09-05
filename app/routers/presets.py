"""Named capture-setting presets: save, list, recall, delete.

Presets live server-side in SQLite so they are shared across all lab members
reaching the Pi and persist across browsers and devices. The stored `settings`
mirror the control-panel body sent to /api/capture, so recalling a preset is just
applying it back into the control panel client-side.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException

from .. import db

router = APIRouter(prefix="/api/presets", tags=["presets"])


@router.get("")
def list_presets() -> list[dict[str, Any]]:
    return db.list_presets()


@router.post("")
def save_preset(payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name", "")).strip()
    if not name:
        raise HTTPException(status_code=400, detail="preset name is required")
    settings = payload.get("settings")
    if not isinstance(settings, dict):
        raise HTTPException(status_code=400, detail="settings must be an object")

    preset_id = db.upsert_preset(
        name=name,
        settings=settings,
        created_at=datetime.now(UTC).isoformat(),
    )
    return db.get_preset(preset_id)


@router.delete("/{preset_id}")
def delete_preset(preset_id: int) -> dict[str, bool]:
    if not db.delete_preset(preset_id):
        raise HTTPException(status_code=404, detail="preset not found")
    return {"deleted": True}
