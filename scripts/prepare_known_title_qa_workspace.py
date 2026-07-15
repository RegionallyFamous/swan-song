#!/usr/bin/env python3
"""Create and refresh a private, all-pending known-title QA workspace.

``prepare`` is read-only unless ``--apply`` is supplied.  Applying atomically
creates an owner-only directory outside the repository, copies the reviewed
17-case catalogue into a private manifest, stamps only the run identity, and
materializes deterministic evidence directories, a 124-slot evidence plan,
and an operator worksheet.  It never searches for or copies ROM, save, device,
or capture bytes and it never changes a result from ``pending``.

``worksheet`` validates an existing in-progress manifest and refreshes a
read-only Markdown report.  It does not edit the manifest or evidence.
"""

from __future__ import annotations

import argparse
import copy
import ctypes
import datetime as dt
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import shutil
import stat
import sys
import tempfile
from typing import Any

import known_title_compatibility as compatibility


ROOT = Path(__file__).resolve().parent.parent
CATALOGUE = ROOT / "known-title-compatibility.json"
PLAN_MAGIC = "SWAN_SONG_KNOWN_TITLE_EVIDENCE_PLAN_V1"
REFERENCE_SLOT_COUNT = 20
MODE_SLOT_COUNT = 104
TOTAL_SLOT_COUNT = REFERENCE_SLOT_COUNT + MODE_SLOT_COUNT
SUFFIXES = {
    "pocket_screenshot": ".png",
    "photo": ".jpg",
    "video": ".mp4",
    "save": ".sav",
    "log": ".txt",
    "reference_photo": ".jpg",
    "reference_video": ".mp4",
}


class WorkspaceError(ValueError):
    """A safe, actionable known-title workspace failure."""


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
            f"{label} must be a nonempty control-free string of at most "
            f"{maximum} characters"
        )
    return value


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
        raise WorkspaceError("known-title QA workspace must be outside the repository")
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
            pass
    finally:
        os.close(descriptor)


