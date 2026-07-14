#!/usr/bin/env python3
"""Fail-closed contract for the exact Pocket APF boundary waivers."""

from __future__ import annotations

from pathlib import Path
import re
import unittest

from pocket_sdram_constraint_test import source_sdc


ROOT = Path(__file__).resolve().parents[1]
SDC = ROOT / "src/fpga/core/core_constraints.sdc"

BRIDGE_INPUTS = (
    "bridge_1wire",
    "bridge_spimiso",
    "bridge_spimosi",
    "bridge_spiss",
)
BRIDGE_OUTPUTS = ("bridge_1wire", "bridge_spimiso", "bridge_spimosi")
SCALER_OUTPUTS = (
    "scal_auddac",
    "scal_audlrck",
    "scal_audmclk",
    "scal_clk",
    "scal_de",
    "scal_hs",
    "scal_skip",
    "scal_vid[*]",
    "scal_vs",
)


def normalized(source: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\\\r?\n", " ", source))


class PocketApfBoundaryConstraintContract(unittest.TestCase):
    def test_exact_named_open_gateware_boundary_precedent(self) -> None:
        source = SDC.read_text(encoding="utf-8")
        flat = normalized(source)
        self.assertIn(
            "get_ports -nowarn {" + " ".join(BRIDGE_INPUTS) + "}", flat
        )
        self.assertIn(
            "get_ports -nowarn {" + " ".join(BRIDGE_OUTPUTS) + "}", flat
        )
        self.assertIn(
            "get_ports -nowarn {" + " ".join(SCALER_OUTPUTS) + "}", flat
        )
        self.assertEqual(source.count("set_false_path -from $apf_boundary_input_ports"), 1)
        self.assertEqual(source.count("set_false_path -to $apf_bridge_output_ports"), 1)
        self.assertEqual(source.count("set_false_path -to $apf_scaler_output_ports"), 1)
        self.assertNotRegex(source, r"set_false_path[^\n]*(?:all_inputs|all_outputs)")
        self.assertIn("explicit APF boundary waiver, not measured I/O closure", flat)

    def test_each_collection_guard_rejects_a_missing_port(self) -> None:
        cases = (
            (
                {"apf_input_ports": 3},
                "expected exactly 4 input-side ports",
            ),
            (
                {"apf_bridge_output_ports": 2},
                "expected exactly 3 bridge output-side ports",
            ),
            (
                {"apf_scaler_output_ports": 19},
                "expected exactly 20 scaler output-side ports",
            ),
        )
        for parameters, message in cases:
            with self.subTest(parameters=parameters):
                result = source_sdc(**parameters)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stdout + result.stderr)

    def test_all_exact_collections_source_successfully(self) -> None:
        result = source_sdc()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
