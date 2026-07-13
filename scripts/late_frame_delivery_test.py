#!/usr/bin/env python3

import unittest
from fractions import Fraction
from pathlib import Path

from late_frame_delivery import (
    PRODUCER_SYSTEM_CYCLES,
    derive,
    milliseconds,
    model_current_dynamic_orientation,
    model_safe_deferred_orientation,
    validate_apf_geometry,
)

ROOT = Path(__file__).resolve().parents[1]


class LateFrameDeliveryTest(unittest.TestCase):
    def test_isolated_candidate_remains_out_of_production_rtl(self) -> None:
        qsf = (ROOT / "src/fpga/ap_core.qsf").read_text(encoding="utf-8")
        top = (ROOT / "src/fpga/core/wonderswan.sv").read_text(encoding="utf-8")
        self.assertNotIn("apf_late_frame_candidate.sv", qsf)
        self.assertNotIn("apf_late_frame_candidate", top)

    def test_exact_60_geometry_satisfies_guarded_apf_spacing(self) -> None:
        validate_apf_geometry()
        metrics = derive()
        self.assertEqual(metrics.late.consumer_system_cycles, 614_400)
        self.assertEqual(metrics.late_refresh_hz, Fraction(60, 1))
        self.assertEqual(metrics.late_selection_after_vs_cycles, 393_216)
        self.assertAlmostEqual(
            milliseconds(metrics.late_selection_after_vs_cycles),
            10.666666666666666,
        )

    def test_all_completion_phase_residues_are_enumerated(self) -> None:
        metrics = derive()
        self.assertEqual(metrics.current.phase_quantum_cycles, 36)
        self.assertEqual(metrics.current.reset_residues_checked, 36)
        self.assertEqual(metrics.current.selections_per_residue, 13_568)
        self.assertEqual(
            metrics.current.reset_residues_checked
            * metrics.current.selections_per_residue,
            PRODUCER_SYSTEM_CYCLES,
        )
        self.assertEqual(metrics.late.phase_quantum_cycles, 3_072)
        self.assertEqual(metrics.late.reset_residues_checked, 3_072)
        self.assertEqual(metrics.late.selections_per_residue, 159)
        self.assertEqual(
            metrics.late.reset_residues_checked
            * metrics.late.selections_per_residue,
            PRODUCER_SYSTEM_CYCLES,
        )

    def test_late_selection_has_a_conservative_age_improvement(self) -> None:
        metrics = derive()
        self.assertEqual(metrics.current.selection_mean_min_cycles, 244_206)
        self.assertEqual(metrics.current.selection_mean_max_cycles, 244_241)
        self.assertEqual(metrics.current.mean_pixel_offset_cycles, 328_380)
        self.assertEqual(metrics.late.selection_mean_min_cycles, 242_688)
        self.assertEqual(metrics.late.selection_mean_max_cycles, 245_759)
        self.assertEqual(metrics.late.mean_pixel_offset_cycles, 110_547)
        self.assertEqual(metrics.guaranteed_mean_pixel_improvement_cycles, 216_280)
        self.assertEqual(metrics.guaranteed_first_pixel_improvement_cycles, 155_791)
        self.assertAlmostEqual(
            milliseconds(metrics.guaranteed_mean_pixel_improvement_cycles),
            5.866970486111111,
        )
        self.assertAlmostEqual(
            milliseconds(metrics.guaranteed_first_pixel_improvement_cycles),
            4.226101345486111,
        )

    def test_late_gate_can_observe_one_newer_native_generation(self) -> None:
        metrics = derive()
        self.assertEqual(metrics.newer_generation_residues, 393_216)
        self.assertEqual(metrics.producer_residues_checked, 488_448)
        self.assertEqual(metrics.newer_generation_fraction, Fraction(128, 159))
        self.assertAlmostEqual(
            float(metrics.newer_generation_fraction * 100),
            80.50314465408805,
        )

    def test_current_next_frame_order_has_a_potential_transition_mismatch(self) -> None:
        frames = model_current_dynamic_orientation()
        self.assertTrue(frames[0].matched)
        self.assertFalse(frames[1].matched)
        self.assertEqual(
            (
                frames[1].presented_slot,
                frames[1].expected_applied_slot,
                frames[1].command_for_next_frame,
            ),
            (1, 0, 1),
        )
        self.assertTrue(frames[2].matched)

        # Lock the source ordering that motivates the model without claiming
        # physical Pocket behavior beyond the official next-frame contract.
        wonderswan = (ROOT / "src/fpga/core/wonderswan.sv").read_text(
            encoding="utf-8"
        )
        selector = (ROOT / "src/fpga/core/apf_scaler_selector.sv").read_text(
            encoding="utf-8"
        )
        self.assertIn(".consumer_frame_boundary(scanout_frame_boundary)", wonderswan)
        self.assertIn("if (frame_start_video && !request_arrived_video)", selector)

    def test_safe_model_repeats_before_promoting_a_new_slot(self) -> None:
        frames = model_safe_deferred_orientation()
        self.assertTrue(all(frame.matched for frame in frames))
        self.assertTrue(frames[1].repeated)
        self.assertEqual(
            (
                frames[1].presented_slot,
                frames[1].expected_applied_slot,
                frames[1].command_for_next_frame,
            ),
            (0, 0, 1),
        )
        self.assertEqual(frames[2].presented_slot, 1)
        self.assertFalse(frames[2].repeated)


if __name__ == "__main__":
    unittest.main()
