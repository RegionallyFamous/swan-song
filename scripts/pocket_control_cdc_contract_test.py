#!/usr/bin/env python3
"""Mutation-lock Pocket reset/download controls to their consumer domains."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def active(source: str) -> str:
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", source)


def compact(value: str) -> str:
    return re.sub(r"\s+", "", value)


def instance_body(source: str, instance: str) -> str:
    match = re.search(rf"\b{re.escape(instance)}\s*\(", source)
    if match is None:
        raise ValueError(f"missing instance {instance}")
    opening = source.find("(", match.start())
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "(":
            depth += 1
        elif source[index] == ")":
            depth -= 1
            if depth == 0:
                return source[opening + 1 : index]
    raise ValueError(f"unterminated instance {instance}")


def split_top_level(body: str) -> list[str]:
    parts: list[str] = []
    start = 0
    round_depth = square_depth = brace_depth = 0
    for index, character in enumerate(body):
        if character == "(":
            round_depth += 1
        elif character == ")":
            round_depth -= 1
        elif character == "[":
            square_depth += 1
        elif character == "]":
            square_depth -= 1
        elif character == "{":
            brace_depth += 1
        elif character == "}":
            brace_depth -= 1
        elif (
            character == ","
            and round_depth == 0
            and square_depth == 0
            and brace_depth == 0
        ):
            parts.append(compact(body[start:index]))
            start = index + 1
    parts.append(compact(body[start:]))
    return parts


def named_ports(source: str, instance: str) -> dict[str, str]:
    ports: dict[str, str] = {}
    for name, expression in re.findall(
        r"\.([A-Za-z_][A-Za-z0-9_]*)\s*\(\s*([^()]*?)\s*\)",
        instance_body(source, instance),
    ):
        ports[name] = compact(expression)
    return ports


def require_named(
    source: str, instance: str, expected: dict[str, str], label: str
) -> None:
    ports = named_ports(source, instance)
    for port, expression in expected.items():
        if ports.get(port) != expression:
            raise ValueError(
                f"{label} port {port} is {ports.get(port)!r}, expected {expression!r}"
            )


def require_positional(
    source: str, instance: str, expected: list[str], label: str
) -> None:
    actual = split_top_level(instance_body(source, instance))
    if actual != expected:
        raise ValueError(f"{label} wiring is {actual!r}, expected {expected!r}")


def clocked_blocks(source: str, clock: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    pattern = re.compile(
        r"\balways(?:_ff)?\s*@\s*\((?P<sensitivity>[^)]*)\)\s*begin\b"
    )
    for match in pattern.finditer(source):
        sensitivity = match.group("sensitivity")
        if not re.search(rf"\bposedge\s+{re.escape(clock)}\b", sensitivity):
            continue
        body_start = match.end()
        depth = 1
        for token in re.finditer(r"\b(?:begin|end)\b", source[body_start:]):
            depth += 1 if token.group(0) == "begin" else -1
            if depth == 0:
                blocks.append(
                    (sensitivity, source[body_start : body_start + token.start()])
                )
                break
    return blocks


def verify_contract(core_top_source: str, wonderswan_source: str) -> None:
    core_top = active(core_top_source)
    wonderswan = active(wonderswan_source)

    require_named(
        core_top,
        "core_reset_memory",
        {
            "clk": "clk_mem_110_592",
            "reset_n_async": "reset_n",
            "reset_n_sync": "reset_n_mem_s",
        },
        "memory reset synchronizer",
    )
    require_named(
        core_top,
        "core_reset_system",
        {
            "clk": "clk_sys_36_864",
            "reset_n_async": "reset_n",
            "reset_n_sync": "reset_n_sys_s",
        },
        "system reset synchronizer",
    )
    require_positional(
        core_top,
        "cart_download_memory_s",
        ["ext_cart_download", "ext_cart_download_mem_s", "clk_mem_110_592"],
        "memory cartridge-download synchronizer",
    )
    require_positional(
        core_top,
        "download_system_s",
        [
            "{external_reset,ext_cart_download}",
            "{external_reset_sys_s,ext_cart_download_sys_s}",
            "clk_sys_36_864",
        ],
        "system download synchronizer",
    )
    require_named(
        core_top,
        "wonderswan",
        {
            "reset_n": "reset_n_mem_s",
            "reset_n_sys": "reset_n_sys_s",
            "external_reset": "external_reset_sys_s",
            "ext_cart_download": "ext_cart_download_mem_s",
            "ext_cart_download_sys": "ext_cart_download_sys_s",
        },
        "WonderSwan domain controls",
    )

    for stale in (
        "reset_n_s",
        "external_reset_s",
        "ext_cart_download_s",
        "bios_download_s",
        "sys_control_s",
    ):
        if re.search(rf"\b{stale}\b", core_top):
            raise ValueError(f"stale single-domain control alias remains: {stale}")

    if not re.search(r"\binput\s+wire\s+reset_n_sys\b", wonderswan):
        raise ValueError("WonderSwan lacks a system-domain reset input")
    if not re.search(
        r"\binput\s+wire\s*\[\s*1\s*:\s*0\s*\]\s*ext_cart_download_sys\b",
        wonderswan,
    ):
        raise ValueError("WonderSwan lacks a system-domain cartridge input")

    reset_match = re.search(r"\bwire\s+reset\s*=\s*([^;]+);", wonderswan)
    reset_expression = compact(reset_match.group(1)) if reset_match else None
    expected_reset = (
        "~reset_n_sys|cart_download_sys|clearing_save_sys|external_reset"
    )
    if reset_expression != expected_reset:
        raise ValueError(
            f"system reset expression is {reset_expression!r}, expected {expected_reset!r}"
        )

    clearing_blocks = [
        body
        for sensitivity, body in clocked_blocks(wonderswan, "clk_sys_36_864")
        if re.search(r"\bposedge\s+clearing_save\b", sensitivity)
    ]
    if len(clearing_blocks) != 1:
        raise ValueError("save clearing needs one system-domain reset synchronizer")
    clearing_body = compact(clearing_blocks[0])
    expected_clearing = (
        "if(clearing_save)beginclearing_save_sys_sync<=3'b111;"
        "endelsebeginclearing_save_sys_sync<="
        "{clearing_save_sys_sync[1:0],1'b0};"
    )
    if expected_clearing not in clearing_body:
        raise ValueError("save-clearing synchronizer is not async-assert/sync-release")
    if not re.search(
        r"\(\*\s*altera_attribute\s*=\s*\""
        r"-name\s+SYNCHRONIZER_IDENTIFICATION\s+FORCED;\s*"
        r"-name\s+PRESERVE_REGISTER\s+ON\"\s*\*\)\s*"
        r"reg\s*\[\s*2\s*:\s*0\s*\]\s*clearing_save_sys_sync",
        wonderswan,
    ):
        raise ValueError(
            "save-clearing synchronizer lacks the supported Quartus staging assignment"
        )
    if "ASYNC_REG" in wonderswan:
        raise ValueError("save-clearing synchronizer uses an unsupported Quartus attribute")
    if not re.search(
        r"clearing_save_sys_sync\s*=\s*3'b111\s*;", wonderswan
    ):
        raise ValueError(
            "save-clearing synchronizer power-up does not match its asynchronous preset"
        )
    if not re.search(
        r"\bwire\s+clearing_save_sys\s*=\s*clearing_save_sys_sync\[2\]\s*;",
        wonderswan,
    ):
        raise ValueError("save-clearing system output is not the final stage")

    require_named(
        wonderswan,
        "save_initializer",
        {"cart_download": "cart_download", "reset_n": "reset_n"},
        "memory save initializer",
    )
    require_named(
        wonderswan,
        "rtc_save_loader",
        {"clk": "clk_sys_36_864", "reset_title": "cart_download_sys"},
        "system RTC save loader",
    )

    if re.search(r"\b(?:ioctl_download|bios_download)\b", wonderswan):
        raise ValueError("retired external BIOS download control remains")

    system_blocks = clocked_blocks(wonderswan, "clk_sys_36_864")
    if not system_blocks:
        raise ValueError("no system-domain sequential logic found")
    for sensitivity, body in system_blocks:
        if re.search(r"\bposedge\s+clearing_save\b", sensitivity):
            continue
        for raw_signal in ("reset_n", "cart_download", "colorcart_download"):
            if re.search(rf"\b{raw_signal}\b", body):
                raise ValueError(
                    f"clk_sys logic consumes memory-domain {raw_signal} directly"
                )

    if not re.search(
        r"if\s*\(\s*cart_download_sys\s*\)\s*begin(?:(?!\bend\b).)*"
        r"did_receive_sys_rtc\s*<=\s*0\s*;",
        wonderswan,
        re.DOTALL,
    ):
        raise ValueError("per-title RTC state is not reset by cart_download_sys")


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
        verify_contract(mutated["core_top"], mutated["wonderswan"])
    except ValueError as error:
        if expected_error not in str(error):
            raise AssertionError(
                f"expected {expected_error!r}, got {error!r}"
            ) from error
    else:
        raise AssertionError(f"invalid CDC mutation passed: {expected_error}")


def main() -> None:
    sources = {
        "core_top": (ROOT / "src/fpga/core/core_top.v").read_text(encoding="utf-8"),
        "wonderswan": (ROOT / "src/fpga/core/wonderswan.sv").read_text(
            encoding="utf-8"
        ),
    }
    verify_contract(sources["core_top"], sources["wonderswan"])

    mutations = [
        ("core_top", "apf_reset_sync core_reset_memory (\n      .clk(clk_mem_110_592)", "apf_reset_sync core_reset_memory (\n      .clk(clk_sys_36_864)", "memory reset synchronizer"),
        ("core_top", ".reset_n_sync(reset_n_sys_s)", ".reset_n_sync(reset_n_mem_s)", "system reset synchronizer"),
        ("core_top", "ext_cart_download_mem_s,\n      clk_mem_110_592", "ext_cart_download_sys_s,\n      clk_mem_110_592", "memory cartridge-download synchronizer"),
        ("core_top", ") download_system_s (\n      {external_reset, ext_cart_download},\n      {external_reset_sys_s, ext_cart_download_sys_s},\n      clk_sys_36_864", ") download_system_s (\n      {external_reset, ext_cart_download},\n      {external_reset_sys_s, ext_cart_download_sys_s},\n      clk_mem_110_592", "system download synchronizer"),
        ("core_top", ".reset_n_sys(reset_n_sys_s)", ".reset_n_sys(reset_n_mem_s)", "WonderSwan domain controls"),
        ("core_top", ".external_reset(external_reset_sys_s)", ".external_reset(external_reset)", "WonderSwan domain controls"),
        ("core_top", ".ext_cart_download_sys(ext_cart_download_sys_s)", ".ext_cart_download_sys(ext_cart_download_mem_s)", "WonderSwan domain controls"),
        ("wonderswan", "~reset_n_sys | cart_download_sys", "~reset_n | cart_download_sys", "system reset expression"),
        ("wonderswan", "cart_download_sys | clearing_save_sys", "cart_download | clearing_save_sys", "system reset expression"),
        ("wonderswan", "clearing_save_sys | external_reset", "clearing_save | external_reset", "system reset expression"),
        ("wonderswan", "clearing_save_sys_sync[1:0], 1'b0", "clearing_save_sys_sync[0:0], 2'b00", "save-clearing synchronizer"),
        ("wonderswan", "clearing_save_sys_sync = 3'b111", "clearing_save_sys_sync = 3'b000", "power-up does not match"),
        ("wonderswan", "SYNCHRONIZER_IDENTIFICATION FORCED", "ASYNC_REG = \"TRUE\"", "supported Quartus staging assignment"),
        ("wonderswan", ".reset_title         (cart_download_sys)", ".reset_title         (cart_download)", "system RTC save loader"),
        ("wonderswan", "wire cart_download_sys = cart_download_sys_external || rom_prepare_busy_sys;", "wire cart_download_sys = cart_download_sys_external || rom_prepare_busy_sys;\n  wire bios_download = 1'b0;", "retired external BIOS"),
        ("wonderswan", "if (cart_download_sys) begin\n      // Do not carry", "if (cart_download) begin\n      // Do not carry", "clk_sys logic consumes"),
    ]
    for mutation in mutations:
        must_fail(sources, *mutation)

    print(f"PASS Pocket control CDC contract ({len(mutations)} mutations rejected)")


if __name__ == "__main__":
    main()
