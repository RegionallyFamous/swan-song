#!/usr/bin/env python3
"""Adversarial and source-contract tests for the isolated A0 service model."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

from apf_a0_prefetch_service_model import (
    DEFAULT_PAYLOAD_BYTES,
    ModelConfig,
    analyze,
    minimum_safe_depth,
    simulate_depth,
)


ROOT = Path(__file__).resolve().parents[1]


class A0PrefetchServiceModelTest(unittest.TestCase):
    def test_current_sources_prove_bridge_period_but_not_sdram_fairness(self) -> None:
        bridge = (ROOT / "src/fpga/apf/io_bridge_peripheral.v").read_text(
            encoding="utf-8"
        )
        self.assertIn("reads are buffered by 1 word", bridge)
        self.assertIn("worst-case read/write timing is every 88 cycles @ 74.25mhz", bridge)
        read_state = bridge[bridge.index("ST_READ_0: begin") : bridge.index("ST_READ_2: begin")]
        self.assertLess(
            read_state.index("spis_word_tx <= pmp_rd_data_e"),
            read_state.index("pmp_rd <= 1"),
        )

        sdram = (ROOT / "src/fpga/core/rtl/sdram.sv").read_text(encoding="utf-8")
        priority = sdram[sdram.index("STATE_IDLE: begin") : sdram.index("STATE_WAIT:")]
        self.assertLess(priority.index("if (refresh_count > cycles_per_refresh)"),
                        priority.index("else if(ch1_rq)"))
        self.assertLess(priority.index("else if(ch1_rq)"), priority.index("else if(ch2_rq)"))
        self.assertLess(priority.index("else if(ch2_rq)"), priority.index("else if(ch3_rq)"))
        self.assertNotIn("ch4", sdram)

        pll = (ROOT / "src/fpga/core/mf_pllbase.v").read_text(encoding="utf-8")
        self.assertIn('gui_reference_clock_frequency" value="74.25"', pll)
        self.assertIn('gui_output_clock_frequency0" value="110.592"', pll)

    def test_current_arbiter_fails_closed_without_a_service_bound(self) -> None:
        result = analyze(ModelConfig())
        self.assertFalse(result["safe"])
        self.assertEqual(result["status"], "unproven")
        self.assertIsNone(result["minimum_fifo_depth_words"])
        self.assertEqual(result["full_blob_prefill_words"], 147_648)
        self.assertEqual(result["full_blob_prefill_bytes"], DEFAULT_PAYLOAD_BYTES)

    def test_conditional_fast_bound_needs_one_prefetched_word(self) -> None:
        config = ModelConfig(halfword_service_bound_mem_cycles=14)
        self.assertEqual(config.word_service_bound_mem_cycles, 31)
        self.assertEqual(config.bridge_period_mem_cycles.numerator, 16_384)
        self.assertEqual(config.bridge_period_mem_cycles.denominator, 125)
        depth, result = minimum_safe_depth(config)
        self.assertEqual(depth, 1)
        self.assertTrue(result.safe)

    def test_setup_margin_forces_two_words_at_near_equal_rates(self) -> None:
        config = ModelConfig(
            payload_bytes=0x4000,
            halfword_service_bound_mem_cycles=64,
        )
        self.assertEqual(config.word_service_bound_mem_cycles, 131)
        one = simulate_depth(config, 1)
        two = simulate_depth(config, 2)
        self.assertFalse(one.safe)
        self.assertEqual(one.failed_word_index, 1)
        self.assertTrue(two.safe)
        depth, _ = minimum_safe_depth(config)
        self.assertEqual(depth, 2)

    def test_slow_producer_boundary_is_adversarially_exact(self) -> None:
        config = ModelConfig(
            payload_bytes=0x4000,
            halfword_service_bound_mem_cycles=70,
        )
        depth, result = minimum_safe_depth(config)
        self.assertEqual(config.word_service_bound_mem_cycles, 143)
        self.assertEqual(depth, 343)
        self.assertTrue(result.safe)
        below = simulate_depth(config, depth - 1)
        self.assertFalse(below.safe)
        self.assertIsNotNone(below.failed_word_index)

    def test_full_prefill_covers_finite_blob_for_any_finite_bound(self) -> None:
        config = ModelConfig(
            payload_bytes=0x100,
            halfword_service_bound_mem_cycles=1_000_000,
        )
        result = simulate_depth(config, config.payload_words)
        self.assertTrue(result.safe)
        depth, _ = minimum_safe_depth(config)
        self.assertEqual(depth, config.payload_words)

    def test_invalid_configuration_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            analyze(ModelConfig(payload_bytes=3))
        with self.assertRaises(ValueError):
            analyze(ModelConfig(halfword_service_bound_mem_cycles=0))
        with self.assertRaises(ValueError):
            simulate_depth(ModelConfig(), 1)

    def test_cli_exit_status_tracks_proof_state(self) -> None:
        script = ROOT / "scripts/apf_a0_prefetch_service_model.py"
        unbounded = subprocess.run(
            [str(script), "--payload-bytes", "0x100"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(unbounded.returncode, 2)
        self.assertFalse(json.loads(unbounded.stdout)["safe"])

        bounded = subprocess.run(
            [
                str(script),
                "--payload-bytes",
                "0x100",
                "--halfword-service-bound-mem-cycles",
                "14",
                "--verify-depth-words",
                "1",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(bounded.returncode, 0, bounded.stderr)
        report = json.loads(bounded.stdout)
        self.assertTrue(report["safe"])
        self.assertTrue(report["verified_depth_safe"])


if __name__ == "__main__":
    unittest.main()
