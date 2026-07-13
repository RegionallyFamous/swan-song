#!/usr/bin/env python3
"""Generate a self-contained mono WonderSwan V30MZ quirk probe.

The ROM is assembled directly from repository-authored 80186 machine-code
bytes.  It needs no SDK, assembler, BIOS, carrier ROM, or checked-in binary.
The program records arithmetic results and flags in IRAM, handles AAM base 0
through a locally installed INT 0 vector, exercises both SALC carry paths, and
halts so a complete one-frame CPU/memory trace remains small.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path


ROM_SIZE = 128 * 1024
PROGRAM_OFFSET = 0x10000
PROGRAM_PC = 0xF0000
MARKER_OFFSET = 0x10200
FOOTER_OFFSET = ROM_SIZE - 16
ROM_NAME = "cpu_quirks_probe.ws"
MARKER = b"SWAN-SONG-V30MZ-QUIRKS-PROBE-V1\0"

AAM_FLAGS = 0x00C4  # PF, ZF, SF are architecturally defined.
ADD_FLAGS = 0x08D5  # CF, PF, AF, ZF, SF, OF.

# Word records written by the probe.  Flag records are compared through the
# corresponding masks because PUSHF also reports fixed/control flag bits.
RESULTS = {
    "aam_3c_result": (0x0200, 0x030C, 0xFFFF),
    "aam_3c_flags": (0x0202, 0x0004, AAM_FLAGS),
    "aam_30_result": (0x0204, 0x0300, 0xFFFF),
    "aam_30_flags": (0x0206, 0x0044, AAM_FLAGS),
    "aam_f1_baseff_result": (0x022C, 0x00F1, 0xFFFF),
    "aam_f1_baseff_flags": (0x022E, 0x0080, AAM_FLAGS),
    "aad_0880_result": (0x0208, 0x0000, 0xFFFF),
    "aad_0880_flags": (0x020A, 0x0845, ADD_FLAGS),
    "aad_0808_result": (0x020C, 0x0088, 0xFFFF),
    "aad_0808_flags": (0x020E, 0x0084, ADD_FLAGS),
    "aad_0101_base15_result": (0x0210, 0x0010, 0xFFFF),
    "aad_0101_base15_flags": (0x0212, 0x0010, ADD_FLAGS),
    "aam_zero_ax": (0x0214, 0x5AC3, 0xFFFF),
    "aam_zero_ip": (0x0216, 0x0000, 0xFFFF),  # filled from the post-AAM label
    "aam_zero_cs": (0x0218, 0xF000, 0xFFFF),
    "aam_zero_count": (0x021A, 0x0001, 0xFFFF),
    "aam_zero_resumed": (0x021C, 0xC0DE, 0xFFFF),
    "salc_cf0_flags_before": (0x021E, 0xFED6, 0xFFFF),
    "salc_cf0_result": (0x0220, 0xA500, 0xFFFF),
    "salc_cf0_flags": (0x0222, 0xFED6, 0xFFFF),
    "salc_cf1_flags_before": (0x0224, 0xF003, 0xFFFF),
    "salc_cf1_result": (0x0226, 0xA5FF, 0xFFFF),
    "salc_cf1_flags": (0x0228, 0xF003, 0xFFFF),
    "complete": (0x022A, 0xBEEF, 0xFFFF),
}


@dataclass(frozen=True)
class Program:
    data: bytes
    labels: dict[str, int]
    result_origins: dict[str, int]
    salc_origins: tuple[int, int]


class Builder:
    def __init__(self) -> None:
        self.data = bytearray()
        self.labels: dict[str, int] = {}
        self.word_fixups: list[tuple[int, str]] = []
        self.result_origins: dict[str, int] = {}
        self.salc_origins: list[int] = []

    @property
    def offset(self) -> int:
        return len(self.data)

    @property
    def pc(self) -> int:
        return PROGRAM_PC + self.offset

    def emit(self, *values: int) -> None:
        if any(not 0 <= value <= 0xFF for value in values):
            raise ValueError(f"machine-code byte outside 0..255: {values!r}")
        self.data.extend(values)

    def label(self, name: str) -> None:
        if name in self.labels:
            raise ValueError(f"duplicate label {name}")
        self.labels[name] = self.offset

    def mov_ax(self, value: int) -> None:
        self.emit(0xB8, value & 0xFF, value >> 8)

    def store_ax(self, name: str) -> None:
        address = RESULTS[name][0]
        self.result_origins[name] = self.pc
        self.emit(0xA3, address & 0xFF, address >> 8)

    def store_bx(self, name: str) -> None:
        address = RESULTS[name][0]
        self.result_origins[name] = self.pc
        self.emit(0x89, 0x1E, address & 0xFF, address >> 8)

    def store_flags(self, name: str) -> None:
        self.emit(0x9C, 0x58)  # pushf; pop ax
        self.store_ax(name)

    def store_imm(self, name: str, value: int) -> None:
        address = RESULTS[name][0]
        self.result_origins[name] = self.pc
        self.emit(
            0xC7,
            0x06,
            address & 0xFF,
            address >> 8,
            value & 0xFF,
            value >> 8,
        )

    def mov_mem_label(self, address: int, label: str) -> None:
        self.emit(0xC7, 0x06, address & 0xFF, address >> 8)
        self.word_fixups.append((self.offset, label))
        self.emit(0, 0)

    def finish(self) -> Program:
        for position, label in self.word_fixups:
            if label not in self.labels:
                raise ValueError(f"undefined label {label}")
            value = self.labels[label]
            self.data[position : position + 2] = value.to_bytes(2, "little")
        return Program(
            bytes(self.data),
            dict(self.labels),
            dict(self.result_origins),
            tuple(self.salc_origins),
        )


def program() -> Program:
    """Return the exact probe program and its verification metadata."""

    code = Builder()
    code.emit(0xFA)  # cli
    code.mov_ax(0)
    code.emit(0x8E, 0xD8)  # mov ds, ax
    code.emit(0x8E, 0xD0)  # mov ss, ax
    code.emit(0xBC, 0xF0, 0x3F)  # mov sp, 0x3ff0
    code.emit(0xBB, 0x00, 0x05)  # mov bx, 0x0500 (would expose D6-as-XLAT)

    # AAM base 16: conventional non-decimal result and the important
    # quotient-nonzero/remainder-zero ZF case.
    code.mov_ax(0x003C)
    code.emit(0xD4, 0x10)
    code.store_ax("aam_3c_result")
    code.store_flags("aam_3c_flags")
    code.mov_ax(0x0030)
    code.emit(0xD4, 0x10)
    code.store_ax("aam_30_result")
    code.store_flags("aam_30_flags")
    # An unsigned base above 0x7f leaves an odd-parity, sign-bit-set remainder,
    # proving that PF/SF are computed from AL rather than held at 1/0.
    code.mov_ax(0x00F1)
    code.emit(0xD4, 0xFF)
    code.store_ax("aam_f1_baseff_result")
    code.store_flags("aam_f1_baseff_flags")

    # AAD uses the same flags as an 8-bit ADD of AL and the truncated
    # (AH * base) operand.  Two base-16 cases exercise carry/zero/overflow and
    # sign; base 15 makes AF observable because a base-16 product has low
    # nibble zero.
    code.mov_ax(0x0880)
    code.emit(0xD5, 0x10)
    code.store_ax("aad_0880_result")
    code.store_flags("aad_0880_flags")
    code.mov_ax(0x0808)
    code.emit(0xD5, 0x10)
    code.store_ax("aad_0808_result")
    code.store_flags("aad_0808_flags")
    code.mov_ax(0x0101)
    code.emit(0xD5, 0x0F)
    code.store_ax("aad_0101_base15_result")
    code.store_flags("aad_0101_base15_flags")

    # Point INT 0 to the in-ROM handler, then execute AAM base 0.  The handler
    # records AX before touching it and reads the interrupt frame via SS:BP.
    code.mov_mem_label(0x0000, "divide_error")
    code.emit(0xC7, 0x06, 0x02, 0x00, 0x00, 0xF0)
    code.mov_ax(0x5AC3)
    code.label("aam_zero")
    code.emit(0xD4, 0x00)
    code.label("after_aam_zero")
    code.store_imm("aam_zero_resumed", 0xC0DE)

    # SALC must change AL only.  POPF loads deliberately different full status
    # patterns; MOV and the memory stores leave those flags untouched.
    code.emit(0x68, 0xD4, 0x8E, 0x9D)  # push 0x8ed4; popf (CF clear, IF/DF set)
    code.store_flags("salc_cf0_flags_before")
    code.mov_ax(0xA55A)
    code.label("salc_cf0")
    code.salc_origins.append(code.pc)
    code.emit(0xD6)
    code.store_ax("salc_cf0_result")
    code.store_flags("salc_cf0_flags")

    code.emit(0x68, 0x01, 0x80, 0x9D)  # push 0x8001; popf (CF set)
    code.store_flags("salc_cf1_flags_before")
    code.mov_ax(0xA55A)
    code.label("salc_cf1")
    code.salc_origins.append(code.pc)
    code.emit(0xD6)
    code.store_ax("salc_cf1_result")
    code.store_flags("salc_cf1_flags")
    code.store_imm("complete", 0xBEEF)
    code.label("halt")
    code.emit(0xF4)

    code.label("divide_error")
    code.store_ax("aam_zero_ax")
    code.emit(0x89, 0xE5)  # mov bp, sp
    code.emit(0x8B, 0x5E, 0x00)  # mov bx, [ss:bp+0] (saved IP)
    code.store_bx("aam_zero_ip")
    code.emit(0x8B, 0x5E, 0x02)  # mov bx, [ss:bp+2] (saved CS)
    code.store_bx("aam_zero_cs")
    code.store_imm("aam_zero_count", 1)
    code.emit(0xCF)  # iret

    result = code.finish()
    if result.labels["divide_error"] > 0xFFFF:
        raise ValueError("divide-error handler is outside the code segment")
    # Resolve the one result whose expected value is a generated code label.
    expected_ip = result.labels["after_aam_zero"]
    if expected_ip != expected_results(result)["aam_zero_ip"][1]:
        raise AssertionError("post-AAM IP metadata did not resolve")
    return result


def expected_results(built: Program) -> dict[str, tuple[int, int, int]]:
    """Return result contracts with the generated post-fault IP filled in."""

    result = dict(RESULTS)
    address, _, mask = result["aam_zero_ip"]
    result["aam_zero_ip"] = (address, built.labels["after_aam_zero"], mask)
    return result


def footer() -> bytes:
    """Return an authored horizontal mono cartridge footer."""

    result = bytearray(16)
    result[0:5] = b"\xEA\x00\x00\x00\xF0"  # jmp far F000:0000
    result[6] = 0x00  # Homebrew/test developer ID.
    result[7] = 0x00  # Mono WonderSwan.
    result[8] = 0x51  # Repository-authored diagnostic ID.
    result[9] = 0x01  # Probe format version.
    result[10] = 0x00  # 1 Mbit / 128 KiB ROM.
    result[11] = 0x00  # No save memory.
    result[12] = 0x04  # 16-bit ROM bus, horizontal orientation.
    result[13] = 0x00  # Standard mapper.
    return bytes(result)


def image() -> bytes:
    """Return the deterministic checksummed probe image."""

    built = program()
    result = bytearray(b"\xFF" * ROM_SIZE)
    if PROGRAM_OFFSET + len(built.data) > MARKER_OFFSET:
        raise ValueError("CPU quirk program overlaps its identity marker")
    if MARKER_OFFSET + len(MARKER) > FOOTER_OFFSET:
        raise ValueError("CPU quirk marker overlaps its footer")
    result[PROGRAM_OFFSET : PROGRAM_OFFSET + len(built.data)] = built.data
    result[MARKER_OFFSET : MARKER_OFFSET + len(MARKER)] = MARKER
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
        raise SystemExit(f"cannot generate CPU quirk probe: {error}") from error
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
