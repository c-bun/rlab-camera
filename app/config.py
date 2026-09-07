"""Runtime paths and settings, overridable by environment variables."""

from __future__ import annotations

import os
from pathlib import Path

# Root for all mutable app data (kept out of git via .gitignore).
DATA_DIR = Path(os.environ.get("RLAB_DATA_DIR", "data")).resolve()
IMAGES_DIR = DATA_DIR / "images"
# Cached JPEG thumbnails, used to preview formats browsers can't render inline (TIFF).
THUMBS_DIR = DATA_DIR / "thumbs"
DB_PATH = Path(os.environ.get("RLAB_DB_PATH", str(DATA_DIR / "rlab.db"))).resolve()

# BLE addresses (or names) of the LED illumination panels, comma-separated. Empty off-Pi;
# on the Pi set RLAB_PANELS so the "auto" illumination backend picks the Bluetooth panels.
PANELS = [p.strip() for p in os.environ.get("RLAB_PANELS", "").split(",") if p.strip()]

# Max seconds the capture path waits for a panel's "I'm on" render ack before proceeding
# anyway (a dark-frame safety net, not the normal path — the panel usually acks in well
# under this). Tunable so a slow link can be given more slack.
ILLUM_ACK_TIMEOUT_S = float(os.environ.get("RLAB_ILLUM_ACK_TIMEOUT_S", "1.0"))


def ensure_dirs() -> None:
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    THUMBS_DIR.mkdir(parents=True, exist_ok=True)
