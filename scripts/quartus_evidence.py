#!/usr/bin/env python3
"""Collect a bounded, symlink-safe allowlist of Quartus candidate evidence."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import stat
import sys


CHUNK_SIZE = 1024 * 1024


class EvidenceError(RuntimeError):
    """The candidate evidence tree does not satisfy the upload contract."""


@dataclass(frozen=True)
class EvidenceFile:
    relative: Path
    max_bytes: int


EVIDENCE_FILES = (
    EvidenceFile(Path("quartus-audit-candidate.json"), 8 * 1024 * 1024),
    EvidenceFile(Path("quartus.log"), 128 * 1024 * 1024),
    EvidenceFile(Path("ap_core.rbf.sha256"), 64 * 1024),
    EvidenceFile(Path("build-metadata.txt"), 1024 * 1024),
    EvidenceFile(Path("toolchain-version.txt"), 1024 * 1024),
    EvidenceFile(Path("build_id.mif"), 1024 * 1024),
    EvidenceFile(Path("output_files/ap_core.rbf"), 32 * 1024 * 1024),
    EvidenceFile(Path("output_files/ap_core.fit.rpt"), 64 * 1024 * 1024),
    EvidenceFile(Path("output_files/ap_core.asm.rpt"), 64 * 1024 * 1024),
    EvidenceFile(Path("output_files/ap_core.sta.rpt"), 64 * 1024 * 1024),
    EvidenceFile(Path("output_files/ap_core.flow.rpt"), 64 * 1024 * 1024),
)


def _require_plain_directory(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as error:
        raise EvidenceError(f"{label} does not exist: {path}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise EvidenceError(f"{label} must be a nonsymlink directory: {path}")


def _open_source(root: Path, item: EvidenceFile) -> int | None:
    parent = root
    for component in item.relative.parts[:-1]:
        parent = parent / component
        try:
            metadata = parent.lstat()
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise EvidenceError(
                f"evidence parent must be a nonsymlink directory: {item.relative}"
            )

    source = root / item.relative
    try:
        metadata = source.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise EvidenceError(f"evidence input must be a regular file: {item.relative}")
    if metadata.st_size > item.max_bytes:
        raise EvidenceError(
            f"evidence input exceeds {item.max_bytes} bytes: {item.relative}"
        )

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(source, flags)
    opened = os.fstat(descriptor)
    if (
        not stat.S_ISREG(opened.st_mode)
        or opened.st_dev != metadata.st_dev
        or opened.st_ino != metadata.st_ino
    ):
        os.close(descriptor)
        raise EvidenceError(f"evidence input changed while opening: {item.relative}")
    return descriptor


def _copy_source(descriptor: int, output: Path, item: EvidenceFile) -> None:
    destination = output / item.relative
    copied = 0
    with os.fdopen(descriptor, "rb", closefd=True) as source:
        destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        output_descriptor = os.open(destination, flags, 0o600)
        try:
            with os.fdopen(output_descriptor, "wb", closefd=True) as target:
                while chunk := source.read(CHUNK_SIZE):
                    copied += len(chunk)
                    if copied > item.max_bytes:
                        raise EvidenceError(
                            f"evidence input grew beyond {item.max_bytes} bytes: "
                            f"{item.relative}"
                        )
                    target.write(chunk)
                target.flush()
                os.fchmod(target.fileno(), 0o644)
        except BaseException:
            destination.unlink(missing_ok=True)
            raise


def collect_evidence(artifacts: Path, output: Path) -> list[Path]:
    """Copy only present allowlisted files; missing files are valid after a failed fit."""

    _require_plain_directory(artifacts, "artifact root")
    _require_plain_directory(output, "evidence output")
    if os.path.samefile(artifacts, output):
        raise EvidenceError("artifact root and evidence output must be different")
    if any(output.iterdir()):
        raise EvidenceError(f"evidence output must be empty: {output}")

    opened: list[tuple[EvidenceFile, int]] = []
    try:
        for item in EVIDENCE_FILES:
            descriptor = _open_source(artifacts, item)
            if descriptor is not None:
                opened.append((item, descriptor))

        collected: list[Path] = []
        while opened:
            item, descriptor = opened.pop(0)
            _copy_source(descriptor, output, item)
            collected.append(item.relative)
        return collected
    finally:
        for _, descriptor in opened:
            os.close(descriptor)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        collected = collect_evidence(args.artifacts, args.output)
    except (EvidenceError, OSError) as error:
        print(f"quartus_evidence.py: {error}", file=sys.stderr)
        return 1
    print(f"collected {len(collected)} bounded Quartus evidence file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
