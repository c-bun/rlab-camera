from __future__ import annotations

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


def test_illumination_off_endpoint(client):
    from app.illumination import get_illumination

    get_illumination().apply(
        {"illum_enable": True, "illum_color": "#ffffff", "illum_brightness": 100}
    )
    res = client.post("/api/illumination/off")
    assert res.status_code == 200
    assert get_illumination()._last_applied["illum_enable"] is False
