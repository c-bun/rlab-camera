"""Canonical illumination-control definitions for the Waveshare RGB matrix panels.

The panels are broadcast to identically: one colour + brightness drives every connected
panel. Brightness is the *fraction of LEDs lit* — the panel dithers to that density so a
sample sees roughly even illumination (each LED is either on or off).
"""

from __future__ import annotations

from .base import IlluminationControl

# Quick-pick colours offered as buttons in the UI. "off" is special-cased in the
# frontend (it clears the enable toggle rather than setting a colour).
COLOR_PRESETS: dict[str, str] = {
    "white": "#ffffff",
    "blue": "#0000ff",
    "red": "#ff0000",
    "green": "#00ff00",
    "off": "#000000",
}

PANEL_CONTROLS: list[IlluminationControl] = [
    IlluminationControl(
        "illum_enable",
        "Illumination",
        "bool",
        default=False,
        description="Master switch for the LED panels. When off, panels stay dark for "
        "captures and live view.",
    ),
    IlluminationControl(
        "illum_color",
        "Colour",
        "color",
        default="#ffffff",
        description="Colour every lit LED shows. Applied identically to all connected panels.",
    ),
    IlluminationControl(
        "illum_brightness",
        "Brightness",
        "number",
        min=0,
        max=100,
        default=100,
        step=1,
        unit="%",
        description="Fraction of the panel's LEDs that light up. The panel spreads them "
        "evenly (dither) so brightness scales with lit-LED density.",
    ),
]


def controls_by_name() -> dict[str, IlluminationControl]:
    return {c.name: c for c in PANEL_CONTROLS}
