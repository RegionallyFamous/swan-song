#!/usr/bin/env python3

import unittest

from frame_delivery_metrics import derive


class FrameDeliveryMetricsTest(unittest.TestCase):
    def test_corrected_raster_exact_metrics(self) -> None:
        metrics = derive(397)
        self.assertEqual(metrics.frame_system_cycles, 614_556)
        self.assertAlmostEqual(metrics.refresh_hz, 59.98476949212114)
        self.assertAlmostEqual(metrics.output_period_ms, 16.6708984375)
        self.assertEqual(metrics.output_frames_per_superperiod, 13_568)
        self.assertEqual(metrics.producer_frames_per_superperiod, 17_071)
        self.assertEqual(metrics.producer_drops_per_superperiod, 3_503)
        self.assertEqual(metrics.skip_gap_3_count, 444)
        self.assertEqual(metrics.skip_gap_4_count, 3_059)
        self.assertEqual(metrics.skip_gap_5_count, 0)
        self.assertEqual(metrics.completion_phase_quantum_cycles, 36)
        self.assertEqual(metrics.delivery_phase_residues_checked, 36)
        self.assertAlmostEqual(
            metrics.complete_frame_age_envelope_max_ms,
            13.24997287326389,
        )
        self.assertAlmostEqual(
            metrics.complete_frame_age_phase_mean_min_ms,
            6.62451171875,
        )
        self.assertAlmostEqual(
            metrics.complete_frame_age_phase_mean_max_ms,
            6.625461154513889,
        )

    def test_correction_improves_cadence_without_latency_claim(self) -> None:
        inherited = derive(401)
        corrected = derive(397)
        self.assertAlmostEqual(inherited.refresh_hz, 59.38641767673839)
        self.assertAlmostEqual(inherited.producer_drop_rate_hz, 16.085280436469162)
        self.assertAlmostEqual(corrected.producer_drop_rate_hz, 15.486928621086406)
        self.assertAlmostEqual(
            inherited.producer_drop_rate_hz - corrected.producer_drop_rate_hz,
            0.598351815382756,
        )
        self.assertLess(abs(corrected.refresh_error_from_60_percent), 0.026)
        self.assertGreater(abs(inherited.refresh_error_from_60_percent), 1.0)
        self.assertEqual(
            corrected.complete_frame_age_envelope_max_ms,
            inherited.complete_frame_age_envelope_max_ms,
        )
        self.assertEqual(
            corrected.complete_frame_age_phase_mean_min_ms,
            inherited.complete_frame_age_phase_mean_min_ms,
        )
        self.assertEqual(
            corrected.complete_frame_age_phase_mean_max_ms,
            inherited.complete_frame_age_phase_mean_max_ms,
        )

    def test_optional_smooth_mode_reduces_drops_and_spreads_skips(self) -> None:
        standard = derive(397)
        smooth = derive(391)
        self.assertEqual(smooth.frame_system_cycles, 605_268)
        self.assertAlmostEqual(smooth.refresh_hz, 60.90525188841968)
        self.assertAlmostEqual(smooth.output_period_ms, 16.4189453125)
        self.assertEqual(smooth.output_frames_per_superperiod, 13_568)
        self.assertEqual(smooth.producer_frames_per_superperiod, 16_813)
        self.assertEqual(smooth.producer_drops_per_superperiod, 3_245)
        self.assertEqual(smooth.skip_gap_3_count, 0)
        self.assertEqual(smooth.skip_gap_4_count, 2_657)
        self.assertEqual(smooth.skip_gap_5_count, 588)
        self.assertAlmostEqual(smooth.producer_drop_rate_hz, 14.566446224787873)
        self.assertAlmostEqual(
            standard.producer_drop_rate_hz - smooth.producer_drop_rate_hz,
            0.920482396298533,
        )
        self.assertLess(
            smooth.producer_drop_rate_hz,
            standard.producer_drop_rate_hz,
        )
        # Higher delivery cadence changes motion sampling, not the age of the
        # newest complete native frame or any unmodeled Pocket panel latency.
        self.assertEqual(
            smooth.complete_frame_age_envelope_max_ms,
            standard.complete_frame_age_envelope_max_ms,
        )

    def test_rejects_raster_narrower_than_active_video(self) -> None:
        with self.assertRaisesRegex(ValueError, "narrower"):
            derive(223)


if __name__ == "__main__":
    unittest.main()
