#!/usr/bin/env python3
"""Verify exact trace/frame artifact bytes against a v2 manifest."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from frame_manifest import SCHEMA_V2, exact_int, fnv1a64, validate_v2_frame_timeline


def read_manifest(path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid trace manifest {path}: {error}") from error
    if not isinstance(manifest, dict):
        raise ValueError("trace manifest must be an object")
    return manifest


def verify(trace: Path) -> list[int]:
    manifest_path = Path(f"{trace}.manifest.json")
    manifest = read_manifest(manifest_path)
    if manifest.get("schema") != SCHEMA_V2:
        raise ValueError("trace manifest schema is not frame-binding v2")
    try:
        trace_size = trace.stat().st_size
        trace_digest = fnv1a64(trace)
    except OSError as error:
        raise ValueError(f"cannot bind trace {trace}: {error}") from error
    if exact_int(manifest.get("trace_size_bytes"), "trace_size_bytes", 1) != trace_size:
        raise ValueError("trace_size_bytes mismatch")
    if manifest.get("trace_fnv1a64") != trace_digest:
        raise ValueError("trace_fnv1a64 mismatch")
    if manifest.get("trace_file") != str(trace):
        raise ValueError("trace_file mismatch")
    if manifest.get("capture_start") != "reset_release":
        raise ValueError("capture_start mismatch")
    if manifest.get("capture_completed") is not True:
        raise ValueError("trace capture is not complete")
    if manifest.get("savestate_inputs_asserted") is not False:
        raise ValueError("trace capture asserted save-state inputs")
    frames = validate_v2_frame_timeline(manifest, manifest_path, trace)
    return [frame.completion_cycle for frame in frames]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path, help="completed CSV/JSONL trace")
    args = parser.parse_args()
    try:
        completion_cycles = verify(args.trace)
    except (OSError, ValueError) as error:
        raise SystemExit(f"frame manifest: {error}") from error
    print(
        "PASS frame manifest binding "
        f"frames={len(completion_cycles)} cycles="
        + ",".join(str(cycle) for cycle in completion_cycles)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
