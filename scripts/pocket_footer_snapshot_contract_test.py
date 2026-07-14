#!/usr/bin/env python3
"""Lock the footer snapshot domain split and forbid timing waivers."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WONDERSWAN = ROOT / "src/fpga/core/wonderswan.sv"
CORE_TOP = ROOT / "src/fpga/core/core_top.v"
SDC = ROOT / "src/fpga/core/core_constraints.sdc"


def strip_comments(source: str) -> str:
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", source)


def compact(source: str) -> str:
    return re.sub(r"\s+", "", strip_comments(source))


def instance_body(source: str, module: str, instance: str) -> str:
    match = re.search(
        rf"\b{re.escape(module)}(?:\s*#\s*\(.*?\))?\s+"
        rf"{re.escape(instance)}\s*\((.*?)\)\s*;",
        strip_comments(source),
        flags=re.DOTALL,
    )
    if match is None:
        raise ValueError(f"missing {module} {instance} instance")
    return compact(match.group(1))


def tcl_commands(source: str) -> list[str]:
    logical = re.sub(r"\\\s*\n", " ", source)
    return [line.strip() for line in logical.splitlines() if line.strip()]


def verify_contract(wonderswan: str, core_top: str, sdc: str) -> None:
    swan = compact(wonderswan)

    snapshot = re.search(
        r"always@\(posedgeclk_sys_36_864\)begin"
        r"if\(cart_download_sys\)begin"
        r"footer_color_sys<=lastdata\[4\]\[8\];"
        r"footer_romtype_sys<=lastdata\[1\]\[15:8\];"
        r"footer_ramtype_sys<=lastdata\[2\]\[15:8\];"
        r"endend",
        swan,
    )
    if snapshot is None:
        raise ValueError("system footer snapshot is missing or is not title-load qualified")

    for declaration, message in (
        ("regfooter_color_sys=1'b0;", "model snapshot is absent or uninitialized"),
        ("reg[7:0]footer_romtype_sys=8'h00;", "RTC/model metadata snapshot is absent"),
        ("reg[7:0]footer_ramtype_sys=8'h00;", "RAM-type snapshot is absent"),
        ("wire[7:0]ramtype_mem=lastdata[2][15:8];", "memory RAM type is not footer-derived"),
        ("wire[7:0]ramtype_sys=footer_ramtype_sys;", "system RAM type bypasses its snapshot"),
        ("wirehas_rtc_mem=lastdata[1][15:8]==8'h01;", "memory RTC metadata is not canonical"),
        ("wirehas_rtc_sys=footer_romtype_sys==8'h01;", "system RTC metadata bypasses its snapshot"),
        ("assignhas_rtc=has_rtc_mem;", "Pocket metadata output is not memory-domain RTC data"),
    ):
        if declaration not in swan:
            raise ValueError(message)

    expected_sizes = {
        "00": "00000",
        "01": "08000",
        "02": "08000",
        "03": "20000",
        "04": "40000",
        "05": "80000",
        "10": "00080",
        "20": "00800",
        "50": "00400",
    }
    for ram_type, size in expected_sizes.items():
        for domain, destination in (("mem", "save_size_bytes"), ("sys", "save_size_bytes_sys")):
            fragment = (
                f"if(ramtype_{domain}==8'h{ram_type})"
                f"{destination}=20'h{size};"
            )
            if ram_type == "00":
                # Type 00 is the decoder default and therefore has no branch.
                default = f"{destination}=20'h00000;"
                if default not in swan:
                    raise ValueError(f"{domain} save-size decoder lacks the type-00 default")
            elif fragment not in swan:
                raise ValueError(
                    f"{domain} save-size decoder changed for RAM type 0x{ram_type}"
                )

    decoder_contracts = {
        "mem": (
            (
                "save_is_sram",
                "(ramtype_mem==8'h01)||(ramtype_mem==8'h02)||"
                "(ramtype_mem==8'h03)||(ramtype_mem==8'h04)||"
                "(ramtype_mem==8'h05)",
            ),
            (
                "save_is_eeprom",
                "(ramtype_mem==8'h10)||(ramtype_mem==8'h20)||"
                "(ramtype_mem==8'h50)",
            ),
        ),
        "sys": (
            (
                "save_is_sram",
                "(ramtype_sys==8'h01)||(ramtype_sys==8'h02)||"
                "(ramtype_sys==8'h03)||(ramtype_sys==8'h04)||"
                "(ramtype_{d}==8'h05)",
            ),
        ),
    }
    for domain, contracts in decoder_contracts.items():
        for name, expression in contracts:
            expected = f"wire{name}_{domain}=" + expression.format(d=domain) + ";"
            if expected not in swan:
                raise ValueError(f"{domain} {name} decoder changed")

    allowed_raw_lastdata = (
        "reg[15:0]lastdata[0:4];",
        "lastdata[0]<=ioctl_dout;",
        "lastdata[1]<=lastdata[0];",
        "lastdata[2]<=lastdata[1];",
        "lastdata[3]<=lastdata[2];",
        "lastdata[4]<=lastdata[3];",
        "footer_color_sys<=lastdata[4][8];",
        "footer_romtype_sys<=lastdata[1][15:8];",
        "footer_ramtype_sys<=lastdata[2][15:8];",
        "wire[7:0]ramtype_mem=lastdata[2][15:8];",
        "wirehas_rtc_mem=lastdata[1][15:8]==8'h01;",
    )
    # Every indexed use beyond the declaration/capture shift, the three system
    # boundary registers, and the two memory-domain decoders is a raw-footer
    # consumer and therefore forbidden.
    without_allowed_lastdata = swan
    for allowed in allowed_raw_lastdata:
        if without_allowed_lastdata.count(allowed) != 1:
            raise ValueError(f"footer capture boundary changed: {allowed}")
        without_allowed_lastdata = without_allowed_lastdata.replace(allowed, "", 1)
    if "lastdata[" in without_allowed_lastdata:
        raise ValueError("raw lastdata bypasses the footer domain split")

    if ".romtype(footer_romtype_sys)" not in instance_body(wonderswan, "SwanTop", "SwanTop"):
        raise ValueError("SwanTop romtype bypasses the system footer snapshot")
    swan_top = instance_body(wonderswan, "SwanTop", "SwanTop")
    for port, signal in (
        ("ramtype", "ramtype_sys"),
        ("hasRTC", "has_rtc_sys"),
    ):
        if f".{port}({signal})" not in swan_top:
            raise ValueError(f"SwanTop {port} bypasses the system footer snapshot")
    if (
        ".eeprom_req(clear_eeprom_write||"
        "(save_is_eeprom_mem&&(sd_buff_rd||sd_buff_wr)&&~extra_data_addr))"
        not in swan_top
    ):
        raise ValueError("SwanTop external EEPROM port does not use its memory-domain classifier")

    save_initializer = instance_body(wonderswan, "pocket_save_init", "save_initializer")
    for port, signal in (
        ("save_is_sram", "save_is_sram_mem"),
        ("save_is_eeprom", "save_is_eeprom_mem"),
        ("save_size_bytes", "save_size_bytes"),
    ):
        if f".{port}({signal})" not in save_initializer:
            raise ValueError(f"save initializer {port} bypasses memory-domain footer metadata")

    rtc_loader = instance_body(wonderswan, "apf_rtc_save_loader", "rtc_save_loader")
    for fragment, message in (
        (".has_rtc(has_rtc_sys)", "RTC loader bypasses the system RTC snapshot"),
        (".save_size_bytes(save_size_bytes_sys)", "RTC loader bypasses the system size decoder"),
        (
            ".legacy_padded_type((ramtype_sys==8'h10)||(ramtype_sys==8'h50))",
            "RTC loader bypasses the system RAM-type snapshot",
        ),
    ):
        if fragment not in rtc_loader:
            raise ValueError(message)

    if "assignsd_buff_din=extra_data_addr?" not in swan or "save_is_sram_sys?sdram_din:eeprom_din;" not in swan:
        raise ValueError("system save-read mux bypasses the footer snapshot")
    for fragment, message in (
        (
            "reg[1:0]configured_system_active=2'b00;",
            "active System Type latch is absent or uninitialized",
        ),
        (
            "if(reset)beginconfigured_system_active<=configured_system;end",
            "System Type is not captured only while the console is in reset",
        ),
        (
            "wireisColor=(configured_system_active==0)?"
            "(footer_color_sys|colorcart_downloaded):"
            "(configured_system_active==2'b10);",
            "automatic console model bypasses the reset-latched System Type or footer snapshot",
        ),
    ):
        if fragment not in swan:
            raise ValueError(message)

    if ".clk_memory(clk_sys_36_864)" not in instance_body(core_top, "data_unloader", "save_data_unloader"):
        raise ValueError("save unloader no longer declares the system-domain consumer boundary")

    waiver_tokens = re.compile(
        r"(?:lastdata|footer_(?:color|romtype|ramtype)|ramtype_(?:mem|sys)|"
        r"has_rtc_(?:mem|sys)|save_size_bytes_(?:mem|sys)|"
        r"save_is_(?:sram|eeprom)_(?:mem|sys)|sd_buff_din)",
        flags=re.IGNORECASE,
    )
    for command in tcl_commands(strip_comments(sdc)):
        if re.match(r"set_(?:false_path|multicycle_path)\b", command) and waiver_tokens.search(command):
            raise ValueError("footer timing path was waived instead of structurally closed")


def expect_failure(
    label: str,
    wonderswan: str,
    core_top: str,
    sdc: str,
) -> None:
    try:
        verify_contract(wonderswan, core_top, sdc)
    except ValueError:
        return
    raise AssertionError(f"mutation unexpectedly passed: {label}")


def mutate_once(source: str, pattern: str, replacement: str) -> str:
    mutated, count = re.subn(pattern, replacement, source, count=1)
    if count != 1:
        raise AssertionError(f"mutation pattern did not match exactly once: {pattern}")
    return mutated


def main() -> None:
    wonderswan = WONDERSWAN.read_text(encoding="utf-8")
    core_top = CORE_TOP.read_text(encoding="utf-8")
    sdc = SDC.read_text(encoding="utf-8")
    verify_contract(wonderswan, core_top, sdc)

    mutations = (
        (
            "snapshot wrong RAM footer index",
            mutate_once(
                wonderswan,
                r"footer_ramtype_sys\s*<=\s*lastdata\[2\]\[15:8\]",
                "footer_ramtype_sys <= lastdata[3][15:8]",
            ),
            core_top,
            sdc,
        ),
        (
            "snapshot missing title-load gate",
            mutate_once(
                wonderswan,
                r"if\s*\(\s*cart_download_sys\s*\)\s*begin\s*"
                r"footer_color_sys",
                "if (1'b1) begin footer_color_sys",
            ),
            core_top,
            sdc,
        ),
        (
            "automatic model raw footer bit",
            mutate_once(
                wonderswan,
                r"footer_color_sys\s*\|\s*colorcart_downloaded",
                "lastdata[4][8] | colorcart_downloaded",
            ),
            core_top,
            sdc,
        ),
        (
            "automatic model live System Type",
            mutate_once(
                wonderswan,
                r"wire\s+isColor\s*=\s*\(configured_system_active\s*==\s*0\)",
                "wire isColor = (configured_system == 0)",
            ),
            core_top,
            sdc,
        ),
        (
            "System Type latch updates while running",
            mutate_once(
                wonderswan,
                r"if\s*\(\s*reset\s*\)\s*begin\s*"
                r"configured_system_active\s*<=\s*configured_system",
                "if (1'b1) begin configured_system_active <= configured_system",
            ),
            core_top,
            sdc,
        ),
        (
            "SwanTop raw ROM type",
            mutate_once(
                wonderswan,
                r"\.romtype\s*\(\s*footer_romtype_sys\s*\)",
                ".romtype(lastdata[1][15:8])",
            ),
            core_top,
            sdc,
        ),
        (
            "SwanTop raw RAM type",
            mutate_once(
                wonderswan,
                r"\.ramtype\s*\(\s*ramtype_sys\s*\)",
                ".ramtype(lastdata[2][15:8])",
            ),
            core_top,
            sdc,
        ),
        (
            "RTC loader raw RTC field",
            mutate_once(
                wonderswan,
                r"\.has_rtc\s*\(\s*has_rtc_sys\s*\)",
                ".has_rtc(lastdata[1][15:8] == 8'h01)",
            ),
            core_top,
            sdc,
        ),
        (
            "save read raw decoder",
            mutate_once(wonderswan, r"save_is_sram_sys\s*\?", "save_is_sram_mem ?"),
            core_top,
            sdc,
        ),
        (
            "footer false path",
            wonderswan,
            core_top,
            sdc + "\nset_false_path -from [get_registers {*lastdata*}] -to [get_registers {*footer_ramtype_sys*}]\n",
        ),
        (
            "footer multicycle path",
            wonderswan,
            core_top,
            sdc + "\nset_multicycle_path -setup 2 -from [get_registers {*lastdata*}] -to [get_registers {*footer_romtype_sys*}]\n",
        ),
    )
    for label, mutated_swan, mutated_top, mutated_sdc in mutations:
        expect_failure(label, mutated_swan, mutated_top, mutated_sdc)

    print(
        "PASS footer snapshot contract "
        "ram_types=00/01/02/03/04/05/10/20/50 mutations=11 "
        "system_type=reset_latched waivers=forbidden"
    )


if __name__ == "__main__":
    main()
