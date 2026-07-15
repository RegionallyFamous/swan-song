#!/usr/bin/env python3
"""Positive and mutation tests for the independent window-boundary verifier."""

from __future__ import annotations

import tempfile
from pathlib import Path

import generate_window_boundary_probe as generator
import verify_window_boundary_probe as verifier


def must_fail(function, *args, contains: str | None = None) -> None:
    try:
        function(*args)
    except ValueError as error:
        if contains is not None and contains not in str(error):
            raise AssertionError(f"expected {contains!r} in {str(error)!r}") from error
        return
    raise AssertionError(f"mutation passed {function.__name__}")


def _different(color: bytes) -> bytes:
    return verifier.MAGENTA if color != verifier.MAGENTA else verifier.GREEN


def main() -> int:
    # The coordinate oracle itself must classify every boundary as inside and
    # the immediately adjacent pixel as outside.
    for x, y in ((64, 40), (159, 40), (64, 103), (159, 103),
                 (64, 80), (159, 80), (120, 40), (120, 103)):
        assert verifier.inside_window(x, y)
    for x, y in ((63, 80), (160, 80), (120, 39), (120, 104)):
        assert not verifier.inside_window(x, y)

    with tempfile.TemporaryDirectory(prefix="swansong-window-verifier-") as name:
        root = Path(name)
        rom_dir = root / "roms"
        frame_dir = root / "frames"
        frame_dir.mkdir(parents=True)
        generated = generator.generate(rom_dir)

        for variant, rom_path in zip(verifier.VARIANTS, generated):
            frame_path = frame_dir / f"{variant}.rgb"
            expected = verifier.expected_frame(variant)
            frame_path.write_bytes(expected)

            assert verifier.verify_rom(rom_path, variant) == rom_path.read_bytes()
            assert verifier.verify_frame(frame_path, variant) == expected
            counts = verifier.verify_pair(rom_path, frame_path, variant)
            assert counts == {
                "boundary_samples": 24,
                "inclusive_edges": 4,
                "sprites": 8,
                "diagnostic_pixels": 256,
            }

            samples = verifier.boundary_samples(variant)
            assert len(samples) == 24
            assert len({(sample.x, sample.y) for sample in samples}) == len(samples)
            assert sum(sample.name.startswith("screen2-") for sample in samples) == 8
            assert sum(sample.name.startswith("sprite-inside-") for sample in samples) == 8
            assert sum(sample.name.startswith("sprite-outside-") for sample in samples) == 8

            # Every named boundary contract is independently mutation-tested.
            for sample in samples:
                changed = bytearray(expected)
                offset = (sample.y * verifier.WIDTH + sample.x) * 3
                changed[offset : offset + 3] = _different(sample.color)
                frame_path.write_bytes(changed)
                must_fail(
                    verifier.verify_frame,
                    frame_path,
                    variant,
                    contains=sample.name,
                )

            # A non-sampled interior mutation must still fail the whole-frame
            # identity, proving the verifier does not reduce to spot checks.
            changed = bytearray(expected)
            changed[(72 * verifier.WIDTH + 128) * 3] ^= 1
            frame_path.write_bytes(changed)
            must_fail(
                verifier.verify_frame,
                frame_path,
                variant,
                contains="whole stable frame mismatch",
            )

            frame_path.write_bytes(expected + b"\x00")
            must_fail(
                verifier.verify_frame,
                frame_path,
                variant,
                contains="frame size mismatch",
            )

            damaged = bytearray(rom_path.read_bytes())
            damaged[verifier.MARKER_OFFSET] ^= 1
            damaged_path = root / f"damaged-{variant}.wsc"
            damaged_path.write_bytes(damaged)
            must_fail(
                verifier.verify_rom,
                damaged_path,
                variant,
                contains="ROM size/hash mismatch",
            )

        # Complementary Screen 2 modes must differ while sprite masks retain
        # their own per-descriptor inside/outside behavior.
        inside_frame = verifier.expected_frame(verifier.INSIDE)
        outside_frame = verifier.expected_frame(verifier.OUTSIDE)
        assert inside_frame != outside_frame
        for x, y in ((64, 80), (63, 80), (159, 80), (160, 80)):
            assert verifier.pixel(inside_frame, x, y) != verifier.pixel(outside_frame, x, y)
        assert verifier.pixel(inside_frame, 64, 51) == verifier.GREEN
        assert verifier.pixel(outside_frame, 64, 51) == verifier.GREEN
        assert verifier.pixel(inside_frame, 63, 67) == verifier.MAGENTA
        assert verifier.pixel(outside_frame, 63, 67) == verifier.MAGENTA

    for function, args in (
        (verifier.expected_frame, ("invalid",)),
        (verifier.boundary_samples, ("invalid",)),
    ):
        must_fail(function, *args, contains="unsupported window-boundary variant")

    print("PASS window-boundary verifier: 48 named sample mutations plus whole-frame/ROM mutations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
