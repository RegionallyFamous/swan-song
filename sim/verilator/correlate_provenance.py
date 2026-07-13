#!/usr/bin/env python3
"""Correlate v4/v5 display reads with observed IRAM writers and ROM sources."""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, TextIO

from verify_trace import FIELDS_V4, FIELDS_V5, FIELDS_V6, VRAM_ROLES


ROM_SPACES = {"cart_rom0", "cart_rom1", "cart_rom_linear"}
OUTPUT_FIELDS = [
    "fetch_index",
    "cycle",
    "role",
    "address",
    "fetch_value",
    "fetch_collision",
    "reconstructed_value",
    "scoreboard_status",
    "ram_status",
    "writer_summary",
    "source_summary",
    "coverage_status",
    "lo_value",
    "lo_write_line",
    "lo_write_cycle",
    "lo_initiator",
    "lo_instruction_id",
    "lo_origin_pc",
    "lo_source_space",
    "lo_source_offset",
    "lo_source_read_cycle",
    "hi_value",
    "hi_write_line",
    "hi_write_cycle",
    "hi_initiator",
    "hi_instruction_id",
    "hi_origin_pc",
    "hi_source_space",
    "hi_source_offset",
    "hi_source_read_cycle",
]


@dataclass(frozen=True)
class TraceRow:
    line: int
    values: dict[str, str]

    @property
    def cycle(self) -> int:
        return int(self.values["cycle"])


@dataclass(frozen=True)
class ByteVersion:
    value: int
    write: TraceRow | None
    source_read: TraceRow | None = None
    source_lane: int | None = None


POWERUP_ZERO = ByteVersion(0, None)
REP_MOVSB_WORD = 0xA4F3
REP_OPCODE_MAX_AGE = 4096
REP_TRANSFER_MAX_AGE = 4096


