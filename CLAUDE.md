# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

`rlab-camera` is a lab imaging application for a **Raspberry Pi 4** with the **RPi High Quality camera** (libcamera stack). It serves a web UI where lab members — reaching the Pi over **Tailscale** — capture images with **full manual camera control**, download image files, and schedule **time-course experiments**. Because it is a lab instrument, the UI must expose every manual setting picamera2 offers, not a simplified point-and-shoot subset.

**Stack:** Python + FastAPI (uvicorn) backend · Jinja2 templates + vanilla JS frontend (no build step) · picamera2/libcamera for the camera · APScheduler for scheduling · SQLite for experiment and image metadata.

> **Status:** MVP built, tested, and **deployed on the Pi** as a systemd service. Working: capture with full manual controls (mock backend off-Pi, real picamera2 on-Pi) — each control carries a hover tooltip built from its `description` — output as JPEG, PNG, or **TIFF that embeds the applied settings + sensor metadata as an ImageJ-readable `Info` property**, a **low-framerate live view** for tuning controls without capturing, image download, and a gallery (TIFFs preview via a cached server-side JPEG thumbnail since browsers can't render TIFF inline). Verified end to end over Tailscale against the real HQ camera. Time-course experiments (APScheduler + experiment tables) are **not built yet** — that is the next feature to add on top of this base.

## Two-machine development model (important)

This is the central thing to understand before making changes:

- **Dev machine (this repo, macOS):** where code is written and tested. `picamera2`/`libcamera` are **Pi-only and will not import on macOS**, so all camera access must sit behind an abstraction with a **mock backend** used for local dev and tests. Never assume the real camera is present here.
- **Pi 4 (deployment target):** runs the real camera and the uvicorn server.
- **Deploy loop:** edit here → commit → push to the git remote → SSH into the Pi over Tailscale → pull → restart the service. Code is not run on the Pi by editing there.

### The Pi (current deployment)

- Host: `rlab-camera@100.67.2.37` (Tailscale IP; name `rlab-camera`). Debian 13, Python 3.13.
- Repo at `~/rlab-camera`; venv created with `--system-site-packages` so it can see the apt-installed `python3-picamera2` (picamera2 is **not** pip-installable and is deliberately absent from `requirements.txt`).
- Runs as the **systemd service `rlab-camera`** (unit in `deploy/rlab-camera.service`), bound to `0.0.0.0:8000`, `enabled` on boot, `Restart=on-failure`, `Environment=CAMERA_BACKEND=picamera2`.
- Reachable from any tailnet peer at `http://100.67.2.37:8000/`.
- `sudo` on the Pi requires a password — steps needing it (apt installs, installing/enabling the unit, **`systemctl restart`**) must be run interactively by the user, not automated.
- **Passwordless SSH works for non-sudo operations.** Claude Code can `ssh -o BatchMode=yes rlab-camera@100.67.2.37 '…'` to run read-only checks and git commands (`git fetch`/`checkout`/`pull`/`status`/`log`, `journalctl`, `systemctl status`) directly — so deploying code to the Pi and inspecting its state can be done autonomously. Only the final `sudo systemctl restart rlab-camera` needs the user to run it (e.g. via a `!`-prefixed command in the session).

Update the running Pi:
```bash
ssh rlab-camera@100.67.2.37 'cd rlab-camera && git pull && sudo systemctl restart rlab-camera'
```
Operate: `systemctl status rlab-camera` · `journalctl -u rlab-camera -f`. Full setup steps are in `deploy/README.md`.

## Commands

```bash
# Setup (dev machine)
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt    # runtime deps only: requirements.txt

# Run locally with the mock camera (macOS dev). CAMERA_BACKEND defaults to "auto",
# which falls back to mock when picamera2 is unavailable, so the env var is optional.
CAMERA_BACKEND=mock uvicorn app.main:app --reload

# Run on the Pi (bind 0.0.0.0 so Tailscale peers can reach it)
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Tests
pytest                                          # all tests
pytest tests/test_api.py::test_capture_download_and_list   # a single test

# Lint / format
ruff check .
ruff format .
```

On the Pi, install picamera2 via apt (it is intentionally not in requirements.txt so
the file installs on macOS): `sudo apt install -y python3-picamera2`.

## Architecture (big picture)

The parts below span multiple files and are worth understanding up front:

- **Camera abstraction layer** (`app/camera/`): one interface (`base.py` → `CameraBackend`) with two backends — `picamera2_backend.py` (Pi) and `mock.py` (dev/CI) — chosen at startup by `get_camera()` in `factory.py` via `CAMERA_BACKEND` (`auto`|`mock`|`picamera2`). **All capture goes through this interface; never `import picamera2` outside `picamera2_backend.py`.** The canonical manual control set lives in `controls.py` (exposure time, analogue gain, AWB + red/blue colour gains, exposure compensation, framerate, resolution, format); the real backend refines numeric ranges from `Picamera2.camera_controls` where the sensor reports them. `capture()` returns a `CaptureResult` recording the exact applied settings, which are persisted with the image for reproducibility. `preview(settings)` returns an **in-memory JPEG** at a small fixed size (`_PREVIEW_SIZE`) for the live view — no file, no DB row.

  The picamera2 backend builds a **still configuration at the requested resolution** and reconfigures (stop → configure → start) only when the resolution changes, then **drops one settling frame** after `set_controls` so manual exposure/gain/AWB take effect before the kept frame. It reports the size the camera was *actually* configured to (from `camera_configuration()["main"]["size"]`), not the requested string — do not reintroduce echoing the request, since a mismatch silently corrupts capture metadata. `preview()` reuses the same `_ensure_configured` path at `_PREVIEW_SIZE` but **skips the settling-frame drop** (the stream is continuous, so a control change simply shows on the next poll). Because `get_camera()` is a process-wide singleton shared across FastAPI's threadpool, `capture()` and `preview()` are both guarded by a `threading.Lock` — do not remove it, or a preview poll and a capture will race on the reconfigure.

- **Web layer** (`app/main.py` + `app/routers/`): `capture.py` serves the page, `/api/controls`, `/api/capture`, and `/api/preview`; `images.py` serves listing, metadata, and file download. Jinja2 template + vanilla JS in `app/templates/` and `app/static/`. The control panel is **built client-side from `/api/controls`** so it always reflects the active backend's reported ranges rather than hard-coded limits. **Live view:** the Start/Stop toggle polls `POST /api/preview` (same settings body as capture) every ~500 ms (~2 fps), reusing `collectSettings()`, and displays each JPEG via a blob URL; it pauses during a capture to avoid preview↔capture resolution-reconfigure churn.

- **Persistence & storage** (`app/db.py`, `app/config.py`): captured-image metadata (including the full settings JSON) goes in SQLite; image files are written to `data/images/`, the DB to `data/rlab.db`. Both live under `data/` (gitignored) and paths are overridable via `RLAB_DATA_DIR`/`RLAB_DB_PATH` — the tests rely on these overrides for isolation.

- **Experiments / scheduling (not built yet):** the plan is APScheduler running time-course capture jobs with experiment definitions in SQLite, reusing the same `get_camera()` + `db.insert_image()` path (note `images.experiment_id` is already in the schema). Add an experiments router/table when implementing.

- **Auth model:** access is gated by **Tailscale network membership** — on the Pi the server binds `0.0.0.0` and is reachable only over the tailnet. There is no app-level login yet; decide whether to add one or delegate trust to Tailscale.

## Conventions

- Never `import picamera2` outside the camera backend module — everything else uses the abstraction.
- Manual controls are first-class: expose the full picamera2 control surface, prefer sensor-reported ranges over hard-coded limits, and persist the exact settings used with every capture.
- On the Pi the server must bind `0.0.0.0` for Tailscale peers to reach it.
- Keep the camera interface mockable so dev and tests run on macOS without hardware.
