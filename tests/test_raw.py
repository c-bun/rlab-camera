from __future__ import annotations

import numpy as np
import pytest

from app.camera.raw import (
    bayer_to_channels,
    bit_depth_from_format,
    cfa_from_format,
    unpack_csi2p,
)


@pytest.mark.parametrize(
    "fmt,cfa",
    [
        ("SRGGB12", "RGGB"),
        ("SRGGB12_CSI2P", "RGGB"),
        ("SBGGR12_CSI2P", "BGGR"),
        ("SGRBG10", "GRBG"),
        ("SGBRG10_CSI2P", "GBRG"),
    ],
)
def test_cfa_from_format(fmt, cfa):
    assert cfa_from_format(fmt) == cfa


def test_cfa_from_format_rejects_garbage():
    with pytest.raises(ValueError):
        cfa_from_format("NOPE")


@pytest.mark.parametrize("fmt,bits", [("SRGGB12_CSI2P", 12), ("SGRBG10", 10), ("SBGGR12", 12)])
def test_bit_depth_from_format(fmt, bits):
    assert bit_depth_from_format(fmt) == bits


def test_bayer_to_channels_rggb_maps_and_averages_greens():
    # One 2x2 RGGB block: R=100, G=10 & 30, B=200 -> R=100, G=20 (mean), B=200.
    mosaic = np.array(
        [
            [100, 10],
            [30, 200],
        ],
        dtype=np.uint16,
    )
    stack = bayer_to_channels(mosaic, "RGGB")
    assert stack.shape == (3, 1, 1)
    assert stack.dtype == np.uint16
    assert stack[0, 0, 0] == 100  # red
    assert stack[1, 0, 0] == 20  # green = (10 + 30) // 2
    assert stack[2, 0, 0] == 200  # blue


def test_bayer_to_channels_bggr_swaps_red_and_blue():
    mosaic = np.array([[200, 10], [30, 100]], dtype=np.uint16)
    stack = bayer_to_channels(mosaic, "BGGR")
    assert stack[0, 0, 0] == 100  # red is bottom-right for BGGR
    assert stack[1, 0, 0] == 20
    assert stack[2, 0, 0] == 200  # blue is top-left for BGGR


def test_bayer_to_channels_shape_and_odd_crop():
    mosaic = np.zeros((5, 7), dtype=np.uint16)  # odd dims should be cropped to 4x6
    stack = bayer_to_channels(mosaic, "RGGB")
    assert stack.shape == (3, 2, 3)


def test_bayer_to_channels_rejects_non_2d():
    with pytest.raises(ValueError):
        bayer_to_channels(np.zeros((2, 2, 3), dtype=np.uint16), "RGGB")


def test_unpack_csi2p_12bit_roundtrip():
    # Pack two known 12-bit pixels into the 3-byte CSI2P layout, then unpack.
    p0, p1 = 0xABC, 0x123
    b0 = p0 >> 4
    b1 = p1 >> 4
    b2 = ((p1 & 0x0F) << 4) | (p0 & 0x0F)
    data = np.array([[b0, b1, b2]], dtype=np.uint8)
    out = unpack_csi2p(data, width=2, bits=12)
    assert out.shape == (1, 2)
    assert out[0, 0] == p0
    assert out[0, 1] == p1


def test_unpack_csi2p_12bit_ignores_row_padding():
    p0, p1 = 4000, 2000
    b0, b1, b2 = p0 >> 4, p1 >> 4, ((p1 & 0x0F) << 4) | (p0 & 0x0F)
    # 3 packed bytes + 5 padding bytes of stride.
    data = np.array([[b0, b1, b2, 0, 0, 0, 0, 0]], dtype=np.uint8)
    out = unpack_csi2p(data, width=2, bits=12)
    assert list(out[0]) == [p0, p1]


def test_unpack_csi2p_10bit_roundtrip():
    px = [1000, 200, 511, 3]
    b = [px[i] >> 2 for i in range(4)]
    b4 = 0
    for i in range(4):
        b4 |= (px[i] & 0x03) << (2 * i)
    data = np.array([[b[0], b[1], b[2], b[3], b4]], dtype=np.uint8)
    out = unpack_csi2p(data, width=4, bits=10)
    assert list(out[0]) == px
