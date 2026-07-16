#!/usr/bin/env python3
"""Build the reviewed QA-only Chip32 stuck-pending diagnostic.

The release Chip32 program polls a PMP status word until RTL reports ready or
rejected.  Physical QA must prove that its instruction-count guard produces a
visible error before Pocket's own Chip32 crash limit.  This tool derives a
diagnostic from the exact pinned release source/image pair by replacing the
single ``pmpr r1,r2`` instruction with ``xor r2,r2``.  The diagnostic therefore
holds the observed status at pending without depending on another register or
shortening the release timeout.

The output is a new private directory.  It is never a release input and the
tool will not write inside the repository.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
from typing import Any

from build_chip32 import (
    EXPECTED_ASM_SHA256,
    EXPECTED_IMAGE_SHA256,
    EXPECTED_IMAGE_SIZE,
    chip32_image_bytes,
)


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ASSEMBLY = ROOT / "src/support/chip32.asm"
DEFAULT_ENCODED_IMAGE = ROOT / "src/support/chip32.bin.hex"
MAGIC = "SWAN_SONG_CHIP32_PENDING_DIAGNOSTIC_V1"
ARCHITECTURE_URL = (
    "https://github.com/open-fpga/bass-chip32/blob/"
    "main/architectures/chip32.vm.arch"
)
RELEASE_SOURCE_INSTRUCTION = b"  pmpr r1,r2\n"
DIAGNOSTIC_SOURCE_INSTRUCTION = (
    b"  xor r2,r2 // QA-only: hold validation status at pending (0)\n"
)
# From the official Chip32 BASS architecture: operands r1,r2 + PMPR opcode 3b,
# and operands r2,r2 + register-XOR opcode 2b.
RELEASE_MACHINE_INSTRUCTION = bytes.fromhex("213b")
DIAGNOSTIC_MACHINE_INSTRUCTION = bytes.fromhex("222b")
EXPECTED_PATCH_OFFSET = 84
TIMEOUT_LITERAL = b"constant rom_validation_timeout = 0x00100000"
EXPECTED_DIAGNOSTIC_ASM_SHA256 = (
    "40beab8a7ee0bb90aeb806e2cd2ca6d06de9a63ad5195dafcd177e48ba0ac2ee"
)
EXPECTED_DIAGNOSTIC_IMAGE_SHA256 = (
    "0b49da5d3de1090a254caa72a996cfc078d9326e6d067709227c737a326d9a7d"
)


class DiagnosticError(ValueError):
    """A safe, actionable diagnostic-build failure."""


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _read_regular(path: Path, label: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise DiagnosticError(f"{label} must be a regular non-symlink file: {path}")
    try:
        return path.read_bytes()
    except OSError as error:
        raise DiagnosticError(f"cannot read {label} {path}: {error}") from error


def build_payloads(
    assembly_bytes: bytes, encoded_image_bytes: bytes
) -> tuple[dict[str, bytes], dict[str, Any]]:
    """Return the deterministic diagnostic files and their public manifest."""

    try:
        release_image = chip32_image_bytes(
            assembly_bytes,
            encoded_image_bytes,
            assembly_description="release Chip32 assembly",
            encoded_image_description="release encoded Chip32 image",
        )
    except ValueError as error:
        raise DiagnosticError(str(error)) from error

    if assembly_bytes.count(RELEASE_SOURCE_INSTRUCTION) != 1:
        raise DiagnosticError(
            "release assembly must contain exactly one reviewed PMPR poll instruction"
        )
    if assembly_bytes.count(TIMEOUT_LITERAL) != 1:
        raise DiagnosticError(
            "release assembly must contain exactly one reviewed timeout literal"
        )
    if release_image.count(RELEASE_MACHINE_INSTRUCTION) != 1:
        raise DiagnosticError(
            "release image must contain exactly one reviewed PMPR machine instruction"
        )
    offset = release_image.find(RELEASE_MACHINE_INSTRUCTION)
    if offset != EXPECTED_PATCH_OFFSET:
        raise DiagnosticError(
            "release PMPR instruction offset changed: "
            f"expected {EXPECTED_PATCH_OFFSET}, got {offset}"
        )

    diagnostic_assembly = assembly_bytes.replace(
        RELEASE_SOURCE_INSTRUCTION, DIAGNOSTIC_SOURCE_INSTRUCTION
    )
    diagnostic_image = (
        release_image[:offset]
        + DIAGNOSTIC_MACHINE_INSTRUCTION
        + release_image[offset + len(RELEASE_MACHINE_INSTRUCTION) :]
    )
    changed_offsets = [
        index
        for index, (release_byte, diagnostic_byte) in enumerate(
            zip(release_image, diagnostic_image, strict=True)
        )
        if release_byte != diagnostic_byte
    ]
    if changed_offsets != [offset, offset + 1]:
        raise DiagnosticError("diagnostic must change exactly the reviewed two bytes")
    if diagnostic_assembly.count(TIMEOUT_LITERAL) != 1:
        raise DiagnosticError("diagnostic changed the release timeout literal")
    if _sha256(diagnostic_assembly) != EXPECTED_DIAGNOSTIC_ASM_SHA256:
        raise DiagnosticError("diagnostic assembly identity changed")
    if _sha256(diagnostic_image) != EXPECTED_DIAGNOSTIC_IMAGE_SHA256:
        raise DiagnosticError("diagnostic image identity changed")

    readme = (
        "Swan Song Chip32 stuck-pending diagnostic\n\n"
        "QA ONLY - NEVER SHIP THIS FILE.\n\n"
        "This package changes only the ROM-validation status read. It keeps the\n"
        "release timeout literal at 0x00100000 and forces the read result to\n"
        "pending (0). Use it only on an isolated QA SD card to confirm that the\n"
        "visible 'ROM validation timed out' path occurs before Pocket's own\n"
        "Chip32 cycle limit. Record this manifest and the complete source delta,\n"
        "then restore the exact signed release package and verify every installed\n"
        "payload hash before continuing.\n"
    ).encode("ascii")

    manifest: dict[str, Any] = {
        "magic": MAGIC,
        "purpose": "physical calibration of the bounded ROM-validation pending path",
        "release_input": {
            "assembly_sha256": EXPECTED_ASM_SHA256,
            "encoded_image_sha256": _sha256(encoded_image_bytes),
            "image_sha256": EXPECTED_IMAGE_SHA256,
            "image_size": EXPECTED_IMAGE_SIZE,
        },
        "diagnostic": {
            "assembly": "chip32-pending.asm",
            "assembly_sha256": EXPECTED_DIAGNOSTIC_ASM_SHA256,
            "image": "chip32-pending.bin",
            "image_sha256": EXPECTED_DIAGNOSTIC_IMAGE_SHA256,
            "image_size": len(diagnostic_image),
        },
        "patch": {
            "offset": offset,
            "release_source": RELEASE_SOURCE_INSTRUCTION.decode("ascii").strip(),
            "diagnostic_source": DIAGNOSTIC_SOURCE_INSTRUCTION.decode("ascii").strip(),
            "release_bytes": RELEASE_MACHINE_INSTRUCTION.hex(),
            "diagnostic_bytes": DIAGNOSTIC_MACHINE_INSTRUCTION.hex(),
            "changed_offsets": changed_offsets,
        },
        "invariants": {
            "timeout_literal": TIMEOUT_LITERAL.decode("ascii"),
            "timeout_preserved": True,
            "release_image_size_preserved": len(diagnostic_image)
            == len(release_image),
            "qa_only_never_release": True,
        },
        "chip32_architecture": ARCHITECTURE_URL,
    }
    manifest_bytes = (
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode("ascii")
    payloads = {
        "README.txt": readme,
        "chip32-pending.asm": diagnostic_assembly,
        "chip32-pending.bin": diagnostic_image,
        "manifest.json": manifest_bytes,
    }
    return payloads, manifest


def _safe_output(output: Path) -> Path:
    output = output.expanduser().absolute()
    if output.name in {"", ".", ".."}:
        raise DiagnosticError("output must name a new directory")
    if output.exists() or output.is_symlink():
        raise DiagnosticError(f"output already exists: {output}")
    try:
        repository = ROOT.resolve(strict=True)
        parent = output.parent.resolve(strict=True)
        parent_stat = output.parent.lstat()
    except OSError as error:
        raise DiagnosticError("output parent must be an existing directory") from error
    if stat.S_ISLNK(parent_stat.st_mode) or not stat.S_ISDIR(parent_stat.st_mode):
        raise DiagnosticError("output parent must be a real non-symlink directory")
    candidate = parent / output.name
    if candidate == repository or repository in candidate.parents:
        raise DiagnosticError("diagnostic output must be outside the repository")
    return candidate


def _write_exclusive(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)


def materialize(output: Path, payloads: dict[str, bytes]) -> Path:
    destination = _safe_output(output)
    try:
        destination.mkdir(mode=0o700)
        for name in sorted(payloads):
            _write_exclusive(destination / name, payloads[name])
        descriptor = os.open(
            destination, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        )
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except Exception:
        if destination.is_dir() and not destination.is_symlink():
            shutil.rmtree(destination)
        raise
    return destination


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assembly", type=Path, default=DEFAULT_ASSEMBLY)
    parser.add_argument("--encoded-image", type=Path, default=DEFAULT_ENCODED_IMAGE)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--apply", action="store_true", help="create the new private output directory"
    )
    args = parser.parse_args()
    try:
        payloads, manifest = build_payloads(
            _read_regular(args.assembly, "release assembly"),
            _read_regular(args.encoded_image, "release encoded image"),
        )
        destination = _safe_output(args.output)
        if args.apply:
            materialize(destination, payloads)
            print(destination)
        else:
            print(f"Would create QA-only diagnostic directory: {destination}")
            print(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True))
    except (DiagnosticError, OSError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
