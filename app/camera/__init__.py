"""Camera abstraction.

Everything outside this package talks to the camera through `get_camera()` and
the `CameraBackend` interface. Never import `picamera2` anywhere else — that keeps
the app importable and testable on machines without the camera hardware (e.g. macOS
dev machines and CI).
"""

from .base import CameraBackend, CameraControl, CaptureResult
from .factory import get_camera

__all__ = ["CameraBackend", "CameraControl", "CaptureResult", "get_camera"]
