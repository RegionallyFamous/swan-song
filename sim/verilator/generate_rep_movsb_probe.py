#!/usr/bin/env python3
"""Generate the clean-room Swan Song REP MOVSB CPU probe.

The cartridge is built entirely from project-authored machine code and
algorithmic payload bytes.  It requires no SDK, assembler, BIOS, carrier ROM,
or pre-existing test fixture.  Two independently initialized REP MOVSB
instructions copy different 2 KiB linear-ROM regions into disjoint IRAM
windows, write a completion word, and halt.
"""

from __future__ import annotations

import argparse
import hashlib
import struct
from dataclasses import dataclass
from pathlib import Path


ROM_SIZE = 128 * 1024
PROGRAM_OFFSET = 0x10000
PROGRAM_PC = 0xF0000
MARKER_OFFSET = 0x10200
FOOTER_SIZE = 16
FOOTER_OFFSET = ROM_SIZE - FOOTER_SIZE
ROM_NAME = "rep_movsb_probe.ws"

MARKER_MAGIC = b"SSREPMV\0"
MARKER_SCHEMA = 1
MARKER_HEADER = struct.Struct("<8sHHI")
MARKER_RECORD = struct.Struct("<IIIHH32s")
MARKER_SIZE = MARKER_HEADER.size + 2 * MARKER_RECORD.size

COMPLETION_ADDRESS = 0x3FFE
COMPLETION_VALUE = 0xC0DE


@dataclass(frozen=True)
class Transfer:
    """Static address contract for one generated copy."""

    name: str
    source_offset: int
    source_address: int
    source_ip: int
    destination: int
    length: int = 0x0800


TRANSFERS = (
    Transfer("low_window", 0x12000, 0xF2000, 0x2000, 0x0800),
    Transfer("high_window", 0x15000, 0xF5000, 0x5000, 0x2800),
)


@dataclass(frozen=True)
class Program:
    data: bytes
    rep_origins: tuple[int, int]
    completion_origin: int
    halt_pc: int


@dataclass(frozen=True)
class MarkerRecord:
    source_address: int
    source_offset: int
    rep_origin: int
    destination: int
    length: int
    payload_sha256: bytes


class Builder:
    """Minimal builder for this probe's authored 80186 instruction bytes."""

    def __init__(self) -> None:
        self.data = bytearray()

    @property
    def pc(self) -> int:
        return PROGRAM_PC + len(self.data)

    def emit(self, *values: int) -> None:
        if any(not 0 <= value <= 0xFF for value in values):
            raise ValueError(f"machine-code byte outside 0..255: {values!r}")
        self.data.extend(values)

    def mov_ax(self, value: int) -> None:
        self.emit(0xB8, value & 0xFF, (value >> 8) & 0xFF)

    def mov_si(self, value: int) -> None:
        self.emit(0xBE, value & 0xFF, (value >> 8) & 0xFF)

    def mov_di(self, value: int) -> None:
        self.emit(0xBF, value & 0xFF, (value >> 8) & 0xFF)

    def mov_cx(self, value: int) -> None:
        self.emit(0xB9, value & 0xFF, (value >> 8) & 0xFF)

    def align_word(self) -> None:
        if self.pc & 1:
            self.emit(0x90)  # nop; keeps the REP opcode in one fetch word


def validate_layout() -> None:
    """Reject address metadata that cannot describe two independent copies."""

    if len(TRANSFERS) != 2:
        raise ValueError(f"REP MOVSB probe requires two transfers, got {len(TRANSFERS)}")
    for transfer in TRANSFERS:
        expected_address = PROGRAM_PC + transfer.source_ip
        expected_offset = PROGRAM_OFFSET + (transfer.source_address - PROGRAM_PC)
        if transfer.source_address != expected_address:
            raise ValueError(f"{transfer.name} source segment:offset mapping is invalid")
        if transfer.source_offset != expected_offset:
            raise ValueError(f"{transfer.name} linear-ROM mapping is invalid")
        if transfer.length != 0x0800:
            raise ValueError(f"{transfer.name} is not exactly 2 KiB")
        if not 0 <= transfer.destination < transfer.destination + transfer.length <= 0x4000:
            raise ValueError(f"{transfer.name} destination is outside 16 KiB IRAM")
    first, second = TRANSFERS
    if first.source_offset + first.length > second.source_offset:
        raise ValueError("REP MOVSB source regions overlap")
    if first.destination + first.length > second.destination:
        raise ValueError("REP MOVSB destination regions overlap")


