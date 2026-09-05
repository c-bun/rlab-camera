"""Camera backend interface and shared control definitions.

A backend reports the manual controls it supports (with ranges), applies a set of
requested control values, and captures a still image to a file. Both the real
Picamera2 backend and the mock backend implement this same interface so the rest
of the app is hardware-agnostic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CameraControl:
    """A single manual control the UI can render and the user can set.

    `min`/`max`/`default` are reported by the backend so the UI is honest about
    what the sensor actually supports rather than hard-coding limits.
    """

    name: str
    label: str
    kind: str  # "number" | "choice" | "bool"
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


@dataclass
class CaptureResult:
    """Outcome of a capture: where the file landed and the settings actually used."""

    path: Path
    width: int
    height: int
    image_format: str
    applied_settings: dict[str, Any] = field(default_factory=dict)


class CameraBackend(ABC):
    """Interface every camera backend implements."""

    #: Human-readable backend name, e.g. "picamera2" or "mock".
    name: str = "base"

    @abstractmethod
    def get_controls(self) -> list[CameraControl]:
        """Return the manual controls this backend supports, with ranges."""

    @abstractmethod
    def capture(self, settings: dict[str, Any], dest: Path) -> CaptureResult:
        """Apply `settings`, capture a still to `dest`, return what was used.

        `settings` maps control names (from `get_controls`) to requested values.
        Unknown or out-of-range values should be ignored or clamped, not fatal.
        """

    @abstractmethod
    def preview(self, settings: dict[str, Any]) -> bytes:
        """Apply `settings` and return a small JPEG frame in memory (no file).

        Used for the live view: called repeatedly at a low framerate to let users
        see the effect of controls without capturing to disk or the database.
        """

    def close(self) -> None:  # noqa: B027 (optional hook; backends without resources need no override)
        """Release hardware resources. Safe to call multiple times."""
