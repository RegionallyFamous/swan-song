#!/usr/bin/env python3
"""Verify and narrowly extract the official Quartus Lite 21.1.1 bundle.

The production CLI has no checksum override. Tests call the library API with a
small synthetic manifest instead of weakening the fail-closed command line.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import os
from pathlib import Path, PurePosixPath
import sys
import tarfile
from typing import Iterable, Mapping


CHUNK_SIZE = 4 * 1024 * 1024


class ArchiveError(RuntimeError):
    """The supplied archive does not satisfy the pinned vendor contract."""


@dataclasses.dataclass(frozen=True)
class Artifact:
    name: str
    sha1: str
    executable: bool = False


@dataclasses.dataclass(frozen=True)
class Manifest:
    archive: Artifact
    components: tuple[Artifact, ...]


OFFICIAL_MANIFEST = Manifest(
    archive=Artifact(
        "Quartus-lite-21.1.1.850-linux.tar",
        "789c1133d99fde7146fdb99c1f5dcb4d2e5cc0cc",
    ),
    components=(
        Artifact(
            "QuartusLiteSetup-21.1.1.850-linux.run",
            "6b25e8c62535d0ac02a1075b3dd334d2b04394aa",
            executable=True,
        ),
        Artifact(
            "cyclonev-21.1.1.850.qdz",
            "467123b7bd5e6907beb7d6b1e073ed7bad3e5e94",
        ),
    ),
)


def sha1_file(path: Path) -> str:
    digest = hashlib.sha1(usedforsecurity=False)
    with path.open("rb") as source:
        while chunk := source.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _require_archive(path: Path, manifest: Manifest) -> None:
    if path.name != manifest.archive.name:
        raise ArchiveError(
            f"archive filename must be {manifest.archive.name}, got {path.name}"
        )
    if not path.is_file():
        raise ArchiveError(f"archive is not a regular file: {path}")
    actual = sha1_file(path)
    if actual != manifest.archive.sha1:
        raise ArchiveError(
            f"archive SHA-1 mismatch: expected {manifest.archive.sha1}, got {actual}"
        )


def _safe_member_name(raw_name: str) -> PurePosixPath:
    path = PurePosixPath(raw_name)
    if path.is_absolute() or ".." in path.parts:
        raise ArchiveError(f"unsafe tar member path: {raw_name!r}")
    return path


def _find_components(
    archive: tarfile.TarFile, components: Iterable[Artifact]
) -> Mapping[str, tarfile.TarInfo]:
    wanted = {component.name: component for component in components}
    found: dict[str, tarfile.TarInfo] = {}
    for member in archive:
        member_path = _safe_member_name(member.name)
        basename = member_path.name
        if basename not in wanted:
            continue
        if basename in found:
            raise ArchiveError(f"duplicate required component in archive: {basename}")
        if not member.isreg():
            raise ArchiveError(f"required component is not a regular file: {member.name}")
        found[basename] = member

    missing = sorted(set(wanted).difference(found))
    if missing:
        raise ArchiveError("archive is missing required component(s): " + ", ".join(missing))
    return found


def inspect_archive(path: Path, manifest: Manifest = OFFICIAL_MANIFEST) -> dict[str, str]:
    """Verify the bundle and return verified inner component SHA-1 values."""

    _require_archive(path, manifest)
    results: dict[str, str] = {}
    with tarfile.open(path, mode="r:*") as archive:
        members = _find_components(archive, manifest.components)
        for component in manifest.components:
            source = archive.extractfile(members[component.name])
            if source is None:
                raise ArchiveError(f"cannot read required component: {component.name}")
            digest = hashlib.sha1(usedforsecurity=False)
            while chunk := source.read(CHUNK_SIZE):
                digest.update(chunk)
            actual = digest.hexdigest()
            if actual != component.sha1:
                raise ArchiveError(
                    f"{component.name} SHA-1 mismatch: expected {component.sha1}, got {actual}"
                )
            results[component.name] = actual
    return results


def extract_components(
    path: Path, destination: Path, manifest: Manifest = OFFICIAL_MANIFEST
) -> dict[str, str]:
    """Verify the bundle and extract exactly the manifest's regular files."""

    _require_archive(path, manifest)
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise ArchiveError(f"extraction destination must be empty: {destination}")

    results: dict[str, str] = {}
    with tarfile.open(path, mode="r:*") as archive:
        members = _find_components(archive, manifest.components)
        for component in manifest.components:
            source = archive.extractfile(members[component.name])
            if source is None:
                raise ArchiveError(f"cannot read required component: {component.name}")
            output_path = destination / component.name
            descriptor = os.open(output_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            digest = hashlib.sha1(usedforsecurity=False)
            try:
                with os.fdopen(descriptor, "wb") as output:
                    while chunk := source.read(CHUNK_SIZE):
                        digest.update(chunk)
                        output.write(chunk)
                actual = digest.hexdigest()
                if actual != component.sha1:
                    raise ArchiveError(
                        f"{component.name} SHA-1 mismatch: expected {component.sha1}, got {actual}"
                    )
                output_path.chmod(0o755 if component.executable else 0o644)
                results[component.name] = actual
            except BaseException:
                output_path.unlink(missing_ok=True)
                raise
    return results


def _print_result(path: Path, results: Mapping[str, str]) -> None:
    print(f"verified {path.name}: {OFFICIAL_MANIFEST.archive.sha1}")
    for component in OFFICIAL_MANIFEST.components:
        print(f"verified {component.name}: {results[component.name]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify_parser = subparsers.add_parser("verify", help="verify bundle and inner files")
    verify_parser.add_argument("archive", type=Path)
    extract_parser = subparsers.add_parser(
        "extract", help="verify and extract only Quartus Lite plus Cyclone V"
    )
    extract_parser.add_argument("archive", type=Path)
    extract_parser.add_argument("destination", type=Path)
    args = parser.parse_args(argv)

    try:
        if args.command == "verify":
            results = inspect_archive(args.archive)
        else:
            results = extract_components(args.archive, args.destination)
        _print_result(args.archive, results)
    except (ArchiveError, OSError, tarfile.TarError) as error:
        print(f"quartus_archive.py: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