class MemorySourceTracker:
    """Conservatively pair DMA and opcode-bound CPU source transfers.

    CPU instruction ownership alone is not dataflow proof.  A CPU source is
    therefore accepted only after a trace-observed F3 A4 origin signature and
    one immediate exact same-instruction ROM-read/IRAM-byte-write pair.  An
    unattributed row alone is not proof of prefetch.  Any intervening memory
    row retires the active CPU chain, as does an excessive signature or
    transfer age.  CPU reads expose a raw 16-bit bus value with byte_enable=0,
    so MOVSB consumes only its low byte at the exact mapped offset; this
    deliberately does not generalize to MOVSW.
    """

    def __init__(self) -> None:
        self.pending_gdma_read: TraceRow | None = None
        self.pending_cpu_read: TraceRow | None = None
        self.rep_opcode_signatures: dict[int, TraceRow] = {}
        self.active_rep_identity: tuple[int, int] | None = None
        self.active_rep_last_cycle: int | None = None
        self.cpu_rom_movsb_bytes = 0
        self.cpu_rom_movsb_origins: set[int] = set()

    @staticmethod
    def _identity(row: TraceRow) -> tuple[int, int] | None:
        values = row.values
        if values["origin_status"] != "exact":
            return None
        try:
            instruction_id = int(values["instruction_id"])
            origin_pc = int(values["origin_pc"])
        except ValueError:
            return None
        if instruction_id <= 0 or not 0 <= origin_pc <= 0xFFFFF:
            return None
        return instruction_id, origin_pc

    def _remember_opcode_signature(self, row: TraceRow) -> None:
        values = row.values
        if (
            values["initiator"] != "cpu"
            or values["access"] != "read"
            or values["origin_status"] != "unattributed"
            or values["space"] not in ROM_SPACES
            or values["byte_enable"] != "0"
            or not values["mapped_offset"]
        ):
            return
        address = int(values["address"])
        mapped_offset = int(values["mapped_offset"])
        if (
            not (address & 1)
            and not (mapped_offset & 1)
            and int(values["value"]) == REP_MOVSB_WORD
        ):
            self.rep_opcode_signatures[address] = row
        else:
            self.rep_opcode_signatures.pop(address, None)

    def _is_rep_movsb_read(self, row: TraceRow, identity: tuple[int, int]) -> bool:
        _, origin_pc = identity
        values = row.values
        if (
            values["access"] != "read"
            or values["space"] not in ROM_SPACES
            or values["byte_enable"] != "0"
            or not values["mapped_offset"]
        ):
            return False
        if self.active_rep_identity == identity:
            return (
                self.active_rep_last_cycle is not None
                and 0 < row.cycle - self.active_rep_last_cycle <= REP_TRANSFER_MAX_AGE
            )
        signature = self.rep_opcode_signatures.get(origin_pc)
        if signature is None or not 0 < row.cycle - signature.cycle <= REP_OPCODE_MAX_AGE:
            return False
        self.rep_opcode_signatures.pop(origin_pc)
        self.active_rep_identity = identity
        self.active_rep_last_cycle = None
        return True

    def _retire_cpu_chain(self) -> None:
        self.active_rep_identity = None
        self.active_rep_last_cycle = None

    @staticmethod
    def _matches_cpu_byte_write(
        read: TraceRow, write: TraceRow, identity: tuple[int, int]
    ) -> bool:
        values = write.values
        return (
            MemorySourceTracker._identity(read) == identity
            and values["access"] == "write"
            and values["space"] == "iram"
            and values["byte_enable"] == "1"
            and values["mapped_offset"] == values["address"]
            and int(values["value"]) <= 0xFF
            and 0 < write.cycle - read.cycle <= REP_TRANSFER_MAX_AGE
            and (int(read.values["value"]) & 0xFF) == int(values["value"])
        )

    def observe(self, row: TraceRow) -> TraceRow | None:
        """Observe one completed mem row and return its exact source read."""

        values = row.values
        initiator, access = values["initiator"], values["access"]

        # An active CPU chain must alternate exact source reads and matching
        # byte writes in the completed memory stream.  Retiring the whole
        # chain on an interruption prevents a stale instruction ID from
        # authorizing later traffic without a fresh opcode signature.
        pending_cpu = self.pending_cpu_read
        self.pending_cpu_read = None

        identity = self._identity(row) if initiator == "cpu" else None
        if pending_cpu is not None:
            if (
                identity is not None
                and self.active_rep_identity == identity
                and self._matches_cpu_byte_write(pending_cpu, row, identity)
            ):
                self.cpu_rom_movsb_bytes += 1
                self.cpu_rom_movsb_origins.add(identity[1])
                self.active_rep_last_cycle = row.cycle
                return pending_cpu
            self._retire_cpu_chain()

        if initiator == "gdma":
            self._retire_cpu_chain()
            if access == "read":
                self.pending_gdma_read = row
                return None
            if access == "write":
                source = self.pending_gdma_read
                self.pending_gdma_read = None
                if (
                    source is not None
                    and source.values["value"] == values["value"]
                    and source.values["byte_enable"] == values["byte_enable"]
                ):
                    return source
            return None

        if initiator != "cpu":
            self._retire_cpu_chain()
            return None

        self._remember_opcode_signature(row)
        if identity is None:
            self._retire_cpu_chain()
            return None
        if self.active_rep_identity is not None and self.active_rep_identity != identity:
            self._retire_cpu_chain()
        if self._is_rep_movsb_read(row, identity):
            self.pending_cpu_read = row
            return None
        self._retire_cpu_chain()
        return None


def source_lane(source_read: TraceRow | None, write_lane: int) -> int | None:
    if source_read is None:
        return None
    return 0 if source_read.values["initiator"] == "cpu" else write_lane


