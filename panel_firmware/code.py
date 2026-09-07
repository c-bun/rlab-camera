"""rlab-camera LED illumination panel — CircuitPython BLE peripheral.

Runs on a Raspberry Pi Pico W wired to a Waveshare Pico-RGB-Matrix-P3 64x32 panel.
Advertises a custom GATT service with one writable command characteristic. The Pi
(BLE central) writes a 4-byte command ``[R, G, B, brightness]``:

  * R, G, B     — 0-255, the colour every lit LED shows
  * brightness  — 0-255, the *fraction* of LEDs to light (0 = clear the panel)

Brightness controls how many LEDs are on: the panel ordered-dithers to that density so a
sample sees roughly even illumination (each LED is only on/off). This mirrors
``app/illumination/protocol.py`` on the Pi side — keep the UUIDs and payload in sync.

The rgbmatrix pin wiring matches the lab's existing panel setup.

Copy this file to the CIRCUITPY drive as ``code.py`` and copy the ``adafruit_ble`` library
folder into ``CIRCUITPY/lib/`` (from the Adafruit CircuitPython bundle). ``rgbmatrix``,
``displayio`` and ``framebufferio`` are built into the Pico W CircuitPython firmware.
"""

import board
import displayio
import framebufferio
import rgbmatrix
from adafruit_ble import BLERadio
from adafruit_ble.advertising.standard import ProvideServicesAdvertisement
from adafruit_ble.characteristics import Characteristic
from adafruit_ble.services import Service
from adafruit_ble.uuid import VendorUUID

WIDTH = 64
HEIGHT = 32

# Must match SERVICE_UUID / COMMAND_CHAR_UUID in app/illumination/protocol.py.
SERVICE_UUID = "5f1d0001-9d6f-4c1e-8b2a-2a5f3c9e7a10"
COMMAND_CHAR_UUID = "5f1d0002-9d6f-4c1e-8b2a-2a5f3c9e7a10"

# Advertised name; put this (or the address) into RLAB_PANELS on the Pi. Give each panel a
# distinct name if you run more than one.
PANEL_NAME = "rlab-panel"

# 4x4 ordered (Bayer) dither thresholds, normalised to (0, 1). A pixel is lit when the
# requested brightness fraction exceeds its threshold, spreading lit LEDs evenly.
_BAYER = (
    (0, 8, 2, 10),
    (12, 4, 14, 6),
    (3, 11, 1, 9),
    (15, 7, 13, 5),
)
_DITHER = tuple(tuple((v + 0.5) / 16.0 for v in row) for row in _BAYER)


class PanelService(Service):
    uuid = VendorUUID(SERVICE_UUID)
    command = Characteristic(
        uuid=VendorUUID(COMMAND_CHAR_UUID),
        properties=Characteristic.WRITE | Characteristic.WRITE_NO_RESPONSE,
        max_length=4,
        fixed_length=True,
        initial_value=b"\x00\x00\x00\x00",
    )


def make_display():
    displayio.release_displays()
    matrix = rgbmatrix.RGBMatrix(
        width=WIDTH,
        height=HEIGHT,
        bit_depth=6,  # higher than the old script's 1 so arbitrary RGB renders
        rgb_pins=[board.GP2, board.GP3, board.GP4, board.GP5, board.GP8, board.GP9],
        addr_pins=[board.GP10, board.GP16, board.GP18, board.GP20],
        clock_pin=board.GP11,
        latch_pin=board.GP12,
        output_enable_pin=board.GP13,
    )
    return framebufferio.FramebufferDisplay(matrix, auto_refresh=True)


def render(bitmap, palette, r, g, b, brightness):
    """Fill `bitmap` with a dithered pattern of the given colour at the given density."""
    if brightness == 0:
        bitmap.fill(0)
        return
    palette[1] = (r << 16) | (g << 8) | b
    fraction = brightness / 255.0
    for y in range(HEIGHT):
        drow = _DITHER[y & 3]
        for x in range(WIDTH):
            bitmap[x, y] = 1 if fraction > drow[x & 3] else 0


def main():
    display = make_display()
    bitmap = displayio.Bitmap(WIDTH, HEIGHT, 2)
    palette = displayio.Palette(2)
    palette[0] = 0x000000  # off
    palette[1] = 0xFFFFFF  # overwritten per command
    group = displayio.Group()
    group.append(displayio.TileGrid(bitmap, pixel_shader=palette))
    display.root_group = group

    ble = BLERadio()
    service = PanelService()
    advertisement = ProvideServicesAdvertisement(service)
    advertisement.complete_name = PANEL_NAME

    last = None
    while True:
        ble.start_advertising(advertisement)
        while not ble.connected:
            pass
        ble.stop_advertising()

        while ble.connected:
            cmd = service.command
            if cmd != last and len(cmd) == 4:
                last = cmd
                render(bitmap, palette, cmd[0], cmd[1], cmd[2], cmd[3])

        # Disconnected: clear the panel and wait for the next connection.
        bitmap.fill(0)
        last = None


main()
