#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

import quartus_archive


def sha1(payload: bytes) -> str:
    return hashlib.sha1(payload, usedforsecurity=False).hexdigest()


class QuartusArchiveTest(unittest.TestCase):
    installer = b"synthetic installer"
    device = b"synthetic Cyclone V package"

    def make_bundle(
        self,
        root: Path,
        *,
        installer: bytes | None = installer,
        device: bytes | None = device,
        duplicate_installer: bool = False,
        symlink_installer: bool = False,
        unsafe_member: bool = False,
    ) -> tuple[Path, quartus_archive.Manifest]:
        path = root / "bundle.tar"
        with tarfile.open(path, "w") as archive:
            if unsafe_member:
                info = tarfile.TarInfo("../escape")
                info.size = 1
                archive.addfile(info, io.BytesIO(b"x"))
            if installer is not None:
                info = tarfile.TarInfo("nested/installer.run")
                if symlink_installer:
                    info.type = tarfile.SYMTYPE
                    info.linkname = "target"
                    archive.addfile(info)
                else:
                    info.size = len(installer)
                    archive.addfile(info, io.BytesIO(installer))
            if duplicate_installer:
                info = tarfile.TarInfo("other/installer.run")
                info.size = len(self.installer)
                archive.addfile(info, io.BytesIO(self.installer))
            if device is not None:
                info = tarfile.TarInfo("device.qdz")
                info.size = len(device)
                archive.addfile(info, io.BytesIO(device))

        manifest = quartus_archive.Manifest(
            archive=quartus_archive.Artifact(path.name, sha1(path.read_bytes())),
            components=(
                quartus_archive.Artifact("installer.run", sha1(self.installer), True),
                quartus_archive.Artifact("device.qdz", sha1(self.device)),
            ),
        )
        return path, manifest

    def test_inspect_and_extract_exact_components(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle, manifest = self.make_bundle(root)
            self.assertEqual(
                quartus_archive.inspect_archive(bundle, manifest),
                {"installer.run": sha1(self.installer), "device.qdz": sha1(self.device)},
            )
            output = root / "out"
            quartus_archive.extract_components(bundle, output, manifest)
            self.assertEqual((output / "installer.run").read_bytes(), self.installer)
            self.assertEqual((output / "device.qdz").read_bytes(), self.device)
            self.assertEqual((output / "installer.run").stat().st_mode & 0o777, 0o755)
            self.assertEqual((output / "device.qdz").stat().st_mode & 0o777, 0o644)
            self.assertEqual(sorted(item.name for item in output.iterdir()), ["device.qdz", "installer.run"])

    def test_rejects_outer_digest_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle, manifest = self.make_bundle(Path(temporary))
            bad = quartus_archive.Manifest(
                archive=quartus_archive.Artifact(bundle.name, "0" * 40),
                components=manifest.components,
            )
            with self.assertRaisesRegex(quartus_archive.ArchiveError, "archive SHA-1 mismatch"):
                quartus_archive.inspect_archive(bundle, bad)

    def test_rejects_inner_digest_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle, manifest = self.make_bundle(Path(temporary), installer=b"changed")
            with self.assertRaisesRegex(quartus_archive.ArchiveError, "installer.run SHA-1 mismatch"):
                quartus_archive.inspect_archive(bundle, manifest)

    def test_rejects_missing_component(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle, manifest = self.make_bundle(Path(temporary), device=None)
            with self.assertRaisesRegex(quartus_archive.ArchiveError, "missing required"):
                quartus_archive.inspect_archive(bundle, manifest)

    def test_rejects_duplicate_component(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle, manifest = self.make_bundle(Path(temporary), duplicate_installer=True)
            with self.assertRaisesRegex(quartus_archive.ArchiveError, "duplicate required"):
                quartus_archive.inspect_archive(bundle, manifest)

    def test_rejects_symlink_component(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle, manifest = self.make_bundle(Path(temporary), symlink_installer=True)
            with self.assertRaisesRegex(quartus_archive.ArchiveError, "not a regular file"):
                quartus_archive.inspect_archive(bundle, manifest)

    def test_rejects_unsafe_member_even_when_unrelated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle, manifest = self.make_bundle(Path(temporary), unsafe_member=True)
            with self.assertRaisesRegex(quartus_archive.ArchiveError, "unsafe tar member"):
                quartus_archive.inspect_archive(bundle, manifest)

    def test_rejects_nonempty_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle, manifest = self.make_bundle(root)
            output = root / "out"
            output.mkdir()
            (output / "keep").write_text("user data", encoding="utf-8")
            with self.assertRaisesRegex(quartus_archive.ArchiveError, "must be empty"):
                quartus_archive.extract_components(bundle, output, manifest)
            self.assertEqual((output / "keep").read_text(encoding="utf-8"), "user data")

    def test_rejects_renamed_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle, manifest = self.make_bundle(root)
            renamed = root / "wrong-name.tar"
            bundle.rename(renamed)
            with self.assertRaisesRegex(quartus_archive.ArchiveError, "filename must be"):
                quartus_archive.inspect_archive(renamed, manifest)


if __name__ == "__main__":
    unittest.main()
