#!/usr/bin/env python3
"""Focused positive and mutation tests for the paired 4bpp probe verifier."""

from __future__ import annotations

import argparse
import csv
import json
import tempfile
from copy import deepcopy
from pathlib import Path

from verify_4bpp_probe import (
    MAP_ADDRESSES,
    PACKED,
    PATTERN_OFFSET,
    PATTERN_PHYSICAL,
    PLANAR,
    PIXELS,
    PROVENANCE_FIELDS,
    ROM_NAMES,
    TILE_ADDRESS,
    TraceEvidence,
    decode_tile,
    expected_frame,
    read_csv,
    read_trace,
    selected_cells,
    verify_cell_semantics,
    verify_cell_trace_links,
    verify_frame,
    verify_gdma,
    verify_glyph_contact,
    verify_glyph_rows,
    verify_manifest,
    verify_known_vectors,
    verify_provenance,
    verify_rom,
    verify_root,
)
from report_glyphs import OUTPUT_FIELDS as GLYPH_FIELDS
from verify_trace import FIELDS_V5


REPO = Path(__file__).resolve().parents[2]
DEFAULT_ARTIFACTS = REPO / "build/sim/4bpp-probe"
TEST_TILE_BYTES = {
    PLANAR: bytes.fromhex(
        "aa661e0155667880cc3c0300cc3cfc03"
        "ab661efeaaccf0ff01aa661eff55330f"
    ),
    PACKED: bytes.fromhex(
        "12345678876543211122334455667788"
        "9abcdef1fedcba982468ace113579bdf"
    ),
}


def must_fail(function, *args, contains: str | None = None) -> None:
    try:
        function(*args)
    except ValueError as error:
        if contains is not None and contains not in str(error):
            raise AssertionError(f"expected {contains!r} in {str(error)!r}") from error
        return
    raise AssertionError(f"mutation passed {function.__name__}")


def mem_row(**values: object) -> dict[str, str]:
    row = {field: "" for field in FIELDS_V5}
    row.update({field: str(value) for field, value in values.items()})
    return row


def gdma_rows(variant: str) -> list[tuple[int, dict[str, str]]]:
    payload = TEST_TILE_BYTES[variant]
    rows: list[tuple[int, dict[str, str]]] = []
    cycle = 100
    line = 2
    for word in range(16):
        value = int.from_bytes(payload[word * 2 : word * 2 + 2], "little")
        rows.append(
            (
                line,
                mem_row(
                    cycle=cycle,
                    event="mem",
                    address=PATTERN_PHYSICAL + word * 2,
                    value=value,
                    initiator="gdma",
                    access="read",
                    byte_enable=3,
                    space="cart_rom_linear",
                    mapped_offset=PATTERN_OFFSET + word * 2,
                    origin_status="not_applicable",
                ),
            )
        )
        rows.append(
            (
                line + 1,
                mem_row(
                    cycle=cycle + 1,
                    event="mem",
                    address=TILE_ADDRESS + word * 2,
                    value=value,
                    initiator="gdma",
                    access="write",
                    byte_enable=3,
                    space="iram",
                    mapped_offset=TILE_ADDRESS + word * 2,
                    origin_status="not_applicable",
                ),
            )
        )
        cycle += 2
        line += 2
    return rows


def mutate_provenance(
    source: Path, destination: Path, cycle: str, address: str
) -> None:
    rows = read_csv(source, PROVENANCE_FIELDS, "test provenance")
    matches = [
        row
        for row in rows
        if row["cycle"] == cycle
        and row["role"] == "screen1_tile"
        and row["address"] == address
    ]
    if len(matches) != 1:
        raise AssertionError("test could not identify selected provenance row")
    matches[0]["source_summary"] = "unknown"
    write_provenance(destination, rows)


