"""Gallery API: grouping timecourse runs into stacks + batch-download zip."""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime


def _seed(client):
    """Two ad-hoc captures and one run with two frames. Returns the run id."""
    from app import db
    from app.capture_service import perform_capture

    manual = [perform_capture({})["id"] for _ in range(2)]

    now = datetime.now(UTC).isoformat()
    exp_id = db.insert_experiment(
        name="run one",
        notes="sample A",
        settings={},
        interval_seconds=60,
        duration_seconds=600,
        started_at=now,
        created_at=now,
    )
    frames = [perform_capture({}, experiment_id=exp_id)["id"] for _ in range(2)]
    return manual, exp_id, frames


def test_gallery_groups_runs_and_lists_captures(client):
    manual, exp_id, frames = _seed(client)

    data = client.get("/api/gallery").json()

    assert [e["id"] for e in data["experiments"]] == [exp_id]
    run = data["experiments"][0]
    assert run["frames_captured"] == 2
    assert run["cover_image_id"] == max(frames)  # newest frame is the cover
    assert run["name"] == "run one"

    # Ad-hoc captures are listed separately; run frames are not among them.
    listed = {i["id"] for i in data["images"]}
    assert listed == set(manual)
    assert not (listed & set(frames))


def test_run_without_frames_is_skipped(client):
    from app import db

    now = datetime.now(UTC).isoformat()
    db.insert_experiment(
        name="empty",
        notes=None,
        settings={},
        interval_seconds=60,
        duration_seconds=600,
        started_at=now,
        created_at=now,
    )
    data = client.get("/api/gallery").json()
    assert data["experiments"] == []


def test_download_zip_with_run_and_captures(client):
    manual, exp_id, frames = _seed(client)

    resp = client.post(
        "/api/gallery/download",
        json={"image_ids": [manual[0]], "experiment_ids": [exp_id]},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"

    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    names = zf.namelist()
    assert "manifest.csv" in names
    # Run frames go under a named subfolder; the manual capture sits at the root.
    assert any(n.startswith(f"run_one_{exp_id}/") for n in names)
    # One member per file (2 frames + 1 manual) plus the manifest.
    assert len(names) == 4

    manifest = zf.read("manifest.csv").decode()
    # Header + one row per selected image (2 frames + 1 manual).
    assert len(manifest.strip().splitlines()) == 1 + 3


def test_download_empty_selection_rejected(client):
    _seed(client)
    resp = client.post("/api/gallery/download", json={"image_ids": [], "experiment_ids": []})
    assert resp.status_code == 400


def test_delete_image_removes_row_and_file(client):
    from app import config, db

    manual, exp_id, frames = _seed(client)
    image = db.get_image(manual[0])
    path = config.IMAGES_DIR / image["filename"]
    assert path.exists()

    resp = client.post("/api/gallery/delete", json={"image_ids": [manual[0]], "experiment_ids": []})
    assert resp.status_code == 200
    assert resp.json() == {"deleted_images": 1, "deleted_experiments": 0}
    assert db.get_image(manual[0]) is None
    assert not path.exists()


def test_delete_running_experiment_rejected(client):
    manual, exp_id, frames = _seed(client)
    resp = client.post("/api/gallery/delete", json={"image_ids": [], "experiment_ids": [exp_id]})
    assert resp.status_code == 409
    from app import db

    assert db.get_experiment(exp_id) is not None


def test_delete_stopped_experiment_removes_frames_and_files(client):
    from app import config, db

    manual, exp_id, frames = _seed(client)
    db.set_experiment_status(exp_id, "stopped", ended_at=datetime.now(UTC).isoformat())
    frame_paths = [config.IMAGES_DIR / db.get_image(fid)["filename"] for fid in frames]
    assert all(p.exists() for p in frame_paths)

    resp = client.post("/api/gallery/delete", json={"image_ids": [], "experiment_ids": [exp_id]})
    assert resp.status_code == 200
    assert resp.json() == {"deleted_images": 2, "deleted_experiments": 1}
    assert db.get_experiment(exp_id) is None
    assert all(db.get_image(fid) is None for fid in frames)
    assert all(not p.exists() for p in frame_paths)
