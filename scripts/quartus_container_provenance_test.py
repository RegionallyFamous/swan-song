#!/usr/bin/env python3

import json
from pathlib import Path
import tempfile
import unittest

import quartus_container_provenance as provenance


IMAGE_ID = "sha256:" + "a" * 64
REPO_DIGEST = "example.invalid/swan-song/quartus@sha256:" + "b" * 64


class QuartusContainerProvenanceTest(unittest.TestCase):
    def create(self, root: Path) -> tuple[Path, Path]:
        packages = root / provenance.PACKAGE_FILENAME
        packages.write_text(
            "bash\t5.0-6ubuntu1.2\tamd64\n"
            "libc6:amd64\t2.31-0ubuntu9.18\tamd64\n"
        )
        output = root / "container-provenance.json"
        provenance.create_provenance(
            image_id=IMAGE_ID,
            repo_digests_text=REPO_DIGEST,
            packages=packages,
            output=output,
        )
        return output, packages

    def test_round_trip_binds_image_and_packages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output, packages = self.create(Path(temporary))
            document = provenance.validate_provenance(output, packages)
            self.assertEqual(document["image_id"], IMAGE_ID)
            self.assertEqual(
                document["registry_manifest_digests"], ["sha256:" + "b" * 64]
            )
            self.assertEqual(document["packages"]["count"], 2)

    def test_registry_coordinates_are_not_written_to_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packages = root / provenance.PACKAGE_FILENAME
            packages.write_text("bash\t5.0-6ubuntu1.2\tamd64\n")
            output = root / "container-provenance.json"
            provenance.create_provenance(
                image_id=IMAGE_ID,
                repo_digests_text=(
                    REPO_DIGEST
                    + "\nprivate.example/internal/quartus@sha256:"
                    + "b" * 64
                ),
                packages=packages,
                output=output,
            )
            raw = output.read_text()
            self.assertNotIn("example.invalid", raw)
            self.assertNotIn("private.example", raw)
            self.assertEqual(
                provenance.validate_provenance(output, packages)[
                    "registry_manifest_digests"
                ],
                ["sha256:" + "b" * 64],
            )

    def test_package_mutation_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output, packages = self.create(Path(temporary))
            packages.write_text(packages.read_text() + "make\t4.2.1-1.2\tamd64\n")
            with self.assertRaises(provenance.ProvenanceError):
                provenance.validate_provenance(output, packages)

    def test_noncanonical_or_malformed_packages_are_rejected(self) -> None:
        invalid = (
            "make\t4.2.1-1.2\tamd64\nbash\t5.0\tamd64\n",
            "bash\t5.0 amd64\tamd64\n",
            "bash\t5.0\n",
            "bash\t5.0\tamd64",
        )
        for payload in invalid:
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as temporary:
                packages = Path(temporary) / provenance.PACKAGE_FILENAME
                packages.write_text(payload)
                with self.assertRaises(provenance.ProvenanceError):
                    provenance.validate_packages(packages)

    def test_wrong_image_or_quartus_identity_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output, packages = self.create(Path(temporary))
            document = json.loads(output.read_text())
            document["image_id"] = "sha256:short"
            output.write_text(json.dumps(document) + "\n")
            with self.assertRaises(provenance.ProvenanceError):
                provenance.validate_provenance(output, packages)

        with tempfile.TemporaryDirectory() as temporary:
            output, packages = self.create(Path(temporary))
            document = json.loads(output.read_text())
            document["quartus"]["version"] = "latest"
            output.write_text(json.dumps(document) + "\n")
            with self.assertRaises(provenance.ProvenanceError):
                provenance.validate_provenance(output, packages)

    def test_package_numeric_fields_require_exact_non_bool_integers(self) -> None:
        mutations: tuple[tuple[str, object], ...] = (
            ("count", True),
            ("count", 2.0),
            ("bytes", False),
            ("bytes", 58.0),
        )
        for field, value in mutations:
            with self.subTest(field=field, value=value), tempfile.TemporaryDirectory() as temporary:
                output, packages = self.create(Path(temporary))
                document = json.loads(output.read_text())
                document["packages"][field] = value
                output.write_text(json.dumps(document) + "\n")
                with self.assertRaises(provenance.ProvenanceError):
                    provenance.validate_provenance(output, packages)

    def test_unknown_and_duplicate_json_fields_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output, packages = self.create(Path(temporary))
            document = json.loads(output.read_text())
            document["unexpected"] = True
            output.write_text(json.dumps(document) + "\n")
            with self.assertRaises(provenance.ProvenanceError):
                provenance.validate_provenance(output, packages)

        with tempfile.TemporaryDirectory() as temporary:
            output, packages = self.create(Path(temporary))
            payload = output.read_text().rstrip()
            output.write_text(payload[:-1] + ', "magic": "duplicate"}\n')
            with self.assertRaises(provenance.ProvenanceError):
                provenance.validate_provenance(output, packages)

    def test_symlinks_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output, packages = self.create(root)
            link = root / "packages-link.tsv"
            link.symlink_to(packages.name)
            with self.assertRaises(provenance.ProvenanceError):
                provenance.validate_provenance(output, link)


if __name__ == "__main__":
    unittest.main()
