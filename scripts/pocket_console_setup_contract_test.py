#!/usr/bin/env python3
"""Mutation-lock the original-BIOS Console Setup action and input boundary."""

from __future__ import annotations

import copy
import json
import pathlib
import re


ROOT = pathlib.Path(__file__).resolve().parent.parent


def compact(source: str) -> str:
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    source = re.sub(r"//[^\n]*", "", source)
    return re.sub(r"\s+", "", source).lower()


def number(value: int | str) -> int:
    return int(value, 0) if isinstance(value, str) else value


def verify_contract(interact: dict, sources: dict[str, str]) -> None:
    variables = interact["interact"]["variables"]
    setup = [item for item in variables if number(item["id"]) == 1]
    expected = {
        "name": "Console Setup",
        "id": 1,
        "type": "action",
        "enabled": True,
        "address": "0x54",
        "value": 1,
    }
    if setup != [expected]:
        raise ValueError("interact Console Setup action contract changed")

    sequencer = compact(sources["sequencer"])
    for expression, message in (
        ("parameterintegerreset_cycles=1_048_576", "setup reset interval changed"),
        ("parameterintegerstart_cycles=33_554_432", "setup Start interval changed"),
        (
            "always@(posedgeclk_sourceornegedgereset_n)",
            "host reset does not asynchronously cancel source setup state",
        ),
        (
            "always@(posedgeclk_destinationornegedgereset_n)",
            "host reset does not asynchronously cancel destination setup state",
        ),
        ("if(!reset_n)", "host reset does not cancel setup"),
        ("elseif(trigger)", "setup retrigger does not reload the intervals"),
        (
            "reset_counter_source<=reset_cycles[counter_width-1:0]",
            "setup reset counter is not reloaded",
        ),
        (
            "start_counter_source<=start_cycles[counter_width-1:0]",
            "setup Start counter is not reloaded",
        ),
        ("reg[2:0]reset_sync_destination", "setup reset lacks a three-stage CDC"),
        ("reg[2:0]start_sync_destination", "setup Start lacks a three-stage CDC"),
        ("assignreset_active_destination=reset_sync_destination[2]", "setup reset CDC output changed"),
        ("assignstart_active_destination=start_sync_destination[2]", "setup Start CDC output changed"),
    ):
        if expression not in sequencer:
            raise ValueError(message)
    quartus_sync_attribute = (
        'altera_attribute="-namesynchronizer_identificationforced;'
        '-namepreserve_registeron"'
    )
    if sequencer.count(quartus_sync_attribute) != 2:
        raise ValueError(
            "both setup level synchronizers must carry the supported Quartus "
            "synchronizer assignment"
        )
    if "async_reg" in sequencer:
        raise ValueError("setup CDC uses an unsupported Quartus attribute")

    core_top = compact(sources["core_top"])
    for expression, message in (
        (
            "bridge_wr&&bridge_addr==32'h00000054&&bridge_wr_data==32'd1",
            "bridge action does not trigger only from address 0x54/value 1",
        ),
        (
            ".external_reset(external_reset_sys_s|console_setup_reset_sys_s)",
            "setup reset does not reach the console reset boundary",
        ),
        (
            ".button_start(cont1_key_s[15]|console_setup_start_sys_s)",
            "forced Start is not ORed at the logical Start boundary",
        ),
    ):
        if expression not in core_top:
            raise ValueError(message)
    if "configured_orientation<=console_setup" in core_top:
        raise ValueError("Console Setup must never mutate presentation orientation")

    if sources["qsf"].count(
        "set_global_assignment -name SYSTEMVERILOG_FILE core/apf_console_setup.sv"
    ) != 1:
        raise ValueError("Quartus does not compile the Console Setup sequencer")
    for hook in (
        '"$ROOT/sim/rtl/run_apf_console_setup_tb.sh"',
        'python3 "$ROOT/scripts/pocket_console_setup_contract_test.py"',
    ):
        if hook not in sources["regression"]:
            raise ValueError(f"regression is missing {hook}")

    docs = (sources["readme"] + sources["hardware_qa"] + sources["status"]).lower()
    for phrase in (
        "console setup",
        "hold start",
        "owner",
        "original bios",
        "does not change display orientation",
    ):
        if phrase not in docs:
            raise ValueError(f"Console Setup documentation is missing {phrase!r}")
    if "console_setup_action_both_models" not in sources["hardware_qa_source"]:
        raise ValueError("hardware QA does not require the action on both BIOS models")


def main() -> None:
    paths = {
        "sequencer": ROOT / "src/fpga/core/apf_console_setup.sv",
        "core_top": ROOT / "src/fpga/core/core_top.v",
        "qsf": ROOT / "src/fpga/ap_core.qsf",
        "regression": ROOT / "scripts/regression.sh",
        "readme": ROOT / "README.md",
        "hardware_qa": ROOT / "HARDWARE_QA_PROTOCOL.md",
        "hardware_qa_source": ROOT / "scripts/pocket_hardware_qa.py",
        "status": ROOT / "PHASE_STATUS.md",
    }
    sources = {name: path.read_text(encoding="utf-8") for name, path in paths.items()}
    interact_path = ROOT / "dist/Cores/RegionallyFamous.SwanSong/interact.json"
    interact = json.loads(interact_path.read_text(encoding="utf-8"))
    verify_contract(interact, sources)

    mutations: list[tuple[dict, dict[str, str]]] = []
    for field, value in (("address", "0x58"), ("value", 0), ("name", "Setup")):
        changed = copy.deepcopy(interact)
        item = next(
            value for value in changed["interact"]["variables"] if number(value["id"]) == 1
        )
        item[field] = value
        mutations.append((changed, sources))
    for source_name, old, new in (
        ("sequencer", "START_CYCLES = 33_554_432", "START_CYCLES = 1_048_576"),
        ("sequencer", "or negedge reset_n", ""),
        (
            "sequencer",
            "SYNCHRONIZER_IDENTIFICATION FORCED",
            'ASYNC_REG = "TRUE"',
        ),
        (
            "core_top",
            ".external_reset(external_reset_sys_s | console_setup_reset_sys_s)",
            ".external_reset(external_reset_sys_s)",
        ),
        ("core_top", "cont1_key_s[15] | console_setup_start_sys_s", "cont1_key_s[15]"),
        ("qsf", "core/apf_console_setup.sv", "core/missing_console_setup.sv"),
        ("regression", "run_apf_console_setup_tb.sh", "run_missing_console_setup_tb.sh"),
    ):
        if old not in sources[source_name]:
            raise RuntimeError(f"mutation anchor missing in {source_name}: {old!r}")
        changed_sources = dict(sources)
        changed_sources[source_name] = changed_sources[source_name].replace(old, new, 1)
        mutations.append((interact, changed_sources))

    rejected = 0
    for changed_interact, changed_sources in mutations:
        try:
            verify_contract(changed_interact, changed_sources)
        except ValueError:
            rejected += 1
        else:
            raise AssertionError("Console Setup contract accepted an adversarial mutation")

    print(
        "PASS Console Setup action/CDC/input contract "
        f"({rejected} adversarial mutations rejected)"
    )


if __name__ == "__main__":
    main()
