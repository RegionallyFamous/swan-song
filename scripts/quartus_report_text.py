#!/usr/bin/env python3
"""Strict text decoding shared by Swan Song's Quartus report parsers."""

from __future__ import annotations


LATIN1_DEGREE_BYTE = 0xB0


def decode_quartus_report(data: bytes) -> str:
    """Decode a Quartus report, normalizing only its legacy 0xB0 degree byte.

    Quartus Prime Lite 21.1.1 emits otherwise UTF-8-compatible reports but
    writes temperature units with a standalone ISO-8859-1 degree byte.  Decode
    valid UTF-8 normally and replace only a byte that the UTF-8 decoder itself
    identifies as an invalid standalone 0xB0.  Any other malformed sequence is
    left to fail closed as ``UnicodeDecodeError``.
    """

    decoded: list[str] = []
    offset = 0
    while True:
        try:
            decoded.append(data[offset:].decode("utf-8"))
            return "".join(decoded)
        except UnicodeDecodeError as error:
            invalid = offset + error.start
            if data[invalid] != LATIN1_DEGREE_BYTE:
                raise
            decoded.append(data[offset:invalid].decode("utf-8"))
            decoded.append("°")
            offset = invalid + 1
