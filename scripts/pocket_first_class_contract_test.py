#!/usr/bin/env python3
"""Contract checks for the Analogue Pocket-facing core definition and wrapper."""

from __future__ import annotations

import json
import os
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parent.parent
CORE_DIR = ROOT / "dist/Cores/agg23.WonderSwan"


def load(name: str) -> dict:
    return json.loads((CORE_DIR / name).read_text(encoding="utf-8"))


def number(value: int | str) -> int:
    return int(value, 0) if isinstance(value, str) else value


class PocketFirstClassContractTest(unittest.TestCase):
    def test_core_platform_and_framework_identity(self) -> None:
        core = load("core.json")["core"]
        self.assertEqual(core["magic"], "APF_VER_1")
        self.assertEqual(core["metadata"]["platform_ids"], ["wonderswan"])

        # Display modes and their B8 command were introduced in framework 2.0.
        self.assertEqual(core["framework"]["version_required"], "2.0")
        # Memories/sleep remains disabled until the full controller and a
        # physical Pocket endurance matrix have passed.
        self.assertFalse(core["framework"]["sleep_supported"])
        self.assertTrue(core["framework"]["dock"]["supported"])
        self.assertEqual(core["framework"]["hardware"]["cartridge_adapter"], -1)

        platform = json.loads(
            (ROOT / "dist/Platforms/wonderswan.json").read_text(encoding="utf-8")
        )["platform"]
        self.assertEqual(
            platform,
            {
                "category": "Handheld",
                "name": "WonderSwan",
                "year": 1999,
                "manufacturer": "Bandai",
            },
        )

    def test_video_modes_are_generic_and_backed_by_grayscale_rtl(self) -> None:
        video = load("video.json")["video"]
        self.assertEqual(video["magic"], "APF_VER_1")
        self.assertLessEqual(len(video["scaler_modes"]), 8)
        self.assertEqual(len(video["scaler_modes"]), 2)
        self.assertEqual(
            [number(mode["id"]) for mode in video["display_modes"]],
            [0x20, 0x30, 0x40],
        )
        self.assertLessEqual(len(video["display_modes"]), 16)
        self.assertEqual(video["defaults"]["sharpness"], 3)

        bridge = (ROOT / "src/fpga/core/core_bridge_cmd.v").read_text(
            encoding="utf-8"
        )
        top = (ROOT / "src/fpga/core/core_top.v").read_text(encoding="utf-8")
        project = (ROOT / "src/fpga/ap_core.qsf").read_text(encoding="utf-8")
        self.assertIn("16'h00B1", bridge)
        self.assertIn("16'h00B2", bridge)
        self.assertIn("16'h00B8", bridge)
        self.assertIn("32'h0000_444D", bridge)
        self.assertIn("displaymode_grayscale_ack", bridge)
        self.assertIn("displaymode_grayscale_to_video", top)
        self.assertIn("displaymode_grayscale_to_bridge", top)
        self.assertIn("displaymode_grayscale_applied <= displaymode_grayscale_video", top)
        self.assertIn("apf_grayscale_video displaymode_video", top)
        self.assertIn("core/apf_grayscale_video.sv", project)

    def test_dynamic_nonvolatile_save_contract(self) -> None:
        data = load("data.json")["data"]
        self.assertEqual(data["magic"], "APF_VER_1")
        slots = data["data_slots"]
        self.assertLessEqual(len(slots), 32)
        self.assertEqual(len({number(slot["id"]) for slot in slots}), len(slots))
        for slot in slots:
            self.assertLessEqual(len(slot["name"]), 15)
            self.assertLessEqual(len(slot.get("extensions", [])), 4)
            self.assertTrue(all(len(ext) <= 7 for ext in slot.get("extensions", [])))

        save = next(slot for slot in slots if number(slot["id"]) == 11)
        parameters = number(save["parameters"])
        self.assertTrue(save["nonvolatile"])
        self.assertEqual(parameters & (1 << 2), 1 << 2)  # clone slot-0 filename
        self.assertEqual(parameters & (1 << 3), 0)  # writable
        self.assertEqual(parameters & (1 << 7), 1 << 7)  # safe full restart
        self.assertEqual(number(save["address"]), 0x20000000)
        self.assertNotIn("size_exact", save)
        self.assertEqual(number(save["size_maximum"]), 512 * 1024 + 12)

    def test_input_and_interact_limits(self) -> None:
        input_definition = load("input.json")["input"]
        controllers = input_definition["controllers"]
        self.assertLessEqual(len(controllers), 4)
        allowed_keys = {
            "pad_btn_a",
            "pad_btn_b",
            "pad_btn_x",
            "pad_btn_y",
            "pad_trig_l",
            "pad_trig_r",
            "pad_btn_start",
            "pad_btn_select",
        }
        for controller in controllers:
            self.assertEqual(controller["type"], "default")
            mappings = controller["mappings"]
            self.assertLessEqual(len(mappings), 8)
            self.assertEqual(len({number(item["id"]) for item in mappings}), len(mappings))
            self.assertTrue(all(len(item["name"]) <= 19 for item in mappings))
            self.assertEqual({item["key"] for item in mappings}, allowed_keys)

        interact = load("interact.json")["interact"]
        variables = interact["variables"]
        self.assertLessEqual(len(variables), 16)
        self.assertEqual(len({number(item["id"]) for item in variables}), len(variables))

    def test_focused_wrapper_tests_are_executable(self) -> None:
        for relative in (
            "scripts/pocket_control_cdc_contract_test.py",
            "sim/rtl/run_apf_host_notify_tb.sh",
            "sim/rtl/run_apf_grayscale_video_tb.sh",
        ):
            path = ROOT / relative
            self.assertTrue(path.is_file())
            self.assertTrue(os.access(path, os.X_OK))


if __name__ == "__main__":
    unittest.main()
