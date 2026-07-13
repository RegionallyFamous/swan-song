#!/usr/bin/env python3
"""Strict helpers for manifest-v2 raw-frame artifact bindings."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import stat
from typing import Any


SCHEMA_V1 = "swan-song-trace-manifest-v1"
SCHEMA_V2 = "swan-song-trace-manifest-v2"
FRAME_WIDTH = 224
FRAME_HEIGHT = 144
FRAME_SIZE_BYTES = FRAME_WIDTH * FRAME_HEIGHT * 3
FRAME_FIELDS = {"index", "completion_cycle", "file", "size_bytes", "fnv1a64"}
BASE_FIELDS = {
    "schema",
    "trace_schema",
    "trace_file",
    "trace_size_bytes",
    "trace_fnv1a64",
    "capture_start",
    "capture_completed",
    "capture_cycles",
    "completed_frames",
    "rom_size",
    "rom_fnv1a64",
    "bios_size",
    "bios_fnv1a64",
    "iram_initial_state",
    "savestate_inputs_asserted",
    "events",
    "memory_filters_active",
    "display_filters_active",
    "complete_memory_history",
    "complete_display_history",
    "complete_bg_cell_history",
}


@dataclass(frozen=True)
class FrameBinding:
    index: int
    completion_cycle: int
    file: Path
    size_bytes: int
    fnv1a64: str


def fnv1a64(path: Path) -> str:
    value = 0xCBF29CE484222325
    with path.open("rb") as source:
        while chunk := source.read(16384):
            for byte in chunk:
                value ^= byte
                value = (value * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return f"{value:016x}"


def exact_int(value: object, field: str, minimum: int = 0) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ValueError(f"{field} must be an integer >= {minimum}")
    return value


def validate_v2_frame_timeline(
    manifest: dict[str, Any], manifest_path: Path, trace_path: Path | None = None
) -> list[FrameBinding]:
    """Validate and return every manifest-v2 raw RGB binding.

    Frame file names are POSIX-style paths relative to the manifest directory.
    The simulator stops immediately after the final visible pixel write, so the
    final completion cycle is exactly one less than capture_cycles.
    """

    if manifest.get("schema") != SCHEMA_V2:
        raise ValueError("trace manifest does not use frame-binding schema v2")

    trace_schema = exact_int(manifest.get("trace_schema"), "trace_schema", 5)
    if trace_schema not in {5, 6}:
        raise ValueError("trace_schema must be 5 or 6 for manifest v2")

    expected_fields = {*BASE_FIELDS, "frames"}
    if "input_script" in manifest:
        expected_fields.add("input_script")
    if trace_schema == 6:
        expected_fields.add("complete_sprite_row_history")
    if set(manifest) != expected_fields:
        raise ValueError("trace manifest v2 field set mismatch")

    event_fields = {"cpu", "bank", "vram", "mem", "bg_cell"}
    if trace_schema == 6:
        event_fields.add("sprite_row")
    events = manifest.get("events")
    if not isinstance(events, dict) or set(events) != event_fields:
        raise ValueError("trace manifest v2 event field set mismatch")
    if any(not isinstance(value, bool) for value in events.values()):
        raise ValueError("trace manifest v2 event values must be booleans")
    if trace_schema == 6 and events["sprite_row"] is not True:
        raise ValueError("trace schema v6 must include sprite_row")

    capture_cycles = exact_int(manifest.get("capture_cycles"), "capture_cycles", 1)
    completed_frames = exact_int(
        manifest.get("completed_frames"), "completed_frames", 1
    )
    frames = manifest.get("frames")
    if not isinstance(frames, list):
        raise ValueError("frames must be an array")
    if len(frames) != completed_frames:
        raise ValueError("frames length does not match completed_frames")

    result: list[FrameBinding] = []
    previous_cycle = -1
    seen_files: set[str] = set()
    seen_identities: set[tuple[int, int]] = set()
    if trace_path is not None:
        try:
            trace_lstat = trace_path.lstat()
            trace_stat = trace_path.stat()
        except OSError as error:
            raise ValueError(f"cannot stat frame-bound trace {trace_path}: {error}") from error
        if stat.S_ISLNK(trace_lstat.st_mode) or not stat.S_ISREG(trace_stat.st_mode):
            raise ValueError("frame-bound trace must be a regular non-symlink file")
        seen_identities.add((trace_stat.st_dev, trace_stat.st_ino))
    for position, item in enumerate(frames):
        prefix = f"frames[{position}]"
        if not isinstance(item, dict) or set(item) != FRAME_FIELDS:
            raise ValueError(f"{prefix} field set mismatch")
        index = exact_int(item.get("index"), f"{prefix}.index")
        if index != position:
            raise ValueError(f"{prefix}.index is not contiguous")
        completion_cycle = exact_int(
            item.get("completion_cycle"), f"{prefix}.completion_cycle"
        )
        if completion_cycle <= previous_cycle:
            raise ValueError("frame completion cycles are not strictly increasing")
        if completion_cycle >= capture_cycles:
            raise ValueError(f"{prefix}.completion_cycle is outside capture")
        previous_cycle = completion_cycle

        file_value = item.get("file")
        if not isinstance(file_value, str) or not file_value:
            raise ValueError(f"{prefix}.file must be a nonempty string")
        relative_file = Path(file_value)
        if relative_file.is_absolute():
            raise ValueError(f"{prefix}.file must be relative to the manifest")
        if relative_file.name != f"frame-{index}.rgb":
            raise ValueError(f"{prefix}.file does not match its frame index")
        if file_value in seen_files:
            raise ValueError("frame artifact paths are not unique")
        seen_files.add(file_value)
        artifact = manifest_path.parent / relative_file

        try:
            artifact_lstat = artifact.lstat()
            artifact_stat = artifact.stat()
        except OSError as error:
            raise ValueError(f"cannot stat {prefix}.file {artifact}: {error}") from error
        if stat.S_ISLNK(artifact_lstat.st_mode) or not stat.S_ISREG(
            artifact_stat.st_mode
        ):
            raise ValueError(f"{prefix}.file must be a regular non-symlink file")
        identity = (artifact_stat.st_dev, artifact_stat.st_ino)
        if identity in seen_identities:
            raise ValueError("trace and frame artifacts must be distinct files")
        seen_identities.add(identity)

        size_bytes = exact_int(item.get("size_bytes"), f"{prefix}.size_bytes", 1)
        if size_bytes != FRAME_SIZE_BYTES:
            raise ValueError(f"{prefix}.size_bytes is not raw RGB888 frame size")
        actual_size = artifact_stat.st_size
        if actual_size != size_bytes:
            raise ValueError(f"{prefix}.size_bytes mismatch")

        digest = item.get("fnv1a64")
        if (
            not isinstance(digest, str)
            or len(digest) != 16
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError(f"{prefix}.fnv1a64 must be 16 lowercase hex digits")
        try:
            actual_digest = fnv1a64(artifact)
        except OSError as error:
            raise ValueError(f"cannot hash {prefix}.file {artifact}: {error}") from error
        if actual_digest != digest:
            raise ValueError(f"{prefix}.fnv1a64 mismatch")
        result.append(
            FrameBinding(index, completion_cycle, artifact, size_bytes, digest)
        )

    if result[-1].completion_cycle + 1 != capture_cycles:
        raise ValueError("final frame completion does not end the capture")
    return result


def accepts_complete_schema(
    manifest: dict[str, Any], manifest_path: Path, trace_path: Path | None = None
) -> bool:
    """Accept legacy v1, or validate every artifact before accepting v2."""

    if manifest.get("schema") == SCHEMA_V1:
        return True
    if manifest.get("schema") == SCHEMA_V2:
        validate_v2_frame_timeline(manifest, manifest_path, trace_path)
        return True
    return False
