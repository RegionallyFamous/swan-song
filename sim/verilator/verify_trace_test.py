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

SPRITE_FIELDS = [
    "sprite_table_address", "sprite_table_value", "sprite_table_collision",
    "sprite_line_y", "sprite_line_slot", "sprite_table_generation",
    "sprite_line_epoch",
]

V6_FIELDS = [*V5_FIELDS, *SPRITE_FIELDS]


def write_v5(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=V5_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_v6(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=V6_FIELDS, lineterminator="\n")
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

        pc_union = root / "pc-union.csv"
        pc_union.write_text(
            "cycle,event,physical_pc,cs,ip,address,value\n"
            "1,cpu,256,16,0,,\n"
            "2,cpu,983040,61440,0,,\n",
            encoding="utf-8",
        )
        run(pc_union, "--pc-range", "0x100-0x1ff,0xf0000-0xfffff")
        run(pc_union, "--pc-range", "0x100-0x1ff", succeeds=False)

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
        origin_union = root / "origin-union.csv"
        origin_union.write_text(
            "cycle,event,physical_pc,cs,ip,address,value,role,initiator,access,"
            "byte_enable,space,mapped_offset,instruction_id,origin_pc,origin_status\n"
            "3,mem,,,,16384,4660,,cpu,write,3,iram,16384,1,256,exact\n"
            "4,mem,,,,16386,22136,,cpu,write,3,iram,16386,2,983040,exact\n",
            encoding="utf-8",
        )
        run(origin_union, "--origin-pc", "0x100-0x1ff,0xf0000-0xfffff")
        run(origin_union, "--origin-pc", "0x100-0x1ff", succeeds=False)
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

        for schema, field_count in ((1, 7), (2, 8), (3, 16), (4, 18)):
            legacy_bank = root / f"v{schema}-bank.csv"
            with legacy_bank.open("w", newline="", encoding="utf-8") as output:
                writer = csv.DictWriter(
                    output, fieldnames=V5_FIELDS[:field_count], lineterminator="\n"
                )
                writer.writeheader()
                writer.writerow(
                    {"cycle": 6, "event": "bank", "address": 0xC0, "value": 0x12}
                )
            run(legacy_bank, "--allowed", "bank", "--require", "bank")

        bank: dict[str, object] = {
            "cycle": 6,
            "event": "bank",
            "address": 0xC0,
            "value": 0x12,
            "instruction_id": 42,
            "origin_pc": 0xF0010,
            "origin_status": "exact",
        }
        alias_bank = dict(bank)
        alias_bank.update({"cycle": 7, "address": 0xD0, "value": 0x03})
        high_bank = dict(bank)
        high_bank.update({"cycle": 8, "address": 0xD5, "value": 0x02})
        flash_bank = dict(bank)
        flash_bank.update({"cycle": 9, "address": 0xCE, "value": 0x01})
        v5_bank = root / "v5-bank.csv"
        write_v5(v5_bank, [bank, alias_bank, high_bank, flash_bank])
        run(
            v5_bank,
            "--allowed",
            "bank",
            "--require",
            "bank",
            "--require-bank-addresses",
            "0xc0,0xce,0xd0,0xd5",
        )
        invalid_bank_port = root / "v5-invalid-bank-port.csv"
        invalid_port_row = dict(bank)
        invalid_port_row["address"] = 0xCD
        write_v5(invalid_bank_port, [invalid_port_row])
        run(invalid_bank_port, "--allowed", "bank", succeeds=False)
        invalid_bank_cases: dict[str, tuple[str, object]] = {
            "instruction": ("instruction_id", ""),
            "zero-instruction": ("instruction_id", 0),
            "origin-pc": ("origin_pc", 0x100000),
            "origin-status": ("origin_status", "not_applicable"),
            "memory-field": ("initiator", "cpu"),
        }
        for name, (field, value) in invalid_bank_cases.items():
            invalid_bank = root / f"v5-invalid-bank-{name}.csv"
            row = dict(bank)
            row[field] = value
            write_v5(invalid_bank, [row])
            run(invalid_bank, "--allowed", "bank", succeeds=False)

        cpu_read: dict[str, object] = {
            "cycle": 7,
            "event": "mem",
            "address": 0x100,
            "value": 0,
            "initiator": "cpu",
            "access": "read",
            "byte_enable": 0,
            "space": "iram",
            "mapped_offset": 0x100,
            "origin_status": "unattributed",
        }
        v5_cpu_read = root / "v5-cpu-read.csv"
        write_v5(v5_cpu_read, [cpu_read])
        run(v5_cpu_read, "--allowed", "mem", "--require", "mem")

        flash_write = dict(cpu_read)
        flash_write.update({
            "cycle": 8,
            "address": 0x10020,
            "value": 0xA5,
            "access": "write",
            "byte_enable": 1,
            "space": "cart_flash",
            "mapped_offset": 0x30020,
            "instruction_id": 43,
            "origin_pc": 0xF0020,
            "origin_status": "exact",
        })
        v5_flash_write = root / "v5-flash-write.csv"
        write_v5(v5_flash_write, [flash_write])
        run(
            v5_flash_write,
            "--allowed",
            "mem",
            "--require",
            "mem",
            "--mem-space",
            "cart_flash",
        )

        stale_cpu_read = root / "v5-stale-cpu-read-mask.csv"
        stale_row = dict(cpu_read)
        stale_row["byte_enable"] = 1
        write_v5(stale_cpu_read, [stale_row])
        run(stale_cpu_read, "--allowed", "mem", succeeds=False)

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

        sprite2: dict[str, object] = {
            "cycle": 8,
            "event": "sprite_row",
            "tile_index": 1,
            "palette": 8,
            "hflip": 0,
            "vflip": 0,
            "bpp": 2,
            "packed": 0,
            "tile_row": 2,
            "tile_row_address": 0x2014,
            "tile_row_bytes": 2,
            "tile_row_value": 0x3412,
            "tile_row_collision": 1,
            "sprite_table_address": 0x1000,
            "sprite_table_value": 0x50400001,
            "sprite_table_collision": 0,
            "sprite_line_y": 66,
            "sprite_line_slot": 3,
            "sprite_table_generation": 7,
            "sprite_line_epoch": 11,
        }
        sprite4: dict[str, object] = {
            "cycle": 9,
            "event": "sprite_row",
            "tile_index": 2,
            "palette": 9,
            "hflip": 0,
            "vflip": 1,
            "bpp": 4,
            "packed": 1,
            "tile_row": 3,
            "tile_row_address": 0x404C,
            "tile_row_bytes": 4,
            "tile_row_value": 0x89ABCDEF,
            "tile_row_collision": 0,
            "sprite_table_address": 0x1004,
            "sprite_table_value": 0x60408202,
            "sprite_table_collision": 1,
            "sprite_line_y": 68,
            "sprite_line_slot": 4,
            "sprite_table_generation": 0xFFFFFFFF,
            "sprite_line_epoch": 0xFFFFFFFF,
        }
        v6 = root / "v6.csv"
        write_v6(v6, [sprite2, sprite4])
        assert v6.read_text(encoding="utf-8").splitlines()[0] == ",".join(V6_FIELDS)
        run(v6, "--allowed", "sprite_row", "--require", "sprite_row")

        v6_mixed = root / "v6-mixed.csv"
        v6_cpu = {
            "cycle": 5,
            "event": "cpu",
            "physical_pc": 0x12345,
            "cs": 0x1234,
            "ip": 5,
        }
        write_v6(v6_mixed, [v6_cpu, bg1, sprite2])
        run(
            v6_mixed,
            "--allowed",
            "cpu,bg_cell,sprite_row",
            "--require",
            "cpu,bg_cell,sprite_row",
        )
        run(v6, "--allowed", "bg_cell", succeeds=False)

        legacy_sprite = {
            field: value for field, value in sprite2.items() if field not in SPRITE_FIELDS
        }
        v5_sprite = root / "v5-sprite-row.csv"
        write_v5(v5_sprite, [legacy_sprite])
        run(v5_sprite, "--allowed", "sprite_row", succeeds=False)
        run(v5, "--require", "sprite_row", succeeds=False)

        for field in SPRITE_FIELDS:
            missing = root / f"v6-sprite-missing-{field}.csv"
            row = dict(sprite2)
            row[field] = ""
            write_v6(missing, [row])
            run(missing, "--allowed", "sprite_row", succeeds=False)

        invalid_sprite_cases: dict[str, tuple[str, object]] = {
            "table-alignment": ("sprite_table_address", 0x1002),
            "table-value-width": ("sprite_table_value", 0x100000000),
            "table-collision": ("sprite_table_collision", 2),
            "table-generation-width": ("sprite_table_generation", 0x100000000),
            "line-epoch-width": ("sprite_line_epoch", 0x100000000),
            "line-y": ("sprite_line_y", 256),
            "line-slot": ("sprite_line_slot", 32),
            "tile-index": ("tile_index", 2),
            "palette": ("palette", 9),
            "hflip": ("hflip", 1),
            "vflip": ("vflip", 1),
            "bpp": ("bpp", 3),
            "packed": ("packed", 2),
            "tile-row": ("tile_row", 3),
            "row-bytes": ("tile_row_bytes", 4),
            "row-address": ("tile_row_address", 0x2016),
            "row-value-width": ("tile_row_value", 0x10000),
            "row-collision": ("tile_row_collision", 2),
            "inactive-line": ("sprite_line_y", 72),
            "background-field": ("bg_layer", 1),
            "memory-field": ("initiator", "cpu"),
        }
        for name, (field, value) in invalid_sprite_cases.items():
            invalid = root / f"v6-invalid-sprite-{name}.csv"
            row = dict(sprite2)
            row[field] = value
            write_v6(invalid, [row])
            run(invalid, "--allowed", "sprite_row", succeeds=False)

        for event_name, valid_row in (("cpu", v6_cpu), ("bg_cell", bg1)):
            leaked = root / f"v6-{event_name}-sprite-field.csv"
            row = dict(valid_row)
            row["sprite_line_epoch"] = 11
            write_v6(leaked, [row])
            run(leaked, "--allowed", event_name, succeeds=False)

    print("PASS structured trace verifier v1/v2/v3/v4/v5/v6 compatibility")


if __name__ == "__main__":
    main()
