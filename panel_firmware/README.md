# LED illumination panel firmware

**MicroPython** firmware turning a **Raspberry Pi Pico W + Waveshare Pico-RGB-Matrix-P3
64×32** panel into a Bluetooth-controlled lamp for `rlab-camera`. The Pi 4 (BLE central)
sends colour + brightness; the panel renders it. One panel = one Pico W; run any number,
each with its own entry in `RLAB_PANELS`.

> **Why MicroPython (not CircuitPython):** CircuitPython on the Pico W can't act as a BLE
> peripheral (its `_bleio` has no adapter for the on-board CYW43 radio). The MicroPython
> `bluetooth`/`aioble` stack does. The old CircuitPython `code.py` is kept in this folder as
> a rendering reference only — it is **not** the deployed firmware.

## Files (in `micropython/`)

| File | Role |
|---|---|
| `hub75.py` | HUB75 display driver: 1-bit-per-channel (8 hues), density-dithered brightness, flicker-free background refresh on core1. |
| `main.py` | **The boot app.** `aioble` GATT peripheral; receives commands and drives `hub75`. |
| `display_test.py` | Run-on-demand display self-test (hues + geometry), no BLE. |
| `../tools/panel_probe.py` | Pi-side `bleak` bench driver to validate a panel without the app. |

## Command protocol

The panel advertises a custom GATT service with one writable command characteristic:

| | UUID |
|---|---|
| Service | `5f1d0001-9d6f-4c1e-8b2a-2a5f3c9e7a10` |
| Command characteristic (write / write-no-response) | `5f1d0002-9d6f-4c1e-8b2a-2a5f3c9e7a10` |
| Status characteristic (notify) | `5f1d0003-9d6f-4c1e-8b2a-2a5f3c9e7a10` |

Each write to the command characteristic is a **4-byte payload**: `[R, G, B, brightness]`.

- `R`, `G`, `B` — 0–255. The firmware **thresholds each at 128** to a 1-bit-per-channel
  hue, so the panel shows one of **8 hues** (R/G/B/C/M/Y/W + off). This is by design — the
  panel is 1-bit colour; brightness stays continuous because it's density, not intensity.
- `brightness` — 0–255, the **fraction of LEDs to light**. The panel ordered-dithers
  (4×4 Bayer) to that density so lit LEDs spread evenly. `brightness == 0` clears the panel.

After it renders each command the panel **notifies a one-byte "I'm on" ack** on the status
characteristic (`1` = lit, `0` = cleared). The Pi subscribes to it and, on the capture path,
writes the command with response and waits for this ack before integrating a frame — so the
panel is guaranteed on before a capture (live view stays fire-and-forget for speed).

These UUIDs and this layout must stay in sync with `app/illumination/protocol.py` on the
Pi (`SERVICE_UUID`, `COMMAND_CHAR_UUID`, `STATUS_CHAR_UUID`, `to_payload`) and the constants
at the top of `micropython/main.py`.

## Wiring

Same wiring as the lab's existing panel setup (Pico W GPIO → HUB75); details and pinout are
documented in `micropython/hub75.py`:

- RGB pins: `GP2, GP3, GP4, GP5, GP8, GP9`
- Address pins: `GP10, GP16, GP18, GP20`
- Clock `GP11`, latch `GP12`, output-enable `GP13`

> **Power:** the LED matrix must have its **own 5V supply** (the board's separate power
> USB). Driving many LEDs from the Pico's USB alone browns the board out.

## Adding a panel: the one-shot script (recommended)

`tools/provision_panel.sh` does the whole bring-up end to end — run it **on the Pi**, over
SSH, with **one** board plugged into a Pi USB port **directly** (not a hub) and the LED
matrix on its own 5V supply:

```bash
cd ~/rlab-camera
sudo panel_firmware/tools/provision_panel.sh              # advertised name "rlab-panel"
sudo panel_firmware/tools/provision_panel.sh rlab-panel-b # or give it a distinct name
```

