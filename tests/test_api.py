from __future__ import annotations

import io

import tifffile


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


def test_capture_tiff_embeds_imagej_metadata(client):
    resp = client.post(
        "/api/capture",
        json={"resolution": "1332x990", "image_format": "tiff", "ExposureTime": 5000},
    )
    assert resp.status_code == 200
    img = resp.json()
    assert img["image_format"] == "tiff"

    file_resp = client.get(f"/api/images/{img['id']}/file?download=true")
    assert file_resp.status_code == 200
    assert file_resp.headers["content-type"] == "image/tiff"

    with tifffile.TiffFile(io.BytesIO(file_resp.content)) as tif:
        info = tif.imagej_metadata["Info"]
    assert "ExposureTime=5000" in info

    # A JPEG thumbnail is served so the TIFF still previews in the browser gallery.
    thumb_resp = client.get(f"/api/images/{img['id']}/thumbnail")
    assert thumb_resp.status_code == 200
    assert thumb_resp.headers["content-type"] == "image/jpeg"
    assert thumb_resp.content[:2] == b"\xff\xd8"  # JPEG magic


def test_preview_returns_jpeg_without_capturing(client):
    before = len(client.get("/api/images").json())

    resp = client.post(
        "/api/preview",
        json={"resolution": "1332x990", "image_format": "jpeg", "ExposureTime": 5000},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"
    assert resp.content[:2] == b"\xff\xd8"  # JPEG magic

    # Preview must not create an image row.
    after = len(client.get("/api/images").json())
    assert after == before


def test_missing_image_404(client):
    assert client.get("/api/images/999999").status_code == 404


def test_preset_save_list_recall_delete(client):
    assert client.get("/api/presets").json() == []

    resp = client.post(
        "/api/presets",
        json={"name": "Bright field", "settings": {"ExposureTime": 5000, "AnalogueGain": 1.5}},
    )
    assert resp.status_code == 200
    preset = resp.json()
    assert preset["name"] == "Bright field"
    assert preset["settings"]["ExposureTime"] == 5000

    listing = client.get("/api/presets").json()
    assert len(listing) == 1
    assert listing[0]["id"] == preset["id"]

    # Saving under the same name overwrites rather than adding a second entry.
    resp = client.post(
        "/api/presets",
        json={"name": "Bright field", "settings": {"ExposureTime": 9000}},
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == preset["id"]
    listing = client.get("/api/presets").json()
    assert len(listing) == 1
    assert listing[0]["settings"]["ExposureTime"] == 9000

    assert client.delete(f"/api/presets/{preset['id']}").status_code == 200
    assert client.get("/api/presets").json() == []
    assert client.delete(f"/api/presets/{preset['id']}").status_code == 404


def test_preset_blank_name_rejected(client):
    assert client.post("/api/presets", json={"name": "  ", "settings": {}}).status_code == 400
    assert client.post("/api/presets", json={"settings": {}}).status_code == 400
