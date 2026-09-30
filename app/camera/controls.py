"""Canonical manual-control definitions for the RPi HQ camera (Sony IMX477).

These ranges are sensible defaults used by the mock backend and as fallbacks. The
real Picamera2 backend should prefer values reported by `picamera2.camera_controls`
where available, since exact ranges depend on sensor mode and tuning.
"""

from __future__ import annotations

from .base import CameraControl

# Resolutions the HQ camera commonly runs at (full sensor is 4056x3040).
RESOLUTIONS = ["4056x3040", "2028x1520", "2028x1080", "1332x990"]

# Captures now record the raw Bayer sensor data (see app/camera/raw.py), which bypasses
# the ISP's white balance entirely — so these values no longer affect captured pixels. They
# are kept because the processed live-view preview still runs through the ISP; pinning AWB
# off with unity gains keeps that preview stable rather than auto-white-balancing.
FIXED_WHITE_BALANCE: dict[str, object] = {
    "AwbEnable": False,
    "ColourGainRed": 1.0,
    "ColourGainBlue": 1.0,
}

MANUAL_CONTROLS: list[CameraControl] = [
    CameraControl(
        "resolution",
        "Sensor readout mode",
        "choice",
        default="4056x3040",
        choices=RESOLUTIONS,
        description="Sensor readout resolution. Raw captures are saved as a 3-channel R/G/B "
        "stack built from 2x2 Bayer blocks, so the saved TIFF is half these dimensions "
        "(e.g. 4056x3040 readout -> 2028x1520 stack).",
    ),
    CameraControl(
        "ExposureTime",
        "Exposure time",
        "number",
        min=100,
        max=10_000_000,
        default=10_000,
        step=100,
        unit="µs",
        description="Shutter/exposure time. Entered and displayed in seconds; the "
        "Raspberry Pi HQ Camera (IMX477) supports roughly 0.00011–694 s (up to "
        "~11.6 minutes), refined at runtime from the sensor.",
    ),
    CameraControl(
        "AnalogueGain",
        "Analogue gain (ISO)",
        "number",
        min=1.0,
        max=16.0,
        default=1.0,
        step=0.1,
        description="Sensor gain; ISO ≈ gain × 100.",
    ),
    CameraControl(
        "ExposureValue",
        "Exposure compensation",
        "number",
        min=-8.0,
        max=8.0,
        default=0.0,
        step=0.1,
        unit="EV",
        description="Auto-exposure bias in stops; only affects captures where exposure is "
        "left to the camera rather than set manually.",
    ),
]


def controls_by_name() -> dict[str, CameraControl]:
    return {c.name: c for c in MANUAL_CONTROLS}
