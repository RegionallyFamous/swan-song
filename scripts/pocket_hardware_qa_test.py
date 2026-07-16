#!/usr/bin/env python3
"""Offline tests for the physical-evidence schema; no hardware pass is claimed."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import pathlib
import re
import shutil
import struct
import sys
import tempfile
import unittest
import zlib
from unittest import mock

from build_chip32 import chip32_image
import pocket_hardware_qa as hardware_qa
import stage_pocket_sd as staging
from pocket_hardware_qa import (
    CASE_SPECS,
    OFFICIAL_FIRMWARE_MD5,
    OFFICIAL_FIRMWARE_VERSION,
    REVERSE,
    generate_manifest,
    verify_manifest,
)
from package_core import validate_hardware_qa_binding
from package_core_test import PackageCoreTest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sim" / "verilator"))
import generate_non_power_two_probe as compact_probe  # noqa: E402
import generate_sram_persistence_probes as sram_persistence_probe  # noqa: E402
import verify_sram_persistence_save as sram_persistence_save  # noqa: E402


VALID_MP4 = base64.b64decode(
    "AAAAIGZ0eXBpc29tAAACAGlzb21pc28yYXZjMW1wNDEAAAMVbW9vdgAAAGxtdmhk"
    "AAAAAAAAAAAAAAAAAAAD6AAAACgAAQAAAQAAAAAAAAAAAAAAAAEAAAAAAAAAAAAA"
    "AAAAAAABAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAgAAAj90cmFrAAAAXHRraGQAAAADAAAAAAAAAAAAAAABAAAAAAAAACgAAAAA"
    "AAAAAAAAAAAAAAAAAAEAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAABAAAAA"
    "ABAAAAAQAAAAAAAkZWR0cwAAABxlbHN0AAAAAAAAAAEAAAAoAAAAAAABAAAAAAG3"
    "bWRpYQAAACBtZGhkAAAAAAAAAAAAAAAAAAAyAAAAAgBVxAAAAAAALWhkbHIAAAAA"
    "AAAAAHZpZGUAAAAAAAAAAAAAAABWaWRlb0hhbmRsZXIAAAABYm1pbmYAAAAUdm1o"
    "ZAAAAAEAAAAAAAAAAAAAACRkaW5mAAAAHGRyZWYAAAAAAAAAAQAAAAx1cmwgAAAA"
    "AQAAASJzdGJsAAAAvnN0c2QAAAAAAAAAAQAAAK5hdmMxAAAAAAAAAAEAAAAAAAAA"
    "AAAAAAAAAAAAABAAEABIAAAASAAAAAAAAAABFUxhdmM2Mi4yOC4xMDEgbGlieDI2"
    "NAAAAAAAAAAAAAAAGP//AAAANGF2Y0MBZAAK/+EAF2dkAAqs2V7ARAAAAwAEAAAD"
    "AMg8SJZYAQAGaOvjyyLA/fj4AAAAABBwYXNwAAAAAQAAAAEAAAAUYnRydAAAAAAA"
    "AinoAAAAAAAAABhzdHRzAAAAAAAAAAEAAAABAAACAAAAABxzdHNjAAAAAAAAAAEA"
    "AAABAAAAAQAAAAEAAAAUc3RzegAAAAAAAALFAAAAAQAAABRzdGNvAAAAAAAAAAEA"
    "AANFAAAAYnVkdGEAAABabWV0YQAAAAAAAAAhaGRscgAAAAAAAAAAbWRpcmFwcGwA"
    "AAAAAAAAAAAAAAAtaWxzdAAAACWpdG9vAAAAHWRhdGEAAAABAAAAAExhdmY2Mi4x"
    "Mi4xMDEAAAAIZnJlZQAAAs1tZGF0AAACrgYF//+q3EXpvebZSLeWLNgg2SPu73gy"
    "NjQgLSBjb3JlIDE2NSByMzIyMiBiMzU2MDVhIC0gSC4yNjQvTVBFRy00IEFWQyBj"
    "b2RlYyAtIENvcHlsZWZ0IDIwMDMtMjAyNSAtIGh0dHA6Ly93d3cudmlkZW9sYW4u"
    "b3JnL3gyNjQuaHRtbCAtIG9wdGlvbnM6IGNhYmFjPTEgcmVmPTMgZGVibG9jaz0x"
    "OjA6MCBhbmFseXNlPTB4MzoweDExMyBtZT1oZXggc3VibWU9NyBwc3k9MSBwc3lf"
    "cmQ9MS4wMDowLjAwIG1peGVkX3JlZj0xIG1lX3JhbmdlPTE2IGNocm9tYV9tZT0x"
    "IHRyZWxsaXM9MSA4eDhkY3Q9MSBjcW09MCBkZWFkem9uZT0yMSwxMSBmYXN0X3Bz"
    "a2lwPTEgY2hyb21hX3FwX29mZnNldD0tMiB0aHJlYWRzPTEgbG9va2FoZWFkX3Ro"
    "cmVhZHM9MSBzbGljZWRfdGhyZWFkcz0wIG5yPTAgZGVjaW1hdGU9MSBpbnRlcmxh"
    "Y2VkPTAgYmx1cmF5X2NvbXBhdD0wIGNvbnN0cmFpbmVkX2ludHJhPTAgYmZyYW1l"
    "cz0zIGJfcHlyYW1pZD0yIGJfYWRhcHQ9MSBiX2JpYXM9MCBkaXJlY3Q9MSB3ZWln"
    "aHRiPTEgb3Blbl9nb3A9MCB3ZWlnaHRwPTIga2V5aW50PTI1MCBrZXlpbnRfbWlu"
    "PTI1IHNjZW5lY3V0PTQwIGludHJhX3JlZnJlc2g9MCByY19sb29rYWhlYWQ9NDAg"
    "cmM9Y3JmIG1idHJlZT0xIGNyZj0yMy4wIHFjb21wPTAuNjAgcXBtaW49MCBxcG1h"
    "eD02OSBxcHN0ZXA9NCBpcF9yYXRpbz0xLjQwIGFxPTE6MS4wMACAAAAAD2WIhAAr"
    "//72c3wKa22xgQ=="
)


def valid_png(width: int, height: int) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    rows = b"".join(b"\0" + bytes(width * 3) for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


def valid_wav() -> bytes:
    samples = bytes(32)
    fmt = struct.pack("<HHIIHH", 1, 1, 8_000, 16_000, 2, 16)
    body = b"WAVEfmt " + struct.pack("<I", len(fmt)) + fmt
    body += b"data" + struct.pack("<I", len(samples)) + samples
    return b"RIFF" + struct.pack("<I", len(body)) + body


def compact_896k_rom() -> bytes:
    return compact_probe.image()


def synthetic_rom(
    *, color: bool, save_type: int, marker: int, rtc: bool = False,
    word_width: int = 16, owner_writable: bool = False,
) -> bytes:
    """Return a checksummed 64 KiB inventory fixture with exact footer type."""

    result = bytearray((marker,)) * (64 * 1024)
    footer = bytearray(16)
    footer[:5] = b"\xEA\x00\x00\x00\xF0"
    footer[7] = int(color)
    footer[8] = marker
    footer[9] = 0x81 if owner_writable else 0x01
    footer[10] = 0
    footer[11] = save_type
    footer[12] = 4 if word_width == 16 else 0
    footer[13] = int(rtc)
    result[-16:] = footer
    result[-2:] = (sum(result[:-2]) & 0xFFFF).to_bytes(2, "little")
    return bytes(result)


class PocketHardwareQATest(unittest.TestCase):
    def setUp(self) -> None:
        # Most schema and mutation tests exercise evidence ordering and
        # identity rules, not the host FFmpeg installation.  Keep those unit
        # tests hermetic; the focused decoder test below calls the real helper
        # with explicit subprocess results and still proves fail-closed media
        # handling.
        self.real_media_validator = hardware_qa._validate_decodable_media
        self.media_validator_patch = mock.patch.object(
            hardware_qa, "_validate_decodable_media", return_value=None
        )
        self.media_validator = self.media_validator_patch.start()
        self.addCleanup(self.media_validator_patch.stop)

        self.temporary = tempfile.TemporaryDirectory(prefix="swan-hardware-qa-test-")
        self.root = pathlib.Path(self.temporary.name)
        self.private = self.root / "private"
        self.private.mkdir()
        self.evidence = self.root / "evidence"
        self.evidence.mkdir()

        self.firmware = self.private / "pocket_firmware.bin"
        self.firmware.write_bytes(b"synthetic firmware identity fixture")
        self.synthetic_firmware_md5 = hashlib.md5(self.firmware.read_bytes()).hexdigest()
        self.firmware_identity_patch = mock.patch.object(
            hardware_qa, "OFFICIAL_FIRMWARE_MD5", self.synthetic_firmware_md5
        )
        self.firmware_identity_patch.start()
        self.addCleanup(self.firmware_identity_patch.stop)
        (self.private / "pocket-id.txt").write_text("synthetic-pocket-unit-1", encoding="utf-8")
        (self.private / "dock-id.txt").write_text("synthetic-dock-unit-1", encoding="utf-8")

        self.installed_root = self.private / "sd"
        shutil.copytree(ROOT / "dist", self.installed_root)
        installed_core = self.installed_root / "Cores/RegionallyFamous.SwanSong"
        self.core_json = installed_core / "core.json"
        self.interact_json = installed_core / "interact.json"
        self.raw_rbf = self.private / "ap_core.rbf"
        self.raw_rbf.write_bytes(bytes(range(256)) * 256)
        self.installed = installed_core / "wonderswan.rev"
        self.installed.write_bytes(self.raw_rbf.read_bytes().translate(REVERSE))
        (installed_core / "chip32.bin").write_bytes(
            chip32_image(
                ROOT / "src/support/chip32.asm",
                ROOT / "src/support/chip32.bin.hex",
            )
        )
        (self.private / "horizontal.ws").write_bytes(
            synthetic_rom(
                color=False, save_type=0x01, marker=0x61, word_width=8
            )
        )
        (self.private / "vertical.wsc").write_bytes(
            synthetic_rom(
                color=True, save_type=0x20, marker=0x62, rtc=True,
                word_width=8,
            )
        )
        extra_save_roms = (
            ("sram02.ws", False, 0x02, 0x63, 16, False),
            ("sram03.ws", False, 0x03, 0x64, 16, False),
            ("sram04.ws", False, 0x04, 0x65, 8, True),
            ("sram05.ws", False, 0x05, 0x66, 16, True),
            ("eeprom10.wsc", True, 0x10, 0x67, 8, True),
            ("eeprom50.wsc", True, 0x50, 0x68, 16, True),
        )
        for filename, color, save_type, marker, word_width, owner_writable in extra_save_roms:
            (self.private / filename).write_bytes(
                synthetic_rom(
                    color=color,
                    save_type=save_type,
                    marker=marker,
                    word_width=word_width,
                    owner_writable=owner_writable,
                )
            )
        (self.private / "sram03.ws").write_bytes(
            sram_persistence_probe.image(0x03, "ws")
        )
        (self.private / "compact-896k.wsc").write_bytes(compact_896k_rom())

        inventory = {
            "hardware_qa_inventory": {
                "magic": hardware_qa.INVENTORY_MAGIC,
                "run_id": "synthetic-unit-test",
                "created_at": "2026-07-13T12:00:00Z",
                "operator": {"name": "Schema unit test", "organization": "Offline fixture"},
                "firmware": {
                    "version": "2.6.0",
                    "update_path": str(self.firmware),
                    "expected_md5": self.synthetic_firmware_md5,
                },
                "pocket": {
                    "model": "Analogue Pocket",
                    "hardware_revision": "synthetic",
                    "device_id_path": str(self.private / "pocket-id.txt"),
                },
                "dock": {
                    "model": "Analogue Dock",
                    "hardware_revision": "synthetic",
                    "firmware_version": "not-reported",
                    "device_id_path": str(self.private / "dock-id.txt"),
                },
                "core": {
                    "installed_dist_path": str(self.installed_root),
                    "core_json_path": str(self.core_json),
                    "interact_json_path": str(self.interact_json),
                    "raw_rbf_path": str(self.raw_rbf),
                    "installed_bitstream_path": str(self.installed),
                },
                "open_ipl": {
                    "identity": hardware_qa.OPEN_IPL_IDENTITY,
                    "variants": list(hardware_qa.REQUIRED_OPEN_IPL_VARIANTS),
                },
                "roms": [
                    {
                        "id": "horizontal-sram", "title": "Synthetic horizontal",
                        "path": str(self.private / "horizontal.ws"), "system": "ws",
                        "native_orientation": "horizontal", "save_media": "sram", "rtc": False,
                    },
                    {
                        "id": "vertical-eeprom-rtc", "title": "Synthetic vertical",
                        "path": str(self.private / "vertical.wsc"), "system": "wsc",
                        "native_orientation": "vertical", "save_media": "eeprom", "rtc": True,
                    },
                    {
                        "id": "compact-896k", "title": "Synthetic 896 KiB compact",
                        "path": str(self.private / "compact-896k.wsc"), "system": "wsc",
                        "native_orientation": "horizontal", "save_media": "none", "rtc": False,
                    },
                    {
                        "id": "sram02", "title": "Synthetic type 02 SRAM",
                        "path": str(self.private / "sram02.ws"), "system": "ws",
                        "native_orientation": "horizontal", "save_media": "sram", "rtc": False,
                    },
                    {
                        "id": "sram03", "title": "Synthetic type 03 SRAM",
                        "path": str(self.private / "sram03.ws"), "system": "ws",
                        "native_orientation": "horizontal", "save_media": "sram", "rtc": False,
                    },
                    {
                        "id": "sram04", "title": "Synthetic type 04 SRAM",
                        "path": str(self.private / "sram04.ws"), "system": "ws",
                        "native_orientation": "horizontal", "save_media": "sram", "rtc": False,
                    },
                    {
                        "id": "sram05", "title": "Synthetic type 05 SRAM",
                        "path": str(self.private / "sram05.ws"), "system": "ws",
                        "native_orientation": "horizontal", "save_media": "sram", "rtc": False,
                    },
                    {
                        "id": "eeprom10", "title": "Synthetic type 10 EEPROM",
                        "path": str(self.private / "eeprom10.wsc"), "system": "wsc",
                        "native_orientation": "vertical", "save_media": "eeprom", "rtc": False,
                    },
                    {
                        "id": "eeprom50", "title": "Synthetic type 50 EEPROM",
                        "path": str(self.private / "eeprom50.wsc"), "system": "wsc",
                        "native_orientation": "vertical", "save_media": "eeprom", "rtc": False,
                    },
                ],
                "controllers": [
                    {"id": "pocket", "scope": "pocket", "device_type": "gamepad", "transport": "built_in", "model": "Built in", "firmware_version": "2.6.0", "mapping_mode": "APF type 1"},
                    {"id": "wired", "scope": "dock", "device_type": "gamepad", "transport": "usb", "model": "Synthetic wired", "firmware_version": "not-reported", "mapping_mode": "XInput"},
                    {"id": "wireless", "scope": "dock", "device_type": "gamepad", "transport": "bluetooth", "model": "Synthetic wireless", "firmware_version": "test", "mapping_mode": "XInput"},
                    {"id": "keyboard", "scope": "dock", "device_type": "keyboard", "transport": "usb", "model": "Synthetic keyboard", "firmware_version": "not-reported", "mapping_mode": "USB HID"},
                    {"id": "mouse", "scope": "dock", "device_type": "mouse", "transport": "usb", "model": "Synthetic mouse", "firmware_version": "not-reported", "mapping_mode": "USB HID"},
                ],
            }
        }
        self.inventory = self.root / "inventory.json"
        self.inventory.write_text(json.dumps(inventory), encoding="utf-8")
        self.manifest = self.evidence / "manifest.json"
        generate_manifest(self.inventory, self.manifest)
        self.generated_document = json.loads(self.manifest.read_text(encoding="utf-8"))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def artifact_bytes(kind: str) -> tuple[str, bytes]:
        if kind == "pocket_screenshot":
            return ".png", valid_png(224, 144)
        if kind == "photo":
            return ".png", valid_png(640, 480)
        if kind == "video":
            return ".mp4", VALID_MP4
        if kind == "audio":
            return ".wav", valid_wav()
        if kind == "save":
            return ".sav", b"synthetic save snapshot"
        if kind == "log":
            return ".txt", b"synthetic schema evidence; not a hardware observation\n"
        raise AssertionError(kind)

    def accepted_fixture(self) -> dict:
        """Create schema-complete synthetic bytes, never persisted as claimed QA."""
        document = copy.deepcopy(self.generated_document)
        body = document["hardware_qa"]
        roms = body["environment"]["roms"]
        controllers = body["environment"]["controllers"]

        def rom_selection(requirement: str) -> list[str]:
            if requirement == "compact_896k":
                return ["compact-896k"]
            if requirement == "auto_off_type03_probe":
                return ["sram03"]
            if requirement == "all_save_types":
                return [
                    next(item["id"] for item in roms if item["save_type"] == save_type)
                    for save_type in hardware_qa.SAVE_TYPE_PAYLOAD_BYTES
                ]
            if requirement in {"both_orientations", "save_pair", "mono_color", "two"}:
                return ["horizontal-sram", "vertical-eeprom-rtc"]
            if requirement in {"eeprom", "rtc", "vertical"}:
                return [next(item["id"] for item in roms if item["id"] == "vertical-eeprom-rtc")]
            return [next(item["id"] for item in roms if item["id"] == "horizontal-sram")]

        def controller_selection(requirement: str) -> list[str]:
            selections = {
                "pocket": ["pocket"],
                "dock_wired_gamepad": ["wired"],
                "dock_wireless_gamepad": ["wireless"],
                "dock_gamepads": ["wired", "wireless"],
                "pocket_and_dock": ["pocket", "wired"],
                "unsupported_devices": ["wired", "wireless", "keyboard", "mouse"],
            }
            return selections[requirement]
        artifacts = []
        by_case = {item["id"]: item for item in body["cases"]}
        counter = 0
        for spec in CASE_SPECS:
            case = by_case[spec.case_id]
            case.update({
                "status": "pass",
                "started_at": "2026-07-13T13:00:00Z",
                "completed_at": "2026-07-13T14:00:00Z",
                "rom_ids": rom_selection(spec.rom_requirement),
                "controller_ids": controller_selection(spec.controller_requirement),
                "notes": "Synthetic unit-test coverage only; not physical evidence.",
            })
            case["checks"] = {name: True for name in spec.checks}
            for need in spec.needs:
                snapshots: list[tuple[str, bytes]] | None = None
                if spec.case_id == "console_eeprom_lifecycle" and need.kinds == ("save",):
                    snapshots = []
                    for model, size in hardware_qa.CONSOLE_EEPROM_SNAPSHOT_SIZES.items():
                        for stage in hardware_qa.CONSOLE_EEPROM_SNAPSHOT_STAGES:
                            snapshots.append((
                                f"console-eeprom {model} {stage}", bytes([0x31]) * size
                            ))
                elif spec.case_id == "all_save_types_lifecycle" and need.kinds == ("save",):
                    snapshots = []
                    selected = [
                        next(item for item in roms if item["id"] == rom_id)
                        for rom_id in case["rom_ids"]
                    ]
                    for rom in selected:
                        save_type = rom["save_type"]
                        if save_type == 0:
                            continue
                        size = rom["save_payload_bytes"] + (12 if rom["rtc"] else 0)
                        for stage in hardware_qa.CARTRIDGE_SAVE_SNAPSHOT_STAGES:
                            fill = 0x31 if stage == "initialized" else 0xA7
                            snapshots.append((
                                f"cartridge-save type-{save_type:02x} {stage}",
                                bytes([fill]) * size,
                            ))
                elif (
                    spec.case_id == "auto_off_dirty_save_flush"
                    and need.kinds == ("save",)
                ):
                    snapshots = [
                        (
                            hardware_qa.AUTO_OFF_SAVE_SNAPSHOT_SHA256[0][0],
                            sram_persistence_save.expected_image(
                                0x03,
                                "ws",
                                sram_persistence_probe.GENERATION_1,
                                sram_persistence_probe.STATUS_INITIALIZED,
                            ),
                        ),
                        (
                            hardware_qa.AUTO_OFF_SAVE_SNAPSHOT_SHA256[1][0],
                            sram_persistence_save.expected_image(
                                0x03,
                                "ws",
                                sram_persistence_probe.GENERATION_2,
                                sram_persistence_probe.STATUS_PERSISTED_1_TO_2,
                            ),
                        ),
                        (
                            hardware_qa.AUTO_OFF_SAVE_SNAPSHOT_SHA256[2][0],
                            sram_persistence_save.expected_image(
                                0x03,
                                "ws",
                                sram_persistence_probe.GENERATION_1,
                                sram_persistence_probe.STATUS_PERSISTED_2_TO_1,
                            ),
                        ),
                    ]
                for snapshot_index in range(need.minimum):
                    kind = need.kinds[0]
                    label_override = None
                    if spec.case_id == "fresh_sd_startup":
                        if "log" in need.kinds:
                            label_override = (
                                hardware_qa.FRESH_SD_APF_BASELINE_LOG_LABEL
                                if snapshot_index == 0
                                else hardware_qa.FRESH_SD_DISTRIBUTION_LIFECYCLE_LOG_LABEL
                            )
                        elif snapshot_index == 0:
                            kind = "photo"
                            label_override = hardware_qa.FRESH_SD_BOUND_INPUT_LABEL
                        elif snapshot_index == 1:
                            kind = "photo"
                            label_override = hardware_qa.FRESH_SD_BOUND_INTERACT_LABEL
                    elif spec.case_id == "invalid_rom_negative" and "log" in need.kinds:
                        label_override = hardware_qa.CHIP32_POLL_GUARD_LOG_LABEL
                    elif (
                        spec.case_id == "settings_options_and_persistence"
                        and "log" in need.kinds
                    ):
                        label_override = hardware_qa.SETTINGS_APF_PATH_AUDIT_LOG_LABEL
                    elif spec.case_id == "auto_off_dirty_save_flush":
                        if "video" in need.kinds:
                            label_override = hardware_qa.AUTO_OFF_VIDEO_LABEL
                        elif "log" in need.kinds:
                            label_override = hardware_qa.AUTO_OFF_LOG_LABEL
                    counter += 1
                    artifact_id = f"artifact-{counter:04d}"
                    if snapshots is None:
                        suffix, contents = self.artifact_bytes(kind)
                        label = label_override or f"Synthetic {kind} for {spec.case_id}"
                    else:
                        suffix = (
                            ".sav"
                            if spec.case_id == "auto_off_dirty_save_flush"
                            else ".eeprom"
                        )
                        label, contents = snapshots[snapshot_index]
                    relative = pathlib.PurePosixPath("files") / f"{artifact_id}{suffix}"
                    path = self.evidence / relative
                    path.parent.mkdir(exist_ok=True)
                    path.write_bytes(contents)
                    artifacts.append({
                        "id": artifact_id, "kind": kind, "path": relative.as_posix(),
                        "label": label,
                        "captured_at": "2026-07-13T13:30:00Z",
                        "size": len(contents), "sha256": hashlib.sha256(contents).hexdigest(),
                    })
                    case["artifact_ids"].append(artifact_id)
        body["artifacts"] = artifacts
        body["attestation"] = {
            "physical_hardware_observed": True,
            "results_not_inferred_from_simulation": True,
            "evidence_reviewed": True,
            "reviewer": "Synthetic schema unit test",
            "reviewed_at": "2026-07-13T15:00:00Z",
        }
        return document

    def write_manifest(self, document: dict) -> None:
        self.manifest.write_text(json.dumps(document), encoding="utf-8")

    def test_generated_manifest_is_valid_pending_and_rejected_for_acceptance(self) -> None:
        summary = verify_manifest(self.manifest, self.inventory, require_pass=False)
        self.assertEqual(summary["cases"], len(CASE_SPECS))
        with self.assertRaisesRegex(ValueError, "not accepted.*pending"):
            verify_manifest(self.manifest, self.inventory)

    def test_media_validation_requires_one_decoded_frame(self) -> None:
        path = self.private / "truncated.mp4"
        path.write_bytes(VALID_MP4[: VALID_MP4.index(b"mdat") + 4])
        with mock.patch.object(hardware_qa.shutil, "which", return_value=None):
            with self.assertRaisesRegex(ValueError, "requires FFmpeg"):
                self.real_media_validator(path, "video", "test video")

        failed_decode = mock.Mock(returncode=1, stdout="", stderr="decode failed")
        with (
            mock.patch.object(
                hardware_qa.shutil, "which", return_value="/synthetic/ffmpeg"
            ),
            mock.patch.object(
                hardware_qa.subprocess, "run", return_value=failed_decode
            ),
        ):
            with self.assertRaisesRegex(ValueError, "not decodable.*decode failed"):
                self.real_media_validator(path, "video", "test video")

        zero_duration = mock.Mock(
            returncode=0,
            stdout="frame=1\nout_time_us=0\nprogress=end\n",
            stderr="",
        )
        with (
            mock.patch.object(
                hardware_qa.shutil, "which", return_value="/synthetic/ffmpeg"
            ),
            mock.patch.object(
                hardware_qa.subprocess, "run", return_value=zero_duration
            ),
        ):
            with self.assertRaisesRegex(ValueError, "no decoded media duration"):
                self.real_media_validator(path, "video", "test video")

        zero_frames = mock.Mock(
            returncode=0,
            stdout="frame=0\nout_time_us=1000\nprogress=end\n",
            stderr="",
        )
        with (
            mock.patch.object(
                hardware_qa.shutil, "which", return_value="/synthetic/ffmpeg"
            ),
            mock.patch.object(
                hardware_qa.subprocess, "run", return_value=zero_frames
            ),
        ):
            with self.assertRaisesRegex(ValueError, "no decoded video frame"):
                self.real_media_validator(path, "video", "test video")

        decoded_frame = mock.Mock(
            returncode=0,
            stdout="frame=1\nout_time_us=1000\nprogress=end\n",
            stderr="",
        )
        with (
            mock.patch.object(
                hardware_qa.shutil, "which", return_value="/synthetic/ffmpeg"
            ),
            mock.patch.object(
                hardware_qa.subprocess, "run", return_value=decoded_frame
            ) as run_decoder,
        ):
            self.real_media_validator(path, "video", "test video")
        run_decoder.assert_called_once_with(
            [
                "/synthetic/ffmpeg",
                "-v", "error",
                "-xerror",
                "-i", str(path),
                "-map", "0:v:0",
                "-frames:v", "1",
                "-progress", "pipe:1",
                "-nostats",
                "-f", "null",
                "-",
            ],
            stdout=hardware_qa.subprocess.PIPE,
            stderr=hardware_qa.subprocess.PIPE,
            text=True,
            check=False,
            timeout=30,
        )

        audio_path = self.private / "synthetic.wav"
        audio_path.write_bytes(valid_wav())
        decoded_audio = mock.Mock(
            returncode=0,
            stdout="out_time_us=1000\nprogress=end\n",
            stderr="",
        )
        with (
            mock.patch.object(
                hardware_qa.shutil, "which", return_value="/synthetic/ffmpeg"
            ),
            mock.patch.object(
                hardware_qa.subprocess, "run", return_value=decoded_audio
            ) as run_audio_decoder,
        ):
            self.real_media_validator(audio_path, "audio", "test audio")
        audio_command = run_audio_decoder.call_args.args[0]
        self.assertIn("0:a:0", audio_command)
        self.assertIn("-frames:a", audio_command)
        self.assertNotIn("-frames:v", audio_command)

    def test_production_firmware_identity_is_pinned(self) -> None:
        self.assertEqual(OFFICIAL_FIRMWARE_VERSION, "2.6.0")
        self.assertEqual(OFFICIAL_FIRMWARE_MD5, "d5be2c99e436081266810594117db496")

        document = json.loads(self.inventory.read_text(encoding="utf-8"))
        document["hardware_qa_inventory"]["firmware"]["version"] = "2.5"
        self.inventory.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "reviewed official 2.6.0"):
            verify_manifest(self.manifest, self.inventory, require_pass=False)

        document["hardware_qa_inventory"]["firmware"]["version"] = "2.6.0"
        document["hardware_qa_inventory"]["firmware"]["expected_md5"] = "0" * 32
        self.inventory.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "reviewed official 2.6.0 identity"):
            verify_manifest(self.manifest, self.inventory, require_pass=False)

    def test_complete_synthetic_schema_fixture_verifies(self) -> None:
        self.write_manifest(self.accepted_fixture())
        summary = verify_manifest(self.manifest, self.inventory)
        self.assertEqual(summary["cases"], len(CASE_SPECS))
        self.assertGreater(summary["artifacts"], len(CASE_SPECS))
        validated_media_kinds = {
            call.args[1] for call in self.media_validator.call_args_list
        }
        self.assertTrue(
            {"audio", "photo", "pocket_screenshot", "video"}
            <= validated_media_kinds
        )
        self.assertEqual(
            summary["manifest_sha256"],
            hashlib.sha256(self.manifest.read_bytes()).hexdigest(),
        )

    def test_manifest_propagates_media_validator_rejection(self) -> None:
        self.write_manifest(self.accepted_fixture())
        self.media_validator.side_effect = ValueError("synthetic decoder rejection")
        with self.assertRaisesRegex(ValueError, "synthetic decoder rejection"):
            verify_manifest(self.manifest, self.inventory)

    def test_installed_payload_manifest_is_complete_and_fails_on_drift(self) -> None:
        self.write_manifest(self.accepted_fixture())
        summary = verify_manifest(self.manifest, self.inventory)
        expected_names = set(
            hardware_qa.installed_payload_names("wonderswan.rev", "chip32.bin")
        )
        self.assertEqual(
            set(summary["core"]["installed_payloads"]), expected_names
        )

        mutation_names = (
            "Cores/RegionallyFamous.SwanSong/data.json",
            "Cores/RegionallyFamous.SwanSong/input.json",
            "Cores/RegionallyFamous.SwanSong/video.json",
            "Cores/RegionallyFamous.SwanSong/audio.json",
            "Cores/RegionallyFamous.SwanSong/variants.json",
            "Platforms/wonderswan.json",
            "Platforms/_images/wonderswan.bin",
        )
        for relative_name in mutation_names:
            with self.subTest(relative_name=relative_name):
                path = self.installed_root / pathlib.Path(
                    *pathlib.PurePosixPath(relative_name).parts
                )
                original = path.read_bytes()
                path.write_bytes(original + b" ")
                try:
                    with self.assertRaisesRegex(ValueError, "environment identities"):
                        verify_manifest(self.manifest, self.inventory)
                finally:
                    path.write_bytes(original)

    def test_installed_payload_tree_rejects_missing_and_symlink_members(self) -> None:
        relative = pathlib.PurePosixPath(
            "Cores/RegionallyFamous.SwanSong/data.json"
        )
        path = self.installed_root / pathlib.Path(*relative.parts)
        original = path.read_bytes()
        path.unlink()
        with self.assertRaisesRegex(ValueError, "installed payload is missing"):
            hardware_qa.build_environment(self.inventory)

        outside = self.private / "outside-data.json"
        outside.write_bytes(original)
        path.symlink_to(outside)
        try:
            with self.assertRaisesRegex(ValueError, "must not traverse a symlink"):
                hardware_qa.build_environment(self.inventory)
        finally:
            path.unlink()
            path.write_bytes(original)

    def test_real_verifier_summary_integrates_with_release_evidence_binding(self) -> None:
        self.write_manifest(self.accepted_fixture())
        bound_inventory = self.evidence / "inventory.json"
        shutil.copy2(self.inventory, bound_inventory)

        def identity(path: pathlib.Path) -> dict[str, object]:
            payload = path.read_bytes()
            return {
                "filename": path.name,
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }

        result = validate_hardware_qa_binding(
            entry_value={
                "manifest": identity(self.manifest),
                "inventory": identity(bound_inventory),
            },
            evidence_directory=self.evidence,
            rbf_filename=self.raw_rbf.name,
            rbf_size=len(self.raw_rbf.read_bytes()),
            rbf_sha256=hashlib.sha256(self.raw_rbf.read_bytes()).hexdigest(),
        )
        self.assertEqual(result["case_count"], len(CASE_SPECS))
        self.assertEqual(
            result["core"]["interact_json"], identity(self.interact_json)
        )
        self.assertEqual(
            result["core"]["persistent_settings"],
            list(hardware_qa.PERSISTENT_SETTING_NAMES),
        )

    def test_real_verifier_bridges_release_package_and_staging(self) -> None:
        self.write_manifest(self.accepted_fixture())
        package_fixture = PackageCoreTest(
            methodName="test_release_rejects_hardware_qa_interact_identity_drift"
        )
        package_fixture.setUp()
        # PackageCoreTest normally isolates package tests behind a synthetic
        # verifier.  This bridge deliberately restores the production verifier.
        package_fixture.hardware_qa_verifier.stop()
        try:
            package_fixture.authorize_release_policy()
            package_fixture.rbf_bytes = self.raw_rbf.read_bytes()
            package_fixture.rbf.write_bytes(package_fixture.rbf_bytes)
            evidence = package_fixture.build_evidence()
            shutil.copytree(self.evidence, evidence.parent, dirs_exist_ok=True)
            bound_inventory = evidence.parent / "inventory.json"
            shutil.copy2(self.inventory, bound_inventory)

            def identity(path: pathlib.Path) -> dict[str, object]:
                payload = path.read_bytes()
                return {
                    "filename": path.name,
                    "size": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }

            evidence_document = json.loads(evidence.read_text(encoding="utf-8"))
            evidence_document["release_evidence"]["hardware_qa"] = {
                "manifest": identity(evidence.parent / self.manifest.name),
                "inventory": identity(bound_inventory),
            }
            evidence.write_text(
                json.dumps(evidence_document, sort_keys=True), encoding="utf-8"
            )

            output = package_fixture.root / (
                "RegionallyFamous.SwanSong_0.1.0-dev.1_2026-07-13.zip"
            )
            package_fixture.package(
                output, build_evidence=evidence, release=True
            )
            provenance = package_fixture.provenance_path(output)
            staging_root = self.root / "release-stage"
            staging_root.mkdir()
            with mock.patch.object(
                staging, "RELEASE_POLICY", package_fixture.release_policy
            ):
                plan = staging.plan_staging(
                    staging_dir=staging_root,
                    package=output,
                    provenance=provenance,
                    verify_release=True,
                    expected_package_sha256=hashlib.sha256(
                        output.read_bytes()
                    ).hexdigest(),
                    expected_provenance_sha256=hashlib.sha256(
                        provenance.read_bytes()
                    ).hexdigest(),
                    expected_version="0.1.0-dev.1",
                    expected_source_commit="a" * 40,
                )
            self.assertTrue(plan.release)
            self.assertEqual(plan.source_commit, "a" * 40)
        finally:
            package_fixture.tearDown()

    def test_compact_rom_inventory_contract_rejects_negative_mutations(self) -> None:
        path = self.private / "compact-896k.wsc"
        valid = bytearray(compact_896k_rom())

        mutations: list[tuple[bytes, str]] = []
        mutations.append((bytes(valid[:-2]), "64 KiB-aligned"))

        bad_entry = bytearray(valid)
        bad_entry[-16] = 0x90
        bad_entry[-2:] = (sum(bad_entry[:-2]) & 0xFFFF).to_bytes(2, "little")
        mutations.append((bytes(bad_entry), "begin with 0xEA"))

        bad_maintenance = bytearray(valid)
        bad_maintenance[-11] |= 0x01
        bad_maintenance[-2:] = (
            sum(bad_maintenance[:-2]) & 0xFFFF
        ).to_bytes(2, "little")
        mutations.append((bytes(bad_maintenance), "maintenance low bits"))

        bad_size = bytearray(valid)
        bad_size[-6] = 0x04
        bad_size[-2:] = (sum(bad_size[:-2]) & 0xFFFF).to_bytes(2, "little")
        mutations.append((bytes(bad_size), "size does not match"))

        bad_checksum = bytearray(valid)
        bad_checksum[0] ^= 1
        mutations.append((bytes(bad_checksum), "checksum mismatch"))

        for contents, message in mutations:
            with self.subTest(message=message):
                path.write_bytes(contents)
                with self.assertRaisesRegex(ValueError, message):
                    hardware_qa.build_environment(self.inventory)
        path.write_bytes(valid)

    def test_compact_probe_identity_matches_repository_generator(self) -> None:
        probe = compact_probe.image()
        self.assertEqual(len(probe), 917_504)
        self.assertEqual(
            hashlib.sha256(probe).hexdigest(),
            hardware_qa.COMPACT_896K_PROBE_SHA256,
        )
        compact_case = next(spec for spec in CASE_SPECS if spec.case_id == "compact_rom_896k")
        self.assertEqual(compact_case.rom_requirement, "compact_896k")

        example = json.loads(
            (ROOT / "hardware-qa-inventory.example.json").read_text(encoding="utf-8")
        )
        rows = example["hardware_qa_inventory"]["roms"]
        self.assertIn({
            "id": "compact-896k",
            "title": "Repository-generated 896 KiB compact probe (footer save type 0x00)",
            "path": "private/compact-896k.wsc",
            "system": "wsc",
            "native_orientation": "horizontal",
            "save_media": "none",
            "rtc": False,
        }, rows)
        documented_types = {
            int(match.group(1), 16)
            for row in rows
            if (match := re.search(r"save type 0x([0-9a-f]{2})", row["title"]))
        }
        self.assertEqual(documented_types, set(hardware_qa.SAVE_TYPE_PAYLOAD_BYTES))

    def test_open_ipl_inventory_identity_and_variants_fail_closed(self) -> None:
        _metadata, environment = hardware_qa.build_environment(self.inventory)
        self.assertEqual(
            environment["open_ipl"],
            {
                "identity": hardware_qa.OPEN_IPL_IDENTITY,
                "variants": list(hardware_qa.REQUIRED_OPEN_IPL_VARIANTS),
            },
        )

        original = self.inventory.read_text(encoding="utf-8")
        inventory = json.loads(original)
        inventory["hardware_qa_inventory"]["open_ipl"]["identity"] = "unknown"
        self.inventory.write_text(json.dumps(inventory), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "open_ipl identity must be"):
            hardware_qa.build_environment(self.inventory)

        self.inventory.write_text(original, encoding="utf-8")
        inventory = json.loads(original)
        inventory["hardware_qa_inventory"]["open_ipl"]["variants"].pop()
        self.inventory.write_text(json.dumps(inventory), encoding="utf-8")
        with self.assertRaisesRegex(
            ValueError, "Open IPL variants must exactly match"
        ):
            hardware_qa.build_environment(self.inventory)
        self.inventory.write_text(original, encoding="utf-8")

    def test_all_save_types_inventory_and_snapshots_fail_closed(self) -> None:
        _metadata, environment = hardware_qa.build_environment(self.inventory)
        by_type = {item["save_type"]: item for item in environment["roms"]}
        self.assertEqual(set(by_type), set(hardware_qa.SAVE_TYPE_PAYLOAD_BYTES))
        for save_type, expected_size in hardware_qa.SAVE_TYPE_PAYLOAD_BYTES.items():
            self.assertEqual(by_type[save_type]["save_payload_bytes"], expected_size)
            self.assertEqual(
                by_type[save_type]["save_media"],
                hardware_qa.SAVE_TYPE_MEDIA[save_type],
            )

        document = self.accepted_fixture()
        case = next(
            item for item in document["hardware_qa"]["cases"]
            if item["id"] == "all_save_types_lifecycle"
        )
        self.assertEqual(len(case["rom_ids"]), 9)
        self.assertEqual(len(case["artifact_ids"]), 25)
        case["rom_ids"].pop()
        self.write_manifest(document)
        with self.assertRaisesRegex(ValueError, "does not satisfy all_save_types"):
            verify_manifest(self.manifest, self.inventory)

        document = self.accepted_fixture()
        artifact = next(
            item for item in document["hardware_qa"]["artifacts"]
            if item["label"] == "cartridge-save type-01 initialized"
        )
        path = self.evidence / artifact["path"]
        contents = path.read_bytes()[:-1]
        path.write_bytes(contents)
        artifact["size"] = len(contents)
        artifact["sha256"] = hashlib.sha256(contents).hexdigest()
        self.write_manifest(document)
        with self.assertRaisesRegex(ValueError, "must be exactly 32768 bytes"):
            verify_manifest(self.manifest, self.inventory)

        document = self.accepted_fixture()
        artifact = next(
            item for item in document["hardware_qa"]["artifacts"]
            if item["label"] == "cartridge-save type-20 power-cycle"
        )
        path = self.evidence / artifact["path"]
        contents = bytes([0x55]) * artifact["size"]
        path.write_bytes(contents)
        artifact["sha256"] = hashlib.sha256(contents).hexdigest()
        self.write_manifest(document)
        with self.assertRaisesRegex(ValueError, "power-cycle save does not match"):
            verify_manifest(self.manifest, self.inventory)

        path = self.private / "sram02.ws"
        original = path.read_bytes()
        changed = bytearray(original)
        changed[-5] = 0x01
        changed[-2:] = (sum(changed[:-2]) & 0xFFFF).to_bytes(2, "little")
        path.write_bytes(changed)
        with self.assertRaisesRegex(ValueError, "missing 0x02"):
            hardware_qa.build_environment(self.inventory)
        path.write_bytes(original)

        inventory = json.loads(self.inventory.read_text(encoding="utf-8"))
        row = next(
            item for item in inventory["hardware_qa_inventory"]["roms"]
            if item["id"] == "sram02"
        )
        row["save_media"] = "eeprom"
        self.inventory.write_text(json.dumps(inventory), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "does not match footer type 0x02"):
            hardware_qa.build_environment(self.inventory)

    def test_auto_off_dirty_save_flush_requires_exact_probe_and_artifacts(self) -> None:
        probe = sram_persistence_probe.image(0x03, "ws")
        self.assertEqual(
            hashlib.sha256(probe).hexdigest(),
            hardware_qa.AUTO_OFF_TYPE03_PROBE_SHA256,
        )
        expected_images = (
            sram_persistence_save.expected_image(
                0x03,
                "ws",
                sram_persistence_probe.GENERATION_1,
                sram_persistence_probe.STATUS_INITIALIZED,
            ),
            sram_persistence_save.expected_image(
                0x03,
                "ws",
                sram_persistence_probe.GENERATION_2,
                sram_persistence_probe.STATUS_PERSISTED_1_TO_2,
            ),
            sram_persistence_save.expected_image(
                0x03,
                "ws",
                sram_persistence_probe.GENERATION_1,
                sram_persistence_probe.STATUS_PERSISTED_2_TO_1,
            ),
        )
        for (label, digest), contents in zip(
            hardware_qa.AUTO_OFF_SAVE_SNAPSHOT_SHA256,
            expected_images,
            strict=True,
        ):
            with self.subTest(label=label):
                self.assertEqual(len(contents), hardware_qa.AUTO_OFF_SAVE_BYTES)
                self.assertEqual(hashlib.sha256(contents).hexdigest(), digest)

        document = self.accepted_fixture()
        body = document["hardware_qa"]
        case = next(
            item for item in body["cases"]
            if item["id"] == "auto_off_dirty_save_flush"
        )
        selected = [
            item for item in body["artifacts"]
            if item["id"] in case["artifact_ids"]
        ]
        self.assertEqual(case["rom_ids"], ["sram03"])
        self.assertEqual(len(selected), 5)
        self.assertEqual(
            {item["label"] for item in selected},
            {
                *(label for label, _digest in hardware_qa.AUTO_OFF_SAVE_SNAPSHOT_SHA256),
                hardware_qa.AUTO_OFF_VIDEO_LABEL,
                hardware_qa.AUTO_OFF_LOG_LABEL,
            },
        )
        self.write_manifest(document)
        verify_manifest(self.manifest, self.inventory)

        document = self.accepted_fixture()
        case = next(
            item for item in document["hardware_qa"]["cases"]
            if item["id"] == "auto_off_dirty_save_flush"
        )
        case["rom_ids"] = ["horizontal-sram"]
        self.write_manifest(document)
        with self.assertRaisesRegex(ValueError, "does not satisfy auto_off_type03_probe"):
            verify_manifest(self.manifest, self.inventory)

        for required_label in (
            hardware_qa.AUTO_OFF_VIDEO_LABEL,
            hardware_qa.AUTO_OFF_LOG_LABEL,
        ):
            with self.subTest(missing_exact_label=required_label):
                document = self.accepted_fixture()
                artifact = next(
                    item for item in document["hardware_qa"]["artifacts"]
                    if item["label"] == required_label
                )
                artifact["label"] += " altered"
                self.write_manifest(document)
                with self.assertRaisesRegex(ValueError, "needs exactly one"):
                    verify_manifest(self.manifest, self.inventory)

        document = self.accepted_fixture()
        artifact = next(
            item for item in document["hardware_qa"]["artifacts"]
            if item["label"] == hardware_qa.AUTO_OFF_SAVE_SNAPSHOT_SHA256[0][0]
        )
        path = self.evidence / artifact["path"]
        contents = path.read_bytes()[:-1]
        path.write_bytes(contents)
        artifact["size"] = len(contents)
        artifact["sha256"] = hashlib.sha256(contents).hexdigest()
        self.write_manifest(document)
        with self.assertRaisesRegex(ValueError, "must be exactly 131072 bytes"):
            verify_manifest(self.manifest, self.inventory)

        document = self.accepted_fixture()
        artifact = next(
            item for item in document["hardware_qa"]["artifacts"]
            if item["label"] == hardware_qa.AUTO_OFF_SAVE_SNAPSHOT_SHA256[1][0]
        )
        path = self.evidence / artifact["path"]
        contents = bytearray(path.read_bytes())
        contents[0] ^= 0x01
        path.write_bytes(contents)
        artifact["sha256"] = hashlib.sha256(contents).hexdigest()
        self.write_manifest(document)
        with self.assertRaisesRegex(ValueError, "does not match the exact generated-probe image"):
            verify_manifest(self.manifest, self.inventory)

        document = self.accepted_fixture()
        body = document["hardware_qa"]
        case = next(
            item for item in body["cases"]
            if item["id"] == "auto_off_dirty_save_flush"
        )
        source = next(
            item for item in body["artifacts"]
            if item["label"] == hardware_qa.AUTO_OFF_SAVE_SNAPSHOT_SHA256[0][0]
        )
        source_path = self.evidence / source["path"]
        extra_path = self.evidence / "files/extra-auto-off.sav"
        extra_path.write_bytes(source_path.read_bytes())
        extra = {
            **source,
            "id": "extra-auto-off-save",
            "path": "files/extra-auto-off.sav",
            "label": "auto-off unexpected extra snapshot",
        }
        body["artifacts"].append(extra)
        case["artifact_ids"].append(extra["id"])
        self.write_manifest(document)
        with self.assertRaisesRegex(ValueError, "only the three exact Auto Off save snapshots"):
            verify_manifest(self.manifest, self.inventory)

    def test_inventory_rtc_must_match_rom_footer_in_both_directions(self) -> None:
        _metadata, environment = hardware_qa.build_environment(self.inventory)
        vertical = next(
            item for item in environment["roms"]
            if item["id"] == "vertical-eeprom-rtc"
        )
        self.assertIs(vertical["rtc"], True)

        path = self.private / "vertical.wsc"
        original = path.read_bytes()
        invalid = bytearray(original)
        invalid[-3] = 2
        invalid[-2:] = (sum(invalid[:-2]) & 0xFFFF).to_bytes(2, "little")
        path.write_bytes(invalid)
        with self.assertRaisesRegex(ValueError, r"ROM footer RTC field is invalid"):
            hardware_qa.build_environment(self.inventory)

        changed = bytearray(original)
        changed[-3] = 0
        changed[-2:] = (sum(changed[:-2]) & 0xFFFF).to_bytes(2, "little")
        path.write_bytes(changed)
        with self.assertRaisesRegex(
            ValueError,
            r"rtc True does not match ROM footer RTC field False",
        ):
            hardware_qa.build_environment(self.inventory)
        path.write_bytes(original)

        inventory = json.loads(self.inventory.read_text(encoding="utf-8"))
        row = next(
            item for item in inventory["hardware_qa_inventory"]["roms"]
            if item["id"] == "vertical-eeprom-rtc"
        )
        row["rtc"] = False
        self.inventory.write_text(json.dumps(inventory), encoding="utf-8")
        with self.assertRaisesRegex(
            ValueError,
            r"rtc False does not match ROM footer RTC field True",
        ):
            hardware_qa.build_environment(self.inventory)

    def test_settings_buffer_and_interface_catalog_mutations_fail_closed(self) -> None:
        cases = {spec.case_id: spec for spec in CASE_SPECS}
        self.assertEqual(len(CASE_SPECS), 31)
        _metadata, environment = hardware_qa.build_environment(self.inventory)
        self.assertEqual(
            environment["core"]["persistent_settings"],
            list(hardware_qa.PERSISTENT_SETTING_NAMES),
        )
        fresh_checks = set(cases["fresh_sd_startup"].checks)
        self.assertTrue({
            "presets_namespace_absent_prelaunch",
            "settings_namespace_absent_prelaunch",
            "bound_input_menu_observed",
            "bound_interact_defaults_observed",
            "no_presets_added_during_run",
            "agg23_core_present_before_swan_song_install",
            "side_by_side_core_entries_visible",
            "agg23_core_and_saves_unchanged_after_install",
            "swan_song_update_replaced_only_swan_song_payloads",
            "swan_song_namespaces_preserved_across_update",
            "swan_song_uninstall_removed_only_swan_song_core",
            "shared_platform_and_agg23_core_remained_operational",
            "reviewed_swan_song_package_reinstalled_after_uninstall",
        }.issubset(fresh_checks))
        settings_checks = set(cases["settings_options_and_persistence"].checks)
        self.assertTrue({
            "system_type_auto_mono", "system_type_auto_color",
            "system_type_forced_mono_after_reset",
            "system_type_forced_color_after_reset",
            "cpu_turbo_off_baseline", "cpu_turbo_on_rate_observed",
            "system_type_persisted", "cpu_turbo_persisted",
            "triple_buffer_persisted", "motion_lcd_response_persisted",
            "display_orientation_persisted", "landscape_180_persisted",
            "color_profile_persisted", "control_layout_persisted",
            "fastforward_audio_persisted", "power_cycle_preserved_all_settings",
            "global_interact_persist_created_by_run",
            "no_per_asset_interact_settings_used",
            "settings_path_transitions_and_hashes_recorded",
            "reset_all_defaults_restored_all_settings",
        }.issubset(settings_checks))
        self.assertTrue({
            "direct_mode_triple_buffer_off", "triple_buffer_mode_on",
            "triple_buffer_complete_frames", "lcd_response_forces_buffered_path",
            "lcd_response_off_restores_direct_path",
            "complete_frames_60_9_forces_buffered_path",
            "complete_frames_60_9_statistics_recorded_pocket_and_dock",
            "complete_frames_60_9_rotations_0_270_180",
            "complete_frames_60_9_display_modes_20_30_40",
            "standard_to_60_9_transition_clean",
            "complete_frames_60_9_to_standard_transition_clean",
            "complete_frames_60_9_no_tearing_or_resync_after_priming",
        }.issubset(set(cases["video_buffer_modes"].checks)))
        self.assertTrue({
            "calibration_chip32_identity_and_source_delta_recorded",
            "stuck_pending_status_fault_injected",
            "visible_poll_guard_timeout_observed",
            "poll_guard_preceded_firmware_cycle_limit",
            "reviewed_package_restored_after_calibration",
        }.issubset(set(cases["invalid_rom_negative"].checks)))
        self.assertTrue({
            "duration_at_least_120_minutes",
            "auto_dim_disabled_and_recorded", "auto_off_disabled_and_recorded",
            "complete_frames_60_9_active_for_full_soak",
            "complete_frames_60_9_pocket_and_dock_soak_segments_recorded",
            "statistics_recorded_before_and_after_soak",
        }.issubset(set(cases["long_run_stability"].checks)))
        self.assertEqual(
            set(cases["auto_off_dirty_save_flush"].checks),
            {
                "auto_off_enabled_and_interval_recorded",
                "auto_dim_disabled_and_recorded",
                "pocket_undocked",
                "baseline_created_by_normal_quit",
                "no_input_menu_or_power_button_during_idle",
                "automatic_off_observed_after_configured_interval",
                "automatic_off_flushed_exact_generation_2",
                "relaunch_loaded_generation_2",
                "exact_path_sizes_hashes_and_timeline_recorded",
            },
        )
        self.assertTrue({
            "cartridge_power_state_matches_framework_minus_one",
            "cartridge_bank3_bank2_bank1_input_high_impedance",
            "cartridge_bank0_nibble_high_output", "link_port_not_advertised",
            "link_so_si_sck_sd_input_high_impedance", "ir_transmitter_off",
            "ir_receiver_disable_asserted", "electrical_measurement_method_recorded",
        }.issubset(set(cases["unused_hardware_interfaces"].checks)))

        all_schema_words = [
            spec.case_id for spec in CASE_SPECS
        ] + [check for spec in CASE_SPECS for check in spec.checks]
        self.assertFalse(any("sleep" in word.casefold() for word in all_schema_words))
        protocol = (ROOT / "HARDWARE_QA_PROTOCOL.md").read_text(encoding="utf-8").casefold()
        for stale_wording in ("sleep cycle", "sleep/wake", "sleep not advertised"):
            self.assertNotIn(stale_wording, protocol)
        self.assertIn("/presets/regionallyfamous.swansong/input", protocol)
        self.assertIn("/presets/regionallyfamous.swansong/interact", protocol)
        self.assertIn(
            "/settings/regionallyfamous.swansong/interact/interact_persist.json",
            protocol,
        )

        original_interact = self.interact_json.read_bytes()
        interact = json.loads(original_interact)
        persistent = next(
            item for item in interact["interact"]["variables"]
            if item.get("name") == "CPU Turbo"
        )
        persistent.pop("persist")
        self.interact_json.write_text(json.dumps(interact), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "complete reviewed nine-setting catalogue"):
            hardware_qa.build_environment(self.inventory)
        self.interact_json.write_bytes(original_interact)

        for case_id in (
            "video_buffer_modes",
            "settings_options_and_persistence",
            "unused_hardware_interfaces",
            "memories_disabled_negative",
            "invalid_rom_negative",
            "long_run_stability",
        ):
            with self.subTest(case_id=case_id):
                document = self.accepted_fixture()
                case = next(
                    item for item in document["hardware_qa"]["cases"]
                    if item["id"] == case_id
                )
                removed = next(iter(case["checks"]))
                case["checks"][f"mutated_{removed}"] = case["checks"].pop(removed)
                self.write_manifest(document)
                with self.assertRaisesRegex(ValueError, "checks has invalid members"):
                    verify_manifest(self.manifest, self.inventory)

        for case_id, label in (
            ("fresh_sd_startup", hardware_qa.FRESH_SD_APF_BASELINE_LOG_LABEL),
            ("fresh_sd_startup", hardware_qa.FRESH_SD_BOUND_INPUT_LABEL),
            ("fresh_sd_startup", hardware_qa.FRESH_SD_BOUND_INTERACT_LABEL),
            (
                "fresh_sd_startup",
                hardware_qa.FRESH_SD_DISTRIBUTION_LIFECYCLE_LOG_LABEL,
            ),
            (
                "invalid_rom_negative",
                hardware_qa.CHIP32_POLL_GUARD_LOG_LABEL,
            ),
            (
                "settings_options_and_persistence",
                hardware_qa.SETTINGS_APF_PATH_AUDIT_LOG_LABEL,
            ),
        ):
            with self.subTest(case_id=case_id, label=label):
                document = self.accepted_fixture()
                artifact = next(
                    item for item in document["hardware_qa"]["artifacts"]
                    if item["label"] == label
                )
                artifact["label"] = "mutated APF audit label"
                self.write_manifest(document)
                with self.assertRaisesRegex(ValueError, "needs exactly one"):
                    verify_manifest(self.manifest, self.inventory)

    def test_compact_case_rejects_other_valid_896k_image(self) -> None:
        path = self.private / "compact-896k.wsc"
        other = bytearray(compact_probe.image())
        other[0] ^= 1
        other[-2:] = (sum(other[:-2]) & 0xFFFF).to_bytes(2, "little")
        path.write_bytes(other)
        wrong_template = self.evidence / "wrong-compact-template.json"
        generate_manifest(self.inventory, wrong_template)
        original = self.generated_document
        try:
            self.generated_document = json.loads(wrong_template.read_text(encoding="utf-8"))
            self.write_manifest(self.accepted_fixture())
        finally:
            self.generated_document = original
        with self.assertRaisesRegex(ValueError, "does not satisfy compact_896k"):
            verify_manifest(self.manifest, self.inventory)

    def test_missing_case_and_false_check_fail_closed(self) -> None:
        document = self.accepted_fixture()
        document["hardware_qa"]["cases"].pop()
        self.write_manifest(document)
        with self.assertRaisesRegex(ValueError, "exact hardware QA case catalogue"):
            verify_manifest(self.manifest, self.inventory)

        document = self.accepted_fixture()
        first = document["hardware_qa"]["cases"][0]
        first["checks"][next(iter(first["checks"]))] = False
        self.write_manifest(document)
        with self.assertRaisesRegex(ValueError, "not accepted"):
            verify_manifest(self.manifest, self.inventory)

    def test_missing_or_tampered_artifact_fails_closed(self) -> None:
        document = self.accepted_fixture()
        self.write_manifest(document)
        first = document["hardware_qa"]["artifacts"][0]
        (self.evidence / first["path"]).write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "(size|SHA-256)"):
            verify_manifest(self.manifest, self.inventory)

        document = self.accepted_fixture()
        self.write_manifest(document)
        first = document["hardware_qa"]["artifacts"][0]
        (self.evidence / first["path"]).unlink()
        with self.assertRaisesRegex(ValueError, "evidence file is missing"):
            verify_manifest(self.manifest, self.inventory)

    def test_hard_link_alias_cannot_bypass_artifact_reuse(self) -> None:
        document = self.accepted_fixture()
        body = document["hardware_qa"]
        first_case, second_case = body["cases"][:2]
        first_id = first_case["artifact_ids"][0]
        second_id = second_case["artifact_ids"][0]
        first = next(item for item in body["artifacts"] if item["id"] == first_id)
        second = next(item for item in body["artifacts"] if item["id"] == second_id)
        source = self.evidence / first["path"]
        alias = self.evidence / "files" / "hardlink-alias.png"
        alias.hardlink_to(source)
        second.update(
            {
                "path": "files/hardlink-alias.png",
                "size": first["size"],
                "sha256": first["sha256"],
            }
        )
        self.write_manifest(document)
        with self.assertRaisesRegex(ValueError, "must not be a hard link"):
            verify_manifest(self.manifest, self.inventory)

    def test_identity_changes_and_bad_installed_bitstream_fail_closed(self) -> None:
        self.write_manifest(self.accepted_fixture())
        self.firmware.write_bytes(b"changed firmware fixture")
        with self.assertRaisesRegex(ValueError, "firmware update MD5"):
            verify_manifest(self.manifest, self.inventory)

        self.firmware.write_bytes(b"synthetic firmware identity fixture")
        self.installed.write_bytes(b"not bit reversed")
        with self.assertRaisesRegex(ValueError, "sizes differ"):
            verify_manifest(self.manifest, self.inventory)

        self.installed.write_bytes(bytes(len(self.raw_rbf.read_bytes())))
        with self.assertRaisesRegex(ValueError, "not the bit-reversed raw RBF"):
            verify_manifest(self.manifest, self.inventory)

    def test_tiny_bitstream_fails_plausibility_floor(self) -> None:
        tiny = bytes(range(64))
        self.raw_rbf.write_bytes(tiny)
        self.installed.write_bytes(tiny.translate(REVERSE))
        with self.assertRaisesRegex(ValueError, "implausibly small"):
            verify_manifest(self.manifest, self.inventory, require_pass=False)

    def test_overbroad_case_selections_and_artifact_reuse_fail_closed(self) -> None:
        document = self.accepted_fixture()
        first = document["hardware_qa"]["cases"][0]
        first["rom_ids"] = [item["id"] for item in document["hardware_qa"]["environment"]["roms"]]
        self.write_manifest(document)
        with self.assertRaisesRegex(ValueError, "ROM selection does not satisfy any"):
            verify_manifest(self.manifest, self.inventory)

        document = self.accepted_fixture()
        first = document["hardware_qa"]["cases"][0]
        first["controller_ids"] = [item["id"] for item in document["hardware_qa"]["environment"]["controllers"]]
        self.write_manifest(document)
        with self.assertRaisesRegex(ValueError, "controller selection does not satisfy pocket"):
            verify_manifest(self.manifest, self.inventory)

        document = self.accepted_fixture()
        first, second = document["hardware_qa"]["cases"][:2]
        second["artifact_ids"].append(first["artifact_ids"][0])
        self.write_manifest(document)
        with self.assertRaisesRegex(ValueError, "reused by distinct cases"):
            verify_manifest(self.manifest, self.inventory)

    def test_save_negative_case_requires_supported_type01_check(self) -> None:
        document = self.accepted_fixture()
        case = next(
            item for item in document["hardware_qa"]["cases"]
            if item["id"] == "save_negative_cases"
        )
        self.assertIn("type01_32k_supported", case["checks"])
        case["checks"]["legacy_type01_rejected"] = case["checks"].pop(
            "type01_32k_supported"
        )
        self.write_manifest(document)
        with self.assertRaisesRegex(ValueError, "checks has invalid members"):
            verify_manifest(self.manifest, self.inventory)

    def test_console_eeprom_lifecycle_requires_exact_related_snapshots(self) -> None:
        document = self.accepted_fixture()
        case = next(
            item for item in document["hardware_qa"]["cases"]
            if item["id"] == "console_eeprom_lifecycle"
        )
        self.assertEqual(len(case["artifact_ids"]), 13)
        self.assertEqual(
            set(case["rom_ids"]), {"horizontal-sram", "vertical-eeprom-rtc"}
        )

        document = self.accepted_fixture()
        case = next(
            item for item in document["hardware_qa"]["cases"]
            if item["id"] == "console_eeprom_lifecycle"
        )
        case["rom_ids"] = ["vertical-eeprom-rtc"]
        self.write_manifest(document)
        with self.assertRaisesRegex(ValueError, "does not satisfy mono_color"):
            verify_manifest(self.manifest, self.inventory)

        document = self.accepted_fixture()
        artifact = next(
            item for item in document["hardware_qa"]["artifacts"]
            if item["label"] == "console-eeprom mono power-cycle"
        )
        path = self.evidence / artifact["path"]
        contents = bytes([0x55]) * 128
        path.write_bytes(contents)
        artifact["sha256"] = hashlib.sha256(contents).hexdigest()
        self.write_manifest(document)
        with self.assertRaisesRegex(ValueError, "power-cycle snapshot does not match"):
            verify_manifest(self.manifest, self.inventory)

        document = self.accepted_fixture()
        artifact = next(
            item for item in document["hardware_qa"]["artifacts"]
            if item["label"] == "console-eeprom color ordinary-reset"
        )
        path = self.evidence / artifact["path"]
        contents = path.read_bytes()[:-1]
        path.write_bytes(contents)
        artifact["size"] = len(contents)
        artifact["sha256"] = hashlib.sha256(contents).hexdigest()
        self.write_manifest(document)
        with self.assertRaisesRegex(ValueError, "exact fixed 2048-byte image"):
            verify_manifest(self.manifest, self.inventory)

    def test_controls_behavior_is_recorded_without_assuming_outcome(self) -> None:
        expected_cases = {
            "pocket_horizontal_input",
            "dock_wired_input",
            "dock_wireless_input",
        }
        by_id = {spec.case_id: spec for spec in CASE_SPECS}
        for case_id in expected_cases:
            self.assertIn("controls_behavior_recorded", by_id[case_id].checks)
            self.assertNotIn("controls_menu_read_only", by_id[case_id].checks)

        document = self.accepted_fixture()
        case = next(
            item for item in document["hardware_qa"]["cases"]
            if item["id"] == "dock_wired_input"
        )
        case["checks"]["controls_menu_read_only"] = case["checks"].pop(
            "controls_behavior_recorded"
        )
        self.write_manifest(document)
        with self.assertRaisesRegex(ValueError, "checks has invalid members"):
            verify_manifest(self.manifest, self.inventory)

    def test_fresh_sd_requires_both_core_icon_palette_contexts(self) -> None:
        by_id = {spec.case_id: spec for spec in CASE_SPECS}
        self.assertIn(
            "core_icon_positive_negative_correct",
            by_id["fresh_sd_startup"].checks,
        )

        document = self.accepted_fixture()
        case = next(
            item for item in document["hardware_qa"]["cases"]
            if item["id"] == "fresh_sd_startup"
        )
        case["checks"].pop("core_icon_positive_negative_correct")
        self.write_manifest(document)
        with self.assertRaisesRegex(ValueError, "checks has invalid members"):
            verify_manifest(self.manifest, self.inventory)

    def test_unreviewed_attestation_and_wrong_native_screenshot_fail_closed(self) -> None:
        document = self.accepted_fixture()
        document["hardware_qa"]["attestation"]["evidence_reviewed"] = False
        self.write_manifest(document)
        with self.assertRaisesRegex(ValueError, "attestation is not accepted"):
            verify_manifest(self.manifest, self.inventory)

        document = self.accepted_fixture()
        native = next(item for item in document["hardware_qa"]["artifacts"] if item["kind"] == "pocket_screenshot")
        path = self.evidence / native["path"]
        contents = self.artifact_bytes("photo")[1]
        path.write_bytes(contents)
        native["size"] = len(contents)
        native["sha256"] = hashlib.sha256(contents).hexdigest()
        self.write_manifest(document)
        with self.assertRaisesRegex(ValueError, "native 224x144"):
            verify_manifest(self.manifest, self.inventory)

    def test_operator_worksheet_is_strict_manifest_derived_and_read_only(self) -> None:
        manifest_before = self.manifest.read_bytes()
        inventory_before = self.inventory.read_bytes()
        report = hardware_qa.render_operator_worksheet(
            self.inventory, self.manifest
        )

        self.assertEqual(self.manifest.read_bytes(), manifest_before)
        self.assertEqual(self.inventory.read_bytes(), inventory_before)
        self.assertIn("0 pass / 0 fail / 31 pending", report)
        self.assertIn("Checking boxes here does not update evidence", report)
        self.assertIn("Captured times, sizes, hashes", report)
        for spec in CASE_SPECS:
            self.assertIn(f"`{spec.case_id}`", report)
            for check in spec.checks:
                self.assertIn(f"[ ] `{check}`", report)

        fresh_plan = hardware_qa._artifact_plan(
            hardware_qa.CASE_BY_ID["fresh_sd_startup"]
        )
        self.assertEqual(len(fresh_plan), 9)
        self.assertIn(
            {
                "id": "fresh_sd_startup-photo-01",
                "kind": "photo",
                "label": hardware_qa.FRESH_SD_BOUND_INPUT_LABEL,
                "exact_label": True,
                "path": (
                    "files/fresh_sd_startup/"
                    "fresh_sd_startup-photo-01.png"
                ),
            },
            fresh_plan,
        )
        console_plan = hardware_qa._artifact_plan(
            hardware_qa.CASE_BY_ID["console_eeprom_lifecycle"]
        )
        all_types_plan = hardware_qa._artifact_plan(
            hardware_qa.CASE_BY_ID["all_save_types_lifecycle"]
        )
        self.assertEqual(len(console_plan), 13)
        self.assertEqual(len(all_types_plan), 25)
        auto_off_plan = hardware_qa._artifact_plan(
            hardware_qa.CASE_BY_ID["auto_off_dirty_save_flush"]
        )
        self.assertEqual(len(auto_off_plan), 5)
        self.assertTrue(all(item["exact_label"] for item in auto_off_plan))
        self.assertEqual(
            {item["label"] for item in auto_off_plan},
            {
                *(label for label, _digest in hardware_qa.AUTO_OFF_SAVE_SNAPSHOT_SHA256),
                hardware_qa.AUTO_OFF_VIDEO_LABEL,
                hardware_qa.AUTO_OFF_LOG_LABEL,
            },
        )
        self.assertEqual(
            all_types_plan[23]["label"],
            "cartridge-save type-50 power-cycle",
        )
        self.assertEqual(
            all_types_plan[23]["path"],
            "files/all_save_types_lifecycle/"
            "all_save_types_lifecycle-save-24.sav",
        )

        output = self.root / "operator-worksheet.md"
        hardware_qa.write_operator_worksheet(
            self.inventory, self.manifest, output
        )
        self.assertEqual(output.read_text(encoding="utf-8"), report)
        with self.assertRaisesRegex(ValueError, "must not replace"):
            hardware_qa.write_operator_worksheet(
                self.inventory, self.manifest, self.manifest
            )

        document = copy.deepcopy(self.generated_document)
        first = document["hardware_qa"]["cases"][0]
        first.update({
            "status": "fail",
            "started_at": "2026-07-13T13:00:00Z",
            "completed_at": "2026-07-13T13:05:00Z",
            "notes": "Observed physical failure; no pass is claimed.",
        })
        first["checks"][next(iter(first["checks"]))] = True
        self.write_manifest(document)
        failed_report = hardware_qa.render_operator_worksheet(
            self.inventory, self.manifest
        )
        self.assertIn("0 pass / 1 fail / 30 pending", failed_report)
        self.assertIn("01. `fresh_sd_startup` — FAIL", failed_report)
        self.assertFalse(
            document["hardware_qa"]["attestation"]["physical_hardware_observed"]
        )

    def test_refuses_manifest_overwrite(self) -> None:
        original = self.manifest.read_bytes()
        with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
            generate_manifest(self.inventory, self.manifest)
        self.assertEqual(self.manifest.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
