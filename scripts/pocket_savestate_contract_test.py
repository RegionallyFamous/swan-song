#!/usr/bin/env python3
"""Source-level gates for the intentionally disabled Pocket Memories path."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


class PocketSavestateContract(unittest.TestCase):
    def test_mister_max_payload_derivation(self) -> None:
        rtl = source("src/fpga/core/rtl/savestates.vhd")
        self.assertRegex(rtl, r"HEADERCOUNT\s*:\s*integer\s*:=\s*2\s*;")
        self.assertRegex(rtl, r"INTERNALSCOUNT\s*:\s*integer\s*:=\s*63\s*;")
        self.assertRegex(rtl, r"256,\s*--\s*REGISTER")
        self.assertRegex(rtl, r"65536,\s*--\s*RAM")
        self.assertRegex(rtl, r'when\s+x"05"\s*=>\s*savetypes\(2\)\s*<=\s*524288')
        self.assertIn(
            "bus_out_Adr <= std_logic_vector(unsigned(bus_out_Adr) + 2);",
            rtl,
        )

        header_bytes = 2 * 4
        internal_bytes = 63 * 8
        register_bytes = 256
        system_ram_bytes = 65536
        max_sram_bytes = 524288
        self.assertEqual(
            header_bytes
            + internal_bytes
            + register_bytes
            + system_ram_bytes
            + max_sram_bytes,
            0x90300,
        )

    def test_envelope_defaults_and_pocket_query_size(self) -> None:
        envelope = compact(source("src/fpga/core/apf_savestate_envelope.sv"))
        self.assertIn("parameter[31:0]PAYLOAD_BYTES=32'h0009_0300", envelope)
        self.assertIn("parameter[31:0]FORMAT_ID=32'h5753_0001", envelope)
        self.assertIn("localparam[31:0]MAGIC=32'h5357_414e", envelope)
        self.assertIn("localparam[31:0]VERSION=32'd1", envelope)
        self.assertIn("localparam[31:0]HEADER_BYTES=32'd32", envelope)
        self.assertIn("localparam[31:0]TOTAL_BYTES=PAYLOAD_BYTES+HEADER_BYTES", envelope)

        top = compact(source("src/fpga/core/core_top.v"))
        self.assertIn("wire[31:0]savestate_size=32'h9_0320;", top)
        self.assertIn("wire[31:0]savestate_maxloadsize=32'h9_0320;", top)

    def test_support_remains_disabled_and_requests_fail_closed(self) -> None:
        core = json.loads(source("dist/Cores/agg23.WonderSwan/core.json"))
        self.assertIs(core["core"]["framework"]["sleep_supported"], False)

        top = compact(source("src/fpga/core/core_top.v"))
        self.assertIn("wiresavestate_supported=0;", top)

        commands = compact(source("src/fpga/core/core_bridge_cmd.v"))
        self.assertIn("if(host_20[0]&&savestate_supported)begin", commands)
        self.assertEqual(commands.count("if(host_20[0]&&savestate_supported)begin"), 2)

        # The envelope is a staging-memory contract, not permission to connect
        # its streaming output to the live MiSTer state bus.
        controller = source("src/fpga/core/save_state_controller.sv")
        self.assertNotIn("apf_savestate_envelope", controller)

        # The protected full-blob coordinator is an isolated integration
        # contract. It must remain outside production RTL until its SDRAM and
        # clock-domain adapters exist and pass the documented gates.
        staging = compact(source("src/fpga/core/apf_savestate_staging.sv"))
        self.assertIn("load_staged_bytes==PAYLOAD_BYTES", staging)
        self.assertIn("outputregrestore_start", staging)
        self.assertIn("outputwirerestore_read_permitted", staging)
        self.assertNotIn("apf_savestate_staging", top)
        qsf = source("src/fpga/ap_core.qsf")
        self.assertNotIn("core/apf_savestate_staging.sv", qsf)

    def test_build_and_regression_include_the_contract(self) -> None:
        qsf = source("src/fpga/ap_core.qsf")
        self.assertIn(
            "set_global_assignment -name SYSTEMVERILOG_FILE core/apf_savestate_envelope.sv",
            qsf,
        )
        regression = source("scripts/regression.sh")
        self.assertIn('"$ROOT/sim/rtl/run_apf_savestate_envelope_tb.sh"', regression)
        self.assertIn('"$ROOT/sim/rtl/run_apf_savestate_staging_tb.sh"', regression)
        self.assertIn('python3 "$ROOT/scripts/pocket_savestate_contract_test.py"', regression)


if __name__ == "__main__":
    unittest.main()
