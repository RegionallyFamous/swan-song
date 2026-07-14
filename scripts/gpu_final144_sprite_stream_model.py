#!/usr/bin/env python3
"""Exhaustive timing model for the final-144 OAM-to-row-0 handoff.

This is deliberately independent of the production RTL.  It models the
minimum-bandwidth fast-forward case: one WonderSwan ``ce`` every four FPGA
clocks, the GPU's eight-slot VRAM arbiter, one OAM word per ``ce``, and a
row-zero sprite-tile streamer with one current job plus one pending job.

Primary contract:

* WSdev Display/Sprites revision 507 says line 144 copies one 16-bit word per
  system clock into the internal sprite table and that the new table is used
  by the next frame.
* Mesen2 b9fa69d copies into ``_spriteRam`` on line 144 and row zero then draws
  from that array.
* ares 449b937 writes the current OAM field on line 144, toggles the field at
  the frame boundary, and row zero reads the newly written bank.

The production implementation may use different state names, but must retain
the modeled service contract and deadline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


ARBITER_SLOTS = 8
FAST_CE_CLOCKS = 4
OAM_REQUEST_SLOTS = frozenset((1, 5))
OAM_RESPONSE_DELAY = 2
TILE_REQUEST_SLOTS = frozenset((2, 6))
TILE_RESPONSE_DELAY = 2
OAM_WORDS = 256
MAX_OBJECTS = 32
SPRITE_PREROLL_CYCLES = 15


@dataclass(frozen=True)
class Job:
    descriptor: int
    arrived: int


@dataclass(frozen=True)
class CaseResult:
    boundary_phase: int
    sprite_count: int
    active: tuple[int, ...]
    accepted: tuple[int, ...]
    max_pending: int
    last_accept_clock: int | None
    start_offset: int
    tile_requests: int


def next_slot(clock: int, slots: frozenset[int], *, strict: bool = False) -> int:
    """Return the first matching arbiter slot at or after ``clock``."""

    candidate = clock + int(strict)
    while candidate % ARBITER_SLOTS not in slots:
        candidate += 1
    return candidate


def descriptor_arrivals(boundary_phase: int) -> dict[int, int]:
    """Return current-generation descriptor completion clocks.

    OAM word zero is requested on the edge entering line 144.  Word ``n`` is
    requested four FPGA clocks later than word ``n - 1``.  Odd responses
    complete one 32-bit descriptor.
    """

    arrivals: dict[int, int] = {}
    previous_issue = -1
    for word in range(OAM_WORDS):
        request = word * FAST_CE_CLOCKS
        issue = next_slot(request + boundary_phase, OAM_REQUEST_SLOTS)
        # The one-entry OAM request queue is sufficient only if every request
        # physically issues before the next logical request.
        assert issue - boundary_phase < request + FAST_CE_CLOCKS
        assert issue > previous_issue
        previous_issue = issue
        if word & 1:
            descriptor = word // 2
            arrivals[descriptor] = issue - boundary_phase + OAM_RESPONSE_DELAY
    assert tuple(arrivals) == tuple(range(128))
    return arrivals


def first_ce_strictly_after(clock: int, first_ce: int) -> int:
    """Return the first row-zero CE after all Next-array writes have settled."""

    candidate = first_ce
    while candidate <= clock:
        candidate += FAST_CE_CLOCKS
    return candidate


def run_case(
    boundary_phase: int,
    sprite_count: int,
    active_descriptors: Iterable[int],
) -> CaseResult:
    """Run one streaming-predecode schedule and prove its invariants."""

    assert 0 <= boundary_phase < ARBITER_SLOTS
    assert 0 <= sprite_count <= 128
    active = tuple(sorted(set(active_descriptors)))
    assert all(0 <= descriptor < 128 for descriptor in active)
    active_set = set(active)
    arrivals = descriptor_arrivals(boundary_phase)
    arrival_events = {
        clock: descriptor
        for descriptor, clock in arrivals.items()
        if descriptor < sprite_count and descriptor in active_set
    }
    # OAM descriptor responses are eight clocks apart, so there can be only
    # one active arrival on a clock.
    assert len(arrival_events) == len(
        [
            descriptor
            for descriptor in active
            if descriptor < sprite_count
        ]
    )

    frame_boundary = OAM_WORDS * FAST_CE_CLOCKS
    first_row0_ce = frame_boundary + FAST_CE_CLOCKS
    stop_clock = frame_boundary + 4 * SPRITE_PREROLL_CYCLES

    current: Job | None = None
    pending: Job | None = None
    outstanding: tuple[int, Job, int] | None = None
    words_issued = 0
    max_pending = 0
    accepted: list[int] = []
    accepted_at: list[int] = []
    issued_for: dict[int, list[int]] = {}

    for clock in range(stop_clock + 1):
        # OAM high-word responses occur in slots 3/7; tile responses occur in
        # slots 4/0.  Keeping the assertion explicit prevents an accidental
        # model ordering dependency.
        arbiter_phase = (clock + boundary_phase) % ARBITER_SLOTS
        if clock in arrival_events:
            assert arbiter_phase in (3, 7)
            descriptor = arrival_events[clock]
            if len(accepted) + int(current is not None) + int(pending is not None) < MAX_OBJECTS:
                job = Job(descriptor, clock)
                if current is None:
                    current = job
                else:
                    assert pending is None, (
                        f"pending overflow phase={boundary_phase} "
                        f"descriptor={descriptor} clock={clock}"
                    )
                    pending = job
                    max_pending = 1

        if outstanding is not None and outstanding[0] == clock:
            _, response_job, word = outstanding
            assert current == response_job
            outstanding = None
            if word == 1:
                accepted.append(response_job.descriptor)
                # gpu.vhd raises loadNext on this response edge.  sprites.vhd
                # accepts that registered pulse on the following FPGA clock.
                accepted_at.append(clock + 1)
                current = pending
                pending = None

        if arbiter_phase in TILE_REQUEST_SLOTS and current is not None:
            assert outstanding is None
            issued_words = issued_for.setdefault(current.descriptor, [])
            word = len(issued_words)
            assert word in (0, 1)
            assert clock > current.arrived
            issued_words.append(clock)
            words_issued += 1
            outstanding = (clock + TILE_RESPONSE_DELAY, current, word)

    expected = tuple(
        descriptor
        for descriptor in active
        if descriptor < sprite_count
    )[:MAX_OBJECTS]
    assert tuple(accepted) == expected, (
        f"accept order phase={boundary_phase} count={sprite_count}: "
        f"{accepted} != {expected}"
    )
    assert words_issued == 2 * len(expected)
    assert current is None and pending is None and outstanding is None
    assert all(len(words) == 2 for words in issued_for.values())

    if accepted_at:
        last_accept = accepted_at[-1]
        start_clock = first_ce_strictly_after(last_accept, first_row0_ce)
    else:
        last_accept = None
        start_clock = first_row0_ce
    assert (start_clock - first_row0_ce) % FAST_CE_CLOCKS == 0
    start_offset = (start_clock - first_row0_ce) // FAST_CE_CLOCKS
    assert start_offset <= 2, (
        f"row0 start deadline phase={boundary_phase} count={sprite_count} "
        f"offset={start_offset}"
    )
    assert start_offset < SPRITE_PREROLL_CYCLES

    return CaseResult(
        boundary_phase=boundary_phase,
        sprite_count=sprite_count,
        active=active,
        accepted=tuple(accepted),
        max_pending=max_pending,
        last_accept_clock=last_accept,
        start_offset=start_offset,
        tile_requests=words_issued,
    )


def main() -> None:
    scenarios: tuple[tuple[str, int, tuple[int, ...]], ...] = (
        ("count0", 0, ()),
        ("count1-first", 1, (0,)),
        ("count32-consecutive", 32, tuple(range(32))),
        ("count128-first32", 128, tuple(range(32))),
        ("count128-all-limit32", 128, tuple(range(128))),
        ("count128-last-only", 128, (127,)),
        ("count128-last32", 128, tuple(range(96, 128))),
    )
    worst_offset = 0
    observed_pending = False
    for phase in range(ARBITER_SLOTS):
        for label, count, active in scenarios:
            result = run_case(phase, count, active)
            worst_offset = max(worst_offset, result.start_offset)
            observed_pending |= result.max_pending == 1
            if label == "count128-last32":
                assert result.accepted[-1] == 127
    assert observed_pending, "tests never exercised the required pending register"
    assert worst_offset == 2, "deadline test did not reach the proven worst case"
    print(
        "PASS final144 sprite stream: 8 phases, counts 0/1/32/128, "
        "first-32 limit, descriptor127, pending depth1, row0 start offset<=2"
    )


if __name__ == "__main__":
    main()
