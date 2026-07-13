#!/usr/bin/env python3
"""Mutation-lock the Pocket console EEPROM persistence contract."""

from __future__ import annotations

import copy
import json
import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "dist/Cores/RegionallyFamous.SwanSong/data.json"

SOURCE_PATHS = {
    "core_top": ROOT / "src/fpga/core/core_top.v",
    "wonderswan": ROOT / "src/fpga/core/wonderswan.sv",
    "swan_top": ROOT / "src/fpga/core/rtl/swanTop.vhd",
    "memorymux": ROOT / "src/fpga/core/rtl/memorymux.vhd",
    "eeprom": ROOT / "src/fpga/core/rtl/eeprom.vhd",
    "initializer": ROOT / "src/fpga/core/pocket_console_eeprom_init.sv",
    "chip32": ROOT / "src/support/chip32.asm",
    "qsf": ROOT / "src/fpga/ap_core.qsf",
    "regression": ROOT / "scripts/regression.sh",
    "roundtrip": ROOT / "sim/rtl/console_eeprom_roundtrip_tb.vhd",
    "external_backing": ROOT / "sim/rtl/external_eeprom_backing_tb.vhd",
    "roundtrip_runner": ROOT / "sim/rtl/run_console_eeprom_roundtrip_tb.sh",
    "readme": ROOT / "README.md",
    "status": ROOT / "PHASE_STATUS.md",
}


def number(value: int | str) -> int:
    return int(value, 0) if isinstance(value, str) else value


def compact(source: str) -> str:
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    source = re.sub(r"//[^\n]*", "", source)
    source = re.sub(r"--[^\n]*", "", source)
    return re.sub(r"\s+", "", source).lower()


def source_bundle() -> dict[str, str]:
    return {name: path.read_text(encoding="utf-8") for name, path in SOURCE_PATHS.items()}


