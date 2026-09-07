"""Phase-1 display bring-up test harness for the HUB75 illumination panel.

Runs on boot under MicroPython. The panel refreshes continuously in the background
(hub75 core1 thread); this loop just draws patterns and calls show(). Cycles the 8 hues
at several densities plus geometry/orientation checks, printing each pattern to the REPL
so it can be verified by eye. No BLE yet -- this file becomes the aioble app in phase 2.

Push with mpremote and watch the REPL, e.g. on the Pi:
    mpremote connect /dev/ttyACM0 fs cp hub75.py :hub75.py
    mpremote connect /dev/ttyACM0 fs cp main.py :main.py
    mpremote connect /dev/ttyACM0 run main.py      # or reset to run on boot
"""

import time

import hub75

panel = hub75.Hub75()
panel.start()  # begin background refresh (blank framebuffer)

HOLD_MS = 2500

# Density stays modest so the panel is safe on USB power if the external 5V supply is
# absent; with external matrix power, higher densities and full white are fine too.
HUES = (
    ("red", hub75.RED),
    ("green", hub75.GREEN),
    ("blue", hub75.BLUE),
    ("cyan", hub75.CYAN),
    ("magenta", hub75.MAGENTA),
    ("yellow", hub75.YELLOW),
    ("white", hub75.WHITE),
)
DENSITIES = (0.15, 0.5, 1.0)


def geometry_checks():
    # Doubles as an R/G/B channel-order + orientation check.
    print(
        "geometry: corners -> top-left RED, top-right GREEN, "
        "bottom-left BLUE, bottom-right WHITE"
    )
    panel.clear()
    panel.set_pixel(0, 0, hub75.RED)
    panel.set_pixel(hub75.WIDTH - 1, 0, hub75.GREEN)
    panel.set_pixel(0, hub75.HEIGHT - 1, hub75.BLUE)
    panel.set_pixel(hub75.WIDTH - 1, hub75.HEIGHT - 1, hub75.WHITE)
    panel.show()
    time.sleep_ms(HOLD_MS)

    print("geometry: 1px white border (expect a clean, steady rectangle)")
    panel.clear()
    for x in range(hub75.WIDTH):
        panel.set_pixel(x, 0, hub75.WHITE)
        panel.set_pixel(x, hub75.HEIGHT - 1, hub75.WHITE)
    for y in range(hub75.HEIGHT):
        panel.set_pixel(0, y, hub75.WHITE)
        panel.set_pixel(hub75.WIDTH - 1, y, hub75.WHITE)
    panel.show()
    time.sleep_ms(HOLD_MS)


def hue_sweep():
    for name, color in HUES:
        for d in DENSITIES:
            print("hue={} density={:.2f}".format(name, d))
            panel.fill_dithered(color, d)
            panel.show()
            time.sleep_ms(HOLD_MS)


print("HUB75 phase-1 test (background refresh): {}x{}".format(hub75.WIDTH, hub75.HEIGHT))
try:
    while True:
        geometry_checks()
        hue_sweep()
        print("--- cycle complete, repeating ---")
finally:
    panel.stop()
