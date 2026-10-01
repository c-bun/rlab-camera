"""Timecourse experiment API + scheduler tests.

Deliberately deterministic: they do not wait for APScheduler to fire on its own
(that is timing-flaky). Where a captured frame is needed, ``perform_capture`` is
called directly, and scheduler behaviour is checked via reconcile/stop rather than
by observing real interval firing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

_RUN = {
    "name": "test run",
    "notes": "sample A",
    "interval_seconds": 60,
    "duration_seconds": 600,
    "settings": {"resolution": "1332x990", "ExposureTime": 5000},
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
        settings={},
        interval_seconds=60,
        duration_seconds=600,
        started_at=now,
        created_at=now,
    )

    img = perform_capture({}, experiment_id=exp_id)
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
        settings={},
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
        settings={},
        interval_seconds=60,
        duration_seconds=3600,  # still well within the window
        started_at=started,
        created_at=started,
    )
    sched = scheduler.make_scheduler()
    scheduler.reconcile_on_startup(sched)
    assert db.get_experiment(exp_id)["status"] == "running"
    assert sched.get_job(f"exp-{exp_id}") is not None


# --- Multi-acquisition runs (e.g. illuminated growth frame + dark luminescence frame) ---

_FLASH = {"ExposureTime": 5000, "illum_enable": True, "illum_color": "#ffffff"}
_DARK = {"ExposureTime": 5_000_000, "illum_enable": False}
_MULTI_RUN = {
    "name": "lux",
    "interval_seconds": 600,
    "duration_seconds": 3600,
    "acquisitions": [
        {"name": "brightfield", "settings": _FLASH},
        {"name": "luminescence", "settings": _DARK},
    ],
}


@pytest.fixture()
def unscheduled(client, monkeypatch):
    """POST runs without arming jobs: a created run fires its first capture at once on
    a background thread that can outlive the test (the lifespan shuts the scheduler
    down with wait=False) and write frames into the next test's database."""
    from app.routers import experiments

    monkeypatch.setattr(experiments, "schedule_experiment", lambda *a, **k: None)


def _insert_multi_run():
    from app import db

    now = datetime.now(UTC).isoformat()
    return db.insert_experiment(
        name="lux",
        notes=None,
        settings=_FLASH,
        acquisitions=_MULTI_RUN["acquisitions"],
        interval_seconds=600,
        duration_seconds=3600,
        started_at=now,
        created_at=now,
    )


def test_start_multi_acquisition_run(client, unscheduled):
    exp = client.post("/api/experiments", json=_MULTI_RUN).json()
    assert exp["acquisition_names"] == ["brightfield", "luminescence"]
    assert [a["name"] for a in exp["acquisitions"]] == ["brightfield", "luminescence"]
    # floor(3600/600)+1 == 7 timepoints, each capturing both acquisitions.
    assert exp["expected_timepoints"] == 7
    assert exp["expected_total"] == 14
    # The first acquisition's settings double as the run's legacy `settings`.
    assert exp["settings"] == _FLASH


def test_legacy_settings_payload_is_single_default_acquisition(client, unscheduled):
    exp = client.post("/api/experiments", json=_RUN).json()
    assert exp["acquisition_names"] == ["default"]
    assert exp["acquisitions"][0]["settings"] == _RUN["settings"]


def test_acquisition_validation(client, unscheduled):
    base = {k: v for k, v in _MULTI_RUN.items() if k != "acquisitions"}

    def post(acqs):
        return client.post("/api/experiments", json={**base, "acquisitions": acqs})

    assert post([]).status_code == 400
    assert post([{"name": " ", "settings": {}}]).status_code == 400
    assert post([{"name": "a", "settings": {}}, {"name": "a", "settings": {}}]).status_code == 400
    assert post([{"name": "a", "settings": "nope"}]).status_code == 400


def test_timepoint_that_cannot_fit_in_interval_rejected(client, unscheduled):
    # A 60 s dark exposure costs ~3 exposures (~180 s) — too long for a 60 s interval.
    resp = client.post(
        "/api/experiments",
        json={
            **_MULTI_RUN,
            "interval_seconds": 60,
            "acquisitions": [{"name": "lum", "settings": {"ExposureTime": 60_000_000}}],
        },
    )
    assert resp.status_code == 400
    assert "interval" in resp.json()["detail"]


def test_timepoint_estimate_covers_switch_from_long_exposure():
    from app.scheduler import estimate_timepoint_seconds

    # Measured on the Pi: a 20 ms frame after a 5 s one took ~25 s to arrive, and the
    # whole flash + dark timepoint ~30 s. The estimate must not undershoot that.
    needed = estimate_timepoint_seconds(_MULTI_RUN["acquisitions"])
    assert 30 <= needed <= 45
    # A single acquisition never switches controls, so it pays no drain.
    assert estimate_timepoint_seconds([{"name": "a", "settings": _DARK}]) == 12


