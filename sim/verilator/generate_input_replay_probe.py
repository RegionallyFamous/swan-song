#!/usr/bin/env python3
"""Generate an open WonderSwan keypad/replay integration fixture.

Both outputs are build artifacts.  The authored 80186 program selects the
horizontal keypad row at port B5h, waits for physical X2 (matrix bit 1), emits
the ASCII-like mapper marker ``I``/``N``, waits for release, then emits ``P``.
The marker is unreachable without the requested press/release sequence.

The physical X2 mapping is corroborated by the current RTL and primary
reference implementations/specification:

* ``src/fpga/core/rtl/joypad.vhd`` maps horizontal X2 to B5h bit 1.
* https://ws.nesdev.org/w/index.php?title=Keypad&oldid=618
* https://github.com/ares-emulator/ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2/ares/ws/cpu/keypad.cpp#L1-L38
"""

from __future__ import annotations

import argparse
from pathlib import Path


ROM_SIZE = 128 * 1024
PROGRAM_OFFSET = 0x10000
FOOTER_OFFSET = ROM_SIZE - 16
ROM_NAME = "input_replay_probe.ws"
SCRIPT_NAME = "input_replay_probe.input"
MARKER = b"SWAN-SONG-INPUT-REPLAY-PROBE-V1\0"
MARKER_OFFSET = 0x10100

# The raw source bytes are deliberately part of the fixture contract.  The
# comment makes the raw-source hash differ from the normalized semantic hash,
# allowing the manifest verifier to prove that both identities are checked.
INPUT_SCRIPT = (
    b"# Physical X2 is right on a horizontal WonderSwan cartridge.\n"
    b"1000 x2\n"
    b"5000 none\n"
)

# 80186 machine code at physical F0000h (offset 10000h in this 128 KiB image):
#
#   cli
#   mov al, 20h; out B5h, al       ; select horizontal X row
# poll_press:
#   nop; nop; nop; nop             ; documented matrix settling interval
#   in al, B5h; test al, 02h
#   jz poll_press
#   mov al, 'I'; out C0h, al
#   mov al, 'N'; out C2h, al
# poll_release:
#   nop; nop; nop; nop
#   in al, B5h; test al, 02h
#   jnz poll_release
#   mov al, 'P'; out C3h, al
# hang:
#   jmp hang
#
# C0/C2/C3 are cartridge bank registers. The probe writes them only after the
# corresponding instruction has already been fetched, then immediately enters
# the next local sequence; the three writes form the trace marker "INP".
PROGRAM = bytes(
    (
        0xFA,
        0xB0, 0x20,
        0xE6, 0xB5,
        0x90, 0x90, 0x90, 0x90,
        0xE4, 0xB5,
        0xA8, 0x02,
        0x74, 0xF6,
        0xB0, 0x49,
        0xE6, 0xC0,
        0xB0, 0x4E,
        0xE6, 0xC2,
        0x90, 0x90, 0x90, 0x90,
        0xE4, 0xB5,
        0xA8, 0x02,
        0x75, 0xF6,
        0xB0, 0x50,
        0xE6, 0xC3,
        0xEB, 0xFE,
    )
)

# Mapper-write instruction starts, expressed as 20-bit physical PCs.
MARKER_ORIGIN_PCS = (0xF0011, 0xF0015, 0xF0023)


def footer() -> bytes:
    """Return an authored horizontal mono cartridge footer."""

    result = bytearray(16)
    result[0:5] = b"\xEA\x00\x00\x00\xF0"  # jmp far F000:0000
    result[5] = 0x00  # Maintenance byte.
    result[6] = 0x00  # Homebrew/test developer ID.
    result[7] = 0x00  # Mono WonderSwan.
    result[8] = 0x49  # Repository-authored diagnostic ID.
    result[9] = 0x01  # Fixture format version.
    result[10] = 0x00  # 1 Mbit / 128 KiB ROM.
    result[11] = 0x00  # No save memory.
    result[12] = 0x04  # 16-bit ROM bus, horizontal orientation.
    result[13] = 0x00  # Standard mapper.
    return bytes(result)


def image() -> bytes:
    """Return the deterministic checksummed ROM image."""

    result = bytearray(b"\xFF" * ROM_SIZE)
    if PROGRAM_OFFSET + len(PROGRAM) > MARKER_OFFSET:
        raise ValueError("input-replay program overlaps identity marker")
    if MARKER_OFFSET + len(MARKER) > FOOTER_OFFSET:
        raise ValueError("input-replay identity marker overlaps footer")
    result[PROGRAM_OFFSET : PROGRAM_OFFSET + len(PROGRAM)] = PROGRAM
    result[MARKER_OFFSET : MARKER_OFFSET + len(MARKER)] = MARKER
    result[FOOTER_OFFSET:] = footer()
    result[-2:] = (sum(result[:-2]) & 0xFFFF).to_bytes(2, "little")
    return bytes(result)


def generate(output_dir: Path) -> tuple[Path, Path]:
    """Write the build-only ROM and raw replay script."""

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
        outputs = generate(args.output_dir)
    except (OSError, ValueError) as error:
        raise SystemExit(f"cannot generate input-replay probe: {error}") from error
    for path in outputs:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
