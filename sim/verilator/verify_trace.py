#!/usr/bin/env python3
"""Validate Swan Song structured traces with only the Python standard library."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path


FIELDS = ["cycle", "event", "physical_pc", "cs", "ip", "address", "value"]
EVENTS = {"cpu", "bank", "vram"}


def number(value: str, field: str, line: int, maximum: int) -> int:
    if not value:
        raise ValueError(f"line {line}: {field} is empty")
    try:
        result = int(value, 10)
    except ValueError as error:
        raise ValueError(f"line {line}: {field} is not a decimal integer: {value!r}") from error
    if not 0 <= result <= maximum:
        raise ValueError(f"line {line}: {field} is outside 0..{maximum}: {result}")
    return result


def empty(row: dict[str, str], fields: tuple[str, ...], line: int) -> None:
    populated = [field for field in fields if row[field]]
    if populated:
        raise ValueError(f"line {line}: unexpected fields for {row['event']}: {', '.join(populated)}")


def event_set(value: str) -> set[str]:
    result = {item.strip().lower() for item in value.split(",") if item.strip()}
    unknown = result - EVENTS
    if unknown:
        raise argparse.ArgumentTypeError(f"unknown event type(s): {', '.join(sorted(unknown))}")
    return result


def pc_range(value: str) -> tuple[int, int]:
    try:
        first_text, last_text = value.split("-", 1)
        first, last = int(first_text, 0), int(last_text, 0)
    except ValueError as error:
        raise argparse.ArgumentTypeError("PC range must be START-END") from error
    if not 0 <= first <= last <= 0xFFFFF:
        raise argparse.ArgumentTypeError("PC range must be ordered within 0x00000..0xfffff")
    return first, last


def bank_address_set(value: str) -> set[int]:
    try:
        result = {int(item.strip(), 0) for item in value.split(",") if item.strip()}
    except ValueError as error:
        raise argparse.ArgumentTypeError("bank addresses must be comma-separated integers") from error
    if not result:
        raise argparse.ArgumentTypeError("at least one bank address is required")
    invalid = sorted(address for address in result if not 0xC0 <= address <= 0xC3)
    if invalid:
        rendered = ", ".join(f"{address:#x}" for address in invalid)
        raise argparse.ArgumentTypeError(f"bank addresses must be within 0xc0..0xc3: {rendered}")
    return result


def verify(
    path: Path,
    allowed: set[str],
    required: set[str],
    pc_filter: tuple[int, int] | None,
    required_bank_addresses: set[int],
) -> Counter[str]:
    counts: Counter[str] = Counter()
    bank_addresses: set[int] = set()
    previous_cycle = -1

    with path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != FIELDS:
            raise ValueError(f"unexpected CSV header: {reader.fieldnames!r}")

        for line, row in enumerate(reader, start=2):
            event = row["event"]
            if event not in allowed:
                raise ValueError(f"line {line}: event {event!r} is not allowed")
            cycle = number(row["cycle"], "cycle", line, (1 << 64) - 1)
            if cycle < previous_cycle:
                raise ValueError(f"line {line}: cycle {cycle} follows later cycle {previous_cycle}")
            previous_cycle = cycle

            if event == "cpu":
                physical_pc = number(row["physical_pc"], "physical_pc", line, 0xFFFFF)
                cs = number(row["cs"], "cs", line, 0xFFFF)
                ip = number(row["ip"], "ip", line, 0xFFFF)
                empty(row, ("address", "value"), line)
                expected_pc = ((cs << 4) + ip) & 0xFFFFF
                if physical_pc != expected_pc:
                    raise ValueError(
                        f"line {line}: physical_pc {physical_pc} does not match CS:IP ({expected_pc})"
                    )
                if pc_filter and not pc_filter[0] <= physical_pc <= pc_filter[1]:
                    raise ValueError(f"line {line}: CPU PC {physical_pc:#x} escaped requested filter")
            elif event == "bank":
                empty(row, ("physical_pc", "cs", "ip"), line)
                address = number(row["address"], "address", line, 0xFF)
                number(row["value"], "value", line, 0xFF)
                if not 0xC0 <= address <= 0xC3:
                    raise ValueError(f"line {line}: bank address is outside 0xc0..0xc3: {address:#x}")
                bank_addresses.add(address)
            elif event == "vram":
                empty(row, ("physical_pc", "cs", "ip", "value"), line)
                number(row["address"], "address", line, 0xFFFF)
            counts[event] += 1

    missing = required - counts.keys()
    if missing:
        raise ValueError(f"missing required event type(s): {', '.join(sorted(missing))}")
    missing_bank_addresses = required_bank_addresses - bank_addresses
    if missing_bank_addresses:
        rendered = ", ".join(f"{address:#x}" for address in sorted(missing_bank_addresses))
        raise ValueError(f"missing required bank address(es): {rendered}")
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--allowed", type=event_set, default=EVENTS)
    parser.add_argument("--require", type=event_set, default=set())
    parser.add_argument("--pc-range", type=pc_range)
    parser.add_argument(
        "--require-bank-addresses",
        type=bank_address_set,
        default=set(),
        metavar="ADDR,...",
        help="require bank-write events for each listed address (for example 0xc0,0xc1)",
    )
    args = parser.parse_args()

    try:
        counts = verify(
            args.trace,
            args.allowed,
            args.require,
            args.pc_range,
            args.require_bank_addresses,
        )
    except (OSError, ValueError) as error:
        raise SystemExit(f"{args.trace}: {error}") from error
    summary = " ".join(f"{event}={counts[event]}" for event in sorted(counts))
    print(f"PASS {args.trace} {summary}")


if __name__ == "__main__":
    main()
