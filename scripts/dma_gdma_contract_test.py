#!/usr/bin/env python3
"""Mutation-lock the WonderSwan General-DMA eligibility/timing contract."""

from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
RTL = ROOT / "src/fpga/core/rtl/dma.vhd"


def validate(source: str) -> None:
    assert "cartridge_rom_word : in std_logic := '1';" in source
    assert "cartridge_rom_slow : in std_logic := '0';" in source
    assert re.search(
        r'when x"0" => return true;\s+'
        r'when x"1" => return false;\s+'
        r"when others => return rom_word = '1' and rom_slow = '0';",
        source,
    )
    assert source.count(
        "gdma_source_valid(DMA_SRC, cartridge_rom_word, cartridge_rom_slow)"
    ) == 2
    assert re.search(
        r"if \(unsigned\(DMA_LEN\) > 0 and\s+"
        r"gdma_source_valid\(DMA_SRC, cartridge_rom_word, cartridge_rom_slow\)\) then\s+"
        r"dmaOn\s+<= '1';\s+state\s+<= WAITING;\s+waitcnt <= 0;",
        source,
    )
    assert re.search(
        r"when READING =>\s+"
        r"if \(gdma_source_valid\(DMA_SRC, cartridge_rom_word, cartridge_rom_slow\)\) then\s+"
        r"state\s+<= WRITING;\s+bus_read <= '1';\s+bus_addr <= unsigned\(DMA_SRC\);\s+"
        r"else\s+.*?state\s+<= IDLE;\s+dmaOn\s+<= '0';\s+DMA_CTRL\(7\) <= '0';",
        source,
        re.DOTALL,
    )
    assert "dma_active   <= dmaOn or bus_write;" in source
    assert "RegBus_wren_color <= RegBus_wren when isColor = '1' else '0';" in source
    assert source.count("RegBus_wren_color, RegBus_rst") == 15
    assert re.search(
        r"if \(isColor = '1' or sleep_savestate = '1'\) then\s+"
        r"RegBus_Dout <= wired_or;\s+else\s+"
        r"RegBus_Dout <= \(others => '0'\);",
        source,
    )
    assert re.search(
        r"gdma_start_accepted := true;.*?when IDLE =>\s+"
        r"if \(gdma_start_accepted\) then\s+.*?null;\s+elsif \(SDMA_CTRL_written",
        source,
        re.DOTALL,
    )
    assert re.search(
        r"if \(unsigned\(DMA_LEN\) = 2\) then\s+.*?"
        r"state\s+<= IDLE;\s+dmaOn\s+<= '0';\s+DMA_CTRL\(7\) <= '0';",
        source,
        re.DOTALL,
    )
    assert re.search(
        r"elsif \(not gdma_source_valid\(\s*gdma_next_source,\s*"
        r"cartridge_rom_word,\s*cartridge_rom_slow\)\) then\s+.*?"
        r"state\s+<= IDLE;\s+dmaOn\s+<= '0';\s+DMA_CTRL\(7\) <= '0';",
        source,
        re.DOTALL,
    )
    assert not re.search(r"state\s*<=\s*DONE", source)
    assert "DMA&oldid=562" in source
    assert "Mesen2/blob/b9fa69ddc6d0a331fb103fdb5eef6904305703c2" in source


def mutate_once(source: str, old: str, new: str) -> str:
    assert source.count(old) == 1, old
    return source.replace(old, new, 1)


def must_reject(source: str, label: str) -> None:
    try:
        validate(source)
    except AssertionError:
        return
    raise AssertionError(f"GDMA contract accepted mutant: {label}")


def main() -> None:
    source = RTL.read_text(encoding="utf-8")
    validate(source)

    mutants = {
        "default ROM byte bus": mutate_once(
            source,
            "cartridge_rom_word : in std_logic := '1';",
            "cartridge_rom_word : in std_logic := '0';",
        ),
        "default slow ROM": mutate_once(
            source,
            "cartridge_rom_slow : in std_logic := '0';",
            "cartridge_rom_slow : in std_logic := '1';",
        ),
        "SRAM accepted": mutate_once(
            source, 'when x"1" => return false;', 'when x"1" => return true;'
        ),
        "slow ROM accepted": mutate_once(
            source,
            "when others => return rom_word = '1' and rom_slow = '0';",
            "when others => return rom_word = '1';",
        ),
        "final write loses ownership": mutate_once(
            source,
            "dma_active   <= dmaOn or bus_write;",
            "dma_active   <= dmaOn;",
        ),
        "disabled Color DMA writes accepted": mutate_once(
            source,
            "RegBus_wren_color <= RegBus_wren when isColor = '1' else '0';",
            "RegBus_wren_color <= RegBus_wren;",
        ),
        "disabled Color DMA reads exposed": mutate_once(
            source,
            "if (isColor = '1' or sleep_savestate = '1') then",
            "if (true) then",
        ),
        "pending SDMA displaces accepted GDMA": mutate_once(
            source,
            "if (gdma_start_accepted) then",
            "if (false) then",
        ),
        "invalid next source consumes an abort CE": mutate_once(
            source,
            "elsif (not gdma_source_valid(\n"
            "                           gdma_next_source,\n"
            "                           cartridge_rom_word,\n"
            "                           cartridge_rom_slow)) then",
            "elsif (false) then",
        ),
        "extra DONE busy cycle": mutate_once(
            source,
            "state       <= IDLE;\n"
            "                     dmaOn       <= '0';\n"
            "                     DMA_CTRL(7) <= '0';\n"
            "                  else\n"
            "                     state <= READING;",
            "state       <= DONE;\n"
            "                     dmaOn       <= dmaOn;\n"
            "                     DMA_CTRL(7) <= DMA_CTRL(7);\n"
            "                  else\n"
            "                     state <= READING;",
        ),
    }
    for label, mutant in mutants.items():
        must_reject(mutant, label)

    # Remove the second predicate occurrence only: start remains guarded but
    # a boundary/config change before the next word no longer is.
    predicate = "gdma_source_valid(DMA_SRC, cartridge_rom_word, cartridge_rom_slow)"
    first = source.find(predicate)
    second = source.find(predicate, first + len(predicate))
    assert first >= 0 and second >= 0
    no_revalidation = source[:second] + "true" + source[second + len(predicate) :]
    must_reject(no_revalidation, "missing per-word revalidation")

    print(
        "PASS GDMA source/start/revalidation/final-write/timing contract and "
        "eleven mutants"
    )


if __name__ == "__main__":
    main()