It handles a board arriving in **any** state — blank RP2 bootloader, CircuitPython (the old
`code.py`), or already-MicroPython — and: installs the MicroPython Pico W firmware, installs
`aioble`, pushes `hub75.py` + `main.py` (rewriting `_PANEL_NAME` to the name you gave), reads
the board's **BLE address off the board itself over serial** (a BLE scan is the fallback),
resets it, drives the full colour sequence with `panel_probe.py` to prove it renders, then —
after a confirmation prompt — appends the address to `RLAB_PANELS` in both the installed unit
and `deploy/rlab-camera.service` and restarts the service. It is idempotent: re-running on an
already-provisioned board is safe.

`sudo` is needed only to mount the `RPI-RP2` bootloader volume and restart the service. If
the board can't auto-enter the bootloader (e.g. unknown firmware), the script pauses and
tells you to hold **BOOTSET**, tap **RUN**. A mid-run serial drop is almost always a
brownout — see **Power** above. A board already running MicroPython is kept as-is (blank or
CircuitPython boards get the UF2); pass `FORCE_REFLASH=1` to reflash it anyway, or override
the UF2 with `MICROPYTHON_UF2_URL=… sudo -E …`.

The manual steps below are the equivalent, kept as reference and fallback.

## Flashing (manual)

The dev Mac has no USB-A, so panels are flashed via the Pi over SSH; `mpremote` lives in
`~/mpremote-venv/` on the Pi and the board enumerates as `/dev/ttyACM0`.

1. **Install MicroPython for the Pico W** — hold BOOTSEL, drag the Pico **W** `.uf2`
   (from micropython.org, must be the CYW43/W build so BLE works) onto the `RPI-RP2` drive.
   The board reboots running MicroPython (no USB drive — unlike CircuitPython).
2. **Put `aioble` on the board.** It's *not* frozen into the stock image, and the panel
   can't reach the IT-locked lab WiFi for `mpremote mip`, so copy the package from
   [micropython-lib](https://github.com/micropython/micropython-lib) — fetch it **on the
   Pi** (which has internet) and push the `aioble/` package directory to the board:
   ```bash
   mpremote connect /dev/ttyACM0 fs cp -r aioble :      # aioble/ from micropython-lib
   ```
   (`bluetooth` and `uasyncio` are built into the MicroPython firmware.)
3. **Copy the firmware** and reset:
   ```bash
   mpremote connect /dev/ttyACM0 fs cp micropython/hub75.py :hub75.py
   mpremote connect /dev/ttyACM0 fs cp micropython/main.py :main.py
   mpremote connect /dev/ttyACM0 reset      # main.py runs on boot; watch REPL for "advertising"
   ```
4. To run more than one panel, edit `_PANEL_NAME` at the top of `main.py` so each advertises
   a distinct name (e.g. `rlab-panel-a`, `rlab-panel-b`).

To check the display alone (no BLE), push and run `display_test.py`:
`mpremote connect /dev/ttyACM0 run micropython/display_test.py`.

## Bench-testing a panel (no systemd needed)

With the firmware flashed, drive the panel directly from the Pi using the same 4-byte
encoding the app uses — this confirms BLE + rendering before wiring it into the service:

```bash
cd ~/rlab-camera
.venv/bin/python panel_firmware/tools/panel_probe.py            # scans for "rlab-panel"
.venv/bin/python panel_firmware/tools/panel_probe.py AA:BB:CC:DD:EE:FF   # or by address
```

It cycles white/blue/red/green then off; watch the panel (and the board's REPL). Passing
here means `app/illumination/ble_backend.py` will connect and drive it unchanged.

## Registering panels on the Pi (wire into the app)

> `provision_panel.sh` (above) does this step for you — it appends the discovered address to
> `RLAB_PANELS` and restarts the service. The following is the manual equivalent.

List each panel's advertised name or BLE address in `RLAB_PANELS` (comma-separated) in
`deploy/rlab-camera.service`, and set `ILLUMINATION_BACKEND=ble`. bleak connects by either
the advertised name (`rlab-panel`) or the address; the address is more reliable. Discover
addresses on the Pi with:

```bash
bluetoothctl
scan on        # watch for "rlab-panel…", note the address
```

Changing the unit needs a reinstall + restart (`sudo cp deploy/rlab-camera.service
/etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl restart
rlab-camera`). See `deploy/README.md` for the full deploy flow.
