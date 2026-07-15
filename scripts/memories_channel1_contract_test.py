#!/usr/bin/env python3
"""Fail-closed source contract for the disabled Memories channel-1 boundary."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def require(text: str, needle: str, message: str) -> None:
    if needle not in text:
        raise AssertionError(message)


def verify_ch3_payload_latch(
    sdram: str, bench: str, runner: str
) -> None:
    edge_start = sdram.find("if (ch3_req & ~ch3_req_1) begin")
    if edge_start < 0:
        raise AssertionError("SDRAM channel-3 request edge is missing")
    edge_end = sdram.find("\n\tend", edge_start)
    if edge_end < 0:
        raise AssertionError("SDRAM channel-3 request-edge block is malformed")
    edge_block = sdram[edge_start:edge_end]
    for assignment in (
        "ch3_rq     <= 1;",
        "ch3_rnw_1  <= ch3_rnw;",
        "ch3_addr_1 <= ch3_addr;",
        "ch3_din_1  <= ch3_din;",
        "ch3_be_1   <= ch3_be;",
    ):
        require(
            edge_block,
            assignment,
            f"channel-3 edge does not atomically capture {assignment}",
        )
        if sdram.count(assignment) != 1:
            raise AssertionError(
                f"channel-3 payload assignment is duplicated: {assignment}"
            )

    for fragment in (
        '"refresh before delayed ch3 read"',
        '"refresh before delayed ch3 write"',
        "ch3_addr = 26'h02abcde;",
        "ch3_din = 16'hdead;",
        "ch3_rnw = 1'b0;",
        "dut.ch3_addr_1 == 26'h0123456",
        "dut.ch3_din_1 == 16'hbeef",
        "read_commands == baseline_read + 1",
        "write_commands == baseline_write + 1",
        "ready_pulses == baseline_ready + 1",
    ):
        require(
            bench,
            fragment,
            f"SDRAM bench omits delayed/poisoned channel-3 evidence: {fragment}",
        )
    require(
        runner,
        'if ! output="$($BUILD/obj_dir/sdram_quiescent_tb 2>&1)"; then',
        "SDRAM runner hides a failing simulation diagnostic",
    )


def main() -> None:
    wonderswan = (ROOT / "src/fpga/core/wonderswan.sv").read_text(encoding="utf-8")
    core_top = (ROOT / "src/fpga/core/core_top.v").read_text(encoding="utf-8")
    qsf = (ROOT / "src/fpga/ap_core.qsf").read_text(encoding="utf-8")
    regression = (ROOT / "scripts/regression.sh").read_text(encoding="utf-8")
    sdram = (ROOT / "src/fpga/core/rtl/sdram.sv").read_text(encoding="utf-8")
    sdram_bench = (ROOT / "sim/rtl/sdram_quiescent_tb.sv").read_text(
        encoding="utf-8"
    )
    sdram_runner = (ROOT / "sim/rtl/run_sdram_quiescent_tb.sh").read_text(
        encoding="utf-8"
    )
    core_json = json.loads(
        (ROOT / "dist/Cores/RegionallyFamous.SwanSong/core.json").read_text(
            encoding="utf-8"
        )
    )

    require(
        qsf,
        "SYSTEMVERILOG_FILE core/apf_sdram_channel1_mux.sv",
        "Quartus does not compile the channel-1 owner",
    )
    require(
        regression,
        '"$ROOT/sim/rtl/run_apf_sdram_channel1_mux_tb.sh"',
        "regression does not run the channel-1 owner bench",
    )
    require(
        core_top,
        "localparam SAVESTATE_SUPPORTED = 1'b0;",
        "Memories support was enabled before its release gates",
    )
    require(
        core_top,
        "wire savestate_supported = SAVESTATE_SUPPORTED;",
        "APF capability reporting bypasses the disabled compile-time gate",
    )
    require(
        core_top,
        "else begin : gen_save_state_disabled",
        "disabled Memories transport is not compiled through its fail-closed branch",
    )
    if core_json["core"]["framework"]["sleep_supported"] is not False:
        raise AssertionError("Sleep was enabled before its release gates")

    verify_ch3_payload_latch(sdram, sdram_bench, sdram_runner)

    mutations = (
        (
            "sdram",
            "ch3_rnw_1  <= ch3_rnw;",
            "ch3_rnw_1  <= 1'b0;",
        ),
        (
            "sdram",
            "ch3_addr_1 <= ch3_addr;",
            "ch3_addr_1 <= '0;",
        ),
        (
            "bench",
            "dut.ch3_addr_1 == 26'h0123456",
            "dut.ch3_addr_1 == ch3_addr",
        ),
        (
            "bench",
            "write_commands == baseline_write + 1",
            "write_commands >= baseline_write + 1",
        ),
        (
            "runner",
            'if ! output="$($BUILD/obj_dir/sdram_quiescent_tb 2>&1)"; then',
            'output="$($BUILD/obj_dir/sdram_quiescent_tb 2>&1)"',
        ),
    )
    originals = {"sdram": sdram, "bench": sdram_bench, "runner": sdram_runner}
    for name, original, replacement in mutations:
        if originals[name].count(original) != 1:
            raise AssertionError(f"mutation source is missing or ambiguous: {original}")
        changed = dict(originals)
        changed[name] = changed[name].replace(original, replacement, 1)
        try:
            verify_ch3_payload_latch(
                changed["sdram"], changed["bench"], changed["runner"]
            )
        except AssertionError:
            pass
        else:
            raise AssertionError(f"channel-3 contract accepted mutation: {original}")

    instance_start = wonderswan.index("apf_sdram_channel1_mux channel1_owner")
    instance_end = wonderswan.index("\n  );", instance_start)
    instance = wonderswan[instance_start:instance_end]
    for needle, message in (
        (".stage_acquire(1'b0)", "production staging acquisition is not tied off"),
        (".runtime_quiesced(1'b0)", "unproven quiescence can reach the owner"),
        (".stage_req(1'b0)", "production staging requests are not tied off"),
        (".rom_req(rom_sdram_req)", "ROM request bypasses the owner"),
        (".rom_ready(rom_sdram_ready)", "ROM completion bypasses the owner"),
        (".sdram_req(ch1_sdram_req)", "physical request is not owner-routed"),
        (".sdram_ready(ch1_sdram_ready)", "physical completion is not owner-routed"),
    ):
        require(instance, needle, message)

    for needle, message in (
        (".ch1_req  (ch1_sdram_req)", "SDRAM ch1 request bypasses owner"),
        (".ch1_ready(ch1_sdram_ready)", "SDRAM ch1 ready bypasses owner"),
        (".ch1_dout (ch1_sdram_read_data)", "SDRAM ch1 read data is discarded"),
        (
            ".ch1_addr ({1'b0, ch1_sdram_word_addr})",
            "SDRAM ch1 does not retain the full physical word address",
        ),
        (".ch2_req  (ch2_sdram_req)", "channel-2 drain is not observable"),
        (".ch3_req (ch3_sdram_req)", "channel-3 drain is not observable"),
        (".ch3_ready(ch3_sdram_ready)", "channel-3 completion is discarded"),
        (".quiescent(sdram_quiescent)", "global SDRAM drain is discarded"),
    ):
        require(wonderswan, needle, message)

    print("PASS disabled Memories channel1 source contract")


if __name__ == "__main__":
    main()
