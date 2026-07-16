#!/usr/bin/env python3
"""Generate open, self-checking WonderSwan SRAM persistence probes.

The generated ROMs contain only repository-authored 80186 machine code,
explicit ASCII provenance, cartridge metadata, and 0xFF padding.  They cover
footer save types 0x03, 0x04, and 0x05 for both mono and Color hardware.

On an empty save, a probe writes and immediately verifies two distinct words
in every declared 64 KiB SRAM bank, then commits generation 1.  On later
boots, it verifies the previously committed generation before alternating to
the other pattern and reading it back.  Status is left both in SRAM bank 0 at
offset 0x0004 (so a captured save is self-describing) and in IRAM at 0000:0400:

    0x11  initialized and read back generation 1
    0x22  persisted generation 1, committed/read back generation 2
    0x21  persisted generation 2, committed/read back generation 1
    0xEE  corrupt, aliased, or otherwise unexpected save state

The ROM bundle includes an exact JSON manifest and SHA-256 checksum file that
bind the generator source, the production Open IPL identity, and every
generated output. Generated binaries are build/test artifacts and are
intentionally not checked into the repository.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


ROM_SIZE = 2 * 1024 * 1024
PROGRAM_OFFSET = 0x1F0000
MARKER_OFFSET = PROGRAM_OFFSET + 0x0800
FOOTER_OFFSET = ROM_SIZE - 16
MANIFEST_NAME = "sram_persistence_probes.manifest.json"
CHECKSUM_NAME = "sram_persistence_probes.sha256"
GENERATOR_RELATIVE = "sim/verilator/generate_sram_persistence_probes.py"
MANIFEST_SCHEMA = "swan-song-sram-persistence-probes-v2"
OPEN_IPL_IDENTITY = "open-bootstrap-v3"

SIGNATURE = 0x5353
GENERATION_1 = 0x1357
GENERATION_2 = 0x2468
PATTERN_1 = 0x3100
PATTERN_2 = 0xA600
STATUS_INITIALIZED = 0x11
STATUS_PERSISTED_1_TO_2 = 0x22
STATUS_PERSISTED_2_TO_1 = 0x21
STATUS_FAILURE = 0xEE

MODELS = {
    "ws": 0,
    "wsc": 1,
}
OPEN_IPL_VARIANTS = {
    "ws": "mono-16bit-protected-owner",
    "wsc": "color-16bit-protected-owner",
}


@dataclass(frozen=True)
class SaveType:
    code: int
    bytes: int

    @property
    def banks(self) -> int:
        return self.bytes // 0x10000


SAVE_TYPES = {
    0x03: SaveType(0x03, 128 * 1024),
    0x04: SaveType(0x04, 256 * 1024),
    0x05: SaveType(0x05, 512 * 1024),
}

PROVENANCE_MARKER = (
    b"SWAN SONG SRAM PERSISTENCE PROBE V1\0"
    b"REPOSITORY-AUTHORED; NO COMMERCIAL ROM BYTES\0"
)

class Assembler:
    """Tiny deterministic assembler for the exact 80186 subset used here."""

    def __init__(self) -> None:
        self.data = bytearray()
        self.labels: dict[str, int] = {}
        self.fixups: list[tuple[str, int, str]] = []

    def emit(self, *values: int) -> None:
        if any(not 0 <= value <= 0xFF for value in values):
            raise ValueError("assembler byte is outside 0..255")
        self.data.extend(values)

    def word(self, value: int) -> None:
        if not 0 <= value <= 0xFFFF:
            raise ValueError("assembler word is outside 0..65535")
        self.data.extend(value.to_bytes(2, "little"))

    def label(self, name: str) -> None:
        if name in self.labels:
            raise ValueError(f"duplicate assembler label: {name}")
        self.labels[name] = len(self.data)

    def _relative16(self, opcode: int, label: str) -> None:
        self.emit(opcode)
        position = len(self.data)
        self.word(0)
        self.fixups.append(("rel16", position, label))

    def call(self, label: str) -> None:
        self._relative16(0xE8, label)

    def jump(self, label: str) -> None:
        self._relative16(0xE9, label)

    def jump_equal(self, label: str) -> None:
        # Invert the condition and skip over a near jump.  This avoids the
        # fragile +/-127-byte range of 80186 conditional branches.
        self.emit(0x75, 0x03)  # jne +3
        self.jump(label)

    def jump_not_equal(self, label: str) -> None:
        self.emit(0x74, 0x03)  # je +3
        self.jump(label)

    def loop(self, label: str) -> None:
        self.emit(0xE2)
        position = len(self.data)
        self.emit(0)
        self.fixups.append(("rel8", position, label))

    def finish(self) -> bytes:
        for kind, position, label in self.fixups:
            if label not in self.labels:
                raise ValueError(f"undefined assembler label: {label}")
            displacement = self.labels[label] - (
                position + (2 if kind == "rel16" else 1)
            )
            if kind == "rel16":
                if not -0x8000 <= displacement <= 0x7FFF:
                    raise ValueError(f"near branch to {label} is out of range")
                self.data[position : position + 2] = (
                    displacement & 0xFFFF
                ).to_bytes(2, "little")
            else:
                if not -0x80 <= displacement <= 0x7F:
                    raise ValueError(f"short branch to {label} is out of range")
                self.data[position] = displacement & 0xFF
        return bytes(self.data)


def _mov_word_immediate(assembler: Assembler, offset: int, value: int) -> None:
    assembler.emit(0xC7, 0x06)
    assembler.word(offset)
    assembler.word(value)


def _compare_word_immediate(assembler: Assembler, offset: int, value: int) -> None:
    assembler.emit(0x81, 0x3E)
    assembler.word(offset)
    assembler.word(value)


def program(save_type: int, model: str) -> bytes:
    """Assemble one self-checking program for an exact save geometry/model."""

    if save_type not in SAVE_TYPES:
        raise ValueError(f"unsupported SRAM save type 0x{save_type:02x}")
    if model not in MODELS:
        raise ValueError(f"unsupported WonderSwan model: {model}")
    bank_count = SAVE_TYPES[save_type].banks
    a = Assembler()

    a.emit(0xFA)                    # cli
    a.emit(0xB8, 0x00, 0x10)       # mov ax, 0x1000
    a.emit(0x8E, 0xD8)             # mov ds, ax
    a.emit(0xB0, 0x00)             # mov al, 0
    a.emit(0xE6, 0xC1)             # out 0xc1, al
    _compare_word_immediate(a, 0x0000, SIGNATURE)
    a.jump_not_equal("initialize")
    _compare_word_immediate(a, 0x0002, GENERATION_1)
    a.jump_equal("from_generation_1")
    _compare_word_immediate(a, 0x0002, GENERATION_2)
    a.jump_equal("from_generation_2")
    a.jump("failure")

    a.label("initialize")
    a.emit(0xBB)                    # mov bx, pattern 1
    a.word(PATTERN_1)
    a.call("write_patterns")
    a.call("verify_patterns")
    a.emit(0xB0, 0x00, 0xE6, 0xC1)
    _mov_word_immediate(a, 0x0000, SIGNATURE)
    _mov_word_immediate(a, 0x0002, GENERATION_1)
    _compare_word_immediate(a, 0x0000, SIGNATURE)
    a.jump_not_equal("failure")
    _compare_word_immediate(a, 0x0002, GENERATION_1)
    a.jump_not_equal("failure")
    a.emit(0xB0, STATUS_INITIALIZED)
    a.jump("publish_status")

    a.label("from_generation_1")
    a.emit(0xBB)
    a.word(PATTERN_1)
    a.call("verify_patterns")       # persisted bytes must pass first
    a.emit(0xBB)
    a.word(PATTERN_2)
    a.call("write_patterns")
    a.call("verify_patterns")
    a.emit(0xB0, 0x00, 0xE6, 0xC1)
    _mov_word_immediate(a, 0x0002, GENERATION_2)  # commit last
    _compare_word_immediate(a, 0x0002, GENERATION_2)
    a.jump_not_equal("failure")
    a.emit(0xB0, STATUS_PERSISTED_1_TO_2)
    a.jump("publish_status")

    a.label("from_generation_2")
    a.emit(0xBB)
    a.word(PATTERN_2)
    a.call("verify_patterns")       # persisted bytes must pass first
    a.emit(0xBB)
    a.word(PATTERN_1)
    a.call("write_patterns")
    a.call("verify_patterns")
    a.emit(0xB0, 0x00, 0xE6, 0xC1)
    _mov_word_immediate(a, 0x0002, GENERATION_1)  # commit last
    _compare_word_immediate(a, 0x0002, GENERATION_1)
    a.jump_not_equal("failure")
    a.emit(0xB0, STATUS_PERSISTED_2_TO_1)
    a.jump("publish_status")

    a.label("failure")
    a.emit(0xB0, STATUS_FAILURE)

    a.label("publish_status")
    a.emit(0x88, 0xC2)             # mov dl, al
    a.emit(0xB0, 0x00, 0xE6, 0xC1) # select SRAM bank 0
    a.emit(0x88, 0x16, 0x04, 0x00) # mov [0x0004], dl
    a.emit(0xC6, 0x06, 0x05, 0x00, save_type)
    a.emit(0xC6, 0x06, 0x06, 0x00, MODELS[model])
    a.emit(0x31, 0xC0)             # xor ax, ax
    a.emit(0x8E, 0xD8)             # mov ds, ax
    a.emit(0x88, 0x16, 0x00, 0x04) # mov [0x0400], dl
    a.emit(0xC6, 0x06, 0x01, 0x04, save_type)
    a.emit(0xC6, 0x06, 0x02, 0x04, MODELS[model])
    a.label("halt")
    a.jump("halt")

    a.label("write_patterns")
    a.emit(0xB9)                    # mov cx, bank_count
    a.word(bank_count)
    a.emit(0x31, 0xD2)             # xor dx, dx
    a.label("write_loop")
    a.emit(0x88, 0xD0)             # mov al, dl
    a.emit(0xE6, 0xC1)             # out 0xc1, al
    a.emit(0x89, 0xD8)             # mov ax, bx
    a.emit(0x01, 0xD0)             # add ax, dx
    a.emit(0xA3, 0x00, 0x01)       # mov [0x0100], ax
    a.emit(0xF7, 0xD0)             # not ax
    a.emit(0xA3, 0xFE, 0xFF)       # mov [0xfffe], ax
    a.emit(0x42)                    # inc dx
    a.loop("write_loop")
    a.emit(0xC3)                    # ret

    a.label("verify_patterns")
    a.emit(0xB9)
    a.word(bank_count)
    a.emit(0x31, 0xD2)
    a.label("verify_loop")
    a.emit(0x88, 0xD0)
    a.emit(0xE6, 0xC1)
    a.emit(0x89, 0xD8)
    a.emit(0x01, 0xD0)
    a.emit(0x39, 0x06, 0x00, 0x01) # cmp [0x0100], ax
    a.jump_not_equal("failure")
    a.emit(0xF7, 0xD0)
    a.emit(0x39, 0x06, 0xFE, 0xFF) # cmp [0xfffe], ax
    a.jump_not_equal("failure")
    a.emit(0x42)
    a.loop("verify_loop")
    a.emit(0xC3)

    result = a.finish()
    if len(result) > MARKER_OFFSET - PROGRAM_OFFSET:
        raise ValueError("persistence program overlaps provenance marker")
    return result


def footer(save_type: int, model: str) -> bytes:
    if save_type not in SAVE_TYPES:
        raise ValueError(f"unsupported SRAM save type 0x{save_type:02x}")
    if model not in MODELS:
        raise ValueError(f"unsupported WonderSwan model: {model}")
    return bytes(
        (
            0xEA, 0x00, 0x00, 0x00, 0xF0,  # jmp far f000:0000
            0x00,                          # maintenance flags
            0x00,                          # developer/publisher ID
            MODELS[model],                 # mono/color field
            0x53,                          # Swan Song diagnostic ID
            0x01,                          # probe format version
            0x04,                          # 16 Mbit / 2 MiB ROM
            save_type,
            0x04,                          # 16-bit ROM bus, horizontal
            0x00,                          # Bandai 2001 mapper
            0x00, 0x00,                    # checksum filled by image()
        )
    )


def image(save_type: int, model: str) -> bytes:
    result = bytearray(b"\xFF" * ROM_SIZE)
    payload = program(save_type, model)
    result[PROGRAM_OFFSET : PROGRAM_OFFSET + len(payload)] = payload
    result[MARKER_OFFSET : MARKER_OFFSET + len(PROVENANCE_MARKER)] = (
        PROVENANCE_MARKER
    )
    result[FOOTER_OFFSET:] = footer(save_type, model)
    result[-2:] = (sum(result[:-2]) & 0xFFFF).to_bytes(2, "little")
    return bytes(result)


def rom_name(save_type: int, model: str) -> str:
    if save_type not in SAVE_TYPES or model not in MODELS:
        raise ValueError("unsupported persistence probe identity")
    return f"sram_type{save_type:02x}_persistence.{model}"


def _identity(data: bytes) -> dict[str, object]:
    return {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate manifest field: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"non-standard JSON constant: {value}")


def _read_regular(path: Path, *, role: str, single_link: bool = True) -> bytes:
    """Read one exact regular file without following a final symlink."""

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ValueError(f"{role} must be a readable regular nonsymlink file: {path}") from error
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"{role} must be a regular file: {path}")
        if single_link and metadata.st_nlink != 1:
            raise ValueError(f"{role} must not be hard-linked: {path}")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            return stream.read()
    finally:
        os.close(descriptor)


def _write_new_private_at(directory: int, name: str, payload: bytes) -> None:
    """Create one owner-only bundle member without following or replacing."""

    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(name, flags, 0o600, dir_fd=directory)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(descriptor)
    finally:
        os.close(descriptor)


def manifest_document(
    outputs: dict[str, bytes], source_path: Path, models: Sequence[str]
) -> dict[str, object]:
    source = _read_regular(source_path, role="generator source")
    probes = []
    for model in models:
        for save_type, save in SAVE_TYPES.items():
            name = rom_name(save_type, model)
            payload = program(save_type, model)
            probes.append(
                {
                    "banks": save.banks,
                    "footer_save_type": f"0x{save_type:02x}",
                    "model": model,
                    "output": name,
                    "open_ipl_identity": OPEN_IPL_IDENTITY,
                    "open_ipl_variant": OPEN_IPL_VARIANTS[model],
                    "program_bytes": len(payload),
                    "program_sha256": hashlib.sha256(payload).hexdigest(),
                    "sram_bytes": save.bytes,
                    "status_iram": "0x0400",
                    "status_sram": "bank-0:0x0004",
                }
            )
    return {
        "schema": MANIFEST_SCHEMA,
        "content_origin": "repository-authored-machine-code-metadata-and-padding-only",
        "commercial_rom_bytes": False,
        "generator": {
            "path": GENERATOR_RELATIVE,
            **_identity(source),
        },
        "models": list(models),
        "outputs": {
            name: _identity(outputs[name]) for name in sorted(outputs)
        },
        "probes": probes,
        "protocol": {
            "generation_1": f"0x{GENERATION_1:04x}",
            "generation_2": f"0x{GENERATION_2:04x}",
            "signature": f"0x{SIGNATURE:04x}",
            "status_failure": f"0x{STATUS_FAILURE:02x}",
            "status_initialized": f"0x{STATUS_INITIALIZED:02x}",
            "status_persisted_1_to_2": f"0x{STATUS_PERSISTED_1_TO_2:02x}",
            "status_persisted_2_to_1": f"0x{STATUS_PERSISTED_2_TO_1:02x}",
        },
    }


def _manifest_bytes(document: dict[str, object]) -> bytes:
    return (
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode("utf-8")


def _checksum_bytes(files: dict[str, bytes]) -> bytes:
    return "".join(
        f"{hashlib.sha256(files[name]).hexdigest()}  {name}\n"
        for name in sorted(files)
    ).encode("ascii")


def normalize_models(models: Iterable[str] | None) -> tuple[str, ...]:
    selected = tuple(MODELS) if models is None else tuple(models)
    if not selected or len(selected) != len(set(selected)):
        raise ValueError("models must be nonempty and unique")
    unknown = sorted(set(selected) - set(MODELS))
    if unknown:
        raise ValueError(f"unsupported WonderSwan models: {unknown}")
    return tuple(model for model in MODELS if model in selected)


def bundle_files(
    *,
    models: Iterable[str] | None = None,
    source_path: Path | None = None,
) -> dict[str, bytes]:
    """Return one complete deterministic bundle without touching the filesystem."""

    selected = normalize_models(models)
    source_path = Path(__file__).resolve() if source_path is None else source_path
    _read_regular(source_path, role="generator source")
    outputs: dict[str, bytes] = {}
    for model in selected:
        for save_type in SAVE_TYPES:
            outputs[rom_name(save_type, model)] = image(save_type, model)
    document = manifest_document(outputs, source_path, selected)
    manifest = _manifest_bytes(document)
    checksummed = {**outputs, MANIFEST_NAME: manifest}
    checksum = _checksum_bytes(checksummed)
    return {**outputs, MANIFEST_NAME: manifest, CHECKSUM_NAME: checksum}


def generate(
    output_dir: Path,
    *,
    models: Iterable[str] | None = None,
    source_path: Path | None = None,
) -> tuple[Path, ...]:
    all_files = bundle_files(models=models, source_path=source_path)
    if output_dir.name in {"", ".", ".."}:
        raise ValueError("output directory must name one new child directory")
    try:
        parent = output_dir.expanduser().absolute().parent.resolve(strict=True)
    except OSError as error:
        raise ValueError("output directory parent must already exist") from error
    output_dir = parent / output_dir.name
    try:
        output_dir.mkdir(mode=0o700, exist_ok=False)
    except FileExistsError as error:
        raise ValueError(
            "output directory must not already exist; refusing to replace or mix artifacts"
        ) from error
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(output_dir, flags)
    try:
        created = os.fstat(descriptor)
        if not stat.S_ISDIR(created.st_mode):
            raise ValueError("created persistence output is not a directory")
        os.fchmod(descriptor, 0o700)
        for name in sorted(all_files):
            _write_new_private_at(descriptor, name, all_files[name])
        current = output_dir.lstat()
        if (current.st_dev, current.st_ino) != (created.st_dev, created.st_ino):
            raise ValueError("persistence output directory changed during generation")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return tuple(output_dir / name for name in sorted(all_files))


def _read_plain(path: Path) -> bytes:
    return _read_regular(path, role="bundle member")


def _read_plain_at(directory: int, name: str) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=directory)
    except OSError as error:
        raise ValueError(f"bundle member is unavailable: {name}") from error
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ValueError(f"bundle member must be one regular file: {name}")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            return stream.read()
    finally:
        os.close(descriptor)


def verify_bundle(
    output_dir: Path,
    *,
    source_path: Path | None = None,
) -> dict[str, object]:
    """Fail closed unless a generated directory is one exact current bundle."""

    source_path = Path(__file__).resolve() if source_path is None else source_path
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        directory = os.open(output_dir, flags)
    except OSError as error:
        raise ValueError("persistence bundle must be a nonsymlink directory") from error
    try:
        directory_metadata = os.fstat(directory)
        manifest_payload = _read_plain_at(directory, MANIFEST_NAME)
        document = json.loads(
            manifest_payload.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_json_constant,
        )
        if not isinstance(document, dict) or document.get("schema") != MANIFEST_SCHEMA:
            raise ValueError("persistence manifest schema mismatch")
        raw_models = document.get("models")
        if not isinstance(raw_models, list) or any(
            not isinstance(model, str) for model in raw_models
        ):
            raise ValueError("persistence manifest models are invalid")
        selected = normalize_models(raw_models)
        names: set[str] = set()
        for model in selected:
            names.update(rom_name(save_type, model) for save_type in SAVE_TYPES)
        actual_outputs = {name: _read_plain_at(directory, name) for name in names}
        expected = manifest_document(actual_outputs, source_path, selected)
        if document != expected:
            raise ValueError("persistence manifest source/output contract mismatch")
        for model in selected:
            for save_type in SAVE_TYPES:
                name = rom_name(save_type, model)
                if actual_outputs[name] != image(save_type, model):
                    raise ValueError(f"persistence ROM is not exact generated content: {name}")
        manifest_bytes = _manifest_bytes(document)
        if manifest_payload != manifest_bytes:
            raise ValueError("persistence manifest is not exact canonical bytes")
        checksum_expected = _checksum_bytes(
            {**actual_outputs, MANIFEST_NAME: manifest_payload}
        )
        if _read_plain_at(directory, CHECKSUM_NAME) != checksum_expected:
            raise ValueError("persistence checksum file mismatch")
        expected_names = names | {MANIFEST_NAME, CHECKSUM_NAME}
        actual_names = set(os.listdir(directory))
        if actual_names != expected_names:
            raise ValueError(
                "persistence bundle member set mismatch: "
                f"missing={sorted(expected_names - actual_names)!r} "
                f"extra={sorted(actual_names - expected_names)!r}"
            )
        current = output_dir.lstat()
        if (current.st_dev, current.st_ino) != (
            directory_metadata.st_dev,
            directory_metadata.st_ino,
        ):
            raise ValueError("persistence bundle directory changed during verification")
        return document
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid persistence manifest: {error}") from error
    finally:
        os.close(directory)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument(
        "--model",
        action="append",
        choices=tuple(MODELS),
        help="generate only this model (repeatable; default: ws and wsc)",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="verify an existing bundle instead of generating it",
    )
    args = parser.parse_args()
    try:
        if args.verify:
            document = verify_bundle(args.output_dir)
            print(
                f"verified {args.output_dir} "
                f"({len(document['outputs'])} exact outputs)"
            )
        else:
            paths = generate(args.output_dir, models=args.model)
            for path in paths:
                print(f"generated {path} ({path.stat().st_size} bytes)")
    except (OSError, ValueError) as error:
        raise SystemExit(f"SRAM persistence probes: {error}") from error


if __name__ == "__main__":
    main()