def contract_errors(data_document: dict, sources: dict[str, str]) -> list[str]:
    errors: list[str] = []
    slots = {number(slot["id"]): slot for slot in data_document["data"]["data_slots"]}

    expected = {
        12: ("Mono EEPROM", "mono.eeprom", 128, 0x50000000),
        13: ("Color EEPROM", "color.eeprom", 2048, 0x60000000),
    }
    for slot_id, (name, filename, size, address) in expected.items():
        slot = slots.get(slot_id, {})
        actual = (
            slot.get("name"),
            slot.get("required"),
            slot.get("filename"),
            number(slot.get("parameters", -1)),
            slot.get("nonvolatile"),
            slot.get("extensions"),
            number(slot.get("size_exact", -1)),
            number(slot.get("size_maximum", -1)),
            number(slot.get("address", -1)),
        )
        wanted = (name, False, filename, 0x02, True, ["eeprom"], size, size, address)
        if actual != wanted:
            errors.append(f"slot {slot_id} fixed console EEPROM metadata mismatch")

    save = slots.get(11, {})
    if number(save.get("parameters", -1)) != 0x84 or save.get("filename") is not None:
        errors.append("cartridge slot 11 must remain independent and filename-cloned")
    if number(save.get("address", -1)) != 0x20000000:
        errors.append("cartridge slot 11 address changed")

    core_top = compact(sources["core_top"])
    wonderswan = compact(sources["wonderswan"])
    swan_top = compact(sources["swan_top"])
    memorymux = compact(sources["memorymux"])
    eeprom = compact(sources["eeprom"])
    initializer = compact(sources["initializer"])

    for expression, message in (
        ("16'd12:begin", "slot 12 is missing from the RTL data-slot guard"),
        ("dataslot_policy_exact_size=48'd128;", "slot 12 exact RTL size is missing"),
        ("16'd13:begin", "slot 13 is missing from the RTL data-slot guard"),
        ("dataslot_policy_exact_size=48'd2048;", "slot 13 exact RTL size is missing"),
        (".address_mask_upper_4(4'h5)", "mono loader window is missing"),
        (".address_mask_upper_4(4'h6)", "Color loader window is missing"),
        ("datatable_addr<=10'd9;datatable_data<=32'd128;", "mono unload size is not published"),
        ("datatable_addr<=10'd11;datatable_data<=32'd2048;", "Color unload size is not published"),
    ):
        if expression not in core_top:
            errors.append(message)
    if core_top.count("dataslot_policy_allow_read=1'b1;") < 3:
        errors.append("console EEPROM guard entries must permit shutdown reads")
    if core_top.count("dataslot_policy_allow_write=1'b1;") < 4:
        errors.append("console EEPROM guard entries must permit exact startup writes")

    for expression, message in (
        ("pocket_console_eeprom_initconsole_eeprom_initializer", "title-only initializer is not instantiated"),
        (".preserve_internal_eeprom(1'b1)", "Pocket wrapper does not preserve EEPROM on reset"),
        ("console_eeprom_wr&&!console_eeprom_clearing", "APF load can acknowledge during factory seeding"),
        ("cartridge_save_initialization_resolved&&console_eeprom_initialization_resolved", "startup does not wait for both initializers"),
    ):
        if expression not in wonderswan:
            errors.append(message)

    if "preserve_internal_eeprom:instd_logic:='0'" not in swan_top:
        errors.append("SwanTop persistence boundary is missing")
    if "preserve_on_reset=>preserve_internal_eeprom" not in memorymux:
        errors.append("memorymux does not preserve the internal controller")
    if "eeprom_bank=>internal_eeprom_bank" not in memorymux:
        errors.append("internal and cartridge EEPROM host ports are not separated")
    if "eeprom_bank=>'0'" not in memorymux:
        errors.append("cartridge EEPROM must remain fixed to its own bank")
    if (
        "external_backing:ifisexternal='1'generate" not in eeprom
        or "addr_width=>10" not in eeprom
        or "address_b=>eeprom_addr" not in eeprom
    ):
        errors.append("external cartridge EEPROM is not fixed at 1024 words")
    if (
        "internal_backing:ifisexternal='0'generate" not in eeprom
        or "addr_width=>11" not in eeprom
        or "eepromaddrphysical<=eeprom_bank&eeprom_addr" not in eeprom
        or "address_b=>eepromaddrphysical" not in eeprom
    ):
        errors.append("internal EEPROM backing is not dual-bank")
    if "isexternal='0'andpreserve_on_reset='0'" not in eeprom:
        errors.append("ordinary reset is not gated away from factory CLEAR")

    if "inputwirecart_download" not in initializer or "reset" in re.sub(
        r"preserve[^,;)]*reset", "", initializer
    ):
        # The module intentionally has no reset input. Its comments may mention
        # reset, so evaluate only the compact port prefix below as the hard gate.
        port_prefix = initializer.split(");", 1)[0]
        if "reset" in port_prefix:
            errors.append("console initializer must be armed only by title load")
    if "last_factory_word=11'd1087" not in initializer:
        errors.append("initializer does not cover Color 1024 + mono 64 words exactly")

    chip32 = sources["chip32"]
    ordered = [
        "load_rom_asset(cart_download_addr, rom_dataslot)",
        "load_asset(save_download_addr, mono_eeprom_dataslot, 0)",
        "load_asset(save_download_addr, color_eeprom_dataslot, 0)",
        "load_asset(save_download_addr, save_dataslot, 0)",
        "host r0,r0",
    ]
    positions = [chip32.find(item) for item in ordered]
    if -1 in positions or positions != sorted(positions):
        errors.append("Chip32 must load both console slots before run and separately from slot 11")

    if sources["qsf"].count(
        "set_global_assignment -name SYSTEMVERILOG_FILE core/pocket_console_eeprom_init.sv"
    ) != 1:
        errors.append("Quartus does not compile the console initializer")
    for hook in (
        "run_pocket_console_eeprom_init_tb.sh",
        "run_console_eeprom_roundtrip_tb.sh",
        "pocket_console_eeprom_contract_test.py",
    ):
        if hook not in sources["regression"]:
            errors.append(f"regression is missing {hook}")
    roundtrip = compact(sources["roundtrip"])
    for expression, message in (
        ("dut:entitywork.eeprom", "round-trip bench does not use the real EEPROM backing"),
        ("procedureseed_factory", "round-trip bench lacks the factory phase"),
        ("procedureoverlay_slot", "round-trip bench lacks the existing-slot overlay"),
        ("procedureunload_and_check", "round-trip bench lacks the unload comparison"),
        ("assertbytes_read=128", "round-trip bench does not enforce exact mono unload"),
        ("assertbytes_read=2048", "round-trip bench does not enforce exact Color unload"),
        ("preserve_on_reset=>'1'", "round-trip bench does not exercise reset retention"),
    ):
        if expression not in roundtrip:
            errors.append(message)
    external_backing = compact(sources["external_backing"])
    for expression, message in (
        ("isexternal=>'1'", "external backing bench does not elaborate the cartridge path"),
        ("host_write('1',1023", "external backing bench does not cover the final word"),
        ("host_read('0',1023", "external backing bench does not prove the bank input is ignored"),
    ):
        if expression not in external_backing:
            errors.append(message)
    if (
        "ghdl" not in sources["roundtrip_runner"]
        or "eeprom.vhd" not in sources["roundtrip_runner"]
        or "external_eeprom_backing_tb.vhd" not in sources["roundtrip_runner"]
    ):
        errors.append("round-trip runner does not compile the production EEPROM RTL")

    docs = (sources["readme"] + sources["status"]).lower()
    for phrase in ("mono.eeprom", "color.eeprom", "ordinary reset", "user-supplied bios"):
        if phrase not in docs:
            errors.append(f"documentation is missing {phrase!r}")

    if (ROOT / "dist/Assets/wonderswan/common/bw.rom").exists() or (
        ROOT / "dist/Assets/wonderswan/common/color.rom"
    ).exists():
        errors.append("BIOS files must never be bundled")

    return errors


class PocketConsoleEepromContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.data = json.loads(DATA.read_text(encoding="utf-8"))
        self.sources = source_bundle()

    def test_live_contract(self) -> None:
        self.assertEqual(contract_errors(self.data, self.sources), [])

    def test_metadata_and_source_mutations_fail(self) -> None:
        mutations = []
        for slot_id, field, value in (
            (12, "parameters", "0x06"),
            (12, "size_exact", 127),
            (13, "address", "0x20000000"),
            (13, "filename", "game.eeprom"),
        ):
            document = copy.deepcopy(self.data)
            slot = next(item for item in document["data"]["data_slots"] if number(item["id"]) == slot_id)
            slot[field] = value
            mutations.append((document, self.sources))

        for key, old, new in (
            ("wonderswan", ".preserve_internal_eeprom(1'b1)", ".preserve_internal_eeprom(1'b0)"),
            ("core_top", "dataslot_policy_exact_size = 48'd128;", "dataslot_policy_exact_size = 48'd127;"),
            ("eeprom", "isExternal = '0' and preserve_on_reset = '0'", "isExternal = '0'"),
            ("eeprom", "addr_width => 10", "addr_width => 11"),
            ("external_backing", "host_write('1', 1023", "host_write('1', 1022"),
            ("chip32", "load_asset(save_download_addr, color_eeprom_dataslot, 0)", "// removed"),
            ("roundtrip", "assert bytes_read = 2048", "assert bytes_read = 2047"),
        ):
            sources = dict(self.sources)
            self.assertIn(old, sources[key])
            sources[key] = sources[key].replace(old, new, 1)
            mutations.append((self.data, sources))

        for document, sources in mutations:
            self.assertTrue(contract_errors(document, sources))


if __name__ == "__main__":
    unittest.main()