def _read_stable_regular(path: Path, where: str) -> tuple[bytes, tuple[int, int]]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise WorkspaceError(f"{where} must be a readable regular nonsymlink file") from error
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise WorkspaceError(f"{where} must be a single-link regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            payload = stream.read()
        return payload, (metadata.st_dev, metadata.st_ino)
    finally:
        os.close(descriptor)


def _parse_snapshot(payload: bytes, where: str) -> dict[str, Any]:
    def object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise WorkspaceError(f"{where} repeats member {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        raise WorkspaceError(f"{where} contains non-standard number {value}")

    try:
        document = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=object_without_duplicates,
            parse_constant=reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError) as error:
        raise WorkspaceError(f"invalid {where}: {error}") from error
    if not isinstance(document, dict):
        raise WorkspaceError(f"{where} must be a JSON object")
    return document


def _strict_catalogue() -> tuple[dict[str, Any], str]:
    payload, _identity = _read_stable_regular(CATALOGUE, "catalogue")
    document = _parse_snapshot(payload, "catalogue")
    compatibility.validate_catalogue(
        CATALOGUE,
        _document=document,
        _root=CATALOGUE.parent.resolve(strict=True),
    )
    return copy.deepcopy(document), hashlib.sha256(payload).hexdigest()


def _manifest_document(
    *,
    run_id: str,
    created_at: str,
    operator: str,
    core_commit: str,
    raw_rbf_sha256: str,
    pocket_hardware_revision: str,
    dock_hardware_revision: str,
) -> tuple[dict[str, Any], str]:
    document, catalogue_sha256 = _strict_catalogue()
    body = compatibility._body(document, "catalogue")
    run = body["run"]
    run.update(
        {
            "run_id": compatibility._id(run_id, "run-id"),
            "created_at": compatibility._utc(created_at, "created-at"),
            "operator": _text(operator, "operator", 255),
            "core_commit": core_commit,
            "raw_rbf_sha256": raw_rbf_sha256,
            "firmware_version": compatibility.REQUIRED_FIRMWARE,
            "pocket_hardware_revision": _text(
                pocket_hardware_revision, "pocket-hardware-revision", 255
            ),
            "dock_hardware_revision": _text(
                dock_hardware_revision, "dock-hardware-revision", 255
            ),
        }
    )
    compatibility._validate_run(body)
    # The catalogue validation above guarantees all other mutable fields are
    # still pending.  Assert that invariant at the publication boundary.
    if body["artifacts"] or any(
        case["owner_rom_sha256"] is not None
        or case["operator_steps"]
        or case["reference"] != {"source": None, "artifact_ids": [], "notes": None}
        or any(mode["status"] != "pending" for mode in case["modes"].values())
        for case in body["cases"]
    ):
        raise WorkspaceError("reviewed catalogue is not an all-pending template")
    return document, catalogue_sha256


def _planned_kind(kinds: list[str], mode: str) -> str:
    # A native Pocket screenshot is not a sensible Dock evidence suggestion.
    # Choose the accepted photo alternative for Dock where the catalogue
    # explicitly permits either kind.
    if mode == "dock" and "pocket_screenshot" in kinds and "photo" in kinds:
        return "photo"
    return kinds[0]


def evidence_slots(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the deterministic minimum evidence plan for this manifest."""

    body = compatibility._body(document, "manifest")
    slots: list[dict[str, Any]] = []
    for case in body["cases"]:
        case_id = case["id"]
        scenarios = case["scenarios"]
        if case["class"] == "commercial":
            for index, scenario in enumerate(scenarios, start=1):
                artifact_id = compatibility._id(
                    f"{case_id}-ref-{index:02d}", "reference artifact ID"
                )
                slots.append(
                    {
                        "id": artifact_id,
                        "case_id": case_id,
                        "owner": "reference",
                        "scenario_id": scenario["id"],
                        "kind": "reference_video",
                        "label": (
                            f"Original-hardware reference: {case_id} / "
                            f"{scenario['id']}"
                        ),
                        "path": (
                            PurePosixPath("evidence")
                            / case_id
                            / "reference"
                            / f"{artifact_id}.mp4"
                        ).as_posix(),
                    }
                )

        for mode in ("pocket", "dock"):
            counters: dict[str, int] = {}
            scenario_video = 0
            for requirement in case["mode_evidence_requirements"]:
                kind = _planned_kind(requirement["kinds"], mode)
                for _unused in range(requirement["minimum"]):
                    counters[kind] = counters.get(kind, 0) + 1
                    number = counters[kind]
                    artifact_id = compatibility._id(
                        f"{case_id}-{mode}-{kind}-{number:02d}",
                        "mode artifact ID",
                    )
                    scenario_id = None
                    if kind == "video" and scenario_video < len(scenarios):
                        scenario_id = scenarios[scenario_video]["id"]
                        scenario_video += 1
                        label = f"{mode.title()} scenario: {case_id} / {scenario_id}"
                    elif kind == "log":
                        label = f"{mode.title()} run log: {case_id}"
                    elif kind == "save":
                        label = f"{mode.title()} save snapshot {number:02d}: {case_id}"
                    else:
                        label = f"{mode.title()} observation {number:02d}: {case_id}"
                    slots.append(
                        {
                            "id": artifact_id,
                            "case_id": case_id,
                            "owner": mode,
                            "scenario_id": scenario_id,
                            "kind": kind,
                            "label": label,
                            "path": (
                                PurePosixPath("evidence")
                                / case_id
                                / mode
                                / f"{artifact_id}{SUFFIXES[kind]}"
                            ).as_posix(),
                        }
                    )

    ids = [slot["id"] for slot in slots]
    paths = [slot["path"] for slot in slots]
    if len(ids) != len(set(ids)) or len(paths) != len(set(paths)):
        raise WorkspaceError("deterministic evidence plan contains a collision")
    reference_count = sum(slot["owner"] == "reference" for slot in slots)
    if (
        reference_count != REFERENCE_SLOT_COUNT
        or len(slots) - reference_count != MODE_SLOT_COUNT
        or len(slots) != TOTAL_SLOT_COUNT
    ):
        raise WorkspaceError("reviewed evidence slot totals changed")
    return slots


def _plan_document(document: dict[str, Any], catalogue_sha256: str) -> dict[str, Any]:
    body = document["known_title_compatibility"]
    return {
        "known_title_evidence_plan": {
            "magic": PLAN_MAGIC,
            "run_id": body["run"]["run_id"],
            "catalogue_sha256": catalogue_sha256,
            "slots": evidence_slots(document),
        }
    }


def _requirements_text(case: dict[str, Any]) -> str:
    return "; ".join(
        f"{requirement['minimum']} x {'/'.join(requirement['kinds'])}"
        for requirement in case["mode_evidence_requirements"]
    )


def _render_operator_worksheet(
    document: dict[str, Any], manifest_path: Path, slots: list[dict[str, Any]]
) -> str:
    body = compatibility._body(document, "manifest")
    registered = {item["id"] for item in body["artifacts"]}
    status = {name: 0 for name in ("pass", "fail", "pending")}
    for case in body["cases"]:
        for mode in case["modes"].values():
            status[mode["status"]] += 1

    by_owner: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for slot in slots:
        by_owner.setdefault((slot["case_id"], slot["owner"]), []).append(slot)

    lines = [
        "# Known-title Pocket/Dock physical QA operator worksheet",
        "",
        "> Read-only report generated from the strict private manifest. Checking ",
        "> boxes here does not update evidence, results, or attestation. Record ",
        "> physical observations only in `manifest.json`; this helper never passes a case.",
        "",
        f"- Run ID: `{body['run']['run_id']}`",
        f"- Firmware: `{body['run']['firmware_version']}`",
        f"- Core commit: `{body['run']['core_commit']}`",
        f"- Raw RBF SHA-256: `{body['run']['raw_rbf_sha256']}`",
        f"- Manifest: `{manifest_path.absolute()}`",
        f"- Evidence root: `{manifest_path.absolute().parent / 'evidence'}`",
        f"- Progress: **{status['pass']} pass / {status['fail']} fail / "
        f"{status['pending']} pending** (34 required device modes)",
        f"- Deterministic minimum plan: **{len(slots)} files** "
        f"({REFERENCE_SLOT_COUNT} original-hardware references + "
        f"{MODE_SLOT_COUNT} Pocket/Dock artifacts)",
        "",
        "Suggested IDs, labels, and paths are unregistered slots until the operator "
        "captures the real file, records its UTC time/size/SHA-256 in `artifacts`, "
        "and references its ID from the matching result. Never create placeholder "
        "media or infer a result from simulation.",
        "",
    ]

    for index, case in enumerate(body["cases"], start=1):
        lines.extend(
            [
                f"## {index:02d}. `{case['id']}` — {case['title']}",
                "",
                f"- Class/system: `{case['class']}` / `{case['system']}`",
                f"- Owner ROM SHA-256: `{case['owner_rom_sha256'] or 'not set'}`",
                f"- Exact operator steps: {len(case['operator_steps'])} recorded"
                + (" (required)" if case["operator_steps_required"] else ""),
                f"- Per-mode evidence minimum: {_requirements_text(case)}",
                f"- Reference requirement: {case['reference_requirement']}",
                "",
                "### Reviewed scenarios",
                "",
            ]
        )
        for scenario in case["scenarios"]:
            lines.extend(
                [
                    f"#### `{scenario['id']}`",
                    "",
                    "Preconditions:",
                    "",
                    *[f"- [ ] {entry}" for entry in scenario["preconditions"]],
                    "",
                    "Steps:",
                    "",
                    *[f"- [ ] {entry}" for entry in scenario["steps"]],
                    "",
                    f"Expected: {scenario['expected']}",
                    "",
                ]
            )

        reference_slots = by_owner.get((case["id"], "reference"), [])
        reference_artifacts = set(case["reference"]["artifact_ids"])
        lines.extend(["### Original-hardware reference plan", ""])
        if not reference_slots:
            lines.append(
                "Checked-in open fixture; set reference source to "
                "`checked_in_open_fixture` with no reference artifact."
            )
            lines.append("")
        else:
            lines.extend(
                [
                    "| Recorded | Suggested ID | Scenario | Kind | Label | Path |",
                    "|---|---|---|---|---|---|",
                ]
            )
            for slot in reference_slots:
                mark = (
                    "yes"
                    if slot["id"] in registered and slot["id"] in reference_artifacts
                    else "no"
                )
                lines.append(
                    f"| {mark} | `{slot['id']}` | `{slot['scenario_id']}` | "
                    f"`{slot['kind']}` | {slot['label']} | `{slot['path']}` |"
                )
            lines.append("")

        for mode in ("pocket", "dock"):
            result = case["modes"][mode]
            mode_artifacts = set(result["artifact_ids"])
            mode_slots = by_owner[(case["id"], mode)]
            lines.extend(
                [
                    f"### {mode.title()} — {result['status'].upper()}",
                    "",
                    f"- Started/completed: `{result['started_at'] or 'not set'}` / "
                    f"`{result['completed_at'] or 'not set'}`",
                    f"- Result notes: {result['notes'] or 'not set'}",
                    f"- Recorded artifact IDs: "
                    f"{', '.join(f'`{item}`' for item in result['artifact_ids']) or 'none'}",
                    "",
                    "| Recorded | Suggested ID | Kind | Scenario | Label | Path |",
                    "|---|---|---|---|---|---|",
                ]
            )
            for slot in mode_slots:
                mark = (
                    "yes"
                    if slot["id"] in registered and slot["id"] in mode_artifacts
                    else "no"
                )
                scenario = f"`{slot['scenario_id']}`" if slot["scenario_id"] else "—"
                lines.append(
                    f"| {mark} | `{slot['id']}` | `{slot['kind']}` | {scenario} | "
                    f"{slot['label']} | `{slot['path']}` |"
                )
            lines.append("")

    attestation = body["attestation"]
    lines.extend(
        [
            "## Final human attestation",
            "",
            "> Complete only after all 34 physical mode results and every artifact "
            "> have been independently reviewed.",
            "",
            f"- [{'x' if attestation['physical_hardware_observed'] else ' '}] "
            "`physical_hardware_observed`",
            f"- [{'x' if attestation['results_not_inferred_from_simulation'] else ' '}] "
            "`results_not_inferred_from_simulation`",
            f"- Reviewer: `{attestation['reviewer'] or 'not set'}`",
            f"- Reviewed at: `{attestation['reviewed_at'] or 'not set'}`",
            "",
        ]
    )
    return "\n".join(lines)


def render_operator_worksheet(
    manifest_path: Path, catalogue_path: Path = CATALOGUE
) -> str:
    """Validate and render a report without mutating manifest or evidence."""

    manifest_path = manifest_path.absolute()
    catalogue_path = catalogue_path.absolute()
    manifest_before, _manifest_identity = _read_stable_regular(manifest_path, "manifest")
    catalogue_before, _catalogue_identity = _read_stable_regular(catalogue_path, "catalogue")
    document = _parse_snapshot(manifest_before, "manifest")
    catalogue_document = _parse_snapshot(catalogue_before, "catalogue")
    compatibility.verify_manifest(
        catalogue_path,
        manifest_path,
        _catalogue_document=catalogue_document,
        _manifest_document=document,
        _catalogue_root=catalogue_path.parent.resolve(strict=True),
        _manifest_root=manifest_path.parent.resolve(strict=True),
        _catalogue_bytes=catalogue_before,
        _manifest_bytes=manifest_before,
    )
    return _render_operator_worksheet(
        document, manifest_path, evidence_slots(document)
    )


def write_operator_worksheet(
    manifest_path: Path, output_path: Path, catalogue_path: Path = CATALOGUE
) -> None:
    output_path = output_path.absolute()
    manifest_path = manifest_path.absolute()
    catalogue_path = catalogue_path.absolute()
    rendered = render_operator_worksheet(manifest_path, catalogue_path).encode("utf-8")
    protected = {
        _read_stable_regular(manifest_path, "manifest")[1],
        _read_stable_regular(catalogue_path, "catalogue")[1],
    }
    if output_path.is_symlink() or (output_path.exists() and not output_path.is_file()):
        raise WorkspaceError(f"operator worksheet output must be a regular file: {output_path}")
    parent_metadata = output_path.parent.lstat()
    if not stat.S_ISDIR(parent_metadata.st_mode):
        raise WorkspaceError(
            f"operator worksheet parent must be a real directory: {output_path.parent}"
        )
    if output_path.exists():
        output_metadata = output_path.stat()
        if (output_metadata.st_dev, output_metadata.st_ino) in protected:
            raise WorkspaceError("operator worksheet must not replace manifest or catalogue")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output_path.name}.", dir=output_path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(rendered)
            stream.flush()
            os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.replace(temporary, output_path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _next_steps(destination: Path) -> bytes:
    manifest = destination / "manifest.json"
    worksheet = destination / "operator-worksheet.md"
    helper = shlex.quote(str(ROOT / "scripts" / "prepare_known_title_qa_workspace.py"))
    verifier = shlex.quote(str(ROOT / "scripts" / "known_title_compatibility.py"))
    manifest_arg = shlex.quote(str(manifest))
    worksheet_arg = shlex.quote(str(worksheet))
    return f"""# Swan Song known-title physical QA workspace

This directory is private working material. Do not add commercial ROMs, saves,
device data, or captures to Git.

Already prepared:

- `manifest.json`, with the reviewed 17 cases and all 34 modes still pending;
- `evidence-plan.json`, with 20 original-hardware reference slots and 104
  Pocket/Dock evidence slots;
- `operator-worksheet.md`, a read-only checklist and filename plan;
- empty case/mode evidence directories.

Next:

1. Record owner-computed commercial ROM SHA-256 values and exact operator steps.
2. Capture real files at the suggested paths. Add their IDs, UTC capture times,
   byte sizes, and SHA-256 values to `manifest.json`.
3. Record each physical mode result and notes. A failure remains `fail`; an
   incomplete run remains `pending`.
4. Refresh the worksheet without changing results:

```sh
python3 {helper} worksheet --manifest {manifest_arg} --output {worksheet_arg}
```

5. Validate in progress, then require complete/pass only at the appropriate
   human review gates:

```sh
python3 {verifier} --manifest {manifest_arg}
python3 {verifier} --manifest {manifest_arg} --require-complete
python3 {verifier} --manifest {manifest_arg} --require-pass
```

The helper never creates placeholder media, registers evidence, sets checks,
changes a result, or completes an attestation.
""".encode("utf-8")


def plan(
    *,
    output: Path,
    run_id: str,
    operator: str,
    core_commit: str,
    raw_rbf_sha256: str,
    pocket_hardware_revision: str,
    dock_hardware_revision: str,
    created_at: str,
) -> tuple[Path, bytes, bytes, bytes, bytes, tuple[PurePosixPath, ...]]:
    destination = _safe_output(output)
    document, catalogue_sha256 = _manifest_document(
        run_id=run_id,
        created_at=created_at,
        operator=operator,
        core_commit=core_commit,
        raw_rbf_sha256=raw_rbf_sha256,
        pocket_hardware_revision=pocket_hardware_revision,
        dock_hardware_revision=dock_hardware_revision,
    )
    manifest = (json.dumps(document, indent=2, ensure_ascii=True) + "\n").encode(
        "utf-8"
    )
    plan_document = _plan_document(document, catalogue_sha256)
    evidence_plan = (
        json.dumps(plan_document, indent=2, ensure_ascii=True) + "\n"
    ).encode("utf-8")
    slots = plan_document["known_title_evidence_plan"]["slots"]
    worksheet = _render_operator_worksheet(
        document, destination / "manifest.json", slots
    ).encode("utf-8")
    instructions = _next_steps(destination)
    directories = tuple(
        sorted(
            {
                PurePosixPath("evidence"),
                *[PurePosixPath(slot["path"]).parent for slot in slots],
            },
            key=lambda path: path.as_posix(),
        )
    )
    return (
        destination,
        manifest,
        evidence_plan,
        worksheet,
        instructions,
        directories,
    )


def apply(
    destination: Path,
    manifest: bytes,
    evidence_plan: bytes,
    worksheet: bytes,
    instructions: bytes,
    directories: tuple[PurePosixPath, ...],
) -> None:
    _safe_output(destination)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent)
    )
    published = False
    try:
        os.chmod(temporary, 0o700)
        for relative in directories:
            directory = temporary / Path(relative)
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(directory, 0o700)

        files = {
            Path("manifest.json"): manifest,
            Path("evidence-plan.json"): evidence_plan,
            Path("operator-worksheet.md"): worksheet,
            Path("NEXT_STEPS.md"): instructions,
            Path(".gitignore"): b"*\n!.gitignore\n",
        }
        for relative, payload in files.items():
            target = temporary / relative
            descriptor = os.open(
                target,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0),
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
    commands = result.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="plan or create an all-pending workspace")
    prepare.add_argument("--output", required=True, type=Path)
    prepare.add_argument("--run-id", required=True)
    prepare.add_argument("--operator", required=True)
    prepare.add_argument("--core-commit", required=True)
    prepare.add_argument("--raw-rbf-sha256", required=True)
    prepare.add_argument("--pocket-hardware-revision", required=True)
    prepare.add_argument("--dock-hardware-revision", required=True)
    prepare.add_argument("--apply", action="store_true")

    worksheet = commands.add_parser("worksheet", help="refresh a read-only operator report")
    worksheet.add_argument("--manifest", required=True, type=Path)
    worksheet.add_argument("--catalogue", type=Path, default=CATALOGUE)
    worksheet.add_argument("--output", type=Path)
    return result


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        if arguments.command == "worksheet":
            if arguments.output is None:
                print(
                    render_operator_worksheet(
                        arguments.manifest, arguments.catalogue
                    ),
                    end="",
                )
            else:
                write_operator_worksheet(
                    arguments.manifest, arguments.output, arguments.catalogue
                )
                print(f"WROTE read-only operator worksheet: {arguments.output}")
                print("NO RESULTS CHANGED: manifest and evidence remain operator-owned")
            return 0

        created_at = _utc_now()
        planned = plan(
            output=arguments.output,
            run_id=arguments.run_id,
            operator=arguments.operator,
            core_commit=arguments.core_commit,
            raw_rbf_sha256=arguments.raw_rbf_sha256,
            pocket_hardware_revision=arguments.pocket_hardware_revision,
            dock_hardware_revision=arguments.dock_hardware_revision,
            created_at=created_at,
        )
        destination, _manifest, evidence_plan, _worksheet, _instructions, _dirs = planned
        plan_body = json.loads(evidence_plan)["known_title_evidence_plan"]
        print(f"Swan Song known-title QA workspace: {destination}")
        print(f"Run: {arguments.run_id}; created: {created_at}")
        print(
            f"Evidence plan: {len(plan_body['slots'])} pending slots "
            f"({REFERENCE_SLOT_COUNT} reference, {MODE_SLOT_COUNT} Pocket/Dock)"
        )
        print("Private inputs copied: none; passing results created: none")
        if not arguments.apply:
            print("VALIDATED ONLY — no files written; rerun with --apply to create it")
            return 0
        apply(*planned)
        print("CREATED owner-only all-pending workspace")
        print(f"Next: read {destination / 'NEXT_STEPS.md'}")
        return 0
    except (WorkspaceError, ValueError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
