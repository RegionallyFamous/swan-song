#!/usr/bin/env python3
"""Safely record one physical Pocket/Dock QA case at a time.

The strict hardware-QA manifest has no in-progress case state: a ``pending``
case must remain an empty skeleton.  This recorder therefore keeps one private
active-session sidecar beside the manifest and publishes the completed case to
the existing manifest schema in one atomic replacement.  A prepared sidecar
left by interruption after publication can be removed only by the fail-closed
``recover-session`` proof.  The recorder never selects a result, marks a
check, or changes the final human attestation on its own.
"""

from __future__ import annotations

import argparse
import codecs
from contextlib import contextmanager
import fcntl
import functools
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import struct
import sys
import tempfile
from typing import Any, BinaryIO

import pocket_hardware_qa as qa


ROOT = Path(__file__).resolve().parents[1]
SESSION_MAGIC = "SWAN_SONG_HARDWARE_QA_ACTIVE_CASE_V2"
SESSION_FILENAME = ".active-hardware-qa-case.json"
LOCK_FILENAME = ".hardware-qa-session.lock"
RESULT_MAGIC = "SWAN_SONG_HARDWARE_QA_CASE_RESULT_V1"
CHUNK_BYTES = 1024 * 1024
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024 * 1024
ARTIFACT_ID_RE = re.compile(
    r"(?P<case>[a-z0-9][a-z0-9_.-]{0,62})-"
    r"(?P<kind>pocket_screenshot|photo|video|audio|save|log)-"
    r"(?P<number>[0-9]{2})\Z"
)


class SessionError(ValueError):
    """A fail-closed, actionable recorder error."""


