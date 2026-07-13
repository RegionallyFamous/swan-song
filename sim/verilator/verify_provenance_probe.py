#!/usr/bin/env python3
"""Verify the exact ROM-to-IRAM GDMA transaction sequence in a v3 trace."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


EXPECTED = (
    ("read", 0xF0100, 0x1234, "cart_rom_linear", 0x0100),
    ("write", 0x04000, 0x1234, "iram", 0x4000),
    ("read", 0xF0102, 0x5678, "cart_rom_linear", 0x0102),
    ("write", 0x04002, 0x5678, "iram", 0x4002),
)


def verify(path: Path) -> None:
    observed: list[tuple[str, int, int, str, int]] = []
    with path.open(newline="", encoding="utf-8") as source:
        for line, row in enumerate(csv.DictReader(source), start=2):
            if row["event"] != "mem" or row["initiator"] != "gdma":
                continue
            if row["byte_enable"] != "3" or row["origin_status"] != "not_applicable":
                raise ValueError(f"line {line}: invalid GDMA metadata")
            if row["instruction_id"] or row["origin_pc"]:
                raise ValueError(f"line {line}: DMA event has a CPU origin")
            observed.append(
                (
                    row["access"],
                    int(row["address"]),
                    int(row["value"]),
                    row["space"],
                    int(row["mapped_offset"]),
                )
            )
    if tuple(observed) != EXPECTED:
        raise ValueError(f"unexpected GDMA sequence: {observed!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    args = parser.parse_args()
    try:
        verify(args.trace)
    except (OSError, ValueError, KeyError) as error:
        raise SystemExit(f"{args.trace}: {error}") from error
    print(f"PASS {args.trace} exact GDMA ROM-to-IRAM provenance")


if __name__ == "__main__":
    main()
