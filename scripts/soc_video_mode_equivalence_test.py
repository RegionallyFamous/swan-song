#!/usr/bin/env python3
"""Exhaustive $60 raw-register to canonical GPU-mode equivalence proof.

The standalone controller stores the documented raw byte, while production GPU
consumers receive one of four effective modes.  This model checks every byte on
both physical console models against the prerequisite behavior implemented by
Mesen2 b9fa69d and the mode predicates in ares 449b937.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOC = ROOT / "src/fpga/core/rtl/soc_control.vhd"
GPU = ROOT / "src/fpga/core/rtl/gpu.vhd"
GPU_BG = ROOT / "src/fpga/core/rtl/gpu_bg.vhd"
TOP = ROOT / "src/fpga/core/rtl/swanTop.vhd"

DISP_MODE_MASK = 0xEB
VALID_RAW_MODES = frozenset((0b000, 0b100, 0b110, 0b111))


@dataclass(frozen=True)
class Behavior:
    grayscale: bool
    depth4: bool
    packed: bool
    extended_tile_index: bool
    extended_sprite_base: bool


def canonical_mode(raw: int, color_model: bool) -> int:
    """Mesen-style Color -> 4bpp -> packed prerequisite chain."""

    stored = (raw & DISP_MODE_MASK) if color_model else 0
    if not (stored & 0x80):
        return 0b000
    if not (stored & 0x40):
        return 0b100
    if not (stored & 0x20):
        return 0b110
    return 0b111


def canonical_behavior(mode: int) -> Behavior:
    return Behavior(
        grayscale=(mode >> 1) == 0,
        depth4=((mode >> 1) & 0b11) == 0b11,
        packed=bool(mode & 0b001),
        extended_tile_index=bool(mode & 0b100),
        extended_sprite_base=(mode >> 1) != 0,
    )


def ares_behavior(raw: int, color_model: bool) -> Behavior:
    """Equivalent of ares PPU::grayscale/depth/packed and OAM-base rules."""

    stored = (raw & DISP_MODE_MASK) if color_model else 0
    mode = (stored >> 5) & 0b111
    grayscale = not bool(mode & 0b100)
    return Behavior(
        grayscale=grayscale,
        depth4=((mode >> 1) & 0b11) == 0b11,
        packed=mode == 0b111,
        extended_tile_index=bool(mode & 0b100),
        extended_sprite_base=not grayscale,
    )


def inherited_valid_behavior(raw: int) -> Behavior:
    """Original GPU expressions, restricted to the four valid raw modes."""

    stored = raw & DISP_MODE_MASK
    mode = (stored >> 5) & 0b111
    assert mode in VALID_RAW_MODES
    upper = mode >> 1
    return Behavior(
        grayscale=upper == 0,
        depth4=upper == 0b11,
        packed=bool(mode & 1),
        extended_tile_index=bool(mode & 0b100),
        extended_sprite_base=upper != 0,
    )


def validate_routing() -> None:
    soc = SOC.read_text(encoding="utf-8")
    gpu = GPU.read_text(encoding="utf-8")
    gpu_bg = GPU_BG.read_text(encoding="utf-8")
    top = TOP.read_text(encoding="utf-8")

    assert 'DISP_MODE_MASK  : std_logic_vector(7 downto 0) := x"EB"' in soc
    assert 'video_mode           <= "000" when is_color_model = \'0\' or disp_mode_reg(7) = \'0\' else' in soc
    assert '"100" when disp_mode_reg(6) = \'0\' else' in soc
    assert '"110" when disp_mode_reg(5) = \'0\' else' in soc
    assert 'reg_data_out     <= disp_mode_reg;' in soc

    # Screen-map base width is a physical-model property: three base bits on
    # mono hardware and four on Color hardware, even in grayscale video mode.
    assert "isColor        => isColor," in gpu
    assert 'tilemapAddress <= "00" & screenbase(2 downto 0)' in gpu_bg
    assert "when isColor = '0' else" in gpu_bg
    assert "'0' & screenbase &" in gpu_bg

    # Extended tile indexing, tile format, palette path, sprite format, and
    # both line-144 OAM-base snapshots consume only canonical mode bits.
    assert gpu.count("tilemapSize    => video_mode(2)") == 2
    assert "tilemapSize = '1' and isColor = '1'" in gpu_bg
    assert "depth2      <= '1' when video_mode(2 downto 1) /= \"11\"" in gpu
    assert "isGray      <= '1' when video_mode(2 downto 1) = \"00\"" in gpu
    assert gpu.count("packed         => video_mode(0)") == 3
    assert gpu.count('if (video_mode(2 downto 1) = "00") then') == 2
    assert "spriteRow0CurrentDepth2     <= depth2;" in gpu
    assert "spriteRow0PendingDepth2     <= depth2;" in gpu
    assert "spriteRow0CurrentPacked     <= video_mode(0);" in gpu
    assert "spriteRow0PendingPacked     <= video_mode(0);" in gpu

    # The central owner preserves raw Color readback, while mono $60 remains
    # unmapped and the production bus supplies its established 90h value.
    assert 'elsif (reg_addr = x"60" and is_color_model = \'1\') then' in soc
    assert 'regIsMapped <= soc_port_60_mapped when RegBus_Adr = x"60" else' in top
    assert 'RegBus_Dout_mapped <= RegBus_Dout when (isColor or regIsMapped) else x"90";' in top
    assert "video_mode     => soc_video_mode," in top


def main() -> None:
    validate_routing()

    invalid_modes_seen: set[int] = set()
    for color_model in (False, True):
        for raw in range(256):
            stored = (raw & DISP_MODE_MASK) if color_model else 0
            mode = canonical_mode(raw, color_model)
            expected = ares_behavior(raw, color_model)
            actual = canonical_behavior(mode)
            assert actual == expected, (color_model, raw, mode, actual, expected)

            if color_model:
                # Reserved bits are masked, but every implemented raw field is
                # preserved for readback even when its prerequisites are false.
                assert stored == raw & DISP_MODE_MASK
                raw_mode = (stored >> 5) & 0b111
                if raw_mode in VALID_RAW_MODES:
                    assert actual == inherited_valid_behavior(raw)
                else:
                    invalid_modes_seen.add(raw_mode)
            else:
                # Mono ignores writes, exports mono behavior, and hands $60 to
                # the top-level open-bus policy rather than retaining state.
                assert stored == 0 and mode == 0 and actual == ares_behavior(0, False)

    assert invalid_modes_seen == {0b001, 0b010, 0b011, 0b101}
    print(
        "PASS exhaustive $60 canonical GPU equivalence: 256 raw bytes x 2 models, "
        "EB readback mask, mono open bus, map-base width, 2/4bpp, packed, "
        "final144 snapshots, and invalid prerequisite modes"
    )


if __name__ == "__main__":
    main()
