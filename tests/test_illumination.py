from __future__ import annotations

from app.camera.base import CaptureResult
from app.illumination.mock import MockPanels
from app.illumination.protocol import extract, to_payload


def test_mock_reports_controls():
    controls = {c.name: c for c in MockPanels().get_controls()}
    assert set(controls) == {"illum_enable", "illum_color", "illum_brightness"}
    assert controls["illum_color"].kind == "color"


def test_mock_apply_records_and_returns_coerced_state():
    panels = MockPanels()
    applied = panels.apply(
        {"illum_enable": True, "illum_color": "#FF0000", "illum_brightness": 150}
    )
    # Colour normalised, brightness clamped to the 0-100 range.
    assert applied == {"illum_enable": True, "illum_color": "#ff0000", "illum_brightness": 100}
    assert panels._last_applied == applied


def test_mock_off_clears_state():
    panels = MockPanels()
    panels.apply({"illum_enable": True, "illum_color": "#00ff00", "illum_brightness": 50})
    panels.off()
    assert panels._last_applied["illum_enable"] is False


def test_mock_apply_accepts_confirm_kwarg():
    # The capture path passes confirm=True; the mock has no hardware to wait on, so it
    # must accept and ignore it (returning the same coerced state as the fast path).
    panels = MockPanels()
    settings = {"illum_enable": True, "illum_color": "#00ff00", "illum_brightness": 50}
    assert panels.apply(settings, confirm=True) == panels.apply(settings)


class _FakeIllum:
    """Records the on/off/confirm behaviour perform_capture drives."""

    def __init__(self) -> None:
        self.events: list[str] = []
        self.on = False
        self.confirm: bool | None = None

    def apply(self, settings, *, confirm=False):
        self.on = True
        self.confirm = confirm
        self.events.append("apply")
        return extract(settings)

    def off(self):
        self.on = False
        self.events.append("off")


class _FakeCamera:
    name = "fake"

    def __init__(self, illum: _FakeIllum) -> None:
        self._illum = illum
        self.on_at_capture: bool | None = None

    def capture(self, settings, dest):
        # Record whether illumination was on at the moment the frame is taken.
        self.on_at_capture = self._illum.on
        self._illum.events.append("capture")
        return CaptureResult(
            path=dest, width=4, height=4, image_format="tiff", applied_settings=dict(settings)
        )


def test_perform_capture_confirms_illumination_then_offs_after(monkeypatch):
    from app import capture_service

    illum = _FakeIllum()
    cam = _FakeCamera(illum)
    monkeypatch.setattr(capture_service, "get_illumination", lambda: illum)
    monkeypatch.setattr(capture_service, "get_camera", lambda: cam)
    monkeypatch.setattr(capture_service.db, "insert_image", lambda **kw: 1)
    monkeypatch.setattr(capture_service.db, "get_image", lambda _id: {"id": 1})

    capture_service.perform_capture(
        {"illum_enable": True, "illum_color": "#00ff00", "illum_brightness": 50}
    )

    # The capture path asks the panel to confirm it is on (render ack)...
    assert illum.confirm is True
    # ...the panel was on when the frame was taken...
    assert cam.on_at_capture is True
    # ...and it is turned off only after the capture, in strict order.
    assert illum.on is False
    assert illum.events == ["apply", "capture", "off"]


def test_extract_defaults_and_clamps():
    # Missing keys fall back to control defaults.
    assert extract({}) == {
        "illum_enable": True,
        "illum_color": "#ffffff",
        "illum_brightness": 100,
    }
    # Bad colour is rejected back to the default; 3-digit shorthand expands.
    assert extract({"illum_color": "nope"})["illum_color"] == "#ffffff"
    assert extract({"illum_color": "#0f0"})["illum_color"] == "#00ff00"


def test_to_payload_encoding():
    on = to_payload({"illum_enable": True, "illum_color": "#ff8000", "illum_brightness": 100})
    assert on == bytes((0xFF, 0x80, 0x00, 255))
    half = to_payload({"illum_enable": True, "illum_color": "#000000", "illum_brightness": 50})
    assert half == bytes((0, 0, 0, 128))
    # Disabled → all zeros regardless of colour/brightness.
    assert to_payload(
        {"illum_enable": False, "illum_color": "#ffffff", "illum_brightness": 100}
    ) == bytes((0, 0, 0, 0))


def test_controls_endpoint_shape(client):
    res = client.get("/api/illumination/controls")
    assert res.status_code == 200
    body = res.json()
    assert body["backend"] == "mock"
    names = {c["name"] for c in body["controls"]}
    assert names == {"illum_enable", "illum_color", "illum_brightness"}
    assert body["presets"]["off"] == "#000000"


def test_capture_records_illumination_and_turns_off(client):
    from app.illumination import get_illumination

    res = client.post(
        "/api/capture",
        json={
            "resolution": "1332x990",
            "ExposureTime": 5000,
            "illum_enable": True,
            "illum_color": "#ff0000",
            "illum_brightness": 40,
        },
    )
    assert res.status_code == 200
    settings = res.json()["settings"]
    # The applied illumination is persisted with the capture (recorded before off()).
    assert settings["illum_color"] == "#ff0000"
    assert settings["illum_brightness"] == 40
    assert settings["illum_enable"] is True

    # Synced-to-capture timing: the panels are off again after the capture.
    assert get_illumination()._last_applied["illum_enable"] is False


def test_status_endpoint_mock_reports_no_panels(client):
    # The mock backend has no configured panels, so the UI shows no "not connected"
    # warning off-hardware.
    res = client.get("/api/illumination/status")
    assert res.status_code == 200
    body = res.json()
    assert body == {"backend": "mock", "configured": 0, "connected": 0, "panels": []}


def test_illumination_off_endpoint(client):
    from app.illumination import get_illumination

    get_illumination().apply(
        {"illum_enable": True, "illum_color": "#ffffff", "illum_brightness": 100}
    )
    res = client.post("/api/illumination/off")
    assert res.status_code == 200
    assert get_illumination()._last_applied["illum_enable"] is False
