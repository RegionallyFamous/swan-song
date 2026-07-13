#!/usr/bin/env python3
"""Fail-closed source contract for the disabled Memories channel-1 boundary."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def require(text: str, needle: str, message: str) -> None:
    if needle not in text:
        raise AssertionError(message)


def main() -> None:
    wonderswan = (ROOT / "src/fpga/core/wonderswan.sv").read_text(encoding="utf-8")
    core_top = (ROOT / "src/fpga/core/core_top.v").read_text(encoding="utf-8")
    qsf = (ROOT / "src/fpga/ap_core.qsf").read_text(encoding="utf-8")
    regression = (ROOT / "scripts/regression.sh").read_text(encoding="utf-8")
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
        "wire savestate_supported = 0;",
        "Memories support was enabled before its release gates",
    )
    if core_json["core"]["framework"]["sleep_supported"] is not False:
        raise AssertionError("Sleep was enabled before its release gates")

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
