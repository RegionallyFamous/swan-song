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

    def test_chip32_identity_and_deterministic_complete_package(self) -> None:
        chip32 = chip32_image(ASSEMBLY, ENCODED_IMAGE)
        self.assertEqual(len(chip32), EXPECTED_IMAGE_SIZE)
        self.assertEqual(hashlib.sha256(chip32).hexdigest(), EXPECTED_IMAGE_SHA256)

        first = self.root / "first.zip"
        second = self.root / "second.zip"
        self.package(first)
        for path in self.dist.rglob("*"):
            os.utime(path, (1_700_000_000, 1_700_000_000))
        os.utime(self.rbf, (1_600_000_000, 1_600_000_000))
        self.package(second)
        self.assertEqual(first.read_bytes(), second.read_bytes())

        with zipfile.ZipFile(first) as archive:
            names = archive.namelist()
            self.assertEqual(names, sorted(names))
            self.assertEqual(len(names), len(set(names)))
            self.assertFalse(any(name.endswith(".tmp") for name in names))
            core_definition = json.loads(
                archive.read((CORE_DIRECTORY / "core.json").as_posix())
            )
            bitstream_name = core_definition["core"]["cores"][0]["filename"]
            chip32_name = core_definition["core"]["framework"]["chip32_vm"]
            data_definition = json.loads(
                archive.read((CORE_DIRECTORY / "data.json").as_posix())
            )
            slots_by_id = {
                int(slot["id"]): slot
                for slot in data_definition["data"]["data_slots"]
            }
            cartridge_slot = slots_by_id[0]
            self.assertEqual(cartridge_slot["size_maximum"], 16 * 1024 * 1024)
            # APF_VER_1 documents size_exact and size_maximum, but has no
            # size_minimum field. Minimum ROM validation remains core-owned.
            self.assertNotIn("size_minimum", cartridge_slot)
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
        missing = self.root / "missing.hex"
        with self.assertRaisesRegex(ValueError, "cannot read encoded"):
            self.package(output, chip32_encoded_image=missing)
        self.assertFalse(output.exists())

    def test_rejects_missing_or_unsafe_core_references(self) -> None:
        output = self.root / "invalid.zip"

        self.mutate_core_json(
            lambda definition: definition["core"]["framework"].pop("chip32_vm")
        )
        with self.assertRaisesRegex(ValueError, "invalid core definition"):
            self.package(output)
        self.assertFalse(output.exists())

        self.reset_dist()
        self.mutate_core_json(
            lambda definition: definition["core"]["framework"].__setitem__(
                "chip32_vm", "../chip32.bin"
            )
        )
        with self.assertRaisesRegex(ValueError, "must not contain a path"):
            self.package(output)

        self.reset_dist()
        self.mutate_core_json(
            lambda definition: definition["core"]["cores"][0].__setitem__(
                "filename", "/wonderswan.rev"
            )
        )
        with self.assertRaisesRegex(ValueError, "must not contain a path"):
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
        with self.assertRaisesRegex(ValueError, "refusing to package"):
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


if __name__ == "__main__":
    unittest.main()
