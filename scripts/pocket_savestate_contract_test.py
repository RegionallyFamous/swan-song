#!/usr/bin/env python3
"""Source-level gates for the intentionally disabled Pocket Memories path."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def active_c_like(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", text)


def sram_artifact_safety_violations(harness_text: str) -> list[str]:
    """Return failures in the simulator's fresh no-replace SRAM contract."""

    harness = compact(active_c_like(harness_text))
    publisher_start = harness.find("staticvoidwrite_binary_atomic(")
    publisher_end = harness.find(
        "staticstd::stringmanifest_relative_path(", publisher_start
    )
    publisher = (
        harness[publisher_start:publisher_end]
        if publisher_start >= 0 and publisher_end > publisher_start
        else ""
    )
    required = (
        "staticvoidrequire_fresh_output(constfs::path&path,constchar*description)",
        "require_fresh_output(sram_out_path,\"SRAMoutput\");",
        "require_fresh_output(sram_temporary_path,\"SRAMtemporaryoutput\");",
        "require_fresh_output(path,\"SRAMoutput\");",
        "require_fresh_output(temporary,\"SRAMtemporaryoutput\");",
        "fs::create_directory(temporary,temporary_error)",
        "output.write(reinterpret_cast<constchar*>(bytes.data()),"
        "static_cast<std::streamsize>(count));",
        "output.close();if(!output)",
        "fs::create_hard_link(temporary_payload,path,publish_error);",
        "if(publish_error){",
        "fs::remove(temporary_payload,payload_cleanup_error);",
        "fs::remove(temporary,directory_cleanup_error);",
        "if(payload_cleanup_error||directory_cleanup_error){std::cerr<<",
        "warning:SRAMoutputwaspublishedsuccessfullybuttemporary",
        "cleanupfailed:",
        "createafreshexactfooter-sizedSRAMartifact",
    )
    failures = [token for token in required if token not in harness]
    if "fs::rename(temporary_payload,path" in publisher:
        failures.append("SRAM publish may replace an existing destination")
    if "fs::remove(path" in publisher:
        failures.append("SRAM cleanup may remove the public destination by pathname")
    cleanup_start = publisher.find("std::error_codepayload_cleanup_error;")
    if cleanup_start < 0 or "throw" in publisher[cleanup_start:]:
        failures.append("SRAM post-commit cleanup must not turn success into failure")

    publisher_order = (
        "require_fresh_output(path,\"SRAMoutput\");",
        "require_fresh_output(temporary,\"SRAMtemporaryoutput\");",
        "fs::create_directory(temporary,temporary_error)",
        "output.write(reinterpret_cast<constchar*>(bytes.data()),",
        "output.close();",
        "fs::create_hard_link(temporary_payload,path,publish_error);",
        "fs::remove(temporary_payload,payload_cleanup_error);",
        "fs::remove(temporary,directory_cleanup_error);",
    )
    publisher_positions = [publisher.find(token) for token in publisher_order]
    if (
        any(position < 0 for position in publisher_positions)
        or publisher_positions != sorted(publisher_positions)
    ):
        failures.append("SRAM publisher lifecycle ordering is incomplete")

    early_check = harness.find(
        "require_fresh_output(sram_out_path,\"SRAMoutput\");"
    )
    rom_read = harness.find("constautorom=read_file(rom_path);")
    publish = harness.rfind("write_binary_atomic(sram_out_path,sram,sram_payload_bytes);")
    success_gate = harness.find("if(iram_expectation&&!iram_expectation_met){")
    if min(early_check, rom_read, publish, success_gate) < 0:
        failures.append("SRAM artifact lifecycle ordering is incomplete")
    elif not early_check < rom_read < success_gate < publish:
        failures.append(
            "SRAM artifact must be preflighted early and published only after success"
        )
    return failures


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