def program() -> Program:
    """Return the exact probe program and instruction-origin metadata."""

    validate_layout()
    code = Builder()
    code.emit(0xFA)  # cli
    rep_origins: list[int] = []
    for transfer in TRANSFERS:
        # Re-establish every operand register for both copies.  The second
        # transfer therefore does not inherit DS, ES, DF, SI, DI, or CX from
        # the first transfer's terminal state.
        code.emit(0xFC)  # cld
        code.mov_ax(0xF000)
        code.emit(0x8E, 0xD8)  # mov ds, ax
        code.mov_ax(0x0000)
        code.emit(0x8E, 0xC0)  # mov es, ax
        code.mov_si(transfer.source_ip)
        code.mov_di(transfer.destination)
        code.mov_cx(transfer.length)
        code.align_word()
        rep_origins.append(code.pc)
        code.emit(0xF3, 0xA4)  # rep movsb

    # REP MOVSB leaves DS selecting cartridge ROM.  Restore the data segment
    # explicitly so the terminal status word is independent of that state and
    # lands in IRAM rather than the F0000 cartridge window.
    code.mov_ax(0x0000)
    code.emit(0x8E, 0xD8)  # mov ds, ax
    completion_origin = code.pc
    code.emit(
        0xC7,
        0x06,
        COMPLETION_ADDRESS & 0xFF,
        COMPLETION_ADDRESS >> 8,
        COMPLETION_VALUE & 0xFF,
        COMPLETION_VALUE >> 8,
    )  # mov word [COMPLETION_ADDRESS], COMPLETION_VALUE
    halt_pc = code.pc
    code.emit(0xF4)
    if len(rep_origins) != len(TRANSFERS):
        raise AssertionError("REP MOVSB origin metadata is incomplete")
    if any(origin & 1 for origin in rep_origins):
        raise AssertionError("REP MOVSB opcode is not word aligned")
    return Program(
        data=bytes(code.data),
        rep_origins=(rep_origins[0], rep_origins[1]),
        completion_origin=completion_origin,
        halt_pc=halt_pc,
    )


def payload(index: int) -> bytes:
    """Return one deterministic, distinctive project-authored payload."""

    if index == 0:
        return bytes(
            (
                (offset * 73)
                + ((offset >> 3) * 29)
                + (offset >> 8)
                + 0x31
            )
            & 0xFF
            for offset in range(TRANSFERS[index].length)
        )
    if index == 1:
        return bytes(
            (
                (offset * 151)
                ^ ((offset >> 2) * 17)
                ^ ((offset * offset) >> 5)
                ^ 0xC7
            )
            & 0xFF
            for offset in range(TRANSFERS[index].length)
        )
    raise ValueError(f"payload index outside 0..{len(TRANSFERS) - 1}: {index}")


def marker_records() -> tuple[MarkerRecord, MarkerRecord]:
    """Return the semantic records encoded by the binary identity marker."""

    built = program()
    records = []
    for index, (transfer, origin) in enumerate(zip(TRANSFERS, built.rep_origins)):
        records.append(
            MarkerRecord(
                source_address=transfer.source_address,
                source_offset=transfer.source_offset,
                rep_origin=origin,
                destination=transfer.destination,
                length=transfer.length,
                payload_sha256=hashlib.sha256(payload(index)).digest(),
            )
        )
    return records[0], records[1]


