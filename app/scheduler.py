"""APScheduler wiring for timecourse runs.

SQLite (the ``experiments`` table) is the source of truth; APScheduler's own
jobstore stays in memory. A run is one interval job that, on each fire (a
*timepoint*), captures every one of the run's acquisitions back to back in order —
e.g. an illuminated frame for growth, then a long dark exposure for bioluminescence —
bounded by an ``end_date`` derived from the run's duration, plus a one-shot
job at that deadline that flips the run to ``complete`` (so it finalizes even if a
capture errored). On startup ``reconcile_on_startup`` re-arms the single active run
from the DB — this is what makes a run survive a service restart.

The scheduler instance lives on ``app.state.scheduler`` (created in the lifespan),
not as a module global, so tests that reload the app get a fresh one.
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime, timedelta
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from . import db
from .capture_service import perform_capture

log = logging.getLogger(__name__)


def make_scheduler() -> BackgroundScheduler:
    return BackgroundScheduler(timezone="UTC")


def expected_timepoints(interval_seconds: float, duration_seconds: float) -> int:
    """Timepoints a run should reach: one at t0 plus one per whole interval within
    the duration."""
    if interval_seconds <= 0:
        return 0
    return math.floor(duration_seconds / interval_seconds) + 1


def expected_total(
    interval_seconds: float, duration_seconds: float, n_acquisitions: int = 1
) -> int:
    """Frames a run should produce: every acquisition at every timepoint."""
    return expected_timepoints(interval_seconds, duration_seconds) * n_acquisitions


# Rough per-acquisition cost beyond the exposure itself: sensor reconfigure, the panel
# render-ack handshake, encoding and writing the TIFF.
_ACQUISITION_OVERHEAD_SECONDS = 2.0


def estimate_timepoint_seconds(acquisitions: list[dict[str, Any]]) -> float:
    """Conservative wall-clock estimate for capturing every acquisition once.

    Each capture costs ~3 exposures, not 1: a frame already in flight at the old
    settings, the settling frame dropped after ``set_controls``, then the kept frame.
    Acquisitions alternate controls every timepoint, so every capture pays this.
    """
    total = 0.0
    for acq in acquisitions:
        exposure_us = acq["settings"].get("ExposureTime") or 0
        total += 3 * float(exposure_us) / 1e6 + _ACQUISITION_OVERHEAD_SECONDS
    return total


def _end_time(exp: dict[str, Any]) -> datetime:
    started = datetime.fromisoformat(exp["started_at"])
    return started + timedelta(seconds=exp["duration_seconds"])


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _timepoint_index(exp: dict[str, Any]) -> int:
    """Which timepoint the current fire is, from its offset against the run start."""
    started = datetime.fromisoformat(exp["started_at"])
    elapsed = (datetime.now(UTC) - started).total_seconds()
    return max(0, round(elapsed / exp["interval_seconds"]))


def _capture_job(experiment_id: int) -> None:
    """One timepoint for a run — every acquisition in order — then finalize if the run
    is complete."""
    exp = db.get_experiment(experiment_id)
    if not exp or exp["status"] != "running":
        return
    timepoint = _timepoint_index(exp)
    for i, acq in enumerate(exp["acquisitions"]):
        # Re-check between acquisitions so Stop (or delete) takes effect before a long
        # exposure rather than after it. Only a stop counts: the finalize job may flip
        # the run to "complete" while the final timepoint is still mid-sequence, and
        # that timepoint should still get all of its acquisitions.
        if i > 0:
            current = db.get_experiment(experiment_id)
            if current is None or current["status"] == "stopped":
                return
        try:
            perform_capture(
                acq["settings"],
                experiment_id=experiment_id,
                acquisition=acq["name"],
                timepoint=timepoint,
            )
        except Exception:  # a single failed frame must not kill the run
            log.exception(
                "timecourse capture failed for experiment %s, acquisition %r",
                experiment_id,
                acq["name"],
            )
    total = expected_total(
        exp["interval_seconds"], exp["duration_seconds"], len(exp["acquisitions"])
    )
    current = db.get_experiment(experiment_id)
    if (
        current
        and current["status"] == "running"  # not stopped, or finalized, mid-timepoint
        and db.count_experiment_images(experiment_id) >= total
    ):
        db.set_experiment_status(experiment_id, "complete", ended_at=_now_iso())


def _finalize_job(experiment_id: int) -> None:
    """Deadline reached: mark the run complete if it is still running (covers runs
    whose captures errored and so never hit the frame count)."""
    exp = db.get_experiment(experiment_id)
    if exp and exp["status"] == "running":
        db.set_experiment_status(experiment_id, "complete", ended_at=_now_iso())


def schedule_experiment(
    scheduler: BackgroundScheduler, exp: dict[str, Any], *, run_now: bool
) -> None:
    """Arm the capture + finalize jobs for a running experiment.

    ``run_now`` forces an immediate first capture (new runs); on a restart resume it
    is False so captures continue on the original cadence.
    """
    exp_id = exp["id"]
    interval = exp["interval_seconds"]
    started = datetime.fromisoformat(exp["started_at"])
    end = _end_time(exp)
    # A run of duration D at interval I should capture at t = 0, I, … , D — that's
    # expected_total() frames. Extend the trigger's end_date by half an interval so
    # the boundary fire at exactly t = D is included despite millisecond drift, while
    # staying well short of the next boundary (a full interval away).
    capture_end = end + timedelta(seconds=interval / 2)

    kwargs: dict[str, Any] = {}
    if run_now:
        kwargs["next_run_time"] = datetime.now(UTC)

    scheduler.add_job(
        _capture_job,
        trigger=IntervalTrigger(seconds=interval, start_date=started, end_date=capture_end),
        args=[exp_id],
        id=f"exp-{exp_id}",
        max_instances=1,  # a long exposure must not overlap the next fire
        coalesce=True,  # collapse a burst of missed fires (e.g. after a restart)
        misfire_grace_time=max(int(interval), 30),
        replace_existing=True,
        **kwargs,
    )
    # Finalize a beat after the last capture window so that capture finalizes via the
    # frame count first — otherwise the two race and finalize can skip the final frame.
    scheduler.add_job(
        _finalize_job,
        trigger=DateTrigger(run_date=capture_end + timedelta(seconds=1)),
        args=[exp_id],
        id=f"exp-{exp_id}-final",
        misfire_grace_time=None,  # always run, however late
        replace_existing=True,
    )


def unschedule_experiment(scheduler: BackgroundScheduler, experiment_id: int) -> None:
    for job_id in (f"exp-{experiment_id}", f"exp-{experiment_id}-final"):
        try:
            scheduler.remove_job(job_id)
        except Exception:  # JobLookupError: already gone / never scheduled
            pass


def reconcile_on_startup(scheduler: BackgroundScheduler) -> None:
    """Re-arm (or finalize) the single active run after a (re)start."""
    exp = db.get_active_experiment()
    if not exp:
        return
    if datetime.now(UTC) >= _end_time(exp):
        db.set_experiment_status(exp["id"], "complete", ended_at=_now_iso())
    else:
        schedule_experiment(scheduler, exp, run_now=False)
