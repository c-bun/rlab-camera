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

import numpy as np

from .base import CameraBackend, CameraControl, CaptureResult
from .controls import FIXED_WHITE_BALANCE, MANUAL_CONTROLS
from .raw import (
    bayer_to_channels,
    bit_depth_from_format,
    cfa_from_format,
    unpack_csi2p,
)
from .tiff import write_imagej_channel_stack

# Small fixed size for the live view, independent of the `resolution` control, so
# preview stays cheap even when captures are configured for full sensor resolution.
_PREVIEW_SIZE = (1014, 760)

# Our control names that map 1:1 onto picamera2 control names. The rest
# (colour gains, resolution, format) are translated in capture().
# FrameRate is deliberately absent: pinning it fixes FrameDurationLimits, which caps
# ExposureTime (a FrameRate of 30 clamps exposures to ~33 ms). By not sending it, the
# sensor mode's native frame-duration ceiling stretches to fit long manual exposures.
# The achieved frame duration is still recorded per capture in _sensor_metadata.
_PICAMERA2_DIRECT = {
    "ExposureTime",
    "AnalogueGain",
    "ExposureValue",
}


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

            # Drop a frame so the new controls (exposure/gain) take effect before the
            # frame we keep — otherwise the first capture reflects the old state.
            self._picam2.capture_request().release()

            image_format = "tiff"
            request = self._picam2.capture_request()
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)

                raw_cfg = self._picam2.camera_configuration()["raw"]
                metadata = request.get_metadata()

                # Raw Bayer mosaic straight off the sensor, split into an R/G/B channel
                # stack with no demosaic interpolation (each 2x2 block -> one output pixel).
                mosaic, cfa, bit_depth = self._read_raw_mosaic(request, raw_cfg)
                stack = bayer_to_channels(mosaic, cfa)
                out_h, out_w = stack.shape[1], stack.shape[2]

                black, white = _raw_levels(metadata, bit_depth)
                read_w, read_h = raw_cfg["size"]
                applied = {
                    **settings,
                    **FIXED_WHITE_BALANCE,
                    "resolution": f"{read_w}x{read_h}",
                    "image_format": image_format,
                    "raw_cfa": cfa,
                    "raw_bit_depth": bit_depth,
                    "raw_black_level": black,
                    "raw_white_level": white,
                    "channels": "R,G,B (G = mean of both Bayer greens)",
                    "_sensor_metadata": metadata,
                }

                # 16-bit ImageJ composite stack of raw values; settings + sensor metadata
                # ride along in the Info property (request.save can't embed our metadata).
                write_imagej_channel_stack(dest, stack, applied)
            finally:
                request.release()
            return CaptureResult(
                path=dest,
                width=out_w,
                height=out_h,
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
        """(Re)configure at `size`, restarting only when it changes.

        Both a `main` stream (for the processed live-view preview) and a `raw` stream at
        the sensor readout mode are configured; captures read the raw stream, preview reads
        main. `size` selects the sensor mode, so the raw plane comes off at that resolution.
        """
        if self._configured_size == size and self._started:
            return
        if self._started:
            self._picam2.stop()
            self._started = False
        config = self._picam2.create_still_configuration(main={"size": size}, raw={"size": size})
        self._picam2.configure(config)
        self._picam2.start()
        self._started = True
        self._configured_size = size

    def _read_raw_mosaic(
        self, request: Any, raw_cfg: dict[str, Any]
    ) -> tuple[np.ndarray, str, int]:
        """Return (mosaic, cfa, bit_depth) — a 2-D uint16 Bayer mosaic off the raw stream.

        picamera2 reports the raw stream as a packed CSI2P plane on the IMX477; we reshape
        the raw buffer by its stride and unpack. If a sensor ever reports an already-unpacked
        format, `make_array` yields the uint16 mosaic directly.
        """
        fmt = raw_cfg["format"]
        cfa = cfa_from_format(fmt)
        bit_depth = bit_depth_from_format(fmt)
        width, height = raw_cfg["size"]

        if "CSI2P" in fmt.upper():
            stride = raw_cfg["stride"]
            buf = request.make_buffer("raw")
            plane = np.frombuffer(buf, dtype=np.uint8)[: height * stride].reshape(height, stride)
            mosaic = unpack_csi2p(plane, width, bit_depth)
        else:
            mosaic = np.asarray(request.make_array("raw"))
            if mosaic.ndim != 2:  # some formats come back with a trailing axis
                mosaic = mosaic.reshape(height, -1)
            mosaic = mosaic[:height, :width].astype(np.uint16)
        return mosaic, cfa, bit_depth

    def _build_controls(self, settings: dict[str, Any]) -> dict[str, Any]:
        controls: dict[str, Any] = {}
        for name in _PICAMERA2_DIRECT:
            if settings.get(name) is not None:
                controls[name] = settings[name]

        # AWB is fixed off with unity colour gains — see FIXED_WHITE_BALANCE.
        controls["AwbEnable"] = False
        controls["ColourGains"] = (
            FIXED_WHITE_BALANCE["ColourGainRed"],
            FIXED_WHITE_BALANCE["ColourGainBlue"],
        )
        return controls

    def close(self) -> None:
        picam = getattr(self, "_picam2", None)
        if picam is not None:
            if self._started:
                picam.stop()
                self._started = False
            picam.close()
            self._picam2 = None


def _raw_levels(metadata: dict[str, Any], bit_depth: int) -> tuple[Any, int]:
    """Black and white reference levels for the raw values, for later interpretation.

    White is the sensor's full-scale value (2**bit_depth - 1). Black comes from libcamera's
    per-channel `SensorBlackLevels` when reported (left-justified to 16 bits, as libcamera
    gives it), else 0.
    """
    white = (1 << bit_depth) - 1
    black = metadata.get("SensorBlackLevels", 0)
    if isinstance(black, (list, tuple)):
        black = list(black)
    return black, white


def _parse_resolution(value: str) -> tuple[int, int]:
    try:
        w, h = value.lower().split("x")
        return int(w), int(h)
    except (ValueError, AttributeError):
        return 4056, 3040
