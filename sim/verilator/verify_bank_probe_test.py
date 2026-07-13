#!/usr/bin/env python3
"""Focused negative tests for the generated bank-probe verifier."""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path

from verify_bank_probe import EXPECTED, verify
from verify_trace import FIELDS_V5


def bank_row(
    cycle: int,
    address: int,
    value: int,
    instruction_id: int,
    origin_pc: int,
) -> dict[str, object]:
    row: dict[str, object] = {field: "" for field in FIELDS_V5}
    row.update(
        {
            "cycle": cycle,
            "event": "bank",
            "address": address,
            "value": value,
            "instruction_id": instruction_id,
            "origin_pc": origin_pc,
            "origin_status": "exact",
        }
    )
    return row


def write_trace(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS_V5, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def must_fail(path: Path, rows: list[dict[str, object]], expected: str) -> None:
    write_trace(path, rows)
    try:
        verify(path)
    except ValueError as error:
        if expected not in str(error):
            raise AssertionError(f"expected {expected!r} in {error!r}") from error
    else:
        raise AssertionError(f"invalid trace passed: {path.name}")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="swansong-bank-probe-test-") as directory:
        root = Path(directory)
        rows = [
            bank_row(cycle, address, value, instruction_id, origin_pc)
            for cycle, (address, value, instruction_id, origin_pc) in enumerate(
                EXPECTED, start=100
            )
        ]

        valid = root / "valid.csv"
        write_trace(valid, rows)
        verify(valid)

        wrong_id = [dict(row) for row in rows]
        wrong_id[1]["instruction_id"] = 7
        must_fail(root / "wrong-id.csv", wrong_id, "unexpected mapper-write sequence")

        wrong_pc = [dict(row) for row in rows]
        wrong_pc[2]["origin_pc"] = 0xF000C
        must_fail(root / "wrong-pc.csv", wrong_pc, "unexpected mapper-write sequence")

        missing_origin = [dict(row) for row in rows]
        missing_origin[0]["origin_status"] = "unattributed"
        must_fail(root / "missing-origin.csv", missing_origin, "origin_status is not exact")

        zero_id = [dict(row) for row in rows]
        zero_id[0]["instruction_id"] = 0
        must_fail(root / "zero-id.csv", zero_id, "instruction_id must be nonzero")

        stray_metadata = [dict(row) for row in rows]
        stray_metadata[0]["initiator"] = "cpu"
        must_fail(root / "stray-metadata.csv", stray_metadata, "unexpected fields for bank")

        duplicate = [*rows, dict(rows[-1])]
        duplicate[-1]["cycle"] = int(rows[-1]["cycle"]) + 1
        must_fail(root / "duplicate.csv", duplicate, "unexpected mapper-write sequence")

        duplicate_cycle = [dict(row) for row in rows]
        duplicate_cycle[2]["cycle"] = duplicate_cycle[1]["cycle"]
        must_fail(
            root / "duplicate-cycle.csv", duplicate_cycle, "does not follow cycle"
        )

    print("PASS generated bank-probe verifier")


if __name__ == "__main__":
    main()
