# LED illumination panel firmware

CircuitPython firmware turning a **Raspberry Pi Pico W + Waveshare Pico-RGB-Matrix-P3
64×32** panel into a Bluetooth-controlled lamp for `rlab-camera`. The Pi 4 (BLE central)
sends colour + brightness; the panel renders it. One panel = one Pico W; run any number,
each with its own entry in `RLAB_PANELS`.

## Command protocol

The panel advertises a custom GATT service with one writable command characteristic:

| | UUID |
|---|---|
| Service | `5f1d0001-9d6f-4c1e-8b2a-2a5f3c9e7a10` |
| Command characteristic (write / write-no-response) | `5f1d0002-9d6f-4c1e-8b2a-2a5f3c9e7a10` |

Each write is a **4-byte payload**: `[R, G, B, brightness]`.

- `R`, `G`, `B` — 0–255, the colour every lit LED shows.
- `brightness` — 0–255, the **fraction of LEDs to light**. The panel ordered-dithers
  (4×4 Bayer) to that density so lit LEDs spread evenly and the sample sees roughly uniform
  illumination. `brightness == 0` clears the panel.

These UUIDs and this layout must stay in sync with `app/illumination/protocol.py` on the
Pi (`SERVICE_UUID`, `COMMAND_CHAR_UUID`, `to_payload`).

## Wiring

Same wiring as the lab's existing panel setup (Pico W GPIO → HUB75):

- RGB pins: `GP2, GP3, GP4, GP5, GP8, GP9`
- Address pins: `GP10, GP16, GP18, GP20`
- Clock `GP11`, latch `GP12`, output-enable `GP13`

## Flashing

1. Install **CircuitPython for the Raspberry Pi Pico W** (9.x or newer) — hold BOOTSEL,
   drag the `.uf2` onto the `RPI-RP2` drive. The board reboots as the `CIRCUITPY` drive.
2. Copy the **`adafruit_ble`** library folder from the matching
   [Adafruit CircuitPython bundle](https://circuitpython.org/libraries) into
   `CIRCUITPY/lib/`. (`rgbmatrix`, `displayio`, `framebufferio` are built into the Pico W
   firmware — no library needed.)
3. Copy `code.py` from this folder to the root of `CIRCUITPY`. It runs on boot.
4. To run more than one panel, edit `PANEL_NAME` in `code.py` so each advertises a
   distinct name (e.g. `rlab-panel-a`, `rlab-panel-b`).

## Registering panels on the Pi

Find each panel's advertised name or BLE address and list them in `RLAB_PANELS`
(comma-separated) in `deploy/rlab-camera.service`, then set `ILLUMINATION_BACKEND=ble`.
Discover addresses on the Pi with:

```bash
bluetoothctl
scan on        # watch for "rlab-panel…", note the address
```

bleak on the Pi can connect by either the advertised name or the address; the address is
more reliable. See `deploy/README.md` for the full deploy flow.
