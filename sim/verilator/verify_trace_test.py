#!/usr/bin/env python3
"""Compatibility tests for the standalone structured-trace verifier."""

from __future__ import annotations

import csv
import subprocess
import sys
import tempfile
from pathlib import Path


VERIFY = Path(__file__).with_name("verify_trace.py")

V5_FIELDS = [
    "cycle", "event", "physical_pc", "cs", "ip", "address", "value", "role",
    "initiator", "access", "byte_enable", "space", "mapped_offset",
    "instruction_id", "origin_pc", "origin_status", "fetch_value",
    "fetch_collision", "bg_layer", "map_address", "map_value", "map_x", "map_y",
    "tile_bank_enabled", "tile_index", "palette", "hflip", "vflip", "bpp",
    "packed", "tile_row", "tile_row_address", "tile_row_bytes", "tile_row_value",
    "map_collision", "tile_row_collision",
]


def write_v5(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=V5_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


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
        run(
            v3,
            "--require-mem-initiators",
            "gdma",
            "--require-origin-statuses",
            "not_applicable",
        )
        run(v3, "--require-origin-statuses", "exact", succeeds=False)
        invalid_origin = root / "invalid-origin.csv"
        invalid_origin.write_text(
            "cycle,event,physical_pc,cs,ip,address,value,role,initiator,access,"
            "byte_enable,space,mapped_offset,instruction_id,origin_pc,origin_status\n"
            "4,mem,,,,16384,0,,cpu,write,3,iram,16384,,,exact\n",
            encoding="utf-8",
        )
        run(invalid_origin, "--allowed", "mem", succeeds=False)

        v4 = root / "v4.csv"
        v4.write_text(
            "cycle,event,physical_pc,cs,ip,address,value,role,initiator,access,"
            "byte_enable,space,mapped_offset,instruction_id,origin_pc,origin_status,"
            "fetch_value,fetch_collision\n"
            "5,vram,,,,8192,,screen1_tile,,,,,,,,,4660,0\n",
            encoding="utf-8",
        )
        run(v4, "--allowed", "vram", "--require", "vram", "--require-fetch-values")
        collision = root / "v4-collision.csv"
        collision.write_text(
            v4.read_text(encoding="utf-8").replace(",4660,0\n", ",4660,1\n"),
            encoding="utf-8",
        )
        run(collision, "--reject-fetch-collisions", succeeds=False)

        bg1: dict[str, object] = {
            "cycle": 6,
            "event": "bg_cell",
            "bg_layer": 1,
            "map_address": 0x1000,
            "map_value": 0x0201,
            "map_x": 0,
            "map_y": 0,
            "tile_bank_enabled": 0,
            "tile_index": 1,
            "palette": 1,
            "hflip": 0,
            "vflip": 0,
            "bpp": 2,
            "packed": 0,
            "tile_row": 2,
            "tile_row_address": 0x2014,
            "tile_row_bytes": 2,
            "tile_row_value": 0x3412,
            "map_collision": 0,
            "tile_row_collision": 0,
        }
        bg2: dict[str, object] = {
            "cycle": 6,
            "event": "bg_cell",
            "bg_layer": 2,
            "map_address": 0x1842,
            "map_value": 0xED55,
            "map_x": 1,
            "map_y": 1,
            "tile_bank_enabled": 1,
            "tile_index": 0x355,
            "palette": 6,
            "hflip": 1,
            "vflip": 1,
            "bpp": 4,
            "packed": 1,
            "tile_row": 3,
            "tile_row_address": 0xAAAC,
            "tile_row_bytes": 4,
            "tile_row_value": 0x89ABCDEF,
            "map_collision": 1,
            "tile_row_collision": 0,
        }
        v5 = root / "v5.csv"
        write_v5(v5, [bg1, bg2])
        run(v5, "--allowed", "bg_cell", "--require", "bg_cell")

        invalid_cases: dict[str, tuple[str, object]] = {
            "layer": ("bg_layer", 0),
            "map-coordinate": ("map_x", 2),
            "tile-index": ("tile_index", 2),
            "palette": ("palette", 2),
            "hflip": ("hflip", 1),
            "bpp": ("bpp", 3),
            "row-bytes": ("tile_row_bytes", 4),
            "row-address": ("tile_row_address", 0x2016),
            "row-value-width": ("tile_row_value", 0x10000),
            "collision": ("map_collision", 2),
        }
        for name, (field, value) in invalid_cases.items():
            invalid = root / f"v5-invalid-{name}.csv"
            row = dict(bg1)
            row[field] = value
            write_v5(invalid, [row])
            run(invalid, "--allowed", "bg_cell", succeeds=False)

        non_bg_fields = root / "v5-non-bg-fields.csv"
        cpu_with_bg = {
            "cycle": 7,
            "event": "cpu",
            "physical_pc": 0x12345,
            "cs": 0x1234,
            "ip": 5,
            "bg_layer": 1,
        }
        write_v5(non_bg_fields, [cpu_with_bg])
        run(non_bg_fields, "--allowed", "cpu", succeeds=False)

    print("PASS structured trace verifier v1/v2/v3/v4/v5 compatibility")


if __name__ == "__main__":
    main()
