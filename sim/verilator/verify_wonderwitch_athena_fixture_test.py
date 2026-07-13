#!/usr/bin/env python3
"""Offline mutation tests for the WonderWitch/AthenaOS fixture source."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from verify_wonderwitch_athena_fixture import verify_source


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "testroms/swan-song/wonderwitch_athena_hello"


def must_fail(path: Path) -> None:
    try:
        verify_source(path)
    except ValueError:
        return
    raise AssertionError("mutated WonderWitch fixture passed source verification")


def main() -> None:
    verify_source(FIXTURE)
    with tempfile.TemporaryDirectory(prefix="swansong-wonderwitch-") as directory:
        copy = Path(directory) / "fixture"
        shutil.copytree(FIXTURE, copy)
        source = copy / "src/main.c"
        source.write_bytes(source.read_bytes().replace(b"Hello, World!", b"Hello, Swan!!", 1))
        must_fail(copy)
    print("PASS WonderWitch Athena fixture source mutation rejection")


if __name__ == "__main__":
    main()