def device_state_plumbing_violations(
    overrides: dict[str, str] | None = None,
) -> list[str]:
    """Return failures in the inert RTC/EEPROM native-state hierarchy."""

    overrides = overrides or {}

    def selected(relative: str) -> str:
        return compact(overrides.get(relative, source(relative)))

    top = selected("src/fpga/core/core_top.v")
    wrapper = selected("src/fpga/core/wonderswan.sv")
    swantop = selected("src/fpga/core/rtl/swanTop.vhd")
    memorymux = selected("src/fpga/core/rtl/memorymux.vhd")
    harness = selected("sim/verilator/sim_main.cpp")

    required: dict[str, tuple[str, ...]] = {
        "core_top": (
            "wirertc_state_freeze=1'b0;",
            "wirertc_state_frozen;",
            "wirertc_state_load=1'b0;",
            "wire[255:0]rtc_state_data_in=256'd0;",
            "wire[255:0]rtc_state_data_out;",
            "wireinternal_eeprom_state_freeze=1'b0;",
            "wireinternal_eeprom_state_frozen;",
            "wireinternal_eeprom_state_load=1'b0;",
            "wire[127:0]internal_eeprom_state_in=128'd0;",
            "wire[127:0]internal_eeprom_state_out;",
            "wirecartridge_eeprom_state_freeze=1'b0;",
            "wirecartridge_eeprom_state_frozen;",
            "wirecartridge_eeprom_state_load=1'b0;",
            "wire[127:0]cartridge_eeprom_state_in=128'd0;",
            "wire[127:0]cartridge_eeprom_state_out;",
            ".rtc_state_freeze(rtc_state_freeze)",
            ".rtc_state_frozen(rtc_state_frozen)",
            ".rtc_state_load(rtc_state_load)",
            ".rtc_state_data_in(rtc_state_data_in)",
            ".rtc_state_data_out(rtc_state_data_out)",
            ".internal_eeprom_state_freeze(internal_eeprom_state_freeze)",
            ".internal_eeprom_state_frozen(internal_eeprom_state_frozen)",
            ".internal_eeprom_state_load(internal_eeprom_state_load)",
            ".internal_eeprom_state_in(internal_eeprom_state_in)",
            ".internal_eeprom_state_out(internal_eeprom_state_out)",
            ".cartridge_eeprom_state_freeze(cartridge_eeprom_state_freeze)",
            ".cartridge_eeprom_state_frozen(cartridge_eeprom_state_frozen)",
            ".cartridge_eeprom_state_load(cartridge_eeprom_state_load)",
            ".cartridge_eeprom_state_in(cartridge_eeprom_state_in)",
            ".cartridge_eeprom_state_out(cartridge_eeprom_state_out)",
        ),
        "wonderswan": (
            "inputwirertc_state_freeze,",
            "outputwirertc_state_frozen,",
            "inputwirertc_state_load,",
            "inputwire[255:0]rtc_state_data_in",
            "outputwire[255:0]rtc_state_data_out",
            "inputwireinternal_eeprom_state_freeze,",
            "outputwireinternal_eeprom_state_frozen,",
            "inputwireinternal_eeprom_state_load,",
            "inputwire[127:0]internal_eeprom_state_in",
            "outputwire[127:0]internal_eeprom_state_out",
            "inputwirecartridge_eeprom_state_freeze,",
            "outputwirecartridge_eeprom_state_frozen,",
            "inputwirecartridge_eeprom_state_load,",
            "inputwire[127:0]cartridge_eeprom_state_in",
            "outputwire[127:0]cartridge_eeprom_state_out",
            ".rtc_state_freeze(rtc_state_freeze)",
            ".rtc_state_frozen(rtc_state_frozen)",
            ".rtc_state_load(rtc_state_load)",
            ".rtc_state_data_in(rtc_state_data_in)",
            ".rtc_state_data_out(rtc_state_data_out)",
            ".internal_eeprom_state_freeze(internal_eeprom_state_freeze)",
            ".internal_eeprom_state_frozen(internal_eeprom_state_frozen)",
            ".internal_eeprom_state_load(internal_eeprom_state_load)",
            ".internal_eeprom_state_in(internal_eeprom_state_in)",
            ".internal_eeprom_state_out(internal_eeprom_state_out)",
            ".cartridge_eeprom_state_freeze(cartridge_eeprom_state_freeze)",
            ".cartridge_eeprom_state_frozen(cartridge_eeprom_state_frozen)",
            ".cartridge_eeprom_state_load(cartridge_eeprom_state_load)",
            ".cartridge_eeprom_state_in(cartridge_eeprom_state_in)",
            ".cartridge_eeprom_state_out(cartridge_eeprom_state_out)",
        ),
        "swantop": (
            "rtc_state_freeze:instd_logic:='0';",
            "rtc_state_frozen:outstd_logic:='0';",
            "rtc_state_load:instd_logic:='0';",
            "rtc_state_data_in:instd_logic_vector(255downto0)",
            "rtc_state_data_out:outstd_logic_vector(255downto0)",
            "internal_eeprom_state_freeze:instd_logic:='0';",
            "internal_eeprom_state_frozen:outstd_logic:='0';",
            "internal_eeprom_state_load:instd_logic:='0';",
            "internal_eeprom_state_in:instd_logic_vector(127downto0)",
            "internal_eeprom_state_out:outstd_logic_vector(127downto0)",
            "cartridge_eeprom_state_freeze:instd_logic:='0';",
            "cartridge_eeprom_state_frozen:outstd_logic:='0';",
            "cartridge_eeprom_state_load:instd_logic:='0';",
            "cartridge_eeprom_state_in:instd_logic_vector(127downto0)",
            "cartridge_eeprom_state_out:outstd_logic_vector(127downto0)",
            "state_freeze=>rtc_state_freeze",
            "state_frozen=>rtc_state_frozen",
            "state_load=>rtc_state_load",
            "state_data_in=>rtc_state_data_in",
            "state_data_out=>rtc_state_data_out",
            "internal_eeprom_state_freeze=>internal_eeprom_state_freeze",
            "internal_eeprom_state_frozen=>internal_eeprom_state_frozen",
            "internal_eeprom_state_load=>internal_eeprom_state_load",
            "internal_eeprom_state_in=>internal_eeprom_state_in",
            "internal_eeprom_state_out=>internal_eeprom_state_out",
            "cartridge_eeprom_state_freeze=>cartridge_eeprom_state_freeze",
            "cartridge_eeprom_state_frozen=>cartridge_eeprom_state_frozen",
            "cartridge_eeprom_state_load=>cartridge_eeprom_state_load",
            "cartridge_eeprom_state_in=>cartridge_eeprom_state_in",
            "cartridge_eeprom_state_out=>cartridge_eeprom_state_out",
        ),
        "memorymux": (
            "internal_eeprom_state_freeze:instd_logic:='0';",
            "internal_eeprom_state_frozen:outstd_logic:='0';",
            "internal_eeprom_state_load:instd_logic:='0';",
            "internal_eeprom_state_in:instd_logic_vector(127downto0)",
            "internal_eeprom_state_out:outstd_logic_vector(127downto0)",
            "cartridge_eeprom_state_freeze:instd_logic:='0';",
            "cartridge_eeprom_state_frozen:outstd_logic:='0';",
            "cartridge_eeprom_state_load:instd_logic:='0';",
            "cartridge_eeprom_state_in:instd_logic_vector(127downto0)",
            "cartridge_eeprom_state_out:outstd_logic_vector(127downto0)",
            "state_freeze=>internal_eeprom_state_freeze",
            "frozen_ack=>internal_eeprom_state_frozen",
            "state_load=>internal_eeprom_state_load",
            "state_in=>internal_eeprom_state_in",
            "state_out=>internal_eeprom_state_out",
            "state_freeze=>cartridge_eeprom_state_freeze",
            "frozen_ack=>cartridge_eeprom_state_frozen",
            "state_load=>cartridge_eeprom_state_load",
            "state_in=>cartridge_eeprom_state_in",
            "state_out=>cartridge_eeprom_state_out",
        ),
        "harness": (
            "top->rtc_state_freeze=0;",
            "top->rtc_state_load=0;",
            "word<8;++word)top->rtc_state_data_in[word]=0;",
            "top->internal_eeprom_state_freeze=0;",
            "top->internal_eeprom_state_load=0;",
            "word<4;++word){top->internal_eeprom_state_in[word]=0;}",
            "top->cartridge_eeprom_state_freeze=0;",
            "top->cartridge_eeprom_state_load=0;",
            "word<4;++word){top->cartridge_eeprom_state_in[word]=0;}",
        ),
    }
    texts = {
        "core_top": top,
        "wonderswan": wrapper,
        "swantop": swantop,
        "memorymux": memorymux,
        "harness": harness,
    }
    failures = [
        f"{name}:{token}"
        for name, tokens in required.items()
        for token in tokens
        if token not in texts[name]
    ]

    # Lower hierarchy levels must never regain a literal production tie-off.
    # Scope these checks to the exact device instances because soc_control and
    # the legacy state manager have independent, intentionally inert inputs.
    rtc_instance = swantop[
        swantop.index("irtc:entitywork.rtc") : swantop.index(
            "--savestates", swantop.index("irtc:entitywork.rtc")
        )
    ]
    internal_instance = memorymux[
        memorymux.index("ieeprom_int:entitywork.eeprom") : memorymux.index(
            "ieeprom_ext:entitywork.eeprom"
        )
    ]
    cartridge_instance = memorymux[memorymux.index("ieeprom_ext:entitywork.eeprom") :]
    for label, instance in (
        ("rtc-instance", rtc_instance),
        ("internal-instance", internal_instance),
        ("cartridge-instance", cartridge_instance),
    ):
        for token in (
            "state_freeze=>'0'",
            "frozen_ack=>open",
            "state_load=>'0'",
            "state_in=>(others=>'0')",
            "state_out=>open",
        ):
            if token in instance:
                failures.append(f"{label}:lower-tie:{token}")
    return failures


