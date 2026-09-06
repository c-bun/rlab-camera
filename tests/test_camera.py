from __future__ import annotations

from app.camera.mock import MockCamera


def test_mock_reports_manual_controls():
    controls = {c.name: c for c in MockCamera().get_controls()}
    # Core manual controls a lab user needs must be present.
    for name in ("ExposureTime", "AnalogueGain", "AwbEnable", "resolution"):
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
    assert (result.width, result.height) == (1332, 990)
    assert result.applied_settings["ExposureTime"] >= 100
