"""Mock camera backend for development and tests (no hardware required).

Generates a synthetic image and burns the requested settings onto it, so the
capture/download/experiment flows can be exercised end to end on a laptop or in CI.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from .base import CameraBackend, CameraControl, CaptureResult
from .controls import FIXED_WHITE_BALANCE, MANUAL_CONTROLS
from .raw import bayer_to_channels
from .tiff import write_imagej_channel_stack

# Small fixed size for the live view, independent of the `resolution` control, so
# preview stays cheap even when captures are configured for full sensor resolution.
_PREVIEW_SIZE = (1014, 760)

# CFA the mock pretends its sensor uses (the real IMX477 reports its own via picamera2).
_MOCK_CFA = "RGGB"
# 12-bit sensor: raw values live in [0, 4095] inside a uint16 container.
_MOCK_BIT_DEPTH = 12
_MOCK_WHITE_LEVEL = (1 << _MOCK_BIT_DEPTH) - 1
_MOCK_BLACK_LEVEL = 0


class MockCamera(CameraBackend):
    name = "mock"

    def get_controls(self) -> list[CameraControl]:
        return list(MANUAL_CONTROLS)

    def capture(self, settings: dict[str, Any], dest: Path) -> CaptureResult:
        applied = self._apply(settings)
        read_w, read_h = _parse_resolution(applied.get("resolution", "1332x990"))
        image_format = "tiff"

        # Synthesize a raw Bayer mosaic at the sensor readout size, then split it into an
        # R/G/B channel stack with the same no-interpolation path the real backend uses.
        mosaic = self._synthesize_mosaic(read_w, read_h)
        stack = bayer_to_channels(mosaic, _MOCK_CFA)
        height, width = stack.shape[1], stack.shape[2]

        applied = {
            **applied,
            "resolution": f"{read_w}x{read_h}",
            "image_format": image_format,
            "raw_cfa": _MOCK_CFA,
            "raw_bit_depth": _MOCK_BIT_DEPTH,
            "raw_black_level": _MOCK_BLACK_LEVEL,
            "raw_white_level": _MOCK_WHITE_LEVEL,
            "channels": "R,G,B (G = mean of both Bayer greens)",
        }

        dest.parent.mkdir(parents=True, exist_ok=True)
        # 16-bit composite stack of raw values, capture settings embedded as ImageJ metadata.
        write_imagej_channel_stack(dest, stack, applied)

        return CaptureResult(
            path=dest,
            width=width,
            height=height,
            image_format=image_format,
            applied_settings=applied,
        )

    def _synthesize_mosaic(self, width: int, height: int) -> np.ndarray:
        """A synthetic 12-bit Bayer mosaic; R/G/B sites get distinct gradients so the
        split channels visibly differ (successive frames differ via a small time jitter)."""
        yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
        gx = xx / max(width - 1, 1)
        gy = yy / max(height - 1, 1)
        jitter = (datetime.now(UTC).microsecond % 256) / 255.0

        mosaic = np.zeros((height, width), dtype=np.uint16)
        # RGGB tile: R at (0,0), G at (0,1)&(1,0), B at (1,1).
        white = _MOCK_WHITE_LEVEL
        mosaic[0::2, 0::2] = (gx[0::2, 0::2] * white).astype(np.uint16)  # red
        mosaic[0::2, 1::2] = (gy[0::2, 1::2] * white).astype(np.uint16)  # green
        mosaic[1::2, 0::2] = (gy[1::2, 0::2] * white).astype(np.uint16)  # green
        mosaic[1::2, 1::2] = (
            ((gx + gy) * 0.5 + jitter * 0.1).clip(0, 1)[1::2, 1::2] * white
        ).astype(np.uint16)  # blue
        return mosaic

    def preview(self, settings: dict[str, Any]) -> bytes:
        applied = self._apply(settings)
        width, height = _PREVIEW_SIZE
        img = self._render(width, height, "jpeg", applied)
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        return buf.getvalue()

    def _apply(self, settings: dict[str, Any]) -> dict[str, Any]:
        """Coerce/clamp requested values against the canonical control set."""
        return {
            **{
                ctrl.name: _coerce(ctrl, settings.get(ctrl.name, ctrl.default))
                for ctrl in MANUAL_CONTROLS
            },
            **FIXED_WHITE_BALANCE,
        }

    def _render(
        self, width: int, height: int, image_format: str, applied: dict[str, Any]
    ) -> Image.Image:
        # A synthetic gradient so successive frames look different and the image is
        # valid; overlay the applied settings for visual confirmation.
        img = Image.new("RGB", (width, height))
        px = img.load()
        for y in range(height):
            shade = int(255 * y / max(height - 1, 1))
            for x in range(0, width, 8):  # stride keeps the render fast at full res
                for dx in range(min(8, width - x)):
                    px[x + dx, y] = (shade, (shade + 64) % 256, (shade + 128) % 256)

        draw = ImageDraw.Draw(img)
        stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%SZ")
        lines = [f"MOCK CAMERA  {stamp}", f"{width}x{height} {image_format}"]
        lines += [f"{k}={v}" for k, v in applied.items() if k not in ("resolution", "image_format")]
        draw.multiline_text((10, 10), "\n".join(lines), fill=(255, 255, 255))
        return img


def _coerce(ctrl: CameraControl, value: Any) -> Any:
    if value is None:
        return ctrl.default
    if ctrl.kind == "bool":
        if isinstance(value, str):
            return value.lower() in ("1", "true", "on", "yes")
        return bool(value)
    if ctrl.kind == "number":
        try:
            num = float(value)
        except (TypeError, ValueError):
            return ctrl.default
        if ctrl.min is not None:
            num = max(num, ctrl.min)
        if ctrl.max is not None:
            num = min(num, ctrl.max)
        return num
    return value


def _parse_resolution(value: str) -> tuple[int, int]:
    try:
        w, h = value.lower().split("x")
        return int(w), int(h)
    except (ValueError, AttributeError):
        return 1332, 990