def load_settle_bound_violations(
    overrides: dict[str, str] | None = None,
) -> list[str]:
    """Bind the SV guard bound to both observed EEPROM settle schedules."""

    overrides = overrides or {}

    def selected(relative: str) -> str:
        return overrides.get(relative, source(relative))

    guard = selected("src/fpga/core/apf_savestate_v2_load_settle_guard.sv")
    device_tb = selected("sim/rtl/eeprom_state_tb.vhd")
    failures: list[str] = []

    guard_match = re.search(
        r"parameter\s+integer\s+MAX_ACK_LOW_CYCLES\s*=\s*(\d+)", guard
    )
    device_match = re.search(
        r"constant\s+MAX_V2_LOAD_ACK_LOW_CYCLES\s*:\s*natural\s*:=\s*(\d+)",
        device_tb,
        re.IGNORECASE,
    )
    if guard_match is None:
        failures.append("missing-guard-bound")
    if device_match is None:
        failures.append("missing-device-bound")
    if guard_match is not None and device_match is not None:
        guard_bound = int(guard_match.group(1))
        device_bound = int(device_match.group(1))
        if guard_bound != 2:
            failures.append(f"guard-bound:{guard_bound}")
        if device_bound != 2:
            failures.append(f"device-bound:{device_bound}")
        if guard_bound != device_bound:
            failures.append("bound-mismatch")

    for marker in (
        'report "state load was acknowledged before RAM settle"',
        'report "state load did not acknowledge after RAM settle"',
        "ack_low_samples <= MAX_V2_LOAD_ACK_LOW_CYCLES",
        "2 <= MAX_V2_LOAD_ACK_LOW_CYCLES",
        'report "legacy normalization exceeded settle-guard bound"',
    ):
        if marker not in device_tb:
            failures.append(f"missing-device-proof:{marker}")
    return failures


