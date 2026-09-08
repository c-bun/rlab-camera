# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

`rlab-camera` is a lab imaging application for a **Raspberry Pi 4** with the **RPi High Quality camera** (libcamera stack). It serves a web UI where lab members — reaching the Pi over **Tailscale** — capture images with **full manual camera control**, download image files, and schedule **time-course experiments**. Because it is a lab instrument, the UI must expose every manual setting picamera2 offers, not a simplified point-and-shoot subset.

**Stack:** Python + FastAPI (uvicorn) backend · Jinja2 templates + vanilla JS frontend (no build step) · picamera2/libcamera for the camera · bleak/BLE for the LED illumination panels · APScheduler for scheduling · SQLite for experiment and image metadata.

> **Status:** MVP built, tested, and **deployed on the Pi** as a systemd service. Working: capture with full manual controls (mock backend off-Pi, real picamera2 on-Pi) — each control carries a hover tooltip built from its `description` — output as JPEG, PNG, or **TIFF that embeds the applied settings + sensor metadata as an ImageJ-readable `Info` property**, a **low-framerate live view** for tuning controls without capturing, image download, and a gallery (TIFFs preview via a cached server-side JPEG thumbnail since browsers can't render TIFF inline), and **time-course experiments** (APScheduler): a `/timecourse` page starts an interval+duration run (one active at a time) and shows its frames and progress live as they are captured, with per-run notes; a run **auto-resumes** if the service restarts mid-run. A **`/gallery` page** holds every image in one grid: each timecourse run appears as a single "stack" tile (cover thumbnail + frame count + status) that **expands inline** to its frames, while ad-hoc captures each get their own tile; checkboxes on stacks (whole run) and individual captures drive a **batch download** — a `.zip` of the original files (runs in named subfolders) plus a `manifest.csv` of every image's metadata + settings. Verified end to end over Tailscale against the real HQ camera.
>
> **In progress (branch `add-led-illumination`, not yet on `main`):** **LED sample illumination** over Bluetooth. The capture page has an **Illumination** section (enable, RGB colour picker, brightness, and white/blue/red/green/off presets); illumination is **synced to capture** (panels on just before each frame, off after) and recorded with every image, while live view keeps them lit. Any number of **Waveshare RGB-matrix panels** (each a Pico W running the **MicroPython** firmware in `panel_firmware/micropython/`) are driven identically over BLE from the Pi. Mockable off-hardware like the camera; a UI warning shows when illumination is on but configured panels aren't reachable. **Bench-verified end to end against a real panel** (capture, preview, timecourse, off all drive it; an "I'm on" render-ack handshake guarantees the panel is lit before a frame integrates). A new panel is provisioned with the one-shot `panel_firmware/tools/provision_panel.sh` (see below).

## Two-machine development model (important)

This is the central thing to understand before making changes:

- **Dev machine (this repo, macOS):** where code is written and tested. `picamera2`/`libcamera` are **Pi-only and will not import on macOS**, so all camera access must sit behind an abstraction with a **mock backend** used for local dev and tests. Never assume the real camera is present here.
- **Pi 4 (deployment target):** runs the real camera and the uvicorn server, and is the **BLE central** that drives the illumination panels.
- **LED panels (separate microcontrollers):** each is a **Raspberry Pi Pico W running MicroPython** (`panel_firmware/micropython/main.py` + `hub75.py`) wired to a Waveshare RGB-matrix panel; it acts as a BLE peripheral the Pi connects to. This firmware is flashed to the board, not run from this repo (the legacy CircuitPython `panel_firmware/code.py` is kept as a rendering reference only — CircuitPython on the Pico W can't do BLE). `bleak` (unlike picamera2) *does* import on macOS, so the illumination code needs no import guard — but there is no panel hardware off-Pi, so illumination still sits behind the same mock-backed abstraction for dev and tests. Bringing up a new panel is fully scripted: `panel_firmware/tools/provision_panel.sh`, run on the Pi with a board plugged in, flashes MicroPython + `aioble` + the firmware, discovers the panel's BLE address, verifies it renders, and registers it in `RLAB_PANELS`.
- **Deploy loop:** edit here → commit → push to the git remote → SSH into the Pi over Tailscale → pull → restart the service. Code is not run on the Pi by editing there.

### The Pi (current deployment)

- Host: `rlab-camera@100.67.2.37` (Tailscale IP; name `rlab-camera`). Debian 13, Python 3.13.
- Repo at `~/rlab-camera`; venv created with `--system-site-packages` so it can see the apt-installed `python3-picamera2` (picamera2 is **not** pip-installable and is deliberately absent from `requirements.txt`).
- Runs as the **systemd service `rlab-camera`** (unit in `deploy/rlab-camera.service`), bound to `0.0.0.0:8000`, `enabled` on boot, `Restart=on-failure`, `Environment=CAMERA_BACKEND=picamera2`.
- **Illumination env** (also in the unit): `ILLUMINATION_BACKEND` (`auto`|`mock`|`ble`) and `RLAB_PANELS` (comma-separated BLE addresses/names). `auto` uses the BLE backend only when `RLAB_PANELS` is non-empty, else mock; `bleak` uses BlueZ, already present on the Pi. With no panels listed the app still runs (illumination is a no-op). Changing these needs the unit reinstalled (`sudo cp … && sudo systemctl daemon-reload`), i.e. a **user-run sudo step** — but `panel_firmware/tools/provision_panel.sh` does the whole add-a-panel flow (flash → discover address → verify → append to `RLAB_PANELS` in both the installed unit and the repo copy → restart) in one interactive `sudo` run on the Pi. See `panel_firmware/README.md` for that script and the manual equivalent.
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

- **Illumination abstraction layer** (`app/illumination/`): deliberately mirrors the camera layer. One interface (`base.py` → `IlluminationBackend`) with two backends — `ble_backend.py` (real panels over Bluetooth) and `mock.py` (dev/CI) — chosen by `get_illumination()` in `factory.py` via `ILLUMINATION_BACKEND`. **Never `import bleak` outside `ble_backend.py`.** The canonical control set is in `controls.py` (`illum_enable`, `illum_color`, `illum_brightness`, plus `COLOR_PRESETS`); `protocol.py` holds the settings→state coercion, the 4-byte panel command `[R,G,B,brightness]`, and the three GATT UUIDs (a command char plus a notify-only status char for the "I'm on" render ack) — all shared with `panel_firmware/micropython/main.py`, so **keep the two in sync.** Illumination settings ride the **same flat settings dict** as camera controls (keys `illum_*`), so capture, preview, presets, and timecourse carry them with no extra plumbing. `perform_capture()` sets the panels **before** `camera.capture()` and turns them **off after** (synced-to-capture timing), and merges the applied illumination into the persisted settings so it survives even the mock camera (which rebuilds `applied_settings` from its own control set). `apply()`/`off()` are sync but drive `bleak` (async) via a **background asyncio loop thread**, guarded by a `threading.Lock`; a per-panel error is logged and skipped, never fatal to a capture. Brightness is the **fraction of LEDs lit** — the firmware ordered-dithers to that density for even illumination. `status()` (exposed at `/api/illumination/status`) probes panel connectivity so the UI can warn when illumination is on but panels are unreachable. `BlePanels` is not created in the lifespan (lazy via the `lru_cache`), but the lifespan does call `get_illumination().close()` on shutdown to tear down BLE connections.

- **Web layer** (`app/main.py` + `app/routers/`): `capture.py` serves the page, `/api/controls`, `/api/capture`, and `/api/preview` (which also drives the panels via `get_illumination().apply()` so live view stays lit); `illumination.py` serves `/api/illumination/controls`, `/api/illumination/status`, and `/api/illumination/off`; `images.py` serves listing, metadata, and file download; `experiments.py` serves the `/timecourse` page and the `/api/experiments` run API; `gallery.py` serves the `/gallery` page, `GET /api/gallery` (runs-as-stacks + ungrouped captures, using the single-aggregate `db.experiment_gallery_summaries()` to avoid an N+1 count-per-run), and `POST /api/gallery/download` (streams a zip built to a temp file — never in memory — via `list_images_by_ids`/`list_images(experiment_id=…)`, deduped by id, with a `manifest.csv`). Jinja2 templates + vanilla JS in `app/templates/` and `app/static/`. The single-capture body is factored into `app/capture_service.py` `perform_capture(settings, experiment_id=None)` so both the `/api/capture` route and the scheduler job share one path — **do not inline capture logic back into the route.** The control panel is **built client-side from `/api/controls`** so it always reflects the active backend's reported ranges rather than hard-coded limits; that build plus the preset-load and `collectSettings`/`applySettings` helpers live in the shared `app/static/controls.js`, included by both the capture page (`app.js`) and the timecourse page (`timecourse.js`). The **Illumination** section is built the same way from `/api/illumination/controls` into its own `#illumination-form` (kept out of `#controls-form`, which `loadControls()` clears); `collectSettings`/`applySettings` scan both forms, so `illum_*` keys flow through capture/preview/presets/experiments automatically — and `controls.js` adds a `"color"` field kind plus `refreshIllumStatus()` for the connectivity warning. **Live view:** the Start/Stop toggle polls `POST /api/preview` (same settings body as capture) every ~500 ms (~2 fps), reusing `collectSettings()`, and displays each JPEG via a blob URL; it pauses during a capture to avoid preview↔capture resolution-reconfigure churn.

- **Persistence & storage** (`app/db.py`, `app/config.py`): captured-image metadata (including the full settings JSON) goes in SQLite; image files are written to `data/images/`, the DB to `data/rlab.db`. Both live under `data/` (gitignored) and paths are overridable via `RLAB_DATA_DIR`/`RLAB_DB_PATH` — the tests rely on these overrides for isolation.

- **Experiments / scheduling** (`app/scheduler.py`, `experiments` table): a time-course run is an `experiments` row (name, notes, settings, interval + duration, status: `running`|`complete`|`stopped`) plus captures in `images` tagged with its `experiment_id`. **SQLite is the source of truth; APScheduler's own jobstore is in-memory.** Each run arms two jobs on the `BackgroundScheduler` (created per-app in the lifespan and stored on `app.state.scheduler`, not a module global): an `IntervalTrigger` capture job (`max_instances=1`, `coalesce=True`) bounded by `end_date = started + duration + interval/2` — the half-interval slack ensures the boundary frame at exactly `t = duration` fires despite ms drift, so a run yields `expected_total = floor(duration/interval)+1` frames — and a one-shot `DateTrigger` finalize job a beat later that flips a still-`running` row to `complete` (covers runs whose captures errored). On startup `reconcile_on_startup()` re-arms the single active run from the DB (auto-resume); frames whose boundaries fell during the downtime are simply lost — the camera wasn't running — and the run continues on its original cadence. **Only one run is active at a time** (`get_active_experiment()`; the POST rejects a second with 409). Captures go through the same `perform_capture()` → `db.insert_image(..., experiment_id=...)` path as manual capture, so the camera `threading.Lock` serializes a scheduled capture against live view and manual capture.

- **Auth model:** access is gated by **Tailscale network membership** — on the Pi the server binds `0.0.0.0` and is reachable only over the tailnet. There is no app-level login yet; decide whether to add one or delegate trust to Tailscale.

## Conventions

- Never `import picamera2` outside the camera backend module — everything else uses the abstraction. Likewise never `import bleak` outside `app/illumination/ble_backend.py`.
- Illumination settings are flat `illum_*` keys in the same settings dict as camera controls — don't nest them into a sub-object, or `collectSettings`/`applySettings` and the persisted metadata stop carrying them. Brightness means LED density (fraction lit), not per-LED intensity.
- The panel wire protocol and GATT UUIDs are shared between `app/illumination/protocol.py` and `panel_firmware/micropython/main.py` — change both together.
- Manual controls are first-class: expose the full picamera2 control surface, prefer sensor-reported ranges over hard-coded limits, and persist the exact settings used with every capture.
- On the Pi the server must bind `0.0.0.0` for Tailscale peers to reach it.
- Keep the camera interface mockable so dev and tests run on macOS without hardware.
