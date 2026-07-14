#!/usr/bin/env python3

import unittest
from pathlib import Path

from beam_race_safety import (
    current_arbiter_reuse_counterexample,
    programmable_final_line_counterexample,
    prove_nominal_geometry,
    quantify_opportunity,
)

ROOT = Path(__file__).resolve().parents[1]


class BeamRaceSafetyTest(unittest.TestCase):
    def test_rejected_candidate_remains_out_of_production_rtl(self) -> None:
        qsf = (ROOT / "src/fpga/ap_core.qsf").read_text(encoding="utf-8")
        top = (ROOT / "src/fpga/core/wonderswan.sv").read_text(encoding="utf-8")
        self.assertNotIn("apf_beam_race_candidate.sv", qsf)
        self.assertNotIn("apf_beam_race_candidate", top)

    def test_nominal_geometry_has_positive_margin_for_every_pixel_and_phase(self) -> None:
        proof = prove_nominal_geometry()
        self.assertEqual(proof.pixels_checked, 224 * 144)
        self.assertEqual(proof.eligible_phase_cycles_checked, 441_973)
        self.assertEqual(proof.minimum_slack_cycles, 57_386)
        self.assertAlmostEqual(proof.minimum_slack_ms, 1.5566948784722223)
        self.assertEqual((proof.minimum_row, proof.minimum_column), (143, 223))

    def test_live_final_line_can_abort_an_armed_candidate(self) -> None:
        counterexample = programmable_final_line_counterexample(143)
        self.assertEqual(counterexample.first_stale_row, 143)
        self.assertEqual(counterexample.first_stale_address, 32_032)
        self.assertGreater(counterexample.read_deadline_cycles, 0)
        with self.assertRaisesRegex(ValueError, "shorter"):
            programmable_final_line_counterexample(144)

    def test_default_opportunity_is_phase_independent_and_one_generation_newer(self) -> None:
        opportunity = quantify_opportunity(158)
        self.assertEqual(opportunity.output_frames_per_phase_period, 13_568)
        self.assertEqual(opportunity.eligible_output_frames, 12_277)
        self.assertAlmostEqual(opportunity.eligible_percent, 90.48496462264151)
        self.assertAlmostEqual(
            opportunity.content_age_reduction_per_eligible_ms,
            13.25,
        )
        self.assertAlmostEqual(
            opportunity.phase_average_content_age_reduction_ms,
            11.9892578125,
        )
        with self.assertRaisesRegex(ValueError, "at least 144"):
            quantify_opportunity(143)
        self.assertEqual(quantify_opportunity(144).final_line, 144)

    def test_current_arbiter_recycles_selected_writer_before_next_boundary(self) -> None:
        counterexample = current_arbiter_reuse_counterexample()
        self.assertEqual(counterexample.selected_bank, 2)
        self.assertEqual(counterexample.next_writer_bank, 3)
        self.assertEqual(counterexample.recycled_writer_bank, 2)
        self.assertEqual(counterexample.producer_completions_before_consumer, 2)


if __name__ == "__main__":
    unittest.main()
