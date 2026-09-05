"""Write a TIFF whose capture settings are readable in ImageJ/Fiji.

Both camera backends save TIFFs through `write_imagej_tiff` so the embedded metadata
is identical. picamera2 is *not* imported here — callers hand us a plain numpy array,
so this module imports fine on macOS for the mock backend and tests.

ImageJ reads acquisition metadata from the "Info" property, which tifffile stores in
the TIFF ImageDescription tag when `imagej=True`. In ImageJ the string shows up under
*Image ▸ Show Info…* and via `getInfoProperty("Info")` in a macro.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import tifffile


def build_info_string(info: dict[str, Any]) -> str:
    """Render the applied settings as newline-separated ``key=value`` lines.

    Nested/non-scalar values (e.g. picamera2 ``_sensor_metadata``) are JSON-encoded so
    they survive as readable text rather than a Python ``repr``.
    """
    lines: list[str] = []
    for key, value in info.items():
        if isinstance(value, (dict, list, tuple)):
            rendered = json.dumps(value, default=str)
        else:
            rendered = str(value)
        lines.append(f"{key}={rendered}")
    return "\n".join(lines)


def write_imagej_tiff(dest: Path, array: np.ndarray, info: dict[str, Any]) -> None:
    """Save `array` as a TIFF at `dest` with `info` embedded as an ImageJ Info property."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tifffile.imwrite(
        str(dest),
        np.asarray(array),
        imagej=True,
        metadata={"Info": build_info_string(info)},
    )