def write_provenance(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=PROVENANCE_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def run(artifacts: Path) -> None:
    if not artifacts.is_dir():
        raise SystemExit(
            f"4bpp verifier test requires captures first: {artifacts}"
        )

    # The positive test is deliberately the real paired artifact contract.
    verify_known_vectors()
    for variant in (PLANAR, PACKED):
        if decode_tile(TEST_TILE_BYTES[variant], variant) != PIXELS:
            raise AssertionError(f"{variant} literal test vector does not decode to PIXELS")
    verify_root(artifacts)

    for variant in (PLANAR, PACKED):
        rows = gdma_rows(variant)
        verify_gdma(rows, variant)

        wrong_value = deepcopy(rows)
        wrong_value[0][1]["value"] = str(int(wrong_value[0][1]["value"]) ^ 1)
        must_fail(verify_gdma, wrong_value, variant, contains="GDMA read word 0 mismatch")

        wrong_offset = deepcopy(rows)
        wrong_offset[0][1]["mapped_offset"] = str(PATTERN_OFFSET + 2)
        must_fail(verify_gdma, wrong_offset, variant, contains="GDMA read word 0 mismatch")

        reordered = deepcopy(rows)
        reordered[1], reordered[2] = reordered[2], reordered[1]
        must_fail(verify_gdma, reordered, variant, contains="GDMA write word 0 mismatch")

        variant_root = artifacts / variant
        cells, wanted_lines = selected_cells(variant_root / "bg-cells.csv")
        trace = read_trace(variant_root / "events.csv", wanted_lines)
        words = verify_gdma(trace.gdma, variant)
        verify_cell_semantics(cells, variant, words)
        verify_cell_trace_links(cells, trace)

        wrong_lane = deepcopy(cells)
        wrong_lane[0]["row_b3_source_offset"] = str(PATTERN_OFFSET)
        must_fail(
            verify_cell_semantics,
            wrong_lane,
            variant,
            words,
            contains="row_b3_source_offset",
        )

        wrong_collision = deepcopy(cells)
        wrong_collision[0]["tile_row_collision"] = "1"
        must_fail(
            verify_cell_semantics,
            wrong_collision,
            variant,
            words,
            contains="tile_row_collision",
        )

        wrong_map_owner = deepcopy(cells)
        wrong_map_owner[0]["map_hi_instruction_id"] = str(
            int(wrong_map_owner[0]["map_hi_instruction_id"]) + 1
        )
        must_fail(
            verify_cell_semantics,
            wrong_map_owner,
            variant,
            words,
            contains="map_hi_instruction_id",
        )

        duplicate_identity = deepcopy(cells)
        duplicate_identity[1]["line"] = duplicate_identity[0]["line"]
        duplicate_identity[1]["cycle"] = duplicate_identity[0]["cycle"]
        must_fail(
            verify_cell_semantics,
            duplicate_identity,
            variant,
            words,
            contains="identities are not unique",
        )

        must_fail(
            verify_cell_semantics,
            deepcopy(cells[:-1]),
            variant,
            words,
            contains="expected 64 selected rows",
        )

        broken_occurrences = deepcopy(cells)
        placement_cells = sorted(
            (cell for cell in broken_occurrences if int(cell["map_address"]) == MAP_ADDRESSES[0]),
            key=lambda cell: int(cell["cycle"]),
        )
        placement_cells[7]["cycle"], placement_cells[8]["cycle"] = (
            placement_cells[8]["cycle"],
            placement_cells[7]["cycle"],
        )
        must_fail(
            verify_cell_semantics,
            broken_occurrences,
            variant,
            words,
            contains="not exactly two complete occurrences",
        )

        same_rows = sorted(
            (
                cell
                for cell in cells
                if int(cell["map_address"]) == MAP_ADDRESSES[0]
                and int(cell["tile_row"]) == 0
            ),
            key=lambda cell: int(cell["cycle"]),
        )
        prior_raw_group = deepcopy(cells)
        target = next(cell for cell in prior_raw_group if cell["line"] == same_rows[1]["line"])
        for prefix in ("map", "tile0", "tile1"):
            target[f"{prefix}_raw_line"] = same_rows[0][f"{prefix}_raw_line"]
            target[f"{prefix}_raw_cycle"] = same_rows[0][f"{prefix}_raw_cycle"]
        must_fail(
            verify_cell_semantics,
            prior_raw_group,
            variant,
            words,
            contains="raw group is not the adjacent measured fetch",
        )

        wrong_atomic = deepcopy(trace.lines)
        atomic_line = int(cells[0]["line"])
        wrong_atomic[atomic_line]["packed"] = "0" if variant == PACKED else "1"
        must_fail(
            verify_cell_trace_links,
            cells,
            TraceEvidence(
                gdma=trace.gdma,
                lines=wrong_atomic,
                selected_bg_cells=trace.selected_bg_cells,
                last_cycle=trace.last_cycle,
            ),
            contains="packed",
        )

        duplicate_trace_occurrence = deepcopy(trace.selected_bg_cells)
        duplicate_trace_occurrence[-1] = deepcopy(duplicate_trace_occurrence[0])
        must_fail(
            verify_cell_trace_links,
            cells,
            TraceEvidence(
                gdma=trace.gdma,
                lines=trace.lines,
                selected_bg_cells=duplicate_trace_occurrence,
                last_cycle=trace.last_cycle,
            ),
            contains="not one-to-one",
        )

        glyphs = read_csv(variant_root / "glyph-epochs.csv", GLYPH_FIELDS, "test glyphs")
        verify_glyph_rows(glyphs, variant, words)
        wrong_glyph = deepcopy(glyphs)
        sourced = next(row for row in wrong_glyph if row["row_source_ranges"])
        sourced["bitmap_fingerprint"] = "0" * 64
        must_fail(
            verify_glyph_rows,
            wrong_glyph,
            variant,
            words,
            contains="bitmap_fingerprint",
        )

    with tempfile.TemporaryDirectory(prefix="swansong-4bpp-verifier-") as directory:
        root = Path(directory)
        for index in (0, 1):
            frame = root / f"frame-{index}.rgb"
            frame.write_bytes(expected_frame(index))
            verify_frame(frame, index)
            damaged = bytearray(frame.read_bytes())
            damaged[((64 * 224 + 80) * 3)] ^= 1
            frame.write_bytes(damaged)
            must_fail(verify_frame, frame, index, contains="pixel mismatch")

        contacts = [
            verify_glyph_contact(artifacts / variant / "glyph-contact.png")
            for variant in (PLANAR, PACKED)
        ]
        if contacts[0] != contacts[1]:
            raise AssertionError("planar/packed contact sheets differ")
        must_fail(
            verify_glyph_contact,
            root / "missing-contact.png",
            contains="missing glyph contact sheet",
        )
        corrupt_contact = root / "glyph-contact.png"
        damaged_contact = bytearray(contacts[0])
        damaged_contact[-1] ^= 1
        corrupt_contact.write_bytes(damaged_contact)
        must_fail(
            verify_glyph_contact,
            corrupt_contact,
            contains="hash/format mismatch",
        )

        for variant in (PLANAR, PACKED):
            original = artifacts / "roms" / ROM_NAMES[variant]
            copied = root / ROM_NAMES[variant]
            copied.write_bytes(original.read_bytes())
            verify_rom(copied, variant)
            damaged = bytearray(copied.read_bytes())
            damaged[PATTERN_OFFSET] ^= 1
            copied.write_bytes(damaged)
            must_fail(verify_rom, copied, variant, contains="size/hash mismatch")

        variant = PLANAR
        original_trace = artifacts / variant / "events.csv"
        rom = (artifacts / "roms" / ROM_NAMES[variant]).read_bytes()
        original_manifest = json.loads(
            Path(f"{original_trace}.manifest.json").read_text(encoding="utf-8")
        )

        def manifest_mutation(
            name: str,
            field: str | None,
            value: object,
            expected: str,
            *,
            damage_trace: bool = False,
        ) -> None:
            trace_dir = root / name / variant
            trace_dir.mkdir(parents=True)
            trace = trace_dir / "events.csv"
            if damage_trace:
                trace_bytes = bytearray(original_trace.read_bytes())
                trace_bytes[-2] ^= 1
                trace.write_bytes(trace_bytes)
            else:
                trace.symlink_to(original_trace)
            manifest = deepcopy(original_manifest)
            if field is not None:
                manifest[field] = value
            Path(f"{trace}.manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            must_fail(verify_manifest, trace, rom, variant, contains=expected)

        manifest_mutation(
            "manifest-completeness",
            "complete_memory_history",
            False,
            "complete_memory_history mismatch",
        )
        manifest_mutation(
            "manifest-size", "trace_size_bytes", 1, "trace_size_bytes mismatch"
        )
        manifest_mutation(
            "manifest-trace-fnv", "trace_fnv1a64", "0" * 16, "trace_fnv1a64 mismatch"
        )
        manifest_mutation(
            "manifest-rom-fnv", "rom_fnv1a64", "0" * 16, "rom_fnv1a64 mismatch"
        )
        manifest_mutation(
            "trace-bytes", None, None, "trace integrity mismatch", damage_trace=True
        )

        cells, _ = selected_cells(artifacts / PLANAR / "bg-cells.csv")
        first = cells[0]
        changed_provenance = root / "provenance.csv"
        mutate_provenance(
            artifacts / PLANAR / "provenance.csv",
            changed_provenance,
            first["tile0_raw_cycle"],
            first["tile0_raw_address"],
        )
        must_fail(
            verify_provenance,
            changed_provenance,
            cells,
            contains="source_summary",
        )

        provenance_rows = read_csv(
            artifacts / PLANAR / "provenance.csv",
            PROVENANCE_FIELDS,
            "test provenance",
        )
        duplicate_key = deepcopy(provenance_rows)
        duplicate_key[-1] = deepcopy(duplicate_key[0])
        duplicate_provenance = root / "provenance-duplicate.csv"
        write_provenance(duplicate_provenance, duplicate_key)
        must_fail(
            verify_provenance,
            duplicate_provenance,
            cells,
            contains="duplicate (cycle, role, address) keys",
        )

        omitted_provenance = root / "provenance-omitted.csv"
        write_provenance(omitted_provenance, provenance_rows[:-1])
        must_fail(
            verify_provenance,
            omitted_provenance,
            cells,
            contains="row count mismatch",
        )

    print(
        "PASS 4bpp verifier mutations rom,manifest-trace-bytes-size-fnv-rom-fnv,"
        "gdma,known-answer-vectors,map-owner,atomic-occurrence,adjacent-raw-group,"
        "trace-link,provenance-count-and-keys,glyph,glyph-contact,frame"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_ARTIFACTS,
        help="paired 4bpp artifact root produced by the runtime probe",
    )
    args = parser.parse_args()
    run(args.root)


if __name__ == "__main__":
    main()
