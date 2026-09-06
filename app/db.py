"""SQLite persistence for captured-image metadata.

Tables: `images` (every capture, optionally tagged with the `experiment_id` of the
timecourse run that produced it), `presets` (named control-panel settings), and
`experiments` (timecourse run definitions + status; SQLite is the source of truth
the scheduler re-arms from on startup).
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

CREATE TABLE IF NOT EXISTS presets (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL UNIQUE,
    settings_json TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS experiments (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL,
    notes            TEXT,
    settings_json    TEXT NOT NULL,
    interval_seconds REAL NOT NULL,
    duration_seconds REAL NOT NULL,
    status           TEXT NOT NULL,      -- running | complete | stopped
    created_at       TEXT NOT NULL,
    started_at       TEXT NOT NULL,
    ended_at         TEXT
);

CREATE INDEX IF NOT EXISTS idx_images_experiment ON images(experiment_id);
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


def list_images(limit: int = 200, experiment_id: int | None = None) -> list[dict[str, Any]]:
    with connect() as conn:
        if experiment_id is None:
            rows = conn.execute(
                "SELECT * FROM images ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM images WHERE experiment_id = ? ORDER BY id DESC LIMIT ?",
                (experiment_id, limit),
            ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_image(image_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM images WHERE id = ?", (image_id,)).fetchone()
    return _row_to_dict(row) if row else None


def list_ungrouped_images(limit: int = 1000) -> list[dict[str, Any]]:
    """Ad-hoc captures — those not tagged with a timecourse run — newest first."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM images WHERE experiment_id IS NULL ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def list_images_by_ids(ids: list[int]) -> list[dict[str, Any]]:
    """Fetch specific images by id (used to assemble batch-download zips)."""
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM images WHERE id IN ({placeholders}) ORDER BY id DESC",
            tuple(ids),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def experiment_gallery_summaries() -> list[dict[str, Any]]:
    """One row per timecourse run that has captured frames: frame count and the id
    of its newest frame (used as the stack's cover thumbnail). Single aggregate
    query — no per-experiment COUNT(*) loop."""
    with connect() as conn:
        rows = conn.execute(
            """SELECT experiment_id, COUNT(*) AS n, MAX(id) AS cover_id
               FROM images
               WHERE experiment_id IS NOT NULL
               GROUP BY experiment_id"""
        ).fetchall()
    return [
        {"experiment_id": r["experiment_id"], "count": r["n"], "cover_id": r["cover_id"]}
        for r in rows
    ]


def upsert_preset(
    *,
    name: str,
    settings: dict[str, Any],
    created_at: str,
) -> int:
    """Save a named preset, overwriting any existing preset with the same name."""
    with connect() as conn:
        cur = conn.execute(
            """INSERT INTO presets (name, settings_json, created_at)
               VALUES (?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET
                   settings_json = excluded.settings_json,
                   created_at    = excluded.created_at""",
            (name, json.dumps(settings, default=str), created_at),
        )
        # lastrowid is only meaningful on insert; on update look the id up by name.
        row = conn.execute("SELECT id FROM presets WHERE name = ?", (name,)).fetchone()
        return int(row["id"]) if row else int(cur.lastrowid)


def list_presets() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM presets ORDER BY name").fetchall()
    return [_row_to_dict(r) for r in rows]


def get_preset(preset_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM presets WHERE id = ?", (preset_id,)).fetchone()
    return _row_to_dict(row) if row else None


def delete_preset(preset_id: int) -> bool:
    with connect() as conn:
        cur = conn.execute("DELETE FROM presets WHERE id = ?", (preset_id,))
        return cur.rowcount > 0


# --- Experiments (timecourse runs) ---


def insert_experiment(
    *,
    name: str,
    notes: str | None,
    settings: dict[str, Any],
    interval_seconds: float,
    duration_seconds: float,
    started_at: str,
    created_at: str,
) -> int:
    with connect() as conn:
        cur = conn.execute(
            """INSERT INTO experiments
               (name, notes, settings_json, interval_seconds, duration_seconds,
                status, created_at, started_at, ended_at)
               VALUES (?, ?, ?, ?, ?, 'running', ?, ?, NULL)""",
            (
                name,
                notes,
                json.dumps(settings, default=str),
                interval_seconds,
                duration_seconds,
                created_at,
                started_at,
            ),
        )
        return int(cur.lastrowid)


def get_experiment(experiment_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM experiments WHERE id = ?", (experiment_id,)).fetchone()
    return _row_to_dict(row) if row else None


def list_experiments() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM experiments ORDER BY id DESC").fetchall()
    return [_row_to_dict(r) for r in rows]


def get_active_experiment() -> dict[str, Any] | None:
    """The single running experiment, if any. The app enforces at most one at a time."""
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM experiments WHERE status = 'running' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return _row_to_dict(row) if row else None


def set_experiment_status(experiment_id: int, status: str, *, ended_at: str | None = None) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE experiments SET status = ?, ended_at = ? WHERE id = ?",
            (status, ended_at, experiment_id),
        )


def count_experiment_images(experiment_id: int) -> int:
    with connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM images WHERE experiment_id = ?", (experiment_id,)
        ).fetchone()
    return int(row["n"])


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["settings"] = json.loads(d.pop("settings_json"))
    return d
