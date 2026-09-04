"""Real camera backend using picamera2 (Raspberry Pi only).

`picamera2` is imported lazily inside __init__ so this module can be imported on
machines without the library; only instantiating the backend requires the hardware.
Install on the Pi with: sudo apt install -y python3-picamera2
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import CameraBackend, CameraControl, CaptureResult
from .controls import MANUAL_CONTROLS, controls_by_name

# Map our control names to picamera2 control names. Names that match picamera2
# 1:1 are handled directly; the rest are translated in capture().
_PICAMERA2_DIRECT = {
    "ExposureTime",
    "AnalogueGain",
    "AwbEnable",
    "Brightness",
    "Contrast",
    "Saturation",
    "Sharpness",
    "ExposureValue",
    "FrameRate",
}


class Picamera2Camera(CameraBackend):
    name = "picamera2"

    def __init__(self) -> None:
        from picamera2 import Picamera2  # noqa: PLC0415 (lazy: Pi-only import)

        self._picam2 = Picamera2()
        self._picam2.start()

    def get_controls(self) -> list[CameraControl]:
        # Start from our canonical set, then refine numeric ranges from what the
        # sensor actually reports so the UI matches this specific hardware.
        reported = getattr(self._picam2, "camera_controls", {})
        controls: list[CameraControl] = []
        for ctrl in MANUAL_CONTROLS:
            info = reported.get(ctrl.name)
            if info and ctrl.kind == "number":
                lo, hi, default = info
                controls.append(
                    CameraControl(
                        ctrl.name, ctrl.label, ctrl.kind,
                        min=lo, max=hi,
                        default=default if default is not None else ctrl.default,
                        step=ctrl.step, unit=ctrl.unit, description=ctrl.description,
                    )
                )
            else:
                controls.append(ctrl)
        return controls

    def capture(self, settings: dict[str, Any], dest: Path) -> CaptureResult:
        defs = controls_by_name()
        controls: dict[str, Any] = {}
        for name in _PICAMERA2_DIRECT:
            if name in settings and settings[name] is not None:
                controls[name] = settings[name]

        # Manual colour gains as a (red, blue) tuple, only when AWB is disabled.
        if settings.get("AwbEnable") in (False, "false", "off", "0", 0):
            controls["AwbEnable"] = False
            red = settings.get("ColourGainRed", defs["ColourGainRed"].default)
            blue = settings.get("ColourGainBlue", defs["ColourGainBlue"].default)
            controls["ColourGains"] = (float(red), float(blue))

        if controls:
            self._picam2.set_controls(controls)

        width, height = _parse_resolution(str(settings.get("resolution", "4056x3040")))
        image_format = str(settings.get("image_format", "jpeg")).lower()

        request = self._picam2.capture_request()
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            request.save("main", str(dest))
            metadata = request.get_metadata()
        finally:
            request.release()

        applied = {**settings, "resolution": f"{width}x{height}", "image_format": image_format}
        applied["_sensor_metadata"] = metadata
        return CaptureResult(
            path=dest, width=width, height=height,
            image_format=image_format, applied_settings=applied,
        )

    def close(self) -> None:
        picam = getattr(self, "_picam2", None)
        if picam is not None:
            picam.stop()
            picam.close()
            self._picam2 = None


def _parse_resolution(value: str) -> tuple[int, int]:
    try:
        w, h = value.lower().split("x")
        return int(w), int(h)
    except (ValueError, AttributeError):
        return 4056, 3040
