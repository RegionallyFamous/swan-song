#!/usr/bin/env python3
"""Generate Swan Song's deterministic Analogue Pocket core-author icon.

Analogue's documented display canvas is 36x36 pixels. The design below uses
an 18x18 logical grid expanded at the recommended 2x2 pixel scale. ``#`` is
the black (0x0000) swan mark and ``.`` is the white (0xFF00) canvas. APF
stores the displayed bitmap rotated 90 degrees counter-clockwise.
"""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "dist/Cores/agg23.WonderSwan/icon.bin"
LOGICAL_SIZE = 18
PIXEL_SCALE = 2
DISPLAY_SIZE = LOGICAL_SIZE * PIXEL_SCALE

# An original generic swan silhouette, not a Bandai/WonderSwan logo or a
# tracing of third-party art. Keep a one-logical-pixel safe margin.
LOGICAL_ICON = (
    "..................",
    "..........###.....",
    ".........#####....",
    ".........##.#####.",
    ".........####.....",
    "........###.......",
    ".......###........",
    "......###.........",
    ".....###..........",
    "....###...####....",
    "...###..######....",
    "..###..########...",
    "..##############..",
    "..##############..",
    "...############...",
    "....##########....",
    "......######......",
    "..................",
)


def _validate_source() -> None:
    if len(LOGICAL_ICON) != LOGICAL_SIZE:
        raise ValueError(f"logical icon must have {LOGICAL_SIZE} rows")
    for row_number, row in enumerate(LOGICAL_ICON, 1):
        if len(row) != LOGICAL_SIZE:
            raise ValueError(
                f"logical icon row {row_number} must have {LOGICAL_SIZE} columns"
            )
        if set(row) - {".", "#"}:
            raise ValueError(f"logical icon row {row_number} is not monochrome")


def display_brightness() -> tuple[tuple[int, ...], ...]:
    """Return the intended upright 36x36 display bitmap as brightness bytes."""

    _validate_source()
    rows: list[tuple[int, ...]] = []
    for logical_row in LOGICAL_ICON:
        expanded = tuple(
            brightness
            for pixel in logical_row
            for brightness in ((0x00,) if pixel == "#" else (0xFF,)) * PIXEL_SCALE
        )
        rows.extend((expanded,) * PIXEL_SCALE)
    return tuple(rows)


def rotate_counterclockwise(
    pixels: tuple[tuple[int, ...], ...],
) -> tuple[tuple[int, ...], ...]:
    """Rotate a square row-major bitmap 90 degrees counter-clockwise."""

    size = len(pixels)
    if size == 0 or any(len(row) != size for row in pixels):
        raise ValueError("bitmap must be a nonempty square")
    return tuple(
        tuple(pixels[x][size - 1 - y] for x in range(size))
        for y in range(size)
    )


def icon_bytes() -> bytes:
    """Return the APF on-disk bitmap (CCW rotation, big-endian brightness)."""

    stored = rotate_counterclockwise(display_brightness())
    return b"".join(bytes((brightness, 0x00)) for row in stored for brightness in row)


def preview_bytes() -> bytes:
    """Return a dependency-free PGM preview in upright display orientation."""

    pixels = bytes(value for row in display_brightness() for value in row)
    return f"P5\n{DISPLAY_SIZE} {DISPLAY_SIZE}\n255\n".encode("ascii") + pixels


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=pathlib.Path,
        default=DEFAULT_OUTPUT,
        help=f"icon.bin output (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail unless --output already equals the generated icon",
    )
    parser.add_argument(
        "--preview",
        type=pathlib.Path,
        help="also write an upright 36x36 PGM preview",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    generated = icon_bytes()
    output = args.output.resolve()

    if args.check:
        try:
            existing = output.read_bytes()
        except FileNotFoundError:
            print(f"missing generated core icon: {output}", file=sys.stderr)
            return 1
        if existing != generated:
            print(f"stale generated core icon: {output}", file=sys.stderr)
            return 1
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(generated)

    if args.preview is not None:
        preview = args.preview.resolve()
        preview.parent.mkdir(parents=True, exist_ok=True)
        preview.write_bytes(preview_bytes())

    state = "verified" if args.check else "wrote"
    digest = hashlib.sha256(generated).hexdigest()
    print(f"{state} {output}: {len(generated)} bytes sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