def trace_fnv1a64(path: Path) -> str:
    value = 0xCBF29CE484222325
    with path.open("rb") as source:
        while chunk := source.read(16384):
            for byte in chunk:
                value ^= byte
                value = (value * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return f"{value:016x}"


def parse_range(value: str, maximum: int) -> tuple[int, int]:
    try:
        if "-" in value:
            first_text, last_text = value.split("-", 1)
            first, last = int(first_text, 0), int(last_text, 0)
        else:
            first = last = int(value, 0)
    except ValueError as error:
        raise argparse.ArgumentTypeError("range must be ADDR or START-END") from error
    if not 0 <= first <= last <= maximum:
        raise argparse.ArgumentTypeError(f"range must be within 0..{maximum:#x}")
    return first, last


def read_manifest(trace: Path) -> tuple[str, list[ByteVersion | None]]:
    path = Path(f"{trace}.manifest.json")
    if not path.exists():
        return "observed_only", [None] * 0x10000
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid trace manifest {path}: {error}") from error
    events = manifest.get("events")
    positive_integer = lambda value: (
        isinstance(value, int) and not isinstance(value, bool) and value > 0
    )
    try:
        binding_matches = (
            manifest.get("trace_size_bytes") == trace.stat().st_size
            and manifest.get("trace_fnv1a64") == trace_fnv1a64(trace)
        )
    except OSError as error:
        raise ValueError(f"cannot validate trace binding for {trace}: {error}") from error
    complete = (
        manifest.get("schema") == "swan-song-trace-manifest-v1"
        and manifest.get("trace_schema") in {4, 5, 6}
        and binding_matches
        and manifest.get("capture_start") == "reset_release"
        and manifest.get("capture_completed") is True
        and positive_integer(manifest.get("capture_cycles"))
        and positive_integer(manifest.get("completed_frames"))
        and positive_integer(manifest.get("rom_size"))
        and manifest.get("complete_memory_history") is True
        and manifest.get("complete_display_history") is True
        and manifest.get("memory_filters_active") is False
        and manifest.get("display_filters_active") is False
        and isinstance(events, dict)
        and events.get("mem") is True
        and events.get("vram") is True
        and manifest.get("savestate_inputs_asserted") is False
        and manifest.get("iram_initial_state") == "zero"
    )
    if complete:
        return "complete_from_reset", [POWERUP_ZERO] * 0x10000
    return "observed_only", [None] * 0x10000


def optional_int(row: TraceRow | None, field: str) -> str:
    if row is None:
        return ""
    return row.values[field]


def byte_fields(prefix: str, version: ByteVersion | None, address: int) -> dict[str, object]:
    result: dict[str, object] = {f"{prefix}_value": ""}
    if version is None:
        for suffix in (
            "write_line",
            "write_cycle",
            "initiator",
            "instruction_id",
            "origin_pc",
            "source_space",
            "source_offset",
            "source_read_cycle",
        ):
            result[f"{prefix}_{suffix}"] = ""
        return result

    result[f"{prefix}_value"] = version.value
    write = version.write
    result[f"{prefix}_write_line"] = "" if write is None else write.line
    result[f"{prefix}_write_cycle"] = "" if write is None else write.cycle
    result[f"{prefix}_initiator"] = optional_int(write, "initiator")
    result[f"{prefix}_instruction_id"] = optional_int(write, "instruction_id")
    result[f"{prefix}_origin_pc"] = optional_int(write, "origin_pc")
    source = version.source_read
    result[f"{prefix}_source_space"] = optional_int(source, "space")
    if source is not None and source.values["mapped_offset"] and version.source_lane is not None:
        result[f"{prefix}_source_offset"] = (
            int(source.values["mapped_offset"]) + version.source_lane
        )
    else:
        result[f"{prefix}_source_offset"] = ""
    result[f"{prefix}_source_read_cycle"] = "" if source is None else source.cycle
    return result


def summarize_versions(
    low: ByteVersion | None, high: ByteVersion | None
) -> tuple[str, str, str]:
    if low is None and high is None:
        return "none_observed", "none_observed", "none_observed"
    if low is None:
        return "partial_high", "partial", "partial"
    if high is None:
        return "partial_low", "partial", "partial"

    same_write = low.write is high.write
    ram_status = "complete_same_write" if same_write else "complete_mixed_writes"
    if low.write is None and high.write is None:
        return ram_status, "initial_powerup", "initial_powerup"

    writes = [version.write for version in (low, high) if version.write is not None]
    initiators = {write.values["initiator"] for write in writes}
    origins = {write.values["origin_status"] for write in writes}
    if len(initiators) == 1 and initiators == {"cpu"}:
        writer = "cpu_exact" if origins == {"exact"} else "cpu_unattributed"
    elif len(initiators) == 1:
        writer = next(iter(initiators))
    else:
        writer = "mixed"

    source_reads = [version.source_read for version in (low, high)]
    known_sources = [source for source in source_reads if source is not None]
    source_initiators = {source.values["initiator"] for source in known_sources}
    if source_reads[0] is not None and source_reads[0] is source_reads[1]:
        source = source_reads[0]
        if source.values["initiator"] == "cpu" and source.values["space"] in ROM_SPACES:
            source_summary = "cpu_rom_movsb"
        else:
            source_summary = (
                "gdma_rom_same_transfer"
                if source.values["space"] in ROM_SPACES
                else "gdma_nonrom_same_transfer"
            )
    elif (
        len(known_sources) == 2
        and source_initiators == {"cpu"}
        and all(source.values["space"] in ROM_SPACES for source in known_sources)
    ):
        source_summary = "cpu_rom_movsb"
    elif any(source_reads):
        source_summary = "mixed_or_partial_sources"
    elif initiators == {"gdma"}:
        source_summary = "gdma_unpaired"
    elif initiators == {"cpu"}:
        source_summary = "cpu_write"
    else:
        source_summary = "mixed"
    return ram_status, writer, source_summary


def iter_rows(source: TextIO) -> Iterable[TraceRow]:
    reader = csv.DictReader(source)
    if reader.fieldnames not in (FIELDS_V4, FIELDS_V5, FIELDS_V6):
        raise ValueError(
            "provenance correlation requires an exact v4/v5/v6 header, "
            f"got {reader.fieldnames!r}"
        )
    previous_cycle = -1
    for line, values in enumerate(reader, start=2):
        try:
            cycle = int(values["cycle"])
        except ValueError as error:
            raise ValueError(f"line {line}: invalid cycle") from error
        if cycle < previous_cycle:
            raise ValueError(f"line {line}: cycles are not monotonic")
        previous_cycle = cycle
        yield TraceRow(line, values)


def correlate(
    trace: Path,
    output: TextIO,
    roles: set[str] | None = None,
    address_range: tuple[int, int] | None = None,
    only_status: set[str] | None = None,
    fail_on_mismatch: bool = False,
    require_matches: int = 0,
    require_complete_coverage: bool = False,
    require_exact_fetches: bool = False,
) -> dict[str, int]:
    coverage_status, iram = read_manifest(trace)
    if require_complete_coverage and coverage_status != "complete_from_reset":
        raise ValueError("trace manifest does not prove complete mem+vram history from reset")

    counts = {
        "fetches": 0,
        "written": 0,
        "match": 0,
        "mismatch": 0,
        "partial": 0,
        "unobserved": 0,
        "collision": 0,
        "cpu_exact": 0,
        "initial_powerup": 0,
        "gdma_rom": 0,
        "cpu_rom_movsb": 0,
        "cpu_rom_movsb_bytes": 0,
        "cpu_rom_movsb_origins": 0,
    }
    writer = csv.DictWriter(output, fieldnames=OUTPUT_FIELDS, lineterminator="\n")
    writer.writeheader()
    source_tracker = MemorySourceTracker()
    fetch_index = 0

    with trace.open(newline="", encoding="utf-8") as source:
        grouped = itertools.groupby(iter_rows(source), key=lambda row: row.cycle)
        for cycle, rows_iter in grouped:
            rows = list(rows_iter)

            # A same-cycle completed IRAM write occurred on the display read's
            # DPRAM sample edge. Preserve the pre-write scoreboard; the RTL
            # collision bit records whether Intel mixed-port data is uncertain.
            for row in rows:
                values = row.values
                if values["event"] != "vram":
                    continue
                address = int(values["address"])
                if address & 1 or address == 0xFFFF:
                    raise ValueError(f"line {row.line}: invalid display word address")
                fetch_value = int(values["fetch_value"])
                collision = int(values["fetch_collision"])
                low, high = iram[address], iram[address + 1]
                ram_status, writer_summary, source_summary = summarize_versions(low, high)
                reconstructed = (
                    None if low is None or high is None else low.value | (high.value << 8)
                )
                if collision:
                    scoreboard_status = "unspecified_collision"
                    counts["collision"] += 1
                elif reconstructed is None:
                    scoreboard_status = (
                        "unobserved" if low is None and high is None else "partial"
                    )
                    counts[scoreboard_status] += 1
                elif reconstructed == fetch_value:
                    scoreboard_status = "match"
                    counts["match"] += 1
                else:
                    scoreboard_status = "mismatch"
                    counts["mismatch"] += 1

                record: dict[str, object] = {
                    "fetch_index": fetch_index,
                    "cycle": cycle,
                    "role": values["role"],
                    "address": address,
                    "fetch_value": fetch_value,
                    "fetch_collision": collision,
                    "reconstructed_value": "" if reconstructed is None else reconstructed,
                    "scoreboard_status": scoreboard_status,
                    "ram_status": ram_status,
                    "writer_summary": writer_summary,
                    "source_summary": source_summary,
                    "coverage_status": coverage_status,
                }
                record.update(byte_fields("lo", low, address))
                record.update(byte_fields("hi", high, address + 1))
                if writer_summary == "cpu_exact":
                    counts["cpu_exact"] += 1
                if writer_summary == "initial_powerup":
                    counts["initial_powerup"] += 1
                if source_summary == "gdma_rom_same_transfer":
                    counts["gdma_rom"] += 1
                if source_summary == "cpu_rom_movsb":
                    counts["cpu_rom_movsb"] += 1

                selected = (
                    (roles is None or values["role"] in roles)
                    and (
                        address_range is None
                        or address_range[0] <= address <= address_range[1]
                    )
                    and (only_status is None or scoreboard_status in only_status)
                )
                if selected:
                    writer.writerow(record)
                    counts["written"] += 1
                counts["fetches"] += 1
                fetch_index += 1

            for row in rows:
                values = row.values
                if values["event"] != "mem":
                    continue
                access = values["access"]
                source_read = source_tracker.observe(row)
                if access != "write" or values["space"] != "iram":
                    continue
                address = int(values["address"])
                byte_enable = int(values["byte_enable"])
                value = int(values["value"])
                for lane in (0, 1):
                    if not (byte_enable & (1 << lane)):
                        continue
                    target = address + lane
                    if target > 0xFFFF:
                        raise ValueError(f"line {row.line}: IRAM write crosses 0xffff")
                    byte_value = (value >> (8 * lane)) & 0xFF
                    iram[target] = ByteVersion(
                        byte_value, row, source_read, source_lane(source_read, lane)
                    )

    counts["cpu_rom_movsb_bytes"] = source_tracker.cpu_rom_movsb_bytes
    counts["cpu_rom_movsb_origins"] = len(source_tracker.cpu_rom_movsb_origins)

    if require_exact_fetches:
        uncertain = {
            name: counts[name]
            for name in ("mismatch", "collision", "partial", "unobserved")
            if counts[name]
        }
        if uncertain:
            detail = " ".join(f"{name}={count}" for name, count in uncertain.items())
            raise ValueError(f"exact display fetches required, got {detail}")
    if fail_on_mismatch and counts["mismatch"]:
        raise ValueError(f"{counts['mismatch']} display values disagree with the IRAM scoreboard")
    if counts["match"] < require_matches:
        raise ValueError(
            f"required at least {require_matches} matching display values, got {counts['match']}"
        )
    return counts


def role_set(value: str) -> set[str]:
    result = {item.strip().lower() for item in value.split(",") if item.strip()}
    unknown = result - VRAM_ROLES
    if not result or unknown:
        raise argparse.ArgumentTypeError(f"invalid display role list: {value}")
    return result


def status_set(value: str) -> set[str]:
    valid = {"match", "mismatch", "partial", "unobserved", "unspecified_collision"}
    result = {item.strip().lower() for item in value.split(",") if item.strip()}
    if not result or result - valid:
        raise argparse.ArgumentTypeError(f"invalid scoreboard status list: {value}")
    return result


def expected_count(value: str) -> tuple[str, int]:
    try:
        name, count_text = value.split("=", 1)
        count = int(count_text, 0)
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected count must be NAME=COUNT") from error
    valid = {
        "fetches",
        "written",
        "match",
        "mismatch",
        "partial",
        "unobserved",
        "collision",
        "cpu_exact",
        "initial_powerup",
        "gdma_rom",
        "cpu_rom_movsb",
        "cpu_rom_movsb_bytes",
        "cpu_rom_movsb_origins",
    }
    if name not in valid or count < 0:
        raise argparse.ArgumentTypeError(f"invalid expected count: {value}")
    return name, count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--role", type=role_set)
    parser.add_argument(
        "--fetch-address", type=lambda value: parse_range(value, 0xFFFF)
    )
    parser.add_argument("--only-status", type=status_set)
    parser.add_argument("--fail-on-mismatch", action="store_true")
    parser.add_argument(
        "--require-exact-fetches",
        action="store_true",
        help="reject any mismatch, collision, partial, or unobserved display fetch",
    )
    parser.add_argument("--require-matches", type=int, default=0)
    parser.add_argument("--require-complete-coverage", action="store_true")
    parser.add_argument(
        "--expect-count",
        type=expected_count,
        action="append",
        default=[],
        metavar="NAME=COUNT",
    )
    args = parser.parse_args()
    if args.require_matches < 0:
        parser.error("--require-matches must be non-negative")

    try:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", newline="", encoding="utf-8") as output:
            counts = correlate(
                args.trace,
                output,
                roles=args.role,
                address_range=args.fetch_address,
                only_status=args.only_status,
                fail_on_mismatch=args.fail_on_mismatch,
                require_matches=args.require_matches,
                require_complete_coverage=args.require_complete_coverage,
                require_exact_fetches=args.require_exact_fetches,
            )
        for name, expected in args.expect_count:
            if counts[name] != expected:
                raise ValueError(
                    f"expected {name}={expected}, got {counts[name]}"
                )
    except (OSError, ValueError) as error:
        raise SystemExit(f"{args.trace}: {error}") from error
    summary = " ".join(f"{key}={value}" for key, value in counts.items())
    print(f"PASS {args.trace} {summary}")


if __name__ == "__main__":
    main()
