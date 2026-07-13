#!/usr/bin/env python3
"""Convert a 224x144 RGB24 framebuffer dump to a dependency-free PNG."""

import binascii
import pathlib
import struct
import sys
import zlib

WIDTH = 224
HEIGHT = 144


def chunk(kind: bytes, payload: bytes) -> bytes:
    body = kind + payload
    return struct.pack(">I", len(payload)) + body + struct.pack(">I", binascii.crc32(body))


def convert(source: pathlib.Path) -> pathlib.Path:
    rgb = source.read_bytes()
    expected = WIDTH * HEIGHT * 3
    if len(rgb) != expected:
        raise SystemExit(f"{source}: expected {expected} bytes, got {len(rgb)}")
    scanlines = b"".join(
        b"\0" + rgb[y * WIDTH * 3 : (y + 1) * WIDTH * 3]
        for y in range(HEIGHT)
    )
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(scanlines, 9))
        + chunk(b"IEND", b"")
    )
    target = source.with_suffix(".png")
    target.write_bytes(png)
    return target


if __name__ == "__main__":
    for argument in sys.argv[1:]:
        print(convert(pathlib.Path(argument)))
