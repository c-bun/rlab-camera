"""1-bit-per-channel HUB75 driver for the Waveshare Pico-RGB-Matrix-P3 64x32.

MicroPython (Raspberry Pi Pico W), rlab-camera illumination panel.

Refresh strategy: a tight scan loop using **direct SIO GPIO register writes**
(GPIO_OUT_SET / GPIO_OUT_CLR) instead of per-pin ``Pin.value()`` calls, run on the
**second core** via ``_thread`` so the panel refreshes continuously in the background
while the main thread does other work (later: the BLE app). Direct register writes also
neatly handle this board's non-contiguous pins -- the SET/CLR masks address any GPIOs at
once, so the scattered RGB (GP2-5/8-9) and address (GP10/16/18/20) pins need no special
layout. (An earlier foreground ``Pin.value()`` scan proved the wiring but flickered
visibly; this replaces it.)

Colour is 1 bit per channel (8 hues: R/G/B/C/M/Y/W + off). Brightness is the *fraction*
of LEDs lit, produced by ordered dithering, so it stays continuous even at 1-bit colour.
This matches app/illumination/protocol.py; the dither table is from panel_firmware/code.py.

Pinout (proven against the lab's CircuitPython rgbmatrix wiring):
  RGB   R1=GP2 G1=GP3 B1=GP4 / R2=GP5 G2=GP8 B2=GP9   (GP6/GP7 = RTC I2C, unused)
  Addr  A=GP10 B=GP16 C=GP18 D=GP20                    (1/16 scan; E/GP22 unused)
  Ctrl  CLK=GP11 LAT=GP12 OE=GP13                      (OE active low)

Power note: the LED matrix must have its own 5V supply (the board's separate power USB).
Driving many LEDs from the Pico's USB alone browns the board out (observed over-current).
"""

import _thread
from array import array

import machine
from machine import Pin

WIDTH = 64
HEIGHT = 32
_HALF = HEIGHT // 2  # 16 addressed rows; address `a` drives row a (top) and a+16 (bottom)

# RP2040 SIO GPIO registers (write a bit-mask to set/clear those GPIOs atomically).
_SIO_BASE = 0xD0000000
_GPIO_SET = _SIO_BASE + 0x014
_GPIO_CLR = _SIO_BASE + 0x018

# Pin bit positions.
_R1, _G1, _B1 = 2, 3, 4
_R2, _G2, _B2 = 5, 8, 9
_CLK, _LAT, _OE = 11, 12, 13
_ADDR_PINS = (10, 16, 18, 20)  # A, B, C, D

_RGB_MASK = (1 << _R1) | (1 << _G1) | (1 << _B1) | (1 << _R2) | (1 << _G2) | (1 << _B2)
_CLK_MASK = 1 << _CLK
_LAT_MASK = 1 << _LAT
_OE_MASK = 1 << _OE
_ADDR_MASK = sum(1 << p for p in _ADDR_PINS)


def rgb(r, g, b):
    """Pack a 1-bit-per-channel colour into an int: bit0=R, bit1=G, bit2=B."""
    return (1 if r else 0) | (2 if g else 0) | (4 if b else 0)


BLACK = rgb(0, 0, 0)
RED = rgb(1, 0, 0)
GREEN = rgb(0, 1, 0)
BLUE = rgb(0, 0, 1)
CYAN = rgb(0, 1, 1)
MAGENTA = rgb(1, 0, 1)
YELLOW = rgb(1, 1, 0)
WHITE = rgb(1, 1, 1)

# 4x4 ordered (Bayer) dither thresholds normalised to (0, 1). A pixel is lit when the
# requested brightness fraction exceeds its threshold, spreading lit LEDs evenly.
_BAYER = (
    (0, 8, 2, 10),
    (12, 4, 14, 6),
    (3, 11, 1, 9),
    (15, 7, 13, 5),
)
_DITHER = tuple(tuple((v + 0.5) / 16.0 for v in row) for row in _BAYER)


def _top_bits(c):
    m = 0
    if c & 1:
        m |= 1 << _R1
    if c & 2:
        m |= 1 << _G1
    if c & 4:
        m |= 1 << _B1
    return m