class PocketSavestateContract(unittest.TestCase):
    def test_direct_sram_export_is_a_fresh_no_replace_artifact(self) -> None:
        harness = source("sim/verilator/sim_main.cpp")
        self.assertEqual(sram_artifact_safety_violations(harness), [])

        mutations = (
            (
                "fs::create_hard_link(temporary_payload, path, publish_error);",
                "fs::rename(temporary_payload, path, publish_error);",
            ),
            (
                'require_fresh_output(sram_out_path, "SRAM output");',
                "// stale output accepted",
            ),
            (
                "static_cast<std::streamsize>(count));",
                "static_cast<std::streamsize>(0));",
            ),
            (
                "fs::remove(temporary_payload, payload_cleanup_error);",
                "fs::remove(path, payload_cleanup_error);",
            ),
            (
                "fs::create_hard_link(temporary_payload, path, publish_error);",
                "// fs::create_hard_link(temporary_payload, path, publish_error);",
            ),
            (
                "create a fresh exact footer-sized SRAM artifact",
                "atomically write exact footer-sized SRAM",
            ),
        )
        for original, replacement in mutations:
            with self.subTest(original=original):
                self.assertEqual(harness.count(original), 1)
                changed = harness.replace(original, replacement, 1)
                self.assertTrue(sram_artifact_safety_violations(changed))

    def test_direct_sram_publisher_runtime_no_replace(self) -> None:
        compiler = shutil.which("c++") or shutil.which("clang++") or shutil.which("g++")
        if compiler is None:
            self.skipTest("no C++17 compiler is available")

        harness = source("sim/verilator/sim_main.cpp")
        implementation_start = harness.index("static void require_fresh_output")
        implementation_end = harness.index(
            "static std::string manifest_relative_path", implementation_start
        )
        implementation = harness[implementation_start:implementation_end]
        translation_unit = (
            """
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <system_error>
#include <vector>

namespace fs = std::filesystem;
"""
            + implementation
            + """
int main(int argc, char** argv) {
  if (argc != 3) return 64;
  try {
    const unsigned long fill = std::stoul(argv[2], nullptr, 0);
    if (fill > 0xff) return 64;
    std::vector<uint8_t> bytes(128u * 1024u, static_cast<uint8_t>(fill));
    write_binary_atomic(argv[1], bytes, bytes.size());
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\\n';
    return 2;
  }
  return 0;
}
"""
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_path = root / "publisher.cpp"
            executable = root / "publisher"
            source_path.write_text(translation_unit, encoding="utf-8")
            compile_result = subprocess.run(
                [compiler, "-std=c++17", str(source_path), "-o", str(executable)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(compile_result.returncode, 0, compile_result.stderr)

            output = root / "success.sav"
            result = subprocess.run(
                [str(executable), str(output), "0x5a"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(output.read_bytes(), b"\x5a" * (128 * 1024))
            self.assertEqual(output.stat().st_nlink, 1)
            self.assertFalse(Path(f"{output}.tmp").exists())

            stale = root / "stale.sav"
            stale.write_bytes(b"older artifact")
            result = subprocess.run(
                [str(executable), str(stale), "0x6b"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(stale.read_bytes(), b"older artifact")
            self.assertFalse(Path(f"{stale}.tmp").exists())

            blocked = root / "blocked.sav"
            blocked_temporary = Path(f"{blocked}.tmp")
            blocked_temporary.mkdir()
            result = subprocess.run(
                [str(executable), str(blocked), "0x7c"],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(blocked.exists())
            self.assertTrue(blocked_temporary.is_dir())

            raced = root / "raced.sav"
            contenders = [
                subprocess.Popen(
                    [str(executable), str(raced), fill],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                for fill in ("0x2d", "0xa4")
            ]
            completed = [process.communicate() for process in contenders]
            returncodes = [process.returncode for process in contenders]
            self.assertEqual(returncodes.count(0), 1, completed)
            winner = 0x2D if returncodes[0] == 0 else 0xA4
            self.assertEqual(raced.read_bytes(), bytes((winner,)) * (128 * 1024))
            self.assertEqual(raced.stat().st_nlink, 1)
            self.assertFalse(Path(f"{raced}.tmp").exists())

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

    def test_native_device_state_buses_reach_only_the_disabled_boundary(self) -> None:
        self.assertEqual(device_state_plumbing_violations(), [])

        # This wiring exposes only the already-tested native device images. It
        # does not compile or advertise the isolated owner/walker/data plane.
        top = compact(source("src/fpga/core/core_top.v"))
        self.assertIn("localparamSAVESTATE_SUPPORTED=1'b0;", top)
        self.assertIn("wirememories_pause_request=1'b0;", top)
        core = json.loads(source("dist/Cores/RegionallyFamous.SwanSong/core.json"))
        self.assertIs(core["core"]["framework"]["sleep_supported"], False)

        qsf = source("src/fpga/ap_core.qsf")
        for isolated in (
            "core/apf_savestate_v2_owner.sv",
            "core/apf_savestate_v2_eeprom_walker.sv",
            "core/apf_savestate_v2_load_settle_guard.sv",
            "core/apf_savestate_staging.sv",
            "core/apf_savestate_sdram_writer.sv",
            "core/apf_savestate_sdram_reader.sv",
            "core/apf_savestate_v2_restore_preflight.sv",
        ):
            self.assertNotIn(isolated, qsf)

        # The native images are direct vectors: this hierarchy must not
        # reverse bytes or use concatenations as an implicit format adapter.
        wrapper = compact(source("src/fpga/core/wonderswan.sv"))
        swantop = compact(source("src/fpga/core/rtl/swanTop.vhd"))
        self.assertNotIn("{rtc_state_data_in", wrapper)
        self.assertNotIn("{internal_eeprom_state_in", wrapper)
        self.assertNotIn("{cartridge_eeprom_state_in", wrapper)
        self.assertNotIn("reverse", swantop)

    def test_v2_eeprom_load_settle_guard_is_bounded_and_isolated(self) -> None:
        self.assertEqual(load_settle_bound_violations(), [])
        guard = compact(
            source("src/fpga/core/apf_savestate_v2_load_settle_guard.sv")
        )
        self.assertIn("parameterintegerMAX_ACK_LOW_CYCLES=2", guard)
        self.assertIn(
            "assigndevice_settling=freeze_request&&!device_reset&&settling_i;",
            guard,
        )
        self.assertIn(
            "if(device_frozen_raw&&freeze_was_acknowledged)begin",
            guard,
        )
        self.assertIn("elseif(ack_low_cycles<MAX_ACK_LOW_CYCLES)begin", guard)
        self.assertIn("protocol_fault<=1'b1;", guard)
        self.assertNotIn("assigndevice_frozen_raw", guard)

        owner = compact(source("src/fpga/core/apf_savestate_v2_owner.sv"))
        self.assertIn("inputwire[DEVICE_COUNT-1:0]device_settling,", owner)
        self.assertIn("inputwiredevice_protocol_fault,", owner)
        self.assertIn(
            "wireall_devices_retained=&(device_frozen|device_settling);",
            owner,
        )
        self.assertIn(
            "wireall_devices_settled=all_devices_frozen&&!any_device_settling;",
            owner,
        )
        self.assertEqual(
            owner.count("datapath_quiescent&&all_devices_settled"), 2
        )
        self.assertIn(
            "if(device_protocol_fault||any_device_settling||"
            "(datapath_started&&!all_devices_settled))begin",
            owner,
        )
        abort_drain = owner[
            owner.index("STATE_ABORT_DRAIN:begin") : owner.index(
                "STATE_RELEASE_STAGE:begin"
            )
        ]
        self.assertIn(
            "if(device_protocol_fault||any_device_settling)begin", abort_drain
        )
        self.assertIn(
            "if(fatal_reset_hold||device_protocol_fault||"
            "any_device_settling)state<=STATE_FATAL_RELEASE;",
            abort_drain,
        )
        release_stage = owner[
            owner.index("STATE_RELEASE_STAGE:begin") : owner.index(
                "STATE_RELEASE_DEVICES:begin"
            )
        ]
        self.assertIn("state<=STATE_FATAL_RELEASE;", release_stage)
        self.assertNotIn("state<=STATE_ABORT_DRAIN;", release_stage)

        combined_tb = source(
            "sim/rtl/apf_savestate_v2_load_settle_guard_tb.sv"
        )
        self.assertIn(
            "grant-drop/reset race released or reacquired ownership", combined_tb
        )
        self.assertIn(
            "fatal_reset_hold && restore_failed && !datapath_abort", combined_tb
        )
        self.assertIn("prestart_load=%0d prestart_reset=%0d", combined_tb)
        self.assertIn(
            "WAIT_STAGE reset fault escaped through recoverable release",
            combined_tb,
        )

        # RTC freeze dominates reset, whereas EEPROM device reset interrupts
        # freeze.  The real mixed-language device benches prove both sides;
        # the combined guard/owner bench proves the terminal and abort races.
        rtc = compact(source("src/fpga/core/rtl/rtc.vhd"))
        self.assertLess(
            rtc.index("if(state_freeze='1')then"),
            rtc.index("if(reset='1')then"),
        )
        eeprom = compact(source("src/fpga/core/rtl/eeprom.vhd"))
        self.assertLess(
            eeprom.index("if(reset='1')then"),
            eeprom.index("elsif(state_load_active='1')then"),
        )
        rtc_tb = source("sim/rtl/rtc_state_tb.vhd")
        self.assertIn("RTC state changed under frozen bus/reset interruption", rtc_tb)
        eeprom_tb = source("sim/rtl/eeprom_state_tb.vhd")
        self.assertIn("device reset did not interrupt freeze deterministically", eeprom_tb)

        qsf = source("src/fpga/ap_core.qsf")
        self.assertNotIn("core/apf_savestate_v2_load_settle_guard.sv", qsf)
        top = compact(source("src/fpga/core/core_top.v"))
        self.assertIn("localparamSAVESTATE_SUPPORTED=1'b0;", top)
        self.assertIn("wirememories_pause_request=1'b0;", top)
        core = json.loads(source("dist/Cores/RegionallyFamous.SwanSong/core.json"))
        self.assertIs(core["core"]["framework"]["sleep_supported"], False)

        regression = source("scripts/regression.sh")
        for runner in (
            "run_apf_savestate_v2_load_settle_guard_tb.sh",
            "run_apf_savestate_v2_owner_tb.sh",
            "run_rtc_state_tb.sh",
            "run_eeprom_state_tb.sh",
        ):
            self.assertIn(runner, regression)

    def test_v2_restore_preflight_is_exact_bounded_and_isolated(self) -> None:
        preflight_path = "src/fpga/core/apf_savestate_v2_restore_preflight.sv"
        preflight = compact(source(preflight_path))
        self.assertIn("MAX_BACKEND_WAIT_CYCLES=1", preflight)
        self.assertIn("MAX_BACKEND_WAIT_CYCLES<=0", preflight)
        self.assertIn("V2_TOTAL_BYTES-32'd4", preflight)
        self.assertIn("v2_static_header_valid", preflight)
        self.assertIn("v2_feature_identity_valid", preflight)
        self.assertIn("v2_active_sizes_valid", preflight)
        self.assertIn("v2_payload_byte_requires_zero", preflight)
        self.assertIn("v2_rtc_state_valid", preflight)
        self.assertIn("v2_eeprom_state_valid", preflight)
        self.assertIn("stage_content_changed", preflight)
        self.assertIn("current_flash_supported", preflight)
        self.assertIn("backend_failure_seen", preflight)
        self.assertIn("compatibility_still_valid", preflight)
        self.assertIn("stage_transfer_failed||backend_failure_seen", preflight)
        self.assertIn("semanticvalidatorsarerequiredasanadditional", preflight)
        self.assertIn("mustneverdriveAPFresultbitsdirectly", preflight)

        timeout_update = (
            "previous_state<=state;"
            "if(backend_wait_state&&state==previous_state)"
            "backend_wait_cycles<=backend_wait_cycles+1;"
            "elsebackend_wait_cycles<=0;"
        )

        def timeout_update_is_live(text: str) -> bool:
            sequential = text[text.index("always@(posedgeclkornegedgereset_n)begin") :]
            reset_end = sequential.index("endelsebegin")
            return (
                timeout_update not in sequential[:reset_end]
                and timeout_update in sequential[reset_end:]
            )

        self.assertTrue(timeout_update_is_live(preflight))
        removed = preflight.replace(timeout_update, "", 1)
        self.assertFalse(timeout_update_is_live(removed))
        moved_to_reset = removed.replace(
            "failure_reason<=FAILURE_NONE;",
            timeout_update + "failure_reason<=FAILURE_NONE;",
            1,
        )
        self.assertFalse(timeout_update_is_live(moved_to_reset))

        # This is a structural/integrity/profile/device slice, not a complete
        # CPU/PPU/APU semantic validator or authorization to advertise A0/A4.
        self.assertNotIn("apf_savestate_v2_restore_preflight", source("src/fpga/core/core_top.v"))
        self.assertNotIn("core/apf_savestate_v2_restore_preflight.sv", source("src/fpga/ap_core.qsf"))
        self.assertIn("localparamSAVESTATE_SUPPORTED=1'b0;", compact(source("src/fpga/core/core_top.v")))
        core = json.loads(source("dist/Cores/RegionallyFamous.SwanSong/core.json"))
        self.assertIs(core["core"]["framework"]["sleep_supported"], False)

        regression = source("scripts/regression.sh")
        self.assertIn("run_apf_savestate_v2_restore_preflight_tb.sh", regression)
        bench = source("sim/rtl/apf_savestate_v2_restore_preflight_tb.sv")
        self.assertIn("semantic_gate_pending=1", bench)
        self.assertIn("capture-overwritten bytes reused old validation", bench)
        self.assertIn("CRC-clear backend error pulse", bench)
        self.assertIn("terminal quiescence timeout", bench)

    def test_v2_eeprom_load_settle_bound_mutations_are_rejected(self) -> None:
        guard_path = "src/fpga/core/apf_savestate_v2_load_settle_guard.sv"
        device_path = "sim/rtl/eeprom_state_tb.vhd"
        originals = {
            guard_path: source(guard_path),
            device_path: source(device_path),
        }
        mutations = (
            (guard_path, "MAX_ACK_LOW_CYCLES = 2", "MAX_ACK_LOW_CYCLES = 1"),
            (guard_path, "MAX_ACK_LOW_CYCLES = 2", "MAX_ACK_LOW_CYCLES = 3"),
            (
                device_path,
                "MAX_V2_LOAD_ACK_LOW_CYCLES : natural := 2",
                "MAX_V2_LOAD_ACK_LOW_CYCLES : natural := 1",
            ),
            (
                device_path,
                "ack_low_samples <= MAX_V2_LOAD_ACK_LOW_CYCLES",
                "ack_low_samples <= 99",
            ),
            (
                device_path,
                "2 <= MAX_V2_LOAD_ACK_LOW_CYCLES",
                "1 <= MAX_V2_LOAD_ACK_LOW_CYCLES",
            ),
        )
        for path, original, replacement in mutations:
            with self.subTest(path=path, replacement=replacement):
                self.assertEqual(originals[path].count(original), 1)
                changed = originals[path].replace(original, replacement, 1)
                self.assertTrue(load_settle_bound_violations({path: changed}))

    def test_native_device_state_plumbing_mutations_are_rejected(self) -> None:
        paths = (
            "src/fpga/core/core_top.v",
            "src/fpga/core/wonderswan.sv",
            "src/fpga/core/rtl/swanTop.vhd",
            "src/fpga/core/rtl/memorymux.vhd",
            "sim/verilator/sim_main.cpp",
        )
        originals = {path: source(path) for path in paths}
        mutations = (
            (
                "src/fpga/core/core_top.v",
                "wire rtc_state_freeze = 1'b0;",
                "wire rtc_state_freeze = ss_save;",
            ),
            (
                "src/fpga/core/core_top.v",
                "wire [255:0] rtc_state_data_in = 256'd0;",
                "wire [255:0] rtc_state_data_in = rtc_state_data_out;",
            ),
            (
                "src/fpga/core/core_top.v",
                "wire [127:0] cartridge_eeprom_state_in = 128'd0;",
                "wire [127:0] cartridge_eeprom_state_in = internal_eeprom_state_out;",
            ),
            (
                "src/fpga/core/wonderswan.sv",
                "output wire         rtc_state_frozen,",
                "input  wire         rtc_state_frozen,",
            ),
            (
                "src/fpga/core/wonderswan.sv",
                ".internal_eeprom_state_in(internal_eeprom_state_in)",
                ".internal_eeprom_state_in(cartridge_eeprom_state_in)",
            ),
            (
                "src/fpga/core/rtl/swanTop.vhd",
                "state_freeze         => rtc_state_freeze,",
                "state_freeze         => '0',",
            ),
            (
                "src/fpga/core/rtl/swanTop.vhd",
                "cartridge_eeprom_state_in     => cartridge_eeprom_state_in,",
                "cartridge_eeprom_state_in     => internal_eeprom_state_in,",
            ),
            (
                "src/fpga/core/rtl/memorymux.vhd",
                "state_freeze   => internal_eeprom_state_freeze,",
                "state_freeze   => '0',",
            ),
            (
                "src/fpga/core/rtl/memorymux.vhd",
                "state_out      => cartridge_eeprom_state_out",
                "state_out      => open",
            ),
            (
                "sim/verilator/sim_main.cpp",
                "top->rtc_state_load = 0;",
                "top->rtc_state_load = 1;",
            ),
            (
                "sim/verilator/sim_main.cpp",
                "word < 8; ++word) top->rtc_state_data_in[word] = 0;",
                "word < 7; ++word) top->rtc_state_data_in[word] = 0;",
            ),
        )
        for path, original, replacement in mutations:
            with self.subTest(path=path, replacement=replacement):
                self.assertEqual(originals[path].count(original), 1)
                changed = originals[path].replace(original, replacement, 1)
                self.assertTrue(device_state_plumbing_violations({path: changed}))

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
        self.assertIn("assignquiescent=backend_idle&&!cache_valid", reader)
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
