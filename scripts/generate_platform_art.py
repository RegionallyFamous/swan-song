#!/usr/bin/env python3
"""Generate Swan Song's deterministic Analogue Pocket platform artwork.

"Swan Wake" is built entirely from integer raster primitives and the original
Regionally Famous-authored 18x18 grid in ``generate_core_icon.py``.  It does
not trace, embed, or depend on third-party artwork, fonts, or image libraries.

Artwork design and generator copyright 2026 Regionally Famous.  This
authorship notice is not a project-wide license declaration; consult the
repository's provenance and release-clearance documentation before reuse.
"""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import sys

from generate_core_icon import LOGICAL_ICON, LOGICAL_SIZE


ROOT = pathlib.Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "dist/Platforms/_images/wonderswan.bin"
WIDTH = 521
HEIGHT = 165
MARK_SCALE = 7
MARK_X = 125
MARK_Y = 19


class Canvas:
    """A small dependency-free, max-composited grayscale raster."""

    def __init__(self, width: int, height: int) -> None:
        if width <= 0 or height <= 0:
            raise ValueError("canvas dimensions must be positive")
        self.width = width
        self.height = height
        self.rows = [bytearray(width) for _ in range(height)]

    @staticmethod
    def _brightness(value: int) -> int:
        if not 0 <= value <= 0xFF:
            raise ValueError("brightness must be an unsigned byte")
        return value

    def plot(self, x: int, y: int, brightness: int) -> None:
        value = self._brightness(brightness)
        if 0 <= x < self.width and 0 <= y < self.height:
            self.rows[y][x] = max(self.rows[y][x], value)

    def rectangle(
        self, left: int, top: int, right: int, bottom: int, brightness: int
    ) -> None:
        value = self._brightness(brightness)
        if right < left or bottom < top:
            raise ValueError("rectangle bounds are reversed")
        for y in range(max(0, top), min(self.height - 1, bottom) + 1):
            row = self.rows[y]
            for x in range(max(0, left), min(self.width - 1, right) + 1):
                row[x] = max(row[x], value)

    def line(
        self,
        x0: int,
        y0: int,
        x1: int,
        y1: int,
        brightness: int,
        thickness: int = 1,
    ) -> None:
        """Draw an inclusive Bresenham segment with square integer pixels."""

        if thickness <= 0:
            raise ValueError("line thickness must be positive")
        radius_before = (thickness - 1) // 2
        radius_after = thickness // 2
        dx = abs(x1 - x0)
        step_x = 1 if x0 < x1 else -1
        dy = -abs(y1 - y0)
        step_y = 1 if y0 < y1 else -1
        error = dx + dy
        while True:
            self.rectangle(
                x0 - radius_before,
                y0 - radius_before,
                x0 + radius_after,
                y0 + radius_after,
                brightness,
            )
            if x0 == x1 and y0 == y1:
                return
            twice = 2 * error
            if twice >= dy:
                error += dy
                x0 += step_x
            if twice <= dx:
                error += dx
                y0 += step_y

    def quadratic(
        self,
        start: tuple[int, int],
        control: tuple[int, int],
        end: tuple[int, int],
        brightness: int,
        thickness: int = 1,
        steps: int = 192,
    ) -> None:
        """Draw a fixed-point quadratic Bezier curve deterministically."""

        if steps <= 0:
            raise ValueError("curve steps must be positive")
        denominator = steps * steps
        previous = start
        for index in range(1, steps + 1):
            inverse = steps - index
            x_numerator = (
                inverse * inverse * start[0]
                + 2 * inverse * index * control[0]
                + index * index * end[0]
            )
            y_numerator = (
                inverse * inverse * start[1]
                + 2 * inverse * index * control[1]
                + index * index * end[1]
            )
            current = (
                (x_numerator + denominator // 2) // denominator,
                (y_numerator + denominator // 2) // denominator,
            )
            self.line(*previous, *current, brightness, thickness)
            previous = current

    def stamp_icon(self, left: int, top: int, scale: int, brightness: int) -> None:
        """Stamp the existing logical swan grid at an integer pixel scale."""

        if scale <= 0:
            raise ValueError("icon scale must be positive")
        if len(LOGICAL_ICON) != LOGICAL_SIZE:
            raise ValueError("logical icon row count changed")
        for grid_y, row in enumerate(LOGICAL_ICON):
            if len(row) != LOGICAL_SIZE or set(row) - {".", "#"}:
                raise ValueError("logical icon grid is malformed")
            for grid_x, pixel in enumerate(row):
                if pixel == "#":
                    x = left + grid_x * scale
                    y = top + grid_y * scale
                    self.rectangle(x, y, x + scale - 1, y + scale - 1, brightness)


def display_brightness() -> tuple[bytes, ...]:
    """Return the upright 521x165 Swan Wake display raster."""

    canvas = Canvas(WIDTH, HEIGHT)

    # Quiet frame marks establish the wide Pocket platform-art canvas without
    # borrowing a wordmark, console silhouette, font, or other external asset.
    canvas.line(18, 21, 46, 21, 32, 2)
    canvas.line(18, 21, 18, 47, 32, 2)
    canvas.line(474, 143, 502, 143, 32, 2)
    canvas.line(502, 117, 502, 143, 32, 2)

    # Abstract wake curves converge beneath the swan.  Integer-only geometry
    # makes the rendered bytes identical on every supported host.
    canvas.quadratic((24, 72), (72, 51), (140, 113), 48, 1)
    canvas.quadratic((22, 128), (73, 163), (142, 124), 64, 1)
    canvas.quadratic((38, 92), (86, 69), (142, 116), 112, 2)
    canvas.quadratic((40, 139), (90, 151), (144, 125), 96, 2)
    canvas.quadratic((64, 108), (105, 96), (147, 120), 192, 2)
    canvas.quadratic((68, 132), (110, 137), (148, 124), 160, 2)

    # A low, icon-derived cadence of dashes echoes the 18 source rows.  Their
    # lengths are the exact ink counts of those rows, so no outside font or
    # decorative bitmap is involved.
    for row_index, row in enumerate(LOGICAL_ICON):
        ink = row.count("#")
        if ink:
            left = 28 + row_index * 15
            canvas.rectangle(left, 151, left + ink * 2 - 1, 152, 24)

    # A restrained shadow gives the mark depth; both layers are the exact same
    # Regionally Famous-authored icon grid used by icon.bin.
    canvas.stamp_icon(MARK_X + 4, MARK_Y + 4, MARK_SCALE, 56)
    canvas.stamp_icon(MARK_X, MARK_Y, MARK_SCALE, 255)

    return tuple(bytes(row) for row in canvas.rows)


def platform_bytes() -> bytes:
    """Encode the APF bitmap rotated 90 degrees counter-clockwise.

    ``display_brightness`` is a 521x165 upright display raster.  APF stores
    graphical assets as the row-major 165x521 raster produced by a 90-degree
    counter-clockwise rotation.  For stored row ``y`` and column ``x`` this
    is ``stored[y][x] = display[x][520-y]``.
    """

    display = display_brightness()
    return b"".join(
        bytes((display[stored_x][WIDTH - 1 - stored_y], 0x00))
        for stored_y in range(WIDTH)
        for stored_x in range(HEIGHT)
    )


def preview_bytes() -> bytes:
    """Return a dependency-free PGM preview in display orientation."""

    pixels = b"".join(display_brightness())
    return f"P5\n{WIDTH} {HEIGHT}\n255\n".encode("ascii") + pixels


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=pathlib.Path,
        default=DEFAULT_OUTPUT,
        help=f"platform-art output (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail unless --output already equals the generated art",
    )
    parser.add_argument(
        "--preview",
        type=pathlib.Path,
        help="also write an upright 521x165 PGM preview",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    generated = platform_bytes()
    output = args.output.resolve()

    if args.check:
        try:
            existing = output.read_bytes()
        except FileNotFoundError:
            print(f"missing generated platform art: {output}", file=sys.stderr)
            return 1
        if existing != generated:
            print(f"stale generated platform art: {output}", file=sys.stderr)
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
