#!/usr/bin/env python3
"""Focused offline tests for Chip32 materialization and APF packaging."""

import hashlib
import json
import os
import pathlib
import shutil
import stat
import subprocess
import tempfile
import unittest
import zipfile
from unittest import mock

from build_chip32 import (
    EXPECTED_IMAGE_SHA256,
    EXPECTED_IMAGE_SIZE,
    chip32_image,
)
import package_core
from package_core import (
    RELEASE_SOURCE_INPUTS_V1,
    create_package,
    quartus_report_version,
    validate_release_source_checkout,
)
from package_validator import PLATFORM_ART_SHA256
import quartus_fit_audit as fit_audit
import quartus_fit_audit_test as fit_audit_test
from reverse_rbf import REVERSE


ROOT = pathlib.Path(__file__).resolve().parent.parent
ASSEMBLY = ROOT / "src/support/chip32.asm"
ENCODED_IMAGE = ROOT / "src/support/chip32.bin.hex"
RELEASE_POLICY = ROOT / "release-policy.json"
CORE_ID = "RegionallyFamous.SwanSong"
CORE_REPOSITORY = "https://github.com/RegionallyFamous/swan-song"
CORE_DIRECTORY = pathlib.PurePosixPath("Cores") / CORE_ID


class PackageCoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="swan-song-package-test-")
        self.root = pathlib.Path(self.temporary.name)
        self.dist = self.root / "dist"
        shutil.copytree(ROOT / "dist", self.dist)
        self.rbf = self.root / "ap_core.rbf"
        self.rbf_bytes = bytes((0x00, 0x01, 0x80, 0xFF, 0x55, 0xAA))
        self.rbf.write_bytes(self.rbf_bytes)
        self.release_policy = self.root / "release-policy.json"
        shutil.copy2(RELEASE_POLICY, self.release_policy)

    def test_release_report_version_accepts_only_quartus_legacy_degree_byte(
        self,
    ) -> None:
        version_line = (
            b"Quartus Prime Version 21.1.1 Build 850 "
            b"06/23/2022 SJ Lite Edition\n"
        )
        self.assertEqual(
            quartus_report_version(
                version_line + b"Low Junction Temperature ; 0 \xb0C\n",
                "fit report",
            ),
            "21.1.1 Build 850 06/23/2022 SJ Lite Edition",
        )
        with self.assertRaisesRegex(ValueError, "bytes other than UTF-8"):
            quartus_report_version(version_line + b"\xff\n", "fit report")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def package(self, output: pathlib.Path, **overrides: object) -> None:
        arguments = {
            "dist": self.dist,
            "rbf": self.rbf,
            "output": output,
            "chip32_assembly": ASSEMBLY,
            "chip32_encoded_image": ENCODED_IMAGE,
            "release_policy": self.release_policy,
        }
        arguments.update(overrides)
        if arguments.get("release"):
            with mock.patch.object(
                package_core,
                "validate_release_source_checkout",
                side_effect=self.release_source_inputs,
            ), mock.patch.object(
                package_core,
                "release_chip32_image",
                return_value=chip32_image(ASSEMBLY, ENCODED_IMAGE),
            ):
                create_package(**arguments)
        else:
            create_package(**arguments)

    def release_source_inputs(self, **arguments: object) -> dict[str, object]:
        dist = pathlib.Path(arguments["dist"])
        source_commit = str(arguments["source_commit"])
        tracked: dict[str, dict[str, object]] = {}
        directories: list[str] = []
        for path in sorted(dist.rglob("*")):
            relative = "dist/" + path.relative_to(dist).as_posix()
            if path.is_dir():
                directories.append(relative)
                continue
            payload = path.read_bytes()
            tracked[relative] = {
                "git_blob": hashlib.sha1(
                    b"blob " + str(len(payload)).encode() + b"\0" + payload
                ).hexdigest(),
                "mode": "100755" if path.stat().st_mode & stat.S_IXUSR else "100644",
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        for relative, path in (
            ("src/support/chip32.asm", ASSEMBLY),
            ("src/support/chip32.bin.hex", ENCODED_IMAGE),
        ):
            payload = path.read_bytes()
            tracked[relative] = {
                "git_blob": hashlib.sha1(
                    b"blob " + str(len(payload)).encode() + b"\0" + payload
                ).hexdigest(),
                "mode": "100644",
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        rbf_bytes = bytes(arguments["rbf_bytes"])
        return {
            "magic": RELEASE_SOURCE_INPUTS_V1,
            "repository": CORE_REPOSITORY,
            "source_commit": source_commit,
            "source_tree": "c" * 40,
            "dist_directory": "dist",
            "dist_directories": directories,
            "chip32_assembly": "src/support/chip32.asm",
            "chip32_encoded_image": "src/support/chip32.bin.hex",
            "tracked_files": tracked,
            "raw_rbf": {
                "filename": str(arguments["rbf_filename"]),
                "size": len(rbf_bytes),
                "sha256": hashlib.sha256(rbf_bytes).hexdigest(),
            },
        }

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

    def mutate_release_policy(self, mutation) -> None:
        definition = json.loads(self.release_policy.read_text(encoding="utf-8"))
        mutation(definition)
        self.release_policy.write_text(json.dumps(definition), encoding="utf-8")

    def authorize_release_policy(self) -> None:
        def authorize(definition) -> None:
            authorization = definition["release_policy"]["authorization"]
            authorization["distribution_and_licensing_authorized"] = True

        self.mutate_release_policy(authorize)

    def set_published_releases(self, releases: list[dict[str, str]]) -> None:
        self.mutate_release_policy(
            lambda definition: definition["release_policy"].__setitem__(
                "published_releases", releases
            )
        )

    def set_release_metadata(self, version: str, release_date: str) -> None:
        def mutate(definition) -> None:
            metadata = definition["core"]["metadata"]
            metadata["version"] = version
            metadata["date_release"] = release_date

        self.mutate_core_json(mutate)

    def mutate_json(self, relative: pathlib.PurePosixPath, mutation) -> None:
        path = self.dist / relative
        definition = json.loads(path.read_text(encoding="utf-8"))
        mutation(definition)
        path.write_text(json.dumps(definition), encoding="utf-8")

    @staticmethod
    def provenance_path(output: pathlib.Path) -> pathlib.Path:
        return output.with_name(output.name + ".provenance.json")

    def build_evidence(
        self, *, legacy_v1: bool = False, **gate_overrides: bool
    ) -> pathlib.Path:
        evidence_directory = self.root / "evidence"
        if evidence_directory.exists():
            shutil.rmtree(evidence_directory)
        evidence_directory.mkdir()
        fit_audit_test.Fixture(evidence_directory)
        source_commit = "a" * 40
        build_id_contents = (
            "-- Reproducible source commit: " + source_commit + "\n"
            "-- SOURCE_DATE_EPOCH: 1700000000\n"
            "0E0 : 20231114;\n"
            "0E1 : 00221320;\n"
            "0E2 : aaaaaaaa;\n"
        ).encode()
        (evidence_directory / "build_id.mif").write_bytes(build_id_contents)
        candidate_rbf = evidence_directory / "output_files/ap_core.rbf"
        candidate_rbf.write_bytes(self.rbf_bytes)
        rbf_digest = hashlib.sha256(self.rbf_bytes).hexdigest()
        (evidence_directory / "ap_core.rbf.sha256").write_text(
            f"{rbf_digest}  /artifacts/output_files/ap_core.rbf\n",
            encoding="utf-8",
        )
        reports = {}
        for kind in ("flow", "fit", "sta"):
            basename = f"ap_core.{kind}.rpt"
            filename = basename if legacy_v1 else f"output_files/{basename}"
            contents = (evidence_directory / "output_files" / basename).read_bytes()
            if legacy_v1:
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
        audit_path = evidence_directory / "quartus-audit-candidate.json"
        audit_document = fit_audit.audit(evidence_directory)
        audit_path.write_text(
            json.dumps(audit_document, sort_keys=True), encoding="utf-8"
        )
        document = {
            "release_evidence": {
                "magic": (
                    "SWAN_SONG_RELEASE_EVIDENCE_V1"
                    if legacy_v1
                    else "SWAN_SONG_RELEASE_EVIDENCE_V2"
                ),
                "source_commit": source_commit,
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
        if not legacy_v1:
            audit_bytes = audit_path.read_bytes()
            document["release_evidence"]["quartus_audit"] = {
                "filename": audit_path.name,
                "size": len(audit_bytes),
                "sha256": hashlib.sha256(audit_bytes).hexdigest(),
            }
        path = evidence_directory / "release-evidence.json"
        path.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
        return path

    @staticmethod
    def rewrite_evidence_artifact(
        evidence: pathlib.Path,
        category: str,
        contents: bytes,
        *,
        report_kind: str | None = None,
    ) -> None:
        document = json.loads(evidence.read_text(encoding="utf-8"))
        release_evidence = document["release_evidence"]
        entry = (
            release_evidence["reports"][report_kind]
            if category == "reports" and report_kind is not None
            else release_evidence[category]
        )
        (evidence.parent / entry["filename"]).write_bytes(contents)
        entry["size"] = len(contents)
        entry["sha256"] = hashlib.sha256(contents).hexdigest()
        evidence.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")

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
            self.assertEqual(
                archive.read((CORE_DIRECTORY / "info.txt").as_posix()),
                (self.dist / CORE_DIRECTORY / "info.txt").read_bytes(),
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
            self.assertEqual(
                {
                    slot_id: (
                        slots_by_id[slot_id]["required"],
                        slots_by_id[slot_id]["filename"],
                        int(slots_by_id[slot_id]["parameters"], 0),
                        slots_by_id[slot_id]["nonvolatile"],
                        slots_by_id[slot_id]["size_exact"],
                        slots_by_id[slot_id]["size_maximum"],
                        int(slots_by_id[slot_id]["address"], 0),
                    )
                    for slot_id in (12, 13)
                },
                {
                    12: (False, "mono.eeprom", 0x02, True, 128, 128, 0x50000000),
                    13: (False, "color.eeprom", 0x02, True, 2048, 2048, 0x60000000),
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
            self.assertEqual(variables_by_id[42]["name"], "LCD Response")
            self.assertEqual(
                [(item["value"], item["name"]) for item in variables_by_id[42]["options"]],
                [(0, "Off"), (1, "2-Frame Blend"), (2, "Persistence")],
            )
            self.assertEqual(variables_by_id[45]["name"], "Color Profile")
            self.assertEqual(variables_by_id[45]["address"], "0x210")
            self.assertEqual(
                [(item["value"], item["name"]) for item in variables_by_id[45]["options"]],
                [(0, "Raw RGB444"), (1, "Color LCD (ares)")],
            )
            self.assertEqual(variables_by_id[46]["name"], "Control Layout")
            self.assertEqual(variables_by_id[46]["address"], "0x214")
            self.assertEqual(
                [(item["value"], item["name"]) for item in variables_by_id[46]["options"]],
                [(0, "Auto"), (1, "Horizontal"), (2, "Vertical")],
            )
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

        assembly = self.root / "chip32.asm"
        assembly.write_bytes(ASSEMBLY.read_bytes())
        with self.assertRaisesRegex(ValueError, "must not overwrite --chip32-assembly"):
            self.package(assembly, chip32_assembly=assembly)
        self.assertEqual(assembly.read_bytes(), ASSEMBLY.read_bytes())

        encoded = self.root / "chip32.bin.hex"
        encoded.write_bytes(ENCODED_IMAGE.read_bytes())
        with self.assertRaisesRegex(
            ValueError, "must not overwrite --chip32-encoded-image"
        ):
            self.package(encoded, chip32_encoded_image=encoded)
        self.assertEqual(encoded.read_bytes(), ENCODED_IMAGE.read_bytes())

        evidence = self.build_evidence()
        evidence_bytes = evidence.read_bytes()
        with self.assertRaisesRegex(ValueError, "must not overwrite --build-evidence"):
            self.package(evidence, build_evidence=evidence)
        self.assertEqual(evidence.read_bytes(), evidence_bytes)

        alias_directory = self.root / "alias"
        alias_directory.mkdir()
        policy_alias = alias_directory / ".." / self.release_policy.name
        policy_bytes = self.release_policy.read_bytes()
        with self.assertRaisesRegex(ValueError, "must not overwrite --release-policy"):
            self.package(
                policy_alias,
                build_evidence=evidence,
                release_policy=policy_alias,
                release=True,
            )
        self.assertEqual(self.release_policy.read_bytes(), policy_bytes)

        provenance_policy = self.root / "collision.zip.provenance.json"
        shutil.copy2(self.release_policy, provenance_policy)
        provenance_policy_bytes = provenance_policy.read_bytes()
        with self.assertRaisesRegex(
            ValueError,
            "package provenance output must not overwrite --release-policy",
        ):
            self.package(
                self.root / "collision.zip",
                build_evidence=evidence,
                release_policy=provenance_policy,
                release=True,
            )
        self.assertEqual(provenance_policy.read_bytes(), provenance_policy_bytes)

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
                CORE_DIRECTORY / "data.json",
                lambda value: next(
                    slot
                    for slot in value["data"]["data_slots"]
                    if int(slot["id"]) == 11
                ).__setitem__("deferload", True),
                "automatic primary loading",
            ),
            (
                CORE_DIRECTORY / "data.json",
                lambda value: next(
                    slot
                    for slot in value["data"]["data_slots"]
                    if int(slot["id"]) == 11
                ).__setitem__("secondary", True),
                "automatic primary loading",
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
                lambda value: next(
                    item
                    for item in value["interact"]["variables"]
                    if int(item["id"]) == 10
                )["options"].append({"value": 0, "name": "Duplicate"}),
                "options values must be unique",
            ),
            (
                CORE_DIRECTORY / "interact.json",
                lambda value: next(
                    item
                    for item in value["interact"]["variables"]
                    if int(item["id"]) == 40
                ).pop("address"),
                "action is missing address",
            ),
            (
                CORE_DIRECTORY / "interact.json",
                lambda value: next(
                    item
                    for item in value["interact"]["variables"]
                    if int(item["id"]) == 80
                ).pop("value"),
                "action is missing value",
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
        self.mutate_json(
            CORE_DIRECTORY / "data.json",
            lambda value: next(
                slot
                for slot in value["data"]["data_slots"]
                if int(slot["id"]) == 11
            ).update({"deferload": False, "secondary": False}),
        )
        explicit_false = self.root / "explicit-false-save-flags.zip"
        self.package(explicit_false)
        self.assertTrue(explicit_false.exists())

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

    def test_shipped_json_rejects_duplicate_members_and_nonstandard_constants(
        self,
    ) -> None:
        output = self.root / "strict-json.zip"
        path = self.core_json_path()
        cases = (
            (
                "duplicate",
                '"author": "RegionallyFamous",',
                '"author": "Wrong", "author": "RegionallyFamous",',
                "duplicate object member 'author'",
            ),
            (
                "nan",
                '"shortname": "SwanSong"',
                '"shortname": NaN',
                "non-standard JSON constant 'NaN'",
            ),
            (
                "infinity",
                '"shortname": "SwanSong"',
                '"shortname": Infinity',
                "non-standard JSON constant 'Infinity'",
            ),
            (
                "negative-infinity",
                '"shortname": "SwanSong"',
                '"shortname": -Infinity',
                "non-standard JSON constant '-Infinity'",
            ),
        )
        for name, original, replacement, message in cases:
            with self.subTest(name=name):
                self.reset_dist()
                path = self.core_json_path()
                contents = path.read_text(encoding="utf-8")
                self.assertIn(original, contents)
                path.write_text(
                    contents.replace(original, replacement, 1), encoding="utf-8"
                )
                with self.assertRaisesRegex(ValueError, message):
                    self.package(output)
                self.assertFalse(output.exists())
                self.assertFalse(self.provenance_path(output).exists())

    def test_graphical_asset_dimensions_and_pixel_format(self) -> None:
        output = self.root / "assets.zip"
        checked_icon = self.dist / CORE_DIRECTORY / "icon.bin"
        expected_icon = checked_icon.read_bytes()
        platform = self.dist / "Platforms/_images/wonderswan.bin"
        expected_platform = platform.read_bytes()
        self.assertEqual(
            hashlib.sha256(expected_platform).hexdigest(), PLATFORM_ART_SHA256
        )
        self.package(output)
        with zipfile.ZipFile(output) as archive:
            self.assertEqual(
                archive.read((CORE_DIRECTORY / "icon.bin").as_posix()),
                expected_icon,
            )
            self.assertEqual(
                archive.read("Platforms/_images/wonderswan.bin"),
                expected_platform,
            )

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
        platform = self.dist / "Platforms/_images/wonderswan.bin"
        changed = bytearray(platform.read_bytes())
        changed[0] ^= 0x01
        platform.write_bytes(changed)
        with self.assertRaisesRegex(ValueError, "reviewed Swan Wake artwork"):
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

    def test_non_release_ignores_release_policy(self) -> None:
        output = self.root / "development.zip"
        self.package(output)
        expected_package = output.read_bytes()
        expected_provenance = self.provenance_path(output).read_bytes()

        self.release_policy.write_text("{not valid JSON", encoding="utf-8")
        self.package(output)
        self.assertEqual(output.read_bytes(), expected_package)
        self.assertEqual(self.provenance_path(output).read_bytes(), expected_provenance)

    def test_checked_policy_separates_identity_predecessor_and_distribution(self) -> None:
        policy = json.loads(RELEASE_POLICY.read_text(encoding="utf-8"))["release_policy"]
        self.assertEqual(policy["magic"], "SWAN_SONG_RELEASE_POLICY_V2")
        self.assertEqual(
            policy["publisher"],
            {"core_id": CORE_ID, "repository_url": CORE_REPOSITORY},
        )
        self.assertEqual(
            policy["authorization"],
            {
                "identity_authorized": True,
                "distribution_and_licensing_authorized": False,
            },
        )
        self.assertEqual(policy["published_releases"], [])
        self.assertEqual(policy["predecessor"]["core_id"], "agg23.WonderSwan")
        self.assertEqual(
            policy["predecessor"]["repository_url"],
            "https://github.com/agg23/openfpga-wonderswan",
        )
        self.assertEqual(
            policy["predecessor"]["inventory"],
            {
                "repository_url": (
                    "https://github.com/openfpga-cores-inventory/analogue-pocket"
                ),
                "commit": "dfc9af340d4b2104bdc771831f7e08aa4df4e20f",
            },
        )
        self.assertEqual(
            policy["predecessor"]["published_releases"],
            [
                {"version": "1.0.0", "date_release": "2023-01-15"},
                {"version": "1.0.1", "date_release": "2023-05-06"},
            ],
        )

    def test_release_rejects_unapproved_distribution_and_licensing(self) -> None:
        output = self.root / "RegionallyFamous.SwanSong_0.1.0-dev.1_2026-07-13.zip"
        output.write_bytes(b"stale package")
        self.provenance_path(output).write_bytes(b"stale provenance")
        with self.assertRaisesRegex(
            ValueError, "distribution and licensing are not authorized"
        ):
            self.package(output, build_evidence=self.build_evidence(), release=True)
        self.assertFalse(output.exists())
        self.assertFalse(self.provenance_path(output).exists())

    def test_predecessor_history_does_not_become_swan_song_history(self) -> None:
        self.authorize_release_policy()
        output = self.root / "RegionallyFamous.SwanSong_0.1.0-dev.1_2026-07-13.zip"
        self.package(output, build_evidence=self.build_evidence(), release=True)
        self.assertTrue(output.is_file())

        provenance = json.loads(
            self.provenance_path(output).read_text(encoding="utf-8")
        )["package_provenance"]["release_policy"]
        self.assertEqual(provenance["published_release_count"], 0)
        self.assertIsNone(provenance["latest_published_version"])
        self.assertEqual(provenance["predecessor"]["core_id"], "agg23.WonderSwan")
        self.assertEqual(
            provenance["predecessor"]["latest_published_version"], "1.0.1"
        )

    def test_release_rejects_published_swan_song_tuple_and_reused_version(self) -> None:
        self.authorize_release_policy()
        self.set_published_releases(
            [
                {"version": "0.1.0-dev.1", "date_release": "2026-07-13"},
            ]
        )
        evidence = self.build_evidence()

        tuple_output = self.root / "RegionallyFamous.SwanSong_0.1.0-dev.1_2026-07-13.zip"
        with self.assertRaisesRegex(ValueError, "release tuple is already published"):
            self.package(tuple_output, build_evidence=evidence, release=True)
        self.assertFalse(tuple_output.exists())
        self.assertFalse(self.provenance_path(tuple_output).exists())

        self.set_release_metadata("0.1.0-dev.1", "2026-07-14")
        version_output = self.root / "RegionallyFamous.SwanSong_0.1.0-dev.1_2026-07-14.zip"
        with self.assertRaisesRegex(ValueError, "release version is already published"):
            self.package(version_output, build_evidence=evidence, release=True)
        self.assertFalse(version_output.exists())
        self.assertFalse(self.provenance_path(version_output).exists())

        self.set_release_metadata("0.1.0-dev.0", "2026-07-14")
        older_output = self.root / "RegionallyFamous.SwanSong_0.1.0-dev.0_2026-07-14.zip"
        with self.assertRaisesRegex(
            ValueError, "release version must be newer than latest published Semantic Version"
        ):
            self.package(older_output, build_evidence=evidence, release=True)
        self.assertFalse(older_output.exists())
        self.assertFalse(self.provenance_path(older_output).exists())

        self.set_release_metadata("0.1.0-dev.1+repacked", "2026-07-14")
        repacked_output = (
            self.root
            / "RegionallyFamous.SwanSong_0.1.0-dev.1+repacked_2026-07-14.zip"
        )
        with self.assertRaisesRegex(
            ValueError, "release version must be newer than latest published Semantic Version"
        ):
            self.package(repacked_output, build_evidence=evidence, release=True)
        self.assertFalse(repacked_output.exists())
        self.assertFalse(self.provenance_path(repacked_output).exists())

    def test_release_rejects_non_monotonic_date(self) -> None:
        evidence = self.build_evidence()
        for release_date in ("2026-07-11", "2026-07-12"):
            with self.subTest(release_date=release_date):
                self.reset_dist()
                shutil.copy2(RELEASE_POLICY, self.release_policy)
                self.authorize_release_policy()
                self.set_published_releases(
                    [{"version": "1.0.0", "date_release": "2026-07-12"}]
                )
                self.set_release_metadata("2.0.0", release_date)
                output = self.root / f"RegionallyFamous.SwanSong_2.0.0_{release_date}.zip"
                output.write_bytes(b"stale package")
                self.provenance_path(output).write_bytes(b"stale provenance")
                with self.assertRaisesRegex(
                    ValueError, "release date must be later than latest published date"
                ):
                    self.package(output, build_evidence=evidence, release=True)
                self.assertFalse(output.exists())
                self.assertFalse(self.provenance_path(output).exists())

    def test_release_rejects_repository_url_before_public_tuple(self) -> None:
        self.authorize_release_policy()
        self.mutate_core_json(
            lambda definition: definition["core"]["metadata"].__setitem__(
                "url", "https://github.com/example/swan-song"
            )
        )
        output = self.root / "RegionallyFamous.SwanSong_0.1.0-dev.1_2026-07-13.zip"
        with self.assertRaisesRegex(ValueError, "release repository URL .* does not match"):
            self.package(output, build_evidence=self.build_evidence(), release=True)
        self.assertFalse(output.exists())
        self.assertFalse(self.provenance_path(output).exists())

    def test_release_rejects_publisher_identity_before_public_tuple(self) -> None:
        self.authorize_release_policy()
        self.mutate_release_policy(
            lambda definition: definition["release_policy"]["publisher"].__setitem__(
                "core_id", "example.WonderSwan"
            )
        )
        output = self.root / "RegionallyFamous.SwanSong_0.1.0-dev.1_2026-07-13.zip"
        with self.assertRaisesRegex(
            ValueError, "release publisher identity .* does not match"
        ):
            self.package(output, build_evidence=self.build_evidence(), release=True)
        self.assertFalse(output.exists())
        self.assertFalse(self.provenance_path(output).exists())

    def test_release_rejects_unapproved_identity_separately(self) -> None:
        self.mutate_release_policy(
            lambda definition: definition["release_policy"]["authorization"].__setitem__(
                "identity_authorized", False
            )
        )
        output = self.root / "RegionallyFamous.SwanSong_0.1.0-dev.1_2026-07-13.zip"
        with self.assertRaisesRegex(ValueError, "publisher identity is not authorized"):
            self.package(output, build_evidence=self.build_evidence(), release=True)
        self.assertFalse(output.exists())
        self.assertFalse(self.provenance_path(output).exists())

    def test_release_policy_schema_is_strict(self) -> None:
        evidence = self.build_evidence()

        def malformed() -> None:
            self.release_policy.write_text("{not valid JSON", encoding="utf-8")

        def unknown_member() -> None:
            self.mutate_release_policy(
                lambda definition: definition["release_policy"].__setitem__(
                    "unreviewed", True
                )
            )

        def legacy_magic() -> None:
            self.mutate_release_policy(
                lambda definition: definition["release_policy"].__setitem__(
                    "magic", "SWAN_SONG_RELEASE_POLICY_V1"
                )
            )

        def legacy_publisher_authorized() -> None:
            self.mutate_release_policy(
                lambda definition: definition["release_policy"]["publisher"].__setitem__(
                    "authorized", True
                )
            )

        def bad_commit() -> None:
            self.mutate_release_policy(
                lambda definition: definition["release_policy"]["predecessor"][
                    "inventory"
                ].__setitem__("commit", "ABC")
            )

        def duplicate_authorization_false_then_true() -> None:
            contents = self.release_policy.read_text(encoding="utf-8")
            original = '"distribution_and_licensing_authorized": false'
            self.assertIn(original, contents)
            self.release_policy.write_text(
                contents.replace(
                    original,
                    (
                        '"distribution_and_licensing_authorized": false, '
                        '"distribution_and_licensing_authorized": true'
                    ),
                    1,
                ),
                encoding="utf-8",
            )

        def nonstandard_constant() -> None:
            contents = self.release_policy.read_text(encoding="utf-8")
            original = '"distribution_and_licensing_authorized": false'
            self.assertIn(original, contents)
            self.release_policy.write_text(
                contents.replace(
                    original,
                    '"distribution_and_licensing_authorized": NaN',
                    1,
                ),
                encoding="utf-8",
            )

        def nonstandard_infinity() -> None:
            contents = self.release_policy.read_text(encoding="utf-8")
            original = '"distribution_and_licensing_authorized": false'
            self.assertIn(original, contents)
            self.release_policy.write_text(
                contents.replace(
                    original,
                    '"distribution_and_licensing_authorized": Infinity',
                    1,
                ),
                encoding="utf-8",
            )

        def bad_date() -> None:
            self.mutate_release_policy(
                lambda definition: definition["release_policy"]["predecessor"][
                    "published_releases"
                ][0].__setitem__("date_release", "2023-02-30")
            )

        def duplicate_version() -> None:
            self.mutate_release_policy(
                lambda definition: definition["release_policy"]["predecessor"][
                    "published_releases"
                ].append({"version": "1.0.1", "date_release": "2024-01-01"})
            )

        def malformed_version() -> None:
            self.mutate_release_policy(
                lambda definition: definition["release_policy"]["predecessor"][
                    "published_releases"
                ][0].__setitem__("version", "release-one")
            )

        def duplicate_version_precedence() -> None:
            self.mutate_release_policy(
                lambda definition: definition["release_policy"]["predecessor"][
                    "published_releases"
                ].append(
                    {"version": "1.0.1+repacked", "date_release": "2024-01-01"}
                )
            )

        def empty_predecessor_releases() -> None:
            self.mutate_release_policy(
                lambda definition: definition["release_policy"]["predecessor"].__setitem__(
                    "published_releases", []
                )
            )

        def same_predecessor_identity() -> None:
            self.mutate_release_policy(
                lambda definition: definition["release_policy"]["predecessor"].__setitem__(
                    "core_id", CORE_ID
                )
            )

        def bad_identity_authorization() -> None:
            self.mutate_release_policy(
                lambda definition: definition["release_policy"]["authorization"].__setitem__(
                    "identity_authorized", 1
                )
            )

        def bad_distribution_authorization() -> None:
            self.mutate_release_policy(
                lambda definition: definition["release_policy"]["authorization"].__setitem__(
                    "distribution_and_licensing_authorized", "yes"
                )
            )

        def missing() -> None:
            self.release_policy.unlink()

        def symlink() -> None:
            self.release_policy.unlink()
            self.release_policy.symlink_to(RELEASE_POLICY)

        cases = (
            ("malformed", malformed, "invalid release policy"),
            ("unknown", unknown_member, "unknown unreviewed"),
            ("legacy-magic", legacy_magic, "must be SWAN_SONG_RELEASE_POLICY_V2"),
            (
                "duplicate-authorization-false-true",
                duplicate_authorization_false_then_true,
                "duplicate object member 'distribution_and_licensing_authorized'",
            ),
            (
                "nonstandard-constant",
                nonstandard_constant,
                "non-standard JSON constant 'NaN'",
            ),
            (
                "nonstandard-infinity",
                nonstandard_infinity,
                "non-standard JSON constant 'Infinity'",
            ),
            (
                "legacy-authorized",
                legacy_publisher_authorized,
                "unknown authorized",
            ),
            ("commit", bad_commit, "lowercase 40-hex commit"),
            ("date", bad_date, "must be YYYY-MM-DD"),
            ("duplicate", duplicate_version, "version is duplicated"),
            ("version", malformed_version, "must be a Semantic Version"),
            (
                "precedence",
                duplicate_version_precedence,
                "Semantic Version precedence is duplicated",
            ),
            (
                "empty-predecessor",
                empty_predecessor_releases,
                "predecessor.published_releases must not be empty",
            ),
            (
                "same-predecessor",
                same_predecessor_identity,
                "predecessor must use a distinct core identity",
            ),
            (
                "identity-authorization",
                bad_identity_authorization,
                "identity_authorized must be boolean",
            ),
            (
                "distribution-authorization",
                bad_distribution_authorization,
                "distribution_and_licensing_authorized must be boolean",
            ),
            ("missing", missing, "does not exist or is not a regular file"),
            ("symlink", symlink, "must not be a symlink"),
        )
        for name, mutation, message in cases:
            with self.subTest(name=name):
                if self.release_policy.exists() or self.release_policy.is_symlink():
                    self.release_policy.unlink()
                shutil.copy2(RELEASE_POLICY, self.release_policy)
                mutation()
                output = (
                    self.root
                    / "RegionallyFamous.SwanSong_0.1.0-dev.1_2026-07-13.zip"
                )
                output.write_bytes(b"stale package")
                self.provenance_path(output).write_bytes(b"stale provenance")
                with self.assertRaisesRegex(ValueError, message):
                    self.package(output, build_evidence=evidence, release=True)
                self.assertFalse(output.exists())
                self.assertFalse(self.provenance_path(output).exists())

    def test_release_requires_evidence_before_policy(self) -> None:
        output = self.root / "RegionallyFamous.SwanSong_0.1.0-dev.1_2026-07-13.zip"
        with self.assertRaisesRegex(ValueError, "requires --build-evidence"):
            self.package(output, release=True)
        self.assertFalse(output.exists())
        self.assertFalse(self.provenance_path(output).exists())

        with self.assertRaisesRegex(ValueError, "requires --release-policy"):
            self.package(
                output,
                build_evidence=self.build_evidence(),
                release_policy=None,
                release=True,
            )
        self.assertFalse(output.exists())
        self.assertFalse(self.provenance_path(output).exists())

    def test_release_evidence_is_verified_and_bound_to_provenance(self) -> None:
        evidence = self.build_evidence()
        output = self.root / "evidence.zip"
        self.package(output, build_evidence=evidence)
        provenance = json.loads(self.provenance_path(output).read_text(encoding="utf-8"))[
            "package_provenance"
        ]
        verified = provenance["build_evidence"]
        self.assertEqual(verified["source_commit"], "a" * 40)
        self.assertEqual(verified["magic"], "SWAN_SONG_RELEASE_EVIDENCE_V2")
        self.assertTrue(verified["quartus_audit"]["audit_pass"])
        self.assertEqual(verified["quartus_audit"]["artifact_count"], 13)
        self.assertEqual(
            verified["manifest_sha256"], hashlib.sha256(evidence.read_bytes()).hexdigest()
        )
        self.assertEqual(set(verified["reports"]), {"flow", "fit", "sta"})
        self.assertEqual(
            {kind: report["filename"] for kind, report in verified["reports"].items()},
            {
                "flow": "output_files/ap_core.flow.rpt",
                "fit": "output_files/ap_core.fit.rpt",
                "sta": "output_files/ap_core.sta.rpt",
            },
        )

        self.authorize_release_policy()
        self.set_release_metadata("2.0.0", "2026-07-13")
        release_output = self.root / "RegionallyFamous.SwanSong_2.0.0_2026-07-13.zip"
        self.package(release_output, build_evidence=evidence, release=True)
        release_provenance = json.loads(
            self.provenance_path(release_output).read_text(encoding="utf-8")
        )["package_provenance"]
        self.assertTrue(release_provenance["release"])
        verified_policy = release_provenance["release_policy"]
        self.assertEqual(
            verified_policy["manifest_sha256"],
            hashlib.sha256(self.release_policy.read_bytes()).hexdigest(),
        )
        self.assertEqual(verified_policy["magic"], "SWAN_SONG_RELEASE_POLICY_V2")
        self.assertEqual(verified_policy["core_id"], CORE_ID)
        self.assertEqual(verified_policy["repository_url"], CORE_REPOSITORY)
        self.assertTrue(verified_policy["identity_authorized"])
        self.assertTrue(
            verified_policy["distribution_and_licensing_authorized"]
        )
        self.assertEqual(verified_policy["published_release_count"], 0)
        self.assertIsNone(verified_policy["latest_published_version"])
        self.assertIsNone(verified_policy["latest_published_date"])
        self.assertEqual(
            verified_policy["predecessor"],
            {
                "core_id": "agg23.WonderSwan",
                "repository_url": "https://github.com/agg23/openfpga-wonderswan",
                "inventory": {
                    "repository_url": (
                        "https://github.com/openfpga-cores-inventory/analogue-pocket"
                    ),
                    "commit": "dfc9af340d4b2104bdc771831f7e08aa4df4e20f",
                },
                "published_release_count": 2,
                "latest_published_version": "1.0.1",
                "latest_published_date": "2023-05-06",
            },
        )
        source_inputs = release_provenance["source_inputs"]
        self.assertEqual(source_inputs["magic"], RELEASE_SOURCE_INPUTS_V1)
        self.assertEqual(source_inputs["source_commit"], "a" * 40)
        self.assertEqual(
            source_inputs["raw_rbf"]["sha256"],
            hashlib.sha256(self.rbf_bytes).hexdigest(),
        )
        self.assertIn("dist/Cores/RegionallyFamous.SwanSong/core.json", source_inputs["tracked_files"])
        self.assertIn("src/support/chip32.asm", source_inputs["tracked_files"])

        with self.assertRaisesRegex(ValueError, "requires --build-evidence"):
            self.package(release_output, release=True)
        self.assertFalse(release_output.exists())
        self.assertFalse(self.provenance_path(release_output).exists())

        with self.assertRaisesRegex(ValueError, "release package filename must be"):
            self.package(output, build_evidence=evidence, release=True)

    def test_release_source_binding_rejects_valid_but_dirty_dist(self) -> None:
        checkout = self.root / "source-checkout"
        (checkout / "dist/Cores/Test.Core").mkdir(parents=True)
        (checkout / "src/support").mkdir(parents=True)
        info = checkout / "dist/Cores/Test.Core/info.txt"
        info.write_text("valid release text\n", encoding="ascii")
        assembly = checkout / "src/support/chip32.asm"
        encoded = checkout / "src/support/chip32.bin.hex"
        assembly.write_bytes(ASSEMBLY.read_bytes())
        encoded.write_bytes(ENCODED_IMAGE.read_bytes())
        subprocess.run(["git", "init", "-q", str(checkout)], check=True)
        subprocess.run(
            ["git", "-C", str(checkout), "config", "user.email", "test@example.invalid"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(checkout), "config", "user.name", "Swan Song Test"],
            check=True,
        )
        subprocess.run(["git", "-C", str(checkout), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(checkout), "commit", "-qm", "fixture"], check=True
        )
        commit = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"],
            check=True,
            stdout=subprocess.PIPE,
            text=True,
        ).stdout.strip()
        clean = validate_release_source_checkout(
            source_root=checkout,
            dist=checkout / "dist",
            chip32_assembly=assembly,
            chip32_encoded_image=encoded,
            rbf_filename="ap_core.rbf",
            rbf_bytes=self.rbf_bytes,
            source_commit=commit,
        )
        self.assertEqual(clean["source_commit"], commit)
        self.assertEqual(
            clean["tracked_files"]["dist/Cores/Test.Core/info.txt"]["sha256"],
            hashlib.sha256(info.read_bytes()).hexdigest(),
        )

        assembly.write_text("raced assembly\n", encoding="ascii")
        encoded.write_text("ff\n", encoding="ascii")
        self.assertEqual(
            package_core.release_chip32_image(checkout, commit),
            chip32_image(ASSEMBLY, ENCODED_IMAGE),
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(checkout),
                "checkout",
                "--",
                "src/support/chip32.asm",
                "src/support/chip32.bin.hex",
            ],
            check=True,
        )

        # This remains valid printable package content; only its divergence
        # from the claimed source commit makes it unacceptable.
        info.write_text("different but still valid release text\n", encoding="ascii")
        with self.assertRaisesRegex(ValueError, "clean exact source checkout"):
            validate_release_source_checkout(
                source_root=checkout,
                dist=checkout / "dist",
                chip32_assembly=assembly,
                chip32_encoded_image=encoded,
                rbf_filename="ap_core.rbf",
                rbf_bytes=self.rbf_bytes,
                source_commit=commit,
            )

    def test_release_evidence_rejects_unbound_or_unaccepted_inputs(self) -> None:
        output = self.root / "bad-evidence.zip"
        evidence = self.build_evidence()
        definition = json.loads(evidence.read_text(encoding="utf-8"))
        definition["release_evidence"]["rbf"]["sha256"] = "0" * 64
        evidence.write_text(json.dumps(definition), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "RBF SHA-256 does not match"):
            self.package(output, build_evidence=evidence)

        evidence = self.build_evidence()
        evidence_link = self.root / "release-evidence-link.json"
        evidence_link.symlink_to(evidence)
        with self.assertRaisesRegex(ValueError, "build evidence must not be a symlink"):
            self.package(output, build_evidence=evidence_link)

        evidence = self.build_evidence()
        build_id_path = evidence.parent / "build_id.mif"
        changed_build_id = build_id_path.read_bytes().replace(b"aaaaaaaa", b"bbbbbbbb")
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
        (evidence.parent / "output_files/ap_core.fit.rpt").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "fit report (size|SHA-256) mismatch"):
            self.package(output, build_evidence=evidence)

        evidence = self.build_evidence(setup_timing=False)
        with self.assertRaisesRegex(ValueError, "unaccepted gates: setup_timing"):
            self.package(output, build_evidence=evidence)

        evidence = self.build_evidence()
        definition = json.loads(evidence.read_text(encoding="utf-8"))
        definition["release_evidence"]["quartus_version"] = "22.1"
        evidence.write_text(json.dumps(definition), encoding="utf-8")
        with self.assertRaisesRegex(
            ValueError, "must identify exact Quartus 21.1.1 Build 850"
        ):
            self.package(output, build_evidence=evidence)

    def test_release_evidence_requires_exact_quartus_version_and_report_agreement(
        self,
    ) -> None:
        output = self.root / "bad-quartus-evidence.zip"
        for version in (
            "21.1.10 Build 850",
            "21.1.1 Build 8500",
            "21.1.1 Build 850 unreviewed",
        ):
            with self.subTest(version=version):
                evidence = self.build_evidence()
                document = json.loads(evidence.read_text(encoding="utf-8"))
                document["release_evidence"]["quartus_version"] = version
                evidence.write_text(json.dumps(document), encoding="utf-8")
                with self.assertRaisesRegex(
                    ValueError, "exact Quartus 21.1.1 Build 850"
                ):
                    self.package(output, build_evidence=evidence)

        evidence = self.build_evidence()
        fit_report = (evidence.parent / "output_files/ap_core.fit.rpt").read_bytes().replace(
            b"06/23/2022", b"06/24/2022"
        )
        self.rewrite_evidence_artifact(
            evidence, "reports", fit_report, report_kind="fit"
        )
        with self.assertRaisesRegex(ValueError, "version lines disagree"):
            self.package(output, build_evidence=evidence)

        evidence = self.build_evidence()
        fit_report = (evidence.parent / "output_files/ap_core.fit.rpt").read_bytes().replace(
            b"Build 850", b"Build 8500"
        )
        self.rewrite_evidence_artifact(
            evidence, "reports", fit_report, report_kind="fit"
        )
        with self.assertRaisesRegex(
            ValueError, "exact Quartus 21.1.1 Build 850"
        ):
            self.package(output, build_evidence=evidence)

    def test_release_evidence_binds_rbf_filename_and_unique_mif_words(self) -> None:
        output = self.root / "bad-source-binding.zip"
        evidence = self.build_evidence()
        document = json.loads(evidence.read_text(encoding="utf-8"))
        document["release_evidence"]["rbf"]["filename"] = "other.rbf"
        evidence.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "RBF filename does not match --rbf"):
            self.package(output, build_evidence=evidence)

        for duplicate in (
            ("0E0", b"E0 : 20231114;\n"),
            ("0E2", b"00e2 : 22222222;\n"),
        ):
            address, assignment = duplicate
            with self.subTest(duplicate=assignment):
                evidence = self.build_evidence()
                build_id = (evidence.parent / "build_id.mif").read_bytes() + assignment
                self.rewrite_evidence_artifact(evidence, "build_id", build_id)
                with self.assertRaisesRegex(
                    ValueError, rf"exactly once; {address} appears"
                ):
                    self.package(output, build_evidence=evidence)

    def test_release_evidence_rejects_ambiguous_or_nonstandard_json(self) -> None:
        output = self.root / "strict-evidence.zip"
        cases = (
            (
                "duplicate-false-true",
                '"pocket_hardware": true',
                '"pocket_hardware": false, "pocket_hardware": true',
                "duplicate object member 'pocket_hardware'",
            ),
            (
                "nan",
                '"source_date_epoch": 1700000000',
                '"source_date_epoch": NaN',
                "non-standard JSON constant 'NaN'",
            ),
            (
                "infinity",
                '"source_date_epoch": 1700000000',
                '"source_date_epoch": Infinity',
                "non-standard JSON constant 'Infinity'",
            ),
        )
        for name, original, replacement, message in cases:
            with self.subTest(name=name):
                evidence = self.build_evidence()
                contents = evidence.read_text(encoding="utf-8")
                self.assertIn(original, contents)
                evidence.write_text(
                    contents.replace(original, replacement, 1), encoding="utf-8"
                )
                with self.assertRaisesRegex(ValueError, message):
                    self.package(output, build_evidence=evidence)
                self.assertFalse(output.exists())
                self.assertFalse(self.provenance_path(output).exists())

    def test_release_requires_v2_but_nonrelease_preserves_v1_compatibility(self) -> None:
        evidence = self.build_evidence(legacy_v1=True)
        nonrelease = self.root / "legacy-evidence.zip"
        self.package(nonrelease, build_evidence=evidence)
        provenance = json.loads(
            self.provenance_path(nonrelease).read_text(encoding="utf-8")
        )["package_provenance"]
        self.assertEqual(
            provenance["build_evidence"]["magic"],
            "SWAN_SONG_RELEASE_EVIDENCE_V1",
        )
        self.assertIsNone(provenance["build_evidence"]["quartus_audit"])

        self.authorize_release_policy()
        self.set_release_metadata("2.0.0", "2026-07-13")
        release = self.root / "RegionallyFamous.SwanSong_2.0.0_2026-07-13.zip"
        with self.assertRaisesRegex(
            ValueError, "requires SWAN_SONG_RELEASE_EVIDENCE_V2"
        ):
            self.package(release, build_evidence=evidence, release=True)
        self.assertFalse(release.exists())
        self.assertFalse(self.provenance_path(release).exists())

    def test_v2_recomputes_candidate_instead_of_trusting_rehashed_claims(self) -> None:
        evidence = self.build_evidence()
        candidate = evidence.parent / "quartus-audit-candidate.json"
        candidate_document = json.loads(candidate.read_text(encoding="utf-8"))
        candidate_document["quartus_audit"]["audit_pass"] = False
        candidate.write_text(
            json.dumps(candidate_document, sort_keys=True), encoding="utf-8"
        )
        evidence_document = json.loads(evidence.read_text(encoding="utf-8"))
        audit_entry = evidence_document["release_evidence"]["quartus_audit"]
        audit_bytes = candidate.read_bytes()
        audit_entry["size"] = len(audit_bytes)
        audit_entry["sha256"] = hashlib.sha256(audit_bytes).hexdigest()
        evidence.write_text(
            json.dumps(evidence_document, sort_keys=True), encoding="utf-8"
        )

        output = self.root / "rehashed-forged-audit.zip"
        with self.assertRaisesRegex(ValueError, "does not match a fresh audit"):
            self.package(output, build_evidence=evidence)
        self.assertFalse(output.exists())
        self.assertFalse(self.provenance_path(output).exists())

    def test_v2_rejects_cross_build_source_and_report_mixes(self) -> None:
        output = self.root / "cross-build.zip"

        evidence = self.build_evidence()
        evidence_document = json.loads(evidence.read_text(encoding="utf-8"))
        evidence_document["release_evidence"]["source_commit"] = "b" * 40
        build_id = (evidence.parent / "build_id.mif").read_bytes()
        build_id = build_id.replace(b"a" * 40, b"b" * 40).replace(
            b"aaaaaaaa", b"bbbbbbbb"
        )
        (evidence.parent / "build_id.mif").write_bytes(build_id)
        build_entry = evidence_document["release_evidence"]["build_id"]
        build_entry["size"] = len(build_id)
        build_entry["sha256"] = hashlib.sha256(build_id).hexdigest()
        candidate = evidence.parent / "quartus-audit-candidate.json"
        candidate_document = json.loads(candidate.read_text(encoding="utf-8"))
        candidate_document["quartus_audit"]["artifacts"]["build_id.mif"] = {
            "size": len(build_id),
            "sha256": hashlib.sha256(build_id).hexdigest(),
        }
        candidate.write_text(
            json.dumps(candidate_document, sort_keys=True), encoding="utf-8"
        )
        audit_bytes = candidate.read_bytes()
        audit_entry = evidence_document["release_evidence"]["quartus_audit"]
        audit_entry["size"] = len(audit_bytes)
        audit_entry["sha256"] = hashlib.sha256(audit_bytes).hexdigest()
        evidence.write_text(
            json.dumps(evidence_document, sort_keys=True), encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "source identity does not match"):
            self.package(output, build_evidence=evidence)

        evidence = self.build_evidence()
        sta_path = evidence.parent / "output_files/ap_core.sta.rpt"
        sta_bytes = sta_path.read_bytes() + b"post-audit report mix\n"
        self.rewrite_evidence_artifact(
            evidence, "reports", sta_bytes, report_kind="sta"
        )
        with self.assertRaisesRegex(
            ValueError, "does not match a fresh audit"
        ):
            self.package(output, build_evidence=evidence)
        self.assertFalse(output.exists())
        self.assertFalse(self.provenance_path(output).exists())

    def test_v2_rejects_rehashed_negative_timing_candidate(self) -> None:
        evidence = self.build_evidence()
        candidate = evidence.parent / "quartus-audit-candidate.json"
        candidate_document = json.loads(candidate.read_text(encoding="utf-8"))
        sta_relative = "output_files/ap_core.sta.rpt"
        sta_path = evidence.parent / sta_relative
        sta_bytes = sta_path.read_bytes().replace(
            b"SWAN_SONG_TIMING_GATE_V1 corners 4 analyses 4 negative_paths 0",
            b"SWAN_SONG_TIMING_GATE_V1 corners 4 analyses 4 negative_paths 1",
            1,
        )
        self.assertIn(b"negative_paths 1", sta_bytes)
        sta_path.write_bytes(sta_bytes)
        candidate_document["quartus_audit"]["artifacts"][sta_relative] = {
            "size": len(sta_bytes),
            "sha256": hashlib.sha256(sta_bytes).hexdigest(),
        }
        candidate.write_text(
            json.dumps(candidate_document, sort_keys=True), encoding="utf-8"
        )

        evidence_document = json.loads(evidence.read_text(encoding="utf-8"))
        audit_bytes = candidate.read_bytes()
        audit_entry = evidence_document["release_evidence"]["quartus_audit"]
        audit_entry["size"] = len(audit_bytes)
        audit_entry["sha256"] = hashlib.sha256(audit_bytes).hexdigest()
        sta_entry = evidence_document["release_evidence"]["reports"]["sta"]
        sta_entry["size"] = len(sta_bytes)
        sta_entry["sha256"] = hashlib.sha256(sta_bytes).hexdigest()
        evidence.write_text(
            json.dumps(evidence_document, sort_keys=True), encoding="utf-8"
        )

        output = self.root / "negative-timing.zip"
        with self.assertRaisesRegex(ValueError, "could not recompute Quartus audit"):
            self.package(output, build_evidence=evidence)
        self.assertFalse(output.exists())
        self.assertFalse(self.provenance_path(output).exists())


if __name__ == "__main__":
    unittest.main()
