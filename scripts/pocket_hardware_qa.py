#!/usr/bin/env python3
"""Generate and integrity-check Pocket/Dock QA evidence attestations.

Generation records immutable identities but deliberately creates no passing
results. Verification checks schema, hashes, and human attestations; it cannot
mechanically prove that a claimed physical observation is truthful or correct.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
import struct
import sys
from dataclasses import dataclass
from typing import Any, Callable

try:
    from reverse_rbf import REVERSE
except ModuleNotFoundError:  # Imported as scripts.pocket_hardware_qa.
    from scripts.reverse_rbf import REVERSE


INVENTORY_MAGIC = "SWAN_SONG_HARDWARE_QA_INVENTORY_V1"
MANIFEST_MAGIC = "SWAN_SONG_HARDWARE_QA_EVIDENCE_V1"
OFFICIAL_FIRMWARE_VERSION = "2.6.0"
OFFICIAL_FIRMWARE_MD5 = "d5be2c99e436081266810594117db496"
COMPACT_896K_PROBE_SHA256 = (
    "b4a2c985906ac04c6622080bb1f1f3ac4b3895784c5594f4ba97cd45e6935979"
)
# A current official openFPGA template compressed RBF inspected for this
# protocol is 787,952 bytes.  64 KiB is a deliberately conservative truncation
# floor, not a Cyclone V format proof and not a substitute for build evidence.
MIN_BITSTREAM_BYTES = 64 * 1024
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
MD5_RE = re.compile(r"[0-9a-f]{32}\Z")
ID_RE = re.compile(r"[a-z0-9][a-z0-9_.-]{0,62}\Z")
VERSION_RE = re.compile(r"[0-9]+\.[0-9]+(?:\.[0-9]+)?\Z")
UTC_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")


@dataclass(frozen=True)
class ArtifactNeed:
    kinds: tuple[str, ...]
    minimum: int


@dataclass(frozen=True)
class CaseSpec:
    case_id: str
    device_mode: str
    checks: tuple[str, ...]
    needs: tuple[ArtifactNeed, ...]
    rom_requirement: str = "any"
    controller_requirement: str = "pocket"


VISUAL = ArtifactNeed(("pocket_screenshot", "photo", "video"), 1)
LOG = ArtifactNeed(("log",), 1)
VIDEO = ArtifactNeed(("video",), 1)
AUDIO = ArtifactNeed(("audio",), 1)
SAVE3 = ArtifactNeed(("save",), 3)

CONSOLE_EEPROM_SNAPSHOT_STAGES = (
    "factory-created",
    "setup-edited",
    "quit-relaunch",
    "model-switch",
    "title-switch",
    "ordinary-reset",
    "power-cycle",
)
CONSOLE_EEPROM_SNAPSHOT_SIZES = {"mono": 128, "color": 2048}


CASE_SPECS = (
    CaseSpec("fresh_sd_startup", "pocket", (
        "fresh_sd_used", "platform_entry_visible", "platform_art_and_info_correct",
        "bios_prompts_correct", "game_booted", "startup_log_captured",
    ), (ArtifactNeed(("pocket_screenshot", "photo"), 2), LOG)),
    CaseSpec("recent_last_title_relaunch", "pocket", (
        "startup_action_openfpga", "recent_entry_created", "quit_returned_to_openfpga",
        "recent_reopened_core", "last_title_reused",
    ), (ArtifactNeed(("pocket_screenshot", "photo", "video"), 2), LOG)),
    CaseSpec("reset_all_defaults", "pocket", (
        "remembered_title_present_before_reset", "reset_all_defaults_invoked",
        "title_history_cleared", "bios_history_cleared", "valid_reselection_recovers",
    ), (ArtifactNeed(("pocket_screenshot", "photo", "video"), 2), LOG)),
    CaseSpec("missing_bios_negative", "pocket", (
        "bw_missing_rejected", "color_missing_rejected", "no_game_execution",
        "recovery_after_restoring_bios",
    ), (VISUAL, LOG)),
    CaseSpec("invalid_rom_negative", "pocket", (
        "too_small_rejected", "misaligned_non_power_of_two_rejected",
        "invalid_compact_footer_rejected", "invalid_compact_error_visible",
        "oversized_rejected",
        "no_invalid_game_execution", "valid_rom_recovers",
    ), (VISUAL, LOG)),
    CaseSpec("compact_rom_896k", "pocket", (
        "size_917504_accepted", "footer_checksum_accepted",
        "booted_from_top_aligned_reset_vector", "mapper_mask_is_1mib",
        "erased_prefix_reads_ff", "ordinary_power_of_two_title_still_boots",
    ), (VISUAL, LOG), "compact_896k"),
    CaseSpec("memories_sleep_disabled_negative", "pocket", (
        "memory_action_unavailable_or_rejected", "sleep_not_advertised",
        "quick_load_does_not_mutate_game", "game_recovers",
    ), (VISUAL, LOG)),
    CaseSpec("pocket_horizontal_input", "pocket", (
        "dpad_x1_x4", "a", "b", "y1_y4", "start", "simultaneous_directions_safe",
        "fastforward_hold", "fastforward_tap_latch_release", "controls_behavior_recorded",
    ), (VIDEO, LOG), "horizontal"),
    CaseSpec("pocket_vertical_input", "pocket", (
        "dpad_y1_y4", "face_x1_x4", "shoulder_a", "shoulder_b", "start",
        "simultaneous_directions_safe", "fastforward_hold", "fastforward_tap_latch_release",
    ), (VIDEO, LOG), "vertical"),
    CaseSpec("orientation_presentation", "pocket", (
        "auto_horizontal", "auto_vertical", "forced_horizontal", "forced_vertical",
        "landscape_180", "presentation_did_not_remap_input", "transition_no_stale_frame",
    ), (ArtifactNeed(("pocket_screenshot", "photo"), 5), LOG), "both_orientations"),
    CaseSpec("display_modes_and_screenshots", "pocket", (
        "raw_rgb444", "color_profile_ares", "lcd_response_off", "lcd_response_blend",
        "lcd_response_persistence", "display_mode_20", "display_mode_30",
        "display_mode_40", "native_screenshot_224x144", "color_restored_after_grayscale",
    ), (ArtifactNeed(("pocket_screenshot",), 3), LOG), "both_orientations"),
    CaseSpec("dock_wired_input", "dock", (
        "digital_matrix_complete", "dpad_explicit", "start", "fastforward",
        "no_stuck_input", "p1_only", "controls_behavior_recorded",
    ), (VIDEO, LOG), "both_orientations", "dock_wired_gamepad"),
    CaseSpec("dock_wireless_input", "dock", (
        "digital_matrix_complete", "dpad_explicit", "analog_stick_behavior_recorded",
        "start", "fastforward", "no_stuck_input", "controls_behavior_recorded",
    ), (VIDEO, LOG), "both_orientations", "dock_wireless_gamepad"),
    CaseSpec("dock_hotplug_and_menu", "dock", (
        "hot_unplug_held_button_cleared", "reconnect_restored_p1", "dedicated_menu_button",
        "select_down_fallback", "fastforward_not_stuck", "no_core_reset",
    ), (VIDEO, LOG), "any", "dock_gamepads"),
    CaseSpec("dock_hdmi_orientations", "dock", (
        "rotation_0", "rotation_270", "rotation_180", "aspect_and_crop_correct",
        "display_modes_correct", "transition_no_resync", "first_vertical_frame_correct",
    ), (ArtifactNeed(("photo", "video"), 3), LOG), "both_orientations", "dock_wired_gamepad"),
    CaseSpec("unsupported_input_devices", "dock", (
        "p2_gamepad_does_not_control", "p3_keyboard_does_not_control",
        "p4_mouse_does_not_control", "disconnect_does_not_control", "p1_recovery",
    ), (VIDEO, LOG), "any", "unsupported_devices"),
    CaseSpec("sram_lifecycle", "both", (
        "absent_save_initialized", "write_persisted_after_quit", "relaunch_loaded",
        "power_cycle_loaded", "save_hashes_recorded", "shutdown_flush_complete",
    ), (SAVE3, LOG), "sram", "pocket_and_dock"),
    CaseSpec("eeprom_lifecycle", "both", (
        "absent_save_initialized", "write_persisted_after_quit", "relaunch_loaded",
        "power_cycle_loaded", "save_hashes_recorded", "shutdown_flush_complete",
    ), (SAVE3, LOG), "eeprom", "pocket_and_dock"),
    CaseSpec("console_eeprom_lifecycle", "both", (
        "fixed_paths_mono_128_color_2048", "absent_before_first_launch_both",
        "factory_files_created_both", "original_mono_bios_setup_edit",
        "original_color_bios_setup_edit", "quit_relaunch_loaded_both",
        "model_switch_isolated", "title_switch_isolated",
        "ordinary_reset_retained_both", "power_cycle_loaded_both",
        "exact_stage_snapshots_and_hashes_recorded", "shutdown_flush_complete",
    ), (
        ArtifactNeed(("save",), 14),
        ArtifactNeed(("pocket_screenshot", "photo", "video"), 2),
        LOG,
    ), "mono_color", "pocket_and_dock"),
    CaseSpec("rtc_lifecycle", "both", (
        "epoch_initialized", "minute_crossing_correct", "day_crossing_correct",
        "quit_relaunch_continues", "power_cycle_continues",
        "title_reload_no_cross_contamination", "rtc_trailer_hashes_recorded",
    ), (SAVE3, ArtifactNeed(("pocket_screenshot", "photo"), 2), LOG), "rtc", "pocket_and_dock"),
    CaseSpec("save_negative_cases", "pocket", (
        "short_rejected", "oversized_rejected", "malformed_rtc_rejected",
        "wrong_type_rejected", "type01_32k_supported",
        "legacy_eeprom_compatibility_recorded", "valid_save_recovers",
    ), (VISUAL, LOG), "save_pair"),
    CaseSpec("title_save_isolation", "pocket", (
        "two_titles_used", "paths_distinct", "payloads_distinct", "rtc_not_reused",
        "reload_each_title_correct", "hashes_recorded",
    ), (ArtifactNeed(("save",), 4), LOG), "two"),
    CaseSpec("pocket_audio", "pocket", (
        "capture_48khz", "left_right_correct", "silence_clean", "extrema_no_wrap",
        "long_run_no_pops", "no_drift",
    ), (ArtifactNeed(("audio",), 2), LOG)),
    CaseSpec("dock_audio", "dock", (
        "capture_48khz", "left_right_correct", "silence_clean", "no_channel_swap",
        "long_run_no_pops", "no_drift",
    ), (ArtifactNeed(("audio",), 2), LOG), "any", "dock_wired_gamepad"),
    CaseSpec("fastforward_menu_audio", "both", (
        "fastforward_rate_observed", "audio_enabled_mode", "audio_disabled_mode",
        "menu_entry_exit", "fastforward_not_stuck", "no_audio_pop",
    ), (ArtifactNeed(("audio",), 2), VIDEO, LOG), "any", "pocket_and_dock"),
    CaseSpec("dock_transition_lifecycle", "both", (
        "dock_undock_no_reset", "video_resync_absent", "audio_continuous",
        "input_handoff_correct", "save_not_corrupted", "rtc_continues",
    ), (VIDEO, AUDIO, ArtifactNeed(("save",), 2), LOG), "rtc", "pocket_and_dock"),
    CaseSpec("long_run_stability", "both", (
        "duration_at_least_120_minutes", "no_crash", "no_video_resync",
        "no_audio_drift", "no_stuck_input", "save_after_run_valid",
    ), (VIDEO, AUDIO, ArtifactNeed(("save",), 1), LOG), "rtc", "pocket_and_dock"),
)

CASE_BY_ID = {spec.case_id: spec for spec in CASE_SPECS}
ARTIFACT_KINDS = {"pocket_screenshot", "photo", "video", "audio", "save", "log"}


def _validate_rom_contract(rom: bytes, where: str) -> None:
    size = len(rom)
    if size < 64 * 1024 or size > 16 * 1024 * 1024:
        raise ValueError(f"{where} ROM size is outside 64 KiB..16 MiB")
    if size & (size - 1) == 0:
        return
    if size % (64 * 1024):
        raise ValueError(f"{where} non-power-of-two ROM size must be 64 KiB-aligned")

    aperture = 1 << (size - 1).bit_length()
    footer = rom[-16:]
    if footer[0] != 0xEA:
        raise ValueError(f"{where} compact ROM footer entry must begin with 0xEA")
    if footer[5] & 0x0F:
        raise ValueError(f"{where} compact ROM footer maintenance low bits must be zero")
    if footer[7] & 0xFE:
        raise ValueError(f"{where} compact ROM footer color field is invalid")
    declared_sizes = {
        0x00: 128 * 1024, 0x01: 256 * 1024, 0x02: 512 * 1024,
        0x03: 1024 * 1024, 0x04: 2 * 1024 * 1024,
        0x05: 3 * 1024 * 1024, 0x06: 4 * 1024 * 1024,
        0x07: 6 * 1024 * 1024, 0x08: 8 * 1024 * 1024,
        0x09: 16 * 1024 * 1024,
    }
    if declared_sizes.get(footer[10]) not in {size, aperture}:
        raise ValueError(f"{where} compact ROM footer size does not match file or aperture")
    if footer[11] not in {0, 1, 2, 3, 4, 5, 0x10, 0x20, 0x50}:
        raise ValueError(f"{where} compact ROM footer save type is unsupported")
    if footer[12] & 0x04 == 0:
        raise ValueError(f"{where} compact ROM footer must select the 16-bit ROM bus")
    if footer[13] > 1:
        raise ValueError(f"{where} compact ROM footer mapper is unsupported")
    stored = int.from_bytes(footer[14:16], "little")
    computed = sum(memoryview(rom)[:-2]) & 0xFFFF
    if stored != computed:
        raise ValueError(f"{where} compact ROM footer checksum mismatch")


def _object(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{where} must be an object with string keys")
    return value


def _array(value: Any, where: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"{where} must be an array")
    return value


def _keys(value: dict[str, Any], where: str, names: set[str]) -> None:
    missing = names - value.keys()
    unknown = value.keys() - names
    if missing or unknown:
        details = []
        if missing:
            details.append("missing " + ", ".join(sorted(missing)))
        if unknown:
            details.append("unknown " + ", ".join(sorted(unknown)))
        raise ValueError(f"{where} has invalid members ({'; '.join(details)})")


def _text(value: Any, where: str, maximum: int = 255) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValueError(f"{where} must be a nonempty string of at most {maximum} characters")
    if any(ord(char) < 0x20 for char in value):
        raise ValueError(f"{where} contains a control character")
    return value


def _id(value: Any, where: str) -> str:
    result = _text(value, where, 63)
    if not ID_RE.fullmatch(result):
        raise ValueError(f"{where} must match {ID_RE.pattern}")
    return result


def _utc(value: Any, where: str) -> str:
    result = _text(value, where, 20)
    if not UTC_RE.fullmatch(result):
        raise ValueError(f"{where} must be UTC YYYY-MM-DDTHH:MM:SSZ")
    try:
        dt.datetime.strptime(result, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise ValueError(f"{where} is not a valid UTC timestamp") from error
    return result


def _integer(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{where} must be a nonnegative integer")
    return value


def _load_json_bytes(path: pathlib.Path, where: str) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{where} must be a regular non-symlink file: {path}")
    try:
        data = path.read_bytes()
        return _object(json.loads(data.decode("utf-8")), where), data
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid {where}: {error}") from error


def _load_json(path: pathlib.Path, where: str) -> dict[str, Any]:
    return _load_json_bytes(path, where)[0]


def _inventory_file(base: pathlib.Path, value: Any, where: str) -> pathlib.Path:
    name = _text(value, where, 4096)
    path = pathlib.Path(name)
    if not path.is_absolute():
        path = base / path
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{where} must name a regular non-symlink file: {path}")
    return path.resolve()


def _identity(path: pathlib.Path, data: bytes | None = None) -> dict[str, Any]:
    if data is None:
        data = path.read_bytes()
    return {
        "filename": path.name,
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _unique(values: list[str], where: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{where} must be unique")


def build_environment(inventory_path: pathlib.Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate private inventory files and return public, hashed identities."""

    inventory_path = inventory_path.absolute()
    document, _inventory_bytes = _load_json_bytes(inventory_path, "hardware QA inventory")
    _keys(document, "inventory", {"hardware_qa_inventory"})
    body = _object(document["hardware_qa_inventory"], "inventory.hardware_qa_inventory")
    _keys(body, "inventory.hardware_qa_inventory", {
        "magic", "run_id", "created_at", "operator", "firmware", "pocket",
        "dock", "core", "bios", "roms", "controllers",
    })
    if body["magic"] != INVENTORY_MAGIC:
        raise ValueError(f"inventory magic must be {INVENTORY_MAGIC}")
    run_id = _id(body["run_id"], "inventory run_id")
    created_at = _utc(body["created_at"], "inventory created_at")
    operator = _object(body["operator"], "inventory operator")
    _keys(operator, "inventory operator", {"name", "organization"})
    public_operator = {
        "name": _text(operator["name"], "inventory operator name", 80),
        "organization": _text(operator["organization"], "inventory operator organization", 120),
    }
    base = inventory_path.parent

    firmware = _object(body["firmware"], "inventory firmware")
    _keys(firmware, "inventory firmware", {"version", "update_path", "expected_md5"})
    version = _text(firmware["version"], "inventory firmware version", 31)
    if not VERSION_RE.fullmatch(version):
        raise ValueError("inventory firmware version must be numeric X.Y or X.Y.Z")
    if version != OFFICIAL_FIRMWARE_VERSION:
        raise ValueError(
            "hardware QA firmware version must be the reviewed official "
            f"{OFFICIAL_FIRMWARE_VERSION}"
        )
    expected_md5 = _text(firmware["expected_md5"], "inventory firmware expected_md5", 32)
    if not MD5_RE.fullmatch(expected_md5):
        raise ValueError("inventory firmware expected_md5 must be lowercase hexadecimal")
    if expected_md5 != OFFICIAL_FIRMWARE_MD5:
        raise ValueError(
            "hardware QA firmware expected_md5 must match the reviewed official "
            f"{OFFICIAL_FIRMWARE_VERSION} identity"
        )
    firmware_path = _inventory_file(base, firmware["update_path"], "inventory firmware update_path")
    firmware_bytes = firmware_path.read_bytes()
    actual_md5 = hashlib.md5(firmware_bytes).hexdigest()  # nosec - published identity, not security
    if actual_md5 != expected_md5:
        raise ValueError("firmware update MD5 does not match inventory expected_md5")
    firmware_identity = _identity(firmware_path, firmware_bytes)
    firmware_identity["md5"] = actual_md5

    def device(value: Any, where: str, dock: bool) -> dict[str, Any]:
        item = _object(value, where)
        required = {"model", "hardware_revision", "device_id_path"}
        if dock:
            required.add("firmware_version")
        _keys(item, where, required)
        id_path = _inventory_file(base, item["device_id_path"], f"{where} device_id_path")
        id_bytes = id_path.read_bytes()
        if not id_bytes:
            raise ValueError(f"{where} device ID file must not be empty")
        result = {
            "model": _text(item["model"], f"{where} model", 80),
            "hardware_revision": _text(item["hardware_revision"], f"{where} hardware_revision", 80),
            "device_id_sha256": hashlib.sha256(id_bytes).hexdigest(),
        }
        if dock:
            result["firmware_version"] = _text(item["firmware_version"], f"{where} firmware_version", 80)
        return result

    pocket = device(body["pocket"], "inventory pocket", False)
    dock = device(body["dock"], "inventory dock", True)

    core = _object(body["core"], "inventory core")
    _keys(core, "inventory core", {"core_json_path", "raw_rbf_path", "installed_bitstream_path"})
    core_json_path = _inventory_file(base, core["core_json_path"], "inventory core_json_path")
    raw_rbf_path = _inventory_file(base, core["raw_rbf_path"], "inventory raw_rbf_path")
    installed_path = _inventory_file(base, core["installed_bitstream_path"], "inventory installed_bitstream_path")
    core_document, core_json_bytes = _load_json_bytes(core_json_path, "inventory core.json")
    try:
        definition = core_document["core"]
        metadata = definition["metadata"]
        core_id = f"{metadata['author']}.{metadata['shortname']}"
        core_version = metadata["version"]
        release_date = metadata["date_release"]
        installed_name = definition["cores"][0]["filename"]
    except (KeyError, IndexError, TypeError) as error:
        raise ValueError("inventory core.json lacks required core identity") from error
    if core_id != "agg23.WonderSwan":
        raise ValueError("hardware QA core ID must be agg23.WonderSwan")
    if installed_path.name != installed_name:
        raise ValueError("installed bitstream filename does not match core.json")
    raw_bytes = raw_rbf_path.read_bytes()
    installed_bytes = installed_path.read_bytes()
    if len(raw_bytes) < MIN_BITSTREAM_BYTES:
        raise ValueError(
            f"raw RBF is implausibly small ({len(raw_bytes)} bytes; "
            f"minimum {MIN_BITSTREAM_BYTES})"
        )
    if len(raw_bytes) != len(installed_bytes):
        raise ValueError("raw RBF and installed bitstream sizes differ")
    if raw_bytes.translate(REVERSE) != installed_bytes:
        raise ValueError("installed bitstream is not the bit-reversed raw RBF")
    core_public = {
        "core_id": core_id,
        "version": _text(core_version, "core version", 31),
        "date_release": _text(release_date, "core release date", 10),
        "core_json": _identity(core_json_path, core_json_bytes),
        "raw_rbf": _identity(raw_rbf_path, raw_bytes),
        "installed_bitstream": _identity(installed_path, installed_bytes),
    }

    bios_items = _array(body["bios"], "inventory bios")
    bios_public = []
    bios_sizes = {"bw": ("bw.rom", 4096), "color": ("color.rom", 8192)}
    for index, value in enumerate(bios_items):
        where = f"inventory bios[{index}]"
        item = _object(value, where)
        _keys(item, where, {"id", "path"})
        bios_id = _id(item["id"], f"{where} id")
        if bios_id not in bios_sizes:
            raise ValueError(f"{where} id must be bw or color")
        path = _inventory_file(base, item["path"], f"{where} path")
        expected_name, expected_size = bios_sizes[bios_id]
        bios_bytes = path.read_bytes()
        if path.name != expected_name or len(bios_bytes) != expected_size:
            raise ValueError(f"{where} must be {expected_name} with {expected_size} bytes")
        bios_public.append({"id": bios_id, "image": _identity(path, bios_bytes)})
    _unique([item["id"] for item in bios_public], "inventory BIOS IDs")
    if {item["id"] for item in bios_public} != set(bios_sizes):
        raise ValueError("inventory must contain exactly bw and color BIOS files")
    bios_public.sort(key=lambda item: item["id"])

    rom_public = []
    for index, value in enumerate(_array(body["roms"], "inventory roms")):
        where = f"inventory roms[{index}]"
        item = _object(value, where)
        _keys(item, where, {"id", "title", "path", "system", "native_orientation", "save_media", "rtc"})
        rom_id = _id(item["id"], f"{where} id")
        system = _text(item["system"], f"{where} system", 3)
        if system not in {"ws", "wsc"}:
            raise ValueError(f"{where} system must be ws or wsc")
        orientation = _text(item["native_orientation"], f"{where} native_orientation", 10)
        if orientation not in {"horizontal", "vertical", "switching"}:
            raise ValueError(f"{where} has invalid native_orientation")
        save_media = _text(item["save_media"], f"{where} save_media", 6)
        if save_media not in {"none", "sram", "eeprom"}:
            raise ValueError(f"{where} has invalid save_media")
        if not isinstance(item["rtc"], bool):
            raise ValueError(f"{where} rtc must be boolean")
        path = _inventory_file(base, item["path"], f"{where} path")
        if path.suffix.casefold() != f".{system}":
            raise ValueError(f"{where} filename extension does not match system")
        rom_bytes = path.read_bytes()
        _validate_rom_contract(rom_bytes, where)
        rom_public.append({
            "id": rom_id,
            "title": _text(item["title"], f"{where} title", 120),
            "system": system,
            "native_orientation": orientation,
            "save_media": save_media,
            "rtc": item["rtc"],
            "image": _identity(path, rom_bytes),
        })
    _unique([item["id"] for item in rom_public], "inventory ROM IDs")
    if len(rom_public) < 2:
        raise ValueError("inventory must contain at least two ROMs")
    if {item["system"] for item in rom_public} != {"ws", "wsc"}:
        raise ValueError("inventory ROMs must cover both ws and wsc")
    if not any(item["native_orientation"] == "horizontal" for item in rom_public):
        raise ValueError("inventory ROMs must include a horizontal title")
    if not any(item["native_orientation"] in {"vertical", "switching"} for item in rom_public):
        raise ValueError("inventory ROMs must include a vertical or switching title")
    if not {"sram", "eeprom"}.issubset({item["save_media"] for item in rom_public}):
        raise ValueError("inventory ROMs must cover SRAM and EEPROM")
    if not any(item["rtc"] for item in rom_public) or not any(not item["rtc"] for item in rom_public):
        raise ValueError("inventory ROMs must cover RTC and non-RTC titles")
    rom_public.sort(key=lambda item: item["id"])

    controller_public = []
    for index, value in enumerate(_array(body["controllers"], "inventory controllers")):
        where = f"inventory controllers[{index}]"
        item = _object(value, where)
        _keys(item, where, {"id", "scope", "device_type", "transport", "model", "firmware_version", "mapping_mode"})
        scope = _text(item["scope"], f"{where} scope", 6)
        device_type = _text(item["device_type"], f"{where} device_type", 8)
        transport = _text(item["transport"], f"{where} transport", 9)
        if scope not in {"pocket", "dock"}:
            raise ValueError(f"{where} scope must be pocket or dock")
        if device_type not in {"gamepad", "keyboard", "mouse"}:
            raise ValueError(f"{where} has invalid device_type")
        if transport not in {"built_in", "usb", "bluetooth", "2.4g"}:
            raise ValueError(f"{where} has invalid transport")
        if scope == "pocket" and (device_type != "gamepad" or transport != "built_in"):
            raise ValueError(f"{where} Pocket controller must be built-in gamepad")
        if scope == "dock" and transport == "built_in":
            raise ValueError(f"{where} Dock device cannot use built_in transport")
        controller_public.append({
            "id": _id(item["id"], f"{where} id"),
            "scope": scope,
            "device_type": device_type,
            "transport": transport,
            "model": _text(item["model"], f"{where} model", 120),
            "firmware_version": _text(item["firmware_version"], f"{where} firmware_version", 80),
            "mapping_mode": _text(item["mapping_mode"], f"{where} mapping_mode", 80),
        })
    _unique([item["id"] for item in controller_public], "inventory controller IDs")
    builtins = [item for item in controller_public if item["scope"] == "pocket"]
    dock_gamepads = [item for item in controller_public if item["scope"] == "dock" and item["device_type"] == "gamepad"]
    if len(builtins) != 1:
        raise ValueError("inventory must contain exactly one Pocket built-in controller")
    if not any(item["transport"] == "usb" for item in dock_gamepads):
        raise ValueError("inventory must contain a wired USB Dock gamepad")
    if not any(item["transport"] in {"bluetooth", "2.4g"} for item in dock_gamepads):
        raise ValueError("inventory must contain a wireless Dock gamepad")
    if not any(item["device_type"] == "keyboard" for item in controller_public):
        raise ValueError("inventory must contain a Dock keyboard negative case")
    if not any(item["device_type"] == "mouse" for item in controller_public):
        raise ValueError("inventory must contain a Dock mouse negative case")
    controller_public.sort(key=lambda item: item["id"])

    environment = {
        "firmware": {"version": version, "update": firmware_identity},
        "pocket": pocket,
        "dock": dock,
        "core": core_public,
        "bios": bios_public,
        "roms": rom_public,
        "controllers": controller_public,
    }
    metadata = {"run_id": run_id, "created_at": created_at, "operator": public_operator}
    return metadata, environment


