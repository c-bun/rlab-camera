"""Real camera backend using picamera2 (Raspberry Pi only).

`picamera2` is imported lazily inside __init__ so this module can be imported on
machines without the library; only instantiating the backend requires the hardware.
Install on the Pi with: sudo apt install -y python3-picamera2
"""

from __future__ import annotations

import io
import threading
from pathlib import Path
from typing import Any

from .base import CameraBackend, CameraControl, CaptureResult
from .controls import MANUAL_CONTROLS, controls_by_name
from .tiff import write_imagej_tiff

# Small fixed size for the live view, independent of the `resolution` control, so
# preview stays cheap even when captures are configured for full sensor resolution.
_PREVIEW_SIZE = (1014, 760)

# Our control names that map 1:1 onto picamera2 control names. The rest
# (colour gains, resolution, format) are translated in capture().
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

_AWB_OFF_VALUES = (False, "false", "False", "off", "0", 0)


class Picamera2Camera(CameraBackend):
    name = "picamera2"

    def __init__(self) -> None:
        from picamera2 import Picamera2  # noqa: PLC0415 (lazy: Pi-only import)

        self._picam2 = Picamera2()
        self._configured_size: tuple[int, int] | None = None
        self._started = False
        # Serialize camera access: FastAPI sync routes run in a threadpool, so a
        # live-view poll and a capture can hit the shared Picamera2 object at once
        # and race on the reconfigure (stop/configure/start) in _ensure_configured.
        self._lock = threading.Lock()

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
                        ctrl.name,
                        ctrl.label,
                        ctrl.kind,
                        min=lo,
                        max=hi,
                        default=default if default is not None else ctrl.default,
                        step=ctrl.step,
                        unit=ctrl.unit,
                        description=ctrl.description,
                    )
                )
            else:
                controls.append(ctrl)
        return controls

    def capture(self, settings: dict[str, Any], dest: Path) -> CaptureResult:
        with self._lock:
            size = _parse_resolution(str(settings.get("resolution", "4056x3040")))
            self._ensure_configured(size)

            controls = self._build_controls(settings)
            if controls:
                self._picam2.set_controls(controls)

            # Drop a frame so the new controls (exposure/gain/AWB) take effect before
            # the frame we keep — otherwise the first capture reflects the old state.
            self._picam2.capture_request().release()

            image_format = str(settings.get("image_format", "jpeg")).lower()
            request = self._picam2.capture_request()
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)

                # Report the size the camera was ACTUALLY configured to, not the request.
                actual_w, actual_h = self._picam2.camera_configuration()["main"]["size"]
                metadata = request.get_metadata()
                applied = {
                    **settings,
                    "resolution": f"{actual_w}x{actual_h}",
                    "image_format": image_format,
                    "_sensor_metadata": metadata,
                }

                if image_format in ("tiff", "tif"):
                    # Lossless TIFF carrying the applied settings + sensor metadata as an
                    # ImageJ-readable Info property (request.save can't embed our metadata).
                    write_imagej_tiff(dest, request.make_array("main"), applied)
                else:
                    request.save("main", str(dest))
            finally:
                request.release()
            return CaptureResult(
                path=dest,
                width=actual_w,
                height=actual_h,
                image_format=image_format,
                applied_settings=applied,
            )

    def preview(self, settings: dict[str, Any]) -> bytes:
        with self._lock:
            self._ensure_configured(_PREVIEW_SIZE)

            controls = self._build_controls(settings)
            if controls:
                self._picam2.set_controls(controls)

            # No settling-frame drop here (unlike capture): the live view is
            # continuous, so a control change simply shows on the next poll. This
            # keeps each poll to a single frame and low-latency.
            img = self._picam2.capture_image("main")
            buf = io.BytesIO()
            img.save(buf, format="JPEG")
            return buf.getvalue()

    def _ensure_configured(self, size: tuple[int, int]) -> None:
        """(Re)configure a still stream at `size`, restarting only when it changes."""
        if self._configured_size == size and self._started:
            return
        if self._started:
            self._picam2.stop()
            self._started = False
        config = self._picam2.create_still_configuration(main={"size": size})
        self._picam2.configure(config)
        self._picam2.start()
        self._started = True
        self._configured_size = size

    def _build_controls(self, settings: dict[str, Any]) -> dict[str, Any]:
        defs = controls_by_name()
        controls: dict[str, Any] = {}
        for name in _PICAMERA2_DIRECT:
            if settings.get(name) is not None:
                controls[name] = settings[name]

        # Manual colour gains as a (red, blue) tuple, only when AWB is disabled.
        if settings.get("AwbEnable") in _AWB_OFF_VALUES:
            controls["AwbEnable"] = False
            red = settings.get("ColourGainRed", defs["ColourGainRed"].default)
            blue = settings.get("ColourGainBlue", defs["ColourGainBlue"].default)
            controls["ColourGains"] = (float(red), float(blue))
        return controls

    def close(self) -> None:
        picam = getattr(self, "_picam2", None)
        if picam is not None:
            if self._started:
                picam.stop()
                self._started = False
            picam.close()
            self._picam2 = None


def _parse_resolution(value: str) -> tuple[int, int]:
    try:
        w, h = value.lower().split("x")
        return int(w), int(h)
    except (ValueError, AttributeError):
        return 4056, 3040
