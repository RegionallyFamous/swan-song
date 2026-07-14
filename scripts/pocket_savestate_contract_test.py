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


def disabled_transport_violations(top_text: str) -> list[str]:
    """Return structural failures in the compile-time Memories boundary."""

    top = compact(top_text)
    required = (
        "localparamSAVESTATE_SUPPORTED=1'b0;",
        "wiresavestate_supported=SAVESTATE_SUPPORTED;",
        "bridge_rd_data<=savestate_supported?"
        "save_state_bridge_read_data:32'd0;",
        "if(SAVESTATE_SUPPORTED)begin:gen_save_state_controller",
        "elsebegin:gen_save_state_disabled",
        "assignsave_state_bridge_read_data=32'd0;",
        "assignsavestate_load_ack=1'b0;",
        "assignsavestate_load_busy=1'b0;",
        "assignsavestate_load_ok=1'b0;",
        "assignsavestate_load_err=1'b0;",
        "assignsavestate_start_ack=1'b0;",
        "assignsavestate_start_busy=1'b0;",
        "assignsavestate_start_ok=1'b0;",
        "assignsavestate_start_err=1'b0;",
        "assignss_save=1'b0;",
        "assignss_load=1'b0;",
        "assignss_dout=64'd0;",
        "assignss_ack=1'b0;",
        "wirememories_pause_request=1'b0;",
    )
    failures = [token for token in required if token not in top]

    enabled_marker = "if(SAVESTATE_SUPPORTED)begin:gen_save_state_controller"
    disabled_marker = "elsebegin:gen_save_state_disabled"
    if enabled_marker in top and disabled_marker in top:
        enabled_start = top.index(enabled_marker)
        disabled_start = top.index(disabled_marker, enabled_start)
        enabled = top[enabled_start:disabled_start]
        disabled = top[disabled_start:]
        if "save_state_controllersave_state_controller(" not in enabled:
            failures.append("controller-not-in-enabled-generate")
        if "save_state_controllersave_state_controller(" in disabled:
            failures.append("controller-present-in-disabled-generate")

    if top.count("save_state_controllersave_state_controller(") != 1:
        failures.append("controller-instance-count")
    if top.count("savestate_supported?save_state_bridge_read_data:32'd0") != 1:
        failures.append("raw-window-gate-count")
    return failures


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
        core = json.loads(source("dist/Cores/RegionallyFamous.SwanSong/core.json"))
        self.assertIs(core["core"]["framework"]["sleep_supported"], False)

        top_text = source("src/fpga/core/core_top.v")
        top = compact(top_text)
        self.assertEqual(disabled_transport_violations(top_text), [])

        # The command handler is not the only route into the legacy state
        # transport: core_top also owns a raw 0x4 bridge window.  Keep that
        # entire boundary capability-gated while Memories is unadvertised so
        # its 16-M10K load FIFO cannot survive synthesis as a dormant back
        # door. The controller exists only in a compile-time-disabled generate
        # branch, and the live branch drives every response and engine input
        # to an inert value.
        self.assertIn("32'h4xxxxxxx:begin", top)

        commands = compact(source("src/fpga/core/core_bridge_cmd.v"))
        self.assertIn("if(host_20[0]&&savestate_supported)begin", commands)
        self.assertEqual(commands.count("if(host_20[0]&&savestate_supported)begin"), 2)

        # The controller stub must not remove SwanTop's internal state manager:
        # that block also turns the external reset into the console reset.
        wonderswan = compact(source("src/fpga/core/wonderswan.sv"))
        self.assertIn(".save_state(ss_save)", wonderswan)
        self.assertIn(".load_state(ss_load)", wonderswan)
        self.assertIn(".SAVE_out_Dout(ss_dout)", wonderswan)
        self.assertIn(".SAVE_out_done(ss_ack)", wonderswan)

        swantop = compact(source("src/fpga/core/rtl/swanTop.vhd"))
        self.assertIn("isavestates:entitywork.savestates", swantop)
        self.assertIn("reset_in=>reset_in", swantop)
        self.assertIn("reset_out=>reset", swantop)
        self.assertIn("save=>savestate_savestate", swantop)
        self.assertIn("load=>savestate_loadstate", swantop)

        manager = compact(source("src/fpga/core/rtl/savestates.vhd"))
        self.assertIn("if(reset_in='1')thenreset_out<='1';", manager)
        self.assertIn("if(reset_in='1')thenstate<=IDLE;", manager)

    def test_disabled_transport_mutations_are_rejected(self) -> None:
        top = source("src/fpga/core/core_top.v")
        mutations = (
            ("localparam SAVESTATE_SUPPORTED = 1'b0;", "localparam SAVESTATE_SUPPORTED = 1'b1;"),
            ("wire savestate_supported = SAVESTATE_SUPPORTED;", "wire savestate_supported = 1'b1;"),
            ("if (SAVESTATE_SUPPORTED) begin : gen_save_state_controller", "if (1'b1) begin : gen_save_state_controller"),
            ("assign save_state_bridge_read_data = 32'd0;", "assign save_state_bridge_read_data = bridge_wr_data;"),
            ("assign savestate_start_ack = 1'b0;", "assign savestate_start_ack = savestate_start;"),
            ("assign savestate_load_ack = 1'b0;", "assign savestate_load_ack = savestate_load;"),
            ("assign ss_save = 1'b0;", "assign ss_save = savestate_start;"),
            ("assign ss_load = 1'b0;", "assign ss_load = savestate_load;"),
            ("assign ss_dout = 64'd0;", "assign ss_dout = ss_din;"),
            ("assign ss_ack = 1'b0;", "assign ss_ack = ss_req;"),
            (
                "wire memories_pause_request = 1'b0;",
                "wire memories_pause_request = savestate_start;",
            ),
        )
        for original, replacement in mutations:
            with self.subTest(replacement=replacement):
                self.assertEqual(top.count(original), 1)
                mutated = top.replace(original, replacement, 1)
                self.assertTrue(disabled_transport_violations(mutated))

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
        self.assertIn('"$ROOT/sim/rtl/run_savestate_disabled_reset_tb.sh"', regression)
        self.assertIn('python3 "$ROOT/scripts/pocket_savestate_contract_test.py"', regression)

    def test_runtime_pause_boundary_is_compiled_but_unreachable(self) -> None:
        pause = compact(source("src/fpga/core/rtl/memories_pause.vhd"))
        self.assertIn("elsifsafe_boundary='1'", pause)
        self.assertIn(
            "pause_gate<=pause_gate_heldor(requestandsafe_boundary)whenstate=WAIT_BOUNDARYelsepause_gate_held;",
            pause,
        )
        self.assertIn("pause_gate_held<='1';state<=ARM_ACK;", pause)
        self.assertIn("whenARM_ACK=>", pause)
        self.assertIn("whenWAIT_RESUME=>", pause)
        self.assertIn("ifresume_ready='1'thenpause_ack<='0';", pause)

        swantop = compact(source("src/fpga/core/rtl/swanTop.vhd"))
        self.assertIn("imemories_pause:entitywork.memories_pause", swantop)
        self.assertIn("request=>memories_pause_request", swantop)
        self.assertIn("pause_ack=>memories_pause_ack", swantop)
        self.assertIn("pause_in='1'ormemories_pause_gate='1'", swantop)
        self.assertIn(
            "system_idle='1'andce='0'andce_cpu='0'andce_4x='0'",
            swantop,
        )

        wrapper = compact(source("src/fpga/core/wonderswan.sv"))
        self.assertIn(".memories_pause_request(memories_pause_request)", wrapper)
        self.assertIn(".memories_pause_ack(memories_pause_ack)", wrapper)

        harness = compact(source("sim/verilator/sim_main.cpp"))
        self.assertIn("top->memories_pause_request=0;", harness)

        top = compact(source("src/fpga/core/core_top.v"))
        self.assertIn("wirememories_pause_request=1'b0;", top)
        self.assertIn(".memories_pause_request(memories_pause_request)", top)
        self.assertIn(".memories_pause_ack(memories_pause_ack)", top)
        self.assertEqual(disabled_transport_violations(source("src/fpga/core/core_top.v")), [])

        qsf = source("src/fpga/ap_core.qsf")
        pause_qsf = (
            "set_global_assignment -name VHDL_FILE core/rtl/memories_pause.vhd"
        )
        swantop_qsf = "set_global_assignment -name VHDL_FILE core/rtl/swanTop.vhd"
        self.assertIn(pause_qsf, qsf)
        self.assertLess(qsf.index(pause_qsf), qsf.index(swantop_qsf))

        translation = source("sim/verilator/translate_vhdl.sh")
        pause_translate = "src/fpga/core/rtl/memories_pause.vhd"
        swantop_translate = "src/fpga/core/rtl/swanTop.vhd"
        self.assertIn(pause_translate, translation)
        self.assertLess(
            translation.index(pause_translate), translation.index(swantop_translate)
        )

        regression = source("scripts/regression.sh")
        self.assertIn('"$ROOT/sim/rtl/run_memories_pause_tb.sh"', regression)

    def test_v2_crc_primitive_remains_isolated(self) -> None:
        crc = compact(source("src/fpga/core/apf_crc64_ecma32.sv"))
        self.assertIn("localparam[63:0]POLYNOMIAL=64'h42f0_e1eb_a9ea_3693", crc)
        self.assertIn("update_byte(next_crc,data_word[31:24])", crc)
        self.assertIn("update_byte(next_crc,data_word[7:0])", crc)
        self.assertIn("elseif(clear)crc_value<=64'd0", crc)

        qsf = source("src/fpga/ap_core.qsf")
        self.assertNotIn("apf_crc64_ecma32.sv", qsf)
        for relative in (
            "src/fpga/core/core_top.v",
            "src/fpga/core/apf_savestate_envelope.sv",
            "src/fpga/core/apf_savestate_staging.sv",
            "src/fpga/core/save_state_controller.sv",
        ):
            self.assertNotIn("apf_crc64_ecma32", source(relative))

        regression = source("scripts/regression.sh")
        self.assertIn('"$ROOT/sim/rtl/run_apf_crc64_ecma32_tb.sh"', regression)
        integrity_doc = source("SAVESTATE_V2_INTEGRITY.md")
        self.assertIn("Status: **isolated and not integrated.**", integrity_doc)

    def test_sdram_writer_remains_isolated(self) -> None:
        writer = compact(source("src/fpga/core/apf_savestate_sdram_writer.sv"))
        self.assertIn("parameter[31:0]STAGE_BASE_BYTE=32'h0110_0000", writer)
        self.assertIn("parameter[31:0]STAGE_BYTES=32'h0009_0300", writer)
        self.assertIn("stage_word_offset[1:0]==2'b00", writer)
        self.assertIn("commit_pulse<=1'b1", writer)
        self.assertIn("state<=STATE_ABORT_DRAIN", writer)

        qsf = source("src/fpga/ap_core.qsf")
        self.assertNotIn("apf_savestate_sdram_writer.sv", qsf)
        for relative in (
            "src/fpga/core/core_top.v",
            "src/fpga/core/apf_savestate_envelope.sv",
            "src/fpga/core/apf_savestate_staging.sv",
            "src/fpga/core/save_state_controller.sv",
            "src/fpga/core/rtl/sdram.sv",
        ):
            self.assertNotIn("apf_savestate_sdram_writer", source(relative))

        regression = source("scripts/regression.sh")
        self.assertIn(
            '"$ROOT/sim/rtl/run_apf_savestate_sdram_writer_tb.sh"',
            regression,
        )
        writer_doc = source("SAVESTATE_SDRAM_WRITER.md")
        self.assertIn(
            "Status: **implemented and adversarially tested in isolation;",
            writer_doc,
        )

    def test_sdram_reader_remains_isolated(self) -> None:
        reader = compact(source("src/fpga/core/apf_savestate_sdram_reader.sv"))
        self.assertIn("parameter[31:0]STAGE_BASE_BYTE=32'h0110_0000", reader)
        self.assertIn("parameter[31:0]STAGE_BYTES=32'h0009_0300", reader)
        self.assertIn("read_request_offset[1:0]==2'b00", reader)
        self.assertIn("pending_low_data[7:0]", reader)
        self.assertIn("assignread_word_valid=cache_valid", reader)
        self.assertIn("state==STATE_ABORT_DRAIN", reader)

        qsf = source("src/fpga/ap_core.qsf")
        self.assertNotIn("apf_savestate_sdram_reader.sv", qsf)
        for relative in (
            "src/fpga/core/core_top.v",
            "src/fpga/core/apf_savestate_envelope.sv",
            "src/fpga/core/apf_savestate_staging.sv",
            "src/fpga/core/save_state_controller.sv",
            "src/fpga/core/rtl/sdram.sv",
        ):
            self.assertNotIn("apf_savestate_sdram_reader", source(relative))

        regression = source("scripts/regression.sh")
        self.assertIn(
            '"$ROOT/sim/rtl/run_apf_savestate_sdram_reader_tb.sh"',
            regression,
        )
        reader_doc = source("SAVESTATE_SDRAM_READER.md")
        self.assertIn(
            "Status: **implemented and adversarially tested in isolation;",
            reader_doc,
        )
        self.assertIn("before the *next* read strobe", reader_doc)

    def test_a0_service_proof_remains_fail_closed_and_isolated(self) -> None:
        model = source("scripts/apf_a0_prefetch_service_model.py")
        self.assertIn("DEFAULT_BRIDGE_PERIOD_CYCLES = 88", model)
        self.assertIn("DEFAULT_MEMORY_CLOCK_HZ = 110_592_000", model)
        self.assertIn("DEFAULT_PAYLOAD_BYTES = 0x90300", model)
        self.assertIn("word_service_bound_mem_cycles", model)
        self.assertIn('"status": "unproven"', model)
        self.assertIn('"minimum_fifo_depth_words": None', model)

        regression = source("scripts/regression.sh")
        self.assertIn(
            'python3 "$ROOT/scripts/apf_a0_prefetch_service_model_test.py"',
            regression,
        )
        proof = source("A0_BRIDGE_SERVICE_PROOF.md")
        self.assertIn("every 88 cycles", proof)
        self.assertIn("No streaming FIFO", proof)
        self.assertIn("Memories remains disabled", proof)

        # This research/model slice must not alter any production source list
        # or instantiate a bridge prefetch engine behind the model's back.
        qsf = source("src/fpga/ap_core.qsf")
        self.assertNotIn("a0_prefetch", qsf.lower())
        for relative in (
            "src/fpga/core/core_top.v",
            "src/fpga/core/apf_savestate_sdram_reader.sv",
            "src/fpga/core/rtl/sdram.sv",
        ):
            self.assertNotIn("a0_prefetch", source(relative).lower())


if __name__ == "__main__":
    unittest.main()
