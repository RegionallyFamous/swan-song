#!/usr/bin/env python3
"""Focused byte-lane and certainty tests for correlate_provenance.py."""

from __future__ import annotations

import csv
import io
import json
import tempfile
from pathlib import Path

from correlate_provenance import correlate, trace_fnv1a64
from verify_trace import FIELDS_V4


def event(cycle: int, kind: str, **values: object) -> dict[str, object]:
    row: dict[str, object] = {field: "" for field in FIELDS_V4}
    row.update({"cycle": cycle, "event": kind})
    row.update(values)
    return row


def write_trace(path: Path, fetch_collision: int = 1) -> None:
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
            fetch_collision=fetch_collision,
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

        try:
            correlate(
                trace,
                io.StringIO(),
                roles={"screen2_tile"},
                only_status={"match"},
                require_exact_fetches=True,
            )
        except ValueError as error:
            assert "collision=1" in str(error)
            assert "unobserved=1" in str(error)
        else:
            raise AssertionError("output filters hid globally uncertain fetches")

        manifest = {
            "schema": "swan-song-trace-manifest-v1",
            "trace_schema": 4,
            "trace_size_bytes": trace.stat().st_size,
            "trace_fnv1a64": trace_fnv1a64(trace),
            "capture_start": "reset_release",
            "capture_completed": True,
            "capture_cycles": 7,
            "completed_frames": 1,
            "rom_size": 65536,
            "events": {"cpu": False, "bank": False, "vram": True, "mem": True},
            "memory_filters_active": False,
            "display_filters_active": False,
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

        try:
            correlate(
                trace,
                io.StringIO(),
                roles={"screen2_tile"},
                require_complete_coverage=True,
                require_exact_fetches=True,
            )
        except ValueError as error:
            assert "collision=1" in str(error)
            assert "unobserved" not in str(error)
        else:
            raise AssertionError("complete trace collision passed exact-fetch gate")

        exact_trace = Path(directory) / "exact-events.csv"
        write_trace(exact_trace, fetch_collision=0)
        exact_manifest = dict(manifest)
        exact_manifest["trace_size_bytes"] = exact_trace.stat().st_size
        exact_manifest["trace_fnv1a64"] = trace_fnv1a64(exact_trace)
        Path(f"{exact_trace}.manifest.json").write_text(
            json.dumps(exact_manifest), encoding="utf-8"
        )
        exact_counts = correlate(
            exact_trace,
            io.StringIO(),
            require_complete_coverage=True,
            require_exact_fetches=True,
        )
        assert exact_counts["match"] == 4
        assert exact_counts["collision"] == 0

        with trace.open("a", encoding="utf-8") as output:
            output.write("\n")
        try:
            correlate(trace, io.StringIO(), require_complete_coverage=True)
        except ValueError as error:
            assert "does not prove complete" in str(error)
        else:
            raise AssertionError("modified trace retained complete coverage")

    print("PASS display provenance correlator")


if __name__ == "__main__":
    main()
