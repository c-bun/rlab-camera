"""Runtime paths and settings, overridable by environment variables."""

from __future__ import annotations

import os
from pathlib import Path

# Root for all mutable app data (kept out of git via .gitignore).
DATA_DIR = Path(os.environ.get("RLAB_DATA_DIR", "data")).resolve()
IMAGES_DIR = DATA_DIR / "images"
DB_PATH = Path(os.environ.get("RLAB_DB_PATH", str(DATA_DIR / "rlab.db"))).resolve()


def ensure_dirs() -> None:
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
