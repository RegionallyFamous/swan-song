#!/usr/bin/env python3
"""Adversarial tests for pocket_per_game_preset.py."""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import pocket_per_game_preset as preset
from pocket_per_game_preset import (
    DEFAULT_DEFINITIONS,
    PresetError,
    PresetOptions,
    build_input_document,
    generate_presets,
    preset_relative_path,
)


SCRIPT = pathlib.Path(__file__).with_name("pocket_per_game_preset.py")


class PocketPerGamePresetTests(unittest.TestCase):
    def _root(self, directory: str) -> pathlib.Path:
        root = pathlib.Path(directory) / "sd"
        root.mkdir()
        return root.resolve()

    def test_documented_path_mirroring_and_selected_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            result = generate_presets(
                sd_root=root,
                asset="/Assets/wonderswan/common/Vertical/Example.wsc",
                options=PresetOptions(
                    orientation="vertical",
                    control_layout="vertical",
                    landscape_180="off",
                    color_profile="ares",
                    triple_buffer="off",
                    flicker="persistence",
                    cpu_turbo="on",
                    fast_forward_audio="off",
                    controls="per-game",
                ),
            )

            expected_suffix = pathlib.Path(
                "Presets/RegionallyFamous.SwanSong/Interact/"
                "wonderswan/common/Vertical/Example.json"
            )
            self.assertEqual(result.interact_path, root / expected_suffix)
            self.assertEqual(
                result.input_path,
                root
                / "Presets/RegionallyFamous.SwanSong/Input/"
                "wonderswan/common/Vertical/Example.json",
            )

            interact = json.loads(result.interact_path.read_text(encoding="utf-8"))
            variables = {
                variable["id"]: variable
                for variable in interact["interact"]["variables"]
            }
            self.assertEqual(variables[14]["defaultval"], 1)
            self.assertEqual(variables[41]["defaultval"], 0)
            self.assertEqual(variables[42]["defaultval"], 2)
            self.assertEqual(variables[43]["defaultval"], 2)
            self.assertEqual(variables[44]["defaultval"], 0)
            self.assertEqual(variables[45]["defaultval"], 1)
            self.assertEqual(variables[46]["defaultval"], 2)
            self.assertEqual(variables[81]["defaultval"], 0)

            self.assertEqual(
                json.loads(result.input_path.read_text(encoding="utf-8")),
                build_input_document(DEFAULT_DEFINITIONS),
            )

    def test_relative_asset_form_and_case_insensitive_extension(self) -> None:
        self.assertEqual(
            preset_relative_path("nested/Game.WS"),
            pathlib.PurePosixPath("wonderswan/common/nested/Game.json"),
        )

    def test_legacy_three_frame_name_is_a_deterministic_persistence_alias(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = pathlib.Path(directory)
            canonical_root = base / "canonical"
            legacy_root = base / "legacy"
            canonical_root.mkdir()
            legacy_root.mkdir()
            canonical = generate_presets(
                sd_root=canonical_root,
                asset="Game.ws",
                options=PresetOptions(flicker="persistence"),
            )
            legacy = generate_presets(
                sd_root=legacy_root,
                asset="Game.ws",
                options=PresetOptions(flicker="3-frame"),
            )
            self.assertEqual(
                canonical.interact_path.read_bytes(), legacy.interact_path.read_bytes()
            )

    def test_output_is_deterministic_and_contains_no_rom_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = pathlib.Path(directory)
            root_a = base / "a"
            root_b = base / "b"
            root_a.mkdir()
            root_b.mkdir()
            secret = "My Personally Dumped Cartridge.wsc"
            a = generate_presets(sd_root=root_a, asset=f"Private/{secret}")
            b = generate_presets(sd_root=root_b, asset=f"Private/{secret}")

            self.assertEqual(a.interact_path.read_bytes(), b.interact_path.read_bytes())
            self.assertEqual(a.input_path.read_bytes(), b.input_path.read_bytes())
            for output in (a.interact_path, a.input_path):
                payload = output.read_bytes()
                self.assertNotIn(secret.encode(), payload)
                self.assertNotIn(b"Private", payload)
                self.assertNotIn(b"crc", payload.lower())
                self.assertNotIn(b"sha", payload.lower())

    def test_asset_does_not_need_to_exist_and_is_never_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            result = generate_presets(
                sd_root=root,
                asset="A folder/Definitely absent.ws",
            )
            self.assertTrue(result.interact_path.is_file())
            self.assertTrue(result.input_path.is_file())

    def test_generator_never_modifies_host_owned_settings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            settings = (
                root
                / "Settings/RegionallyFamous.SwanSong/Interact/"
                "wonderswan/common/Game.json"
            )
            settings.parent.mkdir(parents=True)
            settings.write_bytes(b"host-owned-persistent-values")

            generate_presets(sd_root=root, asset="Game.ws", force=True)
            self.assertEqual(settings.read_bytes(), b"host-owned-persistent-values")

    def test_inherit_controls_writes_only_interact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            result = generate_presets(
                sd_root=root,
                asset="Game.ws",
                options=PresetOptions(controls="inherit"),
            )
            self.assertIsNone(result.input_path)
            self.assertTrue(result.interact_path.is_file())
            self.assertFalse(
                (root / "Presets/RegionallyFamous.SwanSong/Input").exists()
            )

    def test_refuses_overwrite_then_force_replaces_both_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            first = generate_presets(sd_root=root, asset="Game.ws")
            first.interact_path.write_text("not json", encoding="utf-8")
            with self.assertRaisesRegex(PresetError, "already exists"):
                generate_presets(sd_root=root, asset="Game.ws")
            self.assertEqual(first.interact_path.read_text(encoding="utf-8"), "not json")

            replaced = generate_presets(sd_root=root, asset="Game.ws", force=True)
            self.assertEqual(
                json.loads(replaced.interact_path.read_text(encoding="utf-8"))["interact"][
                    "magic"
                ],
                "APF_VER_1",
            )
            self.assertEqual(
                json.loads(replaced.input_path.read_text(encoding="utf-8"))["input"][
                    "magic"
                ],
                "APF_VER_1",
            )

    def test_preflight_conflict_does_not_write_the_other_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            relative = pathlib.Path("wonderswan/common/Game.json")
            existing_input = (
                root / "Presets/RegionallyFamous.SwanSong/Input" / relative
            )
            existing_input.parent.mkdir(parents=True)
            existing_input.write_text("mine", encoding="utf-8")

            with self.assertRaisesRegex(PresetError, "already exists"):
                generate_presets(sd_root=root, asset="Game.ws")
            self.assertFalse(
                (
                    root / "Presets/RegionallyFamous.SwanSong/Interact" / relative
                ).exists()
            )
            self.assertEqual(existing_input.read_text(encoding="utf-8"), "mine")

    def test_concurrent_destination_creation_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            original = preset._rename_noreplace_at
            actor_payload = b"concurrent owner"
            actor_path: pathlib.Path | None = None

            def create_before_publish(
                source_directory: int,
                source: str,
                destination_directory: int,
                destination: str,
            ) -> None:
                nonlocal actor_path
                if actor_path is None and source.endswith(".tmp"):
                    descriptor = os.open(
                        destination,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                        0o600,
                        dir_fd=destination_directory,
                    )
                    with os.fdopen(descriptor, "wb") as stream:
                        stream.write(actor_payload)
                    actor_path = (
                        root
                        / "Presets/RegionallyFamous.SwanSong/Interact/"
                        "wonderswan/common/Game.json"
                    )
                original(
                    source_directory,
                    source,
                    destination_directory,
                    destination,
                )

            with mock.patch.object(
                preset, "_rename_noreplace_at", create_before_publish
            ):
                with self.assertRaisesRegex(PresetError, "concurrently"):
                    generate_presets(sd_root=root, asset="Game.ws")
            self.assertIsNotNone(actor_path)
            self.assertEqual(actor_path.read_bytes(), actor_payload)
            self.assertFalse(
                (
                    root
                    / "Presets/RegionallyFamous.SwanSong/Input/"
                    "wonderswan/common/Game.json"
                ).exists()
            )

    def test_pair_failure_rolls_back_first_preset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            original = preset._rename_noreplace_at
            publishes = 0

            def fail_second_publish(
                source_directory: int,
                source: str,
                destination_directory: int,
                destination: str,
            ) -> None:
                nonlocal publishes
                if source.endswith(".tmp"):
                    publishes += 1
                    if publishes == 2:
                        raise OSError("injected second-preset failure")
                original(
                    source_directory,
                    source,
                    destination_directory,
                    destination,
                )

            with mock.patch.object(
                preset, "_rename_noreplace_at", fail_second_publish
            ):
                with self.assertRaisesRegex(OSError, "second-preset"):
                    generate_presets(sd_root=root, asset="Game.ws")
            self.assertEqual(list(root.rglob("*.json")), [])
            self.assertEqual(list(root.rglob("*.tmp")), [])
            self.assertEqual(list(root.rglob("*.original")), [])

    def test_force_failure_restores_original_pair_inodes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            result = generate_presets(sd_root=root, asset="Game.ws")
            result.interact_path.write_bytes(b"original interact")
            result.input_path.write_bytes(b"original input")
            before = {
                path: (path.read_bytes(), path.stat().st_ino)
                for path in (result.interact_path, result.input_path)
            }
            original = preset._rename_noreplace_at

            def fail_input_publish(
                source_directory: int,
                source: str,
                destination_directory: int,
                destination: str,
            ) -> None:
                if source.endswith(".tmp"):
                    # Parent descriptors do not expose their path portably;
                    # Input is the second temporary publication.
                    fail_input_publish.publishes += 1
                    if fail_input_publish.publishes == 2:
                        raise OSError("injected forced-pair failure")
                original(
                    source_directory,
                    source,
                    destination_directory,
                    destination,
                )

            fail_input_publish.publishes = 0
            with mock.patch.object(
                preset, "_rename_noreplace_at", fail_input_publish
            ):
                with self.assertRaisesRegex(OSError, "forced-pair"):
                    generate_presets(sd_root=root, asset="Game.ws", force=True)
            for path, identity in before.items():
                self.assertEqual((path.read_bytes(), path.stat().st_ino), identity)

    def test_force_detects_and_preserves_concurrent_replacement_inode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            result = generate_presets(sd_root=root, asset="Game.ws")
            original = preset._rename_noreplace_at
            actor_payload = b"concurrent replacement"
            actor_identity: tuple[int, int] | None = None
            replaced = False

            def replace_before_backup(
                source_directory: int,
                source: str,
                destination_directory: int,
                destination: str,
            ) -> None:
                nonlocal actor_identity, replaced
                if not replaced and destination.endswith(".original"):
                    os.unlink(source, dir_fd=source_directory)
                    descriptor = os.open(
                        source,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                        0o600,
                        dir_fd=source_directory,
                    )
                    with os.fdopen(descriptor, "wb") as stream:
                        stream.write(actor_payload)
                        metadata = os.fstat(stream.fileno())
                    actor_identity = (metadata.st_dev, metadata.st_ino)
                    replaced = True
                original(
                    source_directory,
                    source,
                    destination_directory,
                    destination,
                )

            with mock.patch.object(
                preset, "_rename_noreplace_at", replace_before_backup
            ):
                with self.assertRaisesRegex(PresetError, "changed after preflight"):
                    generate_presets(sd_root=root, asset="Game.ws", force=True)
            self.assertTrue(replaced)
            self.assertEqual(result.interact_path.read_bytes(), actor_payload)
            metadata = result.interact_path.stat()
            self.assertEqual((metadata.st_dev, metadata.st_ino), actor_identity)

    def test_root_swap_during_publish_never_writes_outside_and_rolls_back(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = pathlib.Path(directory)
            root = self._root(directory)
            detached = base / "detached"
            outside = base / "outside"
            outside.mkdir()
            original = preset._rename_noreplace_at
            swapped = False

            def swap_root(
                source_directory: int,
                source: str,
                destination_directory: int,
                destination: str,
            ) -> None:
                nonlocal swapped
                if not swapped and source.endswith(".tmp"):
                    root.rename(detached)
                    root.symlink_to(outside, target_is_directory=True)
                    swapped = True
                original(
                    source_directory,
                    source,
                    destination_directory,
                    destination,
                )

            with mock.patch.object(preset, "_rename_noreplace_at", swap_root):
                with self.assertRaisesRegex(PresetError, "root identity changed"):
                    generate_presets(sd_root=root, asset="Game.ws")
            self.assertTrue(swapped)
            self.assertEqual(list(outside.rglob("*.json")), [])
            self.assertEqual(list(detached.rglob("*.json")), [])

    def test_root_swap_during_validation_is_rejected_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = pathlib.Path(directory)
            root = self._root(directory)
            detached = base / "validation-detached"
            outside = base / "validation-outside"
            outside.mkdir()
            original_resolve = pathlib.Path.resolve
            swapped = False

            def swap_before_resolve(
                path: pathlib.Path, *args: object, **kwargs: object
            ) -> pathlib.Path:
                nonlocal swapped
                if path == root and not swapped:
                    root.rename(detached)
                    root.symlink_to(outside, target_is_directory=True)
                    swapped = True
                return original_resolve(path, *args, **kwargs)

            with mock.patch.object(pathlib.Path, "resolve", swap_before_resolve):
                with self.assertRaisesRegex(PresetError, "identity changed"):
                    generate_presets(sd_root=root, asset="Game.ws")
            self.assertTrue(swapped)
            self.assertEqual(list(outside.iterdir()), [])
            self.assertEqual(list(detached.rglob("*.json")), [])

    def test_parent_swap_during_publish_never_follows_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = pathlib.Path(directory)
            root = self._root(directory)
            outside = base / "outside"
            outside.mkdir()
            detached = base / "detached-presets"
            original = preset._rename_noreplace_at
            swapped = False

            def swap_parent(
                source_directory: int,
                source: str,
                destination_directory: int,
                destination: str,
            ) -> None:
                nonlocal swapped
                if not swapped and source.endswith(".tmp"):
                    (root / "Presets").rename(detached)
                    (root / "Presets").symlink_to(
                        outside, target_is_directory=True
                    )
                    swapped = True
                original(
                    source_directory,
                    source,
                    destination_directory,
                    destination,
                )

            with mock.patch.object(preset, "_rename_noreplace_at", swap_parent):
                with self.assertRaisesRegex(PresetError, "parent"):
                    generate_presets(sd_root=root, asset="Game.ws")
            self.assertTrue(swapped)
            self.assertEqual(list(outside.rglob("*.json")), [])
            self.assertEqual(list(detached.rglob("*.json")), [])

    def test_rejects_traversal_wrong_roots_and_malformed_paths(self) -> None:
        invalid = (
            "",
            "../Game.ws",
            "Games/../Game.ws",
            "Games/./Game.ws",
            "Games//Game.ws",
            "Games\\Game.ws",
            "/Assets/wonderswan/other/Game.ws",
            "/Assets/other/common/Game.ws",
            "/Presets/RegionallyFamous.SwanSong/Game.ws",
            "Game.rom",
            ".ws",
            "Game.ws\x00ignored",
            "Game.ws\n",
        )
        for asset in invalid:
            with self.subTest(asset=repr(asset)):
                with self.assertRaises(PresetError):
                    preset_relative_path(asset)

    def test_rejects_core_id_path_injection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            for core_id in ("agg23", "../evil.Core", "A.B/C", "A..B", ".Core"):
                with self.subTest(core_id=core_id):
                    with self.assertRaises(PresetError):
                        generate_presets(
                            sd_root=root,
                            asset="Game.ws",
                            core_id=core_id,
                        )

    def test_rejects_symlink_root_and_symlink_inside_output_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = pathlib.Path(directory)
            real = base / "real"
            real.mkdir()
            linked_root = base / "linked"
            linked_root.symlink_to(real, target_is_directory=True)
            with self.assertRaisesRegex(PresetError, "non-symlink"):
                generate_presets(sd_root=linked_root, asset="Game.ws")

            outside = base / "outside"
            outside.mkdir()
            (real / "Presets").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(PresetError, "symlink"):
                generate_presets(sd_root=real, asset="Game.ws")
            self.assertEqual(list(outside.iterdir()), [])

    def test_rejects_ineffective_vertical_landscape_180_combination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            with self.assertRaisesRegex(PresetError, "no effect"):
                generate_presets(
                    sd_root=root,
                    asset="Game.ws",
                    options=PresetOptions(
                        orientation="vertical", landscape_180="on"
                    ),
                )

    def test_library_call_rejects_invalid_option_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            with self.assertRaisesRegex(PresetError, "unsupported orientation"):
                generate_presets(
                    sd_root=root,
                    asset="Game.ws",
                    options=PresetOptions(orientation="diagonal"),
                )
            with self.assertRaisesRegex(PresetError, "unsupported control-layout"):
                generate_presets(
                    sd_root=root,
                    asset="Game.ws",
                    options=PresetOptions(control_layout="diagonal"),
                )

    def test_definition_drift_fails_closed_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = pathlib.Path(directory)
            root = self._root(directory)
            definitions = base / "definitions"
            shutil.copytree(DEFAULT_DEFINITIONS, definitions)
            interact_path = definitions / "interact.json"
            interact = json.loads(interact_path.read_text(encoding="utf-8"))
            for variable in interact["interact"]["variables"]:
                if variable["id"] == 43:
                    variable["address"] = "0xDEADBEEF"
            interact_path.write_text(json.dumps(interact), encoding="utf-8")

            with self.assertRaisesRegex(PresetError, "no longer matches"):
                generate_presets(
                    sd_root=root,
                    asset="Game.ws",
                    definitions=definitions,
                )
            self.assertFalse((root / "Presets").exists())

    def test_input_mapping_drift_fails_closed_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = pathlib.Path(directory)
            root = self._root(directory)
            definitions = base / "definitions"
            shutil.copytree(DEFAULT_DEFINITIONS, definitions)
            input_path = definitions / "input.json"
            input_document = json.loads(input_path.read_text(encoding="utf-8"))
            input_document["input"]["controllers"][0]["mappings"][0]["key"] = (
                "pad_btn_b"
            )
            input_path.write_text(json.dumps(input_document), encoding="utf-8")

            with self.assertRaisesRegex(PresetError, "eight verified"):
                generate_presets(
                    sd_root=root,
                    asset="Game.ws",
                    definitions=definitions,
                )
            self.assertFalse((root / "Presets").exists())

    def test_interact_option_value_drift_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = pathlib.Path(directory)
            root = self._root(directory)
            definitions = base / "definitions"
            shutil.copytree(DEFAULT_DEFINITIONS, definitions)
            interact_path = definitions / "interact.json"
            interact = json.loads(interact_path.read_text(encoding="utf-8"))
            for variable in interact["interact"]["variables"]:
                if variable["id"] == 45:
                    variable["options"][1]["value"] = 7
            interact_path.write_text(json.dumps(interact), encoding="utf-8")

            with self.assertRaisesRegex(PresetError, "expected option values"):
                generate_presets(
                    sd_root=root,
                    asset="Game.ws",
                    definitions=definitions,
                )
            self.assertFalse((root / "Presets").exists())

    def test_cli_success_and_error_are_unambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            success = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--sd-root",
                    str(root),
                    "--asset",
                    "Games/Example.ws",
                    "--orientation",
                    "horizontal",
                    "--control-layout",
                    "vertical",
                    "--color-profile",
                    "ares",
                    "--lcd-response",
                    "persistence",
                    "--cpu-turbo",
                    "on",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(success.returncode, 0, success.stderr)
            self.assertIn("Interact:", success.stdout)
            self.assertIn("Input:", success.stdout)
            self.assertEqual(success.stderr, "")
            generated = json.loads(
                (
                    root
                    / "Presets/RegionallyFamous.SwanSong/Interact/"
                    "wonderswan/common/Games/Example.json"
                ).read_text(encoding="utf-8")
            )
            generated_by_id = {
                item["id"]: item for item in generated["interact"]["variables"]
            }
            self.assertEqual(generated_by_id[46]["defaultval"], 2)

            failure = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--sd-root",
                    str(root),
                    "--asset",
                    "../escape.ws",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(failure.returncode, 2)
            self.assertIn("error:", failure.stderr)

    def test_cli_does_not_claim_to_pre_remap_controls(self) -> None:
        help_result = subprocess.run(
            [sys.executable, str(SCRIPT), "--help"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        normalized_help = " ".join(help_result.stdout.split())
        self.assertIn(
            "per-game creates a per-asset APF Controls definition/namespace",
            normalized_help,
        )
        self.assertIn("it does not pre-remap buttons", normalized_help)
        self.assertIn("remap them in Pocket OS", normalized_help)


if __name__ == "__main__":
    unittest.main()
