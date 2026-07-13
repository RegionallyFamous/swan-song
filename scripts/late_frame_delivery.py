#!/usr/bin/env python3
"""Exact timing model for the isolated APF late-frame candidate.

The model stops at the APF input bus.  It does not estimate Pocket scaler,
panel, controller-sampling, or game-response latency.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from math import gcd

SYSTEM_CLOCK_HZ = 36_864_000
PIXEL_DIVIDE = 6
PRODUCER_LINE_SYSTEM_CYCLES = 256 * 12
PRODUCER_SYSTEM_CYCLES = 159 * PRODUCER_LINE_SYSTEM_CYCLES

WIDTH = 224
HEIGHT = 144

CURRENT_H_TOTAL = 397
CURRENT_V_TOTAL = 258
CURRENT_ACTIVE_X = 31
CURRENT_ACTIVE_Y = 66

LATE_H_TOTAL = 256
LATE_V_TOTAL = 400
LATE_ACTIVE_X = 9
LATE_ACTIVE_Y = 256
LATE_HS_X = 7
LATE_EOL_X = LATE_ACTIVE_X + WIDTH


@dataclass(frozen=True)
class PhaseAge:
    consumer_system_cycles: int
    phase_quantum_cycles: int
    reset_residues_checked: int
    selections_per_residue: int
    selection_mean_min_cycles: Fraction
    selection_mean_max_cycles: Fraction
    mean_pixel_offset_cycles: Fraction
    first_pixel_offset_cycles: int

    @property
    def mean_pixel_age_min_cycles(self) -> Fraction:
        return self.selection_mean_min_cycles + self.mean_pixel_offset_cycles

    @property
    def mean_pixel_age_max_cycles(self) -> Fraction:
        return self.selection_mean_max_cycles + self.mean_pixel_offset_cycles

    @property
    def first_pixel_age_min_cycles(self) -> Fraction:
        return self.selection_mean_min_cycles + self.first_pixel_offset_cycles

    @property
    def first_pixel_age_max_cycles(self) -> Fraction:
        return self.selection_mean_max_cycles + self.first_pixel_offset_cycles


@dataclass(frozen=True)
class LateDeliveryMetrics:
    current: PhaseAge
    late: PhaseAge
    late_refresh_hz: Fraction
    late_selection_after_vs_cycles: int
    newer_generation_residues: int
    producer_residues_checked: int

    @property
    def newer_generation_fraction(self) -> Fraction:
        return Fraction(
            self.newer_generation_residues,
            self.producer_residues_checked,
        )

    @property
    def guaranteed_mean_pixel_improvement_cycles(self) -> Fraction:
        return (
            self.current.mean_pixel_age_min_cycles
            - self.late.mean_pixel_age_max_cycles
        )

    @property
    def guaranteed_first_pixel_improvement_cycles(self) -> Fraction:
        return (
            self.current.first_pixel_age_min_cycles
            - self.late.first_pixel_age_max_cycles
        )


@dataclass(frozen=True)
class OrientationFrame:
    frame: int
    presented_slot: int
    expected_applied_slot: int
    command_for_next_frame: int
    repeated: bool

    @property
    def matched(self) -> bool:
        return self.presented_slot == self.expected_applied_slot


def active_mean_offset_cycles(
    h_total: int,
    active_x: int,
    active_y_offset: int,
) -> Fraction:
    mean_row = Fraction(HEIGHT - 1, 2)
    mean_column = Fraction(WIDTH - 1, 2)
    return (
        (active_y_offset + mean_row) * h_total
        + active_x
        + mean_column
    ) * PIXEL_DIVIDE


def enumerate_phase_age(
    *,
    h_total: int,
    v_total: int,
    active_x: int,
    active_y_offset: int,
) -> PhaseAge:
    consumer_cycles = h_total * v_total * PIXEL_DIVIDE
    quantum = gcd(PRODUCER_SYSTEM_CYCLES, consumer_cycles)
    selections = PRODUCER_SYSTEM_CYCLES // quantum
    means: list[Fraction] = []

    # Every possible reset/event alignment is represented by one residue in
    # [0, quantum).  Enumerating a complete superperiod for each residue checks
    # exactly PRODUCER_SYSTEM_CYCLES distinct completion phases overall.
    phases_seen: set[int] = set()
    for initial_residue in range(quantum):
        ages = []
        for selection in range(selections):
            phase = (
                initial_residue + selection * consumer_cycles
            ) % PRODUCER_SYSTEM_CYCLES
            phases_seen.add(phase)
            ages.append(phase)
        means.append(Fraction(sum(ages), len(ages)))

    if len(phases_seen) != PRODUCER_SYSTEM_CYCLES:
        raise AssertionError("phase enumeration did not cover every producer cycle")

    return PhaseAge(
        consumer_system_cycles=consumer_cycles,
        phase_quantum_cycles=quantum,
        reset_residues_checked=quantum,
        selections_per_residue=selections,
        selection_mean_min_cycles=min(means),
        selection_mean_max_cycles=max(means),
        mean_pixel_offset_cycles=active_mean_offset_cycles(
            h_total,
            active_x,
            active_y_offset,
        ),
        first_pixel_offset_cycles=(active_y_offset * h_total + active_x)
        * PIXEL_DIVIDE,
    )


def validate_apf_geometry() -> None:
    if LATE_H_TOTAL * LATE_V_TOTAL != 102_400:
        raise AssertionError("late raster is not exact 60 Hz at 6.144 MHz")
    if LATE_HS_X < 3:
        raise AssertionError("first HS violates APF's VS-to-HS minimum")
    if LATE_ACTIVE_X - LATE_HS_X < 2:
        raise AssertionError("no inactive clock remains between HS and DE")
    if LATE_EOL_X >= LATE_H_TOTAL:
        raise AssertionError("no room remains for APF EOL or line tail")
    if LATE_ACTIVE_Y + HEIGHT != LATE_V_TOTAL:
        raise AssertionError("active image is not the final 144 lines")


def derive() -> LateDeliveryMetrics:
    validate_apf_geometry()
    current = enumerate_phase_age(
        h_total=CURRENT_H_TOTAL,
        v_total=CURRENT_V_TOTAL,
        active_x=CURRENT_ACTIVE_X,
        active_y_offset=CURRENT_ACTIVE_Y,
    )
    late = enumerate_phase_age(
        h_total=LATE_H_TOTAL,
        v_total=LATE_V_TOTAL,
        active_x=LATE_ACTIVE_X,
        active_y_offset=0,
    )

    late_selection_after_vs = LATE_ACTIVE_Y * LATE_H_TOTAL * PIXEL_DIVIDE
    newer = 0
    for age_at_vs in range(PRODUCER_SYSTEM_CYCLES):
        until_next_completion = (
            PRODUCER_SYSTEM_CYCLES - age_at_vs
            if age_at_vs
            else PRODUCER_SYSTEM_CYCLES
        )
        if until_next_completion <= late_selection_after_vs:
            newer += 1

    return LateDeliveryMetrics(
        current=current,
        late=late,
        late_refresh_hz=Fraction(
            SYSTEM_CLOCK_HZ,
            late.consumer_system_cycles,
        ),
        late_selection_after_vs_cycles=late_selection_after_vs,
        newer_generation_residues=newer,
        producer_residues_checked=PRODUCER_SYSTEM_CYCLES,
    )


def model_current_dynamic_orientation() -> tuple[OrientationFrame, ...]:
    """Model the potential mismatch in the currently integrated ordering.

    The new bank orientation is exposed in frame 1.  Its EOL command is also
    emitted in frame 1, but the official APF contract applies that command to
    frame 2, leaving frame 1 paired with the previous slot.
    """
    return (
        OrientationFrame(0, 0, 0, 0, False),
        OrientationFrame(1, 1, 0, 1, False),
        OrientationFrame(2, 1, 1, 1, False),
    )


def model_safe_deferred_orientation() -> tuple[OrientationFrame, ...]:
    """Model a repeat/command frame followed by matched promotion."""
    return (
        OrientationFrame(0, 0, 0, 0, False),
        OrientationFrame(1, 0, 0, 1, True),
        OrientationFrame(2, 1, 1, 1, False),
    )


def milliseconds(cycles: Fraction | int) -> float:
    return float(Fraction(cycles) * 1000 / SYSTEM_CLOCK_HZ)


def main() -> None:
    metrics = derive()
    print(
        "late raster: "
        f"{LATE_H_TOTAL}x{LATE_V_TOTAL} "
        f"refresh={float(metrics.late_refresh_hz):.9f} Hz "
        f"selection_after_vs={milliseconds(metrics.late_selection_after_vs_cycles):.6f} ms"
    )
    print(
        "current mean active-pixel age: "
        f"{milliseconds(metrics.current.mean_pixel_age_min_cycles):.6f}.."
        f"{milliseconds(metrics.current.mean_pixel_age_max_cycles):.6f} ms"
    )
    print(
        "late mean active-pixel age: "
        f"{milliseconds(metrics.late.mean_pixel_age_min_cycles):.6f}.."
        f"{milliseconds(metrics.late.mean_pixel_age_max_cycles):.6f} ms"
    )
    print(
        "guaranteed improvement: "
        f"mean={milliseconds(metrics.guaranteed_mean_pixel_improvement_cycles):.6f} ms "
        f"first={milliseconds(metrics.guaranteed_first_pixel_improvement_cycles):.6f} ms"
    )
    print(
        "one-newer-generation opportunities: "
        f"{metrics.newer_generation_residues}/"
        f"{metrics.producer_residues_checked} "
        f"({float(metrics.newer_generation_fraction * 100):.6f}%)"
    )


if __name__ == "__main__":
    main()