def _bot_bits(c):
    m = 0
    if c & 1:
        m |= 1 << _R2
    if c & 2:
        m |= 1 << _G2
    if c & 4:
        m |= 1 << _B2
    return m


class Hub75:
    def __init__(self):
        # Configure every panel pin as an SIO output (so the SET/CLR registers drive them).
        for p in (_R1, _G1, _B1, _R2, _G2, _B2, _CLK, _LAT, _OE) + _ADDR_PINS:
            Pin(p, Pin.OUT, value=0)
        machine.mem32[_GPIO_SET] = _OE_MASK  # start blanked (OE active low)

        # Per-address-row SET mask (A..D) precomputed for a = 0..15.
        self._addr_set = array("I", (sum(1 << _ADDR_PINS[b] for b in range(4) if (a >> b) & 1)
                                     for a in range(_HALF)))

        self.fb = bytearray(WIDTH * HEIGHT)  # logical: one packed colour per pixel
        # Scan buffer the refresh loop streams: one GPIO SET mask per (addr_row, x),
        # combining the top (R1G1B1) and bottom (R2G2B2) pixel for that column.
        self.scan = array("I", bytearray(4 * _HALF * WIDTH))

        self._running = False
        self._thread_done = True

    # --- framebuffer ---
    def clear(self):
        for i in range(len(self.fb)):
            self.fb[i] = 0

    def fill(self, color):
        for i in range(len(self.fb)):
            self.fb[i] = color

    def set_pixel(self, x, y, color):
        if 0 <= x < WIDTH and 0 <= y < HEIGHT:
            self.fb[y * WIDTH + x] = color

    def fill_dithered(self, color, fraction):
        """Fill the whole panel with `color` at LED density `fraction` (0..1)."""
        if fraction <= 0.0:
            self.clear()
            return
        fb = self.fb
        for y in range(HEIGHT):
            drow = _DITHER[y & 3]
            base = y * WIDTH
            for x in range(WIDTH):
                fb[base + x] = color if fraction > drow[x & 3] else 0

    def show(self):
        """Rebuild the scan buffer from the framebuffer (call after drawing)."""
        fb = self.fb
        scan = self.scan
        for a in range(_HALF):
            top = a * WIDTH
            bot = (a + _HALF) * WIDTH
            for x in range(WIDTH):
                scan[top + x] = _top_bits(fb[top + x]) | _bot_bits(fb[bot + x])

    # --- background refresh (core1) ---
    @micropython.native
    def _refresh_loop(self):
        scan = self.scan
        addr_set = self._addr_set
        m = machine.mem32
        SET = _GPIO_SET
        CLR = _GPIO_CLR
        rgbm = _RGB_MASK
        clk = _CLK_MASK
        lat = _LAT_MASK
        oe = _OE_MASK
        addrm = _ADDR_MASK
        self._thread_done = False
        while self._running:
            for a in range(_HALF):
                # Shift this row's data WHILE the previously-latched row is still lit
                # (OE stays low) -- this pipelining keeps the duty cycle near 100% so
                # the panel is bright, instead of dark during every shift.
                base = a << 6  # a * 64
                for x in range(64):
                    m[CLR] = rgbm
                    m[SET] = scan[base + x]
                    m[SET] = clk
                    m[CLR] = clk
                # Brief blank only to change address + latch (prevents ghosting), then
                # display this row -- it stays lit through the next row's shift.
                m[SET] = oe  # blank
                m[CLR] = addrm
                m[SET] = addr_set[a]
                m[SET] = lat
                m[CLR] = lat
                m[CLR] = oe  # show this row
        machine.mem32[SET] = oe  # blank on exit
        self._thread_done = True

    def start(self):
        """Begin continuous background refresh on the second core."""
        if self._running:
            return
        self._running = True
        _thread.start_new_thread(self._refresh_loop, ())

    def stop(self):
        """Stop the background refresh and blank the panel."""
        self._running = False
        while not self._thread_done:
            machine.idle()
