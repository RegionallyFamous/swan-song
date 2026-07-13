#!/usr/bin/env python3
"""Fail-closed service/depth model for future A0 sequential copy-out.

The current Swan SDRAM arbiter has no bounded service guarantee for a future
lowest-priority client. Accordingly, omitting --halfword-service-bound-mem-cycles
always produces an unproven result and exit status 2. Supplying a bound models a
hypothetical reviewed arbiter contract; it does not enable Memories.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from fractions import Fraction
from typing import Any


DEFAULT_PAYLOAD_BYTES = 0x90300
DEFAULT_BRIDGE_CLOCK_HZ = 74_250_000
DEFAULT_MEMORY_CLOCK_HZ = 110_592_000
DEFAULT_BRIDGE_PERIOD_CYCLES = 88
DEFAULT_SETUP_MARGIN_MEM_CYCLES = 2
DEFAULT_READER_WORD_OVERHEAD_MEM_CYCLES = 3


@dataclass(frozen=True)
class ModelConfig:
    payload_bytes: int = DEFAULT_PAYLOAD_BYTES
    bridge_clock_hz: int = DEFAULT_BRIDGE_CLOCK_HZ
    memory_clock_hz: int = DEFAULT_MEMORY_CLOCK_HZ
    bridge_period_cycles: int = DEFAULT_BRIDGE_PERIOD_CYCLES
    setup_margin_mem_cycles: int = DEFAULT_SETUP_MARGIN_MEM_CYCLES
    reader_word_overhead_mem_cycles: int = (
        DEFAULT_READER_WORD_OVERHEAD_MEM_CYCLES
    )
    halfword_service_bound_mem_cycles: int | None = None

    def validate(self) -> None:
        if self.payload_bytes <= 0 or self.payload_bytes % 4:
            raise ValueError("payload_bytes must be a positive multiple of four")
        if self.bridge_clock_hz <= 0 or self.memory_clock_hz <= 0:
            raise ValueError("clock frequencies must be positive")
        if self.bridge_period_cycles <= 0:
            raise ValueError("bridge_period_cycles must be positive")
        if self.setup_margin_mem_cycles < 0:
            raise ValueError("setup margin cannot be negative")
        if self.reader_word_overhead_mem_cycles < 0:
            raise ValueError("reader overhead cannot be negative")
        if (
            self.halfword_service_bound_mem_cycles is not None
            and self.halfword_service_bound_mem_cycles <= 0
        ):
            raise ValueError("halfword service bound must be positive")
        if self.bridge_period_mem_cycles <= self.setup_margin_mem_cycles:
            raise ValueError("setup margin consumes the entire BRIDGE word period")

    @property
    def payload_words(self) -> int:
        return self.payload_bytes // 4

    @property
    def bridge_period_mem_cycles(self) -> Fraction:
        return Fraction(
            self.bridge_period_cycles * self.memory_clock_hz,
            self.bridge_clock_hz,
        )

    @property
    def word_service_bound_mem_cycles(self) -> int | None:
        if self.halfword_service_bound_mem_cycles is None:
            return None
        # The isolated reader performs two serialized x16 reads. From one
        # cached-word completion to the next, three local cycles cover cache
        # handoff/request acceptance and the two distinct issue edges.
        return (
            2 * self.halfword_service_bound_mem_cycles
            + self.reader_word_overhead_mem_cycles
        )


@dataclass(frozen=True)
class SimulationResult:
    safe: bool
    depth_words: int
    failed_word_index: int | None
    failed_deadline_mem_cycles: Fraction | None
    minimum_occupancy_words: int


def _fraction_text(value: Fraction) -> str:
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


def simulate_depth(config: ModelConfig, depth_words: int) -> SimulationResult:
    """Simulate the slowest legal producer against the fastest legal host.

    The FIFO is completely prefetched before A0 publication. The first word is
    therefore present at time zero. Each actual BRIDGE word time frees one FIFO
    slot. A single serialized producer refills available slots, taking exactly
    the asserted maximum service interval. Every word after the first must be
    present setup_margin cycles before its BRIDGE strobe.

    Constant maximum producer latency and minimum host spacing dominate every
    bounded-latency work-conserving trace, so this event trace is adversarial.
    """

    config.validate()
    if config.word_service_bound_mem_cycles is None:
        raise ValueError("cannot simulate without a finite halfword service bound")
    if depth_words <= 0 or depth_words > config.payload_words:
        raise ValueError("depth_words must be within the payload word count")

    capacity = depth_words
    occupancy = depth_words
    produced = depth_words
    minimum_occupancy = occupancy
    service = Fraction(config.word_service_bound_mem_cycles, 1)
    period = config.bridge_period_mem_cycles
    margin = Fraction(config.setup_margin_mem_cycles, 1)
    completion_time: Fraction | None = None

    def start_if_possible(now: Fraction) -> None:
        nonlocal completion_time
        if (
            completion_time is None
            and produced < config.payload_words
            and occupancy < capacity
        ):
            completion_time = now + service

    def advance_completions(limit: Fraction) -> None:
        nonlocal completion_time, occupancy, produced
        while completion_time is not None and completion_time <= limit:
            now = completion_time
            if occupancy >= capacity:
                raise AssertionError("producer completed without a reserved slot")
            occupancy += 1
            produced += 1
            completion_time = None
            start_if_possible(now)

    for word_index in range(config.payload_words):
        actual_time = period * word_index
        deadline = actual_time if word_index == 0 else actual_time - margin

        advance_completions(deadline)
        if occupancy == 0:
            return SimulationResult(
                safe=False,
                depth_words=depth_words,
                failed_word_index=word_index,
                failed_deadline_mem_cycles=deadline,
                minimum_occupancy_words=minimum_occupancy,
            )

        # Data that arrives after setup deadline cannot satisfy this word, but
        # may be queued behind it for a later word before the actual strobe.
        advance_completions(actual_time)
        occupancy -= 1
        minimum_occupancy = min(minimum_occupancy, occupancy)
        start_if_possible(actual_time)

    return SimulationResult(
        safe=True,
        depth_words=depth_words,
        failed_word_index=None,
        failed_deadline_mem_cycles=None,
        minimum_occupancy_words=minimum_occupancy,
    )


def minimum_safe_depth(config: ModelConfig) -> tuple[int, SimulationResult]:
    """Return the smallest fully-prefetched FIFO that passes the full blob."""

    config.validate()
    if config.word_service_bound_mem_cycles is None:
        raise ValueError("no finite depth can be derived without a service bound")

    low = 1
    high = config.payload_words
    high_result = simulate_depth(config, high)
    if not high_result.safe:
        raise AssertionError("full independent prefetch must cover a finite blob")

    while low < high:
        middle = (low + high) // 2
        result = simulate_depth(config, middle)
        if result.safe:
            high = middle
        else:
            low = middle + 1
    result = simulate_depth(config, low)
    return low, result


def analyze(config: ModelConfig, verify_depth_words: int | None = None) -> dict[str, Any]:
    """Return a JSON-serializable proof result."""

    config.validate()
    period = config.bridge_period_mem_cycles
    base: dict[str, Any] = {
        "payload_bytes": config.payload_bytes,
        "payload_words": config.payload_words,
        "bridge_clock_hz": config.bridge_clock_hz,
        "memory_clock_hz": config.memory_clock_hz,
        "bridge_period_cycles": config.bridge_period_cycles,
        "bridge_period_mem_cycles_exact": _fraction_text(period),
        "bridge_period_mem_cycles": float(period),
        "setup_margin_mem_cycles": config.setup_margin_mem_cycles,
        "reader_word_overhead_mem_cycles": (
            config.reader_word_overhead_mem_cycles
        ),
        "full_blob_prefill_words": config.payload_words,
        "full_blob_prefill_bytes": config.payload_bytes,
        "production_integrated": False,
        "memories_enabled": False,
    }

    if config.halfword_service_bound_mem_cycles is None:
        base.update(
            {
                "status": "unproven",
                "safe": False,
                "halfword_service_bound_mem_cycles": None,
                "word_service_bound_mem_cycles": None,
                "minimum_fifo_depth_words": None,
                "reason": (
                    "current Swan fixed-priority SDRAM arbitration supplies no "
                    "finite maximum wait for a future lower-priority client"
                ),
                "buffer_only_fallback": (
                    "prefetch the complete blob into independent proven storage "
                    "before A0 publication"
                ),
            }
        )
        return base

    minimum_depth, minimum_result = minimum_safe_depth(config)
    base.update(
        {
            "status": "conditional-proof",
            "safe": True,
            "halfword_service_bound_mem_cycles": (
                config.halfword_service_bound_mem_cycles
            ),
            "word_service_bound_mem_cycles": (
                config.word_service_bound_mem_cycles
            ),
            "minimum_fifo_depth_words": minimum_depth,
            "minimum_fifo_depth_bytes": minimum_depth * 4,
            "minimum_occupancy_words": minimum_result.minimum_occupancy_words,
            "reason": (
                "safe only if the supplied halfword bound, clocks, setup margin, "
                "sequential access, complete initial prefill, and work-conserving "
                "single-reader assumptions are independently proven"
            ),
        }
    )

    if verify_depth_words is not None:
        verification = simulate_depth(config, verify_depth_words)
        base["verified_depth_words"] = verify_depth_words
        base["verified_depth_safe"] = verification.safe
        base["verified_depth_failed_word_index"] = verification.failed_word_index
        base["verified_depth_failed_deadline_mem_cycles"] = (
            None
            if verification.failed_deadline_mem_cycles is None
            else _fraction_text(verification.failed_deadline_mem_cycles)
        )
    return base


def _integer(text: str) -> int:
    return int(text, 0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload-bytes", type=_integer, default=DEFAULT_PAYLOAD_BYTES)
    parser.add_argument("--bridge-clock-hz", type=_integer, default=DEFAULT_BRIDGE_CLOCK_HZ)
    parser.add_argument("--memory-clock-hz", type=_integer, default=DEFAULT_MEMORY_CLOCK_HZ)
    parser.add_argument(
        "--bridge-period-cycles", type=_integer, default=DEFAULT_BRIDGE_PERIOD_CYCLES
    )
    parser.add_argument(
        "--setup-margin-mem-cycles",
        type=_integer,
        default=DEFAULT_SETUP_MARGIN_MEM_CYCLES,
    )
    parser.add_argument(
        "--reader-word-overhead-mem-cycles",
        type=_integer,
        default=DEFAULT_READER_WORD_OVERHEAD_MEM_CYCLES,
    )
    parser.add_argument(
        "--halfword-service-bound-mem-cycles",
        type=_integer,
        help=(
            "reviewed maximum from one x16 request edge through its ready pulse; "
            "omit to model the current unbounded fixed-priority arbiter"
        ),
    )
    parser.add_argument(
        "--verify-depth-words",
        type=_integer,
        help="also run the full adversarial copy at this FIFO depth",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = ModelConfig(
        payload_bytes=args.payload_bytes,
        bridge_clock_hz=args.bridge_clock_hz,
        memory_clock_hz=args.memory_clock_hz,
        bridge_period_cycles=args.bridge_period_cycles,
        setup_margin_mem_cycles=args.setup_margin_mem_cycles,
        reader_word_overhead_mem_cycles=args.reader_word_overhead_mem_cycles,
        halfword_service_bound_mem_cycles=(
            args.halfword_service_bound_mem_cycles
        ),
    )
    try:
        result = analyze(config, args.verify_depth_words)
    except ValueError as error:
        print(json.dumps({"status": "invalid", "safe": False, "error": str(error)}))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["safe"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
