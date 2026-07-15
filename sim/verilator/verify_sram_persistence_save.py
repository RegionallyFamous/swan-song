#!/usr/bin/env python3
"""Verify one exact save emitted by the translated SwanTop persistence probe."""

from __future__ import annotations

import argparse
import os
import stat
from pathlib import Path

import generate_sram_persistence_probes as probes


GENERATIONS = {
    probes.GENERATION_1: probes.PATTERN_1,
    probes.GENERATION_2: probes.PATTERN_2,
}
VALID_RESULTS = {
    (probes.GENERATION_1, probes.STATUS_INITIALIZED),
    (probes.GENERATION_2, probes.STATUS_PERSISTED_1_TO_2),
    (probes.GENERATION_1, probes.STATUS_PERSISTED_2_TO_1),
}


def open_exact_regular_file(
    path: Path, expected_size: int, description: str
) -> tuple[int, os.stat_result]:
    flags = os.O_RDONLY | os.O_NONBLOCK
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f"{description} must be a regular file")
        if before.st_nlink != 1:
            raise ValueError(f"{description} must not be hard-linked")
        if before.st_size != expected_size:
            raise ValueError(
                f"{description} size mismatch: expected {expected_size}, "
                f"got {before.st_size}"
            )
        return descriptor, before
    except BaseException:
        os.close(descriptor)
        raise


def read_open_exact_regular_file(
    descriptor: int,
    before: os.stat_result,
    expected_size: int,
    description: str,
) -> bytes:
    """Read and revalidate one already-open immutable regular file."""

    result = bytearray()
    while len(result) < expected_size:
        chunk = os.read(descriptor, min(64 * 1024, expected_size - len(result)))
        if not chunk:
            raise ValueError(f"{description} changed while it was being read")
        result.extend(chunk)
    if os.read(descriptor, 1):
        raise ValueError(f"{description} changed while it was being read")

    after = os.fstat(descriptor)
    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
        before.st_nlink,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
        after.st_nlink,
    )
    if identity_after != identity_before:
        raise ValueError(f"{description} changed while it was being read")
    return bytes(result)


def read_exact_regular_file(
    path: Path, expected_size: int, description: str = "save"
) -> bytes:
    """Read one immutable-sized regular file without following symlinks."""

    descriptor, before = open_exact_regular_file(
        path, expected_size, description
    )
    try:
        return read_open_exact_regular_file(
            descriptor, before, expected_size, description
        )
    finally:
        os.close(descriptor)


def expected_image(
    save_type: int, model: str, generation: int, status: int
) -> bytes:
    if save_type not in probes.SAVE_TYPES:
        raise ValueError(f"unsupported save type 0x{save_type:02x}")
    if model not in probes.MODELS:
        raise ValueError(f"unsupported model: {model}")
    if generation not in GENERATIONS:
        raise ValueError(f"unsupported generation 0x{generation:04x}")
    if not 0 <= status <= 0xFF:
        raise ValueError("status must fit in one byte")
    if (generation, status) not in VALID_RESULTS:
        raise ValueError(
            f"impossible successful generation/status pair: "
            f"0x{generation:04x}/0x{status:02x}"
        )

    geometry = probes.SAVE_TYPES[save_type]
    result = bytearray(geometry.bytes)
    result[0:2] = probes.SIGNATURE.to_bytes(2, "little")
    result[2:4] = generation.to_bytes(2, "little")
    result[4] = status
    result[5] = save_type
    result[6] = probes.MODELS[model]
    pattern = GENERATIONS[generation]
    for bank in range(geometry.banks):
        base = bank * 0x10000
        word = (pattern + bank) & 0xFFFF
        result[base + 0x0100 : base + 0x0102] = word.to_bytes(2, "little")
        result[base + 0xFFFE : base + 0x10000] = (
            (~word) & 0xFFFF
        ).to_bytes(2, "little")
    return bytes(result)


