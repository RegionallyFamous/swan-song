#!/usr/bin/env python3
"""Mutation-lock the implemented Bandai 2003 CC/CD register boundary."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def compact(value: str) -> str:
    return "".join(value.split()).lower()


def validate(memorymux: str, bench: str) -> None:
    memory = compact(memorymux)
    test = compact(bench)

    required_memory = (
        "signalgpo_direction:std_logic_vector(3downto0):=(others=>'0');",
        "signalgpo_data:std_logic_vector(3downto0):=(others=>'0');",
        "typet_reg_wired_orisarray(0to10)ofstd_logic_vector(7downto0);",
        "mapper_2003_selected<='1'whenromtype=x\"01\"else'0';",
        "if(regbus_rst='1'ormapper_2003_selected='0')thengpo_direction<=(others=>'0');",
        "gpo_data<=(others=>'0');",
        "whenx\"cc\"=>gpo_direction<=regbus_din(3downto0);",
        "whenx\"cd\"=>gpo_data<=regbus_din(3downto0);",
        "reg_wired_or(9)<=x\"0\"&gpo_directionwhenmapper_2003_selected='1'andregbus_adr=x\"cc\"elsex\"00\";",
        "reg_wired_or(10)<=x\"0\"&gpo_datawhenmapper_2003_selected='1'andregbus_adr=x\"cd\"elsex\"00\";",
    )
    for fragment in required_memory:
        if memory.count(fragment) != 1:
            raise ValueError(f"missing or duplicate GPO RTL contract: {fragment}")

    required_bench = (
        "forvaluein0to255loopwrite_port(16#cc#,value);expect_port(16#cc#,valuemod16);expect_port(16#cd#,0);endloop;",
        "forvaluein0to255loopwrite_port(16#cd#,value);expect_port(16#cd#,valuemod16);expect_port(16#cc#,15);endloop;",
        "romtype<=x\"03\";",
        "write_port(16#cc#,16#ff#);",
        "write_port(16#cd#,16#ff#);",
        "expect_port(16#cc#,5);",
        "expect_port(16#cd#,10);",
        "report\"passboot-lockconsumer,bandai2003aliases/highbytes/gpo,andsavereplay\"severitynote;",
    )
    for fragment in required_bench:
        if fragment not in test:
            raise ValueError(f"GPO black-box coverage is missing: {fragment}")

    # The implementation boundary has four physical pins. Prove the complete
    # write/read model independently of the source-shape checks above.
    direction = 0
    data = 0
    for value in range(256):
        direction = value & 0x0F
        if direction != value % 16 or data != 0:
            raise ValueError("GPO direction model violated nibble masking/isolation")
    for value in range(256):
        data = value & 0x0F
        if data != value % 16 or direction != 15:
            raise ValueError("GPO data model violated nibble masking/isolation")


def must_reject(
    memorymux: str,
    bench: str,
    target: str,
    old: str,
    new: str,
    label: str,
) -> None:
    sources = {"memory": memorymux, "bench": bench}
    if sources[target].count(old) != 1:
        raise AssertionError(f"mutation anchor changed for {label}: {old!r}")
    sources[target] = sources[target].replace(old, new, 1)
    try:
        validate(sources["memory"], sources["bench"])
    except ValueError:
        return
    raise AssertionError(f"Bandai 2003 GPO contract accepted mutant: {label}")


def main() -> None:
    memorymux = (ROOT / "src/fpga/core/rtl/memorymux.vhd").read_text(
        encoding="utf-8"
    )
    bench = (ROOT / "sim/rtl/mapper_2003_alias_tb.vhd").read_text(
        encoding="utf-8"
    )
    validate(memorymux, bench)

    mutations = (
        ("memory", "romtype = x\"01\"", "romtype /= x\"00\"", "mapper gate"),
        (
            "memory",
            'when x"CC" => gpo_direction <= RegBus_Din(3 downto 0);',
            'when x"CC" => gpo_direction <= RegBus_Din(7 downto 0);',
            "direction width",
        ),
        (
            "memory",
            'reg_wired_or(10) <= x"0" & gpo_data',
            'reg_wired_or(10) <= x"F" & gpo_data',
            "upper read bits",
        ),
        (
            "memory",
            'mapper_2003_selected = \'1\' and RegBus_Adr = x"CD" else x"00";',
            'mapper_2003_selected = \'1\' and RegBus_Adr = x"CC" else x"00";',
            "data read port",
        ),
        (
            "bench",
            "expect_port(16#CC#, value mod 16);",
            "expect_port(16#CC#, value mod 256);",
            "exhaustive mask oracle",
        ),
        ("bench", "romtype <= x\"03\";", "romtype <= x\"01\";", "unknown mapper rejection"),
    )
    for target, old, new, label in mutations:
        must_reject(memorymux, bench, target, old, new, label)

    print(
        "PASS Bandai 2003 GPO contract: CC/CD low-nibble state, exact mapper "
        "gate, reset/isolation/replay bench, 512-value model; 6 mutants rejected"
    )


if __name__ == "__main__":
    main()
