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

from .. import db
from ..scheduler import (
    estimate_timepoint_seconds,
    expected_timepoints,
    schedule_experiment,
    unschedule_experiment,
)

router = APIRouter(prefix="/api/experiments", tags=["experiments"])


def _with_progress(exp: dict[str, Any]) -> dict[str, Any]:
    """Augment an experiment row with derived progress fields for the UI."""
    names = [a["name"] for a in exp["acquisitions"]]
    timepoints = expected_timepoints(exp["interval_seconds"], exp["duration_seconds"])
    by_acq = db.count_experiment_images_by_acquisition(exp["id"])
    captured = sum(by_acq.values())
    remaining = 0.0
    if exp["status"] == "running":
        started = datetime.fromisoformat(exp["started_at"])
        end = started.timestamp() + exp["duration_seconds"]
        remaining = max(0.0, end - datetime.now(UTC).timestamp())
    return {
        **exp,
        "acquisition_names": names,
        "frames_captured": captured,
        "frames_by_acquisition": {n: by_acq.get(n, 0) for n in names},
        # A timepoint counts once its slowest acquisition has a frame for it.
        "timepoints_captured": min((by_acq.get(n, 0) for n in names), default=0),
        "expected_timepoints": timepoints,
        "expected_total": timepoints * len(names),
        "seconds_remaining": remaining,
    }


def _parse_acquisitions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate the run's acquisition list, or build a single one from the legacy
    top-level ``settings`` when no list is given."""
    raw = payload.get("acquisitions")
    if raw is None:
        settings = payload.get("settings")
        if not isinstance(settings, dict):
            raise HTTPException(status_code=400, detail="settings must be an object")
        return [{"name": db.DEFAULT_ACQUISITION, "settings": settings}]

    if not isinstance(raw, list) or not raw:
        raise HTTPException(status_code=400, detail="acquisitions must be a non-empty list")
    acquisitions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail="each acquisition must be an object")
        name = str(item.get("name", "")).strip()
        if not name:
            raise HTTPException(status_code=400, detail="every acquisition needs a name")
        if name in seen:
            raise HTTPException(status_code=400, detail=f"duplicate acquisition name {name!r}")
        seen.add(name)
        settings = item.get("settings")
        if not isinstance(settings, dict):
            raise HTTPException(
                status_code=400, detail=f"acquisition {name!r}: settings must be an object"
            )
        acquisitions.append({"name": name, "settings": settings})
    return acquisitions


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

    acquisitions = _parse_acquisitions(payload)

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
    # Every acquisition must fit inside one interval, or timepoints would be silently
    # dropped (the capture job never overlaps itself).
    needed = estimate_timepoint_seconds(acquisitions)
    if needed > interval:
        raise HTTPException(
            status_code=400,
            detail=(
                f"one timepoint needs ~{needed:.0f} s to capture all acquisitions "
                f"(~3× each exposure plus overhead), longer than the {interval:.0f} s "
                "interval; lengthen the interval or shorten the exposures"
            ),
        )

    if db.get_active_experiment() is not None:
        raise HTTPException(
            status_code=409, detail="a timecourse run is already active; stop it first"
        )

    now = datetime.now(UTC).isoformat()
    exp_id = db.insert_experiment(
        name=name,
        notes=notes,
        settings=acquisitions[0]["settings"],
        acquisitions=acquisitions,
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
def experiment_images(
    experiment_id: int, limit: int = 500, acquisition: str | None = None
) -> list[dict[str, Any]]:
    if db.get_experiment(experiment_id) is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    return db.list_images(limit=limit, experiment_id=experiment_id, acquisition=acquisition)


@router.post("/{experiment_id}/stop")
def stop_experiment(request: Request, experiment_id: int) -> dict[str, Any]:
    exp = db.get_experiment(experiment_id)
    if exp is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    unschedule_experiment(request.app.state.scheduler, experiment_id)
    if exp["status"] == "running":
        db.set_experiment_status(experiment_id, "stopped", ended_at=datetime.now(UTC).isoformat())
    return _with_progress(db.get_experiment(experiment_id))
