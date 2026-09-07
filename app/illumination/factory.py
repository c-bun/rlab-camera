"""Illumination backend selection.

`ILLUMINATION_BACKEND` chooses the backend:
  - "mock" → MockPanels (default off-Pi; no hardware touched)
  - "ble"  → real LED panels over Bluetooth (needs RLAB_PANELS)
  - "auto" → ble when RLAB_PANELS lists panels, else mock  (default)

Unlike the camera's "auto" (which tries to import Pi-only hardware), constructing the
BLE backend spins up a Bluetooth connection thread, so auto only picks it when panels
are actually configured — keeping local/CI runs on the mock with zero Bluetooth I/O.
"""

from __future__ import annotations

import os
from functools import lru_cache

from .. import config
from .base import IlluminationBackend


@lru_cache(maxsize=1)
def get_illumination() -> IlluminationBackend:
    """Return the process-wide illumination backend (created once)."""
    choice = os.environ.get("ILLUMINATION_BACKEND", "auto").lower()

    if choice == "mock":
        return _mock()
    if choice == "ble":
        return _ble()

    # auto
    if config.PANELS:
        try:
            return _ble()
        except Exception:
            return _mock()
    return _mock()


def _mock() -> IlluminationBackend:
    from .mock import MockPanels

    return MockPanels()


def _ble() -> IlluminationBackend:
    from .ble_backend import BlePanels

    return BlePanels(config.PANELS)
