#!/usr/bin/env python3
"""Create an owner-only, local Pocket/Dock QA workspace.

The default operation is a read-only plan.  ``--apply`` atomically creates a
private directory outside the repository, materializes the reviewed inventory
template, and generates the open 896 KiB compact-ROM probe.  It never copies,
searches for, or downloads BIOS, firmware, commercial ROM, save, or capture
bytes.
"""

from __future__ import annotations

import argparse
import ctypes
import datetime as dt
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import sys
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "hardware-qa-inventory.example.json"
SIMULATOR_TOOLS = ROOT / "sim" / "verilator"
ID_RE = re.compile(r"[a-z0-9][a-z0-9_.-]{0,62}\Z")
UTC_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")
EXPECTED_MAGIC = "SWAN_SONG_HARDWARE_QA_INVENTORY_V2"
EXPECTED_PROBE_SHA256 = (
    "b4a2c985906ac04c6622080bb1f1f3ac4b3895784c5594f4ba97cd45e6935979"
)
EXPECTED_PERSISTENCE_OUTPUT_SHA256 = {
    "sram_persistence_boot_color.bin": "a0721e517f41a503351bbbfda064b79885d14cf7f6a235265d245a023755ed43",
    "sram_persistence_boot_mono.bin": "01048b2f2f4e512eea6859842b943405f2f897361437018316ac53de98c97324",
    "sram_type03_persistence.ws": "1c04f468ac445616e9613b08dd874aadc83bc214f9b192f777e845019b4c4ccb",
    "sram_type03_persistence.wsc": "1ea9323cf4300d5667eb10bde448c7b013e82d39d2e92757d792377bb6a856a1",
    "sram_type04_persistence.ws": "e44785c8c117bd10519a96a699512c16bd23889f206b763f95f1c1e40c7b36c9",
    "sram_type04_persistence.wsc": "b1c6d141ddd59871806e76a7ab9b5e5c2a2b2ae768bcb41eac37ad53cda73d94",
    "sram_type05_persistence.ws": "42b82002ee3f5f82c12b6ceb4d34015d36490d1321594c77d785e669c0749311",
    "sram_type05_persistence.wsc": "3eb97b9f40c22c097772a7c74c6c39d7fe1a913e3008237398431422b49cb1c2",
}


class WorkspaceError(ValueError):
    """A safe, actionable workspace-preparation failure."""


