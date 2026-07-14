#!/usr/bin/env python3
"""Independent focused tests for the deterministic Swan Wake platform art.

Test authorship copyright 2026 Regionally Famous.  This notice records
authorship only and does not declare a project-wide license.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import pathlib
import subprocess
import sys
import tempfile
import unittest

from generate_core_icon import LOGICAL_ICON


ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = pathlib.Path(__file__).with_name("generate_platform_art.py")
CHECKED_ART = ROOT / "dist/Platforms/_images/wonderswan.bin"
WIDTH = 521
HEIGHT = 165
MARK_X = 125
MARK_Y = 19
MARK_SCALE = 7
EXPECTED_SHA256 = "0161970791a9d7913bfd1d146cb92324644607dd4a287c61d7f5a6d8e8f8045e"
EXPECTED_BRIGHTNESS = {0, 24, 32, 48, 56, 64, 96, 112, 160, 192, 255}


def stored_brightness_rows(data: bytes) -> tuple[bytes, ...]:
    if len(data) != WIDTH * HEIGHT * 2:
        raise ValueError("wrong APF platform-art size")
    if any(data[index] for index in range(1, len(data), 2)):
        raise ValueError("low bytes are not zero")
    brightness = data[0::2]
    return tuple(
        brightness[y * HEIGHT : (y + 1) * HEIGHT]
        for y in range(WIDTH)
    )


def upright_brightness_rows(data: bytes) -> tuple[bytes, ...]:
    """Independently decode APF's stored 90-degree CCW raster."""

    stored = stored_brightness_rows(data)
    return tuple(
        bytes(stored[WIDTH - 1 - x][y] for x in range(WIDTH))
        for y in range(HEIGHT)
    )


class GeneratePlatformArtTest(unittest.TestCase):
    def test_checked_art_has_reviewed_binary_identity_and_palette(self) -> None:
        data = CHECKED_ART.read_bytes()
        stored = stored_brightness_rows(data)
        rows = upright_brightness_rows(data)
        self.assertEqual(hashlib.sha256(data).hexdigest(), EXPECTED_SHA256)
        self.assertEqual({value for row in rows for value in row}, EXPECTED_BRIGHTNESS)
        self.assertEqual((len(rows), len(rows[0])), (HEIGHT, WIDTH))
        self.assertEqual((len(stored), len(stored[0])), (WIDTH, HEIGHT))

    def test_white_mark_is_exactly_the_existing_logical_icon_grid(self) -> None:
        rows = upright_brightness_rows(CHECKED_ART.read_bytes())
        expected_white = sum(row.count("#") for row in LOGICAL_ICON) * MARK_SCALE**2
        actual_white = Counter(value for row in rows for value in row)[255]
        self.assertEqual(actual_white, expected_white)

        white = [
            (x, y)
            for y, row in enumerate(rows)
            for x, value in enumerate(row)
            if value == 255
        ]
        white_bounds = (
            min(x for x, _ in white),
            min(y for _, y in white),
            max(x for x, _ in white),
            max(y for _, y in white),
        )
        self.assertEqual(white_bounds, (139, 26, 243, 137))
        self.assertLess(white_bounds[2], WIDTH // 2)

        for logical_y, source_row in enumerate(LOGICAL_ICON):
            for logical_x, source_pixel in enumerate(source_row):
                if source_pixel != "#":
                    continue
                block = {
                    rows[MARK_Y + logical_y * MARK_SCALE + y][
                        MARK_X + logical_x * MARK_SCALE + x
                    ]
                    for y in range(MARK_SCALE)
                    for x in range(MARK_SCALE)
                }
                self.assertEqual(block, {255})

    def test_on_disk_coordinates_are_counterclockwise_not_upright(self) -> None:
        data = CHECKED_ART.read_bytes()
        stored = stored_brightness_rows(data)
        upright = upright_brightness_rows(data)

        # The top-left frame corner at display (18, 21) maps to stored
        # (21, 502): x/y swap and the 521-pixel axis is reversed.
        self.assertEqual(upright[21][18], 32)
        self.assertEqual(stored[WIDTH - 1 - 18][21], 32)

        # A direct upright row-major encoding has the same byte count and
        # pixel words, so size/palette checks alone cannot detect this bug.
        unrotated = b"".join(
            bytes((value, 0x00)) for row in upright for value in row
        )
        self.assertEqual(len(unrotated), len(data))
        self.assertNotEqual(unrotated, data)
        self.assertNotEqual(hashlib.sha256(unrotated).hexdigest(), EXPECTED_SHA256)

    def test_generator_is_host_deterministic_and_checked_file_is_current(self) -> None:
        with tempfile.TemporaryDirectory(prefix="swan-wake-test-") as temporary:
            output = pathlib.Path(temporary) / "wonderswan.bin"
            preview = pathlib.Path(temporary) / "swan-wake.pgm"
            generated = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--output",
                    str(output),
                    "--preview",
                    str(preview),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(generated.returncode, 0, generated.stderr)
            self.assertEqual(output.read_bytes(), CHECKED_ART.read_bytes())
            header, dimensions, maximum, pixels = preview.read_bytes().split(b"\n", 3)
            self.assertEqual((header, dimensions, maximum), (b"P5", b"521 165", b"255"))
            self.assertEqual(pixels, b"".join(upright_brightness_rows(output.read_bytes())))

            checked = subprocess.run(
                [sys.executable, str(SCRIPT), "--output", str(output), "--check"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(checked.returncode, 0, checked.stderr)
            self.assertIn("verified", checked.stdout)

        repository_check = subprocess.run(
            [sys.executable, str(SCRIPT), "--check"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(repository_check.returncode, 0, repository_check.stderr)

    def test_check_rejects_a_stale_binary(self) -> None:
        with tempfile.TemporaryDirectory(prefix="swan-wake-stale-") as temporary:
            output = pathlib.Path(temporary) / "wonderswan.bin"
            output.write_bytes(CHECKED_ART.read_bytes()[:-2])
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--output", str(output), "--check"],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("stale generated platform art", result.stderr)


if __name__ == "__main__":
    unittest.main()