def marker() -> bytes:
    """Encode a fixed-width, versioned marker suitable for machine parsing."""

    result = bytearray(
        MARKER_HEADER.pack(
            MARKER_MAGIC,
            MARKER_SCHEMA,
            len(TRANSFERS),
            MARKER_SIZE,
        )
    )
    for record in marker_records():
        result.extend(
            MARKER_RECORD.pack(
                record.source_address,
                record.source_offset,
                record.rep_origin,
                record.destination,
                record.length,
                record.payload_sha256,
            )
        )
    if len(result) != MARKER_SIZE:
        raise AssertionError(f"marker size changed: {len(result)} != {MARKER_SIZE}")
    return bytes(result)


def parse_marker(data: bytes) -> tuple[MarkerRecord, MarkerRecord]:
    """Parse and structurally validate one generated marker."""

    if len(data) != MARKER_SIZE:
        raise ValueError(f"marker size mismatch: {len(data)} != {MARKER_SIZE}")
    magic, schema, count, size = MARKER_HEADER.unpack_from(data)
    expected_header = (MARKER_MAGIC, MARKER_SCHEMA, len(TRANSFERS), MARKER_SIZE)
    if (magic, schema, count, size) != expected_header:
        raise ValueError("REP MOVSB marker header mismatch")
    records = []
    offset = MARKER_HEADER.size
    for _ in range(count):
        values = MARKER_RECORD.unpack_from(data, offset)
        records.append(MarkerRecord(*values))
        offset += MARKER_RECORD.size
    if offset != size:
        raise ValueError("REP MOVSB marker record span mismatch")
    return records[0], records[1]


def footer() -> bytes:
    """Return this probe's authored 16-byte mono cartridge footer template."""

    result = bytearray(FOOTER_SIZE)
    result[0:5] = b"\xEA\x00\x00\x00\xF0"  # far jump to F000:0000
    result[5] = 0x00  # normal boot path
    result[6] = 0x00  # unregistered/homebrew publisher
    result[7] = 0x00  # mono WonderSwan cartridge
    result[8] = 0xD7  # Swan Song REP MOVSB diagnostic ID
    result[9] = MARKER_SCHEMA
    result[10] = 0x00  # 1 Mbit / 128 KiB ROM
    result[11] = 0x00  # no cartridge save memory
    result[12] = 0x04  # 16-bit ROM bus, horizontal orientation
    result[13] = 0x00  # standard mapper
    # Bytes 14..15 are filled with the whole-image additive checksum.
    return bytes(result)


def image() -> bytes:
    """Return the exact deterministic, checksummed cartridge image."""

    built = program()
    identity = marker()
    result = bytearray(b"\xFF" * ROM_SIZE)
    if PROGRAM_OFFSET + len(built.data) > MARKER_OFFSET:
        raise ValueError("REP MOVSB program overlaps the machine marker")
    if MARKER_OFFSET + len(identity) > min(
        transfer.source_offset for transfer in TRANSFERS
    ):
        raise ValueError("REP MOVSB marker overlaps source payload data")

    result[PROGRAM_OFFSET : PROGRAM_OFFSET + len(built.data)] = built.data
    result[MARKER_OFFSET : MARKER_OFFSET + len(identity)] = identity
    for index, transfer in enumerate(TRANSFERS):
        data = payload(index)
        end = transfer.source_offset + len(data)
        if end > FOOTER_OFFSET:
            raise ValueError(f"{transfer.name} payload overlaps cartridge footer")
        result[transfer.source_offset:end] = data
    result[FOOTER_OFFSET:] = footer()
    result[-2:] = (sum(result[:-2]) & 0xFFFF).to_bytes(2, "little")
    return bytes(result)


def generate(output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / ROM_NAME
    output.write_bytes(image())
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    try:
        output = generate(args.output_dir)
    except (OSError, ValueError) as error:
        raise SystemExit(f"cannot generate REP MOVSB probe: {error}") from error
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    print(f"generated {output} ({output.stat().st_size} bytes, sha256={digest})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
