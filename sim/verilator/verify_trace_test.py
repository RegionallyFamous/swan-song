#!/usr/bin/env python3
"""Compatibility tests for the standalone structured-trace verifier."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


VERIFY = Path(__file__).with_name("verify_trace.py")


def run(path: Path, *arguments: str, succeeds: bool = True) -> None:
    result = subprocess.run(
        [sys.executable, str(VERIFY), str(path), *arguments],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if (result.returncode == 0) != succeeds:
        raise AssertionError(result.stdout + result.stderr)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="swansong-trace-test-") as directory:
        root = Path(directory)
        v1 = root / "v1.csv"
        v1.write_text(
            "cycle,event,physical_pc,cs,ip,address,value\n"
            "1,cpu,74565,4660,5,,\n",
            encoding="utf-8",
        )
        run(v1, "--allowed", "cpu", "--require", "cpu")

        v2 = root / "v2.csv"
        v2.write_text(
            "cycle,event,physical_pc,cs,ip,address,value,role\n"
            "2,vram,,,,8192,,screen1_tile\n",
            encoding="utf-8",
        )
        run(v2, "--allowed", "vram", "--require", "vram", "--vram-role", "screen1_tile")
        run(v2, "--mem-space", "iram", succeeds=False)

        v3 = root / "v3.csv"
        v3.write_text(
            "cycle,event,physical_pc,cs,ip,address,value,role,initiator,access,"
            "byte_enable,space,mapped_offset,instruction_id,origin_pc,origin_status\n"
            "3,mem,,,,16384,4660,,gdma,write,3,iram,16384,,,not_applicable\n",
            encoding="utf-8",
        )
        run(v3, "--allowed", "mem", "--require", "mem", "--mem-initiator", "gdma")
        invalid_origin = root / "invalid-origin.csv"
        invalid_origin.write_text(
            "cycle,event,physical_pc,cs,ip,address,value,role,initiator,access,"
            "byte_enable,space,mapped_offset,instruction_id,origin_pc,origin_status\n"
            "4,mem,,,,16384,0,,cpu,write,3,iram,16384,,,exact\n",
            encoding="utf-8",
        )
        run(invalid_origin, "--allowed", "mem", succeeds=False)

    print("PASS structured trace verifier v1/v2/v3 compatibility")


if __name__ == "__main__":
    main()
