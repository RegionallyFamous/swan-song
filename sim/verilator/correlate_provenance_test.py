#!/usr/bin/env python3
"""Focused byte-lane and certainty tests for correlate_provenance.py."""

from __future__ import annotations

import csv
import io
import json
import tempfile
from pathlib import Path

from correlate_provenance import correlate
from verify_trace import FIELDS_V4


def event(cycle: int, kind: str, **values: object) -> dict[str, object]:
    row: dict[str, object] = {field: "" for field in FIELDS_V4}
    row.update({"cycle": cycle, "event": kind})
    row.update(values)
    return row


def write_trace(path: Path) -> None:
    rows = [
        event(
            1,
            "mem",
            address=0xF0100,
            value=0x1234,
            initiator="gdma",
            access="read",
            byte_enable=3,
            space="cart_rom_linear",
            mapped_offset=0x100,
            origin_status="not_applicable",
        ),
        event(
            2,
            "mem",
            address=0x4000,
            value=0x1234,
            initiator="gdma",
            access="write",
            byte_enable=3,
            space="iram",
            mapped_offset=0x4000,
            origin_status="not_applicable",
        ),
        event(
            3,
            "vram",
            address=0x4000,
            role="screen1_tile",
            fetch_value=0x1234,
            fetch_collision=0,
        ),
        event(
            4,
            "mem",
            address=0x4001,
            value=0x00AA,
            initiator="cpu",
            access="write",
            byte_enable=1,
            space="iram",
            mapped_offset=0x4001,
            instruction_id=9,
            origin_pc=0xF0020,
            origin_status="exact",
        ),
        event(
            5,
            "vram",
            address=0x4000,
            role="screen1_tile",
            fetch_value=0xAA34,
            fetch_collision=0,
        ),
        event(
            6,
            "vram",
            address=0x5000,
            role="screen2_tile",
            fetch_value=0,
            fetch_collision=0,
        ),
        event(
            7,
            "vram",
            address=0x4000,
            role="screen1_tile",
            fetch_value=0xAA34,
            fetch_collision=1,
        ),
        event(
            7,
            "mem",
            address=0x4000,
            value=0x5678,
            initiator="cpu",
            access="write",
            byte_enable=3,
            space="iram",
            mapped_offset=0x4000,
            instruction_id=10,
            origin_pc=0xF0030,
            origin_status="exact",
        ),
    ]
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS_V4, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="swansong-correlator-") as directory:
        trace = Path(directory) / "events.csv"
        write_trace(trace)

        output = io.StringIO()
        counts = correlate(trace, output, fail_on_mismatch=True, require_matches=2)
        rows = list(csv.DictReader(io.StringIO(output.getvalue())))
        assert counts == {
            "fetches": 4,
            "written": 4,
            "match": 2,
            "mismatch": 0,
            "partial": 0,
            "unobserved": 1,
            "collision": 1,
            "cpu_exact": 0,
            "initial_powerup": 0,
            "gdma_rom": 1,
        }
        assert rows[0]["scoreboard_status"] == "match"
        assert rows[0]["source_summary"] == "gdma_rom_same_transfer"
        assert rows[0]["lo_source_offset"] == "256"
        assert rows[0]["hi_source_offset"] == "257"
        assert rows[1]["ram_status"] == "complete_mixed_writes"
        assert rows[1]["hi_origin_pc"] == str(0xF0020)
        assert rows[2]["scoreboard_status"] == "unobserved"
        assert rows[3]["scoreboard_status"] == "unspecified_collision"

        filtered = io.StringIO()
        filtered_counts = correlate(
            trace,
            filtered,
            roles={"screen2_tile"},
            only_status={"unobserved"},
        )
        assert filtered_counts["fetches"] == 4
        assert len(list(csv.DictReader(io.StringIO(filtered.getvalue())))) == 1

        manifest = {
            "schema": "swan-song-trace-manifest-v1",
            "trace_schema": 4,
            "capture_start": "reset_release",
            "capture_completed": True,
            "complete_memory_history": True,
            "complete_display_history": True,
            "savestate_inputs_asserted": False,
            "iram_initial_state": "zero",
        }
        Path(f"{trace}.manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        complete = io.StringIO()
        complete_counts = correlate(
            trace, complete, require_complete_coverage=True, fail_on_mismatch=True
        )
        assert complete_counts["match"] == 3
        complete_rows = list(csv.DictReader(io.StringIO(complete.getvalue())))
        assert complete_rows[2]["writer_summary"] == "initial_powerup"
        assert complete_rows[2]["coverage_status"] == "complete_from_reset"

    print("PASS display provenance correlator")


if __name__ == "__main__":
    main()
