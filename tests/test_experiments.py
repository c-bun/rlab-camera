"""Timecourse experiment API + scheduler tests.

Deliberately deterministic: they do not wait for APScheduler to fire on its own
(that is timing-flaky). Where a captured frame is needed, ``perform_capture`` is
called directly, and scheduler behaviour is checked via reconcile/stop rather than
by observing real interval firing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

_RUN = {
    "name": "test run",
    "notes": "sample A",
    "interval_seconds": 60,
    "duration_seconds": 600,
    "settings": {"resolution": "1332x990", "image_format": "jpeg", "ExposureTime": 5000},
}


def test_start_run(client):
    resp = client.post("/api/experiments", json=_RUN)
    assert resp.status_code == 200
    exp = resp.json()
    assert exp["status"] == "running"
    assert exp["name"] == "test run"
    assert exp["notes"] == "sample A"
    # one frame at t0 plus one per whole interval: floor(600/60)+1 == 11
    assert exp["expected_total"] == 11

    listing = client.get("/api/experiments").json()
    assert any(e["id"] == exp["id"] for e in listing)


def test_second_run_rejected(client):
    first = client.post("/api/experiments", json=_RUN)
    assert first.status_code == 200
    second = client.post("/api/experiments", json={**_RUN, "name": "another"})
    assert second.status_code == 409


def test_validation(client):
    assert client.post("/api/experiments", json={**_RUN, "name": " "}).status_code == 400
    assert client.post("/api/experiments", json={**_RUN, "interval_seconds": 0}).status_code == 400
    assert (
        client.post(
            "/api/experiments", json={**_RUN, "interval_seconds": 60, "duration_seconds": 30}
        ).status_code
        == 400
    )


def test_scoped_images(client):
    # Insert the run directly (no scheduler job, so no background capture races the
    # frame taken below) and capture one frame tagged to it via the shared helper.
    from app import db
    from app.capture_service import perform_capture

    now = datetime.now(UTC).isoformat()
    exp_id = db.insert_experiment(
        name="scope",
        notes=None,
        settings={"image_format": "jpeg"},
        interval_seconds=60,
        duration_seconds=600,
        started_at=now,
        created_at=now,
    )

    img = perform_capture({"image_format": "jpeg"}, experiment_id=exp_id)
    assert img["experiment_id"] == exp_id
    assert img["width"] > 0 and img["height"] > 0

    scoped = client.get(f"/api/experiments/{exp_id}/images").json()
    assert [i["id"] for i in scoped] == [img["id"]]

    # An unrelated (empty) run and a missing run.
    assert client.get(f"/api/experiments/{exp_id + 1}/images").status_code == 404


def test_stop_run(client):
    from app import main

    exp = client.post("/api/experiments", json=_RUN).json()
    assert main.app.state.scheduler.get_job(f"exp-{exp['id']}") is not None

    stopped = client.post(f"/api/experiments/{exp['id']}/stop").json()
    assert stopped["status"] == "stopped"
    assert stopped["ended_at"] is not None
    assert main.app.state.scheduler.get_job(f"exp-{exp['id']}") is None

    assert client.post("/api/experiments/9999/stop").status_code == 404


def test_reconcile_finalizes_past_window(client):
    from app import db, scheduler

    past = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    exp_id = db.insert_experiment(
        name="old",
        notes=None,
        settings={"image_format": "jpeg"},
        interval_seconds=60,
        duration_seconds=600,  # ended long ago
        started_at=past,
        created_at=past,
    )
    sched = scheduler.make_scheduler()
    scheduler.reconcile_on_startup(sched)
    assert db.get_experiment(exp_id)["status"] == "complete"
    assert sched.get_job(f"exp-{exp_id}") is None


def test_reconcile_rearms_active_run(client):
    from app import db, scheduler

    started = (datetime.now(UTC) - timedelta(seconds=30)).isoformat()
    exp_id = db.insert_experiment(
        name="ongoing",
        notes=None,
        settings={"image_format": "jpeg"},
        interval_seconds=60,
        duration_seconds=3600,  # still well within the window
        started_at=started,
        created_at=started,
    )
    sched = scheduler.make_scheduler()
    scheduler.reconcile_on_startup(sched)
    assert db.get_experiment(exp_id)["status"] == "running"
    assert sched.get_job(f"exp-{exp_id}") is not None
