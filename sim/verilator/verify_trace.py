#!/usr/bin/env python3
"""Validate Swan Song structured traces with only the Python standard library."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path


FIELDS_V1 = ["cycle", "event", "physical_pc", "cs", "ip", "address", "value"]
FIELDS_V2 = [*FIELDS_V1, "role"]
EVENTS = {"cpu", "bank", "vram"}
VRAM_ROLES = {
    "screen1_map",
    "screen1_tile",
    "screen2_map",
    "screen2_tile",
    "sprite_table",
    "sprite_tile",
}


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


def address_ranges(value: str) -> tuple[tuple[int, int], ...]:
    ranges: list[tuple[int, int]] = []
    try:
        for item in value.split(","):
            item = item.strip()
            if not item:
                raise ValueError
            if "-" in item:
                first_text, last_text = item.split("-", 1)
                first, last = int(first_text, 0), int(last_text, 0)
            else:
                first = last = int(item, 0)
            if not 0 <= first <= last <= 0xFFFF:
                raise ValueError
            ranges.append((first, last))
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "VRAM address must be ADDR or comma-separated START-END ranges within 0..0xffff"
        ) from error
    return tuple(ranges)


def vram_role_set(value: str) -> set[str]:
    result = {item.strip().lower() for item in value.split(",") if item.strip()}
    if "all" in result:
        result.remove("all")
        result.update(VRAM_ROLES)
    unknown = result - VRAM_ROLES
    if not result or unknown:
        detail = f": {', '.join(sorted(unknown))}" if unknown else ""
        raise argparse.ArgumentTypeError(f"unknown or empty VRAM role list{detail}")
    return result


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
    vram_address_filter: tuple[tuple[int, int], ...] | None,
    vram_role_filter: set[str] | None,
    required_vram_roles: set[str],
) -> Counter[str]:
    counts: Counter[str] = Counter()
    bank_addresses: set[int] = set()
    vram_roles: set[str] = set()
    previous_cycle = -1

    with path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames == FIELDS_V1:
            schema = 1
        elif reader.fieldnames == FIELDS_V2:
            schema = 2
        else:
            raise ValueError(f"unexpected CSV header: {reader.fieldnames!r}")
        if schema == 1 and (vram_role_filter is not None or required_vram_roles):
            raise ValueError("legacy v1 trace has no role field; VRAM role assertions require v2")

        for line, row in enumerate(reader, start=2):
            if schema == 1:
                row["role"] = ""
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
                empty(row, ("address", "value", "role"), line)
                expected_pc = ((cs << 4) + ip) & 0xFFFFF
                if physical_pc != expected_pc:
                    raise ValueError(
                        f"line {line}: physical_pc {physical_pc} does not match CS:IP ({expected_pc})"
                    )
                if pc_filter and not pc_filter[0] <= physical_pc <= pc_filter[1]:
                    raise ValueError(f"line {line}: CPU PC {physical_pc:#x} escaped requested filter")
            elif event == "bank":
                empty(row, ("physical_pc", "cs", "ip", "role"), line)
                address = number(row["address"], "address", line, 0xFF)
                number(row["value"], "value", line, 0xFF)
                if not 0xC0 <= address <= 0xC3:
                    raise ValueError(f"line {line}: bank address is outside 0xc0..0xc3: {address:#x}")
                bank_addresses.add(address)
            elif event == "vram":
                empty(row, ("physical_pc", "cs", "ip", "value"), line)
                address = number(row["address"], "address", line, 0xFFFF)
                if address & 1:
                    raise ValueError(f"line {line}: VRAM word address is not aligned: {address:#x}")
                if vram_address_filter and not any(
                    first <= address <= last for first, last in vram_address_filter
                ):
                    raise ValueError(
                        f"line {line}: VRAM address {address:#x} escaped requested filter"
                    )
                if schema == 2:
                    role = row["role"]
                    if role not in VRAM_ROLES:
                        raise ValueError(f"line {line}: invalid or missing VRAM role: {role!r}")
                    if vram_role_filter is not None and role not in vram_role_filter:
                        raise ValueError(f"line {line}: VRAM role {role!r} escaped requested filter")
                    vram_roles.add(role)
            counts[event] += 1

    missing = required - counts.keys()
    if missing:
        raise ValueError(f"missing required event type(s): {', '.join(sorted(missing))}")
    missing_bank_addresses = required_bank_addresses - bank_addresses
    if missing_bank_addresses:
        rendered = ", ".join(f"{address:#x}" for address in sorted(missing_bank_addresses))
        raise ValueError(f"missing required bank address(es): {rendered}")
    missing_vram_roles = required_vram_roles - vram_roles
    if missing_vram_roles:
        raise ValueError(f"missing required VRAM role(s): {', '.join(sorted(missing_vram_roles))}")
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--allowed", type=event_set, default=EVENTS)
    parser.add_argument("--require", type=event_set, default=set())
    parser.add_argument("--pc-range", type=pc_range)
    parser.add_argument(
        "--vram-address",
        type=address_ranges,
        help="require all VRAM events to stay within ADDR or START-END ranges",
    )
    parser.add_argument(
        "--vram-role",
        type=vram_role_set,
        help="require all VRAM events to use one of these v2 roles",
    )
    parser.add_argument(
        "--require-bank-addresses",
        type=bank_address_set,
        default=set(),
        metavar="ADDR,...",
        help="require bank-write events for each listed address (for example 0xc0,0xc1)",
    )
    parser.add_argument(
        "--require-vram-roles",
        type=vram_role_set,
        default=set(),
        metavar="ROLE,...",
        help="require at least one v2 VRAM event for each listed role",
    )
    args = parser.parse_args()

    try:
        counts = verify(
            args.trace,
            args.allowed,
            args.require,
            args.pc_range,
            args.require_bank_addresses,
            args.vram_address,
            args.vram_role,
            args.require_vram_roles,
        )
    except (OSError, ValueError) as error:
        raise SystemExit(f"{args.trace}: {error}") from error
    summary = " ".join(f"{event}={counts[event]}" for event in sorted(counts))
    print(f"PASS {args.trace} {summary}")


if __name__ == "__main__":
    main()
