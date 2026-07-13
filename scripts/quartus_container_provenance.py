#!/usr/bin/env python3
"""Create or validate bounded provenance for the trusted Quartus container."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


MAGIC = "SWAN_SONG_QUARTUS_CONTAINER_V1"
PACKAGE_NAME = re.compile(r"[a-z0-9][a-z0-9+.-]*(?::[a-z0-9][a-z0-9-]*)?\Z")
PACKAGE_ARCH = re.compile(r"[a-z0-9][a-z0-9-]*\Z")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
REPO_DIGEST = re.compile(r"[^\s@]+@(sha256:[0-9a-f]{64})\Z")
MANIFEST_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
MAX_PACKAGE_BYTES = 2 * 1024 * 1024
MAX_PACKAGE_COUNT = 4096
MAX_PROVENANCE_BYTES = 64 * 1024
PACKAGE_FILENAME = "container-packages.tsv"


class ProvenanceError(RuntimeError):
    """Container provenance does not satisfy the bounded evidence contract."""


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ProvenanceError(f"duplicate JSON field in container provenance: {key}")
        result[key] = value
    return result


def _plain_file_bytes(path: Path, *, maximum: int, label: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ProvenanceError(f"{label} must be a regular nonsymlink file: {path}")
    size = path.stat().st_size
    if size > maximum:
        raise ProvenanceError(f"{label} exceeds {maximum} bytes: {path}")
    return path.read_bytes()


def validate_packages(path: Path) -> tuple[int, int, str]:
    """Validate the sorted dpkg-query manifest and return count, size, SHA-256."""

    raw = _plain_file_bytes(
        path, maximum=MAX_PACKAGE_BYTES, label="container package manifest"
    )
    if not raw or not raw.endswith(b"\n") or b"\r" in raw or b"\0" in raw:
        raise ProvenanceError("container package manifest must be nonempty LF text")
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise ProvenanceError("container package manifest is not UTF-8") from error
    if len(lines) > MAX_PACKAGE_COUNT:
        raise ProvenanceError(
            f"container package manifest exceeds {MAX_PACKAGE_COUNT} entries"
        )
    if lines != sorted(lines) or len(lines) != len(set(lines)):
        raise ProvenanceError(
            "container package manifest entries must be sorted and unique"
        )

    packages: set[str] = set()
    for line in lines:
        fields = line.split("\t")
        if len(fields) != 3:
            raise ProvenanceError("container package lines require three TSV fields")
        package, version, architecture = fields
        if not PACKAGE_NAME.fullmatch(package):
            raise ProvenanceError(f"invalid container package name: {package!r}")
        if package in packages:
            raise ProvenanceError(f"duplicate container package: {package}")
        packages.add(package)
        if not version or any(character.isspace() for character in version):
            raise ProvenanceError(f"invalid version for container package: {package}")
        if not PACKAGE_ARCH.fullmatch(architecture):
            raise ProvenanceError(
                f"invalid architecture for container package: {package}"
            )

    return len(lines), len(raw), hashlib.sha256(raw).hexdigest()


def _registry_manifest_digests(value: str) -> list[str]:
    repo_digests = [line for line in value.splitlines() if line]
    if repo_digests != sorted(set(repo_digests)):
        raise ProvenanceError("repository digests must be sorted and unique")
    manifest_digests: set[str] = set()
    for repo_digest in repo_digests:
        match = REPO_DIGEST.fullmatch(repo_digest)
        if match is None:
            raise ProvenanceError(f"invalid repository digest: {repo_digest!r}")
        manifest_digests.add(match.group(1))
    return sorted(manifest_digests)


def create_provenance(
    *,
    image_id: str,
    repo_digests_text: str,
    packages: Path,
    output: Path,
) -> dict[str, object]:
    if not IMAGE_ID.fullmatch(image_id):
        raise ProvenanceError(f"invalid immutable image ID: {image_id!r}")
    count, byte_count, digest = validate_packages(packages)
    document: dict[str, object] = {
        "magic": MAGIC,
        "image_id": image_id,
        # Registry/repository coordinates can be private. Preserve only the
        # immutable manifest digest shared by those coordinates.
        "registry_manifest_digests": _registry_manifest_digests(repo_digests_text),
        "platform": "linux/amd64",
        "quartus": {
            "archive_sha1": "789c1133d99fde7146fdb99c1f5dcb4d2e5cc0cc",
            "device": "5CEBA4F23C8",
            "edition": "Lite",
            "version": "21.1.1.850",
        },
        "packages": {
            "path": PACKAGE_FILENAME,
            "count": count,
            "bytes": byte_count,
            "sha256": digest,
        },
    }
    encoded = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode()
    if len(encoded) > MAX_PROVENANCE_BYTES:
        raise ProvenanceError("container provenance document exceeds bounded size")
    if output.exists() or output.is_symlink():
        raise ProvenanceError(f"container provenance output already exists: {output}")
    output.write_bytes(encoded)
    return document


def validate_provenance(provenance: Path, packages: Path) -> dict[str, object]:
    raw = _plain_file_bytes(
        provenance, maximum=MAX_PROVENANCE_BYTES, label="container provenance"
    )
    try:
        document = json.loads(raw, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProvenanceError("container provenance is not valid UTF-8 JSON") from error
    if not isinstance(document, dict):
        raise ProvenanceError("container provenance must be a JSON object")
    if set(document) != {
        "magic",
        "image_id",
        "registry_manifest_digests",
        "platform",
        "quartus",
        "packages",
    }:
        raise ProvenanceError("container provenance fields are not the exact schema")

    image_id = document.get("image_id")
    manifest_digests = document.get("registry_manifest_digests")
    if document.get("magic") != MAGIC:
        raise ProvenanceError("container provenance magic is wrong")
    if not isinstance(image_id, str) or not IMAGE_ID.fullmatch(image_id):
        raise ProvenanceError("container provenance image ID is invalid")
    if not isinstance(manifest_digests, list) or not all(
        isinstance(item, str) for item in manifest_digests
    ):
        raise ProvenanceError("container provenance registry digests are invalid")
    if manifest_digests != sorted(set(manifest_digests)) or not all(
        MANIFEST_DIGEST.fullmatch(item) for item in manifest_digests
    ):
        raise ProvenanceError("container provenance registry digests are not canonical")
    if document.get("platform") != "linux/amd64":
        raise ProvenanceError("container provenance platform is wrong")
    if document.get("quartus") != {
        "archive_sha1": "789c1133d99fde7146fdb99c1f5dcb4d2e5cc0cc",
        "device": "5CEBA4F23C8",
        "edition": "Lite",
        "version": "21.1.1.850",
    }:
        raise ProvenanceError("container provenance Quartus identity is wrong")

    count, byte_count, digest = validate_packages(packages)
    package_identity = document.get("packages")
    if not isinstance(package_identity, dict) or set(package_identity) != {
        "path",
        "count",
        "bytes",
        "sha256",
    }:
        raise ProvenanceError("container package identity is not the exact schema")
    if type(package_identity.get("count")) is not int or type(
        package_identity.get("bytes")
    ) is not int:
        raise ProvenanceError("container package count and size must be exact integers")
    if package_identity != {
        "path": PACKAGE_FILENAME,
        "count": count,
        "bytes": byte_count,
        "sha256": digest,
    }:
        raise ProvenanceError("container package identity does not match provenance")
    return document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--image-id", required=True)
    create.add_argument("--repo-digests", default="")
    create.add_argument("--packages", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--provenance", type=Path, required=True)
    validate.add_argument("--packages", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            create_provenance(
                image_id=args.image_id,
                repo_digests_text=args.repo_digests,
                packages=args.packages,
                output=args.output,
            )
        else:
            validate_provenance(args.provenance, args.packages)
    except (OSError, ProvenanceError) as error:
        print(f"quartus_container_provenance.py: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
