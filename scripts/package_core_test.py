#!/usr/bin/env python3
"""Focused offline tests for Chip32 materialization and APF packaging."""

import hashlib
import json
import os
import pathlib
import shutil
import tempfile
import unittest
import zipfile

from build_chip32 import (
    EXPECTED_IMAGE_SHA256,
    EXPECTED_IMAGE_SIZE,
    chip32_image,
)
from package_core import create_package
from reverse_rbf import REVERSE


ROOT = pathlib.Path(__file__).resolve().parent.parent
ASSEMBLY = ROOT / "src/support/chip32.asm"
ENCODED_IMAGE = ROOT / "src/support/chip32.bin.hex"
CORE_DIRECTORY = pathlib.PurePosixPath("Cores/agg23.WonderSwan")


class PackageCoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="swan-song-package-test-")
        self.root = pathlib.Path(self.temporary.name)
        self.dist = self.root / "dist"
        shutil.copytree(ROOT / "dist", self.dist)
        self.rbf = self.root / "ap_core.rbf"
        self.rbf_bytes = bytes((0x00, 0x01, 0x80, 0xFF, 0x55, 0xAA))
        self.rbf.write_bytes(self.rbf_bytes)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def package(self, output: pathlib.Path, **overrides: pathlib.Path) -> None:
        arguments = {
            "dist": self.dist,
            "rbf": self.rbf,
            "output": output,
            "chip32_assembly": ASSEMBLY,
            "chip32_encoded_image": ENCODED_IMAGE,
        }
        arguments.update(overrides)
        create_package(**arguments)

    def core_json_path(self) -> pathlib.Path:
        return self.dist / CORE_DIRECTORY / "core.json"

    def reset_dist(self) -> None:
        shutil.rmtree(self.dist)
        shutil.copytree(ROOT / "dist", self.dist)

    def mutate_core_json(self, mutation) -> None:
        path = self.core_json_path()
        definition = json.loads(path.read_text(encoding="utf-8"))
        mutation(definition)
        path.write_text(json.dumps(definition), encoding="utf-8")

    def mutate_json(self, relative: pathlib.PurePosixPath, mutation) -> None:
        path = self.dist / relative
        definition = json.loads(path.read_text(encoding="utf-8"))
        mutation(definition)
        path.write_text(json.dumps(definition), encoding="utf-8")

    @staticmethod
    def provenance_path(output: pathlib.Path) -> pathlib.Path:
        return output.with_name(output.name + ".provenance.json")

    def build_evidence(self, **gate_overrides: bool) -> pathlib.Path:
        evidence_directory = self.root / "evidence"
        evidence_directory.mkdir(exist_ok=True)
        build_id_contents = (
            "-- Reproducible source commit: " + "1" * 40 + "\n"
            "-- SOURCE_DATE_EPOCH: 1700000000\n"
            "0E0 : 20231114;\n"
            "0E1 : 00221320;\n"
            "0E2 : 11111111;\n"
        ).encode()
        (evidence_directory / "build_id.mif").write_bytes(build_id_contents)
        reports = {}
        for kind in ("flow", "fit", "sta"):
            filename = f"ap_core.{kind}.rpt"
            contents = f"Quartus Prime Version 21.1.1\nsynthetic {kind} report\n".encode()
            (evidence_directory / filename).write_bytes(contents)
            reports[kind] = {
                "filename": filename,
                "size": len(contents),
                "sha256": hashlib.sha256(contents).hexdigest(),
            }
        gates = {
            "flow_success": True,
            "fit_success": True,
            "setup_timing": True,
            "hold_timing": True,
            "recovery_timing": True,
            "removal_timing": True,
            "no_unconstrained_paths": True,
            "no_critical_warnings": True,
            "compressed_bitstream": True,
            "pocket_hardware": True,
            "dock_hardware": True,
        }
        gates.update(gate_overrides)
        document = {
            "release_evidence": {
                "magic": "SWAN_SONG_RELEASE_EVIDENCE_V1",
                "source_commit": "1" * 40,
                "source_date_epoch": 1_700_000_000,
                "quartus_version": "21.1.1 Build 850",
                "rbf": {
                    "filename": self.rbf.name,
                    "size": len(self.rbf_bytes),
                    "sha256": hashlib.sha256(self.rbf_bytes).hexdigest(),
                },
                "build_id": {
                    "filename": "build_id.mif",
                    "size": len(build_id_contents),
                    "sha256": hashlib.sha256(build_id_contents).hexdigest(),
                },
                "reports": reports,
                "gates": gates,
            }
        }
        path = evidence_directory / "release-evidence.json"
        path.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
        return path

    def test_chip32_identity_and_deterministic_complete_package(self) -> None:
        chip32 = chip32_image(ASSEMBLY, ENCODED_IMAGE)
        self.assertEqual(len(chip32), EXPECTED_IMAGE_SIZE)
        self.assertEqual(hashlib.sha256(chip32).hexdigest(), EXPECTED_IMAGE_SHA256)

        first = self.root / "first.zip"
        second = self.root / "second.zip"
        self.package(first)
        first_provenance = self.provenance_path(first).read_bytes()
        for path in self.dist.rglob("*"):
            os.utime(path, (1_700_000_000, 1_700_000_000))
        os.utime(self.rbf, (1_600_000_000, 1_600_000_000))
        self.package(second)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.package(first)
        self.assertEqual(first_provenance, self.provenance_path(first).read_bytes())

        provenance = json.loads(self.provenance_path(first).read_text(encoding="utf-8"))[
            "package_provenance"
        ]
        self.assertEqual(provenance["magic"], "SWAN_SONG_PACKAGE_PROVENANCE_V1")
        self.assertFalse(provenance["release"])
        self.assertIsNone(provenance["build_evidence"])
        self.assertEqual(
            provenance["archive"]["sha256"], hashlib.sha256(first.read_bytes()).hexdigest()
        )
        self.assertEqual(
            provenance["raw_rbf"]["sha256"], hashlib.sha256(self.rbf_bytes).hexdigest()
        )

        with zipfile.ZipFile(first) as archive:
            names = archive.namelist()
            self.assertEqual(names, sorted(names))
            self.assertEqual(len(names), len(set(names)))
            self.assertFalse(any(name.endswith(".tmp") for name in names))
            self.assertFalse(any(name.endswith(".gitkeep") for name in names))
            core_definition = json.loads(
                archive.read((CORE_DIRECTORY / "core.json").as_posix())
            )
            bitstream_name = core_definition["core"]["cores"][0]["filename"]
            chip32_name = core_definition["core"]["framework"]["chip32_vm"]
            data_definition = json.loads(
                archive.read((CORE_DIRECTORY / "data.json").as_posix())
            )
            self.assertEqual(
                archive.read((CORE_DIRECTORY / "input.json").as_posix()),
                (self.dist / CORE_DIRECTORY / "input.json").read_bytes(),
            )
            slots_by_id = {
                int(slot["id"]): slot
                for slot in data_definition["data"]["data_slots"]
            }
            cartridge_slot = slots_by_id[0]
            self.assertEqual(cartridge_slot["size_maximum"], 16 * 1024 * 1024)
            self.assertEqual(int(cartridge_slot["parameters"], 0), 0x309)
            # APF_VER_1 documents size_exact and size_maximum, but has no
            # size_minimum field. Minimum ROM validation remains core-owned.
            self.assertNotIn("size_minimum", cartridge_slot)
            self.assertEqual(
                {
                    slot_id: (
                        slots_by_id[slot_id]["required"],
                        slots_by_id[slot_id]["filename"],
                        int(slots_by_id[slot_id]["parameters"], 0),
                        slots_by_id[slot_id]["size_exact"],
                    )
                    for slot_id in (9, 10)
                },
                {
                    9: (True, "bw.rom", 0x208, 4096),
                    10: (True, "color.rom", 0x208, 8192),
                },
            )
            interact_definition = json.loads(
                archive.read((CORE_DIRECTORY / "interact.json").as_posix())
            )
            variables_by_id = {
                int(item["id"]): item
                for item in interact_definition["interact"]["variables"]
            }
            self.assertEqual(
                [(item["value"], item["name"]) for item in variables_by_id[10]["options"]],
                [(0, "Auto"), (1, "WonderSwan"), (2, "WonderSwan Color")],
            )
            self.assertEqual(variables_by_id[43]["name"], "Display Orientation")
            self.assertEqual(variables_by_id[43]["address"], "0x208")
            self.assertEqual(variables_by_id[44]["name"], "Landscape 180°")
            self.assertEqual(variables_by_id[44]["address"], "0x20C")
            self.assertEqual(variables_by_id[81]["name"], "Audio in Fast Forward")
            self.assertEqual(variables_by_id[81]["address"], "0x300")
            self.assertIn((CORE_DIRECTORY / bitstream_name).as_posix(), names)
            self.assertIn((CORE_DIRECTORY / chip32_name).as_posix(), names)
            self.assertEqual(
                archive.read((CORE_DIRECTORY / bitstream_name).as_posix()),
                self.rbf_bytes.translate(REVERSE),
            )
            self.assertEqual(
                hashlib.sha256(
                    archive.read((CORE_DIRECTORY / chip32_name).as_posix())
                ).hexdigest(),
                EXPECTED_IMAGE_SHA256,
            )
            self.assertTrue(all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist()))
            self.assertTrue(all(info.create_system == 3 for info in archive.infolist()))
            self.assertTrue(
                all(info.compress_type == zipfile.ZIP_STORED for info in archive.infolist())
            )
            for info in archive.infolist():
                expected_mode = 0o40755 if info.is_dir() else 0o100644
                self.assertEqual(info.external_attr >> 16, expected_mode)
            self.assertEqual(
                {path.split("/", 1)[0] for path in names},
                {"Assets", "Cores", "Platforms"},
            )

    def test_rejects_changed_assembly_and_encoded_image(self) -> None:
        missing_assembly = self.root / "missing.asm"
        with self.assertRaisesRegex(ValueError, "cannot read Chip32 assembly"):
            self.package(
                self.root / "missing-assembly.zip",
                chip32_assembly=missing_assembly,
            )

        changed_assembly = self.root / "chip32.asm"
        changed_assembly.write_bytes(ASSEMBLY.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "assembly does not match"):
            self.package(
                self.root / "assembly.zip", chip32_assembly=changed_assembly
            )

        malformed = self.root / "malformed.hex"
        malformed.write_text("not hexadecimal", encoding="ascii")
        with self.assertRaisesRegex(ValueError, "invalid hexadecimal"):
            self.package(
                self.root / "malformed.zip", chip32_encoded_image=malformed
            )

        non_ascii = self.root / "non-ascii.hex"
        non_ascii.write_bytes(b"00\xff")
        with self.assertRaisesRegex(ValueError, "cannot read encoded"):
            self.package(
                self.root / "non-ascii.zip", chip32_encoded_image=non_ascii
            )

        changed_image = self.root / "changed.hex"
        changed = bytearray(chip32_image(ASSEMBLY, ENCODED_IMAGE))
        changed[0] ^= 0x01
        changed_image.write_text(changed.hex(), encoding="ascii")
        with self.assertRaisesRegex(ValueError, "image identity mismatch"):
            self.package(
                self.root / "changed.zip", chip32_encoded_image=changed_image
            )

    def test_failed_rebuild_removes_stale_package(self) -> None:
        output = self.root / "stale.zip"
        output.write_bytes(b"old package")
        self.provenance_path(output).write_bytes(b"old provenance")
        missing = self.root / "missing.hex"
        with self.assertRaisesRegex(ValueError, "cannot read encoded"):
            self.package(output, chip32_encoded_image=missing)
        self.assertFalse(output.exists())
        self.assertFalse(self.provenance_path(output).exists())

    def test_rejects_missing_or_unsafe_core_references(self) -> None:
        output = self.root / "invalid.zip"

        self.mutate_core_json(
            lambda definition: definition["core"]["framework"].pop("chip32_vm")
        )
        with self.assertRaisesRegex(ValueError, "missing members: chip32_vm"):
            self.package(output)
        self.assertFalse(output.exists())

        self.reset_dist()
        self.mutate_core_json(
            lambda definition: definition["core"]["framework"].__setitem__(
                "chip32_vm", "../chip32.bin"
            )
        )
        with self.assertRaisesRegex(ValueError, "plain filename"):
            self.package(output)

        self.reset_dist()
        self.mutate_core_json(
            lambda definition: definition["core"]["cores"][0].__setitem__(
                "filename", "/wonderswan.rev"
            )
        )
        with self.assertRaisesRegex(ValueError, "plain filename"):
            self.package(output)

    def test_rejects_chip32_target_collisions(self) -> None:
        output = self.root / "collision.zip"
        for filename, message in (
            ("wonderswan.rev", "must be distinct"),
            ("WONDERSWAN.REV", "must be distinct"),
            ("core.json", "refusing to overwrite"),
            ("CORE.JSON", "refusing to overwrite"),
            ("audio.json", "refusing to overwrite"),
            ("AUDIO.JSON", "refusing to overwrite"),
        ):
            with self.subTest(filename=filename):
                self.reset_dist()
                self.mutate_core_json(
                    lambda definition, filename=filename: definition["core"][
                        "framework"
                    ].__setitem__("chip32_vm", filename)
                )
                output.write_bytes(b"old package")
                with self.assertRaisesRegex(ValueError, message):
                    self.package(output)
                self.assertFalse(output.exists())

    def test_rejects_leaked_rom_empty_rbf_and_unsafe_output(self) -> None:
        leaked = self.dist / "Assets/wonderswan/common/bw.rom"
        leaked.write_bytes(b"not firmware")
        output = self.root / "leaked.zip"
        with self.assertRaisesRegex(ValueError, "non-release files"):
            self.package(output)
        self.assertFalse(output.exists())

        leaked.unlink()
        output.write_bytes(b"old package")
        self.rbf.write_bytes(b"")
        with self.assertRaisesRegex(ValueError, "RBF is empty"):
            self.package(output)
        self.assertFalse(output.exists())

        self.rbf.unlink()
        output.write_bytes(b"old package")
        with self.assertRaisesRegex(ValueError, "does not exist"):
            self.package(output)
        self.assertFalse(output.exists())

        self.rbf.write_bytes(self.rbf_bytes)
        with self.assertRaisesRegex(ValueError, "outside --dist"):
            self.package(self.dist / "recursive.zip")
        with self.assertRaisesRegex(ValueError, "must not overwrite"):
            self.package(self.rbf)

    def test_strict_tree_allowlist_and_case_safety(self) -> None:
        output = self.root / "allowlist.zip"
        unexpected_file = self.dist / "README.md"
        unexpected_file.write_text("not an SD asset", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "non-release files: README.md"):
            self.package(output)

        self.reset_dist()
        unexpected_directory = self.dist / "Settings"
        unexpected_directory.mkdir()
        with self.assertRaisesRegex(ValueError, "non-release directories: Settings"):
            self.package(output)

        self.reset_dist()
        link = self.dist / "Platforms/link.json"
        link.symlink_to(self.dist / "Platforms/wonderswan.json")
        with self.assertRaisesRegex(ValueError, "must not contain symlinks"):
            self.package(output)

    def test_all_json_definitions_are_schema_checked(self) -> None:
        output = self.root / "schema.zip"
        cases = [
            (
                CORE_DIRECTORY / "audio.json",
                lambda value: value["audio"].__setitem__("typo", True),
                "unknown members: typo",
            ),
            (
                CORE_DIRECTORY / "core.json",
                lambda value: value["core"]["metadata"].__setitem__(
                    "date_release", "2026-02-30"
                ),
                "date_release must be YYYY-MM-DD",
            ),
            (
                CORE_DIRECTORY / "data.json",
                lambda value: value["data"]["data_slots"][1].__setitem__(
                    "parameters", "0x400"
                ),
                "undocumented APF_VER_1 bits",
            ),
            (
                CORE_DIRECTORY / "input.json",
                lambda value: value["input"]["controllers"][0]["mappings"][0].__setitem__(
                    "key", "pad_btn_home"
                ),
                "not an APF gamepad keycode",
            ),
            (
                CORE_DIRECTORY / "interact.json",
                lambda value: value["interact"]["variables"][1]["options"].append(
                    {"value": 0, "name": "Duplicate"}
                ),
                "options values must be unique",
            ),
            (
                CORE_DIRECTORY / "variants.json",
                lambda value: value["variants"]["variant_list"].append({}),
                "must be empty until variants are implemented",
            ),
            (
                CORE_DIRECTORY / "video.json",
                lambda value: value["video"]["scaler_modes"][0].__setitem__(
                    "rotation", 45
                ),
                "rotation must be 0, 90, 180, or 270",
            ),
            (
                pathlib.PurePosixPath("Platforms/wonderswan.json"),
                lambda value: value["platform"].__setitem__("copyright", "unknown"),
                "unknown members: copyright",
            ),
        ]
        for relative, mutation, message in cases:
            with self.subTest(relative=relative, message=message):
                self.reset_dist()
                self.mutate_json(relative, mutation)
                with self.assertRaisesRegex(ValueError, message):
                    self.package(output)
                self.assertFalse(output.exists())
                self.assertFalse(self.provenance_path(output).exists())

        self.reset_dist()
        info = self.dist / CORE_DIRECTORY / "info.txt"
        info.write_text("\n".join(f"line {index}" for index in range(33)), encoding="ascii")
        with self.assertRaisesRegex(ValueError, "official 32-line limit"):
            self.package(output)

        self.reset_dist()
        info = self.dist / CORE_DIRECTORY / "info.txt"
        info.write_text("not printable in APF: café\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "only printable ASCII and LF"):
            self.package(output)

    def test_graphical_asset_dimensions_and_pixel_format(self) -> None:
        output = self.root / "assets.zip"
        platform = self.dist / "Platforms/_images/wonderswan.bin"
        platform.write_bytes(platform.read_bytes()[:-2])
        with self.assertRaisesRegex(ValueError, "must be 521x165x16-bit"):
            self.package(output)

        self.reset_dist()
        platform = self.dist / "Platforms/_images/wonderswan.bin"
        changed = bytearray(platform.read_bytes())
        changed[1] = 1
        platform.write_bytes(changed)
        with self.assertRaisesRegex(ValueError, "nonzero low brightness bytes"):
            self.package(output)

        self.reset_dist()
        icon = self.dist / CORE_DIRECTORY / "icon.bin"
        icon.write_bytes((b"\xff\x00" + b"\x00\x00") * (36 * 36 // 2))
        self.package(output)
        with zipfile.ZipFile(output) as archive:
            self.assertEqual(
                len(archive.read((CORE_DIRECTORY / "icon.bin").as_posix())),
                36 * 36 * 2,
            )

        icon.write_bytes(icon.read_bytes()[:-2])
        with self.assertRaisesRegex(ValueError, "must be 36x36x16-bit"):
            self.package(output)

        icon.write_bytes(b"\x01\x00" * (36 * 36))
        with self.assertRaisesRegex(ValueError, "only 0x0000/0xFF00 pixels"):
            self.package(output)

    def test_release_evidence_is_verified_and_bound_to_provenance(self) -> None:
        evidence = self.build_evidence()
        output = self.root / "evidence.zip"
        self.package(output, build_evidence=evidence)
        provenance = json.loads(self.provenance_path(output).read_text(encoding="utf-8"))[
            "package_provenance"
        ]
        verified = provenance["build_evidence"]
        self.assertEqual(verified["source_commit"], "1" * 40)
        self.assertEqual(
            verified["manifest_sha256"], hashlib.sha256(evidence.read_bytes()).hexdigest()
        )
        self.assertEqual(set(verified["reports"]), {"flow", "fit", "sta"})

        release_output = self.root / "agg23.WonderSwan_1.0.1_2023-05-06.zip"
        self.package(release_output, build_evidence=evidence, release=True)
        release_provenance = json.loads(
            self.provenance_path(release_output).read_text(encoding="utf-8")
        )["package_provenance"]
        self.assertTrue(release_provenance["release"])

        with self.assertRaisesRegex(ValueError, "requires --build-evidence"):
            self.package(release_output, release=True)
        self.assertFalse(release_output.exists())
        self.assertFalse(self.provenance_path(release_output).exists())

        with self.assertRaisesRegex(ValueError, "release package filename must be"):
            self.package(output, build_evidence=evidence, release=True)

    def test_release_evidence_rejects_unbound_or_unaccepted_inputs(self) -> None:
        output = self.root / "bad-evidence.zip"
        evidence = self.build_evidence()
        definition = json.loads(evidence.read_text(encoding="utf-8"))
        definition["release_evidence"]["rbf"]["sha256"] = "0" * 64
        evidence.write_text(json.dumps(definition), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "RBF SHA-256 does not match"):
            self.package(output, build_evidence=evidence)

        evidence = self.build_evidence()
        build_id_path = evidence.parent / "build_id.mif"
        changed_build_id = build_id_path.read_bytes().replace(b"11111111", b"22222222")
        build_id_path.write_bytes(changed_build_id)
        definition = json.loads(evidence.read_text(encoding="utf-8"))
        definition["release_evidence"]["build_id"]["size"] = len(changed_build_id)
        definition["release_evidence"]["build_id"]["sha256"] = hashlib.sha256(
            changed_build_id
        ).hexdigest()
        evidence.write_text(json.dumps(definition), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "build ID does not match source identity"):
            self.package(output, build_evidence=evidence)

        evidence = self.build_evidence()
        (evidence.parent / "ap_core.fit.rpt").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "fit report (size|SHA-256) mismatch"):
            self.package(output, build_evidence=evidence)

        evidence = self.build_evidence(setup_timing=False)
        with self.assertRaisesRegex(ValueError, "unaccepted gates: setup_timing"):
            self.package(output, build_evidence=evidence)

        evidence = self.build_evidence()
        definition = json.loads(evidence.read_text(encoding="utf-8"))
        definition["release_evidence"]["quartus_version"] = "22.1"
        evidence.write_text(json.dumps(definition), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "must identify Quartus 21.1.1"):
            self.package(output, build_evidence=evidence)


if __name__ == "__main__":
    unittest.main()
