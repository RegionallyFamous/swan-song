#!/usr/bin/env python3
"""Verify that a completed structured trace is bound to one input script."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from frame_manifest import accepts_complete_schema


BUTTONS = {
    b"x1": 1 << 0,
    b"x2": 1 << 1,
    b"x3": 1 << 2,
    b"x4": 1 << 3,
    b"y1": 1 << 4,
    b"y2": 1 << 5,
    b"y3": 1 << 6,
    b"y4": 1 << 7,
    b"start": 1 << 8,
    b"a": 1 << 9,
    b"b": 1 << 10,
}
MAX_SOURCE_SIZE_BYTES = 4 * 1024 * 1024
MAX_EVENTS = 65_536
INPUT_FIELDS = {
    "schema",
    "source_size_bytes",
    "source_fnv1a64",
    "normalized_fnv1a64",
    "event_count",
    "applied_events",
    "completed",
    "final_state",
}


def fnv1a64(data: bytes) -> str:
    value = 0xCBF29CE484222325
    for byte in data:
        value ^= byte
        value = (value * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return f"{value:016x}"


@dataclass(frozen=True)
class ScriptIdentity:
    source_size_bytes: int
    source_fnv1a64: str
    normalized_fnv1a64: str
    event_count: int
    final_cycle: int


def parse_script(source: bytes, source_name: str = "input script") -> ScriptIdentity:
    if len(source) > MAX_SOURCE_SIZE_BYTES:
        raise ValueError(
            f"{source_name}: input script exceeds "
            f"{MAX_SOURCE_SIZE_BYTES}-byte limit"
        )
    events: list[tuple[int, int]] = []
    normalized = bytearray()
    asserted = False

    for line_number, raw_line in enumerate(source.split(b"\n"), start=1):
        line = raw_line.split(b"#", 1)[0].strip()
        if not line:
            continue
        fields = line.split()
        context = f"{source_name}:{line_number}"
        if len(fields) != 2:
            raise ValueError(f"{context}: expected SYSTEM_CYCLE STATE")
        cycle_text, state_text = fields
        if not cycle_text or any(not 0x30 <= byte <= 0x39 for byte in cycle_text):
            raise ValueError(f"{context}: invalid system cycle")
        cycle = int(cycle_text, 10)
        if cycle > 0xFFFFFFFFFFFFFFFF:
            raise ValueError(f"{context}: invalid system cycle")
        if events and cycle <= events[-1][0]:
            raise ValueError(f"{context}: event cycles must be strictly increasing")

        if state_text == b"none":
            buttons = 0
        else:
            if not state_text or state_text.endswith(b","):
                raise ValueError(f"{context}: button state must not be empty")
            buttons = 0
            for name in state_text.split(b","):
                if not name:
                    raise ValueError(f"{context}: empty button name")
                if name not in BUTTONS:
                    rendered = name.decode("ascii", errors="backslashreplace")
                    raise ValueError(f"{context}: unknown button: {rendered}")
                bit = BUTTONS[name]
                if buttons & bit:
                    rendered = name.decode("ascii")
                    raise ValueError(f"{context}: duplicate button: {rendered}")
                buttons |= bit
        if len(events) >= MAX_EVENTS:
            raise ValueError(
                f"{context}: input script exceeds {MAX_EVENTS}-event limit"
            )
        asserted |= buttons != 0
        events.append((cycle, buttons))
        normalized.extend(f"{cycle} {buttons:04x}\n".encode("ascii"))

    if not events:
        raise ValueError(f"{source_name}: input script has no events")
    if not asserted:
        raise ValueError(f"{source_name}: input script never presses a button")
    if events[-1][1] != 0:
        raise ValueError(
            f"{source_name}: final event must release all buttons with none"
        )
    return ScriptIdentity(
        source_size_bytes=len(source),
        source_fnv1a64=fnv1a64(source),
        normalized_fnv1a64=fnv1a64(bytes(normalized)),
        event_count=len(events),
        final_cycle=events[-1][0],
    )


def require_exact_int(value: Any, description: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{description} must be an integer >= {minimum}")
    return value


def read_manifest(trace: Path) -> dict[str, Any]:
    path = Path(f"{trace}.manifest.json")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid trace manifest {path}: {error}") from error
    if not isinstance(manifest, dict):
        raise ValueError(f"trace manifest {path} is not an object")
    return manifest


def read_bounded_script(path: Path) -> bytes:
    with path.open("rb") as source:
        return source.read(MAX_SOURCE_SIZE_BYTES + 1)


def verify_binding(trace: Path, script_path: Path) -> ScriptIdentity:
    trace_bytes = trace.read_bytes()
    script_bytes = read_bounded_script(script_path)
    identity = parse_script(script_bytes, str(script_path))
    manifest = read_manifest(trace)

    if not accepts_complete_schema(manifest, Path(f"{trace}.manifest.json"), trace):
        raise ValueError("trace manifest schema mismatch")
    if manifest.get("capture_start") != "reset_release":
        raise ValueError("input replay requires capture_start=reset_release")
    if manifest.get("capture_completed") is not True:
        raise ValueError("input replay trace is not complete")
    if manifest.get("savestate_inputs_asserted") is not False:
        raise ValueError("input replay trace asserted save-state inputs")
    capture_cycles = require_exact_int(
        manifest.get("capture_cycles"), "capture_cycles", 1
    )
    if capture_cycles <= identity.final_cycle:
        raise ValueError("trace ended before the input script's final release")
    require_exact_int(manifest.get("completed_frames"), "completed_frames", 1)
    if manifest.get("trace_size_bytes") != len(trace_bytes):
        raise ValueError("trace_size_bytes mismatch")
    if manifest.get("trace_fnv1a64") != fnv1a64(trace_bytes):
        raise ValueError("trace_fnv1a64 mismatch")
    if manifest.get("trace_file") != str(trace):
        raise ValueError("trace_file mismatch")

    binding = manifest.get("input_script")
    if not isinstance(binding, dict):
        raise ValueError("trace manifest has no input_script object")
    if set(binding) != INPUT_FIELDS:
        raise ValueError("input_script manifest field set mismatch")
    expected = {
        "schema": "swan-song-input-script-v1",
        "source_size_bytes": identity.source_size_bytes,
        "source_fnv1a64": identity.source_fnv1a64,
        "normalized_fnv1a64": identity.normalized_fnv1a64,
        "event_count": identity.event_count,
        "applied_events": identity.event_count,
        "completed": True,
        "final_state": "released",
    }
    for field in ("source_size_bytes", "event_count", "applied_events"):
        require_exact_int(binding.get(field), f"input_script.{field}")
    if binding != expected:
        raise ValueError(
            f"input_script manifest mismatch: {binding!r} != {expected!r}"
        )
    return identity


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path, help="completed CSV/JSONL trace")
    parser.add_argument("input_script", type=Path, help="exact replay source")
    args = parser.parse_args()
    try:
        identity = verify_binding(args.trace, args.input_script)
    except (OSError, ValueError) as error:
        raise SystemExit(f"input-script manifest: {error}") from error
    print(
        "PASS input-script manifest binding "
        f"events={identity.event_count} final_cycle={identity.final_cycle}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
