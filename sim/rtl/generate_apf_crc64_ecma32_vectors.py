#!/usr/bin/env python3
"""Generate independent CRC-64/ECMA-182 vectors for the RTL stream test."""

from __future__ import annotations

import argparse
import random
from pathlib import Path


POLYNOMIAL = 0x42F0E1EBA9EA3693
MASK64 = (1 << 64) - 1
CHECK_123456789 = 0x6C40DF5F0B497347


def update_byte(crc: int, value: int) -> int:
    """Reference one byte using the direct, unreflected ECMA polynomial."""
    crc ^= value << 56
    for _ in range(8):
        crc = ((crc << 1) ^ POLYNOMIAL) & MASK64 if crc & (1 << 63) else (crc << 1) & MASK64
    return crc


def update_bytes(crc: int, payload: bytes) -> int:
    for value in payload:
        crc = update_byte(crc, value)
    return crc


class Vectors:
    CLEAR = 0
    ENABLE = 1
    HOLD = 2
    CLEAR_AND_ENABLE = 3
    ASYNC_RESET = 4

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.crc = 0
        self.lines: list[str] = []

    def emit(self, operation: int, word: int, count: int) -> None:
        self.lines.append(f"{operation} {word:08x} {count} {self.crc:016x}\n")

    def clear(self) -> None:
        self.crc = 0
        self.emit(self.CLEAR, self.rng.getrandbits(32), self.rng.randrange(8))

    def clear_and_enable(self) -> None:
        self.crc = 0
        self.emit(self.CLEAR_AND_ENABLE, self.rng.getrandbits(32), self.rng.randrange(5))

    def async_reset(self) -> None:
        self.crc = 0
        self.emit(self.ASYNC_RESET, self.rng.getrandbits(32), self.rng.randrange(8))

    def hold(self) -> None:
        # Disabled cycles must ignore both data and even an otherwise-illegal
        # byte count. This distinguishes enable from implicit data activity.
        self.emit(self.HOLD, self.rng.getrandbits(32), self.rng.randrange(8))

    def consume(self, payload: bytes) -> None:
        if len(payload) > 4:
            raise ValueError("one RTL transaction can contain at most four bytes")
        poison = self.rng.getrandbits(32)
        word = poison
        for index, value in enumerate(payload):
            shift = 24 - 8 * index
            word = (word & ~(0xFF << shift)) | (value << shift)
        self.crc = update_bytes(self.crc, payload)
        self.emit(self.ENABLE, word, len(payload))

    def reject_invalid_count(self, count: int) -> None:
        if count < 5 or count > 7:
            raise ValueError("invalid-count test must use a three-bit value above four")
        self.emit(self.ENABLE, self.rng.getrandbits(32), count)

    def stream_randomly(self, payload: bytes) -> None:
        offset = 0
        while offset < len(payload):
            if self.rng.randrange(5) == 0:
                self.hold()
            count = min(self.rng.randrange(1, 5), len(payload) - offset)
            self.consume(payload[offset : offset + count])
            offset += count


def generate(output: Path) -> tuple[int, int]:
    rng = random.Random(0x5357414E)
    vectors = Vectors(rng)

    # All 65,536 possible two-byte strings independently prove every input bit
    # and both normalized byte positions against the Python reference.
    for value in range(1 << 16):
        vectors.clear()
        vectors.consume(value.to_bytes(2, "big"))

    # Exercise every possible single byte and all legal byte_count values,
    # including the enabled zero-byte no-op and unused-byte poison.
    for value in range(256):
        vectors.clear()
        vectors.consume(bytes([value]))
        before = vectors.crc
        vectors.consume(b"")
        assert vectors.crc == before

    # The interface contract allows only 0..4. Synthesis must fail closed for
    # a corrupt three-bit count instead of silently treating 5..7 as four.
    vectors.clear()
    vectors.consume(b"SWAN")
    invalid_count_crc = vectors.crc
    for count in range(5, 8):
        vectors.reject_invalid_count(count)
        assert vectors.crc == invalid_count_crc

    standard = b"123456789"
    assert update_bytes(0, standard) == CHECK_123456789
    for segmentation in ((4, 4, 1), (1,) * 9, (3, 2, 4), (2, 3, 1, 3)):
        vectors.clear()
        offset = 0
        for count in segmentation:
            vectors.consume(standard[offset : offset + count])
            offset += count
        assert offset == len(standard)
        assert vectors.crc == CHECK_123456789

    # Random messages cover continuation across arbitrary 1..4-byte segment
    # boundaries, enable gaps, empty streams, and repeated clear/reset cycles.
    random_messages = 256
    for message_index in range(random_messages):
        if message_index % 17 == 0:
            vectors.async_reset()
        else:
            vectors.clear()
        length = rng.randrange(0, 2049)
        payload = bytes(rng.getrandbits(8) for _ in range(length))
        vectors.stream_randomly(payload)
        assert vectors.crc == update_bytes(0, payload)
        vectors.hold()

    # Clear must dominate a simultaneous enable and return the exact seed.
    vectors.consume(b"SWAN")
    vectors.clear_and_enable()
    assert vectors.crc == 0

    output.write_text("".join(vectors.lines), encoding="ascii")
    return len(vectors.lines), random_messages


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    vector_count, random_messages = generate(args.output)
    print(
        "PASS CRC64 vector generation "
        f"vectors={vector_count} exhaustive_pairs=65536 "
        f"random_messages={random_messages} check={CHECK_123456789:016x}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
