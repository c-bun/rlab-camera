from __future__ import annotations


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_controls_endpoint(client):
    data = client.get("/api/controls").json()
    assert data["backend"] == "mock"
    names = {c["name"] for c in data["controls"]}
    assert {"ExposureTime", "AnalogueGain", "resolution"} <= names


def test_capture_download_and_list(client):
    resp = client.post(
        "/api/capture",
        json={"resolution": "1332x990", "image_format": "jpeg", "ExposureTime": 5000},
    )
    assert resp.status_code == 200
    img = resp.json()
    assert img["settings"]["ExposureTime"] == 5000

    listing = client.get("/api/images").json()
    assert any(i["id"] == img["id"] for i in listing)

    file_resp = client.get(f"/api/images/{img['id']}/file?download=true")
    assert file_resp.status_code == 200
    assert file_resp.headers["content-type"] == "image/jpeg"
    assert len(file_resp.content) > 0


def test_missing_image_404(client):
    assert client.get("/api/images/999999").status_code == 404