def _canonical_json(document: dict[str, Any]) -> bytes:
    return (
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode("utf-8")


def _strict_json(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink() or not path.is_file():
        raise SessionError(f"{label} must be a regular non-symlink file: {path}")
    if path.stat().st_nlink != 1:
        raise SessionError(f"{label} must not be a hard link: {path}")

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise SessionError(f"{label} repeats member {key!r}")
            result[key] = value
        return result

    def reject_nonstandard_number(token: str) -> None:
        raise SessionError(f"{label} contains non-standard number {token}")

    try:
        payload = path.read_bytes()
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=unique,
            parse_constant=reject_nonstandard_number,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SessionError(f"invalid {label}: {error}") from error
    if not isinstance(value, dict):
        raise SessionError(f"{label} must be a JSON object")
    return value, payload


def _beneath(path: Path, root: Path, label: str) -> Path:
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise SessionError(f"{label} must remain inside the private QA workspace") from error
    return resolved


def _private_workspace(inventory: Path, manifest: Path) -> tuple[Path, Path, Path]:
    inventory = inventory.expanduser().absolute()
    manifest = manifest.expanduser().absolute()
    repository = ROOT.resolve(strict=True)
    if (
        inventory == repository
        or repository in inventory.parents
        or manifest == repository
        or repository in manifest.parents
    ):
        raise SessionError("physical QA workspace must be outside the repository")
    if inventory.is_symlink() or manifest.is_symlink():
        raise SessionError("inventory and manifest must not be symlinks")
    if not inventory.is_file() or not manifest.is_file():
        raise SessionError("inventory and manifest must be existing regular files")
    workspace = inventory.parent.resolve(strict=True)
    expected_evidence = workspace / "evidence"
    if manifest.parent.resolve(strict=True) != expected_evidence:
        raise SessionError(
            "manifest must be workspace/evidence/manifest.json beside workspace/inventory.json"
        )
    if workspace == repository or repository in workspace.parents:
        raise SessionError("physical QA workspace must be outside the repository")
    metadata = workspace.stat()
    if not stat.S_ISDIR(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) & 0o077:
        raise SessionError("physical QA workspace must be owner-only (mode 0700)")
    if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
        raise SessionError("physical QA workspace must be owned by the current user")
    for label, path in (("inventory", inventory), ("manifest", manifest)):
        if path.stat().st_nlink != 1:
            raise SessionError(f"{label} must not be a hard link")
        _beneath(path, workspace, label)
    return workspace, inventory.resolve(strict=True), manifest.resolve(strict=True)


def _session_path(manifest: Path) -> Path:
    return manifest.parent / SESSION_FILENAME


@contextmanager
def _operation_lock(manifest: Path):
    """Serialize recorder transactions in one private evidence workspace."""

    path = manifest.parent / LOCK_FILENAME
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as error:
        raise SessionError(f"cannot open hardware QA session lock: {error}") from error
    locked = False
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise SessionError("hardware QA session lock must be one regular file")
        if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
            raise SessionError("hardware QA session lock must be owned by the current user")
        os.fchmod(descriptor, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except BlockingIOError as error:
            raise SessionError(
                "another hardware QA recorder operation is active"
            ) from error
        yield
    finally:
        if locked:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _locked_operation(function):
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        if args or "inventory" not in kwargs or "manifest" not in kwargs:
            raise TypeError("recorder operations require keyword arguments")
        _workspace, inventory, manifest = _private_workspace(
            kwargs["inventory"], kwargs["manifest"]
        )
        with _operation_lock(manifest):
            # Bind the operation to the exact canonical paths whose evidence
            # directory is locked. A caller-supplied symlinked parent cannot
            # be rebound after lock acquisition to redirect the mutation into
            # a different, unlocked workspace.
            bound = {**kwargs, "inventory": inventory, "manifest": manifest}
            return function(**bound)

    return wrapped


def _validate_current_manifest(inventory: Path, manifest: Path) -> tuple[dict[str, Any], bytes]:
    try:
        qa.verify_manifest(manifest, inventory, require_pass=False)
    except ValueError as error:
        raise SessionError(f"current hardware QA manifest is invalid: {error}") from error
    document, payload = _strict_json(manifest, "hardware QA manifest")
    return document, payload


def _atomic_create(path: Path, payload: bytes, mode: int = 0o600) -> None:
    if path.exists() or path.is_symlink():
        raise SessionError(f"refusing to overwrite existing path: {path}")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        # Linking a sibling temporary inode publishes without any overwrite
        # window; removing the temporary name restores link count 1.
        os.link(temporary, path, follow_symlinks=False)
        temporary.unlink()
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _atomic_replace(path: Path, payload: bytes, expected_sha256: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise SessionError(f"atomic update target changed type: {path}")
    if path.stat().st_nlink != 1:
        raise SessionError(f"atomic update target became a hard link: {path}")
    current = path.read_bytes()
    if hashlib.sha256(current).hexdigest() != expected_sha256:
        raise SessionError(f"refusing to replace concurrently changed file: {path}")
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        # Recheck immediately before the atomic publication.
        if path.is_symlink() or not path.is_file():
            raise SessionError(f"atomic update target changed type: {path}")
        if path.stat().st_nlink != 1:
            raise SessionError(f"atomic update target became a hard link: {path}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256:
            raise SessionError(f"refusing to replace concurrently changed file: {path}")
        os.replace(temporary, path)
        try:
            directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        except OSError:
            pass
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _unlink_exact(path: Path, expected_sha256: str) -> None:
    """Remove one exact owner file without accepting a substituted sidecar."""

    if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
        raise SessionError(f"refusing to remove changed session sidecar: {path}")
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise SessionError(f"refusing to remove concurrently changed sidecar: {path}")
    path.unlink()
    try:
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError:
        pass


def _case(document: dict[str, Any], case_id: str) -> dict[str, Any]:
    try:
        cases = document["hardware_qa"]["cases"]
        matches = [item for item in cases if item.get("id") == case_id]
    except (KeyError, TypeError) as error:
        raise SessionError("hardware QA manifest case catalogue is malformed") from error
    if len(matches) != 1:
        raise SessionError(f"manifest must contain exactly one case {case_id!r}")
    return matches[0]


def _selection(
    document: dict[str, Any], case_id: str, rom_ids: list[str], controller_ids: list[str]
) -> tuple[list[str], list[str]]:
    if case_id not in qa.CASE_BY_ID:
        raise SessionError(f"unknown hardware QA case: {case_id}")
    if len(rom_ids) != len(set(rom_ids)) or len(controller_ids) != len(set(controller_ids)):
        raise SessionError("ROM and controller selections must not contain duplicates")
    environment = document["hardware_qa"]["environment"]
    roms = {item["id"]: item for item in environment["roms"]}
    controllers = {item["id"]: item for item in environment["controllers"]}
    if set(rom_ids) - roms.keys() or set(controller_ids) - controllers.keys():
        raise SessionError("ROM/controller selection contains an unknown inventory ID")
    spec = qa.CASE_BY_ID[case_id]
    selected_roms = [roms[item] for item in sorted(rom_ids)]
    selected_controllers = [controllers[item] for item in sorted(controller_ids)]
    if not qa._meets_rom_requirement(spec.rom_requirement, selected_roms):
        raise SessionError(
            f"ROM selection does not satisfy case requirement {spec.rom_requirement}"
        )
    if not qa._meets_controller_requirement(
        spec.controller_requirement, selected_controllers
    ):
        raise SessionError(
            "controller selection does not satisfy case requirement "
            f"{spec.controller_requirement}"
        )
    return sorted(rom_ids), sorted(controller_ids)


@_locked_operation
def start_case(
    *,
    inventory: Path,
    manifest: Path,
    case_id: str,
    started_at: str,
    rom_ids: list[str],
    controller_ids: list[str],
    apply: bool,
) -> dict[str, Any]:
    workspace, inventory, manifest = _private_workspace(inventory, manifest)
    del workspace
    started_at = qa._utc(started_at, "case started_at")
    document, manifest_bytes = _validate_current_manifest(inventory, manifest)
    target = _case(document, case_id)
    if target != {
        "id": case_id,
        "status": "pending",
        "device_mode": qa.CASE_BY_ID[case_id].device_mode,
        "started_at": None,
        "completed_at": None,
        "rom_ids": [],
        "controller_ids": [],
        "checks": {name: False for name in qa.CASE_BY_ID[case_id].checks},
        "artifact_ids": [],
        "notes": "",
    }:
        raise SessionError("start-case requires the exact untouched pending case skeleton")
    selected_roms, selected_controllers = _selection(
        document, case_id, rom_ids, controller_ids
    )
    session = {
        "active_case": {
            "magic": SESSION_MAGIC,
            "case_id": case_id,
            "started_at": started_at,
            "rom_ids": selected_roms,
            "controller_ids": selected_controllers,
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "inventory_sha256": hashlib.sha256(inventory.read_bytes()).hexdigest(),
            "artifacts": [],
            "sources": [],
            "prepared_finish": None,
        }
    }
    path = _session_path(manifest)
    if path.exists() or path.is_symlink():
        raise SessionError(f"another hardware QA case session is active: {path}")
    if apply:
        _atomic_create(path, _canonical_json(session))
    return session


def _load_session(
    inventory: Path,
    manifest: Path,
    *,
    allow_published: bool = False,
) -> tuple[dict[str, Any], bytes, Path, Path, Path]:
    workspace, inventory, manifest = _private_workspace(inventory, manifest)
    path = _session_path(manifest)
    document, payload = _strict_json(path, "active hardware QA session")
    if set(document) != {"active_case"} or not isinstance(document["active_case"], dict):
        raise SessionError("active session envelope is malformed")
    active = document["active_case"]
    required = {
        "magic", "case_id", "started_at", "rom_ids", "controller_ids",
        "manifest_sha256", "inventory_sha256", "artifacts", "sources",
        "prepared_finish",
    }
    if set(active) != required or active.get("magic") != SESSION_MAGIC:
        raise SessionError("active session body is malformed")
    qa._utc(active.get("started_at"), "active session started_at")
    if active.get("case_id") not in qa.CASE_BY_ID:
        raise SessionError("active session case ID is unknown")
    if not isinstance(active.get("artifacts"), list) or not isinstance(active.get("sources"), list):
        raise SessionError("active session lists are malformed")
    for name in ("rom_ids", "controller_ids"):
        values = active.get(name)
        if (
            not isinstance(values, list)
            or any(not isinstance(value, str) for value in values)
            or values != sorted(set(values))
        ):
            raise SessionError(f"active session {name} are malformed")
    for name in ("manifest_sha256", "inventory_sha256"):
        value = active.get(name)
        if not isinstance(value, str) or not qa.SHA256_RE.fullmatch(value):
            raise SessionError(f"active session {name} is malformed")
    artifact_ids: set[str] = set()
    artifact_paths: set[str] = set()
    artifact_labels: set[str] = set()
    for index, artifact in enumerate(active["artifacts"]):
        if not isinstance(artifact, dict) or set(artifact) != {
            "id", "kind", "path", "label", "captured_at", "size", "sha256"
        }:
            raise SessionError(f"active session artifact {index} is malformed")
        artifact_id = qa._id(artifact["id"], f"active artifact {index} ID")
        if artifact["kind"] not in qa.ARTIFACT_KINDS:
            raise SessionError(f"active session artifact {index} kind is malformed")
        path_value = artifact["path"]
        pure = PurePosixPath(path_value) if isinstance(path_value, str) else None
        if (
            pure is None
            or pure.is_absolute()
            or not pure.parts
            or any(part in {".", ".."} for part in pure.parts)
        ):
            raise SessionError(f"active session artifact {index} path is malformed")
        label = qa._text(artifact["label"], f"active artifact {index} label", 160)
        qa._utc(artifact["captured_at"], f"active artifact {index} captured_at")
        if not isinstance(artifact["size"], int) or artifact["size"] <= 0:
            raise SessionError(f"active session artifact {index} size is malformed")
        digest = artifact["sha256"]
        if not isinstance(digest, str) or not qa.SHA256_RE.fullmatch(digest):
            raise SessionError(f"active session artifact {index} SHA-256 is malformed")
        if artifact_id in artifact_ids or path_value in artifact_paths or label in artifact_labels:
            raise SessionError("active session artifacts contain a duplicate identity")
        artifact_ids.add(artifact_id)
        artifact_paths.add(path_value)
        artifact_labels.add(label)
    source_identities: set[tuple[str, int, int]] = set()
    for index, source in enumerate(active["sources"]):
        if not isinstance(source, dict) or set(source) != {"path", "device", "inode"}:
            raise SessionError(f"active session source {index} is malformed")
        path_value = source["path"]
        pure = PurePosixPath(path_value) if isinstance(path_value, str) else None
        if (
            pure is None
            or pure.is_absolute()
            or not pure.parts
            or any(part in {".", ".."} for part in pure.parts)
            or not isinstance(source["device"], int)
            or source["device"] < 0
            or not isinstance(source["inode"], int)
            or source["inode"] <= 0
        ):
            raise SessionError(f"active session source {index} is malformed")
        identity = (path_value, source["device"], source["inode"])
        if identity in source_identities:
            raise SessionError("active session sources contain a duplicate identity")
        source_identities.add(identity)
    prepared = active.get("prepared_finish")
    if prepared is not None:
        if not isinstance(prepared, dict) or set(prepared) != {
            "manifest_sha256", "result_sha256"
        }:
            raise SessionError("active session prepared finish is malformed")
        if any(
            not isinstance(prepared[name], str)
            or not qa.SHA256_RE.fullmatch(prepared[name])
            for name in ("manifest_sha256", "result_sha256")
        ):
            raise SessionError("active session prepared finish hashes are malformed")
    current_manifest = manifest.read_bytes()
    current_manifest_sha256 = hashlib.sha256(current_manifest).hexdigest()
    published = (
        allow_published
        and prepared is not None
        and current_manifest_sha256 == prepared["manifest_sha256"]
    )
    if current_manifest_sha256 != active.get("manifest_sha256") and not published:
        raise SessionError("manifest changed while the hardware QA case was active")
    if hashlib.sha256(inventory.read_bytes()).hexdigest() != active.get("inventory_sha256"):
        raise SessionError("inventory changed while the hardware QA case was active")
    return document, payload, workspace, inventory, manifest


def _safe_source(source: Path, workspace: Path) -> Path:
    source = source.expanduser().absolute()
    if source.is_symlink() or not source.is_file():
        raise SessionError(f"artifact source must be a regular non-symlink file: {source}")
    source = _beneath(source, workspace, "artifact source")
    metadata = source.stat()
    if metadata.st_nlink != 1:
        raise SessionError("artifact source must not be a hard link")
    if metadata.st_size <= 0 or metadata.st_size > MAX_ARTIFACT_BYTES:
        raise SessionError("artifact source must be nonempty and at most 64 GiB")
    private = workspace / "private"
    if private.is_symlink() or not private.is_dir():
        raise SessionError("workspace private input area must be a real directory")
    try:
        source.relative_to(private.resolve(strict=True))
    except ValueError as error:
        raise SessionError(
            "artifact source must come from the workspace private input area"
        ) from error
    return source


def _suffix(kind: str, source: Path) -> str:
    suffix = source.suffix.casefold()
    allowed = {
        "pocket_screenshot": {".png"},
        "photo": {".png", ".jpg", ".jpeg"},
        "video": {".mp4", ".mov", ".mkv", ".webm"},
        "audio": {".wav", ".flac"},
        "save": {".sav"},
        "log": {".txt", ".log"},
    }
    if kind not in qa.ARTIFACT_KINDS:
        raise SessionError(f"unsupported artifact kind: {kind}")
    if suffix not in allowed[kind]:
        raise SessionError(f"artifact extension {suffix!r} does not match kind {kind}")
    if suffix == ".jpeg":
        return ".jpg"
    if suffix == ".log":
        return ".txt"
    return suffix


def _copy_and_hash(source: Path, output: BinaryIO) -> tuple[int, str, bytes, bool]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(source, flags)
    digest = hashlib.sha256()
    size = 0
    header = bytearray()
    decoder = codecs.getincrementaldecoder("utf-8")("strict")
    utf8_valid = True
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise SessionError("artifact source changed type before copying")
        while True:
            chunk = os.read(descriptor, CHUNK_BYTES)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_ARTIFACT_BYTES:
                raise SessionError("artifact source grew beyond 64 GiB")
            if len(header) < 32:
                header.extend(chunk[: 32 - len(header)])
            try:
                decoder.decode(chunk, final=False)
            except UnicodeDecodeError:
                utf8_valid = False
            digest.update(chunk)
            output.write(chunk)
        try:
            decoder.decode(b"", final=True)
        except UnicodeDecodeError:
            utf8_valid = False
        after = os.fstat(descriptor)
        identity_before = (
            before.st_dev, before.st_ino, before.st_size,
            before.st_mtime_ns, before.st_ctime_ns,
        )
        identity_after = (
            after.st_dev, after.st_ino, after.st_size,
            after.st_mtime_ns, after.st_ctime_ns,
        )
        if identity_before != identity_after or size != after.st_size:
            raise SessionError("artifact source changed while it was copied")
    finally:
        os.close(descriptor)
    return size, digest.hexdigest(), bytes(header), utf8_valid


def _validate_media(
    kind: str, suffix: str, header: bytes, utf8_valid: bool, path: Path
) -> None:
    if kind in {"pocket_screenshot", "photo"} and suffix == ".png":
        if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
            raise SessionError("PNG evidence has an invalid signature or IHDR")
        width, height = struct.unpack(">II", header[16:24])
        if kind == "pocket_screenshot" and (width, height) != (224, 144):
            raise SessionError("Pocket screenshot must have native 224x144 IHDR")
    elif kind == "photo":
        if not header.startswith(b"\xff\xd8"):
            raise SessionError("JPEG photo has an invalid signature")
    elif kind == "video":
        valid = (
            suffix in {".mp4", ".mov"} and len(header) >= 12 and header[4:8] == b"ftyp"
        ) or (
            suffix in {".mkv", ".webm"} and header.startswith(b"\x1aE\xdf\xa3")
        )
        if not valid:
            raise SessionError("video has an invalid container signature")
    elif kind == "audio":
        valid = (
            suffix == ".wav" and len(header) >= 12
            and header[:4] == b"RIFF" and header[8:12] == b"WAVE"
        ) or (suffix == ".flac" and header.startswith(b"fLaC"))
        if not valid:
            raise SessionError("audio has an invalid container signature")
    elif kind == "log" and not utf8_valid:
        raise SessionError("log evidence must be valid UTF-8")
    try:
        qa._validate_decodable_media(path, kind, "artifact source")
    except ValueError as error:
        raise SessionError(str(error)) from error


def _next_artifact_id(active: dict[str, Any], kind: str) -> tuple[str, int]:
    case_id = active["case_id"]
    used: set[int] = set()
    for artifact in active["artifacts"]:
        match = ARTIFACT_ID_RE.fullmatch(str(artifact.get("id", "")))
        if match and match["case"] == case_id and match["kind"] == kind:
            used.add(int(match["number"]))
    number = next((value for value in range(1, 100) if value not in used), None)
    if number is None:
        raise SessionError(f"case already has 99 {kind} artifacts")
    artifact_id = f"{case_id}-{kind}-{number:02d}"
    qa._id(artifact_id, "artifact ID")
    return artifact_id, number


@_locked_operation
def ingest_artifact(
    *, inventory: Path, manifest: Path, source: Path, kind: str,
    label: str, captured_at: str, apply: bool,
) -> dict[str, Any]:
    session, session_bytes, workspace, inventory, manifest = _load_session(
        inventory, manifest
    )
    del inventory
    active = session["active_case"]
    if active["prepared_finish"] is not None:
        raise SessionError(
            "case finish is already prepared; rerun finish-case or recover-session"
        )
    source = _safe_source(source, workspace)
    suffix = _suffix(kind, source)
    label = qa._text(label, "artifact label", 160)
    captured_at = qa._utc(captured_at, "artifact captured_at")
    if captured_at < active["started_at"]:
        raise SessionError("artifact captured_at precedes the active case")
    source_identity = {
        "path": source.relative_to(workspace).as_posix(),
        "device": source.stat().st_dev,
        "inode": source.stat().st_ino,
    }
    if source_identity in active["sources"]:
        raise SessionError("the same source file was already ingested in this case")
    if any(item.get("label") == label for item in active["artifacts"]):
        raise SessionError("artifact labels must be unique within a case")
    artifact_id, _number = _next_artifact_id(active, kind)
    relative = PurePosixPath("files", active["case_id"], artifact_id + suffix)
    destination = manifest.parent.joinpath(*relative.parts)
    if destination.exists() or destination.is_symlink():
        raise SessionError(f"refusing to overwrite evidence destination: {destination}")

    record: dict[str, Any] = {
        "id": artifact_id,
        "kind": kind,
        "path": relative.as_posix(),
        "label": label,
        "captured_at": captured_at,
        "size": 0,
        "sha256": "",
    }
    current_document, _current_bytes = _strict_json(
        manifest, "hardware QA manifest"
    )
    existing_artifacts = current_document["hardware_qa"]["artifacts"]
    if artifact_id in {item["id"] for item in existing_artifacts}:
        raise SessionError("deterministic artifact ID already exists in the manifest")
    if not apply:
        with open(os.devnull, "wb") as output:
            size, digest, header, utf8_valid = _copy_and_hash(source, output)
        _validate_media(kind, suffix, header, utf8_valid, source)
        if kind != "save" and any(
            item.get("sha256") == digest
            for item in [*existing_artifacts, *active["artifacts"]]
        ):
            raise SessionError(
                "duplicate non-save evidence bytes are not independent evidence"
            )
        record["size"] = size
        record["sha256"] = digest
        return record

    evidence_root = manifest.parent.resolve(strict=True)
    files_root = manifest.parent / "files"
    if files_root.exists() or files_root.is_symlink():
        if files_root.is_symlink() or not files_root.is_dir():
            raise SessionError("evidence files root is not a real directory")
    else:
        files_root.mkdir(mode=0o700)
    case_root = files_root / active["case_id"]
    if case_root.exists() or case_root.is_symlink():
        if case_root.is_symlink() or not case_root.is_dir():
            raise SessionError("case evidence directory is not a real directory")
    else:
        case_root.mkdir(mode=0o700)
    if not files_root.resolve().is_relative_to(evidence_root) or not case_root.resolve().is_relative_to(evidence_root):
        raise SessionError("evidence destination directory escapes the manifest root")
    os.chmod(files_root, 0o700)
    os.chmod(case_root, 0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{artifact_id}.", dir=destination.parent
    )
    temporary = Path(temporary_name)
    published = False
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=False) as output:
            size, digest, header, utf8_valid = _copy_and_hash(source, output)
            output.flush()
            os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        if size <= 0:
            raise SessionError("artifact source is empty")
        _validate_media(kind, suffix, header, utf8_valid, temporary)
        if kind != "save" and any(
            item.get("sha256") == digest
            for item in [*existing_artifacts, *active["artifacts"]]
        ):
            raise SessionError("duplicate non-save evidence bytes are not independent evidence")
        record["size"] = size
        record["sha256"] = digest
        # Hard-link publication provides atomic no-replace behavior.  Removing
        # the temporary name leaves the final evidence inode with link count 1.
        os.link(temporary, destination, follow_symlinks=False)
        temporary.unlink()
        published = True
        active["artifacts"].append(record)
        active["artifacts"].sort(key=lambda item: item["id"])
        active["sources"].append(source_identity)
        active["sources"].sort(key=lambda item: (item["path"], item["device"], item["inode"]))
        try:
            _atomic_replace(
                _session_path(manifest),
                _canonical_json(session),
                hashlib.sha256(session_bytes).hexdigest(),
            )
        except BaseException:
            destination.unlink(missing_ok=True)
            published = False
            raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
        if not published and destination.exists() and destination.stat().st_nlink != 1:
            destination.unlink(missing_ok=True)
    return record


def _result(
    path: Path, workspace: Path, case_id: str
) -> tuple[dict[str, Any], bytes]:
    path = _safe_source(path, workspace)
    document, payload = _strict_json(path, "human case result")
    if set(document) != {"hardware_qa_case_result"}:
        raise SessionError("human case result envelope is malformed")
    value = document["hardware_qa_case_result"]
    if not isinstance(value, dict) or set(value) != {
        "magic", "case_id", "status", "completed_at", "checks", "notes"
    }:
        raise SessionError("human case result has invalid members")
    if value["magic"] != RESULT_MAGIC or value["case_id"] != case_id:
        raise SessionError("human case result identity does not match active case")
    if value["status"] not in {"pass", "fail"}:
        raise SessionError("human case result status must be explicit pass or fail")
    value["completed_at"] = qa._utc(value["completed_at"], "result completed_at")
    checks = value["checks"]
    expected_checks = set(qa.CASE_BY_ID[case_id].checks)
    if not isinstance(checks, dict) or set(checks) != expected_checks:
        raise SessionError("human case result must explicitly contain every exact check")
    if not all(isinstance(item, bool) for item in checks.values()):
        raise SessionError("human case result checks must be explicit booleans")
    value["notes"] = qa._text(value["notes"], "result notes", 4000)
    if value["status"] == "pass" and not all(checks.values()):
        raise SessionError("a passing human result requires every explicit check true")
    if value["status"] == "fail" and all(checks.values()):
        raise SessionError("a failing human result must identify at least one false check")
    return value, payload


@_locked_operation
def finish_case(
    *, inventory: Path, manifest: Path, result: Path, apply: bool,
) -> dict[str, Any]:
    session, session_bytes, workspace, inventory, manifest = _load_session(
        inventory, manifest
    )
    active = session["active_case"]
    human, result_bytes = _result(result, workspace, active["case_id"])
    if human["completed_at"] < active["started_at"]:
        raise SessionError("case completed_at precedes started_at")
    if not active["artifacts"]:
        raise SessionError("finish-case requires at least one captured evidence artifact")
    for artifact in active["artifacts"]:
        if not active["started_at"] <= artifact["captured_at"] <= human["completed_at"]:
            raise SessionError("captured evidence lies outside the explicit case interval")

    document, manifest_bytes = _validate_current_manifest(inventory, manifest)
    before_attestation = json.loads(
        json.dumps(document["hardware_qa"]["attestation"])
    )
    target = _case(document, active["case_id"])
    if target["status"] != "pending":
        raise SessionError("active case is no longer pending in the manifest")
    known_ids = {item["id"] for item in document["hardware_qa"]["artifacts"]}
    known_paths = {item["path"] for item in document["hardware_qa"]["artifacts"]}
    for artifact in active["artifacts"]:
        if artifact["id"] in known_ids or artifact["path"] in known_paths:
            raise SessionError("active artifact duplicates a manifest ID or path")
        qa._manifest_artifact(
            manifest.parent, artifact, len(document["hardware_qa"]["artifacts"])
        )
        document["hardware_qa"]["artifacts"].append(artifact)
    document["hardware_qa"]["artifacts"].sort(key=lambda item: item["id"])
    target.update({
        "status": human["status"],
        "started_at": active["started_at"],
        "completed_at": human["completed_at"],
        "rom_ids": active["rom_ids"],
        "controller_ids": active["controller_ids"],
        "checks": human["checks"],
        "artifact_ids": sorted(item["id"] for item in active["artifacts"]),
        "notes": human["notes"],
    })
    if document["hardware_qa"]["attestation"] != before_attestation:
        raise AssertionError("recorder changed human attestation authority")
    payload = _canonical_json(document)

    # The existing verifier is authoritative for pass selection, evidence
    # counts, exact labels, media identities, and schema compatibility.
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".finish-hardware-qa.", dir=manifest.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        try:
            qa.verify_manifest(temporary, inventory, require_pass=False)
        except ValueError as error:
            raise SessionError(f"completed case fails the hardware QA schema: {error}") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)

    prepared_finish = {
        "manifest_sha256": hashlib.sha256(payload).hexdigest(),
        "result_sha256": hashlib.sha256(result_bytes).hexdigest(),
    }
    if active["prepared_finish"] is not None and active["prepared_finish"] != prepared_finish:
        raise SessionError(
            "prepared finish does not match this exact result/final manifest"
        )

    prepared_session_bytes = session_bytes
    if apply and active["prepared_finish"] is None:
        active["prepared_finish"] = prepared_finish
        prepared_session_bytes = _canonical_json(session)
        _atomic_replace(
            _session_path(manifest),
            prepared_session_bytes,
            hashlib.sha256(session_bytes).hexdigest(),
        )
    if apply:
        _atomic_replace(
            manifest, payload, hashlib.sha256(manifest_bytes).hexdigest()
        )
        _unlink_exact(
            _session_path(manifest),
            hashlib.sha256(prepared_session_bytes).hexdigest(),
        )
    return document


@_locked_operation
def recover_session(
    *, inventory: Path, manifest: Path, apply: bool,
) -> dict[str, Any]:
    """Remove only a proven post-publication transaction sidecar."""

    session, session_bytes, _workspace, inventory, manifest = _load_session(
        inventory, manifest, allow_published=True
    )
    active = session["active_case"]
    prepared = active["prepared_finish"]
    if prepared is None:
        raise SessionError(
            "active session has no prepared finish; continue or finish the case"
        )
    current_manifest_bytes = manifest.read_bytes()
    current_manifest_sha256 = hashlib.sha256(current_manifest_bytes).hexdigest()
    if current_manifest_sha256 == active["manifest_sha256"]:
        raise SessionError(
            "prepared finish was not published; rerun finish-case with the exact result"
        )
    if current_manifest_sha256 != prepared["manifest_sha256"]:
        raise SessionError("manifest does not match the exact prepared finish")

    document, verified_manifest_bytes = _validate_current_manifest(inventory, manifest)
    if hashlib.sha256(verified_manifest_bytes).hexdigest() != prepared["manifest_sha256"]:
        raise SessionError("manifest changed while recovery was validating it")
    target = _case(document, active["case_id"])
    if target["status"] not in {"pass", "fail"}:
        raise SessionError("prepared case is not completed in the manifest")
    expected_case_fields = {
        "started_at": active["started_at"],
        "rom_ids": active["rom_ids"],
        "controller_ids": active["controller_ids"],
        "artifact_ids": sorted(item["id"] for item in active["artifacts"]),
    }
    if any(target[name] != value for name, value in expected_case_fields.items()):
        raise SessionError("published case does not match the prepared active session")
    manifest_artifacts = {
        item["id"]: item for item in document["hardware_qa"]["artifacts"]
    }
    if any(
        manifest_artifacts.get(artifact["id"]) != artifact
        for artifact in active["artifacts"]
    ):
        raise SessionError("published artifacts do not match the prepared active session")

    result = {
        "case_id": active["case_id"],
        "status": target["status"],
        "manifest_sha256": prepared["manifest_sha256"],
        "result_sha256": prepared["result_sha256"],
        "artifact_ids": expected_case_fields["artifact_ids"],
        "eligible": True,
    }
    if apply:
        if hashlib.sha256(manifest.read_bytes()).hexdigest() != prepared["manifest_sha256"]:
            raise SessionError("manifest changed immediately before recovery cleanup")
        _unlink_exact(
            _session_path(manifest), hashlib.sha256(session_bytes).hexdigest()
        )
    return result


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    subparsers = result.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--inventory", required=True, type=Path)
    common.add_argument("--manifest", required=True, type=Path)
    common.add_argument("--apply", action="store_true")

    start = subparsers.add_parser("start-case", parents=[common])
    start.add_argument("--case", required=True)
    start.add_argument("--started-at", required=True)
    start.add_argument("--rom-id", action="append", default=[])
    start.add_argument("--controller-id", action="append", default=[])

    ingest = subparsers.add_parser("ingest-artifact", parents=[common])
    ingest.add_argument("--source", required=True, type=Path)
    ingest.add_argument("--kind", required=True, choices=sorted(qa.ARTIFACT_KINDS))
    ingest.add_argument("--label", required=True)
    ingest.add_argument("--captured-at", required=True)

    finish = subparsers.add_parser("finish-case", parents=[common])
    finish.add_argument("--result", required=True, type=Path)
    subparsers.add_parser("recover-session", parents=[common])
    return result


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        if arguments.command == "start-case":
            session = start_case(
                inventory=arguments.inventory, manifest=arguments.manifest,
                case_id=arguments.case, started_at=arguments.started_at,
                rom_ids=arguments.rom_id, controller_ids=arguments.controller_id,
                apply=arguments.apply,
            )
            active = session["active_case"]
            action = "STARTED" if arguments.apply else "VALIDATED ONLY"
            print(f"{action}: {active['case_id']} at {active['started_at']}")
        elif arguments.command == "ingest-artifact":
            artifact = ingest_artifact(
                inventory=arguments.inventory, manifest=arguments.manifest,
                source=arguments.source, kind=arguments.kind,
                label=arguments.label, captured_at=arguments.captured_at,
                apply=arguments.apply,
            )
            action = "INGESTED" if arguments.apply else "VALIDATED ONLY"
            print(f"{action}: {artifact['id']} -> {artifact['path']}")
        elif arguments.command == "finish-case":
            active_document, _active_bytes = _strict_json(
                _session_path(arguments.manifest.expanduser().absolute()),
                "active hardware QA session",
            )
            active_case_id = active_document["active_case"]["case_id"]
            document = finish_case(
                inventory=arguments.inventory, manifest=arguments.manifest,
                result=arguments.result, apply=arguments.apply,
            )
            completed = next(
                item for item in document["hardware_qa"]["cases"]
                if item["id"] == active_case_id
            )
            action = "FINISHED" if arguments.apply else "VALIDATED ONLY"
            print(f"{action}: {completed['id']} explicit status={completed['status']}")
        else:
            recovered = recover_session(
                inventory=arguments.inventory,
                manifest=arguments.manifest,
                apply=arguments.apply,
            )
            action = "RECOVERED" if arguments.apply else "ELIGIBLE FOR RECOVERY"
            print(
                f"{action}: {recovered['case_id']} "
                f"explicit status={recovered['status']}"
            )
        if not arguments.apply:
            print("NO FILES CHANGED: rerun with --apply after reviewing the plan")
        print("HUMAN AUTHORITY PRESERVED: no check, status, reviewer, or attestation was inferred")
        return 0
    except (OSError, SessionError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
