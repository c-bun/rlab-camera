"""Canonical manual-control definitions for the RPi HQ camera (Sony IMX477).

These ranges are sensible defaults used by the mock backend and as fallbacks. The
real Picamera2 backend should prefer values reported by `picamera2.camera_controls`
where available, since exact ranges depend on sensor mode and tuning.
"""

from __future__ import annotations

from .base import CameraControl

# Resolutions the HQ camera commonly runs at (full sensor is 4056x3040).
RESOLUTIONS = ["4056x3040", "2028x1520", "2028x1080", "1332x990"]
IMAGE_FORMATS = ["jpeg", "png", "tiff"]
AWB_MODES = ["auto", "incandescent", "tungsten", "fluorescent", "indoor", "daylight", "cloudy"]

MANUAL_CONTROLS: list[CameraControl] = [
    CameraControl(
        "resolution",
        "Resolution",
        "choice",
        default="4056x3040",
        choices=RESOLUTIONS,
        description="Capture resolution (width x height).",
    ),
    CameraControl(
        "image_format",
        "Format",
        "choice",
        default="jpeg",
        choices=IMAGE_FORMATS,
        description="File format. JPEG is compact; PNG is lossless; TIFF is lossless and "
        "embeds the capture settings as ImageJ-readable metadata for analysis.",
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
        description="Shutter/exposure time in microseconds.",
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
        "AwbEnable",
        "Auto white balance",
        "bool",
        default=True,
        description="When off, use the manual red/blue colour gains below.",
    ),
    CameraControl(
        "AwbMode",
        "AWB mode",
        "choice",
        default="auto",
        choices=AWB_MODES,
        description="White-balance preset used when AWB is enabled.",
    ),
    CameraControl(
        "ColourGainRed",
        "Red colour gain",
        "number",
        min=0.0,
        max=32.0,
        default=2.0,
        step=0.1,
        description="Manual red gain (used when AWB is off).",
    ),
    CameraControl(
        "ColourGainBlue",
        "Blue colour gain",
        "number",
        min=0.0,
        max=32.0,
        default=2.0,
        step=0.1,
        description="Manual blue gain (used when AWB is off).",
    ),
    CameraControl(
        "Brightness",
        "Brightness",
        "number",
        min=-1.0,
        max=1.0,
        default=0.0,
        step=0.05,
        description="Post-processing brightness offset; 0 is neutral, negative darkens and "
        "positive lightens the image.",
    ),
    CameraControl(
        "Contrast",
        "Contrast",
        "number",
        min=0.0,
        max=32.0,
        default=1.0,
        step=0.1,
        description="Post-processing contrast; 1.0 is neutral, higher values increase the "
        "difference between light and dark tones.",
    ),
    CameraControl(
        "Saturation",
        "Saturation",
        "number",
        min=0.0,
        max=32.0,
        default=1.0,
        step=0.1,
        description="Colour intensity; 1.0 is neutral, 0 gives greyscale and higher values "
        "make colours more vivid.",
    ),
    CameraControl(
        "Sharpness",
        "Sharpness",
        "number",
        min=0.0,
        max=16.0,
        default=1.0,
        step=0.1,
        description="Edge-enhancement strength; 1.0 is neutral, 0 disables sharpening and "
        "higher values sharpen more.",
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
    CameraControl(
        "FrameRate",
        "Frame rate",
        "number",
        min=0.1,
        max=120.0,
        default=30.0,
        step=0.1,
        unit="fps",
        description="Sensor frame rate. Its inverse caps the maximum exposure time, so lower "
        "it for very long exposures.",
    ),
]


def controls_by_name() -> dict[str, CameraControl]:
    return {c.name: c for c in MANUAL_CONTROLS}
