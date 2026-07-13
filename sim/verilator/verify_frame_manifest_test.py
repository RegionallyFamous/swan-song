#!/usr/bin/env python3
"""Adversarial tests for manifest-v2 trace/frame artifact binding."""

from __future__ import annotations

import copy
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

from correlate_bg_cells import read_manifest as read_bg_manifest
from correlate_provenance import read_manifest as read_provenance_manifest
from correlate_sprite_rows import read_manifest as read_sprite_manifest
from frame_manifest import (
    FRAME_SIZE_BYTES,
    SCHEMA_V1,
    SCHEMA_V2,
    accepts_complete_schema,
    fnv1a64,
)
from verify_frame_manifest import verify


def write_manifest(trace: Path, manifest: object) -> None:
    Path(f"{trace}.manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )


def make_manifest(trace: Path, frame_paths: list[Path]) -> dict[str, Any]:
    completion_cycles = [9, 20]
    return {
        "schema": SCHEMA_V2,
        "trace_schema": 5,
        "trace_file": str(trace),
        "trace_size_bytes": trace.stat().st_size,
        "trace_fnv1a64": fnv1a64(trace),
        "capture_start": "reset_release",
        "capture_completed": True,
        "capture_cycles": completion_cycles[-1] + 1,
        "completed_frames": len(frame_paths),
        "frames": [
            {
                "index": index,
                "completion_cycle": completion_cycles[index],
                "file": str(path.relative_to(trace.parent)),
                "size_bytes": path.stat().st_size,
                "fnv1a64": fnv1a64(path),
            }
            for index, path in enumerate(frame_paths)
        ],
        "rom_size": 65536,
        "rom_fnv1a64": "0123456789abcdef",
        "bios_size": 4096,
        "bios_fnv1a64": "fedcba9876543210",
        "iram_initial_state": "zero",
        "savestate_inputs_asserted": False,
        "events": {
            "cpu": False,
            "bank": False,
            "vram": True,
            "mem": True,
            "bg_cell": True,
        },
        "memory_filters_active": False,
        "display_filters_active": False,
        "complete_memory_history": True,
        "complete_display_history": True,
        "complete_bg_cell_history": True,
    }


def must_fail(
    trace: Path, manifest: object, expected: str, prepare: Callable[[], None] | None = None
) -> None:
    if prepare:
        prepare()
    write_manifest(trace, manifest)
    try:
        verify(trace)
    except ValueError as error:
        if expected not in str(error):
            raise AssertionError(f"expected {expected!r}, got {error!r}") from error
    else:
        raise AssertionError(f"invalid frame manifest passed: expected {expected!r}")


def changed(manifest: dict[str, Any], update: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    result = copy.deepcopy(manifest)
    update(result)
    return result


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="swansong-frame-manifest-test-") as root_text:
        root = Path(root_text)
        trace = root / "events.csv"
        trace.write_bytes(b"cycle,event\n0,cpu\n")
        frames_dir = root / "frames"
        frames_dir.mkdir()
        frame_paths = [frames_dir / "frame-0.rgb", frames_dir / "frame-1.rgb"]
        frame_paths[0].write_bytes(bytes([0x12]) * FRAME_SIZE_BYTES)
        frame_paths[1].write_bytes(bytes([0x34]) * FRAME_SIZE_BYTES)
        valid = make_manifest(trace, frame_paths)
        write_manifest(trace, valid)
        assert verify(trace) == [9, 20]
        assert accepts_complete_schema(valid, Path(f"{trace}.manifest.json"))
        legacy = copy.deepcopy(valid)
        legacy["schema"] = SCHEMA_V1
        legacy.pop("frames")
        assert accepts_complete_schema(legacy, Path(f"{trace}.manifest.json"))

        assert read_provenance_manifest(trace)[0] == "complete_from_reset"
        assert read_bg_manifest(trace)[0] == "complete_from_reset"
        sprite = copy.deepcopy(valid)
        sprite["trace_schema"] = 6
        sprite["events"]["sprite_row"] = True
        sprite["complete_sprite_row_history"] = True
        write_manifest(trace, sprite)
        assert read_sprite_manifest(trace)[0] == "complete_from_reset"

        cases: list[tuple[dict[str, Any], str]] = [
            (changed(valid, lambda value: value.__setitem__("schema", SCHEMA_V1)), "schema"),
            (changed(valid, lambda value: value.__setitem__("trace_schema", True)), "integer"),
            (changed(valid, lambda value: value.__setitem__("trace_schema", 7)), "5 or 6"),
            (changed(valid, lambda value: value.__setitem__("unexpected", 1)), "field set"),
            (changed(valid, lambda value: value["events"].__setitem__("extra", False)), "event field"),
            (changed(valid, lambda value: value["events"].__setitem__("cpu", 0)), "booleans"),
            (changed(valid, lambda value: value.pop("frames")), "field set"),
            (changed(valid, lambda value: value.__setitem__("frames", {})), "frames must"),
            (changed(valid, lambda value: value.__setitem__("completed_frames", 1)), "length"),
            (changed(valid, lambda value: value["frames"][0].__setitem__("extra", 1)), "field set"),
            (changed(valid, lambda value: value["frames"][0].pop("fnv1a64")), "field set"),
            (changed(valid, lambda value: value["frames"][0].__setitem__("index", True)), "integer"),
            (changed(valid, lambda value: value["frames"][1].__setitem__("index", 0)), "contiguous"),
            (changed(valid, lambda value: value["frames"][0].__setitem__("completion_cycle", True)), "integer"),
            (changed(valid, lambda value: value["frames"][1].__setitem__("completion_cycle", 9)), "strictly"),
            (changed(valid, lambda value: value["frames"][1].__setitem__("completion_cycle", 21)), "outside"),
            (changed(valid, lambda value: value.__setitem__("capture_cycles", 22)), "does not end"),
            (changed(valid, lambda value: value["frames"][0].__setitem__("file", "")), "nonempty"),
            (changed(valid, lambda value: value["frames"][0].__setitem__("file", str(frame_paths[0]))), "relative"),
            (changed(valid, lambda value: value["frames"][0].__setitem__("file", "frames/frame-7.rgb")), "index"),
            (changed(valid, lambda value: value["frames"][1].__setitem__("file", "frames/frame-0.rgb")), "index"),
            (changed(valid, lambda value: value["frames"][0].__setitem__("size_bytes", True)), "integer"),
            (changed(valid, lambda value: value["frames"][0].__setitem__("size_bytes", FRAME_SIZE_BYTES - 1)), "RGB888"),
            (changed(valid, lambda value: value["frames"][0].__setitem__("fnv1a64", "A" * 16)), "lowercase"),
            (changed(valid, lambda value: value["frames"][0].__setitem__("fnv1a64", "0" * 16)), "mismatch"),
            (changed(valid, lambda value: value.__setitem__("trace_size_bytes", 1)), "trace_size_bytes"),
            (changed(valid, lambda value: value.__setitem__("trace_fnv1a64", "0" * 16)), "trace_fnv1a64"),
        ]
        for manifest, expected in cases:
            must_fail(trace, manifest, expected)

        original_frame = frame_paths[0].read_bytes()
        original_frame1 = frame_paths[1].read_bytes()
        frame_paths[1].unlink()
        os.link(frame_paths[0], frame_paths[1])
        hardlink = copy.deepcopy(valid)
        hardlink["frames"][1]["fnv1a64"] = hardlink["frames"][0]["fnv1a64"]
        must_fail(trace, hardlink, "distinct files")
        frame_paths[1].unlink()
        frame_paths[1].write_bytes(original_frame1)

        frame_paths[0].unlink()
        frame_paths[0].symlink_to(frame_paths[1].name)
        symlink = copy.deepcopy(valid)
        symlink["frames"][0]["fnv1a64"] = symlink["frames"][1]["fnv1a64"]
        must_fail(trace, symlink, "regular non-symlink")
        frame_paths[0].unlink()
        frame_paths[0].write_bytes(original_frame)

        original_trace = trace.read_bytes()
        trace.write_bytes(original_frame)
        frame_paths[0].unlink()
        os.link(trace, frame_paths[0])
        trace_alias = make_manifest(trace, frame_paths)
        must_fail(trace, trace_alias, "distinct files")
        frame_paths[0].unlink()
        frame_paths[0].write_bytes(original_frame)
        trace.write_bytes(original_trace)

        frame_paths[0].write_bytes(bytes([0x56]) + original_frame[1:])
        must_fail(trace, valid, "fnv1a64 mismatch")
        frame_paths[0].write_bytes(original_frame)
        frame_paths[0].unlink()
        must_fail(trace, valid, "cannot stat")
        frame_paths[0].write_bytes(original_frame)

        trace.write_bytes(original_trace + b"x")
        must_fail(trace, valid, "trace_size_bytes mismatch")
        trace.write_bytes(bytes([original_trace[0] ^ 1]) + original_trace[1:])
        must_fail(trace, valid, "trace_fnv1a64 mismatch")
        trace.write_bytes(original_trace)

    print("PASS frame manifest v1 compatibility and adversarial v2 binding")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
