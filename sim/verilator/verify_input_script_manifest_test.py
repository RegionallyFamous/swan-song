#!/usr/bin/env python3
"""Focused mutation tests for generic input-script manifest verification."""

from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

from verify_input_script_manifest import (
    MAX_EVENTS,
    MAX_SOURCE_SIZE_BYTES,
    fnv1a64,
    parse_script,
    verify_binding,
)


SCRIPT = b"# route\n0 start,a\n12000 none\n500000 x2,y3,b\n500001 none\n"


def must_fail(function, expected: str) -> None:
    try:
        function()
    except ValueError as error:
        if expected not in str(error):
            raise AssertionError(f"expected {expected!r} in {error!r}") from error
    else:
        raise AssertionError(f"invalid binding passed; expected {expected!r}")


def main() -> None:
    identity = parse_script(SCRIPT, "route.input")
    assert identity.event_count == 4
    assert identity.final_cycle == 500001
    assert identity.normalized_fnv1a64 == fnv1a64(
        b"0 0300\n12000 0000\n500000 0442\n500001 0000\n"
    )

    with tempfile.TemporaryDirectory(prefix="swansong-input-binding-") as directory:
        root = Path(directory)
        trace = root / "events.csv"
        script = root / "route.input"
        trace.write_bytes(b"cycle,event\n")
        script.write_bytes(SCRIPT)
        manifest_path = Path(f"{trace}.manifest.json")
        manifest = {
            "schema": "swan-song-trace-manifest-v1",
            "trace_file": str(trace),
            "trace_size_bytes": trace.stat().st_size,
            "trace_fnv1a64": fnv1a64(trace.read_bytes()),
            "capture_start": "reset_release",
            "capture_completed": True,
            "capture_cycles": 600000,
            "completed_frames": 1,
            "savestate_inputs_asserted": False,
            "input_script": {
                "schema": "swan-song-input-script-v1",
                "source_size_bytes": identity.source_size_bytes,
                "source_fnv1a64": identity.source_fnv1a64,
                "normalized_fnv1a64": identity.normalized_fnv1a64,
                "event_count": identity.event_count,
                "applied_events": identity.event_count,
                "completed": True,
                "final_state": "released",
            },
        }

        def write(value: dict[str, object]) -> None:
            manifest_path.write_text(json.dumps(value), encoding="utf-8")

        write(manifest)
        assert verify_binding(trace, script) == identity

        mutated_script = root / "mutated.input"
        mutated_script.write_bytes(SCRIPT + b"# same semantics, different source\n")
        must_fail(
            lambda: verify_binding(trace, mutated_script),
            "input_script manifest mismatch",
        )

        oversized_script = root / "oversized.input"
        oversized_script.write_bytes(b" " * (MAX_SOURCE_SIZE_BYTES + 1))
        must_fail(
            lambda: verify_binding(trace, oversized_script),
            f"exceeds {MAX_SOURCE_SIZE_BYTES}-byte limit",
        )

        for field, value in (
            ("schema", "wrong"),
            ("source_size_bytes", identity.source_size_bytes + 1),
            ("source_fnv1a64", "0" * 16),
            ("normalized_fnv1a64", "0" * 16),
            ("event_count", identity.event_count + 1),
            ("applied_events", identity.event_count - 1),
            ("completed", False),
            ("final_state", "held"),
        ):
            wrong = copy.deepcopy(manifest)
            wrong["input_script"][field] = value  # type: ignore[index]
            write(wrong)
            must_fail(lambda: verify_binding(trace, script), "input_script")

        wrong = copy.deepcopy(manifest)
        wrong["input_script"]["extra"] = True  # type: ignore[index]
        write(wrong)
        must_fail(lambda: verify_binding(trace, script), "field set")

        for field, value, expected in (
            ("capture_start", "late", "capture_start"),
            ("capture_completed", False, "not complete"),
            ("capture_cycles", identity.final_cycle, "final release"),
            ("savestate_inputs_asserted", True, "save-state"),
            ("trace_fnv1a64", "0" * 16, "trace_fnv1a64"),
        ):
            wrong = copy.deepcopy(manifest)
            wrong[field] = value
            write(wrong)
            must_fail(lambda: verify_binding(trace, script), expected)

        write(manifest)
        trace.write_bytes(trace.read_bytes() + b"mutation\n")
        must_fail(lambda: verify_binding(trace, script), "trace_size_bytes")

    for invalid, expected in (
        (b"", "no events"),
        (b"0 none\n", "never presses"),
        (b"0 x2\n", "final event"),
        (b"0 X2\n1 none\n", "unknown button"),
        (b"0 x2\n0 none\n", "strictly increasing"),
        (b"18446744073709551616 x2\n18446744073709551617 none\n", "invalid system cycle"),
    ):
        must_fail(lambda invalid=invalid: parse_script(invalid), expected)

    must_fail(
        lambda: parse_script(b" " * (MAX_SOURCE_SIZE_BYTES + 1)),
        f"exceeds {MAX_SOURCE_SIZE_BYTES}-byte limit",
    )
    too_many_events = b"".join(
        f"{cycle} x1\n".encode("ascii") for cycle in range(MAX_EVENTS + 1)
    )
    must_fail(
        lambda: parse_script(too_many_events),
        f"exceeds {MAX_EVENTS}-event limit",
    )

    print("PASS generic input-script parser, manifest binding, and mutations")


if __name__ == "__main__":
    main()
