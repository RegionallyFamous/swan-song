#!/usr/bin/env python3
"""Convert a Quartus RBF to the per-byte bit-reversed APF format."""

import argparse
import pathlib


REVERSE = bytes(int(f"{value:08b}"[::-1], 2) for value in range(256))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=pathlib.Path)
    parser.add_argument("output", type=pathlib.Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(args.input.read_bytes().translate(REVERSE))


if __name__ == "__main__":
    main()
