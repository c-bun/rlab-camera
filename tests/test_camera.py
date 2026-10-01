from __future__ import annotations

from app.camera.mock import MockCamera


def test_mock_reports_manual_controls():
    controls = {c.name: c for c in MockCamera().get_controls()}
    # Core manual controls a lab user needs must be present.
    for name in ("ExposureTime", "AnalogueGain", "resolution"):
        assert name in controls
    # Format is no longer user-selectable: every capture is ImageJ-TIFF.
    assert "image_format" not in controls


def test_mock_preview_returns_jpeg_bytes(tmp_path):
    cam = MockCamera()
    frame = cam.preview({"resolution": "1332x990", "ExposureTime": 5000})
    assert isinstance(frame, bytes)
    assert frame[:2] == b"\xff\xd8"  # JPEG magic
    # Preview must not write any file.
    assert not list(tmp_path.iterdir())


def test_mock_capture_clamps_and_records_settings(tmp_path):
    cam = MockCamera()
    dest = tmp_path / "shot.tiff"
    # ExposureTime below min should be clamped, not rejected.
    result = cam.capture(
        {"resolution": "1332x990", "ExposureTime": -5},
        dest,
    )
    assert dest.exists()
    # Raw capture halves each dimension: the 1332x990 readout -> a 666x495 channel stack.
    assert (result.width, result.height) == (666, 495)
    assert result.applied_settings["ExposureTime"] >= 100
    assert result.applied_settings["raw_cfa"] == "RGGB"


def test_controls_applied_waits_for_requested_exposure_and_gain():
    # Importable off-Pi: picamera2 itself is only imported when the backend is built.
    from app.camera.picamera2_backend import _controls_applied

    dark = {"ExposureTime": 5_000_000, "AnalogueGain": 8.0}
    flash = {"ExposureTime": 20_000, "AnalogueGain": 1.0}
    # Metadata as read back on the Pi: exposure quantized to whole line times.
    flash_frame = {"ExposureTime": 19979, "AnalogueGain": 1.0}
    dark_frame = {"ExposureTime": 4999914, "AnalogueGain": 8.0}

    assert _controls_applied(flash_frame, flash)
    assert _controls_applied(dark_frame, dark)
    # A stale frame still at the previous acquisition's settings is not accepted.
    assert not _controls_applied(flash_frame, dark)
    assert not _controls_applied(dark_frame, flash)
    # Same exposure, wrong gain.
    assert not _controls_applied({"ExposureTime": 19979, "AnalogueGain": 8.0}, flash)
    # Nothing requested -> nothing to wait for.
    assert _controls_applied({}, {"AwbEnable": False})
