#!/usr/bin/env python3
"""Verify the exact mapper-write provenance emitted by the bank probe."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from verify_trace import FIELDS_V5


# These are full reset-to-probe instruction-chain identities, not instruction
# indices within PROGRAM. The origin PCs identify the common C0-C3 writes and
# Bandai 2003's accepted CE/CF/D0-D5 controls. Raw port identity is preserved,
# including the nonzero high bytes emitted by each 16-bit OUT.
EXPECTED = (
    (0xC0, 0x10, 7, 0xF0003),
    (0xC1, 0x21, 9, 0xF0007),
    (0xC2, 0x32, 11, 0xF000B),
    (0xC3, 0x43, 13, 0xF000F),
    (0xC0, 0x55, 15, 0xF0014),
    (0xC1, 0x66, 15, 0xF0014),
    (0xCF, 0x54, 17, 0xF0018),
    (0xD0, 0x03, 19, 0xF001D),
    (0xD1, 0x01, 19, 0xF001D),
    (0xD2, 0x04, 21, 0xF0022),
    (0xD3, 0x02, 21, 0xF0022),
    (0xD4, 0x05, 23, 0xF0027),
    (0xD5, 0x03, 23, 0xF0027),
    (0xCE, 0x01, 25, 0xF002B),
)

POPULATED_FIELDS = {
    "cycle",
    "event",
    "address",
    "value",
    "instruction_id",
    "origin_pc",
    "origin_status",
}
EMPTY_FIELDS = tuple(field for field in FIELDS_V5 if field not in POPULATED_FIELDS)


def number(value: str, field: str, line: int, maximum: int) -> int:
    if not value:
        raise ValueError(f"line {line}: {field} is empty")
    try:
        result = int(value, 10)
    except ValueError as error:
        raise ValueError(
            f"line {line}: {field} is not a decimal integer: {value!r}"
        ) from error
    if not 0 <= result <= maximum:
        raise ValueError(f"line {line}: {field} is outside 0..{maximum}: {result}")
    return result


def verify(path: Path) -> None:
    observed: list[tuple[int, int, int, int]] = []
    previous_cycle = -1

    with path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != FIELDS_V5:
            raise ValueError(
                "bank provenance requires the exact v5 trace header; "
                f"got {reader.fieldnames!r}"
            )

        for line, row in enumerate(reader, start=2):
            if row["event"] != "bank":
                raise ValueError(f"line {line}: unexpected event {row['event']!r}")

            populated = [field for field in EMPTY_FIELDS if row[field]]
            if populated:
                raise ValueError(
                    f"line {line}: unexpected fields for bank: {', '.join(populated)}"
                )

            cycle = number(row["cycle"], "cycle", line, (1 << 64) - 1)
            if cycle <= previous_cycle:
                raise ValueError(
                    f"line {line}: cycle {cycle} does not follow cycle {previous_cycle}"
                )
            previous_cycle = cycle

            if row["origin_status"] != "exact":
                raise ValueError(
                    f"line {line}: bank origin_status is not exact: "
                    f"{row['origin_status']!r}"
                )

            instruction_id = number(
                row["instruction_id"], "instruction_id", line, 0xFFFFFFFF
            )
            if instruction_id == 0:
                raise ValueError(f"line {line}: instruction_id must be nonzero")
            observed.append(
                (
                    number(row["address"], "address", line, 0xFF),
                    number(row["value"], "value", line, 0xFF),
                    instruction_id,
                    number(row["origin_pc"], "origin_pc", line, 0xFFFFF),
                )
            )

    if tuple(observed) != EXPECTED:
        raise ValueError(f"unexpected mapper-write sequence: {observed!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    args = parser.parse_args()
    try:
        verify(args.trace)
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit(f"{args.trace}: {error}") from error
    print(f"PASS {args.trace} exact mapper-write provenance")


if __name__ == "__main__":
    main()
