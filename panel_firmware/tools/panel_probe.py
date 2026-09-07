#!/usr/bin/env python3
"""Standalone bench driver for an rlab-camera LED panel (run on the Pi).

Validates a freshly-flashed panel's BLE peripheral (panel_firmware/micropython/main.py)
*without* touching the systemd service: it scans for the panel, connects, and writes a
short sequence of commands using the SAME 4-byte encoding the app uses
(``app.illumination.protocol.to_payload``), so a pass here means the real app will drive
it too. Watch the panel by eye (and the board's REPL) as each step prints.

Run on the Pi under the app venv (which has ``bleak``), from the repo root so
``app.illumination.protocol`` imports:

    cd ~/rlab-camera
    .venv/bin/python panel_firmware/tools/panel_probe.py            # target "rlab-panel"
    .venv/bin/python panel_firmware/tools/panel_probe.py AA:BB:CC:DD:EE:FF   # by address

Give an address (more reliable) or the advertised name as the single argument.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Allow running as a plain script: make the repo root importable for app.illumination.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bleak import BleakClient, BleakScanner  # noqa: E402

from app.illumination.protocol import COMMAND_CHAR_UUID, SERVICE_UUID, to_payload  # noqa: E402

DEFAULT_TARGET = "rlab-panel"
_SCAN_TIMEOUT_S = 10.0
_HOLD_S = 2.5

# (label, settings) pairs; settings use the same illum_* keys the app sends. Colours are
# the panel's pure hues (post-128-threshold) so what you see is unambiguous.
_SEQUENCE = [
    ("white @ 100%", {"illum_enable": True, "illum_color": "#ffffff", "illum_brightness": 100}),
    ("blue  @ 50%", {"illum_enable": True, "illum_color": "#0000ff", "illum_brightness": 50}),
    ("red   @ 25%", {"illum_enable": True, "illum_color": "#ff0000", "illum_brightness": 25}),
    ("green @ 100%", {"illum_enable": True, "illum_color": "#00ff00", "illum_brightness": 100}),
    ("off", {"illum_enable": False}),
]


async def _resolve(target: str) -> str:
    """Return a BLE address for ``target`` (already an address, or an advertised name)."""
    if ":" in target and len(target) >= 17:  # looks like AA:BB:CC:DD:EE:FF
        return target
    print(f"scanning for a panel named {target!r} (advertising {SERVICE_UUID})...")
    device = await BleakScanner.find_device_by_name(target, timeout=_SCAN_TIMEOUT_S)
    if device is None:
        raise SystemExit(f"no panel named {target!r} found within {_SCAN_TIMEOUT_S:.0f}s")
    print(f"found {target!r} at {device.address}")
    return device.address


async def _drive(address: str) -> None:
    print(f"connecting to {address}...")
    async with BleakClient(address) as client:
        print(f"connected: {client.is_connected}")
        for label, settings in _SEQUENCE:
            payload = to_payload(settings)
            print(f"  -> {label:14s} payload={bytes(payload).hex()}")
            await client.write_gatt_char(COMMAND_CHAR_UUID, payload, response=False)
            await asyncio.sleep(_HOLD_S)
    print("disconnected -- the panel should have cleared itself on the drop.")


async def _main() -> None:
    target = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TARGET
    address = await _resolve(target)
    await _drive(address)


if __name__ == "__main__":
    asyncio.run(_main())
