#!/usr/bin/env python3
"""Generate an open WSC interrupt-vector and keypad-edge probe.

The build-only machine-code fixture combines a deliberately unaligned Color
interrupt base with deterministic physical-button replay.  It proves the
selected keypad matrix, key-edge status retention/acknowledgement, held-key
non-retriggering, and actual dispatch through vector ``(0x87 & 0xf8) | 1``.
Mapper writes spell ``BDVIHRPACZ`` only after each preceding assertion passes.
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
ROM_NAME = "interrupt_input_probe.wsc"
SCRIPT_NAME = "interrupt_input_probe.input"
MARKER = b"SWAN-SONG-INTERRUPT-INPUT-PROBE-V1\0"

INPUT_SCRIPT = (
    b"# Disabled, enabled, repeat, then combined-row keypad edges.\n"
    b"3000 x2\n"
    b"7000 none\n"
    b"11000 x2\n"
    b"24000 none\n"
    b"28000 x2\n"
    b"33000 none\n"
    b"37000 x2,y1\n"
    b"42000 none\n"
)

EXPECTED_MARKERS = b"BDVIHRPACZ"


@dataclass(frozen=True)
class Program:
    data: bytes
    marker_origins: dict[int, int]
    labels: dict[str, int]


class Builder:
    def __init__(self) -> None:
        self.data = bytearray()
        self.labels: dict[str, int] = {}
        self.rel8_fixups: list[tuple[int, str]] = []
        self.rel16_fixups: list[tuple[int, str]] = []
        self.word_fixups: list[tuple[int, str]] = []
        self.marker_origins: dict[int, int] = {}

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

    def branch(self, opcode: int, label: str) -> None:
        self.emit(opcode, 0)
        self.rel8_fixups.append((self.offset - 1, label))

    def guard(self, failure_opcode: int) -> None:
        """Jump to the distant failure loop when a condition is true."""

        inverse = {0x74: 0x75, 0x75: 0x74}.get(failure_opcode)
        if inverse is None:
            raise ValueError(f"unsupported guard opcode {failure_opcode:#x}")
        self.emit(inverse, 0x03, 0xE9, 0x00, 0x00)
        self.rel16_fixups.append((self.offset - 2, "fail"))

    def mov_word_label(self, address: int, label: str) -> None:
        self.emit(0xC7, 0x06, address & 0xFF, address >> 8)
        self.word_fixups.append((self.offset, label))
        self.emit(0, 0)

    def marker(self, value: int) -> None:
        if value in self.marker_origins:
            raise ValueError(f"duplicate marker value {value:#x}")
        self.emit(0xB0, value, 0xE6, 0xC0)  # mov al,value; out c0h,al
        self.marker_origins[value] = self.pc - 2

    def finish(self) -> Program:
        for position, label in self.rel8_fixups:
            if label not in self.labels:
                raise ValueError(f"undefined branch label {label}")
            displacement = self.labels[label] - (position + 1)
            if not -128 <= displacement <= 127:
                raise ValueError(
                    f"branch to {label} outside signed-byte range: {displacement}"
                )
            self.data[position] = displacement & 0xFF
        for position, label in self.word_fixups:
            if label not in self.labels:
                raise ValueError(f"undefined word label {label}")
            self.data[position : position + 2] = self.labels[label].to_bytes(
                2, "little"
            )
        for position, label in self.rel16_fixups:
            if label not in self.labels:
                raise ValueError(f"undefined near-branch label {label}")
            displacement = self.labels[label] - (position + 2)
            if not -32768 <= displacement <= 32767:
                raise ValueError(
                    f"near branch to {label} outside signed-word range: {displacement}"
                )
            self.data[position : position + 2] = (displacement & 0xFFFF).to_bytes(
                2, "little"
            )
        return Program(
            bytes(self.data), dict(self.marker_origins), dict(self.labels)
        )


def program() -> Program:
    code = Builder()
    code.emit(0xFA)  # cli
    code.emit(0x31, 0xC0)  # xor ax,ax
    code.emit(0x8E, 0xD8)  # mov ds,ax
    code.emit(0x8E, 0xD0)  # mov ss,ax
    code.emit(0xBC, 0xF0, 0x3F)  # mov sp,3ff0h
    code.emit(0xC6, 0x06, 0x00, 0x03, 0x00)  # handler flag = 0

    # Color must mask the intentionally unaligned base just like mono.
    code.emit(0xB0, 0x87, 0xE6, 0xB0)  # interrupt base
    code.emit(0xE4, 0xB0, 0x3C, 0x80)  # in al,b0h; cmp al,80h
    code.guard(0x75)
    code.marker(ord("B"))

    # Install the key handler at vector 81h in the IRAM vector table.
    code.mov_word_label(0x0204, "key_handler")
    code.emit(0xC7, 0x06, 0x06, 0x02, 0x00, 0xF0)
    code.emit(0xB0, 0xFF, 0xE6, 0xB6)  # acknowledge all
    code.emit(0xB0, 0x00, 0xE6, 0xB2)  # disable all
    code.emit(0xB0, 0x20, 0xE6, 0xB5)  # select horizontal X row

    # A key transition while disabled must not become pending later.
    code.label("disabled_press")
    code.emit(0xE4, 0xB5, 0xA8, 0x02)
    code.branch(0x74, "disabled_press")
    code.emit(0xE4, 0xB4, 0xA8, 0x02)
    code.guard(0x75)
    code.marker(ord("D"))
    code.label("disabled_release")
    code.emit(0xE4, 0xB5, 0xA8, 0x02)
    code.branch(0x75, "disabled_release")

    # The next rising edge must set status bit 1 and expose vector 81h.
    code.emit(0xB0, 0x02, 0xE6, 0xB2)
    code.emit(0xE4, 0xB4, 0xA8, 0x02)
    code.guard(0x75)
    code.emit(0xE4, 0xB0, 0x3C, 0x80)
    code.guard(0x75)
    code.label("enabled_press")
    code.emit(0xE4, 0xB5, 0xA8, 0x02)
    code.branch(0x74, "enabled_press")
    code.label("enabled_status")
    code.emit(0xE4, 0xB4, 0xA8, 0x02)
    code.branch(0x74, "enabled_status")
    code.emit(0xE4, 0xB0, 0x3C, 0x81)
    code.guard(0x75)
    code.marker(ord("V"))

    # Actual IRQ dispatch must use the masked Color base and handler vector.
    code.emit(0xFB, 0x90)  # sti; nop (architectural one-instruction delay)
    code.label("wait_handler")
    code.emit(0x80, 0x3E, 0x00, 0x03, 0x01)
    code.branch(0x75, "wait_handler")
    code.emit(0xFA)  # cli

    # Acknowledging an edge IRQ must stay clear for the entire physical hold.
    code.label("held_clear")
    code.emit(0xE4, 0xB4, 0xA8, 0x02)
    code.guard(0x75)
    code.emit(0xE4, 0xB5, 0xA8, 0x02)
    code.branch(0x75, "held_clear")
    code.emit(0xE4, 0xB4, 0xA8, 0x02)
    code.guard(0x75)
    code.emit(0xE4, 0xB0, 0x3C, 0x80)
    code.guard(0x75)
    code.marker(ord("H"))

    # Release/repress must create a fresh edge.  Disabling preserves it;
    # acknowledgement, not mask changes, clears both status and vector index.
    code.label("repeat_press")
    code.emit(0xE4, 0xB5, 0xA8, 0x02)
    code.branch(0x74, "repeat_press")
    code.label("repeat_status")
    code.emit(0xE4, 0xB4, 0xA8, 0x02)
    code.branch(0x74, "repeat_status")
    code.marker(ord("R"))
    code.emit(0xB0, 0x00, 0xE6, 0xB2)
    code.emit(0xE4, 0xB4, 0xA8, 0x02)
    code.guard(0x74)
    code.emit(0xE4, 0xB0, 0x3C, 0x81)
    code.guard(0x75)
    code.marker(ord("P"))
    code.emit(0xB0, 0x02, 0xE6, 0xB6)
    code.emit(0xE4, 0xB4, 0xA8, 0x02)
    code.guard(0x75)
    code.emit(0xE4, 0xB0, 0x3C, 0x80)
    code.guard(0x75)
    code.marker(ord("A"))
    code.label("repeat_release")
    code.emit(0xE4, 0xB5, 0xA8, 0x02)
    code.branch(0x75, "repeat_release")

    # Multiple selected matrix rows are wired-OR, not first-row-only.
    code.emit(0xB0, 0x30, 0xE6, 0xB5)
    code.label("combined_press")
    code.emit(0xE4, 0xB5, 0x3C, 0x33)
    code.branch(0x75, "combined_press")
    code.marker(ord("C"))
    code.label("combined_release")
    code.emit(0xE4, 0xB5, 0x3C, 0x30)
    code.branch(0x75, "combined_release")
    code.marker(ord("Z"))
    code.label("success")
    code.branch(0xEB, "success")

    code.label("fail")
    code.branch(0xEB, "fail")

    code.label("key_handler")
    code.emit(0x50)  # push ax
    code.emit(0xB0, 0x02, 0xE6, 0xB6)  # acknowledge key edge
    code.emit(0xC6, 0x06, 0x00, 0x03, 0x01)  # handler flag = 1
    code.marker(ord("I"))
    code.emit(0x58, 0xCF)  # pop ax; iret
    return code.finish()


def footer() -> bytes:
    result = bytearray(16)
    result[0:5] = b"\xEA\x00\x00\x00\xF0"
    result[7] = 0x01  # Color cartridge.
    result[8] = 0x4A  # Repository-authored diagnostic ID.
    result[9] = 0x01
    result[12] = 0x04  # 16-bit ROM bus, horizontal orientation.
    return bytes(result)


def image() -> bytes:
    compiled = program().data
    result = bytearray(b"\xFF" * ROM_SIZE)
    if PROGRAM_OFFSET + len(compiled) > MARKER_OFFSET:
        raise ValueError("interrupt-input program overlaps identity marker")
    result[PROGRAM_OFFSET : PROGRAM_OFFSET + len(compiled)] = compiled
    result[MARKER_OFFSET : MARKER_OFFSET + len(MARKER)] = MARKER
    result[FOOTER_OFFSET:] = footer()
    result[-2:] = (sum(result[:-2]) & 0xFFFF).to_bytes(2, "little")
    return bytes(result)


def generate(output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rom = output_dir / ROM_NAME
    script = output_dir / SCRIPT_NAME
    rom.write_bytes(image())
    script.write_bytes(INPUT_SCRIPT)
    return rom, script


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    try:
        paths = generate(args.output_dir)
    except (OSError, ValueError) as error:
        raise SystemExit(f"cannot generate interrupt-input probe: {error}") from error
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
