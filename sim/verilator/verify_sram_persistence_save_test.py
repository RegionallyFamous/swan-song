#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from pathlib import Path

import generate_sram_persistence_probes as probes
import verify_sram_persistence_save as verifier


class VerifySramPersistenceSaveTests(unittest.TestCase):
    def test_all_geometries_models_and_generations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "save.sav"
            cases = (
                (probes.GENERATION_1, probes.STATUS_INITIALIZED),
                (probes.GENERATION_2, probes.STATUS_PERSISTED_1_TO_2),
                (probes.GENERATION_1, probes.STATUS_PERSISTED_2_TO_1),
            )
            for model in probes.MODELS:
                for save_type in probes.SAVE_TYPES:
                    for generation, status in cases:
                        path.write_bytes(
                            verifier.expected_image(
                                save_type, model, generation, status
                            )
                        )
                        verifier.verify_save(
                            path, save_type, model, generation, status
                        )

    def test_rejects_wrong_size(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "save.sav"
            original = verifier.expected_image(
                0x03,
                "ws",
                probes.GENERATION_1,
                probes.STATUS_INITIALIZED,
            )
            for mutated in (original[:-1], original + b"\x00"):
                with self.subTest(size=len(mutated)):
                    path.write_bytes(mutated)
                    with self.assertRaisesRegex(ValueError, "save size mismatch"):
                        verifier.verify_save(
                            path,
                            0x03,
                            "ws",
                            probes.GENERATION_1,
                            probes.STATUS_INITIALIZED,
                        )

    def test_rejects_impossible_generation_status_pair(self) -> None:
        with self.assertRaisesRegex(ValueError, "impossible successful"):
            verifier.expected_image(
                0x03,
                "ws",
                probes.GENERATION_2,
                probes.STATUS_INITIALIZED,
            )

    def test_rejects_metadata_and_each_bank_sentinel_mutations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "save.sav"
            original = verifier.expected_image(
                0x05,
                "wsc",
                probes.GENERATION_2,
                probes.STATUS_PERSISTED_1_TO_2,
            )
            offsets = list(range(7))
            for bank in range(probes.SAVE_TYPES[0x05].banks):
                offsets.extend(
                    (
                        bank * 0x10000 + 0x0100,
                        bank * 0x10000 + 0x0101,
                        bank * 0x10000 + 0xFFFE,
                        bank * 0x10000 + 0xFFFF,
                    )
                )
            for offset in offsets:
                mutated = bytearray(original)
                mutated[offset] ^= 0x01
                path.write_bytes(mutated)
                with self.assertRaisesRegex(ValueError, "save content mismatch"):
                    verifier.verify_save(
                        path,
                        0x05,
                        "wsc",
                        probes.GENERATION_2,
                        probes.STATUS_PERSISTED_1_TO_2,
                    )

    def test_rejects_nonzero_unwritten_byte(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "save.sav"
            mutated = bytearray(
                verifier.expected_image(
                    0x03,
                    "ws",
                    probes.GENERATION_1,
                    probes.STATUS_INITIALIZED,
                )
            )
            mutated[0x1234] = 0x80
            path.write_bytes(mutated)
            with self.assertRaisesRegex(ValueError, "save content mismatch"):
                verifier.verify_save(
                    path,
                    0x03,
                    "ws",
                    probes.GENERATION_1,
                    probes.STATUS_INITIALIZED,
                )

    def test_verifies_exact_failure_publication_from_corrupt_import(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            imported_path = Path(directory) / "corrupt.sav"
            output_path = Path(directory) / "failure.sav"
            imported = bytearray(
                verifier.expected_image(
                    0x03,
                    "ws",
                    probes.GENERATION_1,
                    probes.STATUS_INITIALIZED,
                )
            )
            imported[0x0100] ^= 0x80
            imported_path.write_bytes(imported)
            output_path.write_bytes(
                verifier.expected_failure_image(bytes(imported), 0x03, "ws")
            )
            verifier.verify_failure_save(
                imported_path, output_path, 0x03, "ws"
            )

            mutated_output = bytearray(output_path.read_bytes())
            mutated_output[0x1234] ^= 0x01
            output_path.write_bytes(mutated_output)
            with self.assertRaisesRegex(ValueError, "save content mismatch"):
                verifier.verify_failure_save(
                    imported_path, output_path, 0x03, "ws"
                )

    def test_rejects_wrong_sized_failure_import(self) -> None:
        with self.assertRaisesRegex(ValueError, "imported save size mismatch"):
            verifier.expected_failure_image(b"\x00", 0x03, "ws")

    def test_failure_expectation_rejects_imports_that_would_succeed(self) -> None:
        blank = bytes(probes.SAVE_TYPES[0x03].bytes)
        with self.assertRaisesRegex(ValueError, "uninitialized-save path"):
            verifier.expected_failure_image(blank, 0x03, "ws")

        valid = verifier.expected_image(
            0x03,
            "ws",
            probes.GENERATION_1,
            probes.STATUS_INITIALIZED,
        )
        with self.assertRaisesRegex(ValueError, "successful persistence path"):
            verifier.expected_failure_image(valid, 0x03, "ws")

        metadata_only = bytearray(valid)
        metadata_only[4:7] = b"\xff\xff\xff"
        with self.assertRaisesRegex(ValueError, "successful persistence path"):
            verifier.expected_failure_image(bytes(metadata_only), 0x03, "ws")

    def test_failure_verification_requires_distinct_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "failure-shaped.sav"
            imported = bytearray(
                verifier.expected_image(
                    0x03,
                    "ws",
                    probes.GENERATION_1,
                    probes.STATUS_INITIALIZED,
                )
            )
            imported[0x0100] ^= 0x80
            path.write_bytes(
                verifier.expected_failure_image(bytes(imported), 0x03, "ws")
            )
            with self.assertRaisesRegex(ValueError, "distinct artifacts"):
                verifier.verify_failure_save(path, path, 0x03, "ws")

    def test_invalid_generation_takes_exact_failure_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            imported_path = root / "invalid-generation.sav"
            output_path = root / "failure.sav"
            imported = bytearray(
                verifier.expected_image(
                    0x03,
                    "ws",
                    probes.GENERATION_1,
                    probes.STATUS_INITIALIZED,
                )
            )
            imported[2:4] = b"\x99\x99"
            imported_path.write_bytes(imported)
            output_path.write_bytes(
                verifier.expected_failure_image(bytes(imported), 0x03, "ws")
            )
            verifier.verify_failure_save(
                imported_path, output_path, 0x03, "ws"
            )

    def test_pinned_images_have_independent_literals_and_hashes(self) -> None:
        cases = (
            (
                0x03,
                "ws",
                probes.GENERATION_1,
                probes.STATUS_INITIALIZED,
                131072,
                "53535713110300",
                "0031",
                "0131",
                "fece",
                "6e28073ba6d548e82170923a7c42e505d566358111cfd42e4848cc3fc1b7e9c4",
            ),
            (
                0x05,
                "wsc",
                probes.GENERATION_2,
                probes.STATUS_PERSISTED_1_TO_2,
                524288,
                "53536824220501",
                "00a6",
                "07a6",
                "f859",
                "00fa4c862119ed0144da31f225ed0f50514007f23aa4aa0b8170386c1c1cd32f",
            ),
        )
        for (
            save_type,
            model,
            generation,
            status,
            size,
            header_hex,
            bank_0_low_hex,
            last_bank_low_hex,
            last_bank_high_hex,
            sha256,
        ) in cases:
            with self.subTest(save_type=save_type, model=model):
                image = verifier.expected_image(
                    save_type, model, generation, status
                )
                last_bank = probes.SAVE_TYPES[save_type].banks - 1
                self.assertEqual(len(image), size)
                self.assertEqual(image[0:7], bytes.fromhex(header_hex))
                self.assertEqual(image[0x0100:0x0102], bytes.fromhex(bank_0_low_hex))
                self.assertEqual(
                    image[
                        last_bank * 0x10000
                        + 0x0100 : last_bank * 0x10000
                        + 0x0102
                    ],
                    bytes.fromhex(last_bank_low_hex),
                )
                self.assertEqual(image[-2:], bytes.fromhex(last_bank_high_hex))
                self.assertEqual(hashlib.sha256(image).hexdigest(), sha256)

    def test_rejects_complete_invalid_save_type_and_model_sets(self) -> None:
        for save_type in (-1, *range(256), 256):
            if save_type in probes.SAVE_TYPES:
                continue
            with self.subTest(save_type=save_type):
                with self.assertRaisesRegex(ValueError, "unsupported save type"):
                    verifier.expected_image(
                        save_type,
                        "ws",
                        probes.GENERATION_1,
                        probes.STATUS_INITIALIZED,
                    )
        for model in ("", "mono", "color", "WS", "WSC", "ws ", None):
            with self.subTest(model=model):
                with self.assertRaisesRegex(ValueError, "unsupported model"):
                    verifier.expected_image(
                        0x03,
                        model,  # type: ignore[arg-type]
                        probes.GENERATION_1,
                        probes.STATUS_INITIALIZED,
                    )

    def test_rejects_complete_invalid_status_generation_pairs(self) -> None:
        for generation in verifier.GENERATIONS:
            for status in range(256):
                if (generation, status) in verifier.VALID_RESULTS:
                    continue
                with self.subTest(generation=generation, status=status):
                    with self.assertRaisesRegex(ValueError, "impossible successful"):
                        verifier.expected_image(0x03, "ws", generation, status)

        invalid_generations = (
            -1,
            0,
            probes.GENERATION_1 - 1,
            probes.GENERATION_1 + 1,
            probes.GENERATION_2 - 1,
            probes.GENERATION_2 + 1,
            0xFFFF,
            0x10000,
        )
        for generation in invalid_generations:
            for status in (
                probes.STATUS_INITIALIZED,
                probes.STATUS_PERSISTED_1_TO_2,
                probes.STATUS_PERSISTED_2_TO_1,
                probes.STATUS_FAILURE,
            ):
                with self.subTest(generation=generation, status=status):
                    with self.assertRaisesRegex(ValueError, "unsupported generation"):
                        verifier.expected_image(0x03, "ws", generation, status)

        for generation in verifier.GENERATIONS:
            for status in (-1, 256):
                with self.subTest(generation=generation, status=status):
                    with self.assertRaisesRegex(ValueError, "status must fit"):
                        verifier.expected_image(0x03, "ws", generation, status)

    def test_rejects_symlink_and_hardlinked_save_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / "original.sav"
            original.write_bytes(
                verifier.expected_image(
                    0x03,
                    "ws",
                    probes.GENERATION_1,
                    probes.STATUS_INITIALIZED,
                )
            )
            symlink = root / "symlink.sav"
            symlink.symlink_to(original)
            with self.assertRaises(OSError):
                verifier.verify_save(
                    symlink,
                    0x03,
                    "ws",
                    probes.GENERATION_1,
                    probes.STATUS_INITIALIZED,
                )

            hardlink = root / "hardlink.sav"
            os.link(original, hardlink)
            with self.assertRaisesRegex(ValueError, "must not be hard-linked"):
                verifier.verify_save(
                    hardlink,
                    0x03,
                    "ws",
                    probes.GENERATION_1,
                    probes.STATUS_INITIALIZED,
                )

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFO unavailable")
    def test_rejects_special_file_without_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fifo = Path(directory) / "save.fifo"
            os.mkfifo(fifo)
            with self.assertRaisesRegex(ValueError, "must be a regular file"):
                verifier.verify_save(
                    fifo,
                    0x03,
                    "ws",
                    probes.GENERATION_1,
                    probes.STATUS_INITIALIZED,
                )


if __name__ == "__main__":
    unittest.main()