def test_capture_job_takes_every_acquisition(client):
    from app import db, scheduler

    exp_id = _insert_multi_run()
    scheduler._capture_job(exp_id)

    frames = sorted(db.list_images(experiment_id=exp_id), key=lambda i: i["id"])
    # In order, both at timepoint 0, each with its own illumination state.
    assert [f["acquisition"] for f in frames] == ["brightfield", "luminescence"]
    assert [f["timepoint"] for f in frames] == [0, 0]
    assert frames[0]["settings"]["illum_enable"] is True
    assert frames[1]["settings"]["illum_enable"] is False
    assert frames[1]["settings"]["ExposureTime"] == 5_000_000
    # Tags are persisted in the settings too (and so embedded in the TIFF on the Pi).
    assert frames[1]["settings"]["acquisition"] == "luminescence"
    assert frames[1]["filename"].endswith("_luminescence.tiff")

    progress = client.get(f"/api/experiments/{exp_id}").json()
    assert progress["frames_by_acquisition"] == {"brightfield": 1, "luminescence": 1}
    assert progress["timepoints_captured"] == 1

    only_lum = client.get(f"/api/experiments/{exp_id}/images?acquisition=luminescence").json()
    assert [i["id"] for i in only_lum] == [frames[1]["id"]]


def test_capture_job_stops_between_acquisitions(client, monkeypatch):
    from app import db, scheduler

    exp_id = _insert_multi_run()
    real_capture = scheduler.perform_capture

    def capture_then_stop(*args, **kwargs):
        img = real_capture(*args, **kwargs)
        db.set_experiment_status(exp_id, "stopped", ended_at="now")  # user hits Stop
        return img

    monkeypatch.setattr(scheduler, "perform_capture", capture_then_stop)
    scheduler._capture_job(exp_id)
    # The long dark exposure is skipped once the run is stopped.
    assert [f["acquisition"] for f in db.list_images(experiment_id=exp_id)] == ["brightfield"]
    assert db.get_experiment(exp_id)["status"] == "stopped"


def test_final_timepoint_completes_despite_finalize(client, monkeypatch):
    """The finalize job can flip the run to complete mid-way through the last
    timepoint; the remaining acquisitions must still be captured."""
    from app import db, scheduler

    exp_id = _insert_multi_run()
    real_capture = scheduler.perform_capture

    def capture_then_finalize(*args, **kwargs):
        img = real_capture(*args, **kwargs)
        db.set_experiment_status(exp_id, "complete", ended_at="now")
        return img

    monkeypatch.setattr(scheduler, "perform_capture", capture_then_finalize)
    scheduler._capture_job(exp_id)
    assert len(db.list_images(experiment_id=exp_id)) == 2


def test_init_db_migrates_old_schema(tmp_path, monkeypatch):
    import importlib
    import sqlite3

    db_path = tmp_path / "old.db"
    monkeypatch.setenv("RLAB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RLAB_DB_PATH", str(db_path))
    from app import config

    importlib.reload(config)
    from app import db

    importlib.reload(db)

    # The schema as first deployed: no acquisition/timepoint/acquisitions_json columns.
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE images (id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT NOT NULL,
            captured_at TEXT NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL,
            image_format TEXT NOT NULL, settings_json TEXT NOT NULL, experiment_id INTEGER);
        CREATE TABLE experiments (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            notes TEXT, settings_json TEXT NOT NULL, interval_seconds REAL NOT NULL,
            duration_seconds REAL NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
            started_at TEXT NOT NULL, ended_at TEXT);
        INSERT INTO experiments (name, settings_json, interval_seconds, duration_seconds,
            status, created_at, started_at)
            VALUES ('old', '{"ExposureTime": 1}', 60, 600, 'complete', 'x', 'x');
        INSERT INTO images (filename, captured_at, width, height, image_format,
            settings_json, experiment_id) VALUES ('a.tiff', 'x', 1, 1, 'tiff', '{}', 1);
        """
    )
    conn.commit()
    conn.close()

    db.init_db()
    db.init_db()  # idempotent

    exp = db.get_experiment(1)
    assert exp["acquisitions"] == [{"name": "default", "settings": {"ExposureTime": 1}}]
    img = db.get_image(1)
    assert img["acquisition"] is None and img["timepoint"] is None
    assert db.count_experiment_images_by_acquisition(1) == {"default": 1}
