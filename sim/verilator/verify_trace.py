#!/usr/bin/env python3
"""Validate Swan Song structured traces with only the Python standard library."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path


FIELDS_V1 = ["cycle", "event", "physical_pc", "cs", "ip", "address", "value"]
FIELDS_V2 = [*FIELDS_V1, "role"]
MEM_FIELDS = [
    "initiator",
    "access",
    "byte_enable",
    "space",
    "mapped_offset",
    "instruction_id",
    "origin_pc",
    "origin_status",
]
FIELDS_V3 = [*FIELDS_V2, *MEM_FIELDS]
EVENTS = {"cpu", "bank", "vram", "mem"}
VRAM_ROLES = {
    "screen1_map",
    "screen1_tile",
    "screen2_map",
    "screen2_tile",
    "sprite_table",
    "sprite_tile",
}
MEM_INITIATORS = {"cpu", "gdma", "sdma"}
MEM_ACCESSES = {"read", "write"}
MEM_SPACES = {
    "iram",
    "cart_sram",
    "cart_rom0",
    "cart_rom1",
    "cart_rom_linear",
    "boot_rom",
    "unmapped",
    "absent_sram",
}
ORIGIN_STATUSES = {"exact", "unattributed", "not_applicable"}


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


def choice_set(choices: set[str], description: str):
    def parse(value: str) -> set[str]:
        result = {item.strip().lower() for item in value.split(",") if item.strip()}
        if "all" in result:
            result.remove("all")
            result.update(choices)
        unknown = result - choices
        if not result or unknown:
            detail = f": {', '.join(sorted(unknown))}" if unknown else ""
            raise argparse.ArgumentTypeError(f"unknown or empty {description} list{detail}")
        return result

    return parse


mem_initiator_set = choice_set(MEM_INITIATORS, "memory initiator")
mem_access_set = choice_set(MEM_ACCESSES, "memory access")
mem_space_set = choice_set(MEM_SPACES, "memory space")
origin_status_set = choice_set(ORIGIN_STATUSES, "origin status")


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


def wide_ranges(maximum: int, description: str):
    def parse(value: str) -> tuple[tuple[int, int], ...]:
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
                if not 0 <= first <= last <= maximum:
                    raise ValueError
                ranges.append((first, last))
        except ValueError as error:
            raise argparse.ArgumentTypeError(
                f"{description} must be ADDR or comma-separated START-END ranges "
                f"within 0..{maximum:#x}"
            ) from error
        return tuple(ranges)

    return parse


mem_address_ranges = wide_ranges(0xFFFFF, "memory address")
mem_offset_ranges = wide_ranges(0xFFFFFF, "memory offset")


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
    mem_initiator_filter: set[str] | None,
    mem_access_filter: set[str] | None,
    mem_space_filter: set[str] | None,
    mem_address_filter: tuple[tuple[int, int], ...] | None,
    mem_offset_filter: tuple[tuple[int, int], ...] | None,
    origin_status_filter: set[str] | None,
    origin_pc_filter: tuple[int, int] | None,
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
        elif reader.fieldnames == FIELDS_V3:
            schema = 3
        else:
            raise ValueError(f"unexpected CSV header: {reader.fieldnames!r}")
        if schema == 1 and (vram_role_filter is not None or required_vram_roles):
            raise ValueError("legacy v1 trace has no role field; VRAM role assertions require v2")
        mem_assertions = any(
            item is not None
            for item in (
                mem_initiator_filter,
                mem_access_filter,
                mem_space_filter,
                mem_address_filter,
                mem_offset_filter,
                origin_status_filter,
                origin_pc_filter,
            )
        ) or "mem" in required
        if schema < 3 and mem_assertions:
            raise ValueError("legacy v1/v2 trace has no memory provenance fields; memory assertions require v3")

        for line, row in enumerate(reader, start=2):
            if schema == 1:
                row["role"] = ""
            if schema < 3:
                row.update({field: "" for field in MEM_FIELDS})
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
                empty(row, ("address", "value", "role", *MEM_FIELDS), line)
                expected_pc = ((cs << 4) + ip) & 0xFFFFF
                if physical_pc != expected_pc:
                    raise ValueError(
                        f"line {line}: physical_pc {physical_pc} does not match CS:IP ({expected_pc})"
                    )
                if pc_filter and not pc_filter[0] <= physical_pc <= pc_filter[1]:
                    raise ValueError(f"line {line}: CPU PC {physical_pc:#x} escaped requested filter")
            elif event == "bank":
                empty(row, ("physical_pc", "cs", "ip", "role", *MEM_FIELDS), line)
                address = number(row["address"], "address", line, 0xFF)
                number(row["value"], "value", line, 0xFF)
                if not 0xC0 <= address <= 0xC3:
                    raise ValueError(f"line {line}: bank address is outside 0xc0..0xc3: {address:#x}")
                bank_addresses.add(address)
            elif event == "vram":
                empty(row, ("physical_pc", "cs", "ip", "value", *MEM_FIELDS), line)
                address = number(row["address"], "address", line, 0xFFFF)
                if address & 1:
                    raise ValueError(f"line {line}: VRAM word address is not aligned: {address:#x}")
                if vram_address_filter and not any(
                    first <= address <= last for first, last in vram_address_filter
                ):
                    raise ValueError(
                        f"line {line}: VRAM address {address:#x} escaped requested filter"
                    )
                if schema >= 2:
                    role = row["role"]
                    if role not in VRAM_ROLES:
                        raise ValueError(f"line {line}: invalid or missing VRAM role: {role!r}")
                    if vram_role_filter is not None and role not in vram_role_filter:
                        raise ValueError(f"line {line}: VRAM role {role!r} escaped requested filter")
                    vram_roles.add(role)
            elif event == "mem":
                if schema < 3:
                    raise ValueError(f"line {line}: memory event requires v3 schema")
                empty(row, ("physical_pc", "cs", "ip", "role"), line)
                address = number(row["address"], "address", line, 0xFFFFF)
                number(row["value"], "value", line, 0xFFFF)
                number(row["byte_enable"], "byte_enable", line, 3)
                initiator = row["initiator"]
                access = row["access"]
                space = row["space"]
                origin_status = row["origin_status"]
                if initiator not in MEM_INITIATORS:
                    raise ValueError(f"line {line}: invalid memory initiator: {initiator!r}")
                if access not in MEM_ACCESSES:
                    raise ValueError(f"line {line}: invalid memory access: {access!r}")
                if space not in MEM_SPACES:
                    raise ValueError(f"line {line}: invalid memory space: {space!r}")
                if origin_status not in ORIGIN_STATUSES:
                    raise ValueError(f"line {line}: invalid origin status: {origin_status!r}")
                if mem_initiator_filter is not None and initiator not in mem_initiator_filter:
                    raise ValueError(f"line {line}: memory initiator escaped requested filter")
                if mem_access_filter is not None and access not in mem_access_filter:
                    raise ValueError(f"line {line}: memory access escaped requested filter")
                if mem_space_filter is not None and space not in mem_space_filter:
                    raise ValueError(f"line {line}: memory space escaped requested filter")
                if mem_address_filter and not any(
                    first <= address <= last for first, last in mem_address_filter
                ):
                    raise ValueError(f"line {line}: memory address escaped requested filter")
                if space in {"unmapped", "absent_sram"}:
                    if row["mapped_offset"]:
                        raise ValueError(f"line {line}: {space} must not have mapped_offset")
                    mapped_offset = None
                else:
                    mapped_offset = number(row["mapped_offset"], "mapped_offset", line, 0xFFFFFF)
                segment = address >> 16
                expected_segment = {
                    "iram": 0x0,
                    "unmapped": 0x0,
                    "cart_sram": 0x1,
                    "absent_sram": 0x1,
                    "cart_rom0": 0x2,
                    "cart_rom1": 0x3,
                }.get(space)
                if expected_segment is not None and segment != expected_segment:
                    raise ValueError(f"line {line}: {space} is inconsistent with raw address")
                if space == "cart_rom_linear" and segment < 0x4:
                    raise ValueError(f"line {line}: linear ROM requires address >= 0x40000")
                if space == "iram" and mapped_offset != (address & 0xFFFF):
                    raise ValueError(f"line {line}: IRAM offset does not match raw address")
                if space == "boot_rom" and mapped_offset is not None and mapped_offset > 0x1FFF:
                    raise ValueError(f"line {line}: boot ROM offset exceeds 8 KiB")
                if mem_offset_filter and (
                    mapped_offset is None
                    or not any(first <= mapped_offset <= last for first, last in mem_offset_filter)
                ):
                    raise ValueError(f"line {line}: memory offset escaped requested filter")
                if origin_status_filter is not None and origin_status not in origin_status_filter:
                    raise ValueError(f"line {line}: origin status escaped requested filter")
                if origin_status == "exact":
                    number(row["instruction_id"], "instruction_id", line, 0xFFFFFFFF)
                    origin_pc = number(row["origin_pc"], "origin_pc", line, 0xFFFFF)
                    if initiator != "cpu":
                        raise ValueError(f"line {line}: exact origin requires CPU initiator")
                    if origin_pc_filter and not origin_pc_filter[0] <= origin_pc <= origin_pc_filter[1]:
                        raise ValueError(f"line {line}: origin PC escaped requested filter")
                else:
                    empty(row, ("instruction_id", "origin_pc"), line)
                    if origin_status == "not_applicable" and initiator == "cpu":
                        raise ValueError(f"line {line}: CPU memory event cannot use not_applicable origin")
                    if origin_status == "unattributed" and initiator != "cpu":
                        raise ValueError(f"line {line}: DMA memory event must use not_applicable origin")
                    if origin_pc_filter:
                        raise ValueError(f"line {line}: unattributed event escaped origin PC filter")
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
    parser.add_argument("--mem-initiator", type=mem_initiator_set)
    parser.add_argument("--mem-access", type=mem_access_set)
    parser.add_argument("--mem-space", type=mem_space_set)
    parser.add_argument("--mem-address", type=mem_address_ranges)
    parser.add_argument("--mem-offset", type=mem_offset_ranges)
    parser.add_argument("--mem-origin", type=origin_status_set)
    parser.add_argument("--origin-pc", type=pc_range)
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
            args.mem_initiator,
            args.mem_access,
            args.mem_space,
            args.mem_address,
            args.mem_offset,
            args.mem_origin,
            args.origin_pc,
        )
    except (OSError, ValueError) as error:
        raise SystemExit(f"{args.trace}: {error}") from error
    summary = " ".join(f"{event}={counts[event]}" for event in sorted(counts))
    print(f"PASS {args.trace} {summary}")


if __name__ == "__main__":
    main()
