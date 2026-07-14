#!/usr/bin/env python3
"""Discover the tracked Quartus closure under Swan Song's static grammar.

Quartus QSF and QIP files use Tcl syntax, but this offline review deliberately
does not try to evaluate Tcl.  It accepts only the literal, one-command-per-line
assignment forms used by this project and rejects indirection or substitution.
Likewise, bound HDL must not acquire additional inputs through includes or
runtime file loads.  Completeness is therefore exact under this enforced static
grammar rather than a claim to understand arbitrary Tcl or HDL preprocessing.
"""

from __future__ import annotations

import errno
import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess
from typing import Callable, Iterable


MAGIC = "SWAN_SONG_QUARTUS_SOURCE_CLOSURE_V1"
MAX_ASSIGNMENT_FILE_BYTES = 8 * 1024 * 1024
MAX_SOURCE_FILE_BYTES = 64 * 1024 * 1024
PROJECT_FILES = (
    "src/fpga/ap_core.qpf",
    "src/fpga/ap_core.qsf",
    "src/fpga/ap_core_assignment_defaults.qdf",
)
ASSIGNMENT = re.compile(
    r"^\s*set_global_assignment"
    r"(?:\s+-library\s+(?:\"[^\"]*\"|\S+))?"
    r"\s+-name\s+([A-Z0-9_]+)\s+(.+?)\s*$",
    re.IGNORECASE,
)
FILE_JOIN = re.compile(
    r'^\[file join \$::quartus\(qip_path\) "([^"\r\n]+)"\]$'
)
LITERAL_READ_SDC = re.compile(r'^\s*read_sdc\s+"([^"\r\n]+)"\s*$')
SDC_INDIRECT_COMMAND = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(source|read_[A-Za-z0-9_]+|file|open|glob|eval|uplevel|subst)"
    r"(?![A-Za-z0-9_])"
)
GLOBAL_ASSIGNMENT_NAME = re.compile(
    r"(?:^|\s)-name\s+([A-Z0-9_]+)(?:\s|$)", re.IGNORECASE
)
FILE_ASSIGNMENT_NAME = re.compile(
    r"(?:^|\s)-name\s+([A-Z0-9_]*_FILE)(?:\s|$)", re.IGNORECASE
)
STATIC_COMMAND = re.compile(
    r"^\s*(set_global_assignment|set_instance_assignment|set_location_assignment)"
    r"(?:\s|$)"
)
NUMERIC_BUS_INDEX = re.compile(r"\[[0-9]*\]")
HDL_FILE_ASSIGNMENTS = frozenset(
    ("SYSTEMVERILOG_FILE", "VERILOG_FILE", "VHDL_FILE")
)
SEARCH_PATH_ASSIGNMENTS = frozenset(
    ("SEARCH_PATH", "SEARCH_PATHS", "IP_SEARCH_PATH", "IP_SEARCH_PATHS", "USER_LIBRARIES")
)
BUILD_ID_CONSUMER = "src/fpga/apf/mf_datatable.v"
BUILD_ID_GENERATOR = "src/fpga/apf/build_id_gen.tcl"
BUILD_ID_GENERATOR_SHA256 = (
    "dfbf2ffd960f70d3511b3e3f59d4250f9692b2f287d60cbd30b18aa3356c4579"
)
BUILD_ID_MIF = "src/fpga/apf/build_id.mif"
DPRAM_SOURCE = "src/fpga/core/rtl/dpram.vhd"
INPUT_FILE_ASSIGNMENTS = {
    "HEX_FILE",
    "MIF_FILE",
    "PRE_FLOW_SCRIPT_FILE",
    "QIP_FILE",
    "SDC_FILE",
    "SIGNALTAP_FILE",
    "SIP_FILE",
    "SYSTEMVERILOG_FILE",
    "USE_SIGNALTAP_FILE",
    "VERILOG_FILE",
    "VHDL_FILE",
}
# These names end in _FILE but do not identify checked-in synthesis inputs.
NON_INPUT_FILE_ASSIGNMENTS = {
    "EDA_GENERATE_POWER_INPUT_FILE",
    "EDA_SIMULATION_VCD_OUTPUT_SIGNALS_TO_TCL_FILE",
    "EDA_SIMULATION_VCD_OUTPUT_TCL_FILE",
    "GENERATE_CONFIG_HEXOUT_FILE",
    "GENERATE_CONFIG_ISC_FILE",
    "GENERATE_CONFIG_JAM_FILE",
    "GENERATE_CONFIG_JBC_FILE",
    "GENERATE_CONFIG_SVF_FILE",
    "GENERATE_HEX_FILE",
    "GENERATE_ISC_FILE",
    "GENERATE_JAM_FILE",
    "GENERATE_JBC_FILE",
    "GENERATE_PMSF_FILE",
    "GENERATE_RBF_FILE",
    "GENERATE_SVF_FILE",
    "GENERATE_TTF_FILE",
    "MERGE_HEX_FILE",
    "MISC_FILE",  # Generated-IP presentation metadata; not a synthesis input.
    "PHYSICAL_SYNTHESIS_LOG_FILE",
    "POWER_USE_INPUT_FILE",
    "SIMULATOR_GENERATE_POWERPLAY_VCD_FILE",
    "SIMULATOR_GENERATE_SIGNAL_ACTIVITY_FILE",
    "SLD_FILE",  # Quartus-generated System-Level Debug database path.
}


