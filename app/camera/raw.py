"""Turn a raw Bayer mosaic into a 3-channel R/G/B stack — no demosaic interpolation.

Scientific imaging wants the sensor's actual per-pixel readings, not the ISP's
debayered/white-balanced RGB. The IMX477 is a colour sensor: every photosite sits under
one R, G, or B filter and reports a single number. We keep those numbers untouched and
just *reshape* the 2x2 Bayer tile into channels — each 2x2 block (1 red, 2 green, 1 blue)
becomes one output pixel whose channels come from that same block. This halves each spatial
dimension and, unlike demosaicing, never interpolates a value from neighbouring pixels.

Pure numpy and hardware-independent, so it is exercised by the mock backend and unit tests
off-Pi; the picamera2 backend feeds it a real sensor mosaic.
"""

from __future__ import annotations

import numpy as np

# Which corner of the 2x2 Bayer tile holds which colour, per CFA order. Indices are into
# the flattened tile in row-major order: 0=(top-left), 1=(top-right), 2=(bottom-left),
# 3=(bottom-right). Each entry maps CFA -> (red_idx, green_idx_a, green_idx_b, blue_idx).
_CFA_LAYOUT: dict[str, tuple[int, int, int, int]] = {
    "RGGB": (0, 1, 2, 3),
    "BGGR": (3, 1, 2, 0),
    "GRBG": (1, 0, 3, 2),
    "GBRG": (2, 0, 3, 1),
}


def bit_depth_from_format(fmt: str) -> int:
    """Pull the trailing bit-depth out of a raw format string (``"SRGGB12_CSI2P"`` -> 12)."""
    digits = ""
    for ch in fmt.upper().replace("_CSI2P", ""):
        if ch.isdigit():
            digits += ch
    if not digits:
        raise ValueError(f"no bit depth in raw format {fmt!r}")
    return int(digits)


def unpack_csi2p(data: np.ndarray, width: int, bits: int) -> np.ndarray:
    """Unpack a MIPI CSI-2 packed Bayer plane into a ``(H, width)`` uint16 mosaic.

    `data` is the raw plane as ``(H, stride)`` uint8 (stride may include row padding, which
    is ignored past the packed pixels). Supports the 12-bit (2 px / 3 bytes) and 10-bit
    (4 px / 5 bytes) CSI2P layouts the IMX477 uses. Values are left-justified out of the
    MSB byte, matching how libcamera reports them.
    """
    if data.ndim != 2:
        raise ValueError(f"expected (H, stride) packed data, got shape {data.shape}")
    rows = data.shape[0]

    if bits == 12:
        # Every 3 bytes hold 2 pixels: b0=p0[11:4], b1=p1[11:4], b2=p1[3:0]<<4 | p0[3:0].
        n_bytes = (width * 3) // 2
        packed = data[:, :n_bytes].astype(np.uint16)
        b0 = packed[:, 0::3]
        b1 = packed[:, 1::3]
        b2 = packed[:, 2::3]
        p0 = (b0 << 4) | (b2 & 0x0F)
        p1 = (b1 << 4) | (b2 >> 4)
        out = np.empty((rows, width), dtype=np.uint16)
        out[:, 0::2] = p0
        out[:, 1::2] = p1
        return out

    if bits == 10:
        # Every 5 bytes hold 4 pixels: b0..b3=MSB8 of p0..p3, b4 packs the 2 LSBs of each.
        n_bytes = (width * 5) // 4
        packed = data[:, :n_bytes].astype(np.uint16)
        b = [packed[:, i::5] for i in range(5)]
        out = np.empty((rows, width), dtype=np.uint16)
        for i in range(4):
            out[:, i::4] = (b[i] << 2) | ((b[4] >> (2 * i)) & 0x03)
        return out

    raise ValueError(f"unsupported CSI2P bit depth: {bits}")


def cfa_from_format(fmt: str) -> str:
    """Extract the 4-char Bayer order from a libcamera raw format string.

    Examples: ``"SRGGB12"`` -> ``"RGGB"``, ``"SBGGR12_CSI2P"`` -> ``"BGGR"``,
    ``"SGRBG10"`` -> ``"GRBG"``. The pattern depends on sensor orientation, so it must be
    read from the format the camera reports rather than assumed.
    """
    if not fmt:
        raise ValueError("empty raw format string")
    body = fmt.upper()
    if body.startswith("S"):  # libcamera Bayer formats are prefixed with 'S'
        body = body[1:]
    # The CFA order is the leading run of R/G/B letters; drop the bit-depth/packing tail.
    order = ""
    for ch in body:
        if ch in "RGB":
            order += ch
        else:
            break
    if order not in _CFA_LAYOUT:
        raise ValueError(f"unrecognised Bayer CFA in format {fmt!r} (parsed {order!r})")
    return order


def bayer_to_channels(mosaic: np.ndarray, cfa: str) -> np.ndarray:
    """Reshape a 2-D Bayer ``mosaic`` into a ``(3, H/2, W/2)`` R/G/B stack.

    The two green photosites in each 2x2 block are averaged into the single green channel
    (a combination of same-colour sites, not interpolation across the image). Odd trailing
    rows/columns are cropped so the mosaic tiles evenly into 2x2 blocks. Returned dtype
    matches the input (uint16 for real captures).
    """
    if mosaic.ndim != 2:
        raise ValueError(f"expected a 2-D Bayer mosaic, got shape {mosaic.shape}")
    if cfa not in _CFA_LAYOUT:
        raise ValueError(f"unknown CFA order {cfa!r}")

    h, w = mosaic.shape
    h -= h % 2
    w -= w % 2
    mosaic = mosaic[:h, :w]

    # The four 2x2 sub-lattices, in the same 0..3 order as _CFA_LAYOUT indices.
    quads = [
        mosaic[0::2, 0::2],  # 0: top-left
        mosaic[0::2, 1::2],  # 1: top-right
        mosaic[1::2, 0::2],  # 2: bottom-left
        mosaic[1::2, 1::2],  # 3: bottom-right
    ]
    r_idx, g_a, g_b, b_idx = _CFA_LAYOUT[cfa]

    red = quads[r_idx]
    blue = quads[b_idx]
    # Average the two greens without overflow, then return to the source dtype.
    green = ((quads[g_a].astype(np.uint32) + quads[g_b].astype(np.uint32)) // 2).astype(
        mosaic.dtype
    )

    return np.stack([red, green, blue], axis=0)
