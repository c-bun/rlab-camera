"""Mock camera backend for development and tests (no hardware required).

Generates a synthetic image and burns the requested settings onto it, so the
capture/download/experiment flows can be exercised end to end on a laptop or in CI.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from .base import CameraBackend, CameraControl, CaptureResult
from .controls import MANUAL_CONTROLS


class MockCamera(CameraBackend):
    name = "mock"

    def get_controls(self) -> list[CameraControl]:
        return list(MANUAL_CONTROLS)

    def capture(self, settings: dict[str, Any], dest: Path) -> CaptureResult:
        applied: dict[str, Any] = {}
        for ctrl in MANUAL_CONTROLS:
            applied[ctrl.name] = _coerce(ctrl, settings.get(ctrl.name, ctrl.default))

        width, height = _parse_resolution(applied.get("resolution", "1332x990"))
        image_format = str(applied.get("image_format", "jpeg")).lower()

        # A synthetic gradient so successive captures look different and the file
        # is a valid image; overlay the applied settings for visual confirmation.
        img = Image.new("RGB", (width, height))
        px = img.load()
        for y in range(height):
            shade = int(255 * y / max(height - 1, 1))
            for x in range(0, width, 8):  # stride keeps mock capture fast at full res
                for dx in range(min(8, width - x)):
                    px[x + dx, y] = (shade, (shade + 64) % 256, (shade + 128) % 256)

        draw = ImageDraw.Draw(img)
        stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%SZ")
        lines = [f"MOCK CAMERA  {stamp}", f"{width}x{height} {image_format}"]
        lines += [f"{k}={v}" for k, v in applied.items() if k not in ("resolution", "image_format")]
        draw.multiline_text((10, 10), "\n".join(lines), fill=(255, 255, 255))

        dest.parent.mkdir(parents=True, exist_ok=True)
        pil_format = "JPEG" if image_format in ("jpg", "jpeg") else image_format.upper()
        img.save(dest, format=pil_format)

        return CaptureResult(
            path=dest,
            width=width,
            height=height,
            image_format=image_format,
            applied_settings=applied,
        )


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
