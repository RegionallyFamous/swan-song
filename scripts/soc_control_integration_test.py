#!/usr/bin/env python3
"""Mutation-lock production ownership and routing for $A0/$60."""

from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def validate(files: dict[str, str]) -> None:
    top = files["top"]
    gpu = files["gpu"]
    memory = files["memory"]
    translate = files["translate"]
    qsf = files["qsf"]
    sim = files["sim"]

    assert "type t_reg_wired_or is array(0 to 8)" in top
    assert top.count("isoc_control : entity work.soc_control") == 1
    soc_start = top.index("isoc_control : entity work.soc_control")
    soc_block = top[soc_start : top.index("   );", soc_start)]
    assert "reset                  => RegBus_rst," in soc_block
    assert "reg_data_out           => reg_wired_or(8)," in soc_block
    assert "state_load             => '0'," in soc_block
    assert 'regIsMapped <= soc_port_60_mapped when RegBus_Adr = x"60" else' in top
    assert re.search(
        r"imemorymux\s*:.*?isColor\s*=>\s*isColor,.*?"
        r"color_enabled\s*=>\s*soc_color_enabled,.*?"
        r"boot_rom_locked\s*=>\s*soc_boot_rom_locked,",
        top,
        re.S,
    )
    assert re.search(
        r"idma\s*:.*?isColor\s*=>\s*soc_color_enabled,.*?"
        r"cartridge_rom_word\s*=>\s*soc_cartridge_rom_word,.*?"
        r"cartridge_rom_slow\s*=>\s*soc_cartridge_rom_slow,",
        top,
        re.S,
    )
    assert re.search(
        r"igpu\s*:.*?isColor\s*=>\s*isColor,.*?"
        r"video_mode\s*=>\s*soc_video_mode,",
        top,
        re.S,
    )

    assert "iREG_HW_FLAGS" not in memory
    assert "HW_FLAGS_set" not in memory
    assert "reg_wired_or(4) <= (others => '0');" in memory
    assert memory.count("boot_rom_locked = '0'") == 2
    assert "color_enabled        : in  std_logic := '1';" in memory
    assert (
        "if (color_enabled = '0' and cpu_addr(15 downto 14) /= \"00\") then"
        in memory
    )

    assert "iDISP_MODE" not in gpu
    assert "signal DISP_MODE" not in gpu
    assert "reg_wired_or(24) <= (others => '0');" in gpu
    assert "video_mode     : in  std_logic_vector(2 downto 0)" in gpu
    assert "depth2      <= '1' when video_mode(2 downto 1) /= \"11\"" in gpu
    assert "isGray      <= '1' when video_mode(2 downto 1) = \"00\"" in gpu

    translate_order = [
        translate.index("src/fpga/core/rtl/soc_control.vhd"),
        translate.index("src/fpga/core/rtl/swanTop.vhd"),
    ]
    assert translate_order[0] < translate_order[1]
    assert qsf.count("VHDL_FILE core/rtl/soc_control.vhd") == 1
    assert qsf.index("VHDL_FILE core/rtl/soc_control.vhd") < qsf.index(
        "VHDL_FILE core/rtl/swanTop.vhd"
    )
    assert '#include "open_ipl.hpp"' in sim
    assert "swansong::open_ipl::make(" in sim
    assert "top->open_ipl_word_width = open_ipl_word_width;" in sim
    assert "--bios" not in sim


def must_reject(files: dict[str, str], key: str, old: str, new: str, label: str) -> None:
    mutant = dict(files)
    assert mutant[key].count(old) == 1, (key, old)
    mutant[key] = mutant[key].replace(old, new, 1)
    try:
        validate(mutant)
    except (AssertionError, ValueError):
        return
    raise AssertionError(f"soc_control integration accepted mutant: {label}")


def main() -> None:
    files = {
        "top": read("src/fpga/core/rtl/swanTop.vhd"),
        "gpu": read("src/fpga/core/rtl/gpu.vhd"),
        "memory": read("src/fpga/core/rtl/memorymux.vhd"),
        "translate": read("sim/verilator/translate_vhdl.sh"),
        "qsf": read("src/fpga/ap_core.qsf"),
        "sim": read("sim/verilator/sim_main.cpp"),
    }
    validate(files)

    mutations = [
        ("top", "reset                  => RegBus_rst,", "reset                  => reset,", "general-reset coupling"),
        ("top", "state_load             => '0',", "state_load             => load_state,", "parallel state restore"),
        ("top", "isColor           => soc_color_enabled,", "isColor           => isColor,", "physical-model DMA gate"),
        ("top", "video_mode     => soc_video_mode,", "video_mode     => \"000\",", "disconnected video mode"),
        ("memory", "reg_wired_or(4) <= (others => '0');", "reg_wired_or(4) <= x\"80\";", "second A0 data owner"),
        ("top", "color_enabled        => soc_color_enabled,", "color_enabled        => isColor,", "physical-model IRAM gate"),
        ("memory", "if (color_enabled = '0' and cpu_addr(15 downto 14) /= \"00\") then", "if (isColor = '0' and cpu_addr(15 downto 14) /= \"00\") then", "upper IRAM ignores effective Color mode"),
        ("gpu", "reg_wired_or(24) <= (others => '0');", "reg_wired_or(24) <= x\"80\";", "second 60 data owner"),
        ("sim", "top->open_ipl_word_width = open_ipl_word_width;", "top->open_ipl_word_width = false;", "footer-selected Open IPL bus width"),
    ]
    for key, old, new, label in mutations:
        must_reject(files, key, old, new, label)

    print(
        "PASS soc_control production integration: sole A0/60 ownership, "
        "RegBus replay reset, mono handoff, physical/effective model split, "
        "GPU/DMA/memory consumers, source order, built-in Open IPL; "
        "9 mutants rejected"
    )


if __name__ == "__main__":
    main()