def expected_failure_image(imported: bytes, save_type: int, model: str) -> bytes:
    """Return the exact image after a corrupt import publishes failure."""

    if save_type not in probes.SAVE_TYPES:
        raise ValueError(f"unsupported save type 0x{save_type:02x}")
    if model not in probes.MODELS:
        raise ValueError(f"unsupported model: {model}")
    expected_size = probes.SAVE_TYPES[save_type].bytes
    if len(imported) != expected_size:
        raise ValueError(
            f"imported save size mismatch: expected {expected_size}, "
            f"got {len(imported)}"
        )

    signature = int.from_bytes(imported[0:2], "little")
    generation = int.from_bytes(imported[2:4], "little")
    if signature != probes.SIGNATURE:
        raise ValueError(
            "import would take the successful uninitialized-save path, not failure"
        )
    if generation in GENERATIONS:
        pattern = GENERATIONS[generation]
        sentinels_match = True
        for bank in range(probes.SAVE_TYPES[save_type].banks):
            base = bank * 0x10000
            word = (pattern + bank) & 0xFFFF
            if (
                imported[base + 0x0100 : base + 0x0102]
                != word.to_bytes(2, "little")
                or imported[base + 0xFFFE : base + 0x10000]
                != ((~word) & 0xFFFF).to_bytes(2, "little")
            ):
                sentinels_match = False
                break
        if sentinels_match:
            raise ValueError(
                "import would take a successful persistence path, not failure"
            )

    result = bytearray(imported)
    result[4] = probes.STATUS_FAILURE
    result[5] = save_type
    result[6] = probes.MODELS[model]
    return bytes(result)


def verify_image(actual: bytes, expected: bytes) -> None:
    """Require exact size and content, including every unwritten byte."""

    if len(actual) != len(expected):
        raise ValueError(
            f"save size mismatch: expected {len(expected)}, got {len(actual)}"
        )
    if actual != expected:
        mismatch = next(
            index
            for index, (actual_byte, expected_byte) in enumerate(
                zip(actual, expected, strict=True)
            )
            if actual_byte != expected_byte
        )
        raise ValueError(
            f"save content mismatch at 0x{mismatch:05x}: "
            f"expected 0x{expected[mismatch]:02x}, got 0x{actual[mismatch]:02x}"
        )


def verify_save(
    path: Path, save_type: int, model: str, generation: int, status: int
) -> None:
    expected = expected_image(save_type, model, generation, status)
    actual = read_exact_regular_file(path, len(expected))
    verify_image(actual, expected)


def verify_failure_save(
    imported_path: Path, output_path: Path, save_type: int, model: str
) -> None:
    if save_type not in probes.SAVE_TYPES:
        raise ValueError(f"unsupported save type 0x{save_type:02x}")
    if model not in probes.MODELS:
        raise ValueError(f"unsupported model: {model}")
    expected_size = probes.SAVE_TYPES[save_type].bytes
    imported_descriptor, imported_stat = open_exact_regular_file(
        imported_path, expected_size, "imported save"
    )
    try:
        output_descriptor, output_stat = open_exact_regular_file(
            output_path, expected_size, "save"
        )
        try:
            if (
                imported_stat.st_dev == output_stat.st_dev
                and imported_stat.st_ino == output_stat.st_ino
            ):
                raise ValueError(
                    "imported save and failure output must be distinct artifacts"
                )
            imported = read_open_exact_regular_file(
                imported_descriptor,
                imported_stat,
                expected_size,
                "imported save",
            )
            actual = read_open_exact_regular_file(
                output_descriptor, output_stat, expected_size, "save"
            )
            expected = expected_failure_image(imported, save_type, model)
            verify_image(actual, expected)
        finally:
            os.close(output_descriptor)
    finally:
        os.close(imported_descriptor)


def integer(text: str) -> int:
    try:
        return int(text, 0)
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected an integer") from error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("save", type=Path)
    parser.add_argument("--save-type", required=True, type=integer)
    parser.add_argument("--model", required=True, choices=tuple(probes.MODELS))
    parser.add_argument("--generation", type=integer)
    parser.add_argument("--status", type=integer)
    parser.add_argument(
        "--failure-from",
        type=Path,
        metavar="IMPORTED_SAVE",
        help="verify exact 0xEE publication from a corrupt imported save",
    )
    args = parser.parse_args()
    try:
        if args.failure_from is not None:
            if args.generation is not None or args.status is not None:
                parser.error(
                    "--failure-from cannot be combined with --generation or --status"
                )
            verify_failure_save(
                args.failure_from, args.save, args.save_type, args.model
            )
        else:
            if args.generation is None or args.status is None:
                parser.error(
                    "--generation and --status are required without --failure-from"
                )
            verify_save(
                args.save,
                args.save_type,
                args.model,
                args.generation,
                args.status,
            )
    except (OSError, ValueError) as error:
        parser.error(str(error))
    if args.failure_from is not None:
        print(
            f"PASS {args.model} type 0x{args.save_type:02x} "
            "published exact corrupt-save failure status 0xee"
        )
    else:
        print(
            f"PASS {args.model} type 0x{args.save_type:02x} "
            f"generation 0x{args.generation:04x} status 0x{args.status:02x}"
        )


if __name__ == "__main__":
    main()
