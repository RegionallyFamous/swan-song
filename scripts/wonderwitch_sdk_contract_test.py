#!/usr/bin/env python3
"""Validate the WWTM-derived WonderWitch SDK compatibility overlay."""

from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "sdk/wonderwitch-wwtm/include"

PROBE = r"""
#include <stdint.h>
#include <sys/bios.h>

_Static_assert(
    __builtin_types_compatible_p(__typeof__(bank_read_word(0, 0)), uint16_t),
    "bank_read_word must preserve AX"
);
_Static_assert(
    __builtin_types_compatible_p(__typeof__(sys_get_tick_count()), uint32_t),
    "sys_get_tick_count must preserve DX:AX"
);
_Static_assert(LCD_SLEEP_OFF == 0, "zero means display enabled");
_Static_assert(LCD_SLEEP_ON == 1, "one means display disabled/sleeping");

uint32_t wwtm_sdk_probe(uint16_t bank, uint16_t offset) {
    sram_set_map(bank);
    rom0_set_map(bank);
    rom1_set_map(bank);
    lcd_on();
    lcd_off();
    return sys_get_tick_count() ^ bank_read_word(bank, offset);
}
"""

ASM_PROBE = r"""
    .arch i186
    .code16
    .intel_syntax noprefix
#include <asm/wwtm_bios.inc>

    .global wwtm_asm_probe
wwtm_asm_probe:
    mov ah, WW_BANK_READ_WORD
    int WW_INT_BANK
    mov ah, WW_SYS_GET_TICK_COUNT
    int WW_INT_SYSTEM
    ret

    .if WW_TEXT_SCREEN_WIDTH != 28
    .error "text width must be decimal 28"
    .endif
    .if WW_TEXT_SCREEN_HEIGHT != 18
    .error "text height must be decimal 18"
    .endif
    .if WW_LCD_SLEEP_OFF != 0
    .error "LCD sleep-off polarity"
    .endif
    .if WW_SYS_SET_RESUME != 0x14
    .error "resume setter selector"
    .endif
"""


def require_source_contracts() -> None:
    bank = (OVERLAY / "sys/bank.h").read_text(encoding="utf-8")
    system = (OVERLAY / "sys/system.h").read_text(encoding="utf-8")
    display = (OVERLAY / "sys/disp.h").read_text(encoding="utf-8")
    assembly = (OVERLAY / "asm/wwtm_bios.inc").read_text(encoding="utf-8")

    required = {
        "bank setter": "bank_set_map(BANK_SRAM, (bank_id))",
        "word width": "static inline uint16_t bank_read_word",
        "tick width": "static inline uint32_t sys_get_tick_count",
        "tick register pair": '\"=A\" (result)',
        "sleep-off value": "#define LCD_SLEEP_OFF 0",
        "sleep-on value": "#define LCD_SLEEP_ON 1",
        "assembly text width": ".equ WW_TEXT_SCREEN_WIDTH,  28",
        "assembly text height": ".equ WW_TEXT_SCREEN_HEIGHT, 18",
        "assembly tick selector": ".equ WW_SYS_GET_TICK_COUNT,       0x03",
    }
    combined = "\n".join((bank, system, display, assembly))
    for label, fragment in required.items():
        if combined.count(fragment) != 1:
            raise ValueError(f"missing or duplicate {label} contract: {fragment}")


def compiler_flags(toolchain: Path) -> tuple[Path, list[str]]:
    compiler = toolchain / "toolchain/gcc-ia16-elf/bin/ia16-elf-gcc"
    target = toolchain / "target/wwitch"
    flags = [
        "-std=gnu11",
        "-D__WONDERFUL__",
        "-D__WONDERFUL_WWITCH__",
        "-march=v30mz",
        "-mtune=v30mz",
        "-mregparmcall",
        "-ffreestanding",
        "-mcmodel=small",
        "-mno-callee-assume-ss-data-segment",
        "-msegelf",
        "-mno-segment-relocation-stuff",
        "-fexec-charset=shift-jis",
        "-isystem",
        str(target / "include"),
        "-isystem",
        str(target / "libc/include"),
        "-Wall",
        "-Werror",
    ]
    return compiler, flags


def compile_probe(toolchain: Path) -> None:
    compiler, flags = compiler_flags(toolchain)
    if not compiler.is_file():
        print(f"SKIP compile probe: {compiler} is not installed")
        return

    with tempfile.TemporaryDirectory(prefix="wwtm-sdk-contract-") as tmp:
        work = Path(tmp)
        source = work / "probe.c"
        source.write_text(PROBE, encoding="utf-8")

        vendor = subprocess.run(
            [str(compiler), *flags, "-c", str(source), "-o", str(work / "vendor.o")],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if vendor.returncode == 0:
            raise ValueError(
                "the installed headers unexpectedly satisfy every WWTM contract; "
                "review whether the overlay is still needed"
            )

        fixed = subprocess.run(
            [
                str(compiler),
                "-I",
                str(OVERLAY),
                *flags,
                "-c",
                str(source),
                "-o",
                str(work / "fixed.o"),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if fixed.returncode != 0:
            raise ValueError(f"overlay compile failed:\n{fixed.stderr}")

        asm_source = work / "probe.s"
        asm_source.write_text(ASM_PROBE, encoding="utf-8")
        assembled = subprocess.run(
            [
                str(compiler),
                "-I",
                str(OVERLAY),
                *flags,
                "-x",
                "assembler-with-cpp",
                "-c",
                str(asm_source),
                "-o",
                str(work / "asm.o"),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if assembled.returncode != 0:
            raise ValueError(f"assembly include compile failed:\n{assembled.stderr}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--toolchain",
        type=Path,
        default=Path("/opt/wonderful"),
        help="Wonderful Toolchain root (default: /opt/wonderful)",
    )
    args = parser.parse_args()

    require_source_contracts()
    compile_probe(args.toolchain)
    print(
        "PASS WonderWitch SDK overlay: map setters, 16-bit bank word, "
        "32-bit ticks, and LCD sleep polarity"
    )


if __name__ == "__main__":
    main()
