"""Timecourse experiments: define a run (interval + duration), watch its progress,
and browse/download its frames while it is still capturing.

At most one run is active at a time — the camera is a single serialized resource, so
starting a second run while one is active is rejected (409). The scheduler lives on
``request.app.state.scheduler``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from .. import db
from ..scheduler import (
    expected_total,
    schedule_experiment,
    unschedule_experiment,
)

router = APIRouter(prefix="/api/experiments", tags=["experiments"])


def _with_progress(exp: dict[str, Any]) -> dict[str, Any]:
    """Augment an experiment row with derived progress fields for the UI."""
    total = expected_total(exp["interval_seconds"], exp["duration_seconds"])
    captured = db.count_experiment_images(exp["id"])
    remaining = 0.0
    if exp["status"] == "running":
        started = datetime.fromisoformat(exp["started_at"])
        end = started.timestamp() + exp["duration_seconds"]
        remaining = max(0.0, end - datetime.now(UTC).timestamp())
    return {
        **exp,
        "frames_captured": captured,
        "expected_total": total,
        "seconds_remaining": remaining,
    }


@router.get("")
def list_experiments() -> list[dict[str, Any]]:
    return [_with_progress(e) for e in db.list_experiments()]


@router.post("")
def create_experiment(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    name = str(payload.get("name", "")).strip()
    if not name:
        raise HTTPException(status_code=400, detail="experiment name is required")

    notes = payload.get("notes")
    notes = str(notes).strip() if notes not in (None, "") else None

    settings = payload.get("settings")
    if not isinstance(settings, dict):
        raise HTTPException(status_code=400, detail="settings must be an object")

    try:
        interval = float(payload.get("interval_seconds"))
        duration = float(payload.get("duration_seconds"))
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=400, detail="interval_seconds and duration_seconds must be numbers"
        ) from None
    if interval <= 0:
        raise HTTPException(status_code=400, detail="interval_seconds must be > 0")
    if duration < interval:
        raise HTTPException(status_code=400, detail="duration_seconds must be >= interval_seconds")

    if db.get_active_experiment() is not None:
        raise HTTPException(
            status_code=409, detail="a timecourse run is already active; stop it first"
        )

    now = datetime.now(UTC).isoformat()
    exp_id = db.insert_experiment(
        name=name,
        notes=notes,
        settings=settings,
        interval_seconds=interval,
        duration_seconds=duration,
        started_at=now,
        created_at=now,
    )
    exp = db.get_experiment(exp_id)
    schedule_experiment(request.app.state.scheduler, exp, run_now=True)
    return _with_progress(exp)


@router.get("/{experiment_id}")
def get_experiment(experiment_id: int) -> dict[str, Any]:
    exp = db.get_experiment(experiment_id)
    if exp is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    return _with_progress(exp)


@router.get("/{experiment_id}/images")
def experiment_images(experiment_id: int, limit: int = 500) -> list[dict[str, Any]]:
    if db.get_experiment(experiment_id) is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    return db.list_images(limit=limit, experiment_id=experiment_id)


@router.post("/{experiment_id}/stop")
def stop_experiment(request: Request, experiment_id: int) -> dict[str, Any]:
    exp = db.get_experiment(experiment_id)
    if exp is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    unschedule_experiment(request.app.state.scheduler, experiment_id)
    if exp["status"] == "running":
        db.set_experiment_status(experiment_id, "stopped", ended_at=datetime.now(UTC).isoformat())
    return _with_progress(db.get_experiment(experiment_id))


# The timecourse page itself (no /api prefix), served from its own router.
page_router = APIRouter()


@page_router.get("/timecourse", response_class=HTMLResponse)
def timecourse_page(request: Request) -> HTMLResponse:
    from ..camera import get_camera

    templates = request.app.state.templates
    return templates.TemplateResponse(request, "timecourse.html", {"backend": get_camera().name})
