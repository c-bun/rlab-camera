"""SQLite persistence for captured-image metadata.

Kept deliberately small for the MVP: one `images` table. Experiment/scheduling
tables will be added alongside the APScheduler work.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from .config import DB_PATH, ensure_dirs

_SCHEMA = """
CREATE TABLE IF NOT EXISTS images (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    filename      TEXT NOT NULL,
    captured_at   TEXT NOT NULL,
    width         INTEGER NOT NULL,
    height        INTEGER NOT NULL,
    image_format  TEXT NOT NULL,
    settings_json TEXT NOT NULL,
    experiment_id INTEGER
);
"""


def connect() -> sqlite3.Connection:
    ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(_SCHEMA)


def insert_image(
    *,
    filename: str,
    captured_at: str,
    width: int,
    height: int,
    image_format: str,
    settings: dict[str, Any],
    experiment_id: int | None = None,
) -> int:
    with connect() as conn:
        cur = conn.execute(
            """INSERT INTO images
               (filename, captured_at, width, height, image_format, settings_json, experiment_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                filename,
                captured_at,
                width,
                height,
                image_format,
                json.dumps(settings, default=str),
                experiment_id,
            ),
        )
        return int(cur.lastrowid)


def list_images(limit: int = 200) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM images ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_image(image_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM images WHERE id = ?", (image_id,)).fetchone()
    return _row_to_dict(row) if row else None


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["settings"] = json.loads(d.pop("settings_json"))
    return d
