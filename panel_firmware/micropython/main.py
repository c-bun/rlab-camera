"""rlab-camera LED illumination panel -- MicroPython BLE peripheral (boot app).

Runs on a Raspberry Pi Pico W wired to a Waveshare Pico-RGB-Matrix-P3 64x32 panel. Phase 2
of the MicroPython firmware: the display driver (hub75.py) refreshes the panel continuously
on core1, and this app advertises a custom GATT service on core0 whose one writable
characteristic receives a 4-byte command ``[R, G, B, brightness]`` from the Pi (BLE central):

  * R, G, B     -- 0-255. Thresholded at 128 to a 1-bit-per-channel hue (8 hues: the panel
                   is 1-bit colour by design; see hub75.py / the project notes).
  * brightness  -- 0-255, the *fraction* of LEDs to light (density dither). 0 = clear.

This mirrors ``app/illumination/protocol.py`` on the Pi (``SERVICE_UUID``,
``COMMAND_CHAR_UUID``, ``to_payload``) and replaces the old CircuitPython
``panel_firmware/code.py`` -- keep the UUIDs and payload layout in sync with protocol.py.

Requires ``aioble`` (and its ``bluetooth`` dependency) on the board -- not frozen into the
stock Pico W image; copy the aioble package on first flash (see panel_firmware/README.md).
Run the display alone with ``display_test.py`` when bringing the panel up without BLE.
"""

import uasyncio as asyncio

import aioble
import bluetooth

import hub75

# Must match SERVICE_UUID / COMMAND_CHAR_UUID in app/illumination/protocol.py.
_SERVICE_UUID = bluetooth.UUID("5f1d0001-9d6f-4c1e-8b2a-2a5f3c9e7a10")
_COMMAND_UUID = bluetooth.UUID("5f1d0002-9d6f-4c1e-8b2a-2a5f3c9e7a10")

# Advertised name; put this (or the address) into RLAB_PANELS on the Pi. Give each panel a
# distinct name if you run more than one (e.g. rlab-panel-a, rlab-panel-b).
_PANEL_NAME = "rlab-panel"

# BLE advertising interval (us) and GAP appearance (generic display-ish; cosmetic only).
_ADV_INTERVAL_US = 250_000

panel = hub75.Hub75()

# One writable command characteristic. write_without_response matches the Pi's
# write_gatt_char(..., response=False); write=True also accepts a plain write. capture=True
# makes ``written()`` return (connection, data) so we read the payload directly.
_service = aioble.Service(_SERVICE_UUID)
_command = aioble.Characteristic(
    _service,
    _COMMAND_UUID,
    write=True,
    write_no_response=True,
    capture=True,
    initial=b"\x00\x00\x00\x00",
)
aioble.register_services(_service)


def apply_command(data):
    """Render a 4-byte ``[R, G, B, brightness]`` command onto the panel.

    R/G/B are thresholded at 128 to a 1-bit hue; brightness (0-255) is the fraction of
    LEDs to light via ordered dithering. brightness 0 (or an all-off hue) clears the panel.
    """
    if data is None or len(data) != 4:
        return
    r, g, b, bri = data[0], data[1], data[2], data[3]
    color = hub75.rgb(r >= 128, g >= 128, b >= 128)
    if bri == 0 or color == hub75.BLACK:
        panel.clear()
    else:
        panel.fill_dithered(color, bri / 255.0)
    panel.show()


async def peripheral_task():
    """Advertise, serve commands while connected, clear + re-advertise on disconnect."""
    while True:
        try:
            connection = await aioble.advertise(
                _ADV_INTERVAL_US,
                name=_PANEL_NAME,
                services=[_SERVICE_UUID],
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # keep advertising even if one attempt fails
            print("advertise failed:", exc)
            await asyncio.sleep_ms(500)
            continue

        print("connected:", connection.device)
        try:
            while connection.is_connected():
                # capture=True -> (connection, data). Timeout lets us re-check is_connected.
                try:
                    _conn, data = await _command.written(timeout_ms=2000)
                except asyncio.TimeoutError:
                    continue
                apply_command(data)
        except Exception as exc:  # noqa: BLE001 -- a dropped link is expected, not fatal
            print("connection error:", exc)
        finally:
            # Disconnected: clear the panel and loop back to advertising.
            panel.clear()
            panel.show()
            print("disconnected; re-advertising")


def main():
    panel.start()  # begin continuous background refresh (blank framebuffer)
    print("HUB75 BLE peripheral up: advertising as", _PANEL_NAME)
    try:
        asyncio.run(peripheral_task())
    finally:
        panel.stop()


main()