class ClosureError(ValueError):
    """The project input graph is unsafe, incomplete, or ambiguous."""


def _git(source_root: Path, *arguments: str) -> bytes:
    try:
        completed = subprocess.run(
            ("git", "-C", str(source_root), *arguments),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError as error:
        raise ClosureError(f"could not execute Git: {error}") from error
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ClosureError(
            f"Git {' '.join(arguments)} failed" + (f": {detail}" if detail else "")
        )
    return completed.stdout


def _require_repository_root(source_root: Path) -> Path:
    source_root = source_root.resolve(strict=True)
    git_root = Path(
        _git(source_root, "rev-parse", "--show-toplevel").decode("utf-8").strip()
    ).resolve(strict=True)
    if git_root != source_root:
        raise ClosureError(
            f"source root {source_root} is not the Git worktree root {git_root}"
        )
    return source_root


def _index_entries(source_root: Path) -> dict[str, str]:
    raw = _git(source_root, "ls-files", "-s", "-z")
    try:
        values = raw.decode("utf-8").split("\0")
    except UnicodeDecodeError as error:
        raise ClosureError("Git returned a non-UTF-8 tracked path") from error
    entries: dict[str, str] = {}
    for value in values:
        if not value:
            continue
        try:
            metadata, relative = value.split("\t", 1)
            mode, _object_id, stage = metadata.split(" ")
        except ValueError as error:
            raise ClosureError("Git returned a malformed index entry") from error
        if stage != "0" or relative in entries:
            raise ClosureError(f"Git index has an unmerged path: {relative}")
        entries[relative] = mode
    return entries


def _validate_relative(relative: str, label: str) -> tuple[str, ...]:
    candidate = Path(relative)
    if (
        candidate.is_absolute()
        or not candidate.parts
        or ".." in candidate.parts
        or candidate.as_posix() != relative
    ):
        raise ClosureError(f"{label} must be a normalized relative path: {relative!r}")
    return candidate.parts


def _metadata_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


class _WorktreeReader:
    """Read one stable nonsymlink worktree snapshot through anchored dirfds."""

    def __init__(self, source_root: Path) -> None:
        if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
            raise ClosureError("platform lacks fail-closed no-follow file reads")
        try:
            self._root_fd = os.open(
                source_root,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            )
        except OSError as error:
            raise ClosureError(
                f"could not anchor source-root descriptor {source_root}: {error}"
            ) from error
        self._cache: dict[str, bytes] = {}

    def __enter__(self) -> _WorktreeReader:
        return self

    def __exit__(self, *_args: object) -> None:
        os.close(self._root_fd)

    def read(self, relative: str, label: str, maximum: int) -> bytes:
        cached = self._cache.get(relative)
        if cached is not None:
            return cached
        parts = _validate_relative(relative, label)
        opened_directories: list[tuple[int, str, int, tuple[int, ...]]] = []
        descriptor: int | None = None
        parent_fd = self._root_fd
        try:
            for component in parts[:-1]:
                directory_fd = os.open(
                    component,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=parent_fd,
                )
                identity = _metadata_identity(os.fstat(directory_fd))
                opened_directories.append(
                    (parent_fd, component, directory_fd, identity)
                )
                parent_fd = directory_fd
            descriptor = os.open(
                parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd
            )
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise ClosureError(f"{label} is not a regular file: {relative}")
            if before.st_size > maximum:
                raise ClosureError(f"{label} exceeds {maximum} bytes: {relative}")
            blocks: list[bytes] = []
            total = 0
            while True:
                block = os.read(descriptor, min(1024 * 1024, maximum + 1 - total))
                if not block:
                    break
                blocks.append(block)
                total += len(block)
                if total > maximum:
                    raise ClosureError(f"{label} exceeds {maximum} bytes: {relative}")
            after = os.fstat(descriptor)
            if _metadata_identity(before) != _metadata_identity(after):
                raise ClosureError(f"{label} changed while reading: {relative}")
            final_path = os.stat(
                parts[-1], dir_fd=parent_fd, follow_symlinks=False
            )
            if (
                not stat.S_ISREG(final_path.st_mode)
                or final_path.st_dev != after.st_dev
                or final_path.st_ino != after.st_ino
            ):
                raise ClosureError(f"{label} path changed while reading: {relative}")
            for ancestor_fd, component, directory_fd, identity in opened_directories:
                current = os.stat(
                    component, dir_fd=ancestor_fd, follow_symlinks=False
                )
                if (
                    not stat.S_ISDIR(current.st_mode)
                    or _metadata_identity(current) != identity
                    or _metadata_identity(os.fstat(directory_fd)) != identity
                ):
                    raise ClosureError(
                        f"{label} directory changed while reading: {relative}"
                    )
            value = b"".join(blocks)
            self._cache[relative] = value
            return value
        except FileNotFoundError as error:
            raise ClosureError(f"{label} does not exist: {relative}") from error
        except OSError as error:
            if error.errno == errno.ELOOP:
                raise ClosureError(
                    f"{label} must not traverse a symlink: {relative}"
                ) from error
            raise ClosureError(
                f"could not safely read {label} {relative}: {error}"
            ) from error
        finally:
            if descriptor is not None:
                os.close(descriptor)
            for _parent, _component, directory_fd, _identity in reversed(
                opened_directories
            ):
                os.close(directory_fd)


def _commit_entries(
    source_root: Path, commit: str
) -> dict[str, tuple[str, str, str]]:
    raw = _git(source_root, "ls-tree", "-r", "-z", "--full-tree", commit)
    try:
        values = raw.decode("utf-8").split("\0")
    except UnicodeDecodeError as error:
        raise ClosureError("Git tree contains a non-UTF-8 path") from error
    entries: dict[str, tuple[str, str, str]] = {}
    for value in values:
        if not value:
            continue
        try:
            metadata, relative = value.split("\t", 1)
            mode, object_type, object_id = metadata.split(" ")
        except ValueError as error:
            raise ClosureError("Git returned a malformed tree entry") from error
        entries[relative] = (mode, object_type, object_id)
    return entries


class _CommitReader:
    """Read bounded immutable blobs from one exact reviewed Git tree."""

    def __init__(self, source_root: Path, commit: str) -> None:
        self._source_root = source_root
        object_type = _git(source_root, "cat-file", "-t", commit).decode().strip()
        if object_type != "commit":
            raise ClosureError("reviewed source identity is not a Git commit")
        self.entries = _commit_entries(source_root, commit)
        self._cache: dict[str, bytes] = {}

    def read(self, relative: str, label: str, maximum: int) -> bytes:
        cached = self._cache.get(relative)
        if cached is not None:
            return cached
        _validate_relative(relative, label)
        entry = self.entries.get(relative)
        if entry is None:
            raise ClosureError(f"{label} does not exist in reviewed commit: {relative}")
        mode, object_type, object_id = entry
        if mode not in {"100644", "100755"} or object_type != "blob":
            raise ClosureError(
                f"{label} is not a regular Git blob in reviewed commit: {relative}"
            )
        raw_size = _git(self._source_root, "cat-file", "-s", object_id)
        try:
            size = int(raw_size.decode("ascii").strip())
        except (UnicodeDecodeError, ValueError) as error:
            raise ClosureError(
                f"Git returned an invalid blob size: {relative}"
            ) from error
        if size > maximum:
            raise ClosureError(f"{label} exceeds {maximum} bytes: {relative}")
        value = _git(self._source_root, "cat-file", "blob", object_id)
        if len(value) != size:
            raise ClosureError(f"Git blob size changed while reading: {relative}")
        self._cache[relative] = value
        return value


Reader = Callable[[str, str, int], bytes]


def _require_regular_entry(entries: dict[str, str], relative: str, label: str) -> None:
    mode = entries.get(relative)
    if mode is None:
        raise ClosureError(f"{label} is not tracked by Git: {relative}")
    if mode not in {"100644", "100755"}:
        raise ClosureError(f"{label} is not a regular Git file: {relative}")


def _relative_path(source_root: Path, candidate: Path, label: str) -> str:
    try:
        relative = candidate.relative_to(source_root).as_posix()
    except ValueError as error:
        raise ClosureError(f"{label} escapes the source root: {candidate}") from error
    return relative


def _assignment_target(
    *,
    source_root: Path,
    fpga_root: Path,
    assignment_file: Path,
    kind: str,
    value: str,
    line_number: int,
) -> str:
    joined = FILE_JOIN.fullmatch(value)
    if joined is not None:
        raw = joined.group(1)
        base = assignment_file.parent
    else:
        if value.startswith('"') and value.endswith('"') and len(value) >= 2:
            raw = value[1:-1]
        else:
            raw = value
        if kind == "PRE_FLOW_SCRIPT_FILE":
            if ":" not in raw:
                raise ClosureError(
                    f"unsupported PRE_FLOW_SCRIPT_FILE at "
                    f"{assignment_file}:{line_number}"
                )
            executable, raw = raw.split(":", 1)
            if executable != "quartus_sh":
                raise ClosureError(
                    f"unsupported pre-flow executable {executable!r} at "
                    f"{assignment_file}:{line_number}"
                )
        base = (
            fpga_root
            if assignment_file.name == "ap_core.qsf"
            else assignment_file.parent
        )

    if (
        not raw
        or Path(raw).is_absolute()
        or ".." in Path(raw).parts
        or any(character in raw for character in "\0\r\n$\\{};")
        or "[" in raw
        or "]" in raw
    ):
        raise ClosureError(
            f"unsafe or unsupported {kind} value at "
            f"{assignment_file}:{line_number}: {raw!r}"
        )
    return _relative_path(source_root, base / raw, f"{kind} input")


def _read_assignments(data: bytes, path: Path) -> list[tuple[int, str, str]]:
    try:
        if b"\0" in data:
            raise ClosureError(f"NUL byte in Quartus assignment file: {path}")
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ClosureError(f"Quartus assignment file is not UTF-8: {path}") from error

    assignments: list[tuple[int, str, str]] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "\\" in line:
            raise ClosureError(
                f"Tcl continuations and escapes are not allowed in Quartus "
                f"assignment files: {path}:{line_number}"
            )
        if ";" in line:
            raise ClosureError(
                f"multiple or terminated Tcl commands are not allowed in Quartus "
                f"assignment files: {path}:{line_number}"
            )
        command = STATIC_COMMAND.match(line)
        if command is None:
            raise ClosureError(
                f"unsupported Tcl command in Quartus assignment file: "
                f"{path}:{line_number}"
            )

        match = ASSIGNMENT.fullmatch(line)
        joined_value = False
        if match is not None:
            joined_value = (
                path.suffix.lower() == ".qip"
                and match.group(1).upper().endswith("_FILE")
                and FILE_JOIN.fullmatch(match.group(2)) is not None
            )

        # Numeric bus subscripts are the only brackets used by the generated
        # instance/location assignments.  The sole command substitution is the
        # exact QIP-relative file-join form parsed below.
        static_probe = NUMERIC_BUS_INDEX.sub("", line)
        if joined_value:
            static_probe = static_probe.replace(match.group(2), "")
        if any(character in static_probe for character in "$[]"):
            raise ClosureError(
                f"Tcl substitution is not allowed in Quartus assignment files: "
                f"{path}:{line_number}"
            )

        in_quotes = False
        for character in line:
            if character == '"':
                in_quotes = not in_quotes
            elif character in "{}" and not in_quotes:
                raise ClosureError(
                    f"Tcl grouping is not allowed in Quartus assignment files: "
                    f"{path}:{line_number}"
                )
        if in_quotes:
            raise ClosureError(
                f"unterminated quote in Quartus assignment file: "
                f"{path}:{line_number}"
            )

        assignment_name = GLOBAL_ASSIGNMENT_NAME.search(line)
        normalized_name = (
            assignment_name.group(1).upper() if assignment_name is not None else None
        )
        if normalized_name in SEARCH_PATH_ASSIGNMENTS or (
            normalized_name is not None
            and normalized_name.endswith(("_SEARCH_PATH", "_SEARCH_PATHS"))
        ):
            raise ClosureError(
                f"unresolved Quartus search-path assignment {normalized_name} at "
                f"{path}:{line_number}"
            )

        if match is None:
            if command.group(1) == "set_global_assignment":
                file_name = FILE_ASSIGNMENT_NAME.search(line)
                if file_name is not None:
                    raise ClosureError(
                        "unsupported syntax for Quartus file assignment "
                        f"{file_name.group(1).upper()} at {path}:{line_number}"
                    )
            continue
        kind, value = match.groups()
        kind = kind.upper()
        if kind in NON_INPUT_FILE_ASSIGNMENTS:
            continue
        if kind in INPUT_FILE_ASSIGNMENTS:
            assignments.append((line_number, kind, value))
            continue
        if kind.endswith("_FILE"):
            raise ClosureError(
                f"unreviewed Quartus file assignment {kind} at {path}:{line_number}"
            )
    return assignments


def _without_verilog_comments(text: str) -> str:
    output: list[str] = []
    index = 0
    state = "code"
    while index < len(text):
        character = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if state == "code":
            if character == '"':
                state = "string"
                output.append(character)
            elif character == "/" and following == "/":
                state = "line-comment"
                output.extend((" ", " "))
                index += 1
            elif character == "/" and following == "*":
                state = "block-comment"
                output.extend((" ", " "))
                index += 1
            else:
                output.append(character)
        elif state == "string":
            output.append(character)
            if character == "\\" and following:
                output.append(following)
                index += 1
            elif character == '"':
                state = "code"
        elif state == "line-comment":
            if character in "\r\n":
                state = "code"
                output.append(character)
            else:
                output.append(" ")
        else:
            if character == "*" and following == "/":
                state = "code"
                output.extend((" ", " "))
                index += 1
            elif character in "\r\n":
                output.append(character)
            else:
                output.append(" ")
        index += 1
    if state == "block-comment":
        raise ClosureError("unterminated block comment in Quartus HDL input")
    return "".join(output)


def _without_vhdl_comments(text: str) -> str:
    output: list[str] = []
    for line in text.splitlines(keepends=True):
        in_string = False
        index = 0
        while index < len(line):
            character = line[index]
            following = line[index + 1] if index + 1 < len(line) else ""
            if character == '"':
                # A doubled quote is an escaped quote inside a VHDL string.
                if in_string and following == '"':
                    output.extend((character, following))
                    index += 2
                    continue
                in_string = not in_string
                output.append(character)
            elif not in_string and character == "-" and following == "-":
                output.extend("\n" if line.endswith("\n") else "")
                break
            else:
                output.append(character)
            index += 1
    return "".join(output)


def _without_hdl_comments(text: str, suffix: str) -> str:
    if suffix in {".v", ".sv", ".vh", ".svh"}:
        return _without_verilog_comments(text)
    return _without_vhdl_comments(text)


def _read_utf8_source(data: bytes, label: str) -> str:
    try:
        if b"\0" in data:
            raise ClosureError(f"NUL byte in Quartus source input: {label}")
        return data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ClosureError(f"Quartus source input is not UTF-8: {label}") from error


def _validate_indirect_hdl_inputs(
    paths: Iterable[str],
    hdl_assignments: dict[str, str],
    entries: dict[str, str],
    reader: Reader,
) -> None:
    """Reject HDL dependencies outside the statically discovered inventory."""

    paths = tuple(paths)
    hdl_text: dict[str, str] = {}
    for relative, kind in sorted(hdl_assignments.items()):
        dialect = ".vhd" if kind == "VHDL_FILE" else ".v"
        data = reader(relative, "Quartus HDL input", MAX_SOURCE_FILE_BYTES)
        text = _without_hdl_comments(_read_utf8_source(data, relative), dialect)
        hdl_text[relative] = text
        if re.search(r"`include\b", text):
            raise ClosureError(
                f"HDL includes require an exact resolver and are not allowed: {relative}"
            )
        if re.search(r"\$readmem(?:b|h)?\b", text, flags=re.IGNORECASE):
            raise ClosureError(
                f"unbound HDL runtime memory input is not allowed: {relative}"
            )

    init_occurrences: list[tuple[str, str]] = []
    for relative, text in hdl_text.items():
        for line in text.splitlines():
            if re.search(r"\binit_file\b", line, flags=re.IGNORECASE):
                init_occurrences.append((relative, " ".join(line.split())))

    expected_build_id = (
        BUILD_ID_CONSUMER,
        'altsyncram_component.init_file = "./apf/build_id.mif",',
    )
    expected_dpram = (DPRAM_SOURCE, "init_file => mem_init_file,")
    allowed = {expected_build_id, expected_dpram}
    unexpected = [item for item in init_occurrences if item not in allowed]
    if unexpected:
        raise ClosureError(
            "unreviewed or dynamic HDL init_file input: "
            + ", ".join(f"{relative}: {line}" for relative, line in unexpected)
        )

    if BUILD_ID_GENERATOR in paths:
        _require_regular_entry(
            entries, BUILD_ID_MIF, "generated build_id.mif contract"
        )
        reader(BUILD_ID_MIF, "generated build ID contract", MAX_SOURCE_FILE_BYTES)
        generator = reader(
            BUILD_ID_GENERATOR,
            "build ID pre-flow generator",
            MAX_SOURCE_FILE_BYTES,
        )
        if hashlib.sha256(generator).hexdigest() != BUILD_ID_GENERATOR_SHA256:
            raise ClosureError(
                "build_id.mif pre-flow generator changed outside its exact "
                "static source-identity contract"
            )

    if (
        expected_build_id in init_occurrences
        and BUILD_ID_GENERATOR not in paths
    ):
        raise ClosureError(
            "build_id.mif consumer is missing its bound pre-flow generator"
        )

    if expected_dpram in init_occurrences:
        dpram = hdl_text[DPRAM_SOURCE]
        if len(
            re.findall(
                r'mem_init_file\s*:\s*string\s*:=\s*" "',
                dpram,
                flags=re.IGNORECASE,
            )
        ) != 1:
            raise ClosureError(
                "inactive dpram_dif init_file generic no longer has one blank default"
            )
        references = sum(
            len(re.findall(r"\bdpram_dif\b", text, flags=re.IGNORECASE))
            for text in hdl_text.values()
        )
        if references != 2:
            raise ClosureError(
                "inactive dpram_dif init_file exception is referenced or changed"
            )


def _sdc_dependencies(
    data: bytes,
    *,
    source_root: Path,
    fpga_root: Path,
    relative: str,
) -> tuple[str, ...]:
    text = _read_utf8_source(data, relative)
    dependencies: list[str] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.lstrip().startswith(("$", "{*}$")):
            raise ClosureError(
                f"dynamic SDC command name is not allowed at "
                f"{relative}:{line_number}"
            )
        commands = list(SDC_INDIRECT_COMMAND.finditer(line))
        if not commands:
            continue
        match = LITERAL_READ_SDC.fullmatch(line)
        if (
            match is None
            or len(commands) != 1
            or commands[0].group(1).lower() != "read_sdc"
        ):
            names = ", ".join(item.group(1) for item in commands)
            raise ClosureError(
                f"dynamic or unsupported SDC file-loading command {names!r} at "
                f"{relative}:{line_number}"
            )
        raw = match.group(1)
        if (
            not raw
            or Path(raw).is_absolute()
            or ".." in Path(raw).parts
            or Path(raw).suffix.lower() != ".sdc"
            or any(character in raw for character in "\0\r\n$\\{};[]")
        ):
            raise ClosureError(
                f"unsafe or unsupported read_sdc path at "
                f"{relative}:{line_number}: {raw!r}"
            )
        dependencies.append(
            _relative_path(source_root, fpga_root / raw, "read_sdc input")
        )
    return tuple(dependencies)


def _discover_source_graph(
    source_root: Path, entries: dict[str, str], reader: Reader
) -> tuple[str, ...]:
    fpga_root = source_root / "src/fpga"
    discovered = set(PROJECT_FILES)
    hdl_assignments: dict[str, str] = {}
    queue = ["src/fpga/ap_core.qsf", "src/fpga/ap_core_assignment_defaults.qdf"]
    sdc_queue: list[str] = []
    parsed: set[str] = set()

    while queue:
        relative = queue.pop(0)
        if relative in parsed:
            continue
        assignment_file = source_root / relative
        data = reader(
            relative, "Quartus assignment input", MAX_ASSIGNMENT_FILE_BYTES
        )
        parsed.add(relative)
        for line_number, kind, value in _read_assignments(data, assignment_file):
            target = _assignment_target(
                source_root=source_root,
                fpga_root=fpga_root,
                assignment_file=assignment_file,
                kind=kind,
                value=value,
                line_number=line_number,
            )
            if kind == "PRE_FLOW_SCRIPT_FILE" and target != BUILD_ID_GENERATOR:
                raise ClosureError(
                    "only the exact reviewed build_id.mif pre-flow generator is "
                    f"allowed: {target}"
                )
            discovered.add(target)
            if kind in HDL_FILE_ASSIGNMENTS:
                previous = hdl_assignments.setdefault(target, kind)
                if previous != kind and {
                    previous,
                    kind,
                } != {"VERILOG_FILE", "SYSTEMVERILOG_FILE"}:
                    raise ClosureError(
                        f"Quartus HDL input has conflicting languages: {target}"
                    )
            if kind == "QIP_FILE":
                queue.append(target)
            elif kind == "SDC_FILE":
                sdc_queue.append(target)

    parsed_sdc: set[str] = set()
    while sdc_queue:
        relative = sdc_queue.pop(0)
        if relative in parsed_sdc:
            continue
        data = reader(relative, "Quartus SDC input", MAX_SOURCE_FILE_BYTES)
        parsed_sdc.add(relative)
        for target in _sdc_dependencies(
            data,
            source_root=source_root,
            fpga_root=fpga_root,
            relative=relative,
        ):
            discovered.add(target)
            sdc_queue.append(target)

    _validate_indirect_hdl_inputs(
        sorted(discovered), hdl_assignments, entries, reader
    )

    for relative in sorted(discovered):
        reader(relative, "Quartus source-closure input", MAX_SOURCE_FILE_BYTES)
        _require_regular_entry(entries, relative, "Quartus source-closure input")
    return tuple(sorted(discovered))


def discover_source_paths(source_root: Path) -> tuple[str, ...]:
    """Return the sorted closure from one safely read worktree snapshot."""

    source_root = _require_repository_root(source_root)
    entries = _index_entries(source_root)
    with _WorktreeReader(source_root) as worktree:
        return _discover_source_graph(source_root, entries, worktree.read)


def closure_identity(paths: Iterable[str]) -> dict[str, object]:
    """Describe the canonical newline-delimited path inventory."""

    ordered = tuple(paths)
    if not ordered or ordered != tuple(sorted(set(ordered))):
        raise ClosureError("Quartus source closure must be nonempty, unique, and sorted")
    encoded = "".join(f"{path}\n" for path in ordered).encode("utf-8")
    return {
        "algorithm": MAGIC,
        "paths": len(ordered),
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }


def current_bindings(source_root: Path) -> tuple[dict[str, str], dict[str, object]]:
    """Hash every current file in the complete discovered closure."""

    source_root = _require_repository_root(source_root)
    entries = _index_entries(source_root)
    with _WorktreeReader(source_root) as worktree:
        paths = _discover_source_graph(source_root, entries, worktree.read)
        bindings = {
            relative: hashlib.sha256(
                worktree.read(
                    relative, "Quartus source-closure input", MAX_SOURCE_FILE_BYTES
                )
            ).hexdigest()
            for relative in paths
        }
    return bindings, closure_identity(paths)


def committed_bindings(
    source_root: Path, commit: str
) -> tuple[dict[str, str], dict[str, object]]:
    """Hash closure bytes exactly as stored in one reviewed Git commit."""

    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise ClosureError("reviewed source commit must be a lowercase full 40-hex commit")
    source_root = _require_repository_root(source_root)
    committed = _CommitReader(source_root, commit)
    entries = {
        relative: metadata[0] for relative, metadata in committed.entries.items()
    }
    paths = _discover_source_graph(source_root, entries, committed.read)
    bindings = {
        relative: hashlib.sha256(
            committed.read(
                relative, "Quartus source-closure input", MAX_SOURCE_FILE_BYTES
            )
        ).hexdigest()
        for relative in paths
    }
    with _WorktreeReader(source_root) as worktree:
        for relative in paths:
            current = worktree.read(
                relative, "Quartus source-closure input", MAX_SOURCE_FILE_BYTES
            )
            reviewed = committed.read(
                relative, "Quartus source-closure input", MAX_SOURCE_FILE_BYTES
            )
            if reviewed != current:
                raise ClosureError(
                    "Quartus source-closure input drifts from reviewed commit: "
                    f"{relative}"
                )
    return bindings, closure_identity(paths)


if __name__ == "__main__":
    import json
    import sys

    root = Path(sys.argv[1]) if len(sys.argv) == 2 else Path(__file__).resolve().parents[1]
    try:
        values, identity = current_bindings(root)
    except (ClosureError, OSError) as error:
        print(f"quartus_connectivity_source_closure.py: {error}", file=sys.stderr)
        raise SystemExit(1)
    print(json.dumps({"source_closure": identity, "source_bindings": values}, indent=2))
