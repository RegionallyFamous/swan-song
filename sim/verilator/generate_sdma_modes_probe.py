#!/usr/bin/env python3
"""Generate a self-checking open WSC Sound-DMA modes probe.

The generated cartridge exercises a selected live/shadow/control subset from
the WSdev Sound-DMA documentation.  It writes ordered success bytes to mapper
port C0 only after checking each mode in software; any failed assertion writes
``X`` and stops.  A deterministic input script is emitted solely so captures
can bind every external input, even though the probe itself is CPU-driven.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path


ROM_SIZE = 128 * 1024
PROGRAM_OFFSET = 0x10000
PROGRAM_PC = 0xF0000
MARKER_OFFSET = 0x10800
DATA_OFFSET = 0x11000
DATA_PC = 0xF1000
DATA_SIZE = 0x80
FOOTER_OFFSET = ROM_SIZE - 16
ROM_NAME = "sdma_modes_probe.wsc"
SCRIPT_NAME = "sdma_modes_probe.input"
MARKER = b"SWAN-SONG-SDMA-MODES-PROBE-V1\0"
INPUT_SCRIPT = (
    b"# Parser-required X1 pulse; keypad IRQ remains masked.\n"
    b"0 x1\n"
    b"1 none\n"
)
EXPECTED_MARKERS = b"PONSREATDHUZ"
FAIL_MARKER = ord("X")

# Distinct, non-zero bytes make each SDMA read independently attributable.
SAMPLE_DATA = bytes(((index * 29 + 0x31) & 0xFF) for index in range(DATA_SIZE))


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
        """Jump to the distant failure marker if the condition is true."""

        inverse = {0x74: 0x75, 0x75: 0x74}.get(failure_opcode)
        if inverse is None:
            raise ValueError(f"unsupported guard opcode {failure_opcode:#x}")
        self.emit(inverse, 0x03, 0xE9, 0x00, 0x00)
        self.rel16_fixups.append((self.offset - 2, "fail"))

    def out(self, port: int, value: int) -> None:
        self.emit(0xB0, value, 0xE6, port)  # mov al,value; out port,al

    def compare_port(self, port: int, value: int) -> None:
        self.emit(0xE4, port, 0x3C, value)  # in al,port; cmp al,value
        self.guard(0x75)

    def wait_port(self, name: str, port: int, value: int) -> None:
        self.label(name)
        self.emit(0xE4, port, 0x3C, value)
        self.branch(0x75, name)

    def wait_control_off(self, name: str) -> None:
        self.label(name)
        self.emit(0xE4, 0x52, 0xA8, 0x80)  # in al,52h; test al,80h
        self.branch(0x75, name)

    def delay(self, name: str, iterations: int = 256) -> None:
        self.emit(0xB9, iterations & 0xFF, iterations >> 8)  # mov cx,imm16
        self.label(name)
        self.branch(0xE2, name)  # loop name

    def marker(self, value: int) -> None:
        if value in self.marker_origins:
            raise ValueError(f"duplicate marker value {value:#x}")
        self.emit(0xB0, value, 0xE6, 0xC0)
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


def _set_source(code: Builder, low: int) -> None:
    code.out(0x4A, low)
    code.out(0x4B, 0x10)
    code.out(0x4C, 0xFF)  # only the low nibble is implemented


def _set_length(code: Builder, length: int) -> None:
    code.out(0x4E, length & 0xFF)
    code.out(0x4F, (length >> 8) & 0xFF)
    code.out(0x50, 0xF0)  # only the low nibble is implemented


def _check_counters(code: Builder, source_low: int, length: int) -> None:
    code.compare_port(0x4A, source_low)
    code.compare_port(0x4B, 0x10)
    code.compare_port(0x4C, 0x0F)
    code.compare_port(0x4E, length & 0xFF)
    code.compare_port(0x4F, (length >> 8) & 0xFF)
    code.compare_port(0x50, 0x00)


def program() -> Program:
    code = Builder()
    code.emit(0xFA)  # cli
    code.out(0x60, 0x80)  # enable Color mode before Color-only SDMA ports

    # Writes must be visible before first enable, including 20-bit masks.
    _set_source(code, 0x00)
    _set_length(code, 3)
    _check_counters(code, 0x00, 3)
    code.compare_port(0x52, 0x00)
    code.marker(ord("P"))

    # One-shot reaches exact terminal counters and clears only enable.
    code.out(0x52, 0x83)
    code.wait_control_off("one_shot_done")
    _check_counters(code, 0x03, 0)
    code.compare_port(0x52, 0x03)
    code.marker(ord("O"))

    # Enabling again with terminal length zero must fail without rewinding.
    code.out(0x52, 0x83)
    code.compare_port(0x52, 0x03)
    code.delay("failed_restart_delay")
    _check_counters(code, 0x03, 0)
    code.compare_port(0x52, 0x03)
    code.marker(ord("N"))

    # Disable after one byte, wait longer than a 24 kHz period, and prove the
    # live counters stay frozen.  Re-enable must consume the next byte.
    _set_source(code, 0x10)
    _set_length(code, 3)
    code.out(0x52, 0x83)
    code.wait_port("pause_after_one", 0x4E, 2)
    code.out(0x52, 0x03)
    _check_counters(code, 0x11, 2)
    code.delay("pause_delay")
    _check_counters(code, 0x11, 2)
    code.marker(ord("S"))
    code.out(0x52, 0x83)
    code.wait_control_off("resume_done")
    _check_counters(code, 0x13, 0)
    code.marker(ord("R"))

    # Source and length byte writes while active take effect immediately.
    _set_source(code, 0x20)
    _set_length(code, 4)
    code.out(0x52, 0x83)
    code.wait_port("edit_after_one", 0x4E, 3)
    code.out(0x4A, 0x30)
    code.out(0x4E, 2)
    _check_counters(code, 0x30, 2)
    code.marker(ord("E"))
    code.wait_control_off("edit_done")
    _check_counters(code, 0x32, 0)
    code.marker(ord("A"))

    # Active writes also update repeat shadows.  After F1050/F1051 the live
    # counters must reload the edited F1050/2 pair, not the original values.
    _set_source(code, 0x40)
    _set_length(code, 2)
    code.out(0x52, 0x8B)
    code.wait_port("repeat_original_one", 0x4E, 1)
    code.out(0x4A, 0x50)
    code.out(0x4E, 2)
    code.wait_port("repeat_edited_one", 0x4E, 1)
    code.wait_port("repeat_reloaded", 0x4E, 2)
    code.out(0x52, 0x0B)
    _check_counters(code, 0x50, 2)
    code.compare_port(0x52, 0x0B)
    code.marker(ord("T"))

    # Decrement mode consumes exact descending bytes and stops one below.
    _set_source(code, 0x63)
    _set_length(code, 4)
    code.out(0x52, 0xC3)
    code.wait_control_off("decrement_done")
    _check_counters(code, 0x5F, 0)
    code.compare_port(0x52, 0x43)
    code.marker(ord("D"))

    # Hold ticks still occur but freeze both counters and force Channel 2's
    # sample port to zero.  A live length-zero edit during hold must neither
    # stop the engine nor underflow.  Rewriting enabled control with zero live
    # length must then reject enable even for a 1->1 request; restore length,
    # re-enable hold for one more frozen tick, then unhold.
    _set_source(code, 0x70)
    _set_length(code, 2)
    code.out(0x89, 0xA5)
    code.out(0x52, 0x87)
    code.wait_port("hold_zero_one", 0x89, 0x00)
    code.out(0x4E, 0x00)
    code.out(0x89, 0xA5)
    code.wait_port("hold_zero_two", 0x89, 0x00)
    _check_counters(code, 0x70, 0)
    code.compare_port(0x52, 0x87)
    code.out(0x52, 0x87)
    code.compare_port(0x52, 0x07)
    _check_counters(code, 0x70, 0)
    code.out(0x4E, 0x02)
    code.out(0x89, 0xA5)
    code.out(0x52, 0x87)
    code.wait_port("hold_zero_three", 0x89, 0x00)
    _check_counters(code, 0x70, 2)
    code.compare_port(0x52, 0x87)
    code.marker(ord("H"))
    code.out(0x52, 0x83)
    code.wait_control_off("unhold_done")
    _check_counters(code, 0x72, 0)
    code.compare_port(0x89, SAMPLE_DATA[0x71])
    code.marker(ord("U"))

    code.marker(ord("Z"))
    code.label("success")
    code.branch(0xEB, "success")

    code.label("fail")
    code.marker(FAIL_MARKER)
    code.label("failed")
    code.branch(0xEB, "failed")
    return code.finish()


def footer() -> bytes:
    result = bytearray(16)
    result[0:5] = b"\xEA\x00\x00\x00\xF0"
    result[7] = 0x01  # Color cartridge.
    result[8] = 0x4B  # Repository-authored diagnostic ID.
    result[9] = 0x01
    result[12] = 0x04  # 16-bit ROM bus, horizontal orientation.
    return bytes(result)


def image() -> bytes:
    compiled = program().data
    if PROGRAM_OFFSET + len(compiled) > MARKER_OFFSET:
        raise ValueError("SDMA modes program overlaps identity marker")
    if MARKER_OFFSET + len(MARKER) > DATA_OFFSET:
        raise ValueError("SDMA identity marker overlaps sample data")
    result = bytearray(b"\xFF" * ROM_SIZE)
    result[PROGRAM_OFFSET : PROGRAM_OFFSET + len(compiled)] = compiled
    result[MARKER_OFFSET : MARKER_OFFSET + len(MARKER)] = MARKER
    result[DATA_OFFSET : DATA_OFFSET + len(SAMPLE_DATA)] = SAMPLE_DATA
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
        raise SystemExit(f"cannot generate SDMA modes probe: {error}") from error
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
