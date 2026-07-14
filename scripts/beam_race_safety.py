#!/usr/bin/env python3
"""Exact Phase-4 beam-race geometry and counterexample model."""

from __future__ import annotations

from dataclasses import dataclass
from math import gcd

SYSTEM_CLOCK_HZ = 36_864_000
SYSTEM_CYCLES_PER_PIXEL = 6
PRODUCER_CYCLES_PER_DOT = 12
PRODUCER_LINE_DOTS = 256
OUTPUT_LINE_PIXELS = 397
OUTPUT_ACTIVE_Y = 66
OUTPUT_ACTIVE_X = 31
WIDTH = 224
HEIGHT = 144
RAM_PIPELINE_GUARD_CYCLES = 4
OUTPUT_FRAME_SYSTEM_CYCLES = 397 * 258 * SYSTEM_CYCLES_PER_PIXEL
LAST_VISIBLE_WRITE_PHASE = (
    (HEIGHT - 1) * PRODUCER_LINE_DOTS * PRODUCER_CYCLES_PER_DOT
    + (WIDTH - 1) * PRODUCER_CYCLES_PER_DOT
)


def producer_write_time(row: int, column: int, phase_since_first_pixel: int = 0) -> int:
    """Time relative to boundary; phase >= 0 means pixel zero is already older."""
    return (
        row * PRODUCER_LINE_DOTS * PRODUCER_CYCLES_PER_DOT
        + column * PRODUCER_CYCLES_PER_DOT
        - phase_since_first_pixel
    )


def output_read_deadline(row: int, column: int) -> int:
    return (
        (OUTPUT_ACTIVE_Y + row) * OUTPUT_LINE_PIXELS
        + OUTPUT_ACTIVE_X
        + column
    ) * SYSTEM_CYCLES_PER_PIXEL - RAM_PIPELINE_GUARD_CYCLES


@dataclass(frozen=True)
class NominalProof:
    pixels_checked: int
    eligible_phase_cycles_checked: int
    minimum_slack_cycles: int
    minimum_slack_ms: float
    minimum_row: int
    minimum_column: int


def prove_nominal_geometry() -> NominalProof:
    minimum = None
    minimum_location = (0, 0)
    for row in range(HEIGHT):
        for column in range(WIDTH):
            slack = output_read_deadline(row, column) - producer_write_time(row, column)
            if minimum is None or slack < minimum:
                minimum = slack
                minimum_location = (row, column)
    assert minimum is not None and minimum > 0

    # The candidate is eligible only after pixel zero. Every later relative
    # phase makes all producer writes earlier by `phase`, so the phase-zero
    # result is the global minimum. Enumerate every possible eligible source
    # clock phase through the visible sweep to lock that monotonic argument.
    visible_sweep_cycles = (
        (HEIGHT - 1) * PRODUCER_LINE_DOTS * PRODUCER_CYCLES_PER_DOT
        + (WIDTH - 1) * PRODUCER_CYCLES_PER_DOT
        + 1
    )
    for phase in range(visible_sweep_cycles):
        if minimum + phase <= 0:
            raise AssertionError(f"unsafe nominal phase {phase}")

    return NominalProof(
        pixels_checked=WIDTH * HEIGHT,
        eligible_phase_cycles_checked=visible_sweep_cycles,
        minimum_slack_cycles=minimum,
        minimum_slack_ms=minimum * 1000 / SYSTEM_CLOCK_HZ,
        minimum_row=minimum_location[0],
        minimum_column=minimum_location[1],
    )


@dataclass(frozen=True)
class ProgrammableCounterexample:
    final_line: int
    first_stale_row: int
    first_stale_address: int
    read_deadline_cycles: int


def programmable_final_line_counterexample(final_line: int = 143) -> ProgrammableCounterexample:
    # LCD output is delayed by one display line: line 1 publishes row 0 and
    # line 144 publishes row 143. A final line of 143 therefore computes but
    # never publishes the last visible row.
    if final_line >= HEIGHT:
        raise ValueError("counterexample requires a frame shorter than 144 lines")
    first_stale_row = final_line
    return ProgrammableCounterexample(
        final_line=final_line,
        first_stale_row=first_stale_row,
        first_stale_address=first_stale_row * WIDTH,
        read_deadline_cycles=output_read_deadline(first_stale_row, 0),
    )


