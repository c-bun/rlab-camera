"""Shared illumination settings interpretation and the panel wire protocol.

Both backends read the flat capture-settings dict the same way (`extract`). The BLE
backend additionally encodes the applied state into the 4-byte command the panel
firmware expects (`to_payload`). The panel firmware in ``panel_firmware/`` must decode
that same layout — keep the two in sync.
"""

from __future__ import annotations

from typing import Any

from .controls import controls_by_name

# Custom GATT service + characteristics the panel firmware advertises. A writable command
# characteristic receives the 4-byte payload; a notify-only status characteristic sends a
# one-byte render acknowledgement (1 = lit, 0 = cleared) back to the Pi after the panel
# renders each command, so the capture path can wait for the panel to actually be on before
# integrating a frame. Also defined in panel_firmware/micropython/main.py (the CircuitPython
# panel_firmware/code.py is legacy). Keep all three UUIDs in sync with the firmware.
SERVICE_UUID = "5f1d0001-9d6f-4c1e-8b2a-2a5f3c9e7a10"
COMMAND_CHAR_UUID = "5f1d0002-9d6f-4c1e-8b2a-2a5f3c9e7a10"
STATUS_CHAR_UUID = "5f1d0003-9d6f-4c1e-8b2a-2a5f3c9e7a10"


def _coerce_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.lower() in ("1", "true", "on", "yes")
    return bool(value)


def _coerce_number(value: Any, lo: float, hi: float, default: float) -> float:
    if value is None:
        return default
    try:
        num = float(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, num))


def _coerce_color(value: Any, default: str) -> str:
    """Normalise a colour to a lower-case ``#rrggbb`` string, clamping bad input."""
    if not isinstance(value, str):
        return default
    s = value.strip().lower()
    if s.startswith("#"):
        s = s[1:]
    if len(s) == 3:  # #abc shorthand
        s = "".join(ch * 2 for ch in s)
    if len(s) != 6:
        return default
    try:
        int(s, 16)
    except ValueError:
        return default
    return f"#{s}"


def extract(settings: dict[str, Any]) -> dict[str, Any]:
    """Coerce the illumination keys out of a full settings dict.

    Returns exactly the ``illum_*`` keys (enable/color/brightness), clamped to their
    control ranges — the state the panels will actually be driven to and that the caller
    persists with the capture.
    """
    defs = controls_by_name()
    enable = _coerce_bool(settings.get("illum_enable"), bool(defs["illum_enable"].default))
    color = _coerce_color(settings.get("illum_color"), str(defs["illum_color"].default))
    bctrl = defs["illum_brightness"]
    brightness = _coerce_number(
        settings.get("illum_brightness"), bctrl.min, bctrl.max, bctrl.default
    )
    return {
        "illum_enable": enable,
        "illum_color": color,
        "illum_brightness": brightness,
    }


def to_payload(applied: dict[str, Any]) -> bytes:
    """Encode applied illumination state into the 4-byte panel command ``[R,G,B,bri]``.

    ``bri`` is 0–255 (fraction of LEDs to light). When illumination is disabled, all
    four bytes are zero, which the firmware treats as "clear the panel".
    """
    if not applied.get("illum_enable", False):
        return bytes((0, 0, 0, 0))
    hexcolor = applied["illum_color"].lstrip("#")
    r = int(hexcolor[0:2], 16)
    g = int(hexcolor[2:4], 16)
    b = int(hexcolor[4:6], 16)
    bri = round(float(applied["illum_brightness"]) / 100.0 * 255)
    bri = max(0, min(255, bri))
    return bytes((r, g, b, bri))
