"""Illumination controls API for the LED panels."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..illumination import COLOR_PRESETS, get_illumination

router = APIRouter()


@router.get("/api/illumination/controls")
def get_controls() -> dict[str, Any]:
    illum = get_illumination()
    return {
        "backend": illum.name,
        "controls": [c.to_dict() for c in illum.get_controls()],
        "presets": COLOR_PRESETS,
    }


@router.get("/api/illumination/status")
def get_status() -> dict[str, Any]:
    # Panel connectivity, so the UI can warn when illumination is on but no panel is
    # reachable. On the mock backend this reports zero configured panels (no warning).
    return get_illumination().status()


@router.post("/api/illumination/off")
def turn_off() -> dict[str, str]:
    # Called by the client when live view is toggled off, so the panels don't stay lit.
    get_illumination().off()
    return {"status": "off"}
