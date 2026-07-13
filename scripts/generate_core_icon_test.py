#!/usr/bin/env python3
"""Focused tests for the deterministic APF core-author icon."""

from __future__ import annotations

import hashlib
import pathlib
import subprocess
import sys
import tempfile
import unittest

from generate_core_icon import (
    DEFAULT_OUTPUT,
    DISPLAY_SIZE,
    LOGICAL_ICON,
    LOGICAL_SIZE,
    PIXEL_SCALE,
    display_brightness,
    icon_bytes,
)


SCRIPT = pathlib.Path(__file__).with_name("generate_core_icon.py")
EXPECTED_SHA256 = "5f3b3da0162cfa984933fd86977fda94a06bf6773447f9f5dbba8deda55b92a1"


def decode_display(data: bytes) -> tuple[tuple[int, ...], ...]:
    if len(data) != DISPLAY_SIZE * DISPLAY_SIZE * 2:
        raise ValueError("wrong APF icon size")
    words = tuple(data[index : index + 2] for index in range(0, len(data), 2))
    stored = tuple(
        tuple(words[y * DISPLAY_SIZE + x][0] for x in range(DISPLAY_SIZE))
        for y in range(DISPLAY_SIZE)
    )
    # Inverse of the generator's counter-clockwise storage rotation.
    return tuple(
        tuple(stored[DISPLAY_SIZE - 1 - x][y] for x in range(DISPLAY_SIZE))
        for y in range(DISPLAY_SIZE)
    )


class GenerateCoreIconTest(unittest.TestCase):
    def test_source_uses_documented_two_by_two_scale_and_safe_margin(self) -> None:
        self.assertEqual(len(LOGICAL_ICON), LOGICAL_SIZE)
        self.assertTrue(all(len(row) == LOGICAL_SIZE for row in LOGICAL_ICON))
        self.assertTrue(all(set(row) <= {".", "#"} for row in LOGICAL_ICON))
        self.assertTrue(all(pixel == "." for pixel in LOGICAL_ICON[0]))
        self.assertTrue(all(pixel == "." for pixel in LOGICAL_ICON[-1]))
        self.assertTrue(all(row[0] == row[-1] == "." for row in LOGICAL_ICON))

        display = display_brightness()
        self.assertEqual((len(display), len(display[0])), (36, 36))
        for logical_y, row in enumerate(LOGICAL_ICON):
            for logical_x, pixel in enumerate(row):
                expected = 0x00 if pixel == "#" else 0xFF
                block = {
                    display[logical_y * PIXEL_SCALE + y][logical_x * PIXEL_SCALE + x]
                    for y in range(PIXEL_SCALE)
                    for x in range(PIXEL_SCALE)
                }
                self.assertEqual(block, {expected})

    def test_binary_format_rotation_and_reviewed_digest(self) -> None:
        generated = icon_bytes()
        self.assertEqual(len(generated), 36 * 36 * 2)
        words = {
            generated[index : index + 2]
            for index in range(0, len(generated), 2)
        }
        self.assertEqual(words, {b"\x00\x00", b"\xff\x00"})
        self.assertEqual(decode_display(generated), display_brightness())
        self.assertEqual(hashlib.sha256(generated).hexdigest(), EXPECTED_SHA256)

    def test_checked_in_icon_is_exact_generated_output(self) -> None:
        self.assertEqual(DEFAULT_OUTPUT.read_bytes(), icon_bytes())
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--check"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("verified", result.stdout)

    def test_check_rejects_a_stale_binary(self) -> None:
        with tempfile.TemporaryDirectory(prefix="swan-song-icon-test-") as temporary:
            output = pathlib.Path(temporary) / "icon.bin"
            output.write_bytes(icon_bytes()[:-2])
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--output", str(output), "--check"],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("stale generated core icon", result.stderr)


if __name__ == "__main__":
    unittest.main()
