#!/usr/bin/env python3
"""Mutation-lock the complete Pocket command-0090 RTC integration path."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def extract_instance(source: str, module: str, instance: str) -> str:
    match = re.search(
        rf"\b{re.escape(module)}\s+{re.escape(instance)}\s*\(",
        source,
    )
    if match is None:
        raise ValueError(f"missing {module} instance {instance}")
    open_paren = source.find("(", match.start())
    depth = 0
    for index in range(open_paren, len(source)):
        if source[index] == "(":
            depth += 1
        elif source[index] == ")":
            depth -= 1
            if depth == 0:
                return source[open_paren + 1 : index]
    raise ValueError(f"unterminated {module} instance {instance}")


def named_ports(instance_body: str) -> dict[str, str]:
    ports: dict[str, str] = {}
    for name, expression in re.findall(
        r"\.([A-Za-z_][A-Za-z0-9_]*)\s*\(\s*([^()]*?)\s*\)",
        instance_body,
    ):
        if name in ports:
            raise ValueError(f"duplicate named port {name}")
        ports[name] = re.sub(r"\s+", "", expression)
    return ports


def require_ports(
    source: str,
    module: str,
    instance: str,
    expected: dict[str, str],
    label: str,
) -> None:
    ports = named_ports(extract_instance(source, module, instance))
    for name, expression in expected.items():
        actual = ports.get(name)
        if actual != expression:
            raise ValueError(
                f"{label} port {name} is {actual!r}, expected {expression!r}"
            )


def verify_contract(
    core_top: str,
    wonderswan: str,
    rtc_save_loader: str,
    rtc_vhdl: str,
    qsf: str,
) -> None:
    require_ports(
        core_top,
        "core_bridge_cmd",
        "icb",
        {
            "rtc_epoch_seconds": "rtc_epoch_seconds",
            "rtc_date_bcd": "rtc_date_bcd",
            "rtc_time_bcd": "rtc_time_bcd",
            "rtc_valid": "rtc_valid",
        },
        "0090 bridge",
    )

    require_ports(
        core_top,
        "apf_rtc_cdc",
        "rtc_command_cdc",
        {
            "reset_n": "pll_core_ready_74a",
            "clk_74a": "clk_74a",
            "rtc_epoch_src": "rtc_epoch_seconds",
            "rtc_valid_src": "rtc_valid",
            "rtc_busy_src": "rtc_cdc_busy",
            "rtc_rejected_src": "rtc_cdc_rejected",
            "clk_sys": "clk_sys_36_864",
            "rtc_epoch_dst": "rtc_epoch_seconds_sys",
            "rtc_valid_dst": "rtc_valid_sys",
        },
        "RTC CDC",
    )

    require_ports(
        core_top,
        "wonderswan",
        "wonderswan",
        {
            "rtc_epoch_seconds": "rtc_epoch_seconds_sys",
            "rtc_epoch_valid": "rtc_valid_sys",
        },
        "WonderSwan RTC input",
    )

    if not re.search(
        r"^\s*set_global_assignment\s+-name\s+SYSTEMVERILOG_FILE\s+"
        r"core/apf_rtc_cdc\.sv\s*$",
        qsf,
        re.MULTILINE,
    ):
        raise ValueError("QSF does not compile core/apf_rtc_cdc.sv")
    if not re.search(
        r"^\s*set_global_assignment\s+-name\s+SYSTEMVERILOG_FILE\s+"
        r"core/apf_rtc_save_loader\.sv\s*$",
        qsf,
        re.MULTILINE,
    ):
        raise ValueError("QSF does not compile core/apf_rtc_save_loader.sv")

    require_ports(
        wonderswan,
        "SwanTop",
        "SwanTop",
        {
            "RTC_timestampNew": "rtc_epoch_valid",
            "RTC_timestampIn": "rtc_epoch_seconds",
        },
        "SwanTop RTC input",
    )
    require_ports(
        wonderswan,
        "apf_rtc_save_loader",
        "rtc_save_loader",
        {
            "clk": "clk_sys_36_864",
            "reset_title": "cart_download_sys",
            "has_rtc": "has_rtc_sys",
            "save_size_bytes": "save_size_bytes_sys",
            "sd_buff_wr": "sd_buff_wr",
            "sd_buff_addr": "sd_buff_addr",
            "sd_buff_dout": "sd_buff_dout",
            "extra_data_addr": "extra_data_addr",
            "extra_write_complete": "rtc_extra_write_complete",
            "rtc_trailer_begin": "rtc_trailer_begin",
            "rtc_payload_write": "rtc_payload_write",
            "rtc_payload_index": "rtc_payload_index",
            "rtc_payload_data": "rtc_payload_data",
            "rtc_trailer_complete": "rtc_trailer_complete",
        },
        "RTC save loader",
    )
    if wonderswan.count("did_receive_sys_rtc <= 1;") != 1 or not re.search(
        r"if\s*\(\s*rtc_epoch_valid\s*\)\s*begin\s*"
        r"(?:\/\/[^\n]*\n\s*)?did_receive_sys_rtc\s*<=\s*1\s*;",
        wonderswan,
    ):
        raise ValueError("WonderSwan does not consume RTC through its valid pulse")
    if re.search(
        r"rtc_epoch_seconds\s*(?:!=|==)|last_[A-Za-z0-9_]*rtc[A-Za-z0-9_]*epoch",
        wonderswan,
        re.IGNORECASE,
    ):
        raise ValueError("WonderSwan uses RTC word-change detection")

    if rtc_vhdl.count("RTC_timestamp <= RTC_timestampIn;") != 1:
        raise ValueError("RTC timestamp input assignment is not unique")
    if not re.search(
        r"RTC_timestampNew_1\s*<=\s*RTC_timestampNew\s*;\s*"
        r"if\s*\(\s*RTC_timestampNew\s*=\s*'1'\s+and\s+"
        r"RTC_timestampNew_1\s*=\s*'0'\s*\)\s*then\s*"
        r"RTC_timestamp\s*<=\s*RTC_timestampIn\s*;\s*end\s+if\s*;",
        rtc_vhdl,
        re.IGNORECASE,
    ):
        raise ValueError("RTC VHDL does not latch timestamp only on rising valid")
    if re.search(
        r"RTC_timestampIn\s*(?:/=|=)\s*RTC_timestamp",
        rtc_vhdl,
        re.IGNORECASE,
    ):
        raise ValueError("RTC VHDL uses timestamp word-change detection")

    expected_save_sizes = {
        0x01: 0x08000,
        0x02: 0x08000,
        0x03: 0x20000,
        0x04: 0x40000,
        0x05: 0x80000,
        0x10: 0x00080,
        0x20: 0x00800,
        0x50: 0x00400,
    }
    parsed_save_sizes = {
        int(ram_type, 16): int(byte_size, 16)
        for ram_type, byte_size in re.findall(
            r"if\s*\(\s*ramtype_mem\s*==\s*8'h([0-9A-Fa-f]{2})\s*\)\s*"
            r"save_size_bytes\s*=\s*20'h([0-9A-Fa-f]{5})\s*;",
            wonderswan,
        )
    }
    if parsed_save_sizes != expected_save_sizes:
        raise ValueError(
            f"exact save_size_bytes map mismatch: {parsed_save_sizes!r}"
        )
    if not re.search(
        r"assign\s+extra_data_addr\s*=\s*sd_buff_addr\s*>=\s*"
        r"\{\s*1'b0\s*,\s*save_size_bytes\s*\}\s*;",
        rtc_save_loader,
    ):
        raise ValueError("RTC trailer boundary is not relative to save_size_bytes")
    if not re.search(
        r"wire\s*\[20:0\]\s*rtc_data_offset\s*=\s*"
        r"sd_buff_addr\s*-\s*save_size_bytes_sys\s*;",
        wonderswan,
    ):
        raise ValueError("RTC trailer offset is not relative to save_size_bytes")
    if "sd_buff_addr[8:1]" in wonderswan:
        raise ValueError("legacy absolute RTC trailer addressing is present")
    if not re.search(
        r"if\s*\(\s*extra_data_addr\s*&&\s*sd_buff_wr\s*\)\s*"
        r"extra_write_complete\s*<=\s*1'b1\s*;",
        rtc_save_loader,
    ):
        raise ValueError("RTC overflow writes are not acknowledged after sampling")
    if not re.search(
        r"legacy_header\s*=\s*has_rtc\s*&&\s*legacy_padded_type\s*&&\s*"
        r"sd_buff_wr\s*&&\s*\(\s*sd_buff_addr\s*==\s*LEGACY_RTC_BASE\s*\)",
        rtc_save_loader,
    ):
        raise ValueError("legacy RTC marker is not safely type and write gated")
    if not re.search(
        r"wire\s+has_rtc_mem\s*=\s*lastdata\[1\]\[15:8\]\s*"
        r"==\s*8'h01\s*;",
        wonderswan,
    ):
        raise ValueError(
            "per-title RTC capability does not require canonical footer value 0x01"
        )

    cart_reset_bodies = re.findall(
        r"if\s*\(\s*cart_download_sys\s*\)\s*begin(.*?)end\s+else\s+begin",
        wonderswan,
        re.DOTALL,
    )
    reset_body = next(
        (body for body in cart_reset_bodies if "did_receive_sys_rtc" in body),
        None,
    )
    if reset_body is None:
        raise ValueError("missing per-title RTC reset branch")
    for signal in (
        "did_receive_sys_rtc",
        "is_save_rtc_ready",
        "rtc_load_delivered",
        "time_dout",
    ):
        if not re.search(rf"\b{signal}\s*<=\s*0\s*;", reset_body):
            raise ValueError(f"per-title RTC reset omits {signal}")

    if not re.search(
        r"always\s*@\s*\(\s*posedge\s+clk_sys_36_864\s*\)\s*begin\s*"
        r"RTC_load\s*<=\s*0\s*;",
        wonderswan,
        re.DOTALL,
    ):
        raise ValueError("RTC_load is not defaulted low for a one-shot pulse")
    one_shot = re.search(
        r"if\s*\(\s*did_receive_sys_rtc\s*&&\s*is_save_rtc_ready\s*&&\s*"
        r"!\s*rtc_load_delivered\s*\)\s*begin(?P<body>.*?)end",
        wonderswan,
        re.DOTALL,
    )
    if one_shot is None:
        raise ValueError("RTC_load lacks the per-title one-shot guard")
    one_shot_body = one_shot.group("body")
    if not re.search(r"\bRTC_load\s*<=\s*1\s*;", one_shot_body):
        raise ValueError("RTC one-shot does not pulse RTC_load")
    if not re.search(r"\brtc_load_delivered\s*<=\s*1\s*;", one_shot_body):
        raise ValueError("RTC one-shot does not latch delivery")

    trailer_start = re.search(
        r"if\s*\(\s*rtc_trailer_begin\s*\)\s*begin(?P<body>.*?)end",
        wonderswan,
        re.DOTALL,
    )
    if trailer_start is None or not re.search(
        r"\brtc_load_delivered\s*<=\s*0\s*;", trailer_start.group("body")
    ):
        raise ValueError("new RTC trailer does not re-arm the one-shot")


def must_fail(
    sources: dict[str, str],
    filename: str,
    old: str,
    new: str,
    expected_error: str,
) -> None:
    if old not in sources[filename]:
        raise AssertionError(f"mutation source missing in {filename}: {old!r}")
    mutated = dict(sources)
    mutated[filename] = mutated[filename].replace(old, new, 1)
    try:
        verify_contract(
            mutated["core_top"],
            mutated["wonderswan"],
            mutated["rtc_save_loader"],
            mutated["rtc_vhdl"],
            mutated["qsf"],
        )
    except ValueError as error:
        if expected_error not in str(error):
            raise AssertionError(
                f"expected {expected_error!r} for {filename} mutation, got {error!r}"
            ) from error
    else:
        raise AssertionError(f"invalid RTC integration passed: {expected_error}")


def main() -> None:
    sources = {
        "core_top": (ROOT / "src/fpga/core/core_top.v").read_text(encoding="utf-8"),
        "wonderswan": (ROOT / "src/fpga/core/wonderswan.sv").read_text(
            encoding="utf-8"
        ),
        "rtc_save_loader": (
            ROOT / "src/fpga/core/apf_rtc_save_loader.sv"
        ).read_text(encoding="utf-8"),
        "rtc_vhdl": (ROOT / "src/fpga/core/rtl/rtc.vhd").read_text(
            encoding="utf-8"
        ),
        "qsf": (ROOT / "src/fpga/ap_core.qsf").read_text(encoding="utf-8"),
    }
    verify_contract(
        sources["core_top"],
        sources["wonderswan"],
        sources["rtc_save_loader"],
        sources["rtc_vhdl"],
        sources["qsf"],
    )

    mutations = [
        ("core_top", ".rtc_epoch_seconds(rtc_epoch_seconds)", ".rtc_epoch_seconds()", "0090 bridge port rtc_epoch_seconds"),
        ("core_top", ".rtc_date_bcd(rtc_date_bcd)", ".rtc_date_bcd()", "0090 bridge port rtc_date_bcd"),
        ("core_top", ".rtc_time_bcd(rtc_time_bcd)", ".rtc_time_bcd()", "0090 bridge port rtc_time_bcd"),
        ("core_top", ".rtc_valid(rtc_valid)", ".rtc_valid()", "0090 bridge port rtc_valid"),
        ("core_top", "apf_rtc_cdc rtc_command_cdc", "apf_rtc_cdc_broken rtc_command_cdc", "missing apf_rtc_cdc instance"),
        ("core_top", ".rtc_valid_src(rtc_valid)", ".rtc_valid_src(1'b0)", "RTC CDC port rtc_valid_src"),
        ("core_top", ".rtc_epoch_seconds(rtc_epoch_seconds_sys)", ".rtc_epoch_seconds(rtc_epoch_seconds)", "WonderSwan RTC input port rtc_epoch_seconds"),
        ("core_top", ".rtc_epoch_valid(rtc_valid_sys)", ".rtc_epoch_valid(rtc_valid)", "WonderSwan RTC input port rtc_epoch_valid"),
        ("qsf", "set_global_assignment -name SYSTEMVERILOG_FILE core/apf_rtc_cdc.sv", "# RTC CDC omitted", "QSF does not compile"),
        ("qsf", "set_global_assignment -name SYSTEMVERILOG_FILE core/apf_rtc_save_loader.sv", "# RTC save loader omitted", "QSF does not compile core/apf_rtc_save_loader.sv"),
        ("wonderswan", "if (rtc_epoch_valid) begin", "if (rtc_epoch_seconds != 0) begin", "does not consume RTC through its valid pulse"),
        ("wonderswan", "lastdata[1][15:8] == 8'h01", "lastdata[1][15:8] != 8'h00", "does not require canonical footer value 0x01"),
        ("wonderswan", ".reset_title         (cart_download_sys)", ".reset_title         (cart_download)", "RTC save loader port reset_title"),
        ("rtc_vhdl", "if (RTC_timestampNew = '1' and RTC_timestampNew_1 = '0') then", "if (RTC_timestampNew = '1') then", "only on rising valid"),
        ("rtc_save_loader", "sd_buff_addr >= {1'b0, save_size_bytes}", "sd_buff_addr >= 21'h08000", "boundary is not relative"),
        ("rtc_save_loader", "extra_data_addr && sd_buff_wr", "extra_data_addr && 1'b0", "overflow writes are not acknowledged after sampling"),
        ("rtc_save_loader", "has_rtc && legacy_padded_type && sd_buff_wr", "has_rtc && legacy_padded_type && 1'b1", "legacy RTC marker is not safely type and write gated"),
        ("wonderswan", "sd_buff_addr - save_size_bytes_sys", "sd_buff_addr - 20'h08000", "offset is not relative"),
        ("wonderswan", "if (ramtype_mem == 8'h01) save_size_bytes = 20'h08000;", "if (ramtype_mem == 8'h01) save_size_bytes = 20'h02000;", "exact save_size_bytes map mismatch"),
        ("wonderswan", "did_receive_sys_rtc <= 0;", "did_receive_sys_rtc <= did_receive_sys_rtc;", "per-title RTC reset omits did_receive_sys_rtc"),
        ("wonderswan", "is_save_rtc_ready <= 0;", "is_save_rtc_ready <= is_save_rtc_ready;", "per-title RTC reset omits is_save_rtc_ready"),
        ("wonderswan", "rtc_load_delivered <= 0;", "rtc_load_delivered <= rtc_load_delivered;", "per-title RTC reset omits rtc_load_delivered"),
        ("wonderswan", "time_dout <= 0;", "time_dout <= time_dout;", "per-title RTC reset omits time_dout"),
        ("wonderswan", "RTC_load <= 0;", "RTC_load <= RTC_load;", "RTC_load is not defaulted low"),
        ("wonderswan", "&& !rtc_load_delivered", "&& rtc_load_delivered", "lacks the per-title one-shot guard"),
        ("wonderswan", "rtc_load_delivered <= 1;", "rtc_load_delivered <= 0;", "does not latch delivery"),
        ("wonderswan", "if (rtc_trailer_begin) begin\n        is_save_rtc_ready <= 0;\n        rtc_load_delivered <= 0;", "if (rtc_trailer_begin) begin\n        is_save_rtc_ready <= 0;\n        rtc_load_delivered <= 1;", "does not re-arm the one-shot"),
    ]
    for filename, old, new, expected_error in mutations:
        must_fail(sources, filename, old, new, expected_error)

    print(
        "PASS Pocket RTC integration 0090=4words+valid CDC=handshake "
        f"trailer=exact-relative load=one-shot mutations={len(mutations)}"
    )


if __name__ == "__main__":
    main()
