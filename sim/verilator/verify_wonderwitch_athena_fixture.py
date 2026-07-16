#!/usr/bin/env python3
"""Verify the open AthenaOS WonderWitch build and translated-core boot."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from verify_trace import FIELDS_V5


FX_SIZE = 480
FX_SHA256 = "d513b42f8e72bb9a45db2b800adb0411268fe8038fef58bea935c6ee54dff361"
ROM_SIZE = 256 * 1024
ROM_SHA256 = "bb190b7cbbd0a8485b689159bcc5196c252ef0da88412453d4059dda0add83ae"
ROM_FNV1A64 = "443ce2a6a57314d0"
BIOS_SHA256 = "ec5f7fda0539137f3ace5c4a672d0abc81823bee966419c82c1d3dc96f611970"
OS_SHA256 = "7a751ca5398a232a1e900044b95d3fab9a6c44d02f54baa37c769e7cd87cd7a2"
OS_SIZE = 6162
FRAME_SHA256 = (
    "b404fb94d84fa4bd527d8eabaf2d13393f5c43f03d838c4aa2a8c95855aef511",
    "b404fb94d84fa4bd527d8eabaf2d13393f5c43f03d838c4aa2a8c95855aef511",
    "b404fb94d84fa4bd527d8eabaf2d13393f5c43f03d838c4aa2a8c95855aef511",
    "d4e4995f9df957734f3ccad96ee1fa5c1dd1570a443692a0590c479ec76e9814",
    "d4e4995f9df957734f3ccad96ee1fa5c1dd1570a443692a0590c479ec76e9814",
)
FILE_SHA256 = {
    "Makefile": "6d5d482bfee6f40a79e0f5df2f83613b08b6928e00aa1e91610fa344832d77d7",
    "src/main.c": "a59238dc3e05ed3940a77c67e6f8f1584f7d2e55530f37f3d4f6da2bde67b775",
    "normalize_fent.py": "fedab3d2063a632d6bd79dc2158d273bc048c911a6a23cd9596aa06bd7b22f34",
    "LICENSE.athenaos": "ca8e7651ea64ddbdd7f12ec9ac19e369323320609638fc391fae714420199868",
}
PACKAGE_VERSIONS = {
    "target-wswan": "0.1.0-3",
    "target-wswan-syslibs": "0.2.0.r254.d7d97ce-1",
    "target-wswan-athenaos": "0.2.0.r173.d37beae-1",
    "toolchain-gcc-ia16-elf-binutils": "2.43.1.r119451.5cc0e071551-1",
    "toolchain-gcc-ia16-elf-gcc": "6.3.0.r147159.e7507d1845e-1",
    "toolchain-gcc-ia16-elf-gcc-libs": "6.3.0.r147159.e7507d1845e-1",
    "wf-tools": "0.2.0-3",
    "wf-tools-lua": "0.1.0.r181.7f5f3f9-1",
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_source(directory: Path) -> None:
    for relative, wanted in FILE_SHA256.items():
        actual = sha256((directory / relative).read_bytes())
        if actual != wanted:
            raise ValueError(f"fixture source {relative} sha256 {actual} != {wanted}")


def verify_toolchain(toolchain: Path) -> None:
    pacman = toolchain / "bin/wf-pacman"
    import subprocess

    for package, version in PACKAGE_VERSIONS.items():
        completed = subprocess.run(
            (str(pacman), "-Q", package),
            check=True,
            capture_output=True,
            text=True,
        )
        actual = completed.stdout.strip()
        wanted = f"{package} {version}"
        if actual != wanted:
            raise ValueError(f"Wonderful package {actual!r} != {wanted!r}")

    firmware = toolchain / "target/wwitch/fbin"
    binaries = (
        ("athenabios.smallrom.raw", 65536, BIOS_SHA256),
        ("athenaos.smallrom.raw", OS_SIZE, OS_SHA256),
    )
    for name, size, wanted in binaries:
        data = (firmware / name).read_bytes()
        if len(data) != size or sha256(data) != wanted:
            raise ValueError(f"installed {name} size/hash mismatch")


def unique_offset(data: bytes, value: bytes) -> int:
    offsets = [index for index in range(len(data)) if data.startswith(value, index)]
    if len(offsets) != 1:
        raise ValueError(f"expected one {value!r}, got offsets {offsets}")
    return offsets[0]


def verify_artifacts(fx_path: Path, rom_path: Path) -> None:
    fx = fx_path.read_bytes()
    if len(fx) != FX_SIZE or sha256(fx) != FX_SHA256:
        raise ValueError(f"unexpected .fx size/hash: {len(fx)} {sha256(fx)}")
    if fx[:4] != b"#!ws" or fx[116:120] != bytes.fromhex("00607e33"):
        raise ValueError(".fx header or deterministic mtime is invalid")
    if unique_offset(fx, b"Hello, World!") != 0x1D0:
        raise ValueError(".fx payload message moved")

    rom = rom_path.read_bytes()
    if len(rom) != ROM_SIZE or sha256(rom) != ROM_SHA256:
        raise ValueError(f"unexpected .ws size/hash: {len(rom)} {sha256(rom)}")
    if sha256(rom[-65536:]) != BIOS_SHA256:
        raise ValueError("composite ROM does not end in pinned AthenaBIOS")
    if sha256(rom[0x20000 : 0x20000 + OS_SIZE]) != OS_SHA256:
        raise ValueError("composite ROM does not contain pinned AthenaOS")
    if rom[0x2FFE0 : 0x2FFE6] != bytes.fromhex("a55a0100e4df"):
        raise ValueError("AthenaOS filesystem footer is invalid")
    if rom[0x2FFF0 : 0x2FFF6] != bytes.fromhex("ea000000e000"):
        raise ValueError("AthenaOS generic OS header is invalid")
    if unique_offset(rom, b"athena_hello") != 0x1FE40:
        raise ValueError("ROM filesystem executable header moved")
    if unique_offset(rom, b"Hello, World!") != 0x1FFD0:
        raise ValueError("ROM filesystem executable payload moved")


def integer(row: dict[str, str], field: str) -> int:
    try:
        return int(row[field], 10)
    except ValueError as error:
        raise ValueError(f"invalid {field}: {row[field]!r}") from error


def verify_manifest(trace: Path) -> None:
    manifest = json.loads(Path(f"{trace}.manifest.json").read_text(encoding="utf-8"))
    expected = {
        "schema": "swan-song-trace-manifest-v1",
        "trace_schema": 5,
        "capture_start": "reset_release",
        "capture_completed": True,
        "completed_frames": 5,
        "rom_size": ROM_SIZE,
        "rom_fnv1a64": ROM_FNV1A64,
        "open_ipl_size": 8192,
        "open_ipl_fnv1a64": "de968891eff736c1",
        "iram_initial_state": "zero",
        "savestate_inputs_asserted": False,
        "events": {
            "cpu": True,
            "bank": False,
            "vram": False,
            "mem": False,
            "bg_cell": True,
        },
        "memory_filters_active": False,
        "display_filters_active": False,
        "complete_memory_history": False,
        "complete_display_history": False,
        "complete_bg_cell_history": True,
    }
    for field, wanted in expected.items():
        if manifest.get(field) != wanted:
            raise ValueError(f"manifest {field}: {manifest.get(field)!r} != {wanted!r}")
    if manifest.get("trace_size_bytes") != trace.stat().st_size:
        raise ValueError("manifest trace size mismatch")


def verify_runtime(trace: Path, frames: tuple[Path, ...]) -> None:
    verify_manifest(trace)
    with trace.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != FIELDS_V5:
            raise ValueError("WonderWitch fixture requires exact v5 trace fields")
        rows = list(reader)
    counts = Counter(row["event"] for row in rows)
    if counts != Counter(cpu=158, bg_cell=33602):
        raise ValueError(f"unexpected trace event counts: {counts}")

    pcs = [integer(row, "physical_pc") for row in rows if row["event"] == "cpu"]
    required = (0xDFE80, 0xDFE9A, 0xDFEA3, 0xDFF0D, 0xDFF2E, 0xDFF38, 0xDFF4F, 0xDFF42, 0xDFF44)
    cursor = -1
    for pc in required:
        try:
            cursor = pcs.index(pc, cursor + 1)
        except ValueError as error:
            raise ValueError(f"CPU did not reach ordered WonderWitch PC {pc:05x}") from error
    if pcs[-1] != 0xDFF44:
        raise ValueError("WonderWitch program did not settle in key_wait")

    if len(frames) != len(FRAME_SHA256):
        raise ValueError(f"expected {len(FRAME_SHA256)} frames, got {len(frames)}")
    for index, (path, wanted) in enumerate(zip(frames, FRAME_SHA256)):
        data = path.read_bytes()
        actual = sha256(data)
        if len(data) != 224 * 144 * 3 or actual != wanted:
            raise ValueError(f"frame {index} size/hash mismatch: {len(data)} {actual}")
    visible = frames[3].read_bytes()
    pixels = [visible[index : index + 3] for index in range(0, len(visible), 3)]
    if Counter(pixels) != Counter({b"\xff\xff\xff": 32018, b"\0\0\0": 238}):
        raise ValueError("visible Hello frame lost its exact two-color pixel census")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--toolchain", type=Path)
    parser.add_argument("--fx", type=Path)
    parser.add_argument("--rom", type=Path)
    parser.add_argument("--trace", type=Path)
    parser.add_argument("--frames", nargs="*", type=Path)
    args = parser.parse_args()
    try:
        verify_source(args.fixture)
        if args.toolchain is not None:
            verify_toolchain(args.toolchain)
        if (args.fx is None) != (args.rom is None):
            raise ValueError("--fx and --rom must be supplied together")
        if args.fx is not None and args.rom is not None:
            verify_artifacts(args.fx, args.rom)
        if args.trace is not None:
            verify_runtime(args.trace, tuple(args.frames or ()))
        elif args.frames:
            raise ValueError("--frames requires --trace")
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        raise SystemExit(f"WonderWitch Athena fixture: {error}") from error
    print("PASS open AthenaOS mkrom fixture source/artifacts/translated-core checks")


if __name__ == "__main__":
    main()
