#!/usr/bin/env python3
"""Make the generated Freya file header deterministic for regression."""

from __future__ import annotations

import argparse
from pathlib import Path


# 2025-11-30 12:00:00, the pinned AthenaOS commit date, in Freya/DOS layout.
PINNED_MTIME = 0x337E6000
MTIME_OFFSET = 116
HEADER_SIZE = 128


def normalize(path: Path) -> None:
    data = bytearray(path.read_bytes())
    if len(data) < HEADER_SIZE or data[:4] != b"#!ws":
        raise ValueError(f"{path}: not a Freya-headered file")
    data[MTIME_OFFSET : MTIME_OFFSET + 4] = PINNED_MTIME.to_bytes(4, "little")
    path.write_bytes(data)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    args = parser.parse_args()
    try:
        normalize(args.file)
    except (OSError, ValueError) as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
