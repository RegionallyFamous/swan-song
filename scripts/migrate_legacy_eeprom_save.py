#!/usr/bin/env python3
"""Migrate a padded legacy Pocket type-10/type-50 save to its exact layout."""

from __future__ import annotations

import argparse
import pathlib
from dataclasses import dataclass

from migrate_type01_save import (
    MIN_ROM_SIZE,
    ROM_CHECKSUM_SIZE,
    ROM_RAM_TYPE_OFFSET,
    _absolute,
    _atomic_create,
    _ensure_output_available,
    _read_regular_file,
    _sha256,
)


TYPE10 = 0x10
TYPE50 = 0x50
EXACT_EEPROM_SIZES = {TYPE10: 128, TYPE50: 1024}
LEGACY_EEPROM_SIZE = 2048
RTC_TRAILER_SIZE = 12
LEGACY_SAVE_SIZE = LEGACY_EEPROM_SIZE + RTC_TRAILER_SIZE


@dataclass(frozen=True)
class MigrationReport:
    rom: pathlib.Path
    legacy_save: pathlib.Path
    output: pathlib.Path
    ram_type: int
    payload_size: int
    output_size: int
    rom_sha256: str
    legacy_save_sha256: str
    payload_sha256: str
    discarded_padding_sha256: str
    rtc_sha256: str
    output_sha256: str


def _validate_rom(rom: bytes) -> tuple[int, int]:
    if len(rom) < MIN_ROM_SIZE:
        raise ValueError(
            f"ROM is too small for a WonderSwan cartridge image: "
            f"{len(rom)} < {MIN_ROM_SIZE} bytes"
        )

    ram_type = rom[ROM_RAM_TYPE_OFFSET]
    try:
        payload_size = EXACT_EEPROM_SIZES[ram_type]
    except KeyError as error:
        raise ValueError(
            "ROM footer save type must be legacy-padded external EEPROM "
            f"type 0x10 or 0x50, found 0x{ram_type:02x}"
        ) from error

    stored_checksum = int.from_bytes(rom[-ROM_CHECKSUM_SIZE:], "little")
    computed_checksum = sum(memoryview(rom)[:-ROM_CHECKSUM_SIZE]) & 0xFFFF
    if stored_checksum != computed_checksum:
        raise ValueError(
            "ROM footer checksum mismatch: "
            f"stored 0x{stored_checksum:04x}, computed 0x{computed_checksum:04x}"
        )
    return ram_type, payload_size


def _validate_legacy_save(save: bytes) -> None:
    if len(save) != LEGACY_SAVE_SIZE:
        raise ValueError(
            "legacy padded Pocket EEPROM save must be exactly "
            f"{LEGACY_SAVE_SIZE} bytes (2048-byte inherited EEPROM area plus "
            f"opaque 12-byte RTC), found {len(save)}"
        )


def migrate_legacy_eeprom_save(
    rom_path: pathlib.Path, legacy_save_path: pathlib.Path, output_path: pathlib.Path
) -> MigrationReport:
    rom_path = pathlib.Path(rom_path)
    legacy_save_path = pathlib.Path(legacy_save_path)
    output_path = pathlib.Path(output_path)
    sources = (rom_path, legacy_save_path)

    _ensure_output_available(output_path, sources)
    rom = _read_regular_file(rom_path, "ROM")
    legacy_save = _read_regular_file(legacy_save_path, "legacy save")
    ram_type, payload_size = _validate_rom(rom)
    _validate_legacy_save(legacy_save)

    payload = legacy_save[:payload_size]
    discarded_padding = legacy_save[payload_size:LEGACY_EEPROM_SIZE]
    rtc = legacy_save[LEGACY_EEPROM_SIZE:LEGACY_SAVE_SIZE]
    migrated = payload + rtc
    expected_size = payload_size + RTC_TRAILER_SIZE
    if len(migrated) != expected_size:
        raise AssertionError("internal migrated save size invariant failed")

    # Reuse the type-01 migrator's fsync plus atomic no-replace publisher.  It
    # fails closed on filesystems without an exclusive publication primitive.
    _atomic_create(output_path, migrated, sources)
    return MigrationReport(
        rom=_absolute(rom_path),
        legacy_save=_absolute(legacy_save_path),
        output=_absolute(output_path),
        ram_type=ram_type,
        payload_size=payload_size,
        output_size=expected_size,
        rom_sha256=_sha256(rom),
        legacy_save_sha256=_sha256(legacy_save),
        payload_sha256=_sha256(payload),
        discarded_padding_sha256=_sha256(discarded_padding),
        rtc_sha256=_sha256(rtc),
        output_sha256=_sha256(migrated),
    )


def format_report(report: MigrationReport) -> str:
    legacy_rtc_end = LEGACY_EEPROM_SIZE + RTC_TRAILER_SIZE
    output_rtc_end = report.payload_size + RTC_TRAILER_SIZE
    return "\n".join(
        (
            f"ROM: {report.rom}",
            f"ROM SHA-256: {report.rom_sha256}",
            f"EEPROM type: 0x{report.ram_type:02x}",
            f"Legacy save: {report.legacy_save}",
            f"Legacy save SHA-256: {report.legacy_save_sha256}",
            f"Layout: preserve EEPROM [0,{report.payload_size}); discard padding "
            f"[{report.payload_size},{LEGACY_EEPROM_SIZE}); relocate RTC "
            f"[{LEGACY_EEPROM_SIZE},{legacy_rtc_end}) -> "
            f"[{report.payload_size},{output_rtc_end})",
            f"Payload SHA-256: {report.payload_sha256}",
            f"Discarded padding SHA-256: {report.discarded_padding_sha256}",
            "RTC: opaque 12-byte copy; byte order and sentinel unchecked",
            f"RTC SHA-256: {report.rtc_sha256}",
            f"Output: {report.output}",
            f"Output size: {report.output_size} bytes",
            f"Output SHA-256: {report.output_sha256}",
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "rom", type=pathlib.Path, help="type-10 or type-50 WonderSwan ROM"
    )
    parser.add_argument(
        "legacy_save", type=pathlib.Path, help="exact 2,060-byte legacy Pocket save"
    )
    parser.add_argument(
        "output", type=pathlib.Path, help="new output path (must not already exist)"
    )
    args = parser.parse_args()

    try:
        report = migrate_legacy_eeprom_save(
            args.rom, args.legacy_save, args.output
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(format_report(report))


if __name__ == "__main__":
    main()
