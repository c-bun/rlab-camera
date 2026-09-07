"""Illumination abstraction (LED panels over Bluetooth).

Everything outside this package talks to the panels through `get_illumination()` and
the `IlluminationBackend` interface. Never import `bleak` anywhere else — that keeps the
app importable and testable on machines without a Bluetooth stack (macOS dev, CI).
"""

from .base import IlluminationBackend, IlluminationControl
from .controls import COLOR_PRESETS
from .factory import get_illumination

__all__ = [
    "COLOR_PRESETS",
    "IlluminationBackend",
    "IlluminationControl",
    "get_illumination",
]