def _utc_now() -> str:
    return (
        dt.datetime.now(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _text(value: str, label: str, maximum: int) -> str:
    if not value or len(value) > maximum or any(ord(char) < 0x20 for char in value):
        raise WorkspaceError(
            f"{label} must be a nonempty control-free string of at most {maximum} characters"
        )
    return value


def _created_at(value: str) -> str:
    if not UTC_RE.fullmatch(value):
        raise WorkspaceError("created-at must be UTC YYYY-MM-DDTHH:MM:SSZ")
    try:
        dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise WorkspaceError("created-at is not a real UTC timestamp") from error
    return value


def _strict_template() -> dict[str, Any]:
    def object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise WorkspaceError(f"inventory template repeats member {key!r}")
            result[key] = value
        return result

    if TEMPLATE.is_symlink() or not TEMPLATE.is_file():
        raise WorkspaceError(f"inventory template is missing: {TEMPLATE}")
    try:
        document = json.loads(
            TEMPLATE.read_text(encoding="utf-8"),
            object_pairs_hook=object_without_duplicates,
        )
        body = document["hardware_qa_inventory"]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise WorkspaceError("inventory template is not the reviewed JSON envelope") from error
    if not isinstance(body, dict) or body.get("magic") != EXPECTED_MAGIC:
        raise WorkspaceError("inventory template magic is not the reviewed V2 contract")
    return document


def _safe_output(output: Path) -> Path:
    output = output.expanduser().absolute()
    try:
        repository = ROOT.resolve(strict=True)
        parent = output.parent.resolve(strict=True)
    except OSError as error:
        raise WorkspaceError("output parent must be an existing directory") from error
    if output.name in {"", ".", ".."}:
        raise WorkspaceError("output must name a new directory")
    if output.exists() or output.is_symlink():
        raise WorkspaceError(f"output already exists: {output}")
    parent_info = output.parent.lstat()
    if stat.S_ISLNK(parent_info.st_mode) or not stat.S_ISDIR(parent_info.st_mode):
        raise WorkspaceError("output parent must be a real nonsymlink directory")
    resolved_output = parent / output.name
    if resolved_output == repository or repository in resolved_output.parents:
        raise WorkspaceError("hardware QA workspace must be outside the repository")
    return resolved_output


def _rename_noreplace(parent: Path, source_name: str, destination_name: str) -> None:
    """Atomically publish a sibling directory without replacing any inode."""

    libc = ctypes.CDLL(None, use_errno=True)
    descriptor = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        source = os.fsencode(source_name)
        destination = os.fsencode(destination_name)
        function = None
        flags = 0
        if sys.platform == "darwin" and hasattr(libc, "renameatx_np"):
            function = libc.renameatx_np
            flags = 0x00000004  # RENAME_EXCL
        elif hasattr(libc, "renameat2"):
            function = libc.renameat2
            flags = 1  # RENAME_NOREPLACE
        if function is None:
            raise WorkspaceError(
                "platform lacks atomic no-clobber directory publication"
            )
        function.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        function.restype = ctypes.c_int
        if function(descriptor, source, descriptor, destination, flags) != 0:
            number = ctypes.get_errno()
            unavailable = {
                errno.ENOSYS,
                errno.EINVAL,
                getattr(errno, "ENOTSUP", errno.EINVAL),
                getattr(errno, "EOPNOTSUPP", errno.EINVAL),
            }
            if number in unavailable:
                raise WorkspaceError(
                    "filesystem lacks atomic no-clobber directory publication"
                )
            raise OSError(number, os.strerror(number), str(parent / destination_name))
        try:
            os.fsync(descriptor)
        except OSError:
            # Publication already succeeded atomically. Directory fsync is not
            # available on every supported filesystem.
            pass
    finally:
        os.close(descriptor)


def _inventory(
    *, run_id: str, operator_name: str, operator_organization: str, created_at: str
) -> bytes:
    if not ID_RE.fullmatch(run_id):
        raise WorkspaceError(f"run-id must match {ID_RE.pattern}")
    document = _strict_template()
    body = document["hardware_qa_inventory"]
    body["run_id"] = run_id
    body["created_at"] = _created_at(created_at)
    body["operator"] = {
        "name": _text(operator_name, "operator-name", 80),
        "organization": _text(
            operator_organization, "operator-organization", 120
        ),
    }
    return (json.dumps(document, indent=2, ensure_ascii=True) + "\n").encode("utf-8")


def _probe_bytes() -> bytes:
    sys.path.insert(0, str(SIMULATOR_TOOLS))
    try:
        import generate_non_power_two_probe as probe  # type: ignore[import-not-found]

        payload = probe.image()
        probe.validate(payload)
    except (ImportError, OSError, ValueError) as error:
        raise WorkspaceError(f"could not generate reviewed compact probe: {error}") from error
    finally:
        try:
            sys.path.remove(str(SIMULATOR_TOOLS))
        except ValueError:
            pass
    digest = hashlib.sha256(payload).hexdigest()
    if digest != EXPECTED_PROBE_SHA256:
        raise WorkspaceError(
            f"generated compact probe identity changed: expected {EXPECTED_PROBE_SHA256}, got {digest}"
        )
    return payload


def _persistence_probe_files() -> dict[Path, bytes]:
    sys.path.insert(0, str(SIMULATOR_TOOLS))
    try:
        import generate_sram_persistence_probes as probes  # type: ignore[import-not-found]

        bundle = probes.bundle_files()
    except (ImportError, OSError, ValueError) as error:
        raise WorkspaceError(
            f"could not generate reviewed SRAM persistence probes: {error}"
        ) from error
    finally:
        try:
            sys.path.remove(str(SIMULATOR_TOOLS))
        except ValueError:
            pass
    for name, expected in EXPECTED_PERSISTENCE_OUTPUT_SHA256.items():
        if name not in bundle:
            raise WorkspaceError(f"SRAM persistence bundle is missing {name}")
        observed = hashlib.sha256(bundle[name]).hexdigest()
        if observed != expected:
            raise WorkspaceError(
                f"generated {name} identity changed: expected {expected}, got {observed}"
            )
    return {
        Path("private/sram-persistence-probes") / name: payload
        for name, payload in bundle.items()
    }


def _next_steps(output: Path) -> bytes:
    inventory = output / "inventory.json"
    manifest = output / "evidence" / "manifest.json"
    worksheet = output / "evidence" / "operator-worksheet.md"
    qa_script = shlex.quote(str(ROOT / "scripts" / "pocket_hardware_qa.py"))
    diagnostic_script = shlex.quote(
        str(ROOT / "scripts" / "build_chip32_pending_diagnostic.py")
    )
    inventory_arg = shlex.quote(str(inventory))
    manifest_arg = shlex.quote(str(manifest))
    worksheet_arg = shlex.quote(str(worksheet))
    diagnostic_output = shlex.quote(str(output / "chip32-pending-diagnostic"))
    return f"""# Swan Song physical QA workspace

This directory is private working material. Do not add it to Git or upload its
firmware, BIOS, ROM, device-ID, save, or capture files.

Already prepared:

- `inventory.json` with the run/operator identity supplied to the scaffold;
- `private/compact-896k.wsc`, the reviewed open generated probe;
- `private/sram-persistence-probes/`, reviewed open save probes for footer
  types 0x03, 0x04, and 0x05 on mono and Color;
- empty `sd/`, `build/output_files/`, and `evidence/` directories.

Next:

1. Replace every remaining `Replace...` value in `{inventory}`.
2. Put the official Pocket 2.6.0 update at `private/pocket_firmware.bin`.
3. Put stable device identifiers in `private/pocket-device-id.txt` and
   `private/dock-device-id.txt`.
4. Put your own 4 KiB `bw.rom`, 8 KiB `color.rom`, and selected `.ws`/`.wsc`
   files at the paths named by `inventory.json`.
5. Put the exact raw Quartus output at `build/output_files/ap_core.rbf` and
   stage the matching package under `sd/`.
6. Materialize the reviewed QA-only stuck-pending Chip32 diagnostic. It is for
   the negative-path calibration only and must never replace the signed release package:

```sh
python3 {diagnostic_script} \
  --output {diagnostic_output} \
  --apply
```

7. Generate the pending evidence and read-only operator worksheet:

```sh
python3 {qa_script} generate \\
  --inventory {inventory_arg} \\
  --output {manifest_arg}

python3 {qa_script} worksheet \\
  --inventory {inventory_arg} \\
  --manifest {manifest_arg} \\
  --output {worksheet_arg}
```

The generator intentionally fails until all required private inputs and
placeholders are complete. It never turns pending cases into passes.
""".encode("utf-8")


def plan(
    *,
    output: Path,
    run_id: str,
    operator_name: str,
    operator_organization: str,
    created_at: str,
) -> tuple[Path, bytes, bytes, dict[Path, bytes], bytes]:
    destination = _safe_output(output)
    inventory = _inventory(
        run_id=run_id,
        operator_name=operator_name,
        operator_organization=operator_organization,
        created_at=created_at,
    )
    probe = _probe_bytes()
    persistence_probes = _persistence_probe_files()
    instructions = _next_steps(destination)
    return destination, inventory, probe, persistence_probes, instructions


def apply(
    destination: Path,
    inventory: bytes,
    probe: bytes,
    persistence_probes: dict[Path, bytes],
    instructions: bytes,
) -> None:
    # Recheck immediately before mutation; publication is a single rename.
    _safe_output(destination)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent)
    )
    published = False
    try:
        os.chmod(temporary, 0o700)
        for relative in (
            Path("private"),
            Path("evidence"),
            Path("sd"),
            Path("build"),
            Path("build/output_files"),
        ):
            directory = temporary / relative
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(directory, 0o700)

        files = {
            Path("inventory.json"): inventory,
            Path("private/compact-896k.wsc"): probe,
            Path("NEXT_STEPS.md"): instructions,
            Path(".gitignore"): b"*\n!.gitignore\n",
            **persistence_probes,
        }
        for relative, payload in files.items():
            target = temporary / relative
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(target.parent, 0o700)
            descriptor = os.open(
                target,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            try:
                with os.fdopen(descriptor, "wb", closefd=False) as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(descriptor)
            finally:
                os.close(descriptor)
        _rename_noreplace(destination.parent, temporary.name, destination.name)
        published = True
    except BaseException:
        if not published:
            shutil.rmtree(temporary, ignore_errors=True)
        raise


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--output", required=True, type=Path)
    result.add_argument("--run-id", required=True)
    result.add_argument("--operator-name", required=True)
    result.add_argument("--operator-organization", required=True)
    result.add_argument("--apply", action="store_true")
    return result


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        created_at = _utc_now()
        destination, inventory, probe, persistence_probes, instructions = plan(
            output=arguments.output,
            run_id=arguments.run_id,
            operator_name=arguments.operator_name,
            operator_organization=arguments.operator_organization,
            created_at=created_at,
        )
        print(f"Swan Song hardware QA workspace: {destination}")
        print(f"Run: {arguments.run_id}; created: {created_at}")
        print(f"Open probe: {len(probe)} bytes, SHA-256 {hashlib.sha256(probe).hexdigest()}")
        print("Private inputs copied: none")
        if not arguments.apply:
            print("VALIDATED ONLY — no files written; rerun with --apply to create it")
            return 0
        apply(destination, inventory, probe, persistence_probes, instructions)
        print("CREATED owner-only workspace and pending inventory template")
        print(f"Next: read {destination / 'NEXT_STEPS.md'}")
        return 0
    except (WorkspaceError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
