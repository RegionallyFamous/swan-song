#!/usr/bin/env python3
"""Mutation-lock the standalone WonderSwan $A0/$60 control contract."""

from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
RTL = ROOT / "src/fpga/core/rtl/soc_control.vhd"


def validate(source: str) -> None:
    assert 'A0_WRITE_MASK   : std_logic_vector(7 downto 0) := x"0D"' in source
    assert 'DISP_MODE_MASK  : std_logic_vector(7 downto 0) := x"EB"' in source
    assert 'COLOR_RESET_60  : std_logic_vector(7 downto 0) := x"0A"' in source
    assert re.search(
        r"if \(reset = '1'\) then.*?if \(is_color_model = '1'\) then\s+"
        r"disp_mode_reg <= COLOR_RESET_60;\s+else\s+"
        r"disp_mode_reg <= \(others => '0'\);\s+end if;",
        source,
        re.DOTALL,
    )
    assert "boot_rom_locked_reg <= boot_rom_locked_reg or masked_a0(0);" in source
    assert "rom_word_reg        <= masked_a0(2);" in source
    assert "rom_slow_reg        <= masked_a0(3);" in source
    assert "disp_mode_reg <= masked_60;" in source
    assert "port_60_mapped <= is_color_model;" in source
    assert 'elsif (reg_write = \'1\' and reg_addr = x"60") then' in source
    assert "color_enabled        <= is_color_model and disp_mode_reg(7);" in source
    assert (
        "video_4bpp           <= is_color_model and disp_mode_reg(7) and "
        "disp_mode_reg(6);"
    ) in source
    assert re.search(
        r"video_4bpp_packed\s+<= is_color_model and disp_mode_reg\(7\) and\s+"
        r"disp_mode_reg\(6\) and disp_mode_reg\(5\);",
        source,
    )
    assert re.search(
        r'video_mode\s+<= "000" when is_color_model = \'0\' or '
        r'disp_mode_reg\(7\) = \'0\' else\s+'
        r'"100" when disp_mode_reg\(6\) = \'0\' else\s+'
        r'"110" when disp_mode_reg\(5\) = \'0\' else\s+"111";',
        source,
    )
    assert re.search(
        r'elsif \(reg_addr = x"60" and is_color_model = \'1\'\) then\s+'
        r"reg_data_out\s+<= disp_mode_reg;\s+"
        r"reg_read_mapped\s+<= '1';\s+"
        r"reg_write_mapped <= '1';",
        source,
    )
    assert "Mesen2 retains undocumented $60 bit 2" in source
    assert "SoC&oldid=641" in source
    assert "Boot_ROM&oldid=679" in source
    assert "ares/blob/449b93716fb162632de2fd43bf2eba2064fa43f2" in source
    assert "Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2" in source


def must_reject(source: str, label: str) -> None:
    try:
        validate(source)
    except AssertionError:
        return
    raise AssertionError(f"soc_control contract accepted mutant: {label}")


def mutate_once(source: str, old: str, new: str) -> str:
    assert source.count(old) == 1, old
    return source.replace(old, new, 1)


def main() -> None:
    source = RTL.read_text(encoding="utf-8")
    validate(source)

    mutants = {
        "A0 reserved-bit mask": mutate_once(source, 'x"0D"', 'x"0F"'),
        "Color $60 mask": mutate_once(source, 'x"EB"', 'x"EF"'),
        "Color $60 reset value": mutate_once(source, 'x"0A"', 'x"00"'),
        "Color $60 reset disabled": mutate_once(
            source,
            "disp_mode_reg <= COLOR_RESET_60;",
            "disp_mode_reg <= (others => '0');",
        ),
        "mono $60 incorrectly mapped": mutate_once(
            source,
            "port_60_mapped <= is_color_model;",
            "port_60_mapped <= '1';",
        ),
        "boot lock replace instead of sticky": mutate_once(
            source,
            "boot_rom_locked_reg <= boot_rom_locked_reg or masked_a0(0);",
            "boot_rom_locked_reg <= masked_a0(0);",
        ),
        "$60 sticky instead of replace": mutate_once(
            source,
            "disp_mode_reg <= masked_60;",
            "disp_mode_reg <= disp_mode_reg or masked_60;",
        ),
        "mono $60 write accepted": mutate_once(
            source,
            'elsif (reg_write = \'1\' and reg_addr = x"60") then',
            'elsif (reg_write = \'1\' and reg_addr = x"60") or is_color_model = \'0\' then',
        ),
        "4bpp ignores Color prerequisite": mutate_once(
            source,
            "video_4bpp           <= is_color_model and disp_mode_reg(7) and disp_mode_reg(6);",
            "video_4bpp           <= is_color_model and disp_mode_reg(6);",
        ),
        "packed ignores 4bpp prerequisite": mutate_once(
            source,
            "disp_mode_reg(6) and disp_mode_reg(5);",
            "disp_mode_reg(5);",
        ),
        "mode ignores Color prerequisite": mutate_once(
            source,
            '"000" when is_color_model = \'0\' or disp_mode_reg(7) = \'0\' else',
            '"000" when is_color_model = \'0\' else',
        ),
        "Color 2bpp canonical encoding": mutate_once(
            source,
            '"100" when disp_mode_reg(6) = \'0\' else',
            '"101" when disp_mode_reg(6) = \'0\' else',
        ),
    }
    for label, mutant in mutants.items():
        must_reject(mutant, label)

    print(
        "PASS soc_control source contract and mutants "
        "A0-mask,60-mask,60-reset,mono-map,boot-sticky,60-replace,mono-write,"
        "video-prerequisites,normalized-mode"
    )


if __name__ == "__main__":
    main()
