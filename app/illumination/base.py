"""Illumination backend interface and shared control definitions.

A backend reports the illumination controls it supports (with ranges), applies a set
of requested values to the connected LED panels, and can turn them off. Both the real
Bluetooth backend and the mock backend implement this same interface so the rest of the
app is hardware-agnostic — mirroring the camera abstraction in ``app/camera``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class IlluminationControl:
    """A single illumination control the UI can render and the user can set.

    Same shape as ``camera.CameraControl`` so the frontend can render it with the same
    helpers. Adds a ``"color"`` kind (an RGB colour, rendered as an HTML colour input).
    """

    name: str
    label: str
    kind: str  # "number" | "choice" | "bool" | "color"
    min: float | None = None
    max: float | None = None
    default: Any = None
    step: float | None = None
    unit: str | None = None
    choices: list[Any] | None = None
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "kind": self.kind,
            "min": self.min,
            "max": self.max,
            "default": self.default,
            "step": self.step,
            "unit": self.unit,
            "choices": self.choices,
            "description": self.description,
        }


class IlluminationBackend(ABC):
    """Interface every illumination backend implements."""

    #: Human-readable backend name, e.g. "ble" or "mock".
    name: str = "base"

    @abstractmethod
    def get_controls(self) -> list[IlluminationControl]:
        """Return the illumination controls this backend supports, with ranges."""

    @abstractmethod
    def apply(self, settings: dict[str, Any]) -> dict[str, Any]:
        """Drive every panel from ``settings`` and return the state actually applied.

        ``settings`` is the same flat capture-settings dict used elsewhere; the
        illumination keys (``illum_enable``, ``illum_color``, ``illum_brightness``) are
        read out of it and any others ignored. When illumination is disabled the panels
        are turned off. The returned dict contains only the ``illum_*`` keys so the
        caller can persist exactly what the panels did.
        """

    @abstractmethod
    def off(self) -> None:
        """Turn every panel off. Safe to call repeatedly."""

    def status(self) -> dict[str, Any]:
        """Report panel connectivity so the UI can warn when panels are missing.

        Returns ``{"backend", "configured", "connected", "panels": [...]}``. The default
        (used by the mock backend) reports no configured panels, so the UI shows no
        warning off-hardware. The BLE backend overrides this to probe real connections.
        """
        return {"backend": self.name, "configured": 0, "connected": 0, "panels": []}

    def close(self) -> None:  # noqa: B027 (optional hook; backends without resources need no override)
        """Release hardware resources. Safe to call multiple times."""
