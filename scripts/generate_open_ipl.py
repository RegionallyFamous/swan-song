#!/usr/bin/env python3
# Project-authored Swan Song Open IPL generator. See LICENSING.md for the
# unresolved original-work license declaration and combined-work review.
"""Generate the FPGA and Verilator boot images for SwanSong Open IPL v3.

The byte generator below is a direct, independently auditable port of the
WonderSwan and WonderSwan Color paths in SwanSong Desktop's
``swan_song_open_ipl`` implementation. The generated VHDL stores the common
8-bit-bus/protected-owner image in one inferred boot memory per model and
patches only words that differ for the three other footer combinations. It
therefore does not instantiate a second copy of either boot memory. The
generated C++ header stores only each image's 256-byte executable tail and
reconstructs the NOP-filled 4/8-KiB container for the Verilator harness.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
CPP_PATH = ROOT / "sim/verilator/open_ipl.hpp"
GENERATED_BEGIN = "   -- BEGIN GENERATED SWANSONG OPEN IPL V3"
GENERATED_END = "   -- END GENERATED SWANSONG OPEN IPL V3"
NOP = 0x90
NOP_WORD = 0x9090
STARTUP_FROM_END = 256
RESET_VECTOR_FROM_END = 16


@dataclass(frozen=True)
class Model:
    name: str
    color: bool
    size: int
    address_width: int
    rtl_path: Path


MODELS = (
    Model(
        name="mono",
        color=False,
        size=4096,
        address_width=11,
        rtl_path=ROOT / "src/fpga/core/rtl/swanbios.vhd",
    ),
    Model(
        name="color",
        color=True,
        size=8192,
        address_width=12,
        rtl_path=ROOT / "src/fpga/core/rtl/swanbioscolor.vhd",
    ),
)


def make_open_ipl(
    *, color: bool, word_width: bool, protect_owner_area: bool
) -> bytes:
    """Return the exact Open IPL v3 image for one FPGA-relevant variant."""

    boot = bytearray([NOP] * (8192 if color else 4096))
    hardware_flags = 0x81 | (0x02 if color else 0) | (0x04 if word_width else 0)
    ram_handoff = bytes(
        (
            0xB0,
            hardware_flags,  # mov al, HW_FLAGS
            0xE6,
            0xA0,  # out 0xa0, al
            0xEA,
            0x00,
            0x00,
            0xFF,
            0xFF,  # jmp far 0xffff:0000
        )
    )
    startup = bytearray()

    def emit(values: Iterable[int]) -> None:
        startup.extend(values)

    def emit_out8(port: int, value: int) -> None:
        emit((0xB0, value, 0xE6, port))  # mov al,value; out port,al

    emit((0xFA,))  # cli
    emit((0x31, 0xC0))  # xor ax,ax
    emit((0x8E, 0xD8))  # mov ds,ax
    emit((0x8E, 0xC0))  # mov es,ax
    emit((0x8E, 0xD0))  # mov ss,ax
    emit((0xBC, 0x00, 0x20))  # mov sp,0x2000
    emit_out8(0x14, 0x01)
    emit_out8(0x16, 0x9E)
    emit_out8(0x17, 0x9B)
    if color:
        emit_out8(0x60, 0x0A)
    emit_out8(0xB5, 0x40)
    emit_out8(0xBC, 0x00 if color else 0x30)
    emit_out8(0xBD, 0x13 if color else 0x01)
    emit_out8(0xBE, 0x40)  # EWEN
    if protect_owner_area:
        emit_out8(0xBE, 0x80)

    for index, value in enumerate(ram_handoff):
        address = 0x0400 + index
        emit((0xC6, 0x06, address & 0xFF, address >> 8, value))

    emit((0xB9, 0x00, 0x00))  # mov cx,0
    emit((0xBA, 0x01, 0x00))  # mov dx,1
    emit((0xBB, 0x43 if color else 0x40, 0x00))
    emit((0xBD, 0x00, 0x00))  # mov bp,0
    emit((0xBE, 0x35 if color else 0x3D, 0x04 if color else 0x02))
    emit((0xBF, 0x0B if color else 0x0D, 0x04))
    emit((0xB8, 0x00, 0xFE if color else 0xFF))
    emit((0x8E, 0xD8))  # mov ds,ax
    emit((0xB8, 0x86 if color else 0x82, 0xF0))
    emit((0x50, 0x9D))  # push ax; popf
    emit((0xB8, hardware_flags, 0xFF))
    emit((0xEA, 0x00, 0x04, 0x00, 0x00))

    reset_vector = bytes((0xEA, 0x00, 0x00, 0xF0, 0xFF))
    if len(startup) > STARTUP_FROM_END - RESET_VECTOR_FROM_END:
        raise ValueError(f"{len(startup)}-byte startup exceeds its reserved window")
    boot[-STARTUP_FROM_END : -STARTUP_FROM_END + len(startup)] = startup
    boot[-RESET_VECTOR_FROM_END : -RESET_VECTOR_FROM_END + len(reset_vector)] = (
        reset_vector
    )
    return bytes(boot)


def words(image: bytes) -> tuple[int, ...]:
    if len(image) % 2:
        raise ValueError("Open IPL image length is not word-aligned")
    return tuple(
        image[index] | (image[index + 1] << 8)
        for index in range(0, len(image), 2)
    )


def sparse_entries(
    values: tuple[int, ...], reference: tuple[int, ...] | None = None
) -> tuple[tuple[int, int], ...]:
    if reference is None:
        return tuple(
            (index, value)
            for index, value in enumerate(values)
            if value != NOP_WORD
        )
    if len(values) != len(reference):
        raise ValueError("variant/reference word counts differ")
    return tuple(
        (index, value)
        for index, (value, common) in enumerate(zip(values, reference, strict=True))
        if value != common
    )


def format_aggregate_entries(
    entries: tuple[tuple[int, int], ...], indent: str
) -> list[str]:
    return [f'{indent}{index} => x"{value:04X}",' for index, value in entries]


def render_patch_case(
    variant: str,
    entries: tuple[tuple[int, int], ...],
) -> list[str]:
    lines = [f'         when "{variant}" =>']
    if not entries:
        lines.append("            return stored_word;")
        return lines
    lines.append("            case address_index is")
    lines.extend(
        f'               when {index} => return x"{value:04X}";'
        for index, value in entries
    )
    lines.append("               when others => return stored_word;")
    lines.append("            end case;")
    return lines


def model_variants(model: Model) -> dict[str, tuple[int, ...]]:
    variants: dict[str, tuple[int, ...]] = {}
    for protect_owner_area in (False, True):
        for word_width in (False, True):
            key = f"{int(protect_owner_area)}{int(word_width)}"
            variants[key] = words(
                make_open_ipl(
                    color=model.color,
                    word_width=word_width,
                    protect_owner_area=protect_owner_area,
                )
            )
    return variants


def render_generated_block(model: Model) -> str:
    variants = model_variants(model)
    base = variants["10"]  # protected owner area, 8-bit cartridge bus
    lines = [
        GENERATED_BEGIN,
        "   subtype t_boot_word is std_logic_vector(15 downto 0);",
        f"   type t_rom is array(0 to {len(base) - 1}) of t_boot_word;",
        "   constant OPEN_IPL_WORDS : t_rom :=",
        "   (",
    ]
    lines.extend(format_aggregate_entries(sparse_entries(base), "      "))
    lines.extend(
        (
            '      others => x"9090"',
            "   );",
            "   signal rom : t_rom := OPEN_IPL_WORDS;",
            "   attribute ramstyle : string;",
            '   attribute ramstyle of rom : signal is "M10K";',
            "",
            "   function open_ipl_read_word",
            "   (",
            "      address_index     : natural;",
            "      stored_word       : t_boot_word;",
            "      selected_width    : std_logic;",
            "      selected_protect  : std_logic",
            "   ) return t_boot_word is",
            "      variable variant : std_logic_vector(1 downto 0);",
            "   begin",
            "      variant := selected_protect & selected_width;",
            "      case variant is",
        )
    )
    for key in ("00", "01", "10", "11"):
        lines.extend(render_patch_case(key, sparse_entries(variants[key], base)))
    lines.extend(
        (
            "         when others => return (others => 'X');",
            "      end case;",
            "   end function;",
            GENERATED_END,
        )
    )
    return "\n".join(lines)


def format_cpp_tail(image: bytes) -> list[str]:
    tail = image[-STARTUP_FROM_END:]
    if image[:-STARTUP_FROM_END] != bytes((NOP,)) * (
        len(image) - STARTUP_FROM_END
    ):
        raise ValueError("Open IPL compact prefix is not entirely NOP-filled")
    return [
        "    " + ", ".join(f"0x{value:02x}" for value in tail[offset : offset + 16]) + ","
        for offset in range(0, len(tail), 16)
    ]


def render_cpp_header() -> str:
    lines = [
        "// Generated by scripts/generate_open_ipl.py; do not edit.",
        "// Project-authored Swan Song Open IPL data; see LICENSING.md.",
        "#pragma once",
        "",
        "#include <algorithm>",
        "#include <array>",
        "#include <cstddef>",
        "#include <cstdint>",
        "#include <vector>",
        "",
        "namespace swansong::open_ipl {",
        "",
        'inline constexpr const char* kIdentity = "open-bootstrap-v3";',
        f"inline constexpr std::size_t kTailSize = {STARTUP_FROM_END}u;",
        "inline constexpr std::size_t kVariantCount = 8u;",
        "using Tail = std::array<std::uint8_t, kTailSize>;",
        "",
        "// Index bits: color=4, protect_owner_area=2, word_width=1.",
        "inline constexpr std::array<Tail, kVariantCount> kTails = {{",
    ]
    for model in MODELS:
        for protect_owner_area in (False, True):
            for word_width in (False, True):
                image = make_open_ipl(
                    color=model.color,
                    word_width=word_width,
                    protect_owner_area=protect_owner_area,
                )
                lines.append(
                    "  Tail{{  // "
                    f"{model.name} word_width={int(word_width)} "
                    f"protect_owner_area={int(protect_owner_area)}"
                )
                lines.extend(format_cpp_tail(image))
                lines.append("  }},")
    lines.extend(
        (
            "}};",
            "",
            "constexpr std::size_t variant_index(bool color, bool word_width,",
            "                                    bool protect_owner_area) {",
            "  return (color ? 4u : 0u) | (protect_owner_area ? 2u : 0u) |",
            "         (word_width ? 1u : 0u);",
            "}",
            "",
            "inline std::vector<std::uint8_t> make(bool color, bool word_width,",
            "                                      bool protect_owner_area) {",
            "  std::vector<std::uint8_t> image(color ? 8192u : 4096u, 0x90u);",
            "  const auto& tail =",
            "      kTails[variant_index(color, word_width, protect_owner_area)];",
            "  std::copy(tail.begin(), tail.end(), image.end() - kTailSize);",
            "  return image;",
            "}",
            "",
            "}  // namespace swansong::open_ipl",
            "",
        )
    )
    return "\n".join(lines)


def replace_generated_block(source: str, block: str, path: Path) -> str:
    begin = source.find(GENERATED_BEGIN)
    end = source.find(GENERATED_END)
    if begin < 0 or end < begin:
        raise ValueError(f"missing generated Open IPL markers in {path}")
    end += len(GENERATED_END)
    return source[:begin] + block + source[end:]


def update_model(model: Model, *, check: bool) -> bool:
    source = model.rtl_path.read_text(encoding="utf-8")
    expected = replace_generated_block(
        source, render_generated_block(model), model.rtl_path
    )
    if expected == source:
        return False
    if check:
        raise SystemExit(f"generated Open IPL block is stale: {model.rtl_path}")
    model.rtl_path.write_text(expected, encoding="utf-8")
    return True


def update_cpp_header(*, check: bool) -> bool:
    expected = render_cpp_header()
    source = CPP_PATH.read_text(encoding="utf-8") if CPP_PATH.exists() else None
    if source == expected:
        return False
    if check:
        raise SystemExit(f"generated Open IPL header is stale: {CPP_PATH}")
    CPP_PATH.parent.mkdir(parents=True, exist_ok=True)
    CPP_PATH.write_text(expected, encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail instead of rewriting stale generated VHDL/C++",
    )
    arguments = parser.parse_args()
    changed = [
        model.rtl_path
        for model in MODELS
        if update_model(model, check=arguments.check)
    ]
    if update_cpp_header(check=arguments.check):
        changed.append(CPP_PATH)
    if not arguments.check:
        for path in changed:
            print(path.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
