"""Mock illumination backend for development and tests (no hardware required).

Records the last state it was asked to apply so the capture/preview/experiment flows
can be exercised end to end on a laptop or in CI without any Bluetooth panels.
"""

from __future__ import annotations

from typing import Any

from .base import IlluminationBackend, IlluminationControl
from .controls import PANEL_CONTROLS
from .protocol import extract


class MockPanels(IlluminationBackend):
    name = "mock"

    def __init__(self) -> None:
        self._last_applied: dict[str, Any] | None = None

    def get_controls(self) -> list[IlluminationControl]:
        return list(PANEL_CONTROLS)

    def apply(self, settings: dict[str, Any]) -> dict[str, Any]:
        applied = extract(settings)
        self._last_applied = applied
        return applied

    def off(self) -> None:
        self._last_applied = {
            "illum_enable": False,
            "illum_color": "#000000",
            "illum_brightness": 0,
        }