def generate_manifest(inventory_path: pathlib.Path, output_path: pathlib.Path) -> None:
    metadata, environment = build_environment(inventory_path)
    output_path = output_path.absolute()
    if output_path.exists() or output_path.is_symlink():
        raise ValueError(f"refusing to overwrite hardware QA manifest: {output_path}")
    if not output_path.parent.is_dir():
        raise ValueError(f"hardware QA manifest parent does not exist: {output_path.parent}")
    cases = []
    for spec in CASE_SPECS:
        cases.append({
            "id": spec.case_id,
            "status": "pending",
            "device_mode": spec.device_mode,
            "started_at": None,
            "completed_at": None,
            "rom_ids": [],
            "controller_ids": [],
            "checks": {name: False for name in spec.checks},
            "artifact_ids": [],
            "notes": "",
        })
    document = {"hardware_qa": {
        "magic": MANIFEST_MAGIC,
        **metadata,
        "environment": environment,
        "artifacts": [],
        "cases": cases,
        "attestation": {
            "physical_hardware_observed": False,
            "results_not_inferred_from_simulation": False,
            "evidence_reviewed": False,
            "reviewer": None,
            "reviewed_at": None,
        },
    }}
    output_path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _manifest_artifact(root: pathlib.Path, value: Any, index: int) -> tuple[dict[str, Any], pathlib.Path]:
    where = f"manifest artifacts[{index}]"
    item = _object(value, where)
    _keys(item, where, {"id", "kind", "path", "label", "captured_at", "size", "sha256"})
    artifact_id = _id(item["id"], f"{where} id")
    kind = _text(item["kind"], f"{where} kind", 32)
    if kind not in ARTIFACT_KINDS:
        raise ValueError(f"{where} kind is unsupported")
    path_text = _text(item["path"], f"{where} path", 1024)
    pure = pathlib.PurePosixPath(path_text)
    if "\\" in path_text or pure.is_absolute() or not pure.parts or any(part in {".", ".."} for part in pure.parts):
        raise ValueError(f"{where} path must remain beneath the manifest directory")
    cursor = root
    for part in pure.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError(f"{where} path contains a symlink: {path_text}")
    if not cursor.is_file():
        raise ValueError(f"{where} evidence file is missing: {cursor}")
    if cursor.stat().st_nlink != 1:
        raise ValueError(f"{where} evidence file must not be a hard link: {cursor}")
    resolved_root = root.resolve()
    path = cursor.resolve()
    if not path.is_relative_to(resolved_root):
        raise ValueError(f"{where} path escapes the manifest directory")
    data = path.read_bytes()
    size = _integer(item["size"], f"{where} size")
    if not data or size != len(data):
        raise ValueError(f"{where} size does not match a nonempty evidence file")
    digest = _text(item["sha256"], f"{where} sha256", 64)
    if not SHA256_RE.fullmatch(digest) or digest != hashlib.sha256(data).hexdigest():
        raise ValueError(f"{where} SHA-256 mismatch")
    captured_at = _utc(item["captured_at"], f"{where} captured_at")
    label = _text(item["label"], f"{where} label", 160)
    suffix = path.suffix.casefold()
    if kind == "pocket_screenshot":
        if suffix != ".png" or len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
            raise ValueError(f"{where} Pocket screenshot must be a PNG")
        width, height = struct.unpack(">II", data[16:24])
        if (width, height) != (224, 144):
            raise ValueError(f"{where} Pocket screenshot must be native 224x144")
    elif kind == "photo":
        if suffix == ".png":
            if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
                raise ValueError(f"{where} photo has invalid PNG signature")
        elif suffix in {".jpg", ".jpeg"}:
            if not data.startswith(b"\xff\xd8"):
                raise ValueError(f"{where} photo has invalid JPEG signature")
        else:
            raise ValueError(f"{where} photo must be PNG or JPEG")
    elif kind == "audio":
        valid = (suffix == ".wav" and len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE") or (suffix == ".flac" and data.startswith(b"fLaC"))
        if not valid:
            raise ValueError(f"{where} audio must be WAV or FLAC")
    elif kind == "video":
        valid = (suffix in {".mp4", ".mov"} and len(data) >= 12 and data[4:8] == b"ftyp") or (suffix in {".mkv", ".webm"} and data.startswith(b"\x1aE\xdf\xa3"))
        if not valid:
            raise ValueError(f"{where} video must be MP4/MOV/MKV/WebM")
    elif kind == "log":
        try:
            data.decode("utf-8")
        except UnicodeError as error:
            raise ValueError(f"{where} log must be UTF-8") from error
    return ({
        "id": artifact_id, "kind": kind, "path": path_text, "label": label,
        "captured_at": captured_at, "size": size, "sha256": digest,
    }, path)


def _meets_rom_requirement(requirement: str, selected: list[dict[str, Any]]) -> bool:
    if requirement == "any":
        return len(selected) == 1
    if requirement == "compact_896k":
        return (
            len(selected) == 1
            and selected[0]["image"]["size"] == 917_504
            and selected[0]["image"]["sha256"] == COMPACT_896K_PROBE_SHA256
        )
    if requirement == "horizontal":
        return len(selected) == 1 and selected[0]["native_orientation"] == "horizontal"
    if requirement == "vertical":
        return len(selected) == 1 and selected[0]["native_orientation"] in {"vertical", "switching"}
    if requirement == "both_orientations":
        return len(selected) == 2 and any(item["native_orientation"] == "horizontal" for item in selected) and any(item["native_orientation"] in {"vertical", "switching"} for item in selected)
    if requirement in {"sram", "eeprom"}:
        return len(selected) == 1 and selected[0]["save_media"] == requirement
    if requirement == "rtc":
        return len(selected) == 1 and selected[0]["rtc"] is True
    if requirement == "save_pair":
        return len(selected) == 2 and {item["save_media"] for item in selected} == {"sram", "eeprom"}
    if requirement == "mono_color":
        return len(selected) == 2 and {item["system"] for item in selected} == {"ws", "wsc"}
    if requirement == "two":
        return len(selected) == 2
    raise AssertionError(requirement)


def _validate_console_eeprom_snapshots(
    selected: list[dict[str, Any]], where: str
) -> None:
    """Require exact, hash-related mono/Color snapshots at every lifecycle edge."""

    saves = [item for item in selected if item["kind"] == "save"]
    snapshots: dict[tuple[str, str], dict[str, Any]] = {}
    for model, size in CONSOLE_EEPROM_SNAPSHOT_SIZES.items():
        for stage in CONSOLE_EEPROM_SNAPSHOT_STAGES:
            label = f"console-eeprom {model} {stage}"
            matches = [item for item in saves if item["label"] == label]
            if len(matches) != 1:
                raise ValueError(f"{where} needs exactly one save artifact labeled {label!r}")
            snapshot = matches[0]
            if snapshot["size"] != size:
                raise ValueError(
                    f"{where} {label!r} must be the exact fixed {size}-byte image"
                )
            snapshots[(model, stage)] = snapshot

        factory_hash = snapshots[(model, "factory-created")]["sha256"]
        edited_hash = snapshots[(model, "setup-edited")]["sha256"]
        if edited_hash == factory_hash:
            raise ValueError(
                f"{where} {model} original-BIOS setup edit did not change the factory image"
            )
        for stage in CONSOLE_EEPROM_SNAPSHOT_STAGES[2:]:
            if snapshots[(model, stage)]["sha256"] != edited_hash:
                raise ValueError(
                    f"{where} {model} {stage} snapshot does not match the setup-edited image"
                )


def _meets_controller_requirement(requirement: str, selected: list[dict[str, Any]]) -> bool:
    pocket = [item for item in selected if item["scope"] == "pocket"]
    dock_gamepads = [item for item in selected if item["scope"] == "dock" and item["device_type"] == "gamepad"]
    wired = [item for item in dock_gamepads if item["transport"] == "usb"]
    wireless = [item for item in dock_gamepads if item["transport"] in {"bluetooth", "2.4g"}]
    if requirement == "pocket":
        return len(selected) == 1 and len(pocket) == 1
    if requirement == "dock_wired_gamepad":
        return len(selected) == 1 and len(wired) == 1
    if requirement == "dock_wireless_gamepad":
        return len(selected) == 1 and len(wireless) == 1
    if requirement == "dock_gamepads":
        return len(selected) == 2 and len(wired) == 1 and len(wireless) == 1
    if requirement == "pocket_and_dock":
        return len(selected) == 2 and len(pocket) == 1 and len(dock_gamepads) == 1
    if requirement == "unsupported_devices":
        return len(selected) == 4 and len(wired) == 1 and len(wireless) == 1 and sum(item["device_type"] == "keyboard" for item in selected) == 1 and sum(item["device_type"] == "mouse" for item in selected) == 1
    raise AssertionError(requirement)


def verify_manifest(manifest_path: pathlib.Path, inventory_path: pathlib.Path, *, require_pass: bool = True) -> dict[str, Any]:
    """Validate identities, coverage, hashes, and a human attestation.

    Success establishes internal integrity of the supplied record. It does not
    mechanically establish that the human's physical claims are true.
    """

    manifest_path = manifest_path.absolute()
    document, manifest_bytes = _load_json_bytes(manifest_path, "hardware QA manifest")
    _keys(document, "manifest", {"hardware_qa"})
    body = _object(document["hardware_qa"], "manifest.hardware_qa")
    _keys(body, "manifest.hardware_qa", {
        "magic", "run_id", "created_at", "operator", "environment", "artifacts",
        "cases", "attestation",
    })
    if body["magic"] != MANIFEST_MAGIC:
        raise ValueError(f"manifest magic must be {MANIFEST_MAGIC}")
    expected_metadata, expected_environment = build_environment(inventory_path)
    for key in ("run_id", "created_at", "operator"):
        if body[key] != expected_metadata[key]:
            raise ValueError(f"manifest {key} does not match private inventory")
    if body["environment"] != expected_environment:
        raise ValueError("manifest environment identities do not match private inventory")

    root = manifest_path.parent
    artifacts: dict[str, dict[str, Any]] = {}
    artifact_paths: list[pathlib.Path] = []
    for index, value in enumerate(_array(body["artifacts"], "manifest artifacts")):
        artifact, path = _manifest_artifact(root, value, index)
        if artifact["id"] in artifacts:
            raise ValueError("manifest artifact IDs must be unique")
        artifacts[artifact["id"]] = artifact
        artifact_paths.append(path)
    if len(artifact_paths) != len(set(artifact_paths)):
        raise ValueError("manifest artifact paths must be unique")

    case_values = _array(body["cases"], "manifest cases")
    case_ids = []
    referenced_artifacts: set[str] = set()
    artifact_owner: dict[str, str] = {}
    rom_by_id = {item["id"]: item for item in expected_environment["roms"]}
    controller_by_id = {item["id"]: item for item in expected_environment["controllers"]}
    for index, value in enumerate(case_values):
        where = f"manifest cases[{index}]"
        case = _object(value, where)
        _keys(case, where, {"id", "status", "device_mode", "started_at", "completed_at", "rom_ids", "controller_ids", "checks", "artifact_ids", "notes"})
        case_id = _id(case["id"], f"{where} id")
        case_ids.append(case_id)
        if case_id not in CASE_BY_ID:
            raise ValueError(f"{where} has unknown required-case ID {case_id}")
        spec = CASE_BY_ID[case_id]
        if case["device_mode"] != spec.device_mode:
            raise ValueError(f"{where} device_mode changed")
        status = case["status"]
        if status not in {"pending", "pass", "fail"}:
            raise ValueError(f"{where} status must be pending, pass, or fail")
        checks = _object(case["checks"], f"{where} checks")
        _keys(checks, f"{where} checks", set(spec.checks))
        if not all(isinstance(value, bool) for value in checks.values()):
            raise ValueError(f"{where} checks must be booleans")
        rom_ids = [_id(item, f"{where} rom_ids") for item in _array(case["rom_ids"], f"{where} rom_ids")]
        controller_ids = [_id(item, f"{where} controller_ids") for item in _array(case["controller_ids"], f"{where} controller_ids")]
        artifact_ids = [_id(item, f"{where} artifact_ids") for item in _array(case["artifact_ids"], f"{where} artifact_ids")]
        _unique(rom_ids, f"{where} rom_ids")
        _unique(controller_ids, f"{where} controller_ids")
        _unique(artifact_ids, f"{where} artifact_ids")
        unknown_roms = set(rom_ids) - rom_by_id.keys()
        unknown_controllers = set(controller_ids) - controller_by_id.keys()
        unknown_artifacts = set(artifact_ids) - artifacts.keys()
        if unknown_roms or unknown_controllers or unknown_artifacts:
            raise ValueError(f"{where} references unknown ROM/controller/artifact IDs")

        if status == "pending":
            if case["started_at"] is not None or case["completed_at"] is not None or rom_ids or controller_ids or artifact_ids or case["notes"] != "" or any(checks.values()):
                raise ValueError(f"{where} pending case must remain an empty generated skeleton")
            if require_pass:
                raise ValueError(f"hardware QA case is not accepted: {case_id}=pending")
            continue

        started = _utc(case["started_at"], f"{where} started_at")
        completed = _utc(case["completed_at"], f"{where} completed_at")
        if started > completed:
            raise ValueError(f"{where} completes before it starts")
        _text(case["notes"], f"{where} notes", 4000)
        if status != "pass" or not all(checks.values()):
            if require_pass:
                raise ValueError(f"hardware QA case is not accepted: {case_id}={status}")
            continue
        selected_roms = [rom_by_id[item] for item in rom_ids]
        selected_controllers = [controller_by_id[item] for item in controller_ids]
        if not _meets_rom_requirement(spec.rom_requirement, selected_roms):
            raise ValueError(f"{where} ROM selection does not satisfy {spec.rom_requirement}")
        if not _meets_controller_requirement(spec.controller_requirement, selected_controllers):
            raise ValueError(f"{where} controller selection does not satisfy {spec.controller_requirement}")
        selected_artifacts = [artifacts[item] for item in artifact_ids]
        for need in spec.needs:
            count = sum(item["kind"] in need.kinds for item in selected_artifacts)
            if count < need.minimum:
                raise ValueError(f"{where} needs {need.minimum} artifact(s) of {','.join(need.kinds)}")
        if case_id == "console_eeprom_lifecycle":
            _validate_console_eeprom_snapshots(selected_artifacts, where)
        for artifact in selected_artifacts:
            if not started <= artifact["captured_at"] <= completed:
                raise ValueError(f"{where} references evidence captured outside its test interval")
        for artifact_id in artifact_ids:
            previous_owner = artifact_owner.get(artifact_id)
            if previous_owner is not None and previous_owner != case_id:
                raise ValueError(
                    f"evidence artifact {artifact_id} is reused by distinct cases "
                    f"{previous_owner} and {case_id}"
                )
            artifact_owner[artifact_id] = case_id
        referenced_artifacts.update(artifact_ids)

    _unique(case_ids, "manifest case IDs")
    if set(case_ids) != set(CASE_BY_ID) or len(case_ids) != len(CASE_BY_ID):
        missing = sorted(set(CASE_BY_ID) - set(case_ids))
        raise ValueError("manifest does not contain the exact hardware QA case catalogue" + (": " + ", ".join(missing) if missing else ""))
    unused = set(artifacts) - referenced_artifacts
    if unused and require_pass:
        raise ValueError("manifest contains unreferenced evidence artifacts: " + ", ".join(sorted(unused)))

    attestation = _object(body["attestation"], "manifest attestation")
    _keys(attestation, "manifest attestation", {"physical_hardware_observed", "results_not_inferred_from_simulation", "evidence_reviewed", "reviewer", "reviewed_at"})
    for name in ("physical_hardware_observed", "results_not_inferred_from_simulation", "evidence_reviewed"):
        if not isinstance(attestation[name], bool):
            raise ValueError(f"manifest attestation {name} must be boolean")
    if require_pass:
        if not all(attestation[name] is True for name in ("physical_hardware_observed", "results_not_inferred_from_simulation", "evidence_reviewed")):
            raise ValueError("hardware QA attestation is not accepted")
        _text(attestation["reviewer"], "manifest attestation reviewer", 120)
        _utc(attestation["reviewed_at"], "manifest attestation reviewed_at")
    else:
        if attestation["reviewer"] is not None:
            _text(attestation["reviewer"], "manifest attestation reviewer", 120)
        if attestation["reviewed_at"] is not None:
            _utc(attestation["reviewed_at"], "manifest attestation reviewed_at")

    return {
        "run_id": expected_metadata["run_id"],
        "cases": len(CASE_SPECS),
        "artifacts": len(artifacts),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    generate = subparsers.add_parser("generate", help="hash inventory and create an all-pending manifest")
    generate.add_argument("--inventory", required=True, type=pathlib.Path)
    generate.add_argument("--output", required=True, type=pathlib.Path)
    verify = subparsers.add_parser("verify", help="validate complete schema, hashes, and human attestation")
    verify.add_argument("--inventory", required=True, type=pathlib.Path)
    verify.add_argument("--manifest", required=True, type=pathlib.Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "generate":
            generate_manifest(args.inventory, args.output)
            print(f"WROTE pending hardware QA manifest: {args.output}")
            print("NOT ACCEPTED: every physical case and attestation remains pending")
        else:
            summary = verify_manifest(args.manifest, args.inventory)
            print(
                "VALID evidence schema, hashes, and human attestation "
                f"run={summary['run_id']} cases={summary['cases']} "
                f"artifacts={summary['artifacts']} sha256={summary['manifest_sha256']}"
            )
            print("NOT MECHANICAL PROOF: a reviewer remains responsible for physical truth")
    except ValueError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
