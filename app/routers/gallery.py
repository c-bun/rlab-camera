"""The Gallery page: every image in one place. Timecourse runs are grouped into a
single "stack" (cover thumbnail + frame count), ad-hoc captures each stand alone,
and any selection of runs and captures can be batch-downloaded as one zip with a
metadata manifest.

Split into two routers like ``experiments.py``: an ``/api/gallery`` API and a
prefix-less ``page_router`` for the HTML page.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import tempfile
import zipfile
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from starlette.background import BackgroundTask

from .. import config, db

router = APIRouter(prefix="/api/gallery", tags=["gallery"])


@router.get("")
def gallery() -> dict[str, Any]:
    """Everything the gallery grid needs: timecourse runs (with frames) as stacks,
    plus ad-hoc captures as standalone tiles."""
    summaries = {s["experiment_id"]: s for s in db.experiment_gallery_summaries()}
    experiments = []
    for exp in db.list_experiments():
        summary = summaries.get(exp["id"])
        if summary is None:
            # A run with no captured frames has no cover to show — skip it.
            continue
        experiments.append(
            {
                "id": exp["id"],
                "name": exp["name"],
                "notes": exp["notes"],
                "status": exp["status"],
                "interval_seconds": exp["interval_seconds"],
                "duration_seconds": exp["duration_seconds"],
                "created_at": exp["created_at"],
                "started_at": exp["started_at"],
                "ended_at": exp["ended_at"],
                "frames_captured": summary["count"],
                "cover_image_id": summary["cover_id"],
            }
        )
    return {"experiments": experiments, "images": db.list_ungrouped_images()}


def _sanitize(name: str) -> str:
    """Make an experiment name safe for use as a zip folder segment."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")
    return cleaned or "run"


@router.post("/download")
def download(payload: dict[str, Any]) -> FileResponse:
    """Zip up the selected captures and whole runs, plus a ``manifest.csv``.

    Body: ``{"image_ids": [int], "experiment_ids": [int]}``. Runs are resolved to
    all their frames; the two sets are unioned and deduped by image id.
    """
    image_ids = payload.get("image_ids") or []
    experiment_ids = payload.get("experiment_ids") or []
    if not isinstance(image_ids, list) or not isinstance(experiment_ids, list):
        raise HTTPException(status_code=400, detail="image_ids and experiment_ids must be lists")

    # Experiment names for zip folder labels.
    exp_names: dict[int, str] = {}
    rows_by_id: dict[int, dict[str, Any]] = {}

    for eid in experiment_ids:
        exp = db.get_experiment(int(eid))
        if exp is None:
            continue
        exp_names[exp["id"]] = exp["name"]
        for row in db.list_images(limit=100000, experiment_id=exp["id"]):
            rows_by_id[row["id"]] = row

    for row in db.list_images_by_ids([int(i) for i in image_ids]):
        rows_by_id[row["id"]] = row

    if not rows_by_id:
        raise HTTPException(status_code=400, detail="nothing selected to download")

    rows = sorted(rows_by_id.values(), key=lambda r: r["id"])

    tmp = tempfile.NamedTemporaryFile(prefix="rlab-gallery-", suffix=".zip", delete=False)
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            manifest = io.StringIO()
            writer = csv.writer(manifest)
            writer.writerow(
                [
                    "zip_path",
                    "id",
                    "experiment_id",
                    "experiment_name",
                    "captured_at",
                    "width",
                    "height",
                    "image_format",
                    "settings_json",
                ]
            )
            for row in rows:
                exp_id = row["experiment_id"]
                if exp_id is not None:
                    folder = f"{_sanitize(exp_names.get(exp_id, f'run_{exp_id}'))}_{exp_id}"
                    zip_path = f"{folder}/{row['filename']}"
                    exp_name = exp_names.get(exp_id, "")
                else:
                    zip_path = row["filename"]
                    exp_name = ""
                src = config.IMAGES_DIR / row["filename"]
                if src.exists():
                    zf.write(src, zip_path)
                writer.writerow(
                    [
                        zip_path,
                        row["id"],
                        exp_id if exp_id is not None else "",
                        exp_name,
                        row["captured_at"],
                        row["width"],
                        row["height"],
                        row["image_format"],
                        json.dumps(row["settings"], default=str),
                    ]
                )
            zf.writestr("manifest.csv", manifest.getvalue())
        tmp.close()
    except Exception:
        tmp.close()
        os.unlink(tmp.name)
        raise

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return FileResponse(
        tmp.name,
        media_type="application/zip",
        filename=f"rlab-gallery-{stamp}.zip",
        background=BackgroundTask(os.unlink, tmp.name),
    )


# The gallery page itself (no /api prefix), served from its own router.
page_router = APIRouter()


@page_router.get("/gallery", response_class=HTMLResponse)
def gallery_page(request: Request) -> HTMLResponse:
    from ..camera import get_camera

    templates = request.app.state.templates
    return templates.TemplateResponse(request, "gallery.html", {"backend": get_camera().name})