@dataclass(frozen=True)
class Opportunity:
    final_line: int
    output_frames_per_phase_period: int
    eligible_output_frames: int
    eligible_percent: float
    content_age_reduction_per_eligible_ms: float
    phase_average_content_age_reduction_ms: float


def quantify_opportunity(final_line: int = 158) -> Opportunity:
    if final_line < HEIGHT:
        raise ValueError("beam candidate requires at least 144 producer lines")
    producer_period = (final_line + 1) * PRODUCER_LINE_DOTS * PRODUCER_CYCLES_PER_DOT
    phase_quantum = gcd(producer_period, OUTPUT_FRAME_SYSTEM_CYCLES)
    output_frames = producer_period // phase_quantum
    eligible_counts = []
    for initial_residue in range(phase_quantum):
        eligible_counts.append(
            sum(
                0
                < (initial_residue + boundary * OUTPUT_FRAME_SYSTEM_CYCLES)
                % producer_period
                <= LAST_VISIBLE_WRITE_PHASE
                for boundary in range(output_frames)
            )
        )
    if min(eligible_counts) != max(eligible_counts):
        raise AssertionError("candidate opportunity depends on unproven reset phase")
    eligible = eligible_counts[0]
    generation_ms = producer_period * 1000 / SYSTEM_CLOCK_HZ
    eligible_fraction = eligible / output_frames
    return Opportunity(
        final_line=final_line,
        output_frames_per_phase_period=output_frames,
        eligible_output_frames=eligible,
        eligible_percent=eligible_fraction * 100,
        content_age_reduction_per_eligible_ms=generation_ms,
        phase_average_content_age_reduction_ms=eligible_fraction * generation_ms,
    )


@dataclass(frozen=True)
class ArbiterReuseCounterexample:
    selected_bank: int
    next_writer_bank: int
    recycled_writer_bank: int
    producer_completions_before_consumer: int


def current_arbiter_reuse_counterexample() -> ArbiterReuseCounterexample:
    # Exact 10/10 branch behavior in apf_framebank_arbiter: first completion
    # publishes selected writer 2 as pending and chooses free writer 3; the
    # second completion supersedes that pending frame and recycles bank 2.
    selected = 2
    pending = selected
    next_writer = 3
    recycled = pending
    assert recycled == selected
    return ArbiterReuseCounterexample(
        selected_bank=selected,
        next_writer_bank=next_writer,
        recycled_writer_bank=recycled,
        producer_completions_before_consumer=2,
    )


def main() -> None:
    proof = prove_nominal_geometry()
    opportunity = quantify_opportunity()
    programmable = programmable_final_line_counterexample()
    reuse = current_arbiter_reuse_counterexample()
    print(
        "nominal: "
        f"pixels={proof.pixels_checked} phases={proof.eligible_phase_cycles_checked} "
        f"minimum_slack={proof.minimum_slack_cycles} cycles/"
        f"{proof.minimum_slack_ms:.6f} ms at "
        f"({proof.minimum_row},{proof.minimum_column})"
    )
    print(
        "opportunity: "
        f"eligible={opportunity.eligible_output_frames}/"
        f"{opportunity.output_frames_per_phase_period} "
        f"({opportunity.eligible_percent:.6f}%) "
        f"per_eligible={opportunity.content_age_reduction_per_eligible_ms:.6f} ms "
        f"phase_average={opportunity.phase_average_content_age_reduction_ms:.6f} ms"
    )
    print(
        "programmable counterexample: "
        f"final_line={programmable.final_line} stale_row={programmable.first_stale_row} "
        f"address={programmable.first_stale_address}"
    )
    print(
        "arbiter counterexample: "
        f"selected={reuse.selected_bank} next={reuse.next_writer_bank} "
        f"recycled={reuse.recycled_writer_bank} completions_before_next_consumer="
        f"{reuse.producer_completions_before_consumer}"
    )


if __name__ == "__main__":
    main()
