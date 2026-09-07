# Deploying on the Raspberry Pi

The app runs on the Pi under systemd, reachable over Tailscale.

## First-time setup

```bash
# System packages (git + the camera library)
sudo apt update && sudo apt install -y git python3-picamera2

# Clone and build the venv (--system-site-packages so it can see apt's picamera2)
git clone https://github.com/c-bun/rlab-camera.git
cd rlab-camera
python3 -m venv --system-site-packages .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -r requirements.txt

# Install and start the service
sudo cp deploy/rlab-camera.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now rlab-camera
```

The app then listens on `0.0.0.0:8000` and is reachable from any tailnet peer at
`http://<pi-tailscale-ip>:8000/`.

## LED illumination panels (Bluetooth)

The Pi controls the Waveshare LED panels over Bluetooth LE (via `bleak`/BlueZ, already on
Raspberry Pi OS). Flash each Pico W panel per [`panel_firmware/README.md`](../panel_firmware/README.md),
then tell the app which panels exist:

1. Find each panel's BLE address (or advertised name) — with the panel powered and running
   its firmware:
   ```bash
   bluetoothctl
   scan on        # look for "rlab-panel…", note the address, then: scan off / exit
   ```
2. In `deploy/rlab-camera.service` set `ILLUMINATION_BACKEND=ble` and list the panels in
   `RLAB_PANELS` (comma-separated addresses/names), then reinstall the unit and restart:
   ```bash
   sudo cp deploy/rlab-camera.service /etc/systemd/system/
   sudo systemctl daemon-reload && sudo systemctl restart rlab-camera
   ```

With `RLAB_PANELS` empty (or `ILLUMINATION_BACKEND` unset), the app runs on the mock
illumination backend and touches no Bluetooth — the Illumination UI still renders but
drives nothing.

## Updating

```bash
cd ~/rlab-camera
git pull
./.venv/bin/pip install -r requirements.txt   # only if deps changed
sudo systemctl restart rlab-camera
```

## Operating

```bash
systemctl status rlab-camera        # is it running?
journalctl -u rlab-camera -f        # live logs
sudo systemctl restart rlab-camera  # restart
```

The unit assumes the repo lives at `/home/rlab-camera/rlab-camera` and runs as
user `rlab-camera`. Adjust `deploy/rlab-camera.service` if either differs.
