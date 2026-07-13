#!/usr/bin/env python3
"""Derive exact WonderSwan-to-APF complete-frame delivery metrics.

The model is deliberately limited to clock-domain facts: native producer frame
completion, APF scanout boundaries, and newest-complete-frame selection.  It
does not estimate Pocket scaler, panel, controller, or game-response latency.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict, dataclass
from fractions import Fraction
from math import gcd

SYSTEM_CLOCK_HZ = 36_864_000
PIXEL_CLOCK_HZ = 6_144_000
FRAME_LINES = 258
PIXEL_DIVIDE = 6
WS_CLOCK_HZ = 3_072_000
WS_FRAME_CLOCKS = 256 * 159
PRODUCER_SYSTEM_CYCLES = WS_FRAME_CLOCKS * (SYSTEM_CLOCK_HZ // WS_CLOCK_HZ)


@dataclass(frozen=True)
class DeliveryMetrics:
    line_pixels: int
    frame_system_cycles: int
    refresh_hz: float
    refresh_error_from_60_percent: float
    output_period_ms: float
    producer_refresh_hz: float
    producer_drop_rate_hz: float
    producer_drops_per_superperiod: int
    output_frames_per_superperiod: int
    producer_frames_per_superperiod: int
    skip_gap_3_count: int
    skip_gap_4_count: int
    completion_phase_quantum_cycles: int
    delivery_phase_residues_checked: int
    complete_frame_age_envelope_min_ms: float
    complete_frame_age_envelope_max_ms: float
    complete_frame_age_phase_mean_min_ms: float
    complete_frame_age_phase_mean_max_ms: float


def derive(line_pixels: int) -> DeliveryMetrics:
    if line_pixels < 224:
        raise ValueError("line raster cannot be narrower than the active image")

    consumer_cycles = line_pixels * FRAME_LINES * PIXEL_DIVIDE
    divisor = gcd(PRODUCER_SYSTEM_CYCLES, consumer_cycles)
    output_frames = PRODUCER_SYSTEM_CYCLES // divisor
    producer_frames = consumer_cycles // divisor

    sequence_signatures = set()
    for initial_phase in range(divisor):
        producer_ids = [
            (initial_phase + boundary * consumer_cycles) // PRODUCER_SYSTEM_CYCLES
            for boundary in range(output_frames + 1)
        ]
        increments = [
            producer_ids[index] - producer_ids[index - 1]
            for index in range(1, len(producer_ids))
        ]
        if set(increments) - {1, 2}:
            raise ValueError("model assumption violated: output did not advance 1-2 frames")

        skip_indices = [
            index for index, increment in enumerate(increments) if increment == 2
        ]
        skip_gaps = []
        for index, skip in enumerate(skip_indices):
            next_skip = skip_indices[(index + 1) % len(skip_indices)]
            if index == len(skip_indices) - 1:
                next_skip += output_frames
            skip_gaps.append(next_skip - skip)
        gap_counts = Counter(skip_gaps)
        if set(gap_counts) - {3, 4}:
            raise ValueError("unexpected producer-skip spacing")
        sequence_signatures.add(
            (
                Counter(increments)[1],
                Counter(increments)[2],
                gap_counts[3],
                gap_counts[4],
            )
        )
    if len(sequence_signatures) != 1:
        raise AssertionError("delivery cadence depends on unproven reset/event phase")
    increment_1_count, increment_2_count, gap_3_count, gap_4_count = (
        sequence_signatures.pop()
    )
    if increment_1_count + increment_2_count != output_frames:
        raise AssertionError("delivery sequence did not cover its complete phase period")

    refresh = Fraction(SYSTEM_CLOCK_HZ, consumer_cycles)
    producer_refresh = Fraction(WS_CLOCK_HZ, WS_FRAME_CLOCKS)
    # The reset/save-state phase between producer and output is not fixed. For
    # a particular phase residue r in [0, divisor), reachable ages are
    # r, r+divisor, ... P-divisor+r. Report the envelope and the possible mean
    # range across every residue instead of assuming coincident boundaries.
    phase_mean_min_cycles = Fraction(PRODUCER_SYSTEM_CYCLES - divisor, 2)
    phase_mean_max_cycles = phase_mean_min_cycles + divisor - 1

    return DeliveryMetrics(
        line_pixels=line_pixels,
        frame_system_cycles=consumer_cycles,
        refresh_hz=float(refresh),
        refresh_error_from_60_percent=float((refresh - 60) / 60 * 100),
        output_period_ms=float(Fraction(1000, 1) / refresh),
        producer_refresh_hz=float(producer_refresh),
        producer_drop_rate_hz=float(producer_refresh - refresh),
        producer_drops_per_superperiod=producer_frames - output_frames,
        output_frames_per_superperiod=output_frames,
        producer_frames_per_superperiod=producer_frames,
        skip_gap_3_count=gap_3_count,
        skip_gap_4_count=gap_4_count,
        completion_phase_quantum_cycles=divisor,
        delivery_phase_residues_checked=divisor,
        complete_frame_age_envelope_min_ms=0.0,
        complete_frame_age_envelope_max_ms=float(
            Fraction((PRODUCER_SYSTEM_CYCLES - 1) * 1000, SYSTEM_CLOCK_HZ)
        ),
        complete_frame_age_phase_mean_min_ms=float(
            Fraction(phase_mean_min_cycles * 1000, SYSTEM_CLOCK_HZ)
        ),
        complete_frame_age_phase_mean_max_ms=float(
            Fraction(phase_mean_max_cycles * 1000, SYSTEM_CLOCK_HZ)
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    arguments = parser.parse_args()
    metrics = {"inherited_401": derive(401), "corrected_397": derive(397)}
    if arguments.json:
        print(json.dumps({name: asdict(value) for name, value in metrics.items()}, indent=2))
        return

    for name, value in metrics.items():
        print(
            f"{name}: {value.refresh_hz:.9f} Hz, "
            f"{value.output_period_ms:.6f} ms/frame, "
            f"{value.producer_drop_rate_hz:.9f} producer frames/s dropped, "
            f"complete-frame age envelope "
            f"{value.complete_frame_age_envelope_min_ms:.6f}.."
            f"{value.complete_frame_age_envelope_max_ms:.6f} ms "
            f"(phase-mean {value.complete_frame_age_phase_mean_min_ms:.6f}.."
            f"{value.complete_frame_age_phase_mean_max_ms:.6f} ms)"
        )


if __name__ == "__main__":
    main()
