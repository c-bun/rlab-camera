"""Backend selection.

`CAMERA_BACKEND` chooses the backend:
  - "mock"      → MockCamera (default off-Pi; forced when picamera2 is unavailable)
  - "picamera2" → real hardware
  - "auto"      → picamera2 if importable, else mock  (default)
"""

from __future__ import annotations

import os
from functools import lru_cache

from .base import CameraBackend


@lru_cache(maxsize=1)
def get_camera() -> CameraBackend:
    """Return the process-wide camera backend (created once)."""
    choice = os.environ.get("CAMERA_BACKEND", "auto").lower()

    if choice == "mock":
        return _mock()
    if choice == "picamera2":
        return _picamera2()

    # auto
    try:
        return _picamera2()
    except Exception:
        return _mock()


def _mock() -> CameraBackend:
    from .mock import MockCamera

    return MockCamera()


def _picamera2() -> CameraBackend:
    from .picamera2_backend import Picamera2Camera

    return Picamera2Camera()
